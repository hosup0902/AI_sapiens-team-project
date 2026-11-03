---
license: cc-by-sa-4.0
language:
- ko
- en
tags:
- autonomous-driving
- sumo
- reinforcement-learning
- offline-rl
- behavior-cloning
- pomdp
pretty_name: Yeongdeungpo–Yeouido Urban AV Driving (SUMO POMDP transitions)
size_categories:
- 10M<n<100M
---

# 영등포~여의도 도시망 자율주행 POMDP 데이터셋

서울 영등포구 영등포·당산·여의도 일대(약 4.8 km × 3.4 km)의 실제 도로를 OpenStreetMap에서
SUMO로 옮긴 환경에서, 자율주행 차량(AV, ego)이 일반 차량(HV) 사이를 지나
7개 실제 OD 경로(교량·로터리·신호교차로 6~33곳)를 출발지에서 목적지까지 주행한 기록이다.

- 코드: https://github.com/hosup0902/AI_sapiens-team-project (`ydp-yeouido/`)
- 환경: SUMO 1.28, 0.5 s step, 신호 107곳, HV 7,200대/h (Krauss·IDM·EIDM·ACC·버스·트럭 혼합)
- 정책: 최종 PPO (수업 제공 알고리즘, 전문가 데이터로 초기화) / 규칙 기반 전문가(IDM, 초기화용)

## 규모 (2026-11-03 기준)

PPO 정책 데이터 **20,158,391 transition**, 그중 v2 **10,062,955**개가 수업 기본 항목 + State 절대 정보를 모두 담는다.

| 파일 | 형식 | 정책 | 에피소드 | transitions |
|---|---|---|---:|---:|
| `data/multi_v2/ydp_ppo_v2_*.npz` (51개) | NPZ v2 (기본 항목 전부 + State) | 최종 PPO, 다중 AV 12대 | 6,273 | 10,062,955 |
| `data/multi/ydp_ppo_multi_*.npz` (48개) | NPZ v1 (수업 NPZ 기본 키) | 최종 PPO, 다중 AV 12대 | 5,745 | 9,261,316 |
| `data/ydp_ppo_final.jsonl.gz` / `.npz` | JSONL 전체 컬럼 + privileged state | 최종 PPO, 단일 AV | 70 | 123,356 |
| `data/ydp_ppo_bulk_01.npz` | NPZ v1 | 최종 PPO, 단일 AV | 420 | 710,764 |
| `data/expert_train.jsonl.gz` / `.npz` | JSONL + NPZ | 규칙 전문가 + 가감속 잡음 σ=0.1 | 140 | 237,118 |

v2 수집 결과: 에피소드 충돌 0.81% · 도착 96.46% · 교착 2.84% · 안전 필터 개입 0.16% (step 비율).
정지 시간의 82 %는 적·황신호 앞 150 m 안 대기열이다. 집계: `tools/dataset_stats.py`.

## 수집 조건

| 항목 | 값 |
|---|---|
| 정책 | 최종 PPO (`results/final/model.pt`), 결정적 행동, 안전 필터 ON |
| 교통 | HV 7,200 대/h (Krauss·IDM·EIDM·ACC·버스·트럭), 60 s 동적 재경로, 신호 107곳 |
| 시작 | 교통이 찬 스냅샷 900~3,300 s |
| 과제 | 실제 OD 경로 7개 (3.5~4.9 km) 순환 |
| 다중 AV | 시뮬레이션 하나에 AV 12대 (`n_av`), 먼저 투입된 AV가 교차로 우선권 |
| step | 0.5 s, 에피소드 최대 4,800 step, 240 s 연속 정지 = 교착 종료 |

## 컬럼 (수업 `collect_pomdp_data.py` 기본 항목 + 도시망 확장)

| 항목 | 형태 | 의미 |
|---|---|---|
| `episode`, `t` | int | 에피소드 번호, 에피소드 내 step |
| `route` | str | AV 과제 경로 id (7개) |
| `observation` | float[44] | 정책 입력 부분관측 o_t ([-1,1], 레이아웃은 `env/mdp_config.py`) |
| `action_raw` | float[2] | 정책 출력 [가감속, 차선변경] |
| `action.accel_raw / lane_change_raw` | float | 환경에 전달된 값 |
| `action.lane_change` | int {-1,0,1} | 양자화된 차선변경 명령 (우/유지/좌) |
| `action.lane_change_applied` | bool | 안전·경로 게이트를 통과해 실제 실행됐는지 |
| `reward` | float | r_t |
| `terminated`, `truncated` | bool | 충돌·도착·교착 종료 / 시간 제한 |
| `state` | dict | privileged state s_t: ego 절대 위치(x,y,경위도)·속도·가속도·방향·차선·도로명·제한속도·경로 진행·다음 신호, 반경 150 m 주변 차량(위치·속도·가속도·방향·차선·타입) |
| `detected_vehicles` | list | 관측 시야(±80 m, 5개 차선) 안 감지 차량 (위치·상대거리·속도·차선 오프셋·타입) |
| `event.collided / arrived / stuck / shield` | bool | 충돌 / 목적지 도착 / 교착 / 안전 필터 개입 |
| `event.lane_before / lane_after` | int | 행동 전후 차선 |
| `event.progress` | float | 경로 진행률 |
| `next_observation`, `next_state` | | o_{t+1}, s_{t+1} (JSONL에선 에피소드 마지막 step에만 기록, `iter_transitions()`로 복원) |

NPZ v1 키: `observation, action_raw, lane_change, reward, next_observation, terminated, truncated,
episode, t, detected_xy, detected_offsets, route_index, route_names, collided, arrived, ego_xy, ego_speed, shield` (+ `n_av`)

NPZ v2 추가 키 (수업 JSONL 항목 대응 → `docs/data_dictionary.md` 4-1절):
`action_accel_raw, action_lane_change_raw, lane_change_applied, lane_before, lane_after, stuck,
state_sim_time, state_accel, state_angle, state_lane, state_lane_pos, state_edge (+edge_names), state_speed_limit,
state_route_progress_m (+route_lengths_m), state_tls_dist, state_tls_state, state_tls_remain,
detected_speed, detected_rel_pos, detected_lane_offset, detected_type (+vtype_names)`.
s_{t+1}은 같은 `episode`의 다음 행. 경위도는 `ego_xy`를 `sumolib` `net.convertXY2LonLat`로 변환.

## 읽기

```python
import numpy as np
d = np.load("data/<name>.npz")
obs, act = d["observation"], d["action_raw"]
off = d["detected_offsets"]; xy_i = d["detected_xy"][off[i]:off[i + 1]]

from collect_pomdp_data import iter_transitions   # 저장소 코드
for rec in iter_transitions("data/<name>.jsonl.gz"):
    rec["observation"], rec["state"]["ego_lon"], rec["next_observation"]
```

## 출처

도로·건물 데이터 © OpenStreetMap contributors (ODbL). 시뮬레이터: Eclipse SUMO.
