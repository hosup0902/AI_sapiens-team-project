"""SUMO 도로망 + 건물/배경 폴리곤을 PNG로 렌더링 (보고서·검증용).

    python tools/render_map.py                         # 전체 → assets/figures/map_full.png
    python tools/render_map.py --lonlat 126.906 37.517 --radius 500 --out assets/figures/map_rotary.png
    python tools/render_map.py --tls                   # 신호교차로 표시
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_builder import P, NAME  # noqa: E402  (SUMO_HOME 설정 포함)
import sumolib  # noqa: E402

import logging
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
from matplotlib import font_manager  # noqa: E402
_avail = {f.name for f in font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [f for f in ("Malgun Gothic", "AppleGothic", "NanumGothic") if f in _avail] + ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(BASE, "assets", "figures", "map_full.png"))
    ap.add_argument("--lonlat", nargs=2, type=float)
    ap.add_argument("--radius", type=float, default=600)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--labels", action="store_true", help="주요 도로 이름 표시")
    ap.add_argument("--routes", action="store_true", help="AV 과제 경로 표시")
    ap.add_argument("--dpi", type=int, default=220)
    a = ap.parse_args()

    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=True)
    xmin, ymin, xmax, ymax = net.getBoundary()
    if a.lonlat:
        cx, cy = net.convertLonLat2XY(*a.lonlat)
        xmin, xmax, ymin, ymax = cx - a.radius, cx + a.radius, cy - a.radius, cy + a.radius
    w = xmax - xmin
    h = ymax - ymin
    fig = plt.figure(figsize=(14, 14 * h / w))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor((0.95, 0.94, 0.92))

    # 폴리곤 (layer 순)
    polys = []
    pfile = P(f"{NAME}.poly.xml")
    if os.path.exists(pfile):
        for p in ET.parse(pfile).getroot().iter("poly"):
            pts = [tuple(map(float, xy.split(","))) for xy in p.get("shape").split()]
            col = tuple(int(c) / 255 for c in p.get("color").split(",")[:3])
            polys.append((float(p.get("layer", 0)), pts, col, p.get("fill", "1") in ("1", "true"),
                          p.get("type")))
        polys.sort(key=lambda t: t[0])
        fills = [(pts, col) for _, pts, col, fill, _ in polys if fill]
        ax.add_collection(PolyCollection([f[0] for f in fills], facecolors=[f[1] for f in fills],
                                         edgecolors=[(0.55, 0.5, 0.45) if False else f[1] for f in fills],
                                         linewidths=0.2, zorder=1))
        bl = [pts for _, pts, _, _, t in polys if t == "building"]
        ax.add_collection(PolyCollection(bl, facecolors="none", edgecolors=(0.45, 0.42, 0.4),
                                         linewidths=0.25, zorder=2))
        lines = [(pts, col) for _, pts, col, fill, _ in polys if not fill]
        ax.add_collection(LineCollection([l[0] for l in lines], colors=[l[1] for l in lines],
                                         linewidths=0.6, linestyles="--", zorder=2))

    # 차로 (폭 비례)
    segs, widths, cols = [], [], []
    px_per_m = fig.get_figwidth() * 72 / w
    for e in net.getEdges(withInternal=True):
        fn = e.getFunction()
        for ln in e.getLanes():
            segs.append(ln.getShape())
            widths.append(max(0.25, ln.getWidth() * px_per_m))
            if fn == "internal":
                cols.append((0.38, 0.38, 0.4))
            elif e.getPriority() >= 13:
                cols.append((0.25, 0.25, 0.3))
            else:
                cols.append((0.32, 0.32, 0.35))
    ax.add_collection(LineCollection(segs, linewidths=widths, colors=cols, zorder=3,
                                     capstyle="butt"))
    # 차선 경계(흰 점선) — 확대 뷰에서만
    if a.lonlat:
        marks = []
        for e in net.getEdges():
            for ln in e.getLanes()[1:]:
                marks.append(ln.getShape())
        ax.add_collection(LineCollection(marks, linewidths=0.35, colors="white",
                                         linestyles=(0, (4, 6)), zorder=4))

    if a.tls:
        for t in net.getTrafficLights():
            xs, ys = [], []
            for c in t.getConnections():
                x, y = c[0].getShape()[-1]
                xs.append(x)
                ys.append(y)
            if xs:
                ax.scatter([sum(xs) / len(xs)], [sum(ys) / len(ys)], s=30 if not a.lonlat else 90,
                           c="#e53935", edgecolors="white", linewidths=0.6, zorder=6)

    if a.routes:
        import json
        rf = P("av_routes.json")
        palette = ["#e53935", "#1e88e5", "#43a047", "#fb8c00", "#8e24aa", "#00897b", "#6d4c41", "#d81b60"]
        for i, (rid, r) in enumerate(json.load(open(rf, encoding="utf-8")).items()):
            pts = []
            for eid in r["edges"]:
                pts += net.getEdge(eid).getShape()
            xs, ys = zip(*pts)
            c = palette[i % len(palette)]
            ax.plot(xs, ys, color=c, lw=2.6, alpha=0.85, zorder=7, label=f"{rid}: {r['desc']}")
            ax.scatter([xs[0]], [ys[0]], color=c, s=50, marker="o", zorder=8, edgecolors="white")
            ax.scatter([xs[-1]], [ys[-1]], color=c, s=70, marker="*", zorder=8, edgecolors="white")
        ax.legend(loc="lower right", fontsize=9, framealpha=0.9)

    if a.labels:
        seen = {}
        for e in net.getEdges():
            n = e.getName()
            if n and e.getPriority() >= 10 and e.getLength() > 120:
                if n not in seen or e.getLength() > seen[n].getLength():
                    seen[n] = e
        for n, e in seen.items():
            sh = e.getShape()
            x, y = sh[len(sh) // 2]
            if xmin < x < xmax and ymin < y < ymax:
                ax.text(x, y, n, fontsize=8 if not a.lonlat else 11, ha="center", va="center",
                        zorder=9, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))

    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.axis("off")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    fig.savefig(a.out, dpi=a.dpi)
    print("저장:", a.out)


if __name__ == "__main__":
    main()
