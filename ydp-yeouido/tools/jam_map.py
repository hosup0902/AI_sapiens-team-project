"""정체 진단: t초 시점의 정지 차량 위치를 지도에 찍는다.

    python tools/jam_map.py --t 1200 --out assets/figures/jam_1200.png
"""
import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_builder import P, NAME, OUT  # noqa: E402
import sumolib  # noqa: E402
import libsumo as traci  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--t", type=float, default=1200)
ap.add_argument("--step", type=float, default=0.5)
ap.add_argument("--out", default=os.path.join(BASE, "assets", "figures", "jam.png"))
a = ap.parse_args()

cwd = os.getcwd()
os.chdir(OUT)
traci.start(["sumo", "-c", f"{NAME}.sumocfg", "--step-length", str(a.step), "--no-warnings", "true"])
os.chdir(cwd)
while traci.simulation.getTime() < a.t:
    traci.simulationStep()
pts = [(traci.vehicle.getPosition(v), traci.vehicle.getSpeed(v), traci.vehicle.getWaitingTime(v))
       for v in traci.vehicle.getIDList()]
traci.close()

net = sumolib.net.readNet(P(f"{NAME}.net.xml"))
fig = plt.figure(figsize=(16, 11.3))
ax = fig.add_axes([0, 0, 1, 1])
segs = [ln.getShape() for e in net.getEdges() for ln in e.getLanes()]
ax.add_collection(LineCollection(segs, colors=(0.75, 0.75, 0.75), linewidths=0.6))
mv = [p for p, s, w in pts if s > 0.5]
st = [(p, w) for p, s, w in pts if s <= 0.5]
if mv:
    ax.scatter(*zip(*mv), s=2, c="#1e88e5")
if st:
    ax.scatter([p[0] for p, _ in st], [p[1] for p, _ in st], s=4,
               c=[min(w, 300) for _, w in st], cmap="autumn_r", vmin=0, vmax=300)
ax.set_aspect("equal")
ax.autoscale()
ax.axis("off")
ax.set_title(f"t={a.t:.0f}s  주행 {len(mv)} / 정지 {len(st)}")
fig.savefig(a.out, dpi=110)
print(a.out, len(mv), len(st))
