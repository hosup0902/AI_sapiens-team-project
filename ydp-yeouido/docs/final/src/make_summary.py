"""최종발표 PPT에 들어갈 수치 모음 → summary.json (build.js가 읽음).

    python docs/final/src/make_summary.py
"""
import glob
import json
import os

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
R = os.path.join(BASE, "results")


def ev(name):
    p = os.path.join(R, "final", name)
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    s = d["summary"]
    rows = d["episodes"]
    av_fault = sum(1 for r in rows if r["outcome"] == "collision" and (r.get("collision_info") or {}).get("ego_is_collider"))
    return {**{k: s[k] for k in ("episodes", "collision_rate", "success_rate", "stuck_rate", "timeout_rate",
                                  "mean_travel_time_s", "mean_speed_kmh", "shield_rate")},
            "route_match_arrived": s.get("route_match_arrived"), "av_fault_rate": av_fault / max(len(rows), 1),
            "per_route": {k: {"collision_rate": v["collision_rate"], "success_rate": v["success_rate"],
                              "mean_travel_time_s": v["mean_travel_time_s"]} for k, v in d["per_route"].items()}}


def count(paths):
    n, eps = 0, 0
    for p in paths:
        with np.load(p) as d:
            n += len(d["reward"])
            eps += len(np.unique(d["episode"]))
    return n, eps


def multi_stats():
    """tools/dataset_stats.py 결과 (없으면 빈 값)."""
    p = os.path.join(R, "analysis", "dataset_stats.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    m, v2 = d["ppo_multi"], d.get("ppo_multi_v2", {})
    src = v2 if v2.get("episodes") else m
    return {"multi_collision_rate": src["collision_rate"], "multi_arrival_rate": src["arrival_rate"],
            "multi_stuck_rate": src["stuck_rate"], "longest_stop_s": src.get("longest_stop_s"),
            "expert_longest_stop_s": d["expert"].get("longest_stop_s"),
            "stopped_time_pct": v2.get("stopped_time_pct"), "stopped_at_red_pct_of_stops": v2.get("stopped_at_red_pct_of_stops")}


def main():
    data = os.path.join(BASE, "data")
    ppo_single = [os.path.join(data, f) for f in ("ydp_ppo_final.npz", "ydp_ppo_bulk_01.npz")]
    multi = sorted(glob.glob(os.path.join(data, "multi", "*.npz")))
    v2 = sorted(glob.glob(os.path.join(data, "multi_v2", "*.npz")))
    n_v2, e_v2 = count(v2)
    n_single, e_single = count([p for p in ppo_single if os.path.exists(p)])
    n_multi, e_multi = count(multi)
    n_exp, e_exp = count([os.path.join(data, "expert_train.npz")])
    inter = json.load(open(os.path.join(R, "analysis", "interaction_summary.json"), encoding="utf-8"))
    out = {
        "eval": {k: ev(f) for k, f in {
            "ppo": "eval_ppo.json", "ppo_noshield": "eval_ppo_noshield.json", "ppo_fixed": "eval_ppo_fixed.json",
            "bc": "eval_bc.json", "td3bc": "eval_td3bc.json", "expert": "eval_expert.json"}.items()},
        "data": {"ppo_single": n_single, "ppo_single_eps": e_single, "ppo_multi": n_multi, "ppo_multi_eps": e_multi,
                 "ppo_v2": n_v2, "ppo_v2_eps": e_v2, "v2_files": len(v2),
                 "expert": n_exp, "total": n_single + n_multi + n_v2 + n_exp, "ppo_total": n_single + n_multi + n_v2,
                 "multi_files": len(multi), **multi_stats()},
        "interaction": {k: inter[k] for k in ("mean_per_episode", "ttc_lt4_pct_of_time", "vehicles_within_50m",
                                              "vehicles_within_150m", "nearby_vehicle_types_pct")},
    }
    p = os.path.join(BASE, "docs", "final", "src", "summary.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out["data"], ensure_ascii=False), {k: (v or {}).get("collision_rate") for k, v in out["eval"].items()})


if __name__ == "__main__":
    main()
