#!/usr/bin/env python3
"""MCSR Ranked のランク戦のデータを集めて蓄積する(標準ライブラリのみ・管理者権限不要)。
  python collect.py probe                  # APIの応答の形を確かめる(2リクエスト)
  python collect.py fetch [--minutes 25]   # 何度でも再実行OK(続きから再開)
  python collect.py build [--days 14]      # 古い試合を数値だけ(走者は番号)の archive に移し、finishers.json / meta.json を生成

2段階の抽出:
  ①一覧(1リクエストで100試合)を新しい順にたどり、試合を「層」に分ける。
    層 = シーズン × 実力帯(試合前Eloの低い方) × スタート形態 × バスチオン × 途中棄権かどうか
  ②層ごとに「1日あたり約 C 試合」になるよう確率 p を決め、当たった試合だけ詳細(区間タイム)を取る。
    小さい層は全部取り、大きい層は間引く。各試合に p を記録し、集計では 1/p を重みにして偏りを補正する。
保存するのは、完走した人だけでなく、その試合の「全員」(完走しなかった人の区間タイム、試合の終了時刻、Elo、リセットを含む)。"""
import json, time, datetime, argparse, urllib.request, urllib.error
from itertools import islice, chain
from pathlib import Path

API = "https://api.mcsrranked.com"
D = Path("data"); A = D / "archive"; A.mkdir(parents=True, exist_ok=True)
RECENT, STATE, RUNNERS = D / "recent.jsonl", D / "state.json", D / "runners.json"
SLEEP = 1.3        # 公式の上限 500 req / 10 min に収まる間隔
MIN_END = 360000   # これより短く終わった試合は、目標タイムの対象外なので取らない(6:00)
C_NEW, C_BACK = 25, 6   # 層ごとの、1日あたりの狙い件数(新しい試合 / 遡る古い試合)
SURVEY, NEW_SHARE = 20, 0.4   # 率を決めるために先に読む一覧のページ数 / 新しい試合に使う時間の割合
EV = {"nether": "story.enter_the_nether", "bastion": "nether.find_bastion",
      "fortress": "nether.find_fortress", "rod": "nether.obtain_blaze_rod",
      "blind": "projectelo.timeline.blind_travel", "stronghold": "story.follow_ender_eye",
      "end": "story.enter_the_end", "dragon": "projectelo.timeline.dragon_death"}
KEYS = list(EV)
IDX = {v: i for i, v in enumerate(EV.values())}
OW = ["BURIED_TREASURE", "SHIPWRECK", "VILLAGE", "RUINED_PORTAL", "DESERT_TEMPLE"]  # index.html と対応
BT = ["BRIDGE", "HOUSING", "STABLES", "TREASURE"]                                  # index.html と対応
# archive の列(1行 = 1人の1回の走り)
#   finish: 完走タイム(完走しなかった人は None)  mend: その試合が終わった時刻(ms)。区間の "end" とは別の列
#   elo: 試合前のElo(changes の eloRate)  elo_pl: 試合後のElo(players の eloRate)  rs: その試合でのリセット回数
#   full: 1=全員分を記録した試合  ff: 途中棄権の試合なら1  win: 勝者なら1(不明は None)
#   bg: ビギナー戦  bot: bot由来  w: 重み(=1/抽出確率)  rl: 区間まで進んでからのリセット [[時刻, 進んだ区間の番号, その区間の時刻],...]
COLS = ["runner_idx", "season", "time", "start", "bastion_type", "finish", "mend", "elo", "elo_pl", "rs",
        "full", "ff", "win", "bg", "bot", "w", "rl", *KEYS]
NOT_IN_JSON = {"rl"}            # finishers.json には入れない列(ページでは使わない)
DEFAULT = {"full": 0, "w": 1.0}  # 旧形式の archive で欠けている列の既定値(それ以外は None)
VER, SVER = 3, 2                 # 記録の形式 / 状態ファイルの形式
RESET = "projectelo.timeline.reset"

def get(path):
    for k in range(5):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "mcsr-ranked-pace/0.6"})
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
    """試合の全員分。[ニックネーム, UUID, 完走タイム|None, 試合前Elo|None, 試合後Elo|None, リセット回数, 区間8つ, リセットの詳細]
    リセットがあった人は、最後のリセット以降のイベントだけを区間として使う(それ以前は別の試走のため)。"""
    comp = {c["uuid"]: c["time"] for c in m.get("completions") or []}
    chg = {c["uuid"]: c for c in m.get("changes") or []}
    out = []
    for p in m["players"]:
        u = p["uuid"]
        evs = sorted((t for t in m.get("timelines") or [] if t["uuid"] == u), key=lambda t: t["time"])
        resets = [t["time"] for t in evs if t["type"] == RESET]
        r0 = resets[-1] if resets else 0
        first = {}
        for t in evs:
            if t["type"] in IDX and t["time"] >= r0:
                first[t["type"]] = min(first.get(t["type"], t["time"]), t["time"])
        rl, prev = [], 0   # 区間のどれかまで進んでからリセットしたものだけ残す(進む前のリセットは回数だけ)
        for rt in resets:
            k, s = -1, None
            for t in evs:
                if prev <= t["time"] < rt and t["type"] in IDX and IDX[t["type"]] > k: k, s = IDX[t["type"]], t["time"]
            if k >= 0: rl.append([rt, k, s])
            prev = rt
        pre = (chg.get(u) or {}).get("eloRate")  # 実データで確認済み: changes の eloRate は試合前、players の eloRate は試合後
        out.append([p["nickname"], u, comp.get(u), pre, p.get("eloRate"), len(resets)]
                   + [first.get(EV[k]) for k in KEYS] + [rl])
    return out

def _pick(d, key, alt, lst):
    v = (d.get("seed") or {}).get(key) or d.get(alt)
    return lst.index(v) if v in lst else -1

def start_of(d): return _pick(d, "overworld", "seedType", OW)
def bastion_of(d): return _pick(d, "nether", "bastionType", BT)

def band_of(elo):
    if elo is None: return 6   # 未ランク
    for i, t in enumerate((600, 900, 1200, 1500, 2000)):
        if elo < t: return i
    return 5

def stratum(m):
    """一覧の1件から、層のキーを作る(詳細は要らない)"""
    pre = [c["eloRate"] for c in m.get("changes") or [] if c.get("eloRate") is not None]
    pl = [p["eloRate"] for p in m.get("players") or [] if p.get("eloRate") is not None]
    e = min(pre) if len(pre) >= 2 else (min(pl) if len(pl) >= 2 else None)
    seed = m.get("seed") or {}
    return (m["season"], band_of(e), m.get("seedType") or seed.get("overworld"),
            m.get("bastionType") or seed.get("nether"), bool(m.get("forfeited")))

def skip_match(m):
    t = (m.get("result") or {}).get("time")
    return bool(m.get("decayed")) or t is None or t < MIN_END

def h01(i): return ((i * 2654435761) & 0xFFFFFFFF) / 4294967296  # 試合IDから決まる 0〜1 の値(再実行しても同じ結果)

def survey_rates(pages, c):
    """先に読んだ一覧から層ごとの件数を数え、1日あたり約 c 試合になる確率を決める"""
    cnt, dates = {}, []
    for pg in pages:
        for m in pg:
            dates.append(m["date"])
            if skip_match(m): continue
            k = stratum(m); cnt[k] = cnt.get(k, 0) + 1
    span = max((max(dates) - min(dates)) / 86400, 0.02) if dates else 0.02
    return {k: min(1.0, c * span / n) for k, n in cnt.items()}, span

def load_seen():
    seen = set()
    if RECENT.exists():
        for l in RECENT.open(encoding="utf-8"):
            m = json.loads(l)
            if m.get("v", 1) >= VER: seen.add(m["id"])
    for p in A.glob("s*.jsonl"):
        for l in p.open(encoding="utf-8"):
            a = json.loads(l)
            if "rs" not in a["runs"]: continue  # 旧形式
            x = 0
            for d in a["ids"]: x += d; seen.add(x)
    return seen

def fetch(minutes):
    t0 = time.time(); end = t0 + minutes * 60
    seen = load_seen()
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if st.get("ver") != SVER: st = {"ver": SVER}  # 状態の形式が変わったら、遡り位置も最初からやり直す
    info, stat = {}, {"pages": 0, "scanned": 0, "taken": 0, "excluded": 0, "rates": []}

    def put(f, m, p):  # m: 一覧の1件(MatchInfo)
        try: d = get(f"/matches/{m['id']}")
        except urllib.error.HTTPError as e: print("skip", m["id"], e.code); return
        res = d.get("result") or {}
        rec = {"v": VER, "id": m["id"], "date": m["date"], "season": m["season"], "p": round(p, 4),
               "ow": start_of(d), "bt": bastion_of(d), "end": res.get("time"), "wu": res.get("uuid"),
               "ff": bool(d.get("forfeited")), "bg": int(bool(d.get("beginner"))),
               "bot": int(d.get("botSource") is not None), "rows": rows(d)}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
        seen.add(m["id"]); stat["taken"] += 1

    def pager(season, cur, until):
        while time.time() < until:
            pg = get("/matches?type=2&count=100" + (f"&season={season}" if season else "")
                     + (f"&before={cur}" if cur else ""))
            if not pg: return
            yield pg
            cur = min(m["id"] for m in pg)

    def scan(f, season, cur, c, until, stop_date=None):
        """一覧を新しい順にたどり、層ごとの確率で詳細を取る。戻り値: (最後に見たID, 終端/前回の位置に届いたか)"""
        gen = pager(season, cur, until)
        first = list(islice(gen, SURVEY))
        if not first: return cur, True
        rates, span = survey_rates(first, c)
        stat["rates"].append((len(rates), round(min(rates.values()), 3) if rates else 1, round(span, 2)))
        if season is None:
            info.setdefault("season", first[0][0]["season"])
            info.setdefault("newest", max(m["date"] for m in first[0]))
        last = cur
        for pg in chain(first, gen):
            stat["pages"] += 1
            for m in pg:
                if time.time() >= until: return last, False
                last = m["id"]
                if stop_date is not None and m["date"] < stop_date: return last, True
                if skip_match(m): stat["excluded"] += 1; continue
                stat["scanned"] += 1
                if m["id"] in seen: continue
                p = rates.get(stratum(m), 1.0)
                if h01(m["id"]) < p: put(f, m, p)
        return last, True

    try:
        with RECENT.open("a", encoding="utf-8") as f:
            lo, reached = scan(f, None, None, C_NEW, t0 + (end - t0) * NEW_SHARE, st.get("t_last"))  # ① 新しい試合
            cs = info.get("season", st.get("cur", 0)); st["cur"] = cs
            if "newest" in info: st["t_last"] = info["newest"]
            if not st.get("back") and not st.get("done"): st["back"] = {"season": cs, "lo": lo}
            b = st.get("back")
            while b and time.time() < end:                # ② 古い試合を遡る
                lo2, done = scan(f, b["season"], b["lo"], C_BACK, end)
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
    print(f"一覧 {stat['pages']} ページ・{stat['scanned']} 試合を見て、{stat['taken']} 試合の詳細を取得(累計 {len(seen)})"
          f" / 対象外 {stat['excluded']} 試合 / 層の数・最小の確率・一覧の期間(日): {stat['rates']} / 遡り位置: {st.get('back')}")

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

    def vals(m, row):  # COLS の順に並べた値(m は VER 以上の記録だけ)
        nick, uuid, fin, pre, pl, rs, *sp = row
        rl = sp[8] if len(sp) > 8 else None; sp = sp[:8]
        wu, ff = m.get("wu"), int(bool(m.get("ff")))
        if wu: win = int(uuid == wu)
        elif not ff: win = int(fin is not None)  # 通常の決着では、勝者=完走した人
        else: win = None
        p = m.get("p"); w = round(1 / p, 4) if p else 1.0
        return [rid(runners, uuid, nick, m["date"]), m["season"], m["date"], m["ow"], m.get("bt", -1), fin,
                m.get("end"), pre, pl, rs, 1, ff, win, m.get("bg", 0), m.get("bot", 0), w, rl, *sp]

    keep, arch, R = [], {}, {c: [] for c in COLS}
    stat = {"matches": 0, "multi_finish": 0, "no_finish": 0, "ff": 0, "old": 0}
    if RECENT.exists():
        for l in RECENT.open(encoding="utf-8"):
            m = json.loads(l)
            if m.get("v", 1) < VER:
                stat["old"] += 1; continue  # 旧形式は捨てる(再取得される)
            if m["rows"]:
                stat["matches"] += 1
                k = sum(1 for r in m["rows"] if r[2] is not None)
                stat["multi_finish"] += k >= 2; stat["no_finish"] += k == 0; stat["ff"] += bool(m.get("ff"))
            if m["date"] >= cutoff:
                keep.append(l if l.endswith("\n") else l + "\n"); continue
            g = arch.setdefault(m["season"], {"ids": [], "runs": {c: [] for c in COLS}})
            g["ids"].append(m["id"])
            for row in m["rows"]:
                for c, v in zip(COLS, vals(m, row)): g["runs"][c].append(v)
        for sn, g in arch.items():  # 追記のみ(数値だけ・ID は差分符号化)
            ids = sorted(g["ids"]); delta = [ids[0]] + [b - a for a, b in zip(ids, ids[1:])]
            with (A / f"s{sn}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ids": delta, "runs": g["runs"]}) + "\n")
        RECENT.write_text("".join(keep), encoding="utf-8")
    for p in sorted(A.glob("s*.jsonl")):
        for l in p.open(encoding="utf-8"):
            runs = json.loads(l)["runs"]; k = len(runs["finish"])
            if "rs" not in runs: continue  # 旧形式の archive は使わない
            for c in COLS: R[c].extend(runs.get(c, [DEFAULT.get(c)] * k))
    for l in keep:
        m = json.loads(l)
        for row in m["rows"]:
            for c, v in zip(COLS, vals(m, row)): R[c].append(v)
    ordered = sorted(runners.items(), key=lambda kv: kv[1][0])
    RUNNERS.write_text(json.dumps([[r[1], u, r[2]] for u, r in ordered], ensure_ascii=False), encoding="utf-8")
    out = {c: v for c, v in R.items() if c not in NOT_IN_JSON}
    (D / "finishers.json").write_text(json.dumps({"schema_version": 7, "runners": [[r[1], u] for u, r in ordered], "runs": out}, ensure_ascii=False))
    fin = sum(v is not None for v in R["finish"])
    (D / "meta.json").write_text(json.dumps({"schema_version": 7, "runs": len(R["finish"]), "finishers": fin,
        "record_ms": record(), "snapshot_date": datetime.date.today().isoformat()}))
    bys = {}
    for sn, w in zip(R["season"], R["w"]): bys[sn] = bys.get(sn, 0) + 1
    print(f"{len(R['finish'])} 走り(うち完走 {fin}) / 走者 {len(runners)} 人 / シーズン別:", dict(sorted(bys.items())),
          "/ 重みの合計(推定される実際の走り数):", round(sum(R["w"])),
          "/ 区間ごとの取得数:", {k: sum(v is not None for v in R[k]) for k in KEYS},
          "/ スタート形態:", {o: R["start"].count(i) for i, o in enumerate(OW)},
          "/ バスチオン:", {o: R["bastion_type"].count(i) for i, o in enumerate(BT)},
          "/ 直近の試合: 完走者2人以上", stat["multi_finish"], "・完走者0人", stat["no_finish"], "(うち途中棄権", stat["ff"], ")・全", stat["matches"], "/ 旧形式で捨てた試合", stat["old"])

def probe():
    """APIの応答の形を確かめる(2リクエストだけ)。結果はそのまま貼って共有できる(UUIDは先頭6文字だけ)。"""
    sh = lambda u: (u or "")[:6]
    lst = get("/matches?type=2&count=20")
    print(f"[probe] 一覧: {len(lst)}件 / 先頭のキー: {sorted(lst[0].keys())}")
    f = sum(1 for m in lst if m.get("forfeited"))
    print(f"[probe] 一覧の途中棄権: {f}/{len(lst)} / 先頭の result: {lst[0].get('result') and {**lst[0]['result'], 'uuid': sh(lst[0]['result'].get('uuid'))}} / seedType: {lst[0].get('seedType')} / bastionType: {lst[0].get('bastionType')} / 層: {stratum(lst[0])}")
    print(f"[probe] 一覧のElo: {[p.get('eloRate') for p in lst[0]['players']]} / changes: {[(sh(c['uuid']), c.get('change'), c.get('eloRate')) for c in lst[0].get('changes', [])]}")
    m = next((x for x in lst if not x.get("forfeited")), lst[0])
    d = get(f"/matches/{m['id']}")
    print(f"[probe] 詳細(id={d['id']}): season={d['season']} date={d['date']} result={d['result'] and {**d['result'], 'uuid': sh(d['result'].get('uuid'))}} forfeited={d['forfeited']} players={len(d['players'])} 完走者={len(d.get('completions') or [])} timelines={len(d.get('timelines') or [])}")
    info = {}
    for t in d.get("timelines") or []:
        x = info.setdefault(sh(t["uuid"]), {"reset": [], "seen": {}})
        if t["type"] == RESET: x["reset"].append(t["time"])
        x["seen"][t["type"]] = x["seen"].get(t["type"], 0) + 1
    for u, x in info.items(): x["dup"] = {k: v for k, v in x.pop("seen").items() if v >= 2}
    print("[probe] 詳細: リセット時刻と、同じイベントが2回以上ある種類:", info)
    r = rows(d)
    print("[probe] 詳細: 区間に直した結果(試合前Elo, 試合後Elo, リセット回数, 区間8つ, リセット詳細):", [[sh(x[1])] + x[3:] for x in r])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "build", "probe"])
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    {"fetch": lambda: fetch(a.minutes), "build": lambda: build(a.days), "probe": probe}[a.cmd]()
