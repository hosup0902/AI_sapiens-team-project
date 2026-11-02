"""AV(ego)의 MDP/POMDP 정의 — 영등포~여의도 도시망.

수업 코드(env/mdp_config.py)의 구조를 그대로 따르되, 고속도로 직선 구간이 아니라
신호교차로·회전·합류가 있는 실제 도시 경로(env/sumo/av_routes.json)를 달리도록 확장했다.

    S: 관측(OBSERVATION)   — 수업 31차원 + 도시 주행용 13차원 = 44차원, 범위 [-1, 1]
    A: 행동(ACTION)        — [가감속, 차선변경] 2차원 (수업과 동일)
    R: 보상(REWARD)
    에피소드(SIMULATION)    — 상태 스냅샷에서 시작, 7개 OD 경로 중 하나를 완주하면 종료
이 파일만 고치면 env/sumo_env.py 수정 없이 MDP를 바꿀 수 있다.
"""

# ──────────────────────────────────────────────────────────────
# 1) 시뮬레이션 / 에피소드
# ──────────────────────────────────────────────────────────────
SIMULATION = {
    "step_length": 0.5,     # 1 RL step = 0.5 s (수업과 동일)
    "max_steps": 3000,      # 1500 s. 4.9 km 경로를 신호 33곳 거쳐도 완주 가능한 여유
    # 배경 교통이 이미 차 있는 시점의 SUMO 상태를 미리 저장해 두고(tools/make_snapshots.py)
    # reset 때 불러온다 → 매 에피소드 빈 도로에서 10분씩 워밍업할 필요가 없다.
    "snapshot_times": [900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3300],
    "random_pre_steps": 40,  # 스냅샷 로드 후 0~N 스텝 무작위 진행 → 같은 스냅샷이라도 상황이 달라짐
    "stuck_seconds": 240,    # 이 시간 이상 정지 상태가 이어지면 실패(교착)로 종료
    "gui_zoom": 900.0,
    "gui_delay": 60.0,
    "gui_track_ego": True,
}

# ──────────────────────────────────────────────────────────────
# 2) 관측 — 44차원, [-1, 1]
#
#   [0]       내 속도 / 현재 도로 제한속도
#   [1..20]   차선 블록 × 5 (좌2, 좌1, 현재, 우1, 우2) — 수업과 동일
#             (선행 거리/W, 선행 상대속도/vmax, 후행 거리/W, 후행 상대속도/vmax)
#   [21..25]  차선별 "경로 지속성": 그 차선으로 경로를 계속 갈 수 있는 거리 / route_horizon
#             -1 = 차선 없음. 회전·분기 전에 어느 차선에 있어야 하는지를 알려 준다
#             (수업의 '차선 연결성'을 도시 경로용으로 일반화)
#   [26..30]  차선별 전방 밀도 (수업과 동일)
#   ── 도시 주행 확장 ──
#   [31]      다음 신호까지 거리 / tls_horizon      (없으면 1)
#   [32]      다음 신호 상태  초록 +1 / 황색 0 / 적색 -1   (없으면 +1)
#   [33]      다음 신호가 바뀌기까지 남은 시간 / 60 s
#   [34]      다음 교차로까지 거리 / tls_horizon (신호 없는 교차로 포함)
#   [35]      다음 교차로에서 내가 양보해야 하는가 (+1 우선 / -1 양보·정지)
#   [36]      경로상 필요한 차선 변경 수(부호=방향) / 3   (getBestLanes의 offset)
#   [37]      필요한 차선 변경까지 남은 거리 / route_horizon
#   [38]      내 가속도 / max_accel
#   [39]      현재 제한속도 / 22.22 (80 km/h)
#   [40]      다음 엣지 제한속도 / 22.22
#   [41]      경로 진행률 (0 → 1)
#   [42]      교차로 내부 주행 중이면 1
#   [43]      선행차 TTC 위험도 = clip(1 - TTC/6 s, 0, 1)
# ──────────────────────────────────────────────────────────────
OBSERVATION = {
    "visibility": 80.0,          # 주변 차량 감지 거리 W (m). 도시 신호 대기열을 보려면 50 m보다 길게
    "density_veh_length": 7.5,
    "route_horizon": 300.0,      # 경로 지속 거리 정규화 (m)
    "tls_horizon": 150.0,        # 신호/교차로 거리 정규화 (m)
    "speed_norm": 22.22,
}

# ──────────────────────────────────────────────────────────────
# 3) 행동 — [가감속 raw, 차선변경 raw] (수업과 동일)
#
#   종방향: a ∈ [-1,1] → +1 = max_accel, -1 = max_decel. RL이 속도를 직접 정한다.
#   차선:   {-1, 0, +1} (오른쪽 / 유지 / 왼쪽)
#
#   SUMO 안전장치(speedMode) 중 무엇을 남길지:
#     · 앞차와의 안전거리(bit0)    → 끔: 추돌 회피는 RL이 배워야 할 핵심 과제
#     · 교차로 우선권·적색 정지(bit3, bit4) → 켬: 도로교통 법규 계층.
#       신호·양보는 '규칙'이고, 그 안에서 언제 얼마나 가감속할지가 RL의 몫이다.
#       (끄면 신호 위반 = 교차로 측면충돌이 되어 법규 위반을 학습시키는 꼴이 됨)
#   차선: 경로 유지를 위한 '전략적' 변경만 SUMO가 하고(회전 차로 진입),
#         추월 등 재량 변경은 RL 명령으로 — 안전 게이트를 통과할 때만 실행 (수업과 동일)
# ──────────────────────────────────────────────────────────────
ACTION = {
    "dim": 2,
    "accel_index": 0,
    "lane_change_index": 1,
    "lane_change_values": (-1, 0, 1),
    "lane_change_threshold": 0.5,
    "lane_change_duration": 2.0,
    "speed_mode": 0b011110,          # bit1,2(가감속 한계) + bit3(우선권) + bit4(적색 정지), bit0(안전거리) 끔
    "lane_change_mode": 0b0100000001,  # 전략적 변경 O, TraCI 명령은 즉시 충돌만 회피(bit8)
    "lane_change_safety": {
        "enabled": True,
        "min_front_gap": 4.0,
        "min_rear_gap": 4.0,
        "front_tau": 0.3,
        "rear_tau": 0.5,
        "approach_horizon": 1.0,
        "min_route_keep": 0.8,       # 목표 차선의 경로 지속 거리가 현재 차선의 80% 이상일 때만 (경로 이탈 방지)
    },
    # 종방향 안전 필터(shield) — 정책 행동이 물리적으로 피할 수 없는 추돌을 만들 때만 개입.
    #   v_safe = 앞차가 최대 감속해도 멈출 수 있는 최대 속도 (Gipps). 정책 속도가 이를 넘으면 잘라낸다.
    #   학습 정책 자체의 성능을 보려면 False 로 두고 평가 (tools/evaluate.py --no-shield)
    "shield": {
        "enabled": True,
        "reaction_time": 0.5,
        "min_gap": 1.5,
    },
}

# ──────────────────────────────────────────────────────────────
# 4) 보상
#
#   매 스텝  r = speed_weight·v/v_lim                       ← 흐름에 맞춰 달리기
#              + progress_weight·(이번 스텝 이동 거리 / (v_lim·dt))
#              - close_gap_penalty  (주행 중 차간시간 < close_headway 또는 간격 < close_gap_threshold)
#                 ※ 신호 대기열에서 멈춰 선 2~3 m 간격은 정상이므로 감점하지 않는다
#              - ttc_penalty·risk  (선행차 TTC 위험도)
#              - idle_penalty (앞이 비었고 초록인데 서 있음)
#              - jerk_weight·|Δa|/a_max
#              - lane_change_penalty (재량 차선변경 실행 시)
#   종료     -collision_penalty (충돌) / +arrival_bonus (완주) / -stuck_penalty (교착·텔레포트)
# ──────────────────────────────────────────────────────────────
REWARD = {
    "speed_weight": 0.05,
    "progress_weight": 0.05,
    "close_gap_threshold": 2.0,   # 절대 최소 간격 (m)
    "close_headway": 0.8,         # 속도 > 2 m/s 일 때 차간시간 하한 (s)
    "close_gap_penalty": 0.1,
    "ttc_penalty": 0.1,
    "idle_penalty": 0.05,
    "jerk_weight": 0.01,
    "lane_change_penalty": 0.01,
    "invalid_action_penalty": 0.0,
    "shield_penalty": 0.05,       # 안전 필터가 개입한 스텝 → 정책이 스스로 안전하도록 유도
    "collision_penalty": 10.0,
    "arrival_bonus": 5.0,
    "stuck_penalty": 5.0,
}
