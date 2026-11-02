"""POMDP 주행 데이터 수집 — 영등포~여의도 도시망 (수업 collect_pomdp_data.py 확장판).

저장 단위는 POMDP transition 하나:
    (o_t, a_t, r_t, o_{t+1}, terminated, truncated, s_t, s_{t+1})

수업 필수 컬럼 (6_Project_Evaluation.md "기본 데이터 수집 항목") — 전부 그대로 포함
    episode, t, observation, action_raw, action.{accel_raw, lane_change_raw, lane_change,
    lane_change_applied}, reward, terminated, truncated, state, detected_vehicles,
    event.{collided, arrived, lane_before, lane_after}, next_observation, next_state
도시망 추가 컬럼
    route                         AV 과제 경로 id (7개 OD)
    event.stuck / event.shield    교착 종료 여부 / 안전 필터 개입 여부
    event.progress                경로 진행률 (0~1)
    state.* (절대 정보)            ego_x, ego_y, ego_lon, ego_lat, ego_speed, ego_accel, ego_angle,
                                  ego_lane, ego_lane_id, ego_road_id, ego_road_name, speed_limit,
                                  route_progress_m, route_length_m, next_tls_{id,dist,state},
                                  vehicles(반경 150 m 주변 차량: 위치·속도·가속도·방향·차선·타입)
    detected_vehicles[].type      감지 차량의 컨트롤러 (hv_krauss / hv_idm / hv_eidm / hv_acc / bus / truck)

출력
    data/<name>.jsonl.gz   전체 POMDP + privileged state (next_* 는 에피소드 마지막 스텝에만, iter_transitions가 복원)
    data/<name>.npz        학습용 배열: observation / action_raw / lane_change / reward / next_observation /
                           terminated / truncated / episode / t / detected_xy / detected_offsets
                           + route_index / collided / arrived / ego_xy / ego_speed / shield

예시
    python collect_pomdp_data.py --policy expert --episodes 20 --workers 4
    python collect_pomdp_data.py --model results/ppo_final/model.pt --episodes 7000 --workers 8 --no-jsonl-state
    python collect_pomdp_data.py --policy random --episodes 5
"""
import argparse
import gzip
import json
import multiprocessing
import os
import shutil
import time
from datetime import datetime

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))


def detect_algorithm(model_path):
    import torch
    ck = torch.load(model_path, map_location="cpu", weights_only=True)
    return "bc" if isinstance(ck, dict) and ck.get("algorithm") == "bc" else "ppo"


def make_policy(args, env, worker_seed):
    if args.policy == "ppo":
        from algorithms.ppo import PPO
        from train import HPARAMS
        agent = PPO(obs_dim=env.observation_space.shape[0], act_dim=env.action_space.shape[0],
                    **{**HPARAMS, "device": args.device, "seed": worker_seed})
        agent.load(args.model)
        det = not args.stochastic
        return lambda obs: np.clip(agent.predict(obs, deterministic=det), -1, 1).astype(np.float32)
    if args.policy == "bc":
        from algorithms.bc import BCPolicy
        model = BCPolicy.load(args.model, device=args.device)
        return lambda obs: np.clip(model.predict(obs), -1, 1).astype(np.float32)
    if args.policy == "expert":
        from expert_policy import ExpertPolicy
        ex = ExpertPolicy(seed=worker_seed)
        rng = np.random.default_rng(worker_seed)

        def act(obs):
            a = ex.predict(obs)
            if args.expert_noise > 0:      # 상태 분포를 넓히기 위한 소량의 가감속 잡음 (DART식)
                a[0] = np.clip(a[0] + rng.normal(0, args.expert_noise), -1, 1)
            return a
        return act
    if args.policy == "keep-lane":
        return lambda obs: np.asarray([0.25, 0.0], dtype=np.float32)
    rng = np.random.default_rng(worker_seed)
    return lambda obs: np.asarray([rng.uniform(-1, 1), rng.choice([-1.0, 0.0, 1.0], p=[.15, .7, .15])],
                                  dtype=np.float32)


def compact(obj, nd):
    if isinstance(obj, (float, np.floating)):
        return round(float(obj), nd)
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return compact(obj.tolist(), nd)
    if isinstance(obj, dict):
        return {k: compact(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [compact(v, nd) for v in obj]
    return obj


def iter_transitions(jsonl_path):
    """JSONL을 읽어 생략된 next_observation / next_state를 다음 레코드에서 채워 yield."""
    opener = gzip.open if jsonl_path.endswith(".gz") else open
    with opener(jsonl_path, "rt", encoding="utf-8") as f:
        prev = None
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if prev is not None:
                prev.setdefault("next_observation", rec["observation"])
                prev.setdefault("next_state", rec["state"])
                yield prev
            prev = rec
        if prev is not None:
            yield prev


def collect(args, episodes, worker_id, jsonl_path, npz_path, tag=""):
    from env.mdp_config import SIMULATION, OBSERVATION, ACTION, REWARD
    from env.sumo_env import YdpCityEnv
    worker_seed = (args.seed * 1000 + worker_id) % 2 ** 31
    if args.workers > 1:
        try:
            import torch
            torch.set_num_threads(1)
        except ImportError:
            pass
    action = dict(ACTION)
    if args.no_shield:
        action["shield"] = {**ACTION["shield"], "enabled": False}
    env = YdpCityEnv(SIMULATION, OBSERVATION, action, REWARD, gui=args.gui,
                     seed=worker_seed, route_mode="cycle",
                     routes=args.routes.split(",") if args.routes else None)
    route_ids = list(env.route_ids)
    act = make_policy(args, env, worker_seed)

    B = {k: [] for k in ("obs", "nobs", "act", "lane", "rew", "term", "trunc", "ep", "t",
                         "route", "coll", "arr", "xy", "spd", "shield")}
    det_xy, det_off = [], [0]
    total = 0
    stats = {"episodes": 0, "collisions": 0, "arrivals": 0, "stuck": 0}
    try:
        with gzip.open(jsonl_path, "wt", encoding="utf-8", compresslevel=6) as jf:
            parent = os.getppid()
            for ep in episodes:
                if args.workers > 1 and os.getppid() != parent:   # 부모가 죽으면 고아 워커로 남지 않게 종료
                    break
                env._route_cursor = ep          # 에피소드 번호로 경로를 고르게 순환
                obs, info = env.reset(seed=args.seed * 100003 + ep)
                state_t = env.get_privileged_state(args.state_radius)
                done, t, ep_ret = False, 0, 0.0
                while not done:
                    detected = env.get_detected_vehicles()
                    a = act(obs)
                    nobs, r, term, trunc, inf = env.step(a)
                    state_tp1 = env.get_privileged_state(args.state_radius)
                    done = term or trunc
                    if args.jsonl:
                        rec = {
                            "episode": int(ep), "t": t, "route": env.route_id,
                            "observation": compact(obs, args.ndigits),
                            "action_raw": np.asarray(a, dtype=float).tolist(),
                            "action": {"accel_raw": float(inf["accel_raw"]),
                                       "lane_change_raw": float(inf["lane_change_raw"]),
                                       "lane_change": int(inf["lane_change"]),
                                       "lane_change_applied": bool(inf["lane_change_applied"])},
                            "reward": float(r), "terminated": bool(term), "truncated": bool(trunc),
                            "state": compact(state_t, args.ndigits),
                            "detected_vehicles": compact(detected, args.ndigits),
                            "event": {"collided": bool(inf["collided"]), "arrived": bool(inf["arrived"]),
                                      "stuck": bool(inf["stuck"]), "shield": bool(inf["shield"]),
                                      "lane_before": inf["lane_before"], "lane_after": inf["lane_after"],
                                      "progress": None if inf["progress"] is None
                                      else round(float(inf["progress"]), 4)},
                        }
                        if done:
                            rec["next_observation"] = compact(nobs, args.ndigits)
                            rec["next_state"] = compact(state_tp1, args.ndigits)
                        jf.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                    B["obs"].append(np.asarray(obs, np.float32))
                    B["nobs"].append(np.asarray(nobs, np.float32))
                    B["act"].append(np.asarray(a, np.float32))
                    B["lane"].append(int(inf["lane_change"]))
                    B["rew"].append(float(r))
                    B["term"].append(bool(term))
                    B["trunc"].append(bool(trunc))
                    B["ep"].append(int(ep))
                    B["t"].append(t)
                    B["route"].append(route_ids.index(env.route_id))
                    B["coll"].append(bool(inf["collided"]))
                    B["arr"].append(bool(inf["arrived"]))
                    B["xy"].append((state_t.get("ego_x", np.nan), state_t.get("ego_y", np.nan)))
                    B["spd"].append(state_t.get("ego_speed", np.nan))
                    B["shield"].append(bool(inf["shield"]))
                    det_xy.extend((d["x"], d["y"]) for d in detected)
                    det_off.append(len(det_xy))
                    total += 1
                    ep_ret += r
                    t += 1
                    obs, state_t = nobs, state_tp1
                stats["episodes"] += 1
                stats["collisions"] += int(inf["collided"])
                stats["arrivals"] += int(inf["arrived"])
                stats["stuck"] += int(inf["stuck"])
                print(f"{tag}episode {ep + 1:5d}/{args.episodes} | {env.route_id:22s} steps={t:5d} "
                      f"return={ep_ret:8.2f} {'COLLISION' if inf['collided'] else ('arrived' if inf['arrived'] else 'stuck/timeout')}",
                      flush=True)
    finally:
        env.close()
    np.savez_compressed(
        npz_path,
        observation=np.asarray(B["obs"], np.float32).reshape(total, -1),
        action_raw=np.asarray(B["act"], np.float32).reshape(total, -1),
        lane_change=np.asarray(B["lane"], np.int8),
        reward=np.asarray(B["rew"], np.float32),
        next_observation=np.asarray(B["nobs"], np.float32).reshape(total, -1),
        terminated=np.asarray(B["term"], np.bool_),
        truncated=np.asarray(B["trunc"], np.bool_),
        episode=np.asarray(B["ep"], np.int32),
        t=np.asarray(B["t"], np.int32),
        detected_xy=np.asarray(det_xy, np.float32).reshape(-1, 2),
        detected_offsets=np.asarray(det_off, np.int64),
        route_index=np.asarray(B["route"], np.int8),
        route_names=np.asarray(route_ids),
        collided=np.asarray(B["coll"], np.bool_),
        arrived=np.asarray(B["arr"], np.bool_),
        ego_xy=np.asarray(B["xy"], np.float32).reshape(-1, 2),
        ego_speed=np.asarray(B["spd"], np.float32),
        shield=np.asarray(B["shield"], np.bool_),
    )
    return total, stats


def merge_parts(parts, jsonl_path, npz_path):
    with open(jsonl_path, "wb") as out:
        for pj, _ in parts:
            with open(pj, "rb") as f:
                shutil.copyfileobj(f, out)
            os.remove(pj)
    arrays, xy, offs, base = {}, [], [], 0
    names = None
    for _, pn in parts:
        with np.load(pn) as d:
            for k in d.files:
                if k == "route_names":
                    names = d[k]
                elif k not in ("detected_xy", "detected_offsets"):
                    arrays.setdefault(k, []).append(d[k])
            xy.append(d["detected_xy"])
            o = d["detected_offsets"]
            offs.append(o[:-1] + base)
            base += int(o[-1])
        os.remove(pn)
    merged = {k: np.concatenate(v) for k, v in arrays.items()}
    merged["detected_xy"] = np.concatenate(xy).reshape(-1, 2)
    merged["detected_offsets"] = np.concatenate(offs + [np.asarray([base], np.int64)]).astype(np.int64)
    merged["route_names"] = names
    np.savez_compressed(npz_path, **merged)


def main():
    p = argparse.ArgumentParser(description="SUMO 도시망 POMDP 데이터 수집")
    p.add_argument("--episodes", type=int, default=21)
    p.add_argument("--policy", choices=["expert", "random", "keep-lane", "ppo", "bc"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--stochastic", action="store_true")
    p.add_argument("--expert-noise", type=float, default=0.0)
    p.add_argument("--no-shield", action="store_true")
    p.add_argument("--routes", default=None, help="쉼표로 구분한 경로 id (기본: 7개 전부)")
    p.add_argument("--device", default="cpu")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--gui", action="store_true")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out-dir", default=os.path.join(BASE, "data"))
    p.add_argument("--name", default=None)
    p.add_argument("--ndigits", type=int, default=3)
    p.add_argument("--state-radius", type=float, default=150.0, help="privileged state에 넣을 주변 차량 반경 (m)")
    p.add_argument("--no-jsonl", dest="jsonl", action="store_false",
                   help="JSONL(전체 POMDP)을 쓰지 않고 NPZ만 저장 (대용량 수집용)")
    args = p.parse_args()
    if args.policy in ("ppo", "bc") and not args.model:
        p.error("--policy ppo/bc 에는 --model 필요")
    if args.policy is None:
        args.policy = detect_algorithm(args.model) if args.model else "expert"
    workers = 1 if args.gui else max(1, min(args.workers, args.episodes))
    os.makedirs(args.out_dir, exist_ok=True)
    name = args.name or datetime.now().strftime("pomdp_%Y%m%d_%H%M%S")
    jsonl_path = os.path.join(args.out_dir, name + ".jsonl.gz")
    npz_path = os.path.join(args.out_dir, name + ".npz")

    from env.mdp_config import SIMULATION
    from env.sumo_env import ensure_snapshots
    ensure_snapshots(SIMULATION["snapshot_times"], SIMULATION["step_length"])   # 워커 전에 한 번만

    t0 = time.time()
    if workers == 1:
        total, st = collect(args, list(range(args.episodes)), 0, jsonl_path, npz_path)
        stats = [st]
    else:
        chunks = [c.tolist() for c in np.array_split(np.arange(args.episodes), workers)]
        parts = [(os.path.join(args.out_dir, f".{name}.w{w}.jsonl.gz"),
                  os.path.join(args.out_dir, f".{name}.w{w}.npz")) for w in range(workers)]
        jobs = [(args, chunks[w], w, parts[w][0], parts[w][1], f"[w{w}] ") for w in range(workers)]
        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            res = pool.starmap(collect, jobs)
        total = sum(r[0] for r in res)
        stats = [r[1] for r in res]
        merge_parts(parts, jsonl_path, npz_path)
    if not args.jsonl and os.path.exists(jsonl_path) and os.path.getsize(jsonl_path) < 100:
        os.remove(jsonl_path)
    el = time.time() - t0
    agg = {k: sum(s[k] for s in stats) for k in stats[0]}
    mb = lambda q: os.path.getsize(q) / 2 ** 20 if os.path.exists(q) else 0  # noqa: E731
    print(f"\n수집 완료: transitions {total} ({el:.0f}s, {total / max(el, 1e-9):.0f} step/s, workers={workers})")
    print(f"  에피소드 {agg['episodes']} · 충돌 {agg['collisions']} · 완주 {agg['arrivals']} · 교착 {agg['stuck']}")
    print(f"  JSONL: {jsonl_path} ({mb(jsonl_path):.1f} MB)")
    print(f"  NPZ  : {npz_path} ({mb(npz_path):.1f} MB)")


if __name__ == "__main__":
    main()
