"""road_config.py → SUMO 파일 자동 생성 (영등포 ~ 여의도).

파이프라인
    data/osm/region.osm (tools/fetch_osm.py)
        │ 1) netconvert 1차: OSM → 도로망 (국내 제한속도 타입맵, 교차로 병합, 신호 추정,
        │                    램프·회전교차로 추정, 고립 도로 제거)  → plain XML
        │ 2) plain XML 보정: 신호교차로를 '적색 우회전 허용' 유형으로, 사용자 패치 반영
        │ 3) netconvert 2차: plain XML → ydp.net.xml (최종 도로망)
        │ 4) osm_prep:      건물·한강·공원 multipolygon 조립 → ydp.poly.xml (층수별 건물 색)
        │ 5) 교통 수요:     vType 믹스 + randomTrips/duarouter → ydp.rou.xml
        │ 6) AV 과제 경로:  AV_TASKS(도로 이름) → av_routes.json
        ▼ 7) ydp.sumocfg / ydp.gui.xml
사용법
    python -m env.road_builder            # 전체 생성
    python -m env.road_builder --only net # net | poly | traffic | av
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

if "SUMO_HOME" not in os.environ:
    for cand in (r"C:\Program Files (x86)\Eclipse\Sumo", r"C:\Program Files\Eclipse\Sumo",
                 "/usr/share/sumo", "/opt/homebrew/share/sumo"):
        if os.path.isdir(cand):
            os.environ["SUMO_HOME"] = cand
            break
    else:
        try:   # pip install eclipse-sumo
            import sumo as _sumo_pkg
            os.environ["SUMO_HOME"] = _sumo_pkg.SUMO_HOME
        except ImportError:
            pass
sys.path.append(os.path.join(os.environ.get("SUMO_HOME", ""), "tools"))
import sumolib  # noqa: E402
from sumolib import checkBinary  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_config import REGION, NETWORK, BUILDINGS, TRAFFIC, EGO, AV_TASKS  # noqa: E402

OUT = os.path.join(BASE, "env", "sumo")
NAME = "ydp"
PATCH_DIR = os.path.join(BASE, "env", "patches")   # 수작업 보정(선택): *.nod.xml / *.edg.xml / *.con.xml
P = lambda *a: os.path.join(OUT, *a)  # noqa: E731


def _rel(arg):
    """절대경로 인자(쉼표 목록 포함)를 OUT 기준 상대경로로 바꾼다."""
    def one(x):
        return os.path.relpath(x, OUT).replace("\\", "/") if os.path.isabs(x) and os.path.exists(os.path.dirname(x) or x) else x
    if "," in arg and all(os.path.isabs(p) for p in arg.split(",")):
        return ",".join(one(p) for p in arg.split(","))
    return one(arg)


def _run(cmd, log_name):
    log = P(f"{log_name}.log")
    print("  $", " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))[:220])
    with open(log, "w", encoding="utf-8") as f:
        # SUMO(Windows)는 한글 등 비ASCII 경로를 못 다루므로 OUT 폴더에서 상대경로로 실행
        cmd = [cmd[0]] + [_rel(c) for c in cmd[1:]]
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=OUT)
    if r.returncode != 0:
        with open(log, encoding="utf-8", errors="replace") as f:
            tail = f.read()[-3000:]
        raise RuntimeError(f"{os.path.basename(cmd[0])} 실패 (로그: {log})\n{tail}")
    return log


# ──────────────────────────────────────────────────────────────
# 1) 타입맵: OSM 도로 등급 → 국내 제한속도 / 우선순위
# ──────────────────────────────────────────────────────────────
def write_typemap():
    src = os.path.join(os.environ["SUMO_HOME"], "data", "typemap", "osmNetconvert.typ.xml")
    tree = ET.parse(src)
    root = tree.getroot()
    speeds = NETWORK["default_speed_kmh"]
    for t in root.findall("type"):
        tid = t.get("id", "")
        if tid.startswith("highway."):
            cls = tid.split(".", 1)[1]
            if cls in speeds:
                t.set("speed", f"{speeds[cls] / 3.6:.2f}")
            if cls in NETWORK.get("default_lanes", {}):
                t.set("numLanes", str(NETWORK["default_lanes"][cls]))
            t.set("width", str(NETWORK["lane_width"]))
    path = P("osm_ko.typ.xml")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


# ──────────────────────────────────────────────────────────────
# 2) 도로망
# ──────────────────────────────────────────────────────────────
def build_net():
    osm = os.path.join(BASE, REGION["osm_file"])
    if not os.path.exists(osm):
        raise FileNotFoundError(f"{osm} 없음 — 먼저 `python tools/fetch_osm.py` 실행")
    # 영역 경계에서 도로를 잘라낸 OSM (env/osm_prep.py)
    from env.osm_prep import clip_roads
    clipped = P(f"{NAME}.roads.osm")
    nw, nb = clip_roads(osm, clipped, REGION["bbox"], NETWORK.get("osm_fixes", {}))
    print(f"  OSM 도로 클리핑: way {nw}개, 경계 노드 {nb}개")
    osm = clipped
    for stale in (f"{NAME}.tls.xml", f"{NAME}.tls_webster.xml"):   # 이전 도로망 기준 신호 파일 무효화
        if os.path.exists(P(stale)):
            os.remove(P(stale))
    typemap = write_typemap()
    keep_types = ",".join(f"highway.{t}" for t in NETWORK["road_types"])
    plain = P("plain", NAME)
    os.makedirs(P("plain"), exist_ok=True)

    common = [
        "--type-files", typemap,
        "--default.lanewidth", str(NETWORK["lane_width"]),
        "--no-turnarounds.except-deadend", "true",   # 국내: 유턴은 지정 장소만
        "--junctions.corner-detail", "5",
        "--junctions.limit-turn-speed", "5.5",
        "--rectangular-lane-cut", "true",
        "--tls.cycle.time", str(NETWORK["tls_cycle"]),
        "--tls.yellow.time", str(NETWORK["tls_yellow"]),
        "--tls.left-green.time", str(NETWORK["tls_left_green"]),
        "--tls.minor-left.max-speed", str(NETWORK.get("tls_minor_left_max_speed", 19.44)),
        "--tls.default-type", "static",
        # 국내 간선 교차로의 일반적인 운영: 접근로별 동시신호(직진+좌회전 함께) → 비보호 좌회전 상충 제거
        "--tls.layout", NETWORK.get("tls_layout", "incoming"),
        "--output.street-names", "true",
        "--output.original-names", "true",
        "--no-warnings", "true",
    ]
    if not NETWORK.get("right_before_left", True):
        common += ["--junctions.right-before-left.speed-threshold", "0"]
    # ── 1차: OSM → 정리된 plain XML ──
    cmd1 = [checkBinary("netconvert"), "--osm-files", osm,
            "--keep-edges.by-type", keep_types,
            "--keep-edges.by-vclass", "passenger",
            "--remove-edges.isolated", "true",
            "--geometry.remove", "true",
            "--roundabouts.guess", "true",
            "--ramps.guess", "true",
            "--junctions.join", "true",
            "--junctions.join-dist", str(NETWORK["junction_join_dist"]),
            # OSM 신호 태그(highway=traffic_signals) + 태그가 빠진 간선 교차로는 추정
            "--tls.guess-signals", "true",
            "--tls.guess-signals.dist", "25",
            "--tls.guess", "true",
            "--tls.guess.threshold", str(NETWORK.get("tls_guess_threshold", 90)),
            "--tls.guess.joining", "true",
            "--tls.discard-simple", "true",
            "--tls.join", "true",
            "--tls.join-dist", "30",
            "--osm.turn-lanes", "true",
            "--osm.lane-access", "false",
            "--edges.join", "true",
            "--proj.utm", "true",
            "--plain-output-prefix", plain,
            "-o", P(f"{NAME}.stage1.net.xml")] + common
    if NETWORK.get("keep_main_component", True):
        cmd1 += ["--keep-edges.components", "1"]
    _run(cmd1, "netconvert_stage1")

    # ── plain XML 보정 ──
    nod = f"{plain}.nod.xml"
    stage1 = sumolib.net.readNet(P(f"{NAME}.stage1.net.xml"), withInternal=False)
    tree = ET.parse(nod)
    root = tree.getroot()
    nodes = {n.get("id"): n for n in root.iter("node")}
    # (a) 교차점 강제 병합 — 영등포 로터리처럼 OSM에서 쪼개진 교차로
    joined_tls = set()
    #   입체 교차 보호: 평면(layer 0) 도로가 하나도 지나지 않는 노드(고가·지하차도 위의
    #   합류점 등)는 반경 안에 있어도 병합하지 않는다. (여의교 북단: 여의대방로 고가의
    #   램프 합류점이 평면 교차로에 섞여 고가 차량이 신호를 받던 오류)
    from env.osm_prep import OSM, way_layer
    node_layers = {}
    for refs, tags, _ in OSM(osm).ways.values():
        if "highway" in tags:
            for r in refs:
                node_layers.setdefault(r, set()).add(way_layer(tags))
    for cl in NETWORK.get("join_clusters", []):
        cx, cy = stage1.convertLonLat2XY(*cl["lonlat"])
        members = []
        for nid, n in nodes.items():
            x, y = float(n.get("x")), float(n.get("y"))
            if math.hypot(x - cx, y - cy) <= cl["radius"] and \
                    len(stage1.getNode(nid).getIncoming()) + len(stage1.getNode(nid).getOutgoing()) > 2:
                if 0 not in node_layers.get(nid, {0}):
                    print(f"    {cl['name']}: 입체 노드 {nid} (층 {sorted(node_layers[nid])}) 병합 제외")
                    continue
                members.append(nid)
        if len(members) >= 2:
            ET.SubElement(root, "join", nodes=" ".join(members))
            for m in members:
                nodes[m].set("type", "traffic_light")
                nodes[m].attrib.pop("tl", None)
                joined_tls.add(m)
            print(f"  교차점 병합: {cl['name']} ← {len(members)}개 점")
    # (b) 신호 현시 구조 (교차로별)
    #   간선×간선 교차로 → 'incoming'(접근로별 동시신호, 좌회전 상충 없음)
    #   간선×이면도로 / 횡단보도 신호 → 'opposites'(간선 양방향 동시 녹색) — 간선 용량 확보
    n_major = n_minor = 0
    for nid, n in nodes.items():
        if not n.get("type", "").startswith("traffic_light") or nid in joined_tls:
            continue
        try:
            inc = stage1.getNode(nid).getIncoming()
        except KeyError:
            continue
        major = sum(1 for e in inc if e.getPriority() >= 10)   # tertiary 이상
        if major >= 3:
            n.set("tlLayout", "incoming")
            n_major += 1
        else:
            n.set("tlLayout", "opposites")
            n_minor += 1
    print(f"  신호 현시: 간선교차 {n_major}곳(방향별 동시신호) · 간선-이면/횡단보도 {n_minor}곳(양방향 동시)")
    # (b2) 신호 태그가 빠진 간선 교차로를 신호교차로로 지정 (NETWORK["force_tls"])
    for ft in NETWORK.get("force_tls", []):
        fx, fy = stage1.convertLonLat2XY(*ft["lonlat"])
        cand = [(math.hypot(float(n.get("x")) - fx, float(n.get("y")) - fy), nid)
                for nid, n in nodes.items()]
        d, nid = min(cand)
        if d <= ft.get("radius", 30) and not nodes[nid].get("type", "").startswith("traffic_light"):
            nodes[nid].set("type", "traffic_light")
            nodes[nid].set("tlLayout", "incoming")
            nodes[nid].attrib.pop("tl", None)
            print(f"  신호 지정: {ft['name']} ({nid})")
    # (c) 적색 우회전
    if NETWORK.get("right_on_red", True):
        n = 0
        for node in nodes.values():
            if node.get("type") == "traffic_light":
                node.set("type", "traffic_light_right_on_red")
                n += 1
        print(f"  적색 우회전 허용 신호 노드: {n}곳")
    tree.write(nod, encoding="utf-8", xml_declaration=True)

    # ── 2차: plain XML (+ 수작업 패치) → 최종 net ──
    #   신호 현시(tll)는 병합·유형 변경을 반영해 다시 만든다 (노드의 tl 속성으로 신호 묶음은 유지)
    files = {"n": [nod], "e": [f"{plain}.edg.xml"], "x": [f"{plain}.con.xml"],
             "t": [f"{plain}.typ.xml"]}
    if os.path.isdir(PATCH_DIR):
        for f in sorted(os.listdir(PATCH_DIR)):
            for key, ext in (("n", ".nod.xml"), ("e", ".edg.xml"), ("x", ".con.xml"), ("i", ".tll.xml")):
                if f.endswith(ext):
                    files[key].append(os.path.join(PATCH_DIR, f))
    cmd2 = [checkBinary("netconvert"), "--offset.disable-normalization", "true",
            "--tls.rebuild", "true"]
    for key, lst in files.items():
        lst = [x for x in lst if os.path.exists(x)]
        if lst:
            cmd2 += [f"-{key}", ",".join(lst)]
    cmd2 += ["-o", P(f"{NAME}.net.xml")] + [c for c in common if c != typemap and c != "--type-files"]
    _run(cmd2, "netconvert_stage2")
    if NETWORK.get("minor_left_ban_speed"):
        banned = _ban_fast_permissive_left(P(f"{NAME}.net.xml"), f"{plain}.con.xml",
                                           NETWORK["minor_left_ban_speed"])
        print(f"  고속 다차로 횡단 비보호 좌회전 금지: {len(banned)}곳")
        if banned:
            _run(cmd2, "netconvert_stage2")
    os.remove(P(f"{NAME}.stage1.net.xml"))
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
    tls = len(net.getTrafficLights())
    length = sum(e.getLength() * e.getLaneNumber() for e in net.getEdges()) / 1000
    print(f"  도로망: 엣지 {len(net.getEdges())} · 교차로 {len(net.getNodes())} · "
          f"신호 {tls} · 차로 총연장 {length:.1f} km")
    return net


def _ban_fast_permissive_left(net_path, con_path, ban_v):
    """(d) 고속·다차로를 가로지르는 비보호 좌회전 제거.

    도로교통법상 신호교차로의 좌회전은 좌회전 신호(보호) 또는 '비보호 좌회전' 표지가 있는 곳에서만
    가능하다. OSM에는 표지 정보가 없으므로, 녹색 화살표('G')가 한 번도 없이 비보호('g')로만
    열리는 좌회전 중 반대편이 고속(≥ ban_v)·다차로(≥3)인 것은 금지로 본다.
    (예: 노들로 70 km/h 3차로를 가로지르는 비보호 좌회전 → 좌회전 대기차-직진차 충돌 다발)
    """
    netp = sumolib.net.readNet(net_path, withInternal=False, withPrograms=True)
    banned = set()
    for tl in netp.getTrafficLights():
        progs = list(tl.getPrograms().values())
        if not progs:
            continue
        phases = [ph.state for ph in progs[0].getPhases()]
        for inl, outl, idx in tl.getConnections():
            e_in, e_out = inl.getEdge(), outl.getEdge()
            conns = e_in.getConnections(e_out)
            if not conns or conns[0].getDirection() not in ("l", "L"):
                continue
            states = {p[idx] for p in phases if idx < len(p)}
            if "G" in states or "g" not in states:
                continue
            node = e_in.getToNode()
            if any(o != e_in and o.getSpeed() >= ban_v and o.getLaneNumber() >= 3
                   and o.getFromNode() != e_out.getToNode() for o in node.getIncoming()):
                banned.add((e_in.getID(), e_out.getID()))
    if banned:
        tree = ET.parse(con_path)
        for f, t in sorted(banned):
            ET.SubElement(tree.getroot(), "delete", attrib={"from": f, "to": t})
        tree.write(con_path, encoding="utf-8", xml_declaration=True)
    return banned


# ──────────────────────────────────────────────────────────────
# 3) 건물 · 배경 폴리곤
# ──────────────────────────────────────────────────────────────
def build_poly():
    if not BUILDINGS.get("enabled", True):
        return
    from env.osm_prep import build_polygons
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
    counts = build_polygons(os.path.join(BASE, REGION["osm_file"]), P(f"{NAME}.poly.xml"),
                            net.convertLonLat2XY, REGION["bbox"], BUILDINGS["level_colors"],
                            landuse=BUILDINGS.get("landuse", True))
    print("  폴리곤: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda t: -t[1])))

# ──────────────────────────────────────────────────────────────
# 4) 차량 타입 + 교통 수요
# ──────────────────────────────────────────────────────────────
def write_vtypes():
    ctrl = TRAFFIC["controllers"]
    tot = sum(c["probability"] for c in ctrl.values())
    lc = " ".join(f'{k}="{v}"' for k, v in TRAFFIC["lane_change"].items())
    lines = ['<additional>',
             f'    <vType id="ego_type" vClass="passenger" accel="{EGO["accel"]}" decel="{EGO["decel"]}" '
             f'emergencyDecel="9" maxSpeed="{EGO["max_speed"]}" length="{EGO["length"]}" '
             f'color="{EGO["color"]}" carFollowModel="Krauss" sigma="0" guiShape="passenger/sedan"/>',
             # 경로 고정 AV: 동적 재경로 장치를 달지 않아 지정한 경로(예: 여의도 한 바퀴 투어)를 그대로 따른다.
             #   기본 ego_type 은 HV와 같이 60 s 재경로(내비게이션)가 적용되어 목적지까지의 빠른 길로 바뀔 수 있다.
             f'    <vType id="ego_type_fixed" vClass="passenger" accel="{EGO["accel"]}" decel="{EGO["decel"]}" '
             f'emergencyDecel="9" maxSpeed="{EGO["max_speed"]}" length="{EGO["length"]}" '
             f'color="{EGO["color"]}" carFollowModel="Krauss" sigma="0" guiShape="passenger/sedan">'
             '<param key="has.rerouting.device" value="false"/></vType>',
             '    <vTypeDistribution id="hv_mix">']
    for name, c in ctrl.items():
        vclass = c.get("vClass", "passenger")
        shape = {"bus": "bus", "truck": "truck"}.get(vclass, "passenger")
        a = [f'id="hv_{name}"', f'probability="{c["probability"] / tot:.4f}"',
             f'vClass="{vclass}"', f'carFollowModel="{c["carFollowModel"]}"',
             f'accel="{c["accel"]}"', f'decel="{c["decel"]}"', 'emergencyDecel="9"',
             f'tau="{c["tau"]}"', f'minGap="{c["min_gap"]}"',
             f'speedFactor="normc({c["speed_factor"]},{c["speed_dev"]},0.6,1.4)"',
             f'color="{c["color"]}"', f'guiShape="{shape}"', 'lcStrategic="1.0"']
        if "sigma" in c:
            a.append(f'sigma="{c["sigma"]}"')
        if "length" in c:
            a.append(f'length="{c["length"]}"')
        a.append(lc.replace('lcStrategic="1.0" ', ""))
        # 신호 진입 직전 황색에서 무리하게 통과하지 않도록
        a.append('jmDriveAfterYellowTime="0.5" jmStoplineGap="1.0"')
        lines.append(f'        <vType {" ".join(a)}/>')
    lines += ['    </vTypeDistribution>', '</additional>', '']
    path = P(f"{NAME}.vtypes.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def build_tls():
    """신호 시간 최적화: (1) Webster 식으로 교통량에 맞춘 주기·녹색시간 배분
    (2) 간선축 녹색 신호 연동(offset). 결과는 ydp.tls.xml (sumocfg의 additional)."""
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    web = P(f"{NAME}.tls_webster.xml")
    _run([sys.executable, os.path.join(tools, "tlsCycleAdaptation.py"),
          "-n", P(f"{NAME}.net.xml"), "-r", P(f"{NAME}.rou.xml"), "-o", web,
          "-b", "0", "-y", str(NETWORK["tls_yellow"]), "-a", "2", "-l", "4",
          "-g", "8", "--min-cycle", str(NETWORK.get("tls_min_cycle", 60)),
          "--max-cycle", str(NETWORK.get("tls_max_cycle", 160)), "-p", "webster"],
         "tlsCycleAdaptation")
    offs = P(f"{NAME}.tls_offsets.xml")
    _run([sys.executable, os.path.join(tools, "tlsCoordinator.py"),
          "-n", P(f"{NAME}.net.xml"), "-r", P(f"{NAME}.rou.xml"), "-a", web,
          "-o", offs], "tlsCoordinator")
    # tlsCoordinator 는 offset만 출력 → Webster 프로그램에 합친다
    offset = {t.get("id"): t.get("offset") for t in ET.parse(offs).getroot().iter("tlLogic")}
    tree = ET.parse(web)
    progs = 0
    for t in tree.getroot().iter("tlLogic"):
        cyc = sum(float(p.get("duration")) for p in t.findall("phase"))
        o = float(offset.get(t.get("id"), 0) or 0)
        t.set("offset", f"{o % cyc:.1f}" if cyc > 0 else "0")
        progs += 1
    tree.write(P(f"{NAME}.tls.xml"), encoding="utf-8", xml_declaration=True)
    for f in (web, offs):
        os.remove(f)
    cycles = [sum(float(p.get("duration")) for p in t.findall("phase"))
              for t in tree.getroot().iter("tlLogic")]
    print(f"  신호 최적화(Webster) + 녹색 연동: {progs}개 신호 · 주기 "
          f"{min(cycles):.0f}~{max(cycles):.0f} s (평균 {sum(cycles) / len(cycles):.0f} s)")


def build_traffic():
    vtypes = write_vtypes()
    rt = os.path.join(os.environ["SUMO_HOME"], "tools", "randomTrips.py")
    trips = P(f"{NAME}.trips.xml")
    cmd = [sys.executable, rt, "-n", P(f"{NAME}.net.xml"),
           "-o", trips, "-r", P(f"{NAME}.rou.xml"),
           "-b", str(TRAFFIC["begin"]), "-e", str(TRAFFIC["end"]),
           "-p", str(TRAFFIC["period"]), "--seed", str(TRAFFIC["seed"]),
           "--fringe-factor", str(TRAFFIC["fringe_factor"]),
           "--min-distance", str(TRAFFIC["min_trip_distance"]),
           "--vclass", "passenger", "--validate", "--remove-loops",
           "--trip-attributes", 'type="hv_mix" departLane="best" departSpeed="max"',
           "--additional-file", vtypes, "--prefix", "hv"]
    if TRAFFIC.get("through_bias", True):
        cmd += ["--lanes", "--speed-exponent", "1.5"]
    _run(cmd, "randomTrips")
    # duarouter가 vType 정의를 rou.xml에도 복사하므로 제거 (vtypes.xml 한 곳에서만 정의)
    with open(P(f"{NAME}.rou.xml"), encoding="utf-8") as f:
        txt = f.read()
    txt = re.sub(r"\s*<vTypeDistribution\b.*?</vTypeDistribution>", "", txt, flags=re.S)
    txt = re.sub(r"\s*<vType\b[^>]*/>", "", txt)
    txt = re.sub(r"\s*<vType\b.*?</vType>", "", txt, flags=re.S)
    with open(P(f"{NAME}.rou.xml"), "w", encoding="utf-8") as f:
        f.write(txt)
    build_tls()
    n = sum(1 for _ in sumolib.xml.parse_fast(P(f"{NAME}.rou.xml"), "vehicle", ["id"]))
    print(f"  일반 차량 경로 {n}대 ({n * 3600 / max(1, TRAFFIC['end'] - TRAFFIC['begin']):.0f} 대/h)")
    for f in (trips, P(f"{NAME}.rou.alt.xml")):
        if os.path.exists(f):
            os.remove(f)


# ──────────────────────────────────────────────────────────────
# 5) AV 과제 경로 (위경도 출발/도착점 + 도로 이름 힌트 → 최단 시간 경로)
# ──────────────────────────────────────────────────────────────
def _edges_near(net, lon, lat, hint, radius=80.0):
    x, y = net.convertLonLat2XY(lon, lat)
    near = net.getNeighboringEdges(x, y, radius)
    out = []
    for e, d in sorted(near, key=lambda t: t[1]):
        if not e.allows("passenger") or e.getFunction() == "internal":
            continue
        if hint and hint not in (e.getName() or ""):
            continue
        out.append((e, d))
    return out[:8]


def build_av_routes(net=None):
    net = net or sumolib.net.readNet(P(f"{NAME}.net.xml"))
    fastest = getattr(net, "getFastestPath", None)
    out, report = {}, []
    for task in AV_TASKS:
        tid = task["id"]
        best = None
        starts = _edges_near(net, *task["from"])
        ends = _edges_near(net, *task["to"])
        for s, ds in starts:
            for d, dd in ends:
                if s == d:
                    continue
                if fastest:
                    path, cost = fastest(s, d, vClass="passenger")
                else:
                    path, cost = net.getShortestPath(s, d, vClass="passenger")
                if not path:
                    continue
                score = cost + (ds + dd) * 0.5   # 지정점에 가까운 엣지 선호
                if best is None or score < best[1]:
                    best = (path, score)
        if best is None:
            report.append(f"  [경고] {tid}: 경로 없음 (출발 후보 {len(starts)}, 도착 후보 {len(ends)})")
            continue
        path = best[0]
        length = sum(e.getLength() for e in path)
        tls = sum(1 for e in path if e.getToNode().getType().startswith("traffic_light"))
        names = []
        for e in path:
            n = e.getName()
            if n and (not names or names[-1] != n):
                names.append(n)
        out[tid] = {"edges": [e.getID() for e in path], "desc": task["desc"],
                    "length_m": round(length, 1), "signals": tls, "streets": names}
        report.append(f"  {tid:20s} {length / 1000:5.2f} km · 신호 {tls:2d}곳 · {' → '.join(names[:7])}")
    with open(P("av_routes.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n".join(report))
    return out

# ──────────────────────────────────────────────────────────────
# 6) sumocfg / GUI 설정
# ──────────────────────────────────────────────────────────────
def write_cfg():
    add = [f"{NAME}.vtypes.xml"]
    if os.path.exists(P(f"{NAME}.tls.xml")):
        add.append(f"{NAME}.tls.xml")
    if os.path.exists(P(f"{NAME}.poly.xml")):
        add.append(f"{NAME}.poly.xml")
    rt = TRAFFIC.get("runtime", {})
    reroute = ""
    if rt.get("rerouting_period"):
        reroute = (f'\n        <device.rerouting.probability value="1"/>'
                   f'\n        <device.rerouting.period value="{rt["rerouting_period"]}"/>'
                   f'\n        <device.rerouting.adaptation-steps value="18"/>')
    cfg = f"""<configuration>
    <input>
        <net-file value="{NAME}.net.xml"/>
        <route-files value="{NAME}.rou.xml"/>
        <additional-files value="{",".join(add)}"/>
    </input>
    <time>
        <begin value="0"/>
        <step-length value="0.1"/>
    </time>
    <processing>
        <time-to-teleport value="{TRAFFIC['time_to_teleport']}"/>
        <collision.check-junctions value="true"/>
        <collision.action value="{rt.get('collision_action', 'warn')}"/>
        <ignore-route-errors value="true"/>
        <default.speeddev value="0.1"/>{reroute}
        <lateral-resolution value="0"/>
    </processing>
    <random_number>
        <seed value="{TRAFFIC['seed']}"/>
    </random_number>
    <report>
        <no-step-log value="true"/>
    </report>
    <gui_only>
        <gui-settings-file value="{NAME}.gui.xml"/>
    </gui_only>
</configuration>
"""
    with open(P(f"{NAME}.sumocfg"), "w", encoding="utf-8") as f:
        f.write(cfg)
    # 여의도 중심 뷰 (net 좌표)
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
    cx, cy = net.convertLonLat2XY(126.9245, 37.5235)
    gui = f"""<viewsettings>
    <scheme name="real world"/>
    <viewport zoom="180" x="{cx:.1f}" y="{cy:.1f}"/>
    <delay value="20"/>
</viewsettings>
"""
    with open(P(f"{NAME}.gui.xml"), "w", encoding="utf-8") as f:
        f.write(gui)


def build(only=None):
    os.makedirs(OUT, exist_ok=True)
    steps = [only] if only else ["net", "poly", "traffic", "av"]
    net = None
    if "net" in steps:
        print("[1/4] 도로망 (netconvert)")
        net = build_net()
    if "poly" in steps:
        print("[2/4] 건물·배경 폴리곤")
        build_poly()
    if "traffic" in steps:
        print("[3/4] 일반 차량 수요 (randomTrips)")
        build_traffic()
    if "av" in steps:
        print("[4/4] AV 과제 경로")
        build_av_routes(net)
    write_cfg()
    print(f"완료 → {P(NAME + '.sumocfg')}")
    return P(f"{NAME}.sumocfg")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["net", "poly", "traffic", "av"])
    build(ap.parse_args().only)
