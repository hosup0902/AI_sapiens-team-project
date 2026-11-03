"""대량 데이터 수집 — 시뮬레이션 하나에 AV 여러 대를 동시에 투입 (10^7 transition 목표).

    python tools/collect_multi.py --model results/final/model.pt --transitions 2500000 --agents 8 --workers 4 --name ydp_ppo_multi

왜: 한 스텝 시간의 약 75 %가 SUMO 자체(HV 1,000여 대 + 동적 재경로)라, AV 1대짜리 환경으로는 코어당
초당 약 60 transition이 한계다(10^7 → 4코어 약 11시간). AV N대가 한 시뮬레이션 스텝을 공유하면
SUMO 비용을 나눠 쓰므로 같은 시간에 transition이 여러 배로 늘어난다.

동작: 교통 스냅샷을 불러오고, 빈 자리마다 7개 과제 경로 중 하나로 AV를 투입한다. 각 AV는 단일 AV
환경(env/sumo_env.py)과 같은 관측·행동·보상·종료 규칙을 쓰는 독립 에피소드다(apply_action → 공용
simulationStep → observe_step). 에피소드가 끝나면 그 자리에 새 AV를 투입하고, 시뮬레이션 시각이
spawn_until 을 넘으면 투입을 멈춘 뒤 남은 AV가 끝나면 다른 스냅샷을 불러온다.
AV는 HV 1,000여 대 중 N대(1 % 내외)라 교통 흐름에 주는 영향은 작다.

AV끼리: 교차로 장애물 인식(sumo_env._ignore_blocker)에서 먼저 투입된 AV가 우선권을 갖는다.
  - 서로를 장애물로 보면 서로 기다리는 교착이 생기고(시험: 21 에피소드 중 교착 6),
  - 서로 무시하면 교차로에서 AV끼리 충돌했다(시험: 충돌 다수).
  - 투입 순서 우선권은 대기 순환이 생길 수 없어 둘 다 해결 (시험: 29 에피소드 충돌 0, 교착 2).

출력: <out-dir>/<name>_w<k>_p<j>.npz (part-size transition마다 한 파일). 키:
  - collect_pomdp_data.py NPZ 기본 키 (observation, action_raw, lane_change, reward, next_observation,
    terminated, truncated, episode, t, detected_xy, detected_offsets) + route/충돌/도착/ego_xy/ego_speed/shield/n_av
  - 수업 기본 JSONL 항목을 배열로 (v2, 2026-11-03~): action_accel_raw, action_lane_change_raw,
    lane_change_applied, lane_before, lane_after, stuck
  - State s_t 절대 정보 (state_*): sim_time, accel, angle, lane, lane_pos, edge(→edge_names),
    speed_limit, route_progress_m, tls_dist/state/remain (+ route_lengths_m)
  - 감지 차량 상세 (detected_offsets 정렬): detected_speed, detected_rel_pos, detected_lane_offset,
    detected_type(→vtype_names)
  s_{t+1}은 같은 에피소드의 다음 행(마지막 step은 terminated/truncated로 끝남)이다.
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

    KEYS = ("obs", "nobs", "act", "lane", "rew", "term", "trunc", "t", "coll", "arr", "xy", "spd", "shield", "nav",
            "st", "araw", "lraw", "lapp", "lbef", "laft", "stuck")
    B = {k: [] for k in KEYS + ("ep", "route")}
    det_xy, det_off, det_n = [], [0], 0      # det_xy: 스텝별 (k,2) float32 배열 목록
    det_ex = []                              # 스텝별 (k,4) [speed, rel_pos, lane_offset, type]
    edges, vtypes = {}, {}                   # 이름 → 인덱스 (워커 전체 누적, 파일마다 전체 목록 저장)
    route_len = np.asarray([base.route_len[r] for r in route_ids], np.float32)

    def idx(d, k):
        if k not in d:
            d[k] = len(d)
        return d[k]

    def ego_state(ag):
        """State s_t 절대 정보 (get_privileged_state의 ego 부분과 같은 값).
        위경도는 용량 때문에 저장하지 않는다: ego_xy → sumolib net.convertXY2LonLat(x, y) 로 정확히 복원."""
        v = ag.ego_id
        tls = ag._tls_info()
        return (T.simulation.getTime(), T.vehicle.getAcceleration(v), T.vehicle.getAngle(v),
                T.vehicle.getLaneIndex(v), T.vehicle.getLanePosition(v), idx(edges, T.vehicle.getRoadID(v)),
                T.vehicle.getAllowedSpeed(v), T.vehicle.getDistance(v),
                *((tls[0], tls[1], tls[2]) if tls else (np.nan, -2, np.nan)))
    part, total, saved_upto = 0, 0, 0
    stats = {"episodes": 0, "collisions": 0, "arrivals": 0, "stuck": 0}

    def flush(final=False):
        nonlocal part, B, det_xy, det_off, det_n, det_ex, saved_upto
        n = len(B["rew"])
        if n == 0:
            return
        S = np.asarray(B["st"], np.float64).reshape(-1, 11)
        DX = np.concatenate(det_ex) if det_ex else np.zeros((0, 4), np.float32)
        path = os.path.join(args.out_dir, f"{args.name}_w{wid}_p{part:02d}.npz")
        np.savez_compressed(
            path,
            observation=np.asarray(B["obs"], np.float32), action_raw=np.asarray(B["act"], np.float32),
            lane_change=np.asarray(B["lane"], np.int8), reward=np.asarray(B["rew"], np.float32),
            next_observation=np.asarray(B["nobs"], np.float32),
            terminated=np.asarray(B["term"], np.bool_), truncated=np.asarray(B["trunc"], np.bool_),
            episode=np.asarray(B["ep"], np.int64), t=np.asarray(B["t"], np.int32),
            detected_xy=(np.concatenate(det_xy) if det_xy else np.zeros((0, 2), np.float32)).reshape(-1, 2),
            detected_offsets=np.asarray(det_off, np.int64),
            route_index=np.asarray(B["route"], np.int8), route_names=np.asarray(route_ids),
            collided=np.asarray(B["coll"], np.bool_), arrived=np.asarray(B["arr"], np.bool_),
            ego_xy=np.asarray(B["xy"], np.float32).reshape(-1, 2), ego_speed=np.asarray(B["spd"], np.float32),
            shield=np.asarray(B["shield"], np.bool_), n_av=np.asarray(B["nav"], np.int8),
            action_accel_raw=np.asarray(B["araw"], np.float32), action_lane_change_raw=np.asarray(B["lraw"], np.float32),
            lane_change_applied=np.asarray(B["lapp"], np.bool_), lane_before=np.asarray(B["lbef"], np.int8),
            lane_after=np.asarray(B["laft"], np.int8), stuck=np.asarray(B["stuck"], np.bool_),
            state_sim_time=S[:, 0].astype(np.float32),
            state_accel=S[:, 1].astype(np.float32), state_angle=S[:, 2].astype(np.float32),
            state_lane=S[:, 3].astype(np.int8), state_lane_pos=S[:, 4].astype(np.float32),
            state_edge=S[:, 5].astype(np.int32), state_speed_limit=S[:, 6].astype(np.float32),
            state_route_progress_m=S[:, 7].astype(np.float32), state_tls_dist=S[:, 8].astype(np.float32),
            state_tls_state=S[:, 9].astype(np.int8), state_tls_remain=S[:, 10].astype(np.float32),
            route_lengths_m=route_len, edge_names=np.asarray(list(edges)), vtype_names=np.asarray(list(vtypes)),
            detected_speed=DX[:, 0].astype(np.float16), detected_rel_pos=DX[:, 1].astype(np.float16),
            detected_lane_offset=DX[:, 2].astype(np.int8), detected_type=DX[:, 3].astype(np.int8))
        print(f"[w{wid}] 저장 {path} ({n} transitions, 누적 {total})", flush=True)
        part += 1
        saved_upto = total
        B = {k: [] for k in B}
        det_xy, det_off, det_n, det_ex = [], [0], 0, []

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
                xy, spd, st = s["xy"], s["spd"], s["st"]
                nobs, r, term, trunc, inf = ag.observe_step(pre)
                bf = s["buf"]
                bf["obs"].append(s["obs"]); bf["nobs"].append(nobs); bf["act"].append(a)
                bf["lane"].append(int(inf["lane_change"])); bf["rew"].append(float(r))
                bf["term"].append(bool(term)); bf["trunc"].append(bool(trunc)); bf["t"].append(len(bf["rew"]) - 1)
                bf["coll"].append(bool(inf["collided"])); bf["arr"].append(bool(inf["arrived"]))
                bf["xy"].append(xy); bf["spd"].append(spd); bf["shield"].append(bool(inf["shield"]))
                bf["nav"].append(nav); bf["det"].append(np.asarray([(d["x"], d["y"]) for d in det], np.float32).reshape(-1, 2))
                bf["dex"].append(np.asarray([(d["speed"], d["rel_pos"], d["lane_offset"], idx(vtypes, d["type"]))
                                             for d in det], np.float32).reshape(-1, 4))
                bf["st"].append(st); bf["araw"].append(float(inf["accel_raw"])); bf["lraw"].append(float(inf["lane_change_raw"]))
                bf["lapp"].append(bool(inf["lane_change_applied"]))
                bf["lbef"].append(-1 if inf["lane_before"] is None else int(inf["lane_before"]))
                bf["laft"].append(-1 if inf["lane_after"] is None else int(inf["lane_after"]))
                bf["stuck"].append(bool(inf["stuck"]))
                if ag.ego_id in T.vehicle.getIDList():
                    ag._last_edge = T.vehicle.getRoadID(ag.ego_id)
                    s["xy"] = T.vehicle.getPosition(ag.ego_id)
                    s["spd"] = T.vehicle.getSpeed(ag.ego_id)
                    s["st"] = ego_state(ag)
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
                    for k in KEYS:
                        B[k].extend(bf[k])
                    det_ex.extend(bf["dex"])
                    B["ep"].extend([s["ep"]] * n)
                    B["route"].extend([route_ids.index(ag.route_id)] * n)
                    for pts in bf["det"]:
                        det_xy.append(pts)
                        det_n += len(pts)
                        det_off.append(det_n)
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
                    s["st"] = ego_state(ag)
                    s["buf"] = {k: [] for k in KEYS + ("det", "dex")}
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
    ap.add_argument("--part-size", type=int, default=200_000)
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
