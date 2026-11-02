"""시연용 투어 경로 생성 — 서쪽 끝 경인로 → 영등포 로터리(오거리) → 서울교 → 여의도 순환도로 한 바퀴.

    python tools/make_tour_route.py            # → env/sumo/av_tour.json
    python tools/record_video.py --routes-file env/sumo/av_tour.json --route yeouido_tour --model results/final/model.pt

여의도 순환도로 = 여의서로(북서, 한강 쪽) + 여의동로(남동, 샛강 쪽). 섬 중심을 기준으로 시계 방향
(우측통행에서 섬이 오른쪽) 진행 방향의 순환도로 엣지를 각도 순으로 골라 경유점으로 삼고, 경유점 사이를
최단경로로 잇는다. 학습·평가용 7개 과제(av_routes.json)와는 별도 파일이라 평가에는 영향이 없다.
"""
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_builder import P, NAME  # noqa: E402
import sumolib  # noqa: E402

RING = ("여의서로", "여의동로")
CENTER = (126.9265, 37.5255)         # 여의도 중심 (경도, 위도)
STEP_DEG = 25.0                      # 경유점 간격 (각도)


def main():
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"))
    with open(P("av_routes.json"), encoding="utf-8") as f:
        base = json.load(f)["gyeongin_to_mapo"]["edges"]
    # 1) 서쪽 끝 경인로 → 로터리 → 서울교: 여의도 진입 직후(여의대로 직전)까지
    head = []
    for eid in base:
        if net.getEdge(eid).getName() == "여의대로":
            break
        head.append(eid)
    cx, cy = net.convertLonLat2XY(*CENTER)

    def ang(x, y):
        return math.degrees(math.atan2(y - cy, x - cx)) % 360

    # 2) 시계 방향 순환도로 엣지
    ring = []
    for e in net.getEdges():
        if e.getName() not in RING or not e.allows("passenger"):
            continue
        sh = e.getShape()
        (x0, y0), (x1, y1) = sh[0], sh[-1]
        mx, my = sh[len(sh) // 2]
        cross = (mx - cx) * (y1 - y0) - (my - cy) * (x1 - x0)
        if cross < 0 and e.getLength() > 20:          # 시계 방향
            ring.append((ang(mx, my), math.hypot(mx - cx, my - cy), e))
    hx, hy = net.getEdge(head[-1]).getShape()[-1]
    a0 = ang(hx, hy)
    # 진입 각도에서 시계 방향(각도 감소)으로 STEP_DEG 마다 가장 바깥쪽(순환도로 본선) 엣지 선택
    way = []
    k = 1
    while k * STEP_DEG < 360:
        target = (a0 - k * STEP_DEG) % 360
        cand = [r for r in ring if min(abs(r[0] - target), 360 - abs(r[0] - target)) < STEP_DEG / 2]
        if cand:
            way.append(max(cand, key=lambda r: r[1] + 10 * e_len(r[2]))[2])
        k += 1

    def path(a, b):
        p, _ = net.getShortestPath(a, b, vClass="passenger")
        return p

    edges = [net.getEdge(e) for e in head]
    cur = edges[-1]
    loop_start = None
    for w in way + way[:1]:          # 첫 경유점으로 돌아와 한 바퀴를 닫는다
        p = path(cur, w)
        if not p:
            print(f"  경유점 건너뜀: {w.getID()} (경로 없음)")
            continue
        if loop_start is None:
            loop_start = len(edges) + len(p) - 1
        edges += p[1:]
        cur = w
    ids = [e.getID() for e in edges]
    length = sum(e.getLength() for e in edges)
    names = []
    for e in edges:
        n = e.getName()
        if n and (not names or names[-1] != n):
            names.append(n)
    tls = sum(1 for e in edges if e.getToNode().getType().startswith("traffic_light"))
    out = {"yeouido_tour": {"edges": ids, "length_m": round(length, 1), "signals": tls, "streets": names,
                            "desc": "경인로(서쪽 끝) → 영등포 로터리(오거리) → 서울교 → 여의도 순환도로(여의서로·여의동로) 한 바퀴"}}
    with open(P("av_tour.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"투어 경로: {length / 1000:.2f} km · 엣지 {len(ids)} · 신호 {tls}곳")
    print("  " + " → ".join(names))


def e_len(e):
    return e.getLength() / 1000.0


if __name__ == "__main__":
    main()
