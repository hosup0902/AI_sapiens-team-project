"""도로 확인 스크립트 (수업 view_road.py 와 같은 역할) — 영등포~여의도.

    python view_road.py                 # sumo-gui로 도로 + 배경 교통 (▶ 버튼을 눌러 재생)
    python view_road.py --rebuild       # road_config.py 기준으로 도로·교통 다시 생성 후 열기
    python view_road.py --netedit       # netedit(도로 편집기)로 도로망 열기
    python view_road.py --nogui         # 화면 없이 설정 검증 (투입/도착/텔레포트/충돌 통계)
    python view_road.py --av gyeongin_to_mapo   # AV 경로 하나를 빨간 차로 함께 투입

도로의 원본(source of truth)은 env/road_config.py 이다. netedit 수정은 다음 빌드에서 덮어써진다.
영구 보정은 road_config.NETWORK["osm_fixes"] / ["join_clusters"] 또는 env/patches/*.xml 에.
"""
import argparse
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from env import road_builder  # noqa: E402  (SUMO_HOME 자동 설정)
from env.road_builder import P, NAME, OUT  # noqa: E402
from env.road_config import TRAFFIC, NETWORK  # noqa: E402
from sumolib import checkBinary  # noqa: E402


def summary():
    import sumolib
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
    with open(P("av_routes.json"), encoding="utf-8") as f:
        routes = json.load(f)
    n_veh = sum(1 for _ in sumolib.xml.parse_fast(P(f"{NAME}.rou.xml"), "vehicle", ["id"]))
    print("─" * 60)
    print(" 영등포 ~ 여의도 SUMO 환경 (env/road_config.py)")
    print("─" * 60)
    print(f"  엣지 {len(net.getEdges())} · 교차로 {len(net.getNodes())} · 신호 {len(net.getTrafficLights())}")
    print(f"  차로 총연장 {sum(e.getLength() * e.getLaneNumber() for e in net.getEdges()) / 1000:.1f} km")
    print(f"  병합 교차로: {', '.join(c['name'] for c in NETWORK['join_clusters'])}")
    print(f"  일반 차량 {n_veh}대 / {TRAFFIC['end'] - TRAFFIC['begin']} s "
          f"(Krauss·IDM·EIDM·ACC·버스·트럭 혼합, 60 s 주기 동적 재경로)")
    print(f"  AV 과제 경로 {len(routes)}개:")
    for k, r in routes.items():
        print(f"    {k:22s} {r['length_m'] / 1000:4.1f} km · 신호 {r['signals']:2d}곳 · {r['desc']}")
    print("─" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--netedit", action="store_true")
    ap.add_argument("--nogui", action="store_true")
    ap.add_argument("--seconds", type=int, default=1800)
    ap.add_argument("--av", default=None, help="함께 투입할 AV 과제 id (av_routes.json)")
    a = ap.parse_args()

    if a.rebuild or not os.path.exists(P(f"{NAME}.net.xml")):
        road_builder.build()
    summary()
    cfg = f"{NAME}.sumocfg"
    extra = []
    if a.av:
        with open(P("av_routes.json"), encoding="utf-8") as f:
            edges = json.load(f)[a.av]["edges"]
        av_file = P("view_av.rou.xml")
        with open(av_file, "w", encoding="utf-8") as f:
            f.write(f'<routes>\n  <route id="av_route" edges="{" ".join(edges)}"/>\n'
                    f'  <vehicle id="ego" type="ego_type" route="av_route" depart="600" '
                    f'departLane="best" departSpeed="max"/>\n</routes>\n')
        extra = ["--route-files", f"{NAME}.rou.xml,view_av.rou.xml"]
        print(f"  AV(빨간 차) 투입: {a.av} — 600 s 시점 출발")

    if a.netedit:
        subprocess.run([checkBinary("netedit"), f"{NAME}.net.xml"], cwd=OUT)
    elif a.nogui:
        r = subprocess.run([checkBinary("sumo"), "-c", cfg, "--end", str(a.seconds), "--step-length", "0.5",
                            "--no-warnings", "true", "--duration-log.statistics", "true"] + extra,
                           capture_output=True, text=True, cwd=OUT)
        print(r.stdout.strip() or r.stderr.strip())
        print("설정 검증 OK" if r.returncode == 0 else "설정 오류!")
    else:
        print("sumo-gui 실행 중… ▶ 버튼을 누르면 차량이 움직입니다. (Delay 값으로 속도 조절)")
        subprocess.run([checkBinary("sumo-gui"), "-c", cfg, "--step-length", "0.5", "--delay", "60"] + extra,
                       cwd=OUT)
