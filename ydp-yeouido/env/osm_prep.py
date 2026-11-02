"""OSM 원본 전처리 — road_builder.py 가 사용.

1) clip_roads():   도로(highway) way를 대상 영역(bbox) 경계에서 정확히 잘라
                   경계 위에 새 노드를 만든다. (OSM way는 영역 밖으로 수 km씩 이어지므로
                   그대로 쓰면 올림픽대로·강변북로가 영역 밖까지 뻗어나간다)
2) build_polygons(): 건물·한강·공원·토지이용 폴리곤을 직접 조립해 SUMO poly 파일로 저장.
                   - multipolygon relation(한강 등)의 outer/inner 링을 조립
                   - 영역 경계로 클리핑
                   - SUMO 폴리곤은 구멍(hole)을 지원하지 않으므로, 수면의 inner 링(여의도·선유도·밤섬)은
                     땅 색 폴리곤을 한 층 위에 덮어 표현
                   - 건물은 층수(building:levels / height)로 색·레이어 구분
"""
import math
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

from shapely.geometry import LineString, Polygon, MultiPolygon, box
from shapely.geometry import MultiLineString
from shapely.ops import linemerge, unary_union, polygonize, split


# ──────────────────────────────────────────────────────────────
# OSM 읽기
# ──────────────────────────────────────────────────────────────
class OSM:
    def __init__(self, path):
        self.root = ET.parse(path).getroot()
        self.nodes = {}       # id -> (lon, lat)
        self.node_el = {}
        self.ways = {}        # id -> (refs, tags, element)
        self.rels = []        # (id, members, tags)
        for n in self.root.iter("node"):
            nid = n.get("id")
            self.nodes[nid] = (float(n.get("lon")), float(n.get("lat")))
            self.node_el[nid] = n
        for w in self.root.iter("way"):
            refs = [nd.get("ref") for nd in w.findall("nd")]
            tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
            self.ways[w.get("id")] = (refs, tags, w)
        for r in self.root.iter("relation"):
            mem = [(m.get("type"), m.get("ref"), m.get("role")) for m in r.findall("member")]
            tags = {t.get("k"): t.get("v") for t in r.findall("tag")}
            self.rels.append((r.get("id"), mem, tags))


def way_layer(tags):
    """OSM way의 층: layer 태그 우선, 없으면 교량 +1 / 지하차도 -1 / 평면 0."""
    if "layer" in tags:
        try:
            return int(float(tags["layer"].split(";")[0]))
        except ValueError:
            pass
    if tags.get("tunnel") in ("yes", "building_passage") or tags.get("covered") == "yes":
        return -1
    if tags.get("bridge", "no") != "no":
        return 1
    return 0


# ──────────────────────────────────────────────────────────────
# 1) 도로 클리핑
# ──────────────────────────────────────────────────────────────
def _inside(p, bb):
    w, s, e, n = bb
    return w <= p[0] <= e and s <= p[1] <= n


def _cross(p, q, bb):
    """선분 p→q 가 bbox 경계와 만나는 점 (p 안 / q 밖 또는 반대)."""
    w, s, e, n = bb
    best = None
    for axis, val in ((0, w), (0, e), (1, s), (1, n)):
        d = q[axis] - p[axis]
        if abs(d) < 1e-12:
            continue
        t = (val - p[axis]) / d
        if 0 <= t <= 1:
            x = p[0] + t * (q[0] - p[0])
            y = p[1] + t * (q[1] - p[1])
            if w - 1e-9 <= x <= e + 1e-9 and s - 1e-9 <= y <= n + 1e-9:
                if best is None or t < best[0]:
                    best = (t, (x, y))
    return best[1] if best else None


def clip_roads(osm_path, out_path, bbox_snwe, fixes=None):
    s, w, n, e = bbox_snwe
    bb = (w, s, e, n)
    osm = OSM(osm_path)
    out = ET.Element("osm", version="0.6", generator="osm_prep.clip_roads")
    used_nodes = set()
    new_nodes = {}         # id -> (lon, lat)
    new_ways = []
    nid_counter = [9_000_000_000_000]
    wid_counter = [9_000_000_000_000]

    def boundary_node(pt):
        key = (round(pt[0], 7), round(pt[1], 7))
        for k, v in new_nodes.items():
            if v == key:
                return k
        nid_counter[0] += 1
        nid = str(nid_counter[0])
        new_nodes[nid] = key
        return nid

    kept_way_ids = set()
    fixes = fixes or {}
    for wid, (refs, tags, el) in osm.ways.items():
        if wid in fixes:                 # OSM 태그 오류 수동 보정
            tags = {**tags, **fixes[wid]}
        # 도로명 단위 보정 ("name:국회대로": {...}) — lanes 태그가 없는 way에만 적용
        nfix = fixes.get(f"name:{tags.get('name', '')}")
        if nfix and not ({"lanes", "lanes:forward", "lanes:backward"} & set(tags)):
            tags = {**tags, **nfix}
        if "highway" not in tags or any(r not in osm.nodes for r in refs):
            continue
        pts = [osm.nodes[r] for r in refs]
        ins = [_inside(p, bb) for p in pts]
        if all(ins):
            new_ways.append((wid, refs, tags))
            used_nodes.update(refs)
            kept_way_ids.add(wid)
            continue
        # 영역 안쪽 구간(run)들로 분할 (노드가 전부 밖인 way는 버림)
        runs, cur = [], []
        for i, r in enumerate(refs):
            if ins[i]:
                if not cur and i > 0:          # 밖 → 안 : 경계 노드 삽입
                    c = _cross(pts[i], pts[i - 1], bb)
                    if c:
                        cur.append(boundary_node(c))
                cur.append(r)
            else:
                if cur:                         # 안 → 밖 : 경계 노드 삽입 후 끊기
                    c = _cross(pts[i - 1], pts[i], bb)
                    if c:
                        cur.append(boundary_node(c))
                    runs.append(cur)
                    cur = []
        if cur:
            runs.append(cur)
        for run in runs:
            if len(run) < 2:
                continue
            wid_counter[0] += 1
            new_ways.append((str(wid_counter[0]), run, tags))
            used_nodes.update(x for x in run if x in osm.nodes)

    for nid in sorted(used_nodes, key=int):
        src = osm.node_el[nid]
        out.append(src)
    for nid, (lon, lat) in new_nodes.items():
        ET.SubElement(out, "node", id=nid, lat=f"{lat:.7f}", lon=f"{lon:.7f}", version="1")
    for wid, refs, tags in new_ways:
        we = ET.SubElement(out, "way", id=wid, version="1")
        for r in refs:
            ET.SubElement(we, "nd", ref=r)
        for k, v in tags.items():
            ET.SubElement(we, "tag", k=k, v=v)
    # 회전 제한(turn restriction) relation — 참조 way가 그대로 남은 것만 유지
    for rid, mem, tags in osm.rels:
        if tags.get("type") != "restriction":
            continue
        if all((t != "way") or (ref in kept_way_ids) for t, ref, _ in mem) and \
           all((t != "node") or (ref in used_nodes) for t, ref, _ in mem):
            re_ = ET.SubElement(out, "relation", id=rid, version="1")
            for t, ref, role in mem:
                ET.SubElement(re_, "member", type=t, ref=ref, role=role)
            for k, v in tags.items():
                ET.SubElement(re_, "tag", k=k, v=v)
    ET.ElementTree(out).write(out_path, encoding="utf-8", xml_declaration=True)
    return len(new_ways), len(new_nodes)


# ──────────────────────────────────────────────────────────────
# 2) 폴리곤 (건물 · 수면 · 녹지 · 토지이용)
# ──────────────────────────────────────────────────────────────
#   (분류명, RGB, layer, fill)
STYLE = {
    "water":       ((150, 195, 225), -9.0, True),
    "island":      ((238, 236, 230), -8.5, True),   # 수면의 inner 링(여의도·선유도·밤섬)
    "landuse":     ((236, 233, 226), -8.0, True),
    "commercial":  ((240, 229, 226), -8.0, True),
    "industrial":  ((232, 227, 235), -8.0, True),
    "railway_area": ((218, 212, 206), -7.9, True),
    "green":       ((200, 228, 180), -7.0, True),
    "park":        ((190, 226, 170), -6.9, True),
    "pitch":       ((170, 214, 160), -6.5, True),
    "parking":     ((224, 224, 224), -6.0, True),
    "railway":     ((115, 115, 115), -5.0, False),
}


def classify(tags):
    if tags.get("building") or tags.get("building:part"):
        return "building"
    nat, lu, lei, ww = tags.get("natural"), tags.get("landuse"), tags.get("leisure"), tags.get("waterway")
    if nat == "water" or ww in ("riverbank", "dock") or lu in ("reservoir", "basin"):
        return "water"
    if lei in ("park", "garden", "playground") or lu in ("recreation_ground", "village_green"):
        return "park"
    if lei in ("pitch", "golf_course", "sports_centre", "stadium", "track"):
        return "pitch"
    if nat in ("wood", "scrub", "grassland", "heath", "wetland") or \
       lu in ("grass", "forest", "meadow", "cemetery", "allotments", "orchard"):
        return "green"
    if lu in ("commercial", "retail"):
        return "commercial"
    if lu == "industrial":
        return "industrial"
    if lu == "railway":
        return "railway_area"
    if lu:
        return "landuse"
    if tags.get("amenity") == "parking":
        return "parking"
    if tags.get("railway") in ("rail", "light_rail") and tags.get("tunnel") not in ("yes",) \
            and tags.get("location") != "underground":
        return "railway"
    return None


def building_levels(tags):
    for k in ("building:levels", "levels"):
        m = re.match(r"\s*(\d+(\.\d+)?)", tags.get(k, "") or "")
        if m:
            return float(m.group(1))
    m = re.match(r"\s*(\d+(\.\d+)?)", tags.get("height", "") or "")
    if m:
        return float(m.group(1)) / 3.3
    return None


def _split_holes(pg, depth=0):
    """구멍 있는 폴리곤 → 구멍 없는 조각들 (SUMO poly는 hole 미지원).
    각 구멍의 중심을 지나는 세로선으로 잘라 구멍을 바깥과 연결시킨다."""
    if not pg.interiors or depth > 6:
        return [pg]
    minx, miny, maxx, maxy = pg.bounds
    cuts = MultiLineString([[(h.centroid.x, miny - 1), (h.centroid.x, maxy + 1)]
                            for h in pg.interiors])
    try:
        parts = split(pg, cuts).geoms
    except Exception:  # noqa: BLE001
        return [Polygon(pg.exterior)]
    out = []
    for p in parts:
        if isinstance(p, Polygon) and p.area > 1:
            out += _split_holes(p, depth + 1)
    return out


def _rings_from_ways(way_coords):
    """여러 조각 way → 닫힌 링 목록 (multipolygon 조립)."""
    lines = [LineString(c) for c in way_coords if len(c) >= 2]
    if not lines:
        return []
    merged = linemerge(lines)
    return list(polygonize(merged))


def build_polygons(osm_path, out_path, to_xy, bbox_snwe, level_colors, landuse=True,
                   simplify=0.4):
    s, w, n, e = bbox_snwe
    osm = OSM(osm_path)
    x0, y0 = to_xy(w, s)
    x1, y1 = to_xy(e, n)
    clip = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    cols = sorted(level_colors)

    def xy(refs):
        return [to_xy(*osm.nodes[r]) for r in refs if r in osm.nodes]

    items = []   # (layer, type, color, fill, coords, name, levels)

    def add_geom(geom, cls, tags, as_hole_land=True):
        geom = geom.intersection(clip) if not geom.within(clip) else geom
        if geom.is_empty:
            return
        polys = [geom] if isinstance(geom, Polygon) else \
            [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
        if cls != "building":
            polys = [q for p in polys for q in _split_holes(p)]
        for pg in polys:
            if pg.area < 4:
                continue
            pg = pg.simplify(simplify, preserve_topology=True)
            if cls == "building":
                lv = building_levels(tags)
                c = cols[0][1]
                for mn, rgb in cols:
                    if lv is not None and lv >= mn:
                        c = rgb
                layer = -1.0 + min(lv or 0, 70) / 100.0
                items.append((layer, "building", c, True, list(pg.exterior.coords),
                              tags.get("name", ""), lv))
            else:
                c, layer, fill = STYLE[cls]
                items.append((layer, cls, c, fill, list(pg.exterior.coords), tags.get("name", ""), None))

    # ── multipolygon relation ──
    rel_way_ids = set()
    for rid, mem, tags in osm.rels:
        if tags.get("type") not in ("multipolygon", "boundary"):
            continue
        cls = classify(tags)
        if cls is None or cls == "railway" or (cls != "building" and cls != "water" and not landuse):
            continue
        member_lines = [xy(osm.ways[ref][0]) for t, ref, role in mem
                        if t == "way" and ref in osm.ways and role in ("outer", "inner", "")]
        for t, ref, role in mem:
            if t == "way":
                rel_way_ids.add(ref)
        faces = _rings_from_ways(member_lines)
        if not faces:
            continue
        # even-odd 규칙: 링 외곽들을 대칭차집합으로 합친다 → role 태그가 틀려도
        # (outer 안의 inner = 구멍, 그 안의 섬 = 다시 채움) 올바르게 복원된다
        geom = None
        for f in faces:
            ext = Polygon(f.exterior)
            geom = ext if geom is None else geom.symmetric_difference(ext)
        if geom is None or geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        add_geom(geom, cls, tags)

    # ── 단일 way ──
    for wid, (refs, tags, _) in osm.ways.items():
        cls = classify(tags)
        if cls is None:
            continue
        if cls not in ("building", "water") and not landuse:
            continue
        if wid in rel_way_ids and not (set(tags) - {"source", "note"}):
            continue   # relation 멤버로만 쓰이는 태그 없는 way
        coords = xy(refs)
        if len(coords) < 2:
            continue
        if cls == "railway":
            ln = LineString(coords).intersection(clip)
            if ln.is_empty:
                continue
            parts = [ln] if ln.geom_type == "LineString" else list(getattr(ln, "geoms", []))
            c, layer, _ = STYLE["railway"]
            for p in parts:
                if p.geom_type == "LineString" and p.length > 5:
                    items.append((layer, "railway", c, False, list(p.coords), "", None))
            continue
        if refs[0] != refs[-1] or len(coords) < 4:
            continue
        pg = Polygon(coords)
        if not pg.is_valid:
            pg = pg.buffer(0)
        add_geom(pg, cls, tags)

    items.sort(key=lambda t: t[0])
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<additional>"]
    counts = {}
    for i, (layer, typ, c, fill, coords, name, lv) in enumerate(items):
        counts[typ] = counts.get(typ, 0) + 1
        shape = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
        attrs = (f'id="{typ}_{i}" type="{typ}" color="{c[0]},{c[1]},{c[2]}" '
                 f'fill="{1 if fill else 0}" layer="{layer:.2f}" shape="{shape}"')
        if not fill:
            attrs += ' lineWidth="1.2"'
        if name or lv is not None:
            lines.append(f"    <poly {attrs}>")
            if name:
                lines.append(f'        <param key="name" value={quoteattr(name)}/>')
            if lv is not None:
                lines.append(f'        <param key="levels" value="{lv:g}"/>')
            lines.append("    </poly>")
        else:
            lines.append(f"    <poly {attrs}/>")
    lines.append("</additional>\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return counts
