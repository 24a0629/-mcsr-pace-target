#!/usr/bin/env python3
"""MCSR Ranked のランク戦から完走データを集めて蓄積する(標準ライブラリのみ・管理者権限不要)。
  python collect.py fetch [--minutes 25]   # 何度でも再実行OK(続きから再開)
  python collect.py build [--days 14]      # 古い試合を数値だけ(走者は番号)の archive に移し、finishers.json / meta.json を生成
収集の優先順: ①最新の試合(既知の範囲まで) → ②古い試合を新しい順に遡る(シーズンをまたいで続きから再開)"""
import json, time, datetime, argparse, urllib.request, urllib.error
from pathlib import Path

API = "https://api.mcsrranked.com"
D = Path("data"); A = D / "archive"; A.mkdir(parents=True, exist_ok=True)
RECENT, STATE = D / "recent.jsonl", D / "state.json"
SLEEP = 1.3  # 公式の上限 500 req / 10 min に収まる間隔
EV = {"nether": "story.enter_the_nether", "bastion": "nether.find_bastion",
      "fortress": "nether.find_fortress", "rod": "nether.obtain_blaze_rod",
      "blind": "projectelo.timeline.blind_travel", "stronghold": "story.follow_ender_eye",
      "end": "story.enter_the_end", "dragon": "projectelo.timeline.dragon_death"}
KEYS = list(EV)  # finish は completions の時間
OW = ["BURIED_TREASURE", "SHIPWRECK", "VILLAGE", "RUINED_PORTAL", "DESERT_TEMPLE"]  # index.html と対応
BT = ["BRIDGE", "HOUSING", "STABLES", "TREASURE"]                                  # index.html と対応
COLS = ["runner_idx", "season", "time", "start", "bastion_type", "finish", *KEYS]  # archive に残す数値列(走者は番号だけ)
RUNNERS = D / "runners.json"  # 走者番号 → [ニックネーム, UUID, 最終試合日]

def get(path):
    for k in range(5):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "mcsr-ranked-pace/0.4"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
            time.sleep(SLEEP)
            return j["data"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("429: 60秒待機", flush=True); time.sleep(60); continue
            if e.code >= 500:
                time.sleep(5 * (k + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(5 * (k + 1))
    raise RuntimeError("API error: " + path)

def rows(m):
    names = {p["uuid"]: p["nickname"] for p in m["players"]}
    out = []
    for c in m.get("completions") or []:
        u, first = c["uuid"], {}
        for t in m.get("timelines") or []:
            if t["uuid"] == u and t["type"] in EV.values():
                first[t["type"]] = min(first.get(t["type"], t["time"]), t["time"])
        out.append([names.get(u, "?"), u, c["time"]] + [first.get(EV[k]) for k in KEYS])
    return out

def start_of(m):
    v = (m.get("seed") or {}).get("overworld")
    return OW.index(v) if v in OW else -1

def bastion_of(m):
    v = (m.get("seed") or {}).get("nether")
    return BT.index(v) if v in BT else -1

def load_seen():
    seen = set()
    if RECENT.exists():
        for l in RECENT.open(encoding="utf-8"): seen.add(json.loads(l)["id"])
    for p in A.glob("s*.jsonl"):
        for l in p.open(encoding="utf-8"):
            x = 0
            for d in json.loads(l)["ids"]: x += d; seen.add(x)
    return seen

def fetch(minutes):
    end = time.time() + minutes * 60
    seen = load_seen()
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    n, info = [0], {}

    def put(f, m):
        skip = m.get("forfeited") or m.get("decayed")
        d = None
        if not skip:
            try: d = get(f"/matches/{m['id']}")
            except urllib.error.HTTPError as e: print("skip", m["id"], e.code); skip = True
        rec = {"id": m["id"], "date": m["date"], "season": m["season"],
               "ow": -1 if skip else start_of(d), "bt": -1 if skip else bastion_of(d),
               "rows": [] if skip else rows(d)}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
        seen.add(m["id"]); n[0] += 1

    def walk(f, season, cur, stop_on_seen):  # 新しい順に辿る。戻り値: (最後に処理したID, 終端/既知範囲に到達したか)
        last = cur
        while time.time() < end:
            page = get("/matches?type=2&count=100" + (f"&season={season}" if season else "")
                       + (f"&before={cur}" if cur else ""))
            if not page: return last, True
            if season is None and "season" not in info: info["season"] = page[0]["season"]
            todo = [m for m in page if m["id"] not in seen]
            if stop_on_seen and not todo: return last, True
            for m in todo:
                if time.time() >= end: return last, False
                put(f, m); last = m["id"]
            cur = last = min(m["id"] for m in page)
        return last, False

    try:
        with RECENT.open("a", encoding="utf-8") as f:
            lo, _ = walk(f, None, None, True)             # ① 最新の試合
            cs = info.get("season", st.get("cur", 0)); st["cur"] = cs
            if not st.get("back") and not st.get("done"):
                st["back"] = {"season": cs, "lo": lo}
            b = st.get("back")
            while b and time.time() < end:                # ② 古い試合を遡る
                lo2, done = walk(f, b["season"], b["lo"], False)
                if done:
                    b = {"season": b["season"] - 1, "lo": None} if b["season"] > 1 else None
                    if b is None: st["done"] = True
                else:
                    b["lo"] = lo2
            st["back"] = b
    except Exception as e:
        print("中断:", repr(e))
    finally:
        STATE.write_text(json.dumps(st))
    print(f"{n[0]} 試合を追加(累計 {len(seen)}) / 遡り位置: {st.get('back')}")

def record():
    try: return min(e["time"] for e in get("/record-leaderboard"))
    except Exception as e: print("最速タイムの取得に失敗:", e); return None

def rid(runners, uuid, nick, date):
    r = runners.get(uuid)
    if r is None: r = runners[uuid] = [len(runners), nick, date]
    elif date > r[2]: r[1], r[2] = nick, date  # ニックネームは最新の試合のものに更新
    return r[0]

def build(days):
    cutoff = time.time() - days * 86400
    runners = {}
    if RUNNERS.exists():
        for i, (nk, u, d) in enumerate(json.loads(RUNNERS.read_text(encoding="utf-8"))): runners[u] = [i, nk, d]
    def vals(m, nick, uuid, fin, sp):
        return [rid(runners, uuid, nick, m["date"]), m["season"], m["date"], m["ow"], m.get("bt", -1), fin, *sp]
    keep, arch, R = [], {}, {c: [] for c in COLS}
    if RECENT.exists():
        for l in RECENT.open(encoding="utf-8"):
            m = json.loads(l)
            if m["date"] >= cutoff:
                keep.append(l if l.endswith("\n") else l + "\n"); continue
            g = arch.setdefault(m["season"], {"ids": [], "runs": {c: [] for c in COLS}})
            g["ids"].append(m["id"])
            for nick, uuid, fin, *sp in m["rows"]:
                for c, v in zip(COLS, vals(m, nick, uuid, fin, sp)): g["runs"][c].append(v)
        for sn, g in arch.items():  # 追記のみ(数値だけ・ID は差分符号化)
            ids = sorted(g["ids"]); delta = [ids[0]] + [b - a for a, b in zip(ids, ids[1:])]
            with (A / f"s{sn}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ids": delta, "runs": g["runs"]}) + "\n")
        RECENT.write_text("".join(keep), encoding="utf-8")
    for p in sorted(A.glob("s*.jsonl")):
        for l in p.open(encoding="utf-8"):
            runs = json.loads(l)["runs"]; k = len(runs["finish"])
            for c in COLS: R[c].extend(runs.get(c, [-1] * k))  # 旧形式の archive は走者番号なし(-1)
    for l in keep:
        m = json.loads(l)
        for nick, uuid, fin, *sp in m["rows"]:
            for c, v in zip(COLS, vals(m, nick, uuid, fin, sp)): R[c].append(v)
    ordered = sorted(runners.items(), key=lambda kv: kv[1][0])
    RUNNERS.write_text(json.dumps([[r[1], u, r[2]] for u, r in ordered], ensure_ascii=False), encoding="utf-8")
    (D / "finishers.json").write_text(json.dumps({"schema_version": 5, "runners": [[r[1], u] for u, r in ordered], "runs": R}, ensure_ascii=False))
    (D / "meta.json").write_text(json.dumps({"schema_version": 5, "runs": len(R["finish"]),
        "record_ms": record(), "snapshot_date": datetime.date.today().isoformat()}))
    bys = {}
    for sn in R["season"]: bys[sn] = bys.get(sn, 0) + 1
    print(f"{len(R['finish'])} 完走 / 走者 {len(runners)} 人 / シーズン別:", dict(sorted(bys.items())),
          "/ 区間ごとの取得数:", {k: sum(v is not None for v in R[k]) for k in KEYS},
          "/ スタート形態:", {o: R["start"].count(i) for i, o in enumerate(OW)},
          "/ バスチオン:", {o: R["bastion_type"].count(i) for i, o in enumerate(BT)})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build"])
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    fetch(a.minutes) if a.cmd == "fetch" else build(a.days)
