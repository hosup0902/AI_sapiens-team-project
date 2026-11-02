"""PPO 학습 곡선 그리기 — train.py 콘솔 로그(여러 개 이어 붙이기 가능)에서 파싱.

    python tools/plot_training.py logs/ppo_main.log logs/ppo_main2.log --out assets/figures/training_curve.png
"""
import argparse
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
try:
    import koreanize_matplotlib  # noqa: F401,E402
except ImportError:
    pass

UPD = re.compile(r"\[update\s+(\d+)\] steps=\s*(\d+)\s+ep_rew_mean=([-\d.na]+)")
EVAL = re.compile(r"\[eval @(\d+)\].*?충돌률=(\d+)%\s+완주율=(\d+)%\s+평균속도=([\d.]+)m/s.*?보상=([-\d.]+)")


def parse(paths):
    tr, ev, off = [], [], 0
    parse.bounds = []
    for p in paths:
        last = 0
        for line in open(p, encoding="utf-8", errors="ignore"):
            m = UPD.search(line)
            if m:
                s = int(m.group(2)) + off
                last = max(last, int(m.group(2)))
                if m.group(3) != "nan":
                    tr.append((s, float(m.group(3))))
            m = EVAL.search(line)
            if m:
                ev.append((int(m.group(1)) + off, int(m.group(2)), int(m.group(3)),
                           float(m.group(4)) * 3.6, float(m.group(5))))
        off += last
        parse.bounds.append(off)
    return tr, ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--out", default="assets/figures/training_curve.png")
    ap.add_argument("--phases", nargs="*", default=[], help="로그별 단계 이름 (경계선 표시)")
    a = ap.parse_args()
    tr, ev = parse(a.logs)
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    if tr:
        ax[0].plot([t[0] / 1000 for t in tr], [t[1] for t in tr], color="#1f5fa8")
    ax[0].set_title("학습 에피소드 리턴 (최근 20개 평균)")
    ax[0].set_xlabel("환경 스텝 (천)")
    if ev:
        xs = [e[0] / 1000 for e in ev]
        ax[1].plot(xs, [e[4] for e in ev], "o-", color="#1f5fa8")
        ax[1].set_title("평가 리턴 (결정적 정책, 7개 경로)")
        ax[2].plot(xs, [e[3] for e in ev], "o-", color="#c8102e", label="평균속도 (km/h)")
        ax2 = ax[2].twinx()
        ax2.plot(xs, [e[1] for e in ev], "s--", color="#555", label="충돌률 (%)")
        ax2.set_ylim(-5, 105)
        ax[2].set_title("평가 평균속도 · 충돌률")
        ax[2].legend(loc="lower left")
        ax2.legend(loc="lower right")
        for x in ax[1:]:
            x.set_xlabel("환경 스텝 (천)")
    starts = [0] + parse.bounds[:-1]
    for x in ax:
        x.grid(alpha=0.3)
        for i, b in enumerate(starts):
            if i:
                x.axvline(b / 1000, color="#999", ls=":", lw=1)
            if i < len(a.phases):
                x.text(b / 1000 + 2, 0.98, a.phases[i], transform=x.get_xaxis_transform(),
                       va="top", fontsize=8.5, color="#555")
    fig.tight_layout()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    fig.savefig(a.out, dpi=150)
    print("저장:", a.out)


if __name__ == "__main__":
    main()
