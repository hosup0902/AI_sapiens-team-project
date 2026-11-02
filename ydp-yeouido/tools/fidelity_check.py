"""SUMO 도로망 ↔ OSM 원본 일치도 검사 (도로가 실제 도로를 얼마나 그대로 옮겼는가).

    python tools/fidelity_check.py              # 콘솔 요약 + results/fidelity.json
    python tools/fidelity_check.py --list 30    # 불일치 상세를 30개씩 출력

OSM(data/osm/region.osm → 클리핑본 env/sumo/ydp.roads.osm)을 '실제 도로'의 기준으로 삼아
netconvert 결과(env/sumo/ydp.net.xml)를 항목별로 대조한다.

  1) 도로 포함      차량 도로 way 중 SUMO에 들어간 비율 (길이 기준), 빠진 도로 목록
  2) 통행 방향      oneway 태그 ↔ SUMO 정/역방향 엣지 존재
  3) 차로 수        lanes / lanes:forward / lanes:backward 태그 ↔ SUMO 차로 수
                    (태그 없는 도로는 road_config.default_lanes 로 '추정'된 것 → 별도 집계)
  4) 제한속도       maxspeed 태그 ↔ SUMO 속도
  5) 선형(geometry) SUMO 엣지 중심선이 OSM way 선형에서 벗어난 최대 거리
  6) 신호 위치      OSM traffic_signals 노드 ↔ SUMO 신호교차로 (누락 / 추정 추가)
  7) 입체 교차      서로 다른 층(교량·지하차도·평면)의 도로가 OSM에 없는 평면 연결로 이어졌는지
  8) 회전 제한      OSM restriction relation 수 (좌회전 금지 등이 반영됐는지)

OSM 자체가 실측(항공사진·현장조사) 기반 공개 지도라 1:1 기준으로 쓰되,
OSM에 태그가 없거나 틀린 부분은 '실제와 다를 수 있음'으로 따로 보고한다.
"""
import argparse
import collections
import json
import math
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_builder import P, NAME  # noqa: E402  (SUMO_HOME 설정)
from env.road_config import NETWORK, REGION  # noqa: E402
from env.osm_prep import OSM, way_layer as _layer  # noqa: E402
import sumolib  # noqa: E402

R = 6371000.0


def _xy(lon, lat, lat0):
    return (math.radians(lon) * R * math.cos(math.radians(lat0)), math.radians(lat) * R)


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def _poly_dist(p, line):
    return min(_seg_dist(p, line[i], line[i + 1]) for i in range(len(line) - 1))


def _num(v):
    if v is None:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)", v)
    return float(m.group(1)) if m else None


def expected_lanes(tags):
    """OSM 태그가 말하는 방향별 차로 수 (fwd, bwd). 태그가 없으면 None."""
    ow = tags.get("oneway", "no")
    lanes = _num(tags.get("lanes"))
    fwd, bwd = _num(tags.get("lanes:forward")), _num(tags.get("lanes:backward"))
    if ow in ("yes", "true", "1") or tags.get("junction") == "roundabout" \
            or tags.get("highway") in ("motorway",) and ow != "no":
        return (lanes, None)
    if ow == "-1":
        return (None, lanes)
    if fwd or bwd:
        return (fwd, bwd)
    if lanes:
        return (math.ceil(lanes / 2), math.floor(lanes / 2)) if lanes > 1 else (1, 1)
    return (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=int, default=15)
    ap.add_argument("--save", default=os.path.join(BASE, "results", "fidelity.json"))
    a = ap.parse_args()

    clipped = P(f"{NAME}.roads.osm")
    if not os.path.exists(clipped):
        sys.exit("env/sumo/ydp.roads.osm 없음 — 먼저 `python -m env.road_builder --only net`")
    osm = OSM(clipped)
    raw_has_restr = sum(1 for _, _, t in OSM(os.path.join(BASE, REGION["osm_file"])).rels
                        if t.get("type") == "restriction")
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
    lat0 = (REGION["bbox"][0] + REGION["bbox"][2]) / 2
    road_types = set(NETWORK["road_types"])

    # SUMO 엣지 → OSM way (lane param origId)
    by_way = collections.defaultdict(lambda: {"fwd": [], "bwd": []})
    for e in net.getEdges():
        if not e.allows("passenger"):
            continue
        orig = e.getLanes()[0].getParam("origId") or re.sub(r"#.*$", "", e.getID()).lstrip("-")
        for wid in orig.split():
            by_way[wid]["bwd" if e.getID().startswith("-") else "fwd"].append(e)

    def way_xy(refs):
        return [_xy(*osm.nodes[r], lat0) for r in refs if r in osm.nodes]

    def length(line):
        return sum(math.dist(line[i], line[i + 1]) for i in range(len(line) - 1))

    rep = collections.OrderedDict()
    # ── 1) 포함 · 2) 방향 · 3) 차로 · 4) 속도 · 5) 선형 ──
    cov_tot = cov_in = 0.0
    cov_cls = collections.defaultdict(lambda: [0.0, 0.0])
    missing = []
    dir_bad = []
    lane_ok = lane_bad_len = lane_ok_len = lane_default_len = 0.0
    lane_bad = []
    spd_ok = spd_bad = 0
    spd_bad_l = []
    geo = []
    for wid, (refs, tags, _) in osm.ways.items():
        hw = tags.get("highway")
        if hw not in road_types or tags.get("access") in ("no", "private") \
                or tags.get("motor_vehicle") == "no":
            continue
        line = way_xy(refs)
        if len(line) < 2:
            continue
        L = length(line)
        cov_tot += L
        cov_cls[hw][0] += L
        name = tags.get("name", "")
        es = by_way.get(wid)
        if not es or not (es["fwd"] or es["bwd"]):
            missing.append((round(L), hw, name, wid))
            continue
        cov_in += L
        cov_cls[hw][1] += L
        # 방향
        ow = tags.get("oneway", "no")
        one = ow in ("yes", "true", "1") or tags.get("junction") == "roundabout"
        has_f, has_b = bool(es["fwd"]), bool(es["bwd"])
        if one and has_b and not (ow == "-1"):
            dir_bad.append((round(L), name, wid, "일방인데 역방향 엣지 있음"))
        elif ow == "-1" and has_f:
            dir_bad.append((round(L), name, wid, "역일방인데 정방향 엣지 있음"))
        elif not one and ow != "-1" and not (has_f and has_b):
            dir_bad.append((round(L), name, wid, "양방향인데 한쪽만 있음"))
        # 차로 — 엣지 중 가장 긴 것(교차로 직전 회전차로 증설 구간 제외 효과)
        fwd, bwd = expected_lanes(tags)
        for key, exp in (("fwd", fwd), ("bwd", bwd)):
            if not es[key]:
                continue
            main = max(es[key], key=lambda e: e.getLength())
            got = main.getLaneNumber()
            if exp is None:
                lane_default_len += L / (2 if (has_f and has_b) else 1)
                continue
            if int(exp) == got:
                lane_ok += 1
                lane_ok_len += L / (2 if (has_f and has_b) else 1)
            else:
                lane_bad_len += L / (2 if (has_f and has_b) else 1)
                lane_bad.append((round(L), name or hw, wid, key, int(exp), got))
        # 속도
        ms = _num(tags.get("maxspeed"))
        if ms:
            e0 = (es["fwd"] or es["bwd"])[0]
            if abs(e0.getSpeed() * 3.6 - ms) < 1.5:
                spd_ok += 1
            else:
                spd_bad += 1
                spd_bad_l.append((name, wid, ms, round(e0.getSpeed() * 3.6)))
    # ── 5) 선형: SUMO 엣지 형상점 ↔ 가장 가까운 OSM 차량 도로 선형 ──
    #   (netconvert가 여러 way를 한 엣지로 합치므로 way 하나가 아니라 전체 도로망과 비교)
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    lines, names = [], []
    for wid, (refs, tags, _) in osm.ways.items():
        if tags.get("highway") in road_types:
            ln_ = way_xy(refs)
            if len(ln_) >= 2:
                lines.append(LineString(ln_))
                names.append(tags.get("name", ""))
    tree = STRtree(lines)
    for e in net.getEdges():
        if not e.allows("passenger"):
            continue
        two_way = e.getBidi() is not None or net.hasEdge(
            e.getID()[1:] if e.getID().startswith("-") else "-" + e.getID())
        off = e.getLaneNumber() * NETWORK["lane_width"] / 2 if two_way else 0.0
        dmax = 0.0
        for x, y in e.getShape():
            pt = Point(_xy(*net.convertXY2LonLat(x, y), lat0))
            i = tree.nearest(pt)
            dmax = max(dmax, pt.distance(lines[i]))
        geo.append((max(0.0, dmax - off), e.getID(), e.getName()))

    rep["coverage"] = {
        "osm_car_road_km": round(cov_tot / 1000, 1),
        "in_sumo_km": round(cov_in / 1000, 1),
        "ratio": round(cov_in / max(cov_tot, 1), 4),
        "by_class": {k: round(v[1] / max(v[0], 1), 3) for k, v in
                     sorted(cov_cls.items(), key=lambda t: -t[1][0])},
        "missing_top": sorted(missing, reverse=True)[:a.list],
        "missing_km": round(sum(m[0] for m in missing) / 1000, 2),
    }
    rep["direction"] = {"mismatch": len(dir_bad), "list": sorted(dir_bad, reverse=True)[:a.list]}
    tagged = lane_ok_len + lane_bad_len
    rep["lanes"] = {
        "tagged_match_ratio_by_length": round(lane_ok_len / max(tagged, 1), 4),
        "tagged_km": round(tagged / 1000, 1),
        "untagged_default_km": round(lane_default_len / 1000, 1),
        "mismatch_list": sorted(lane_bad, reverse=True)[:a.list],
        "mismatch_count": len(lane_bad),
    }
    rep["speed"] = {"tagged_match": spd_ok, "tagged_mismatch": spd_bad,
                    "list": spd_bad_l[:a.list]}
    gd = sorted(g[0] for g in geo)
    q = lambda p: round(gd[min(len(gd) - 1, int(p * len(gd)))], 2)  # noqa: E731
    rep["geometry_m"] = {"edges": len(gd), "p50": q(0.5), "p95": q(0.95), "p99": q(0.99),
                         "max": round(gd[-1], 1),
                         "over_5m": [(round(d, 1), i, n) for d, i, n in sorted(geo, reverse=True)
                                     if d > 5][:a.list]}

    # ── 6) 신호 ──
    osm_sig = []
    road_nodes = set()
    for wid, (refs, tags, _) in osm.ways.items():
        if tags.get("highway") in road_types:
            road_nodes.update(refs)
    for nid, el in osm.node_el.items():
        if nid in road_nodes and any(t.get("k") == "highway" and t.get("v") == "traffic_signals"
                                     for t in el.findall("tag")):
            osm_sig.append(_xy(*osm.nodes[nid], lat0))
    tls_pos = []
    for tl in net.getTrafficLights():
        nodes = {c[0].getEdge().getToNode() for c in tl.getConnections()}
        for n in nodes:
            lon, lat = net.convertXY2LonLat(*n.getCoord())
            tls_pos.append((tl.getID(), _xy(lon, lat, lat0)))
    near = 40.0
    miss_sig = sum(1 for s in osm_sig if not any(math.dist(s, p) < near for _, p in tls_pos))
    tl_ids = {t for t, _ in tls_pos}
    guessed = {t for t in tl_ids
               if not any(math.dist(p, s) < near for tt, p in tls_pos if tt == t for s in osm_sig)}
    rep["signals"] = {"osm_signal_nodes": len(osm_sig), "sumo_tls": len(tl_ids),
                      "osm_signals_without_sumo_tls": miss_sig,
                      "sumo_tls_without_osm_signal(guessed)": len(guessed)}

    # ── 7) 입체 교차: 한 SUMO 교차로로 합쳐진 OSM 노드들이 실제로는 서로 이어지지 않은
    #       다른 층(교량 1 / 평면 0 / 지하차도 -1) 도로들이면 → 입체 교차가 평면 교차로 둔갑
    way_layer = {w: _layer(t) for w, (_, t, _) in osm.ways.items()
                 if t.get("highway") in road_types}
    node_ways = collections.defaultdict(set)
    for w in way_layer:
        for r in osm.ways[w][0]:
            node_ways[r].add(w)
    false_links = []
    for j in net.getNodes():
        nids = [t for t in re.split(r"[_]", j.getID()) if t.isdigit()]
        if len(nids) < 2:
            continue
        # 노드 공유로 이어진 way 묶음(연결 요소)
        groups = []
        for n in nids:
            ws = node_ways.get(n, set())
            hit = [g for g in groups if g & ws]
            merged = set(ws).union(*hit) if hit else set(ws)
            groups = [g for g in groups if g not in hit] + [merged]
        layers = [sorted({way_layer[w] for w in g}) for g in groups if g]
        if len({tuple(l) for l in layers}) > 1 and \
                not set.intersection(*[set(l) for l in layers]):
            lon, lat = net.convertXY2LonLat(*j.getCoord())
            nm = sorted({osm.ways[w][1].get("name", "") for g in groups for w in g} - {""})
            false_links.append((j.getID()[:50], f"{lon:.5f},{lat:.5f}", layers, nm[:4]))
    rep["grade_separation"] = {"false_at_grade_junctions": len(false_links),
                               "list": false_links[:a.list]}
    rep["turn_restrictions"] = {"in_raw_osm": raw_has_restr,
                                "note": "0이면 수집 쿼리에 restriction relation이 빠진 것 — "
                                        "tools/fetch_osm.py --force 로 다시 받을 것"}

    # ── 출력 ──
    c = rep["coverage"]
    print(f"1) 도로 포함   : {c['in_sumo_km']}/{c['osm_car_road_km']} km ({c['ratio']:.1%}) · "
          f"빠진 도로 {c['missing_km']} km")
    print("   등급별:", ", ".join(f"{k} {v:.0%}" for k, v in c["by_class"].items()))
    for m in c["missing_top"][:a.list]:
        print("     빠짐:", m)
    d = rep["direction"]
    print(f"2) 통행 방향   : 불일치 {d['mismatch']}건")
    for m in d["list"]:
        print("     ", m)
    ln = rep["lanes"]
    print(f"3) 차로 수     : OSM 태그 있는 {ln['tagged_km']} km 중 {ln['tagged_match_ratio_by_length']:.1%} 일치 · "
          f"태그 없어 기본값 추정 {ln['untagged_default_km']} km · 불일치 {ln['mismatch_count']}건")
    for m in ln["mismatch_list"]:
        print("     (길이m, 이름, way, 방향, OSM, SUMO)", m)
    s = rep["speed"]
    print(f"4) 제한속도    : 태그 일치 {s['tagged_match']} · 불일치 {s['tagged_mismatch']}")
    for m in s["list"]:
        print("     ", m)
    g = rep["geometry_m"]
    print(f"5) 선형 오차   : 엣지 {g['edges']}개 · 중앙값 {g['p50']} m · 95% {g['p95']} m · "
          f"99% {g['p99']} m · 최대 {g['max']} m")
    for m in g["over_5m"]:
        print("     ", m)
    sg = rep["signals"]
    print(f"6) 신호        : OSM 신호노드 {sg['osm_signal_nodes']} · SUMO 신호 {sg['sumo_tls']} · "
          f"OSM 신호인데 SUMO 신호 없음 {sg['osm_signals_without_sumo_tls']} · "
          f"OSM에 없는데 추정 추가 {sg['sumo_tls_without_osm_signal(guessed)']}")
    gs = rep["grade_separation"]
    print(f"7) 입체 교차   : 서로 다른 층 도로를 평면으로 합친 교차로 {gs['false_at_grade_junctions']}건")
    for m in gs["list"]:
        print("     ", m)
    print(f"8) 회전 제한   : 원본 OSM restriction relation {raw_has_restr}개")
    os.makedirs(os.path.dirname(a.save), exist_ok=True)
    with open(a.save, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
