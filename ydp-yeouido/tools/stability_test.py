"""일반 차량(HV) 교통 안정성 측정 — 텔레포트 / 충돌 / 정체 고착 / 처리량.

    python tools/stability_test.py                     # 3600 s, seed 42
    python tools/stability_test.py --end 1800 --seeds 1 2 3 --step 0.1
    python tools/stability_test.py --hotspots          # 텔레포트·충돌 위치 상위 목록

평가 기준(6_Project_Evaluation.md: "비정상적인 정체 / Teleport / 오류가 없는가")을 수치로 확인한다.
"""
import argparse
import collections
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_builder import P, NAME, OUT  # noqa: E402  (SUMO_HOME 설정)
import libsumo as traci  # noqa: E402


def run(seed, end, step, warmup):
    cwd = os.getcwd()
    os.chdir(OUT)   # 한글 경로 회피: 상대경로로 실행
    try:
        traci.start(["sumo", "-c", f"{NAME}.sumocfg", "--seed", str(seed),
                     "--step-length", str(step), "--no-warnings", "true",
                     "--duration-log.disable", "true"])
    finally:
        os.chdir(cwd)
    tele = collections.Counter()
    coll = collections.Counter()
    tele_n = coll_n = 0
    running_max = 0
    speeds = []
    stopped_long = 0
    t0 = time.time()
    arrived = departed = 0
    stop_time = collections.defaultdict(float)
    seen_pairs = set()
    jam = collections.Counter()
    while traci.simulation.getTime() < end:
        traci.simulationStep()
        t = traci.simulation.getTime()
        departed += traci.simulation.getDepartedNumber()
        arrived += traci.simulation.getArrivedNumber()
        for v in traci.simulation.getStartingTeleportIDList():
            if t >= warmup:
                tele_n += 1
                tele[traci.vehicle.getRoadID(v)] += 1
        for c in traci.simulation.getCollisions():
            key = tuple(sorted((c.collider, c.victim)))
            if t >= warmup and key not in seen_pairs:   # 같은 충돌이 매 스텝 반복 집계되지 않도록
                seen_pairs.add(key)
                coll_n += 1
                coll[c.lane] += 1
        ids = traci.vehicle.getIDList()
        running_max = max(running_max, len(ids))
        if int(t / step) % int(10 / step) == 0 and t >= warmup:     # 10 s마다 표본
            sp = [traci.vehicle.getSpeed(v) for v in ids]
            if sp:
                speeds.append(sum(sp) / len(sp))
            for v in ids:
                if traci.vehicle.getSpeed(v) < 0.1:
                    stop_time[v] += 10
                    if stop_time[v] == 120:
                        stopped_long += 1
                        jam[traci.vehicle.getRoadID(v)] += 1
                else:
                    stop_time.pop(v, None)
    pending = traci.simulation.getMinExpectedNumber()
    traci.close()
    return {
        "seed": seed, "sim_s": end, "wall_s": round(time.time() - t0, 1),
        "departed": departed, "arrived": arrived, "running_max": running_max,
        "pending_end": pending,
        "teleports": tele_n, "collisions": coll_n,
        "stopped_over_120s": stopped_long,
        "mean_speed_kmh": round(3.6 * sum(speeds) / max(1, len(speeds)), 1),
        "tele_hot": tele.most_common(12), "coll_hot": coll.most_common(12),
        "jam_hot": jam.most_common(12),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", type=float, default=3600)
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--warmup", type=float, default=0)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42])
    ap.add_argument("--hotspots", action="store_true")
    ap.add_argument("--save", default=os.path.join(BASE, "results", "stability.json"))
    a = ap.parse_args()
    res = []
    for s in a.seeds:
        r = run(s, a.end, a.step, a.warmup)
        res.append(r)
        print(f"seed {s}: 투입 {r['departed']} · 도착 {r['arrived']} · 최대 동시 {r['running_max']}대 · "
              f"텔레포트 {r['teleports']} · 충돌 {r['collisions']} · 120s+ 정지 {r['stopped_over_120s']} · "
              f"평균속도 {r['mean_speed_kmh']} km/h · 잔여 {r['pending_end']} ({r['wall_s']} s)")
        if a.hotspots:
            print("   텔레포트 위치:", r["tele_hot"])
            print("   충돌 위치   :", r["coll_hot"])
            print("   정체 위치   :", r["jam_hot"])
    os.makedirs(os.path.dirname(a.save), exist_ok=True)
    with open(a.save, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
