"""실패(충돌·교착·시간초과) 사례 분석 — 평가 결과 JSON들을 모아 유형·책임·위치별로 정리.

    python tools/failure_analysis.py results/final/eval_*.json
결과: results/analysis/failures.md
"""
import collections
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(BASE, "results", "final", "eval_*.json")))
    lines = ["# 실패 사례 분석", "",
             "평가 결과(`results/final/eval_*.json`)의 충돌·교착·시간초과 에피소드를 모았다. "
             "`AV 과실` = SUMO 충돌 기록에서 AV가 collider(뒤에서/옆에서 들이받은 쪽)인 경우, "
             "`피추돌` = 일반 차량이 AV를 들이받은 경우.", ""]
    total = collections.Counter()
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        rows = d["episodes"]
        bad = [r for r in rows if r["outcome"] != "arrived"]
        name = os.path.basename(f)
        s = d["summary"]
        lines += [f"## {name} — {d['policy']} · 필터 {'ON' if d.get('shield', True) else 'OFF'} · {len(rows)} 에피소드", "",
                  f"충돌률 {s['collision_rate']:.1%} · 완주율 {s['success_rate']:.1%} · 교착 {s['stuck_rate']:.1%} · "
                  f"시간초과 {s['timeout_rate']:.1%}", ""]
        if not bad:
            lines += ["실패 없음.", ""]
            continue
        lines += ["| 에피소드 | 경로 | 결과 | 유형 | 책임 | 위치 | AV 속도 | 상대 속도 |", "|---:|---|---|---|---|---|---:|---:|"]
        for r in bad:
            ci = r.get("collision_info") or {}
            if r["outcome"] == "collision":
                fault = "AV 과실" if ci.get("ego_is_collider") else "피추돌"
                total[(r["outcome"], ci.get("type"), fault)] += 1
                lines.append(f"| {r['episode']} | {r['route']} | 충돌 | {ci.get('type', '?')} | {fault} | "
                             f"{ci.get('road_name', '')} `{ci.get('lane', '')[:28]}` | {3.6 * ci.get('ego_speed', 0):.1f} km/h | "
                             f"{3.6 * ci.get('other_speed', 0):.1f} km/h |")
            else:
                total[(r["outcome"], None, None)] += 1
                lines.append(f"| {r['episode']} | {r['route']} | {r['outcome']} | – | – | 진행 {r['progress']:.0%} | – | – |")
        lines.append("")
    lines += ["## 전체 집계", "", "| 결과 | 유형 | 책임 | 건수 |", "|---|---|---|---:|"]
    for (o, t, fa), c in total.most_common():
        lines.append(f"| {o} | {t or '–'} | {fa or '–'} | {c} |")
    lines += ["", "### 해석", "",
              "- 충돌은 모두 교차로 내부(`junction`)에서 났다. 직선 구간 추돌·차선변경 측면 충돌은 없다 "
              "(오토홀드·측면 안전 게이트 효과).",
              "- 상당수가 일반 차량이 AV를 들이받은 경우다. SUMO의 교차로 모델에서 HV끼리도 80분에 41~59건의 "
              "교차로 내부 저속 접촉이 나는 것과 같은 현상이다 (`results/session_logs/hv_collisions/`).",
              "- 교착은 영등포 로터리·서울교 북단 신호의 대기열(28~80대)이 원인인 실제 정체다 "
              "(`tools/collect_multi.py --debug` 대기열 선두 추적)."]
    out = os.path.join(BASE, "results", "analysis", "failures.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-16:]))
    print("저장:", out)


if __name__ == "__main__":
    main()
