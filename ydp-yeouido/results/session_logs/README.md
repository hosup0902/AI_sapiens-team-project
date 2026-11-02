# 세션 실험 기록 (2026-11-02)

| 폴더 | 내용 |
|---|---|
| `stability/` | HV 안정성 실험. `r1,r2`: 동적 재경로 도입, `e1~e3`: 충돌 차량 제거·교차로 막힘 옵션 비교, `f40/45/55`: 수요 9,000/8,000/6,546 대/h (보정 전), `g45/50/55`: 보정 후 8,000/7,200/6,546, `stab_s1~3`: 최종 설정 시드 1~3, `l_A~D`: HV 충돌 원인 분석용 40분 실행 |
| `hv_collisions/` | SUMO `--collision-output` (HV 충돌 유형·위치 분석) |
| `eval/` | 평가 콘솔 로그 (충돌 상세 포함) |
| `collect/` | 데이터 수집 로그. `collect_expert*.log` 중 마지막(`collect_expert5.log`)이 `data/expert_train.*` 에 해당 |
| `train/` | PPO 학습 콘솔 로그. `ppo_main` → `ppo_ns`(필터 OFF) → `ppo_hold`(오토홀드) 순서. `ppo_main2`는 중단된 이어 학습 |

상위 `results/`: 각 학습 실행 폴더(`ppo_main`, `ppo_main2`, `ppo_noshield`, `ppo_hold`, `bc_final`)와 중간 평가 JSON.
최종 제출본은 `results/final/`.
