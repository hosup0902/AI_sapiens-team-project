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
        "ppo_multi_v2": sorted(glob.glob(os.path.join(BASE, "data", "multi_v2", "*.npz"))),
        "expert": [os.path.join(BASE, "data", "expert_train.npz")],
    }
    out, runs = {}, collections.defaultdict(lambda: collections.Counter())
    for g, paths in groups.items():
        c = collections.Counter()
        route_steps = collections.Counter()
        nav_hist = collections.Counter()
        longest = []                    # 에피소드별 최장 연속 정지(s)
        stop_red, stop_other = 0, 0     # 정지 step: 적·황색 신호 앞 60 m 이내 / 그 외 (State 있는 파일만)
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
                stopped = d["ego_speed"] < 0.1
                starts = np.r_[0, np.flatnonzero(ep[1:] != ep[:-1]) + 1]
                for a, b in zip(starts, np.r_[starts[1:], len(ep)]):
                    x = np.r_[False, stopped[a:b], False].astype(np.int8)
                    dx = np.diff(x)
                    rl = np.flatnonzero(dx == -1) - np.flatnonzero(dx == 1)
                    longest.append(0.5 * (rl.max() if len(rl) else 0))
                if "state_tls_state" in d.files:
                    red = (d["state_tls_state"] <= 0) & (d["state_tls_state"] > -2) & (d["state_tls_dist"] < 60)
                    stop_red += int((stopped & red).sum())
                    stop_other += int((stopped & ~red).sum())
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
        for k in ("files", "transitions", "episodes", "collisions", "arrivals", "stuck", "timeouts", "shield_steps"):
            c[k] += 0
        e = max(c["episodes"], 1)
        out[g] = {**c, "collision_rate": c["collisions"] / e, "arrival_rate": c["arrivals"] / e,
                  "stuck_rate": c["stuck"] / e, "shield_rate": c["shield_steps"] / max(c["transitions"], 1),
                  "route_transitions": dict(route_steps),
                  **({"longest_stop_s": {"p50": float(np.percentile(longest, 50)), "p95": float(np.percentile(longest, 95)),
                                         "p99": float(np.percentile(longest, 99)),
                                         "episodes_gt_60s": float(np.mean(np.asarray(longest) > 60)),
                                         "episodes_gt_120s": float(np.mean(np.asarray(longest) > 120))}} if longest else {}),
                  **({"stopped_time_pct": 100 * (stop_red + stop_other) / max(c["transitions"], 1),
                      "stopped_at_red_pct_of_stops": 100 * stop_red / max(stop_red + stop_other, 1)}
                     if stop_red + stop_other else {}),
                  **({"n_av_hist": {str(k): v for k, v in sorted(nav_hist.items())}} if nav_hist else {})}
    ppo = out["ppo_single"]["transitions"] + out["ppo_multi"]["transitions"] + out["ppo_multi_v2"]["transitions"]
    out["total"] = {"ppo_transitions": ppo, "all_transitions": ppo + out["expert"]["transitions"],
                    "ppo_episodes": out["ppo_single"]["episodes"] + out["ppo_multi"]["episodes"] + out["ppo_multi_v2"]["episodes"],
                    "v2_transitions": out["ppo_multi_v2"]["transitions"],
                    "goal_1e7_v2_full_columns": out["ppo_multi_v2"]["transitions"] >= 10_000_000,
                    "goal_1e7_reached": ppo >= 10_000_000}
    out["runs"] = {f"{g}/{r}": dict(c) for (g, r), c in sorted(runs.items())}
    p = os.path.join(BASE, "results", "analysis", "dataset_stats.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{'그룹':12s} {'파일':>5s} {'transitions':>12s} {'에피소드':>8s} {'충돌':>6s} {'도착':>7s} {'교착':>6s}")
    for g in groups:
        c = out[g]
        print(f"{g:12s} {c['files']:5d} {c['transitions']:12,d} {c['episodes']:8,d} "
              f"{c['collision_rate']:6.2%} {c['arrival_rate']:7.2%} {c['stuck_rate']:6.2%} "
              f"최장정지 p95 {c.get('longest_stop_s', {}).get('p95', 0):.0f}s")
    print("PPO 합계", f"{ppo:,}", "· 10^7 달성" if ppo >= 10_000_000 else "· 10^7 미달")
    print("저장:", p)


if __name__ == "__main__":
    main()
