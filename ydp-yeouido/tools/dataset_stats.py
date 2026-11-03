"""데이터셋 전체 통계 — data/*.npz, data/multi/*.npz 의 파일·정책·결과별 집계.

    python tools/dataset_stats.py
결과: results/analysis/dataset_stats.json (+ 표 출력)

에피소드 id는 run(파일명의 `_w*_p*` 앞부분) 안에서만 고유하므로 (run, episode)로 센다.
"""
import collections
import glob
import json
import os
import re

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_name(path):
    return re.sub(r"_w\d+_p\d+$", "", os.path.splitext(os.path.basename(path))[0])


def main():
    groups = {
        "ppo_single": [os.path.join(BASE, "data", f) for f in ("ydp_ppo_final.npz", "ydp_ppo_bulk_01.npz")],
        "ppo_multi": sorted(glob.glob(os.path.join(BASE, "data", "multi", "*.npz"))),
        "expert": [os.path.join(BASE, "data", "expert_train.npz")],
    }
    out, runs = {}, collections.defaultdict(lambda: collections.Counter())
    for g, paths in groups.items():
        c = collections.Counter()
        route_steps = collections.Counter()
        nav_hist = collections.Counter()
        for p in paths:
            if not os.path.exists(p):
                continue
            with np.load(p) as d:
                ep = d["episode"]
                n = len(ep)
                last = np.r_[ep[1:] != ep[:-1], True]           # 에피소드 마지막 step
                coll = d["collided"][last]
                arr = d["arrived"][last]
                term = d["terminated"][last]
                trunc = d["truncated"][last]
                stuck = term & ~coll & ~arr
                names = [str(x) for x in d["route_names"]]
                for ri, k in zip(*np.unique(d["route_index"], return_counts=True)):
                    route_steps[names[ri]] += int(k)
                if "n_av" in d.files:
                    for v, k in zip(*np.unique(d["n_av"], return_counts=True)):
                        nav_hist[int(v)] += int(k)
                sh = int(d["shield"].sum())
            r = run_name(p)
            for cc in (c, runs[(g, r)]):
                cc["files"] += 1
                cc["transitions"] += n
                cc["episodes"] += int(last.sum())
                cc["collisions"] += int(coll.sum())
                cc["arrivals"] += int(arr.sum())
                cc["stuck"] += int(stuck.sum())
                cc["timeouts"] += int((trunc & ~coll & ~arr).sum())
                cc["shield_steps"] += sh
        e = max(c["episodes"], 1)
        out[g] = {**c, "collision_rate": c["collisions"] / e, "arrival_rate": c["arrivals"] / e,
                  "stuck_rate": c["stuck"] / e, "shield_rate": c["shield_steps"] / max(c["transitions"], 1),
                  "route_transitions": dict(route_steps),
                  **({"n_av_hist": {str(k): v for k, v in sorted(nav_hist.items())}} if nav_hist else {})}
    ppo = out["ppo_single"]["transitions"] + out["ppo_multi"]["transitions"]
    out["total"] = {"ppo_transitions": ppo, "all_transitions": ppo + out["expert"]["transitions"],
                    "ppo_episodes": out["ppo_single"]["episodes"] + out["ppo_multi"]["episodes"],
                    "goal_1e7_reached": ppo >= 10_000_000}
    out["runs"] = {f"{g}/{r}": dict(c) for (g, r), c in sorted(runs.items())}
    p = os.path.join(BASE, "results", "analysis", "dataset_stats.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{'그룹':12s} {'파일':>5s} {'transitions':>12s} {'에피소드':>8s} {'충돌':>6s} {'도착':>7s} {'교착':>6s}")
    for g in groups:
        c = out[g]
        print(f"{g:12s} {c['files']:5d} {c['transitions']:12,d} {c['episodes']:8,d} "
              f"{c['collision_rate']:6.2%} {c['arrival_rate']:7.2%} {c['stuck_rate']:6.2%}")
    print("PPO 합계", f"{ppo:,}", "· 10^7 달성" if ppo >= 10_000_000 else "· 10^7 미달")
    print("저장:", p)


if __name__ == "__main__":
    main()
