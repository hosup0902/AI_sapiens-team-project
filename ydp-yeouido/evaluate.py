"""정책 평가 — 충돌률 / 완주율 / 교착률 / 주행 지표 (평가 기준 6_Project_Evaluation.md).

    python evaluate.py --policy expert --episodes 100 --workers 4
    python evaluate.py --model results/ppo_final/model.pt --episodes 100 --workers 4
    python evaluate.py --model results/ppo_final/model.pt --episodes 100 --no-shield   # 안전 필터 없이

7개 OD 경로를 순서대로 돌려 경로별 표본 수를 맞추고, 정책끼리 비교할 수 있게
에피소드 i는 항상 같은 (교통 스냅샷, 시드, 경로)에서 시작한다.
충돌률 = 충돌로 끝난 에피소드 / 전체 에피소드 (평가 기준 정의 그대로)
"""
import argparse
import json
import multiprocessing
import os
import time

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))


def load_policy(args, env):
    if args.policy == "expert":
        from expert_policy import ExpertPolicy
        return ExpertPolicy()
    if args.policy == "td3bc":
        from algorithms.td3bc import TD3BC
        m = TD3BC.load(args.model)

        class _TD3BC:
            def predict(self, o, deterministic=True):
                return np.clip(m.predict(o), -1, 1)
        return _TD3BC()
    if args.policy == "bc":
        from algorithms.bc import BCPolicy
        m = BCPolicy.load(args.model)

        class _BC:
            def predict(self, o, deterministic=True):
                return np.clip(m.predict(o), -1, 1)
        return _BC()
    from algorithms.ppo import PPO
    from train import HPARAMS
    agent = PPO(obs_dim=env.observation_space.shape[0], act_dim=env.action_space.shape[0],
                **{**HPARAMS, "device": "cpu"})
    agent.load(args.model)
    agent.policy.eval()
    return agent


def run_worker(args, episodes, wid):
    import torch
    torch.set_num_threads(1)
    from train import make_env
    env = make_env(seed=777 + wid, route_mode="cycle", shield=not args.no_shield, fixed_route=args.fixed_route)
    pol = load_policy(args, env)
    rows = []
    try:
        parent = os.getppid()
        for ep in episodes:
            if os.getppid() != parent:          # 부모 프로세스가 종료되면 함께 종료
                break
            env._route_cursor = ep
            obs, info = env.reset(seed=args.seed * 100003 + ep)
            done, n, ret = False, 0, 0.0
            speeds, gaps, shield, lc = [], [], 0, 0
            t0 = env.T.simulation.getTime()
            visited = set()
            while not done:
                a = pol.predict(obs, deterministic=True)
                obs, r, term, trunc, inf = env.step(a)
                done = term or trunc
                if env.ego_id in env.T.vehicle.getIDList():
                    visited.add(env.T.vehicle.getRoadID(env.ego_id))
                n += 1
                ret += r
                shield += int(inf["shield"])
                lc += int(inf["lane_change"] != 0 and inf["lane_change_applied"])
                if inf["speed"] is not None:
                    speeds.append(inf["speed"])
                if inf["gap"] is not None:
                    gaps.append(inf["gap"])
            outcome = "collision" if inf["collided"] else "arrived" if inf["arrived"] else \
                "stuck" if inf["stuck"] else "timeout"
            rows.append({"episode": ep, "route": info["route"], "outcome": outcome, "steps": n,
                         "travel_time_s": n * env.step_length, "return": ret,
                         "mean_speed_kmh": 3.6 * float(np.mean(speeds)) if speeds else 0.0,
                         "min_gap_m": float(np.min(gaps)) if gaps else None,
                         "shield_rate": shield / max(n, 1), "lane_changes": lc,
                         "progress": float(inf["progress"] or 0), "start_time": t0,
                         "collision_info": inf.get("collision_info"),
                         # 설계 경로(av_routes.json) 엣지 중 실제로 지나간 비율 (동적 재경로 시 1 미만 가능)
                         "route_match": len(visited & set(env.routes[info["route"]]["edges"]))
                         / len(env.routes[info["route"]]["edges"])})
            if inf.get("collision_info"):
                print(f"[w{wid}]   충돌 상세: {inf['collision_info']}", flush=True)
            print(f"[w{wid}] ep {ep:3d} {info['route']:22s} {outcome:9s} {n * env.step_length:6.0f}s "
                  f"{rows[-1]['mean_speed_kmh']:5.1f} km/h shield {rows[-1]['shield_rate']:.1%}", flush=True)
    finally:
        env.close()
    return rows


def summarize(rows):
    n = len(rows)
    out = {k: sum(r["outcome"] == k for r in rows) / n for k in ("collision", "arrived", "stuck", "timeout")}
    out = {"episodes": n, "collision_rate": out["collision"], "success_rate": out["arrived"],
           "stuck_rate": out["stuck"], "timeout_rate": out["timeout"]}
    ok = [r for r in rows if r["outcome"] == "arrived"]
    out["mean_travel_time_s"] = float(np.mean([r["travel_time_s"] for r in ok])) if ok else None
    out["mean_speed_kmh"] = float(np.mean([r["mean_speed_kmh"] for r in rows]))
    gaps = [r["min_gap_m"] for r in rows if r["min_gap_m"] is not None]
    out["min_gap_m_median"] = float(np.median(gaps)) if gaps else None
    out["shield_rate"] = float(np.mean([r["shield_rate"] for r in rows]))
    out["lane_changes_per_ep"] = float(np.mean([r["lane_changes"] for r in rows]))
    out["mean_return"] = float(np.mean([r["return"] for r in rows]))
    rm = [r["route_match"] for r in rows if r.get("route_match") is not None and r["outcome"] == "arrived"]
    out["route_match_arrived"] = float(np.mean(rm)) if rm else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=["expert", "bc", "ppo", "td3bc"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-shield", action="store_true")
    ap.add_argument("--fixed-route", action="store_true", help="AV 동적 재경로 끄기 (설계 경로 그대로)")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.policy is None:
        if not a.model:
            ap.error("--policy 또는 --model 필요")
        from collect_pomdp_data import detect_algorithm
        a.policy = detect_algorithm(a.model)
    from env.mdp_config import SIMULATION
    from env.sumo_env import ensure_snapshots
    ensure_snapshots(SIMULATION["snapshot_times"], SIMULATION["step_length"])

    t0 = time.time()
    eps = list(range(a.episodes))
    w = max(1, min(a.workers, a.episodes))
    chunks = [c.tolist() for c in np.array_split(np.arange(a.episodes), w)]
    if w == 1:
        rows = run_worker(a, eps, 0)
    else:
        with multiprocessing.get_context("spawn").Pool(w) as pool:
            rows = sum(pool.starmap(run_worker, [(a, chunks[i], i) for i in range(w)]), [])
    rows.sort(key=lambda r: r["episode"])
    summ = summarize(rows)
    per_route = {}
    for rid in sorted({r["route"] for r in rows}):
        per_route[rid] = summarize([r for r in rows if r["route"] == rid])
    tag = a.policy + ("" if not a.model else "_" + os.path.basename(os.path.dirname(a.model))) + \
        ("_noshield" if a.no_shield else "") + ("_fixed" if a.fixed_route else "")
    out = a.out or os.path.join(BASE, "results", f"eval_{tag}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"policy": a.policy, "model": a.model, "shield": not a.no_shield,
                   "summary": summ, "per_route": per_route, "episodes": rows}, f, ensure_ascii=False, indent=1)
    print(f"\n─── {a.policy} {'(shield off)' if a.no_shield else ''} · {a.episodes} 에피소드 ({time.time() - t0:.0f}s) ───")
    print(f"  충돌률 {summ['collision_rate']:.1%} · 완주율 {summ['success_rate']:.1%} · "
          f"교착 {summ['stuck_rate']:.1%} · 시간초과 {summ['timeout_rate']:.1%}")
    print(f"  평균 통행시간 {summ['mean_travel_time_s'] or 0:.0f}s · 평균속도 {summ['mean_speed_kmh']:.1f} km/h · "
          f"안전필터 개입 {summ['shield_rate']:.2%} · 차선변경 {summ['lane_changes_per_ep']:.1f}회/ep · "
          f"설계경로 일치율(완주) {summ['route_match_arrived'] or 0:.1%}")
    for rid, s in per_route.items():
        print(f"    {rid:22s} n={s['episodes']:3d} 충돌 {s['collision_rate']:.0%} 완주 {s['success_rate']:.0%} "
              f"통행 {s['mean_travel_time_s'] or 0:5.0f}s")
    print(f"  저장: {out}")


if __name__ == "__main__":
    main()
