"""대량 데이터 수집 — 시뮬레이션 하나에 AV 여러 대를 동시에 투입 (10^7 transition 목표).

    python tools/collect_multi.py --model results/final/model.pt --transitions 2500000 --agents 8 --workers 4 --name ydp_ppo_multi

왜: 한 스텝 시간의 약 75 %가 SUMO 자체(HV 1,000여 대 + 동적 재경로)라, AV 1대짜리 환경으로는 코어당
초당 약 60 transition이 한계다(10^7 → 4코어 약 11시간). AV N대가 한 시뮬레이션 스텝을 공유하면
SUMO 비용을 나눠 쓰므로 같은 시간에 transition이 여러 배로 늘어난다.

동작: 교통 스냅샷을 불러오고, 빈 자리마다 7개 과제 경로 중 하나로 AV를 투입한다. 각 AV는 단일 AV
환경(env/sumo_env.py)과 같은 관측·행동·보상·종료 규칙을 쓰는 독립 에피소드다(apply_action → 공용
simulationStep → observe_step). 에피소드가 끝나면 그 자리에 새 AV를 투입하고, 시뮬레이션 시각이
spawn_until 을 넘으면 투입을 멈춘 뒤 남은 AV가 끝나면 다른 스냅샷을 불러온다.
AV는 HV 1,000여 대 중 N대(1 % 미만)라 교통 흐름에 주는 영향은 작다(검증: README 데이터 절).

출력: data/<name>_w<k>_p<j>.npz (50만 transition마다 한 파일, collect_pomdp_data.py NPZ와 같은 키 +
n_av = 그 스텝에 시뮬레이션에 있던 AV 수)
"""
import argparse
import copy
import os
import sys
import time

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def worker(args, wid):
    import torch
    torch.set_num_threads(1)
    os.chdir(BASE)
    from env.mdp_config import SIMULATION, OBSERVATION, ACTION
    from env.sumo_env import YdpCityEnv, OUT
    from train import REWARD
    from evaluate import load_policy

    rng = np.random.default_rng(args.seed * 1000 + wid)
    base = YdpCityEnv(SIMULATION, OBSERVATION, ACTION, REWARD, seed=args.seed * 1000 + wid)
    base.blocker_ignore_prefix = "av"
    base._start_sumo()
    T = base.T
    pol = load_policy(args, base)
    route_ids = list(base.route_ids)

    def load_snapshot():
        snap = base.snapshots[rng.integers(0, args.max_snapshot_index + 1)]
        cwd = os.getcwd()
        os.chdir(OUT)
        try:
            T.simulation.loadState(os.path.relpath(snap, OUT))
        finally:
            os.chdir(cwd)
        for rid in route_ids:
            rname = f"ego_route_{rid}"
            if rname not in T.route.getIDList():
                T.route.add(rname, base.routes[rid]["edges"])

    B = {k: [] for k in ("obs", "nobs", "act", "lane", "rew", "term", "trunc", "ep", "t",
                         "route", "coll", "arr", "xy", "spd", "shield", "nav")}
    det_xy, det_off = [], [0]
    part, total, saved_upto = 0, 0, 0
    stats = {"episodes": 0, "collisions": 0, "arrivals": 0, "stuck": 0}

    def flush(final=False):
        nonlocal part, B, det_xy, det_off, saved_upto
        n = len(B["rew"])
        if n == 0:
            return
        path = os.path.join(args.out_dir, f"{args.name}_w{wid}_p{part:02d}.npz")
        np.savez_compressed(
            path,
            observation=np.asarray(B["obs"], np.float32), action_raw=np.asarray(B["act"], np.float32),
            lane_change=np.asarray(B["lane"], np.int8), reward=np.asarray(B["rew"], np.float32),
            next_observation=np.asarray(B["nobs"], np.float32),
            terminated=np.asarray(B["term"], np.bool_), truncated=np.asarray(B["trunc"], np.bool_),
            episode=np.asarray(B["ep"], np.int64), t=np.asarray(B["t"], np.int32),
            detected_xy=np.asarray(det_xy, np.float32).reshape(-1, 2),
            detected_offsets=np.asarray(det_off, np.int64),
            route_index=np.asarray(B["route"], np.int8), route_names=np.asarray(route_ids),
            collided=np.asarray(B["coll"], np.bool_), arrived=np.asarray(B["arr"], np.bool_),
            ego_xy=np.asarray(B["xy"], np.float32).reshape(-1, 2), ego_speed=np.asarray(B["spd"], np.float32),
            shield=np.asarray(B["shield"], np.bool_), n_av=np.asarray(B["nav"], np.int8))
        print(f"[w{wid}] 저장 {path} ({n} transitions, 누적 {total})", flush=True)
        part += 1
        saved_upto = total
        B = {k: [] for k in B}
        det_xy, det_off = [], [0]

    # 에피소드 버퍼: 끝까지 간 에피소드만 B에 넣는다 (파일 경계에서 에피소드가 잘리지 않게)
    slots = [None] * args.agents          # 각 자리: dict(env, state, ...)
    ep_counter = 0
    t0 = time.time()
    load_snapshot()
    try:
        while total < args.transitions:
            now = T.simulation.getTime()
            spawning = now < args.spawn_until
            if not spawning and all(s is None for s in slots):
                load_snapshot()
                continue
            # (1) 빈 자리에 AV 투입
            if spawning:
                for i in range(args.agents):
                    if slots[i] is None:
                        ag = copy.copy(base)
                        ag.ego_id = f"av{wid}_{ep_counter}"
                        ag.route_id = route_ids[ep_counter % len(route_ids)]
                        ag._obst_cache_key = None
                        try:
                            T.vehicle.add(ag.ego_id, f"ego_route_{ag.route_id}", typeID="ego_type",
                                          departLane="best", departSpeed="max", departPos="base")
                        except Exception:
                            continue
                        slots[i] = {"env": ag, "pending": 0, "ep": wid * 10_000_000 + ep_counter, "buf": None}
                        ep_counter += 1
            # (2) 행동
            active = [s for s in slots if s is not None and s["buf"] is not None]
            pres = []
            for s in active:
                ag = s["env"]
                det = ag.get_detected_vehicles()
                a = np.clip(pol.predict(s["obs"], deterministic=True), -1, 1).astype(np.float32)
                pres.append((s, a, det, ag.apply_action(a)))
            T.simulationStep()
            nav = len(active)
            # (3) 결과
            for s, a, det, pre in pres:
                ag = s["env"]
                xy, spd = s["xy"], s["spd"]
                nobs, r, term, trunc, inf = ag.observe_step(pre)
                bf = s["buf"]
                bf["obs"].append(s["obs"]); bf["nobs"].append(nobs); bf["act"].append(a)
                bf["lane"].append(int(inf["lane_change"])); bf["rew"].append(float(r))
                bf["term"].append(bool(term)); bf["trunc"].append(bool(trunc)); bf["t"].append(len(bf["rew"]) - 1)
                bf["coll"].append(bool(inf["collided"])); bf["arr"].append(bool(inf["arrived"]))
                bf["xy"].append(xy); bf["spd"].append(spd); bf["shield"].append(bool(inf["shield"]))
                bf["nav"].append(nav); bf["det"].append([(d["x"], d["y"]) for d in det])
                if ag.ego_id in T.vehicle.getIDList():
                    ag._last_edge = T.vehicle.getRoadID(ag.ego_id)
                    s["xy"] = T.vehicle.getPosition(ag.ego_id)
                    s["spd"] = T.vehicle.getSpeed(ag.ego_id)
                s["obs"] = nobs
                if args.debug and ag._stopped == 200 and ag.ego_id in T.vehicle.getIDList():
                    L = T.vehicle.getLeader(ag.ego_id, 80)
                    lead = (L[0], round(L[1], 1), round(T.vehicle.getSpeed(L[0]), 2)) if L and L[0] else None
                    ob = ag._path_obstacle(80)
                    gb = ag._geometric_blockers(30)
                    jb = ag._junction_blockers(80)
                    x0, y0 = T.vehicle.getPosition(ag.ego_id)
                    near = [v for v in T.vehicle.getIDList()
                            if (T.vehicle.getPosition(v)[0] - x0) ** 2 + (T.vehicle.getPosition(v)[1] - y0) ** 2 < 2500]
                    stopped = sum(T.vehicle.getSpeed(v) < 0.1 for v in near)
                    tls = ag._tls_info()
                    head, chain = ag.ego_id, 0
                    while chain < 80:
                        Lh = T.vehicle.getLeader(head, 30)
                        if not Lh or not Lh[0] or T.vehicle.getSpeed(Lh[0]) > 0.5:
                            break
                        head, chain = Lh[0], chain + 1
                    hinfo = (head, chain, T.vehicle.getRoadID(head), round(T.vehicle.getSpeed(head), 2),
                             T.vehicle.getNextTLS(head)[:1] if T.vehicle.getNextTLS(head) else None)
                    print(f"[w{wid}]   대기열 선두: {hinfo}", flush=True)
                    print(f"[w{wid}] 100s정지 {ag.ego_id} {ag.route_id} edge={T.vehicle.getRoadID(ag.ego_id)} "
                          f"lead={lead} obst={ob} geo={gb} jf={jb} tls={tls[:3] if tls else None} "
                          f"50m내 {len(near)}대 중 정지 {stopped} · a_raw={a[0]:.2f}", flush=True)
                if term or trunc:
                    n = len(bf["rew"])
                    for k in ("obs", "nobs", "act", "lane", "rew", "term", "trunc", "t", "coll", "arr",
                              "xy", "spd", "shield", "nav"):
                        B[k].extend(bf[k])
                    B["ep"].extend([s["ep"]] * n)
                    B["route"].extend([route_ids.index(ag.route_id)] * n)
                    for pts in bf["det"]:
                        det_xy.extend(pts)
                        det_off.append(len(det_xy))
                    total += n
                    stats["episodes"] += 1
                    stats["collisions"] += int(inf["collided"])
                    stats["arrivals"] += int(inf["arrived"])
                    stats["stuck"] += int(inf["stuck"])
                    if inf["stuck"] or inf["collided"]:
                        print(f"[w{wid}] {'교착' if inf['stuck'] else '충돌'} {ag.route_id} t={n} "
                              f"edge={getattr(ag, '_last_edge', '?')} AV수={nav} {inf.get('collision_info')}", flush=True)
                    if ag.ego_id in T.vehicle.getIDList():
                        try:
                            T.vehicle.remove(ag.ego_id)
                        except Exception:
                            pass
                    slots[slots.index(s)] = None
            # (4) 대기 중이던 AV가 도로에 들어왔는지
            for i, s in enumerate(slots):
                if s is None or s["buf"] is not None:
                    continue
                ag = s["env"]
                if ag.ego_id in T.vehicle.getIDList():
                    T.vehicle.setSpeedMode(ag.ego_id, ag.speed_mode)
                    T.vehicle.setLaneChangeMode(ag.ego_id, ag.lc_mode)
                    ag.step_count, ag._stopped, ag._prev_accel_cmd, ag._prev_dist = 0, 0, 0.0, 0.0
                    s["obs"] = ag._get_obs()
                    s["xy"] = T.vehicle.getPosition(ag.ego_id)
                    s["spd"] = T.vehicle.getSpeed(ag.ego_id)
                    s["buf"] = {k: [] for k in ("obs", "nobs", "act", "lane", "rew", "term", "trunc", "t",
                                                "coll", "arr", "xy", "spd", "shield", "nav", "det")}
                else:
                    s["pending"] += 1
                    if s["pending"] > 120:
                        try:
                            T.vehicle.remove(ag.ego_id)
                        except Exception:
                            pass
                        slots[i] = None
            if total - saved_upto >= args.part_size:
                flush()
                el = time.time() - t0
                print(f"[w{wid}] {total} transitions · {total / el:.0f}/s · 에피소드 {stats}", flush=True)
            if args.parent_pid and os.getppid() != args.parent_pid:
                break
    finally:
        flush(final=True)
        try:
            T.close()
        except Exception:
            pass
    return total, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="results/final/model.pt")
    ap.add_argument("--policy", default="ppo")
    ap.add_argument("--transitions", type=int, default=2_500_000, help="워커당 목표 transition 수")
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--spawn-until", type=float, default=3300)
    ap.add_argument("--max-snapshot-index", type=int, default=6, help="0~6 → 900~2700 s 스냅샷 (투입 시간 확보)")
    ap.add_argument("--part-size", type=int, default=500_000)
    ap.add_argument("--out-dir", default=os.path.join(BASE, "data", "multi"))
    ap.add_argument("--name", default="ydp_ppo_multi")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    os.chdir(BASE)
    from env.mdp_config import SIMULATION
    from env.sumo_env import ensure_snapshots
    ensure_snapshots(SIMULATION["snapshot_times"], SIMULATION["step_length"])
    a.parent_pid = os.getpid()
    t0 = time.time()
    if a.workers == 1:
        a.parent_pid = None
        res = [worker(a, 0)]
    else:
        import multiprocessing
        with multiprocessing.get_context("spawn").Pool(a.workers) as pool:
            res = pool.starmap(worker, [(a, w) for w in range(a.workers)])
    tot = sum(r[0] for r in res)
    st = {k: sum(r[1][k] for r in res) for k in res[0][1]}
    print(f"\n완료: {tot} transitions ({time.time() - t0:.0f}s, {tot / (time.time() - t0):.0f}/s) · {st}")


if __name__ == "__main__":
    main()
