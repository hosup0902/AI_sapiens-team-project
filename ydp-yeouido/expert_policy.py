"""규칙 기반 전문가 정책 (BC 교사 / PPO 초기화 / 비교 기준선).

정책 입력과 똑같은 44차원 관측(env/mdp_config.py 레이아웃)만 보고 행동을 낸다.
→ BC가 같은 정보로 이 행동을 그대로 흉내 낼 수 있다 (privileged 정보 사용 안 함).

    종방향: IDM(Intelligent Driver Model)
        - 선행차가 있으면 IDM 추종
        - 적색/곧 적색이 될 황색 신호는 정지선 위치의 '정지한 가상 선행차'로 취급
        - 양보해야 하는 교차로 / 다음 도로 제한속도가 낮으면 미리 감속
    횡방향: 경로상 필요한 변경은 SUMO 전략 변경에 맡기고,
            앞차가 느리고 옆 차선이 경로를 유지하며 더 비어 있으면 추월 차선변경
"""
import numpy as np

from env.mdp_config import OBSERVATION
from env.road_config import EGO

W = OBSERVATION["visibility"]
H_TLS = OBSERVATION["tls_horizon"]
H_ROUTE = OBSERVATION["route_horizon"]
VN = OBSERVATION["speed_norm"]
A_MAX, B_MAX = EGO["accel"], EGO["decel"]

# IDM 파라미터
T_HEAD = 1.3      # 희망 시간 간격 (s)
S0 = 2.5          # 정지 시 최소 간격 (m)
B_COMF = 2.5      # 편안한 감속 (m/s²)
DELTA = 4


def _idm(v, v0, gap=None, dv=0.0):
    """dv = 내 속도 - 앞차 속도 (접근 중이면 +)."""
    v0 = max(v0, 0.1)
    a = A_MAX * (1.0 - (v / v0) ** DELTA)
    if gap is not None:
        s_star = S0 + max(0.0, v * T_HEAD + v * dv / (2.0 * np.sqrt(A_MAX * B_COMF)))
        a -= A_MAX * (s_star / max(gap, 0.1)) ** 2
    return a


class ExpertPolicy:
    def __init__(self, overtake=True, seed=0):
        self.overtake = overtake
        self.rng = np.random.default_rng(seed)
        self._lc_cooldown = 0

    def predict(self, obs, deterministic=True):
        o = np.asarray(obs, dtype=np.float64)
        vlim = max(o[39] * VN, 3.0)
        v = o[0] * vlim
        # ── 희망 속도: 제한속도, 다음 도로·교차로 대비 감속 ──
        v0 = vlim
        jn_dist = o[34] * H_TLS
        next_lim = max(o[40] * VN, 3.0)
        if jn_dist < H_TLS - 1:
            v0 = min(v0, np.sqrt(next_lim ** 2 + 2 * B_COMF * max(jn_dist - 5, 0)))
            if o[35] < 0:                       # 양보 교차로 — 접근 속도 제한
                v0 = min(v0, max(4.0, np.sqrt(2 * B_COMF * max(jn_dist - 3, 0))))
        if o[42] > 0.5:                         # 교차로 내부: 회전 속도
            v0 = min(v0, 8.0)
        # ── 선행차 ──
        gap = None
        dv = 0.0
        if o[9] < 0.999:
            gap = o[9] * W
            dv = -o[10] * VN                    # obs는 (앞차 - 나)
        a = _idm(v, v0, gap, dv)
        # ── 신호: 적색 / 멈출 수 있는 황색 → 정지선을 정지 차량으로 ──
        tls_d = o[31] * H_TLS
        state = o[32]
        if tls_d < H_TLS - 1:
            stop_gap = max(tls_d - 1.0, 0.1)
            must_stop = state < -0.5 or (state < 0.5 and v * v / (2 * B_MAX) < tls_d - 1.0)
            if must_stop:
                a = min(a, _idm(v, v0, stop_gap, v))
        a = float(np.clip(a, -B_MAX, A_MAX))
        accel = a / A_MAX if a >= 0 else a / B_MAX

        # ── 차선 ──
        lane = 0.0
        if self._lc_cooldown > 0:
            self._lc_cooldown -= 1
        elif self.overtake and gap is not None and gap < 40 and dv > 2.0 and abs(o[36]) < 1e-6 \
                and o[42] < 0.5:
            cur_keep = o[23]
            best = None
            for k, cmd in ((1, 1.0), (3, -1.0)):          # 왼쪽 우선, 다음 오른쪽
                keep = o[21 + k]
                if keep < 0 or keep < 0.8 * cur_keep:
                    continue
                lead_gap = o[1 + 4 * k] * W
                foll_gap = -o[3 + 4 * k] * W
                if lead_gap > gap + 15 and foll_gap > 8 and o[26 + k] < o[28]:
                    best = cmd
                    break
            if best is not None:
                lane = best
                self._lc_cooldown = 10
        return np.asarray([accel, lane], dtype=np.float32)

    # PPO 등과 같은 인터페이스
    def act(self, obs):
        return self.predict(obs)
