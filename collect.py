#!/usr/bin/env python3
"""MCSR Ranked のランク戦から完走データを集めて data/finishers.json を作る(標準ライブラリのみ)。
  python collect.py fetch [--minutes 25] [--months 3]   # 何度でも再実行OK。新しい試合→古い試合の順に追加
  python collect.py build [--months 3]                  # finishers.json / meta.json を生成(古い分は削除)"""
import json, time, datetime, argparse, urllib.request, urllib.error
from pathlib import Path

API = "https://api.mcsrranked.com"
D = Path("data"); D.mkdir(exist_ok=True)
CACHE = D / "matches.jsonl"
SLEEP = 1.3  # 公式の上限 500 req / 10 min に収まる間隔
EV = {"nether": "story.enter_the_nether", "bastion": "nether.find_bastion",
      "fortress": "nether.find_fortress", "rod": "nether.obtain_blaze_rod",
      "blind": "projectelo.timeline.blind_travel", "stronghold": "story.follow_ender_eye",
      "end": "story.enter_the_end", "dragon": "projectelo.timeline.dragon_death"}
KEYS = list(EV)  # finish は completions の時間
# スタート形態(seed.overworld)。番号は index.html のセレクトと対応
OW = ["BURIED_TREASURE", "SHIPWRECK", "VILLAGE", "RUINED_PORTAL", "DESERT_TEMPLE"]

def get(path):
    while True:
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "mcsr-ranked-pace/0.3"})
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.load(r)
            time.sleep(SLEEP)
            return j["data"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("429: 60秒待機", flush=True); time.sleep(60); continue
            raise

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

def fetch(minutes, months):
    cut = time.time() - months * 30 * 86400
    seen = {}
    if CACHE.exists():
        for l in CACHE.open(encoding="utf-8"):
            m = json.loads(l); seen[m["id"]] = m["date"]
    end, added, cur, newmode = time.time() + minutes * 60, 0, None, True
    with CACHE.open("a", encoding="utf-8") as f:
        while time.time() < end:
            page = get("/matches?type=2&count=100" + (f"&before={cur}" if cur else ""))
            if not page: break
            todo = [m for m in page if m["id"] not in seen]
            if newmode and not todo:  # 既知の範囲に到達 → 取得済みの最古より前へジャンプ
                newmode, cur = False, min(seen); continue
            for m in todo:
                if time.time() >= end: break
                skip = m.get("forfeited") or m.get("decayed") or m["date"] < cut
                d = None if skip else get(f"/matches/{m['id']}")
                rec = {"id": m["id"], "date": m["date"], "ow": -1 if skip else start_of(d),
                       "rows": [] if skip else rows(d)}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush(); seen[m["id"]] = m["date"]; added += 1
            else:
                if min(m["date"] for m in page) < cut: break
                cur = min(m["id"] for m in page); continue
            break
    print(f"{added} 試合を追加(累計 {len(seen)})")

def record():
    """現時点の最速タイム(全シーズン)。取得できなければ None"""
    try:
        return min(e["time"] for e in get("/record-leaderboard?distinct=true"))
    except Exception as e:
        print("最速タイムの取得に失敗:", e); return None

def build(months):
    cut = time.time() - months * 30 * 86400 if months else 0
    runners, keep = {}, []
    R = {k: [] for k in ["runner_idx", *KEYS, "finish", "time", "start"]}
    for l in CACHE.open(encoding="utf-8"):
        m = json.loads(l)
        if m["date"] < cut: continue
        keep.append(l if l.endswith("\n") else l + "\n")
        for nick, uuid, fin, *sp in m["rows"]:
            i = runners.setdefault(uuid, (len(runners), nick))[0]
            R["runner_idx"].append(i); R["finish"].append(fin)
            R["time"].append(m["date"]); R["start"].append(m["ow"])
            for k, v in zip(KEYS, sp): R[k].append(v)
    CACHE.write_text("".join(keep), encoding="utf-8")
    names = [None] * len(runners)
    for u, (i, n) in runners.items(): names[i] = [n, u]
    (D / "finishers.json").write_text(json.dumps({"schema_version": 3, "runners": names, "runs": R}))
    (D / "meta.json").write_text(json.dumps({"schema_version": 3, "runs": len(R["finish"]),
        "record_ms": record(), "snapshot_date": datetime.date.today().isoformat()}))
    print(f"{len(R['finish'])} 完走を書き出し / 区間ごとの取得数:",
          {k: sum(v is not None for v in R[k]) for k in KEYS},
          "/ スタート形態:", {o: R["start"].count(i) for i, o in enumerate(OW)})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build"])
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--months", type=int, default=3)
    a = ap.parse_args()
    fetch(a.minutes, a.months) if a.cmd == "fetch" else build(a.months)
