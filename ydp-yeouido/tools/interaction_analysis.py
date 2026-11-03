"""차량 상호작용 정량 분석 — 최종 PPO 주행 데이터(JSONL, privileged state)에서.

    python tools/interaction_analysis.py data/ydp_ppo_final.jsonl.gz

평가 항목 "Vehicle Interaction: 일반 차량과 AV 사이에 의미 있는 interaction이 발생하는가"를 숫자로 보인다.

이벤트 정의 (0.5 s step)
    정지         속도 ≥ 0.5 m/s 에서 < 0.1 m/s 로 바뀐 순간. 그때의 상황으로 원인을 나눈다
      · 신호 정지   다음 신호까지 40 m 이내이고 적색/황색
      · 양보 정지   (신호 아님) 다음 교차로 20 m 이내이고 우선권 없음(관측 [35] = −1)
      · 대기열 정지 (그 외) 같은 차선 앞 장애물 20 m 이내 — 앞차·교차로 상충 차량
    교차로 통과   교차로 내부 차선(':'로 시작)에 진입한 횟수
    차선 변경     같은 도로에서 차선 번호가 바뀐 횟수 (정책 재량 변경 / SUMO 경로 유지 변경 구분)
    근접 상황     선행 장애물과의 TTC < 4 s 인 시간 비율
    주변 차량     반경 50 m / 150 m 안 차량 수, 감지 차량의 컨트롤러 구성
결과: results/analysis/interaction_summary.json, assets/figures/interaction_*.png
"""
import collections
import gzip
import json
import math
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

H_TLS = 150.0
W = 80.0
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load(path):
    eps = collections.defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            eps[r["episode"]].append(r)
    return eps


def analyze(eps):
    per_ep, stops_xy, near50, near150, types = [], [], [], [], collections.Counter()
    for ep, rs in sorted(eps.items()):
        rs.sort(key=lambda r: r["t"])
        c = collections.Counter()
        prev_v, prev_road = None, None
        ttc_close = 0
        for i, r in enumerate(rs):
            s, o = r["state"], r["observation"]
            if not s.get("ego_alive"):
                continue
            v = s["ego_speed"]
            road = s["ego_road_id"]
            if prev_v is not None and prev_v >= 0.5 and v < 0.1:
                tls_d, tls_s = s.get("next_tls_dist"), s.get("next_tls_state")
                jn_d, prio = o[34] * H_TLS, o[35]
                lead = o[9] * W
                if tls_d is not None and tls_d < 40 and tls_s is not None and tls_s < 0.5:
                    kind = "signal"
                elif jn_d < 20 and prio < 0:
                    kind = "yield"
                elif lead < 20:
                    kind = "queue"
                else:
                    kind = "other"
                c["stop_" + kind] += 1
                stops_xy.append((s["ego_x"], s["ego_y"], kind))
            if road.startswith(":") and (prev_road is None or not prev_road.startswith(":")):
                c["junction"] += 1
            nxt = rs[i + 1]["state"] if i + 1 < len(rs) else None
            if nxt and nxt.get("ego_alive") and nxt["ego_road_id"] == road and not road.startswith(":") \
                    and nxt["ego_lane"] != s["ego_lane"]:
                if r["action"]["lane_change"] != 0 and r["action"]["lane_change_applied"]:
                    c["lc_policy"] += 1
                else:
                    c["lc_route"] += 1
            if o[43] > 1 - 4 / 6:
                ttc_close += 1
            if i % 10 == 0:
                ex, ey = s["ego_x"], s["ego_y"]
                vs = s.get("vehicles", [])
                near150.append(len(vs))
                near50.append(sum(1 for q in vs if (q["x"] - ex) ** 2 + (q["y"] - ey) ** 2 <= 2500))
                for q in vs:
                    types[q["type"]] += 1
            prev_v, prev_road = v, road
        last = rs[-1]
        per_ep.append({"episode": ep, "route": last["route"], "steps": len(rs),
                       "outcome": "collision" if last["event"]["collided"] else
                       ("arrived" if last["event"]["arrived"] else "stuck/timeout"),
                       "ttc_lt4_frac": ttc_close / max(len(rs), 1), **c})
    return per_ep, stops_xy, near50, near150, types


def style(ax):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "data", "ydp_ppo_final.jsonl.gz")
    eps = load(path)
    per_ep, stops_xy, near50, near150, types = analyze(eps)
    keys = [("stop_signal", "신호 정지"), ("stop_queue", "대기열(앞차) 정지"), ("stop_yield", "교차로 양보 정지"),
            ("junction", "교차로 통과"), ("lc_route", "차선변경 (경로 유지)"), ("lc_policy", "차선변경 (정책 재량)")]
    n = len(per_ep)
    mean = {k: float(np.mean([e.get(k, 0) for e in per_ep])) for k, _ in keys}
    by_route = {}
    for rid in sorted({e["route"] for e in per_ep}):
        es = [e for e in per_ep if e["route"] == rid]
        by_route[rid] = {"episodes": len(es), **{k: round(float(np.mean([e.get(k, 0) for e in es])), 1) for k, _ in keys},
                         "ttc_lt4_pct": round(100 * float(np.mean([e["ttc_lt4_frac"] for e in es])), 2)}
    tot_types = sum(types.values())
    summary = {
        "source": os.path.relpath(path, BASE), "episodes": n,
        "mean_per_episode": {lab: round(mean[k], 1) for k, lab in keys},
        "ttc_lt4_pct_of_time": round(100 * float(np.mean([e["ttc_lt4_frac"] for e in per_ep])), 2),
        "vehicles_within_50m": {"mean": round(float(np.mean(near50)), 1), "p90": int(np.percentile(near50, 90))},
        "vehicles_within_150m": {"mean": round(float(np.mean(near150)), 1), "p90": int(np.percentile(near150, 90))},
        "nearby_vehicle_types_pct": {k: round(100 * v / tot_types, 1) for k, v in types.most_common()},
        "by_route": by_route,
    }
    out = os.path.join(BASE, "results", "analysis")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "interaction_summary.json"), "w", encoding="utf-8") as f:
        json.dump({**summary, "per_episode": per_ep}, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        import koreanize_matplotlib  # noqa: F401
    except ImportError:
        pass
    figs = os.path.join(BASE, "assets", "figures")
    # (1) 에피소드당 상호작용 이벤트 수 — 막대 하나의 계열 (값 라벨 직접 표시)
    fig, ax = plt.subplots(figsize=(8.5, 3.8), facecolor="#fcfcfb")
    labs = [lab for _, lab in keys][::-1]
    vals = [mean[k] for k, _ in keys][::-1]
    ax.barh(labs, vals, color=COLORS[0], height=0.55)
    for y, v in enumerate(vals):
        ax.text(v + max(vals) * 0.01, y, f"{v:.1f}", va="center", fontsize=10, color=INK)
    style(ax)
    ax.set_xlabel("에피소드당 평균 횟수", color=INK2)
    ax.set_title(f"AV가 겪는 상호작용 (최종 PPO, {n} 에피소드, 평균 4.3 km 경로)", color=INK, fontsize=12, loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "interaction_counts.png"), dpi=170)
    plt.close(fig)
    # (2) 주변 차량 수 분포 — 작은 다중 그림 2개 (한 축에 두 척도를 섞지 않음)
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.4), facecolor="#fcfcfb")
    for ax, data, title in ((axs[0], near50, "반경 50 m 안 차량 수"), (axs[1], near150, "반경 150 m 안 차량 수")):
        ax.hist(data, bins=range(0, int(max(data)) + 2, max(1, int(max(data)) // 25)), color=COLORS[0],
                edgecolor="#fcfcfb", linewidth=1)
        ax.axvline(np.mean(data), color=INK, lw=1.2, ls="--")
        ax.text(np.mean(data), ax.get_ylim()[1] * 0.92, f" 평균 {np.mean(data):.1f}대", color=INK, fontsize=10)
        style(ax)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.set_ylabel("표본 수 (5 s 간격)", color=INK2)
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "interaction_nearby.png"), dpi=170)
    plt.close(fig)
    # (3) 정지 위치 지도 — 원인 3가지 (+기타), 색 + 모양으로 구분
    import sumolib
    from env.road_builder import P, NAME
    net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
    fig, ax = plt.subplots(figsize=(11, 7.8), facecolor="#fcfcfb")
    from matplotlib.collections import LineCollection
    ax.add_collection(LineCollection([e.getShape() for e in net.getEdges()], colors="#d8d7d2", linewidths=0.6))
    for kind, lab, col, mk in (("signal", "신호 정지", COLORS[0], "o"), ("queue", "대기열(앞차) 정지", COLORS[1], "s"),
                               ("yield", "교차로 양보 정지", COLORS[2], "^"), ("other", "기타", "#8a8984", "x")):
        pts = [(x, y) for x, y, k in stops_xy if k == kind]
        if pts:
            xs, ys = zip(*pts)
            ax.scatter(xs, ys, s=14, c=col, marker=mk, alpha=0.7, label=f"{lab} ({len(pts)})",
                       edgecolors="none" if mk != "x" else None)
    ax.legend(loc="lower right", frameon=True, fontsize=10)
    ax.set_aspect("equal")
    ax.autoscale()
    ax.axis("off")
    ax.set_title(f"AV 정지 위치와 원인 ({n} 에피소드)", color=INK, fontsize=12, loc="left")
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "interaction_stop_map.png"), dpi=150)
    plt.close(fig)
    print("그림 저장: assets/figures/interaction_counts.png, interaction_nearby.png, interaction_stop_map.png")


if __name__ == "__main__":
    main()
