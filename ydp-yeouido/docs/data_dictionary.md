# 데이터 컬럼 사전 — 의미 · 단위 · 저장 구조 · 필요성

영등포~여의도 도시망 AV 주행 데이터(`data/`, HuggingFace 업로드본)의 모든 항목을 설명한다.
수업 `collect_pomdp_data.py`의 **기본 항목은 이름·형태 그대로** 두고, 도시망에 필요한 항목만 덧붙였다.

- 시간 간격: 1 step = **0.5 s** (SUMO step-length)
- 좌표계: SUMO 네트워크 좌표(m, UTM 52N을 영역 원점으로 옮긴 평면), 경위도는 WGS84
- 저장 형식
  - `*.jsonl.gz` — 한 줄 = transition 하나(모든 항목). `next_observation`·`next_state`는 용량 절약을 위해
    에피소드 마지막 줄에만 있고, 나머지는 다음 줄의 `observation`·`state`로 복원(`collect_pomdp_data.iter_transitions`)
  - `*.npz` — 학습용 고정 크기 배열(아래 “NPZ” 열). 감지 차량은 가변 길이라 `detected_xy`(전 스텝 이어 붙임) + `detected_offsets`(스텝 경계)

## 1. transition 기본 항목 (수업 필수)

| 항목 | 형태 | 단위 | 의미 | 왜 필요한가 | NPZ |
|---|---|---|---|---|---|
| `episode` | int | – | 에피소드 번호 (다중 AV 수집은 `워커×10^7 + 번호`) | 에피소드 단위 분할(학습/검증), 리턴 계산 | `episode` |
| `t` | int | step | 에피소드 안 순번 (0부터) | 시간 순서 복원, 시계열 모델 입력 | `t` |
| `observation` | float[44] | 정규화 [-1,1] | 정책이 실제로 받은 부분 관측 o_t (아래 3절) | BC·오프라인 RL의 입력 그대로 | `observation` |
| `action_raw` | float[2] | [-1,1] | 정책 출력 [가감속, 차선변경] | 모방 대상 행동 | `action_raw` |
| `action.accel_raw` | float | [-1,1] | 가감속 명령. +1 = +3.0 m/s², −1 = −6.0 m/s² | 연속 제어량 복원 | (action_raw[0]) |
| `action.lane_change_raw` | float | [-1,1] | 차선 명령 원시값 | 이산화 전 정책 출력 분석 | (action_raw[1]) |
| `action.lane_change` | int | {−1,0,+1} | 이산화된 명령 (오른쪽/유지/왼쪽, 문턱 ±0.5) | 실제 의도한 차선 행동 | `lane_change` |
| `action.lane_change_applied` | bool | – | 측면 안전·경로 게이트를 통과해 실제 실행됐는지 | 명령과 결과 구분 (거부된 변경 학습 방지) | – |
| `reward` | float | – | r_t (env/mdp_config.py REWARD) | 오프라인 RL·리턴 분석 | `reward` |
| `terminated` | bool | – | 충돌·도착·교착(텔레포트) 종료 | 부트스트랩 중단 지점 | `terminated` |
| `truncated` | bool | – | 시간 제한(4,800 step = 40분) 또는 240 s 정지 교착 | 시간 제한 종료와 실패 종료 구분 | `truncated` |
| `next_observation` | float[44] | [-1,1] | o_{t+1} | TD 학습 타깃 | `next_observation` |
| `state` | dict | – | 정책이 보지 않는 시뮬레이터 상태 s_t (2절) | belief·표현 학습, 데이터 검증, 시각화 | `ego_xy`, `ego_speed` |
| `next_state` | dict | – | s_{t+1} | 상태 전이 모델 | – |
| `detected_vehicles` | list | – | 관측 시야(±80 m, 5개 차선) 안 차량: `id, x, y (m), rel_pos (m, 앞 +), speed (m/s), lane_offset (+왼쪽), type` | 관측이 무엇을 보고 만들어졌는지 추적 | `detected_xy`, `detected_offsets` |
| `event.collided` / `event.arrived` | bool | – | 이번 step에 충돌 / 목적지 도착 | 성공·실패 라벨 | `collided`, `arrived` |
| `event.lane_before` / `event.lane_after` | int | 차선 번호 (0=맨 오른쪽) | 행동 전후 차선 | 차선 변경 결과 확인 | – |

## 2. state — 절대 정보 (평가 기준 필수)

| 항목 | 단위 | 의미 | 왜 필요한가 |
|---|---|---|---|
| `sim_time` | s | 시뮬레이션 시각 (교통 수요 0~3600 s) | 교통 혼잡 시간대 구분 |
| `route_id` | – | AV 과제 경로 (7개 OD) | 경로별 성능·분포 분리 |
| `ego_x`, `ego_y` | m | AV 앞 범퍼 중심 (네트워크 좌표) | 궤적, 지도 위 시각화 |
| `ego_lon`, `ego_lat` | deg | 같은 위치의 경위도 | 실제 지도와 대조 |
| `ego_speed` | m/s | 속도 | 주행 성능, 상태 복원 |
| `ego_accel` | m/s² | 가속도 | 승차감·급정거 분석 |
| `ego_angle` | deg (북 0°, 시계 방향) | 진행 방향 | 궤적 방향, 회전 판별 |
| `ego_lane`, `ego_lane_id` | 번호 / SUMO id | 차선 | 차선 선택 분석 |
| `ego_road_id`, `ego_road_name` | SUMO id / 도로명 | 도로 구간과 실제 이름 (교차로 안은 "(교차로)") | 로터리·교량 등 구조별 분석 |
| `ego_lane_pos` | m | 차선 시작점으로부터 거리 | 정지선까지 거리 계산 |
| `speed_limit` | m/s | 현재 차선 제한속도 | 과속·저속 판정 |
| `route_progress_m`, `route_length_m` | m | 출발 후 주행 거리 / 경로 길이 | 진행률, 완주 판정 |
| `next_tls_id`, `next_tls_dist`, `next_tls_state` | id / m / {+1 초록, 0 황색, −1 적색} | 다음 신호 | 신호 준수·정지 분석 |
| `vehicles[]` | – | 반경 150 m 모든 차량: `id, type, x, y (m), speed (m/s), accel (m/s²), angle (deg), lane, lane_id, road_id, lane_pos (m)` | 상호작용 재현, 주변 교통 밀도, 멀티 에이전트 학습 |

`type`: `hv_krauss` · `hv_idm` · `hv_eidm` · `hv_acc` · `hv_bus` · `hv_truck` (일반 차량 컨트롤러), `ego_type` (다른 AV)

## 3. observation 44차원 (정책 입력)

W = 80 m (시야), vmax = 22.22 m/s, 차선 블록 순서 k = 0..4 → (좌2, 좌1, 현재, 우1, 우2)

| 인덱스 | 내용 | 정규화 | 없을 때 | 왜 필요한가 |
|---|---|---|---|---|
| 0 | 내 속도 | / 현재 제한속도 | – | 속도 조절의 기준 |
| 1+4k | 선행 장애물 간격 | / W (0~1) | 1 | 추돌 회피. 현재 차선(k=2)은 교차로에 갇힌 교차 차량도 포함 |
| 2+4k | 선행 상대속도 (앞 − 나) | / vmax | 1 | 접근 속도 |
| 3+4k | 후행 간격 | −간격 / W | −1 | 차선 변경 시 뒤차 위험 |
| 4+4k | 후행 상대속도 | / vmax | −1 | 뒤차 접근 |
| 21..25 | 차선별 경로 지속 거리 | / 300 m | −1 = 차선 없음 | 회전 전에 있어야 할 차선 (수업 '연결성'의 도시 일반화) |
| 26..30 | 차선별 전방 밀도 | 대수 / (W/7.5 m) | 1 | 덜 막힌 차선 선택 |
| 31 | 다음 신호까지 거리 | / 150 m | 1 | 정지 준비 |
| 32 | 다음 신호 상태 | +1/0/−1 | +1 | 신호 준수 |
| 33 | 신호 바뀌기까지 시간 | / 60 s | 0 | 황색 딜레마 판단 |
| 34 | 다음 교차로까지 거리 | / 150 m | 1 | 교차로 접근 감속 |
| 35 | 교차로 우선권 | +1 우선 / −1 양보 | +1 | 양보 판단 |
| 36 | 필요한 차선 변경 수 | / 3 (부호=방향) | 0 | 경로 유지 |
| 37 | 그 변경까지 남은 거리 | / 300 m | 1 | 변경 시점 |
| 38 | 내 가속도 | / 3 m/s² | – | 부드러운 제어 |
| 39 / 40 | 현재 / 다음 도로 제한속도 | / 22.22 | – | 램프·교량 감속 |
| 41 | 경로 진행률 | 0~1 | – | 남은 거리 |
| 42 | 교차로 내부 여부 | 0/1 | – | 교차로 안 행동 |
| 43 | TTC 위험도 | clip(1 − TTC/6 s, 0, 1) | 0 | 위험 상황 인지 |

## 4. NPZ 추가 키 (도시망)

| 키 | 형태 | 의미 |
|---|---|---|
| `route_index`, `route_names` | int8[N], str[7] | 경로 번호와 이름 |
| `ego_xy`, `ego_speed` | float32[N,2], float32[N] | s_t의 AV 위치(m)·속도(m/s) |
| `shield` | bool[N] | 안전 필터가 속도를 제한한 step |
| `n_av` | int8[N] | (다중 AV 수집만) 그 step에 시뮬레이션에 있던 AV 수 |

## 5. 수집 조건

| 항목 | 값 |
|---|---|
| 도로 | 영등포·당산·여의도 4.8 × 3.4 km, 신호 107곳 (OSM 기반, `env/road_config.py`) |
| 일반 차량 | 7,200 대/h, Krauss 32 · IDM 28 · EIDM 20 · ACC 12 · 버스 5 · 트럭 3 %, 60 s 동적 재경로 |
| 시작 상태 | 교통이 찬 스냅샷 (900~3300 s) |
| 정책 | 최종 PPO (`results/final/model.pt`), 결정적 행동, 안전 필터 ON |
| 과제 | 7개 OD 경로 순환 (3.5~4.9 km) |
| 다중 AV 수집 | 시뮬레이션 하나에 AV 12대 (HV 1,000여 대 중 1 % 내외), 다른 AV는 교차로 장애물 인식에서 제외 |
