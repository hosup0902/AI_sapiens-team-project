"""영등포~여의도 도시망 AV 환경 — Gymnasium 인터페이스 + TraCI/libsumo.

수업 코드(env/sumo_env.py, SumoHighwayEnv)를 실제 도시망으로 확장한 버전.

    obs, info = env.reset()                         # 스냅샷 로드 → AV 투입
    obs, r, terminated, truncated, info = env.step(action)

수업 환경과 달라진 점
    1) 도로: 직선 고속도로 대신 OSM 기반 도시망 (신호 106곳, 로터리, 교량, 지하차도)
    2) 과제: av_routes.json 의 실제 OD 경로 7개 중 하나를 출발지 → 목적지까지 완주
    3) 시작: 배경 교통(HV 수백~천여 대)이 이미 돌고 있는 SUMO 상태 스냅샷을 불러와
             교통 한가운데서 출발 (수업의 prefill 역할, reset ≈ 0.1 s)
    4) 관측: 수업 31차원 + 신호·교차로·경로 차로·TTC 등 13차원 (env/mdp_config.py)
    5) 행동: 수업과 동일 [가감속, 차선변경]. 교차로 우선권·적색 정지는 SUMO 법규 계층이,
             추돌 회피·속도 선택·재량 차선변경은 정책이 담당
    6) 안전 필터(shield): 정책 속도가 '앞차가 급정거해도 멈출 수 있는 속도'를 넘을 때만 개입
             (끄고 평가 가능: ACTION["shield"]["enabled"] = False)

외부 코드(utils/evaluator.py, algorithms/ppo.py, collect_pomdp_data.py)는 수업 코드와
같은 인터페이스(reset/step/info 키, get_privileged_state, get_detected_vehicles)를 쓴다.
"""
import json
import math
import os
import random
import sys

import numpy as np
import gymnasium as gym
from gymnasium import spaces

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_builder import P, NAME, OUT  # noqa: E402  (SUMO_HOME 자동 설정)
from env.road_config import TRAFFIC, EGO  # noqa: E402
import sumolib  # noqa: E402
from sumolib import checkBinary  # noqa: E402

SNAP_DIR = P("snapshots")


def sumo_runtime_args():
    """sumocfg 외 추가 실행 옵션 (재경로·충돌 처리 등은 road_builder 가 sumocfg 에 기록)."""
    return []


def _traci_module(gui):
    if gui:
        import traci
        return traci
    try:
        import libsumo   # in-process SUMO: TraCI 소켓 왕복이 없어 수 배 빠름
        return libsumo
    except ImportError:
        import traci
        return traci


def ensure_snapshots(times, step_length, seed=None, verbose=True):
    """배경 교통 상태 스냅샷을 만든다 (없을 때만). SUMO 버전마다 형식이 달라 git에 넣지 않는다."""
    os.makedirs(SNAP_DIR, exist_ok=True)
    tag = f"s{step_length}"
    paths = [os.path.join(SNAP_DIR, f"state_{tag}_{int(t)}.xml.gz") for t in times]
    if all(os.path.exists(p) for p in paths):
        return paths
    T = _traci_module(False)
    if verbose:
        print(f"[sumo_env] 교통 스냅샷 생성 중 ({len(times)}개, 최대 {max(times)} s) …", flush=True)
    cwd = os.getcwd()
    os.chdir(OUT)
    try:
        T.start([checkBinary("sumo"), "-c", f"{NAME}.sumocfg", "--step-length", str(step_length),
                 "--no-warnings", "true", "--no-step-log", "true",
                 "--seed", str(TRAFFIC["seed"] if seed is None else seed)] + sumo_runtime_args())
        for t, p in sorted(zip(times, paths)):
            while T.simulation.getTime() < t:
                T.simulationStep()
            T.simulation.saveState(os.path.relpath(p, OUT))
        T.close()
    finally:
        os.chdir(cwd)
    return paths


class YdpCityEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(self, mdp_sim, mdp_obs, action, reward, ego=EGO, routes=None,
                 gui=False, gui_autostart=True, seed=None, route_mode="random"):
        """
        Args:
            routes: 사용할 AV 과제 id 목록 (None이면 av_routes.json 전체)
            route_mode: "random" | "cycle" — 에피소드마다 경로 선택 방식
        """
        super().__init__()
        self.gui, self.gui_autostart = gui, gui_autostart
        self.T = _traci_module(gui)
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

        with open(P("av_routes.json"), encoding="utf-8") as f:
            all_routes = json.load(f)
        self.route_ids = list(routes or all_routes.keys())
        self.routes = {k: all_routes[k] for k in self.route_ids}
        self.route_mode = route_mode
        self._route_cursor = 0

        self.net = sumolib.net.readNet(P(f"{NAME}.net.xml"), withInternal=False)
        self.edge_speed = {e.getID(): e.getSpeed() for e in self.net.getEdges()}
        self.route_len = {k: sum(self.net.getEdge(e).getLength() for e in r["edges"])
                          for k, r in self.routes.items()}

        # ---- 설정 ----
        self.step_length = float(mdp_sim["step_length"])
        self.max_steps = int(mdp_sim["max_steps"])
        self.snapshot_times = list(mdp_sim["snapshot_times"])
        self.random_pre_steps = int(mdp_sim.get("random_pre_steps", 0))
        self.stuck_steps = int(mdp_sim.get("stuck_seconds", 240) / self.step_length)
        self.gui_zoom = float(mdp_sim.get("gui_zoom", 900))
        self.gui_delay = float(mdp_sim.get("gui_delay", 60))
        self.gui_track_ego = bool(mdp_sim.get("gui_track_ego", True))

        self.visibility = float(mdp_obs["visibility"])
        self.density_veh_len = float(mdp_obs.get("density_veh_length", 7.5))
        self.route_horizon = float(mdp_obs.get("route_horizon", 300.0))
        self.tls_horizon = float(mdp_obs.get("tls_horizon", 150.0))
        self.vnorm = float(mdp_obs.get("speed_norm", 22.22))

        self.act_dim = int(action["dim"])
        self.accel_index = int(action.get("accel_index", 0))
        self.lane_change_index = int(action.get("lane_change_index", 1))
        self.lane_change_threshold = float(action.get("lane_change_threshold", 0.5))
        self.lane_change_duration = float(action.get("lane_change_duration", 2.0))
        self.speed_mode = int(action.get("speed_mode", 0b011110))
        self.lc_mode = int(action.get("lane_change_mode", 0b0100000001))
        lcs = action.get("lane_change_safety") or {}
        self.lc_safety_enabled = bool(lcs.get("enabled", True))
        self.lc_front_min = float(lcs.get("min_front_gap", 4.0))
        self.lc_rear_min = float(lcs.get("min_rear_gap", 4.0))
        self.lc_front_tau = float(lcs.get("front_tau", 0.3))
        self.lc_rear_tau = float(lcs.get("rear_tau", 0.5))
        self.lc_horizon = float(lcs.get("approach_horizon", 1.0))
        self.lc_route_keep = float(lcs.get("min_route_keep", 0.8))
        sh = action.get("shield") or {}
        self.shield_enabled = bool(sh.get("enabled", True))
        self.shield_tau = float(sh.get("reaction_time", 0.5))
        self.shield_min_gap = float(sh.get("min_gap", 1.5))
        self.rw = reward

        self.max_accel = float(ego["accel"])
        self.max_decel = float(ego["decel"])
        self.ego_max_speed = float(ego["max_speed"])
        self.ego_length = float(ego["length"])

        self.ego_id = "ego"
        self.obs_offsets = (+2, +1, 0, -1, -2)
        self.obs_dim = 1 + 5 * 4 + 5 + 5 + 13
        self.action_space = spaces.Box(-1.0, 1.0, shape=(self.act_dim,), dtype=np.float32)
        self.observation_space = spaces.Box(-1.0, 1.0, shape=(self.obs_dim,), dtype=np.float32)

        self._started = False
        self.snapshots = ensure_snapshots(self.snapshot_times, self.step_length)
        self.route_id = None
        self.step_count = 0

    # ==================================================================
    # SUMO 시작 / 에피소드 초기화
    # ==================================================================
    def _start_sumo(self):
        binary = checkBinary("sumo-gui" if self.gui else "sumo")
        cmd = [binary, "-c", f"{NAME}.sumocfg",
               "--step-length", str(self.step_length),
               "--collision.action", "remove",       # 충돌 차량 제거 → 에피소드 종료 판정이 깔끔
               "--collision.check-junctions", "true",
               "--no-warnings", "true", "--no-step-log", "true",
               "--seed", str(self.rng.randint(0, 99999))] + sumo_runtime_args()
        if self.gui:
            cmd += ["--delay", str(self.gui_delay)]
            if self.gui_autostart:
                cmd += ["--start"]
        cwd = os.getcwd()
        os.chdir(OUT)        # 한글 경로 회피 — 상대경로로 실행
        try:
            self.T.start(cmd)
        finally:
            os.chdir(cwd)
        self._started = True

    def _pick_route(self, options):
        if options and options.get("route"):
            return options["route"]
        if self.route_mode == "cycle":
            rid = self.route_ids[self._route_cursor % len(self.route_ids)]
            self._route_cursor += 1
            return rid
        return self.rng.choice(self.route_ids)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self.rng.seed(seed)
            self.np_rng = np.random.default_rng(seed)
        if not self._started:
            self._start_sumo()
        T = self.T
        options = options or {}
        for _attempt in range(5):
            snap = options.get("snapshot") or self.rng.choice(self.snapshots)
            cwd = os.getcwd()
            os.chdir(OUT)
            try:
                T.simulation.loadState(os.path.relpath(snap, OUT))
            finally:
                os.chdir(cwd)
            for _ in range(self.rng.randint(0, self.random_pre_steps)):
                T.simulationStep()
            self.route_id = self._pick_route(options)
            edges = self.routes[self.route_id]["edges"]
            rname = f"ego_route_{self.route_id}"
            if rname not in T.route.getIDList():
                T.route.add(rname, edges)
            T.vehicle.add(self.ego_id, rname, typeID="ego_type",
                          departLane="best", departSpeed="max", departPos="base")
            for _ in range(int(60 / self.step_length)):      # 입구가 막혀 있으면 최대 60 s 대기
                T.simulationStep()
                if self.ego_id in T.vehicle.getIDList():
                    break
            if self.ego_id in T.vehicle.getIDList():
                break
            try:
                T.vehicle.remove(self.ego_id)
            except Exception:
                pass
        else:
            raise RuntimeError("ego 투입 실패: 출발 엣지가 계속 막혀 있습니다.")

        T.vehicle.setSpeedMode(self.ego_id, self.speed_mode)
        T.vehicle.setLaneChangeMode(self.ego_id, self.lc_mode)
        if self.gui:
            try:
                vid = T.gui.getIDList()[0]
                if self.gui_track_ego:
                    T.gui.trackVehicle(vid, self.ego_id)
                T.gui.setZoom(vid, self.gui_zoom)
            except Exception:
                pass

        self.step_count = 0
        self._stopped = 0
        self._prev_accel_cmd = 0.0
        self._prev_dist = 0.0
        self._start_time = T.simulation.getTime()
        return self._get_obs(), {"route": self.route_id}

    # ==================================================================
    # 관측 도우미 (수업 코드와 같은 방식 + 도시 확장)
    # ==================================================================
    _NEIGHBOR_MODES = {+1: (0b10, 0b00), -1: (0b11, 0b01)}

    def _neighbor(self, offset, leader):
        T = self.T
        if offset == 0:
            if leader:
                res = T.vehicle.getLeader(self.ego_id, self.visibility)
                if not res or res[0] == "":
                    return None
                vid, gap = res
            else:
                vid, gap = T.vehicle.getFollower(self.ego_id, self.visibility)
                if vid == "":
                    return None
        elif abs(offset) >= 2:
            front, rear = self._scan_lane_neighbors(offset)
            res = front if leader else rear
            if res is None or res[0] < 0 or res[0] > self.visibility:
                return None
            return float(res[0]), float(res[1])
        else:
            ml, mf = self._NEIGHBOR_MODES[offset]
            pairs = T.vehicle.getNeighbors(self.ego_id, ml if leader else mf)
            if not pairs:
                return None
            vid, gap = min(pairs, key=lambda p: p[1])
        if gap < 0 or gap > self.visibility:
            return None
        return float(gap), T.vehicle.getSpeed(vid)

    def _scan_lane_neighbors(self, direction):
        T = self.T
        try:
            edge = T.vehicle.getRoadID(self.ego_id)
            li = T.vehicle.getLaneIndex(self.ego_id) + direction
            if edge.startswith(":") or li < 0 or li >= T.edge.getLaneNumber(edge):
                return None, None
            my_pos = T.vehicle.getLanePosition(self.ego_id)
            front = rear = None
            for vid in T.lane.getLastStepVehicleIDs(f"{edge}_{li}"):
                d = T.vehicle.getLanePosition(vid) - my_pos
                if d >= 0:
                    g = d - T.vehicle.getLength(vid)
                    if front is None or g < front[0]:
                        front = (g, T.vehicle.getSpeed(vid))
                else:
                    g = -d - self.ego_length
                    if rear is None or g < rear[0]:
                        rear = (g, T.vehicle.getSpeed(vid))
            return front, rear
        except Exception:
            return None, None

    def _best_lanes(self):
        """현재 엣지의 차선별 (경로 지속 거리, 필요한 차선변경 수). 교차로 내부면 None."""
        T = self.T
        edge = T.vehicle.getRoadID(self.ego_id)
        if edge.startswith(":"):
            return None
        out = {}
        try:
            for b in T.vehicle.getBestLanes(self.ego_id):
                lane_id, length, _occ, offset, allows = b[0], b[1], b[2], b[3], b[4]
                if lane_id.rsplit("_", 1)[0] != edge:
                    continue
                out[int(lane_id.rsplit("_", 1)[1])] = (float(length) if allows else 0.0, int(offset))
        except Exception:
            return None
        return out

    def _lane_density(self, offset):
        T = self.T
        try:
            edge = T.vehicle.getRoadID(self.ego_id)
            if edge.startswith(":"):
                return 0.0
            li = T.vehicle.getLaneIndex(self.ego_id) + offset
            if li < 0 or li >= T.edge.getLaneNumber(edge):
                return 1.0
            lane_id = f"{edge}_{li}"
            ego_pos = T.vehicle.getLanePosition(self.ego_id)
            remaining = T.lane.getLength(lane_id) - ego_pos
            links = T.lane.getLinks(lane_id)
            usable = self.visibility if links else min(self.visibility, remaining)
            if usable <= 0:
                return 1.0
            count = 0
            for vid in T.lane.getLastStepVehicleIDs(lane_id):
                if vid == self.ego_id:
                    continue
                d = T.vehicle.getLanePosition(vid) - ego_pos
                if 0.0 < d <= min(self.visibility, remaining):
                    count += 1
            if links and remaining < self.visibility:
                for vid in T.lane.getLastStepVehicleIDs(links[0][0]):
                    if T.vehicle.getLanePosition(vid) <= self.visibility - remaining:
                        count += 1
            return float(np.clip(count / (usable / self.density_veh_len), 0.0, 1.0))
        except Exception:
            return 0.0

    def _tls_info(self):
        """(거리 m, 상태 +1/0/-1, 남은 시간 s) — 시야 안 신호가 없으면 None."""
        T = self.T
        try:
            nxt = T.vehicle.getNextTLS(self.ego_id)
        except Exception:
            return None
        if not nxt:
            return None
        tls_id, _idx, dist, state = nxt[0]
        s = state.lower()
        code = 1.0 if s in ("g", "o") else (0.0 if s == "y" else -1.0)
        try:
            remain = T.trafficlight.getNextSwitch(tls_id) - T.simulation.getTime()
        except Exception:
            remain = 0.0
        return float(dist), code, float(remain), tls_id

    def _next_junction(self):
        """(다음 교차로까지 거리, 우선권 여부)"""
        T = self.T
        try:
            links = T.vehicle.getNextLinks(self.ego_id)
        except Exception:
            links = None
        if not links:
            return None
        lk = links[0]
        dist = lk[7] if len(lk) > 7 else 0.0
        edge = T.vehicle.getRoadID(self.ego_id)
        if not edge.startswith(":"):
            try:
                dist = T.lane.getLength(T.vehicle.getLaneID(self.ego_id)) - \
                    T.vehicle.getLanePosition(self.ego_id)
            except Exception:
                pass
        return float(dist), bool(lk[1])

    def _ttc_risk(self, v):
        lead = self._neighbor(0, True)
        if lead is None:
            return 0.0, None
        gap, lv = lead
        closing = v - lv
        if closing <= 0.1:
            return 0.0, gap
        ttc = gap / closing
        return float(np.clip(1.0 - ttc / 6.0, 0.0, 1.0)), gap

    def _get_obs(self):
        T = self.T
        if self.ego_id not in T.vehicle.getIDList():
            return np.zeros(self.obs_dim, dtype=np.float32)
        v = T.vehicle.getSpeed(self.ego_id)
        vlim = max(T.vehicle.getAllowedSpeed(self.ego_id), 1.0)
        obs = [v / vlim]
        for off in self.obs_offsets:
            lead = self._neighbor(off, True)
            obs += [1.0, 1.0] if lead is None else \
                [lead[0] / self.visibility, float(np.clip((lead[1] - v) / self.vnorm, -1, 1))]
            foll = self._neighbor(off, False)
            obs += [-1.0, -1.0] if foll is None else \
                [-foll[0] / self.visibility, float(np.clip((foll[1] - v) / self.vnorm, -1, 1))]
        best = self._best_lanes()
        cur = T.vehicle.getLaneIndex(self.ego_id)
        for off in self.obs_offsets:
            if best is None:
                obs.append(1.0)
            elif (cur + off) not in best:
                obs.append(-1.0)
            else:
                obs.append(float(np.clip(best[cur + off][0] / self.route_horizon, 0.0, 1.0)))
        for off in self.obs_offsets:
            obs.append(self._lane_density(off))
        # ---- 도시 확장 ----
        tls = self._tls_info()
        if tls is None or tls[0] > self.tls_horizon:
            obs += [1.0, 1.0, 0.0]
        else:
            obs += [tls[0] / self.tls_horizon, tls[1], float(np.clip(tls[2] / 60.0, 0, 1))]
        jn = self._next_junction()
        if jn is None or jn[0] > self.tls_horizon:
            obs += [1.0, 1.0]
        else:
            obs += [jn[0] / self.tls_horizon, 1.0 if jn[1] else -1.0]
        if best is not None and cur in best:
            obs += [float(np.clip(best[cur][1] / 3.0, -1, 1)),
                    float(np.clip(best[cur][0] / self.route_horizon, 0, 1))]
        else:
            obs += [0.0, 1.0]
        obs.append(float(np.clip(T.vehicle.getAcceleration(self.ego_id) / self.max_accel, -1, 1)))
        obs.append(float(np.clip(vlim / self.vnorm, 0, 1)))
        obs.append(float(np.clip(self._next_edge_speed() / self.vnorm, 0, 1)))
        obs.append(float(np.clip(T.vehicle.getDistance(self.ego_id) / self.route_len[self.route_id], 0, 1)))
        obs.append(1.0 if T.vehicle.getRoadID(self.ego_id).startswith(":") else 0.0)
        obs.append(self._ttc_risk(v)[0])
        return np.clip(np.asarray(obs, dtype=np.float32), -1.0, 1.0)

    def _next_edge_speed(self):
        T = self.T
        try:
            idx = T.vehicle.getRouteIndex(self.ego_id)
            route = T.vehicle.getRoute(self.ego_id)
            if 0 <= idx < len(route) - 1:
                return self.edge_speed.get(route[idx + 1], 13.89)
            return self.edge_speed.get(route[-1], 13.89)
        except Exception:
            return 13.89

    # ==================================================================
    # 행동 적용
    # ==================================================================
    def _quantize_lane_change(self, raw):
        raw = float(np.clip(raw, -1.0, 1.0))
        if raw >= self.lane_change_threshold:
            return 1
        if raw <= -self.lane_change_threshold:
            return -1
        return 0

    def _lane_change_is_safe(self, direction):
        T = self.T
        v = T.vehicle.getSpeed(self.ego_id)
        scan_f, scan_r = self._scan_lane_neighbors(direction)

        def closer(a, b):
            if a is None:
                return b
            if b is None:
                return a
            return a if a[0] <= b[0] else b
        lead = closer(self._neighbor(direction, True), scan_f)
        if lead is not None:
            gap, lv = lead
            if gap <= self.lc_front_min + self.lc_front_tau * v or gap <= max(v - lv, 0) * self.lc_horizon:
                return False
        foll = closer(self._neighbor(direction, False), scan_r)
        if foll is not None:
            gap, fv = foll
            if gap <= self.lc_rear_min + self.lc_rear_tau * fv or gap <= max(fv - v, 0) * self.lc_horizon:
                return False
        return True

    def _apply_lane_change(self, lane_change):
        """재량 차선변경: (1) 차선 존재 (2) 경로 이탈 없음 (3) 측면 안전 — 모두 통과해야 실행."""
        T = self.T
        if lane_change == 0:
            return False
        try:
            edge = T.vehicle.getRoadID(self.ego_id)
            if edge.startswith(":"):
                return False
            cur = T.vehicle.getLaneIndex(self.ego_id)
            target = cur + lane_change
            if target < 0 or target >= T.edge.getLaneNumber(edge):
                return False
            best = self._best_lanes()
            if best is not None and cur in best and target in best:
                keep_cur, keep_tgt = best[cur][0], best[target][0]
                if keep_tgt < self.lc_route_keep * keep_cur and keep_tgt < self.route_horizon:
                    return False          # 회전 차로를 벗어나 경로를 놓치는 변경은 막는다
            if self.lc_safety_enabled and not self._lane_change_is_safe(lane_change):
                return False
            T.vehicle.changeLane(self.ego_id, target, self.lane_change_duration)
            return True
        except Exception:
            return False

    def _shield_speed(self, v_des):
        """앞차가 최대 감속으로 급정거해도 추돌하지 않는 최대 속도(Gipps)로 제한."""
        T = self.T
        res = T.vehicle.getLeader(self.ego_id, 150.0)
        if not res or res[0] == "":
            return v_des, False
        lid, gap = res
        vl = T.vehicle.getSpeed(lid)
        bl = max(T.vehicle.getDecel(lid), 1.0)
        b, tau = self.max_decel, self.shield_tau
        room = gap - self.shield_min_gap + vl * vl / (2 * bl)
        v_safe = -b * tau + math.sqrt(max(0.0, (b * tau) ** 2 + 2 * b * max(room, 0.0)))
        if v_des > v_safe:
            return max(0.0, v_safe), True
        return v_des, False

    # ==================================================================
    # 1 스텝
    # ==================================================================
    def step(self, action):
        T = self.T
        a = np.asarray(action, dtype=np.float32).reshape(-1)
        accel_raw = float(np.clip(a[self.accel_index], -1.0, 1.0))
        lane_raw = float(np.clip(a[self.lane_change_index], -1.0, 1.0))
        lane_change = self._quantize_lane_change(lane_raw)
        lane_applied, lane_before, shield_on = False, None, False

        alive_before = self.ego_id in T.vehicle.getIDList()
        if alive_before:
            v = T.vehicle.getSpeed(self.ego_id)
            lane_before = int(T.vehicle.getLaneIndex(self.ego_id))
            accel_cmd = accel_raw * (self.max_accel if accel_raw >= 0 else self.max_decel)
            vlim = T.vehicle.getAllowedSpeed(self.ego_id)
            v_des = float(np.clip(v + accel_cmd * self.step_length, 0.0, min(vlim, self.ego_max_speed)))
            if self.shield_enabled:
                v_des, shield_on = self._shield_speed(v_des)
            T.vehicle.setSpeed(self.ego_id, v_des)
            lane_applied = self._apply_lane_change(lane_change)

        T.simulationStep()
        self.step_count += 1

        collided = self.ego_id in T.simulation.getCollidingVehiclesIDList()
        arrived = self.ego_id in T.simulation.getArrivedIDList()
        teleported = self.ego_id in T.simulation.getStartingTeleportIDList()
        alive = self.ego_id in T.vehicle.getIDList()
        lane_after = int(T.vehicle.getLaneIndex(self.ego_id)) if alive else None

        obs = self._get_obs()
        terminated = truncated = False
        stuck = False
        ego_speed = ego_gap = None
        progress = 1.0 if arrived else (
            T.vehicle.getDistance(self.ego_id) / self.route_len[self.route_id] if alive else None)

        if collided:
            reward = -float(self.rw["collision_penalty"])
            terminated = True
        elif arrived:
            reward = float(self.rw["arrival_bonus"])
            terminated = True
        elif teleported or not alive:
            reward = -float(self.rw.get("stuck_penalty", 0.0))
            terminated = True
            stuck = True
            if alive:
                try:
                    T.vehicle.remove(self.ego_id)
                except Exception:
                    pass
        else:
            ego_speed = T.vehicle.getSpeed(self.ego_id)
            vlim = max(T.vehicle.getAllowedSpeed(self.ego_id), 1.0)
            risk, ego_gap = self._ttc_risk(ego_speed)
            dist = T.vehicle.getDistance(self.ego_id)
            moved = max(0.0, dist - self._prev_dist)
            self._prev_dist = dist
            reward = (self.rw["speed_weight"] * ego_speed / vlim
                      + self.rw["progress_weight"] * moved / (vlim * self.step_length))
            if ego_gap is not None and (
                    ego_gap < self.rw["close_gap_threshold"]
                    or (ego_speed > 2.0 and ego_gap / ego_speed < self.rw.get("close_headway", 0.0))):
                reward -= self.rw["close_gap_penalty"]
            reward -= self.rw["ttc_penalty"] * risk
            # 앞이 비었고 신호도 막지 않는데 서 있으면 감점 (교차로 앞 과도한 머뭇거림 방지)
            if ego_speed < 0.5 and (ego_gap is None or ego_gap > 15.0):
                tls = self._tls_info()
                blocked_by_signal = tls is not None and tls[0] < 40.0 and tls[1] < 1.0
                jn = self._next_junction()
                yielding = jn is not None and jn[0] < 15.0 and not jn[1]
                if not blocked_by_signal and not yielding:
                    reward -= self.rw["idle_penalty"]
            accel_cmd = accel_raw * (self.max_accel if accel_raw >= 0 else self.max_decel)
            reward -= self.rw["jerk_weight"] * abs(accel_cmd - self._prev_accel_cmd) / self.max_accel
            self._prev_accel_cmd = accel_cmd
            if lane_change != 0 and lane_applied:
                reward -= self.rw["lane_change_penalty"]
            elif lane_change != 0:
                reward -= self.rw.get("invalid_action_penalty", 0.0)
            if shield_on:
                reward -= self.rw.get("shield_penalty", 0.0)
            self._stopped = self._stopped + 1 if ego_speed < 0.1 else 0
            if self._stopped >= self.stuck_steps:
                reward -= float(self.rw.get("stuck_penalty", 0.0))
                truncated = True
                stuck = True

        if self.step_count >= self.max_steps and not terminated:
            truncated = True

        info = {
            "collided": collided, "arrived": arrived, "stuck": stuck, "teleported": teleported,
            "speed": ego_speed, "gap": ego_gap, "route": self.route_id, "progress": progress,
            "accel_raw": accel_raw, "lane_change_raw": lane_raw, "lane_change": lane_change,
            "lane_change_applied": lane_applied, "lane_before": lane_before, "lane_after": lane_after,
            "shield": shield_on, "sim_time": T.simulation.getTime(),
        }
        return obs, float(reward), terminated, truncated, info

    # ==================================================================
    # 데이터셋용 부가 정보 (수업 collect_pomdp_data.py 와 같은 이름)
    # ==================================================================
    def get_detected_vehicles(self):
        T = self.T
        out = []
        if self.ego_id not in T.vehicle.getIDList():
            return out
        try:
            edge = T.vehicle.getRoadID(self.ego_id)
            if edge.startswith(":"):
                return out
            ego_lane = T.vehicle.getLaneIndex(self.ego_id)
            ego_pos = T.vehicle.getLanePosition(self.ego_id)
            n = T.edge.getLaneNumber(edge)
            for off in self.obs_offsets:
                li = ego_lane + off
                if li < 0 or li >= n:
                    continue
                for vid in T.lane.getLastStepVehicleIDs(f"{edge}_{li}"):
                    if vid == self.ego_id:
                        continue
                    rel = T.vehicle.getLanePosition(vid) - ego_pos
                    if abs(rel) > self.visibility:
                        continue
                    x, y = T.vehicle.getPosition(vid)
                    out.append({"id": vid, "x": float(x), "y": float(y), "rel_pos": float(rel),
                                "speed": float(T.vehicle.getSpeed(vid)), "lane_offset": int(off),
                                "type": T.vehicle.getTypeID(vid)})
        except Exception:
            pass
        return out

    def get_privileged_state(self, radius=150.0):
        """정책 입력에 쓰지 않는 시뮬레이터 상태 s_t. 주변 radius m 안의 차량 + ego 절대 정보."""
        T = self.T
        if self.ego_id not in T.vehicle.getIDList():
            return {"ego_alive": False, "sim_time": T.simulation.getTime()}
        try:
            x, y = T.vehicle.getPosition(self.ego_id)
            lon, lat = T.simulation.convertGeo(x, y)
            vehicles = []
            for vid in T.vehicle.getIDList():
                if vid == self.ego_id:
                    continue
                vx, vy = T.vehicle.getPosition(vid)
                if (vx - x) ** 2 + (vy - y) ** 2 > radius * radius:
                    continue
                vehicles.append({
                    "id": vid, "type": T.vehicle.getTypeID(vid),
                    "x": float(vx), "y": float(vy),
                    "speed": float(T.vehicle.getSpeed(vid)),
                    "accel": float(T.vehicle.getAcceleration(vid)),
                    "angle": float(T.vehicle.getAngle(vid)),
                    "lane": int(T.vehicle.getLaneIndex(vid)),
                    "lane_id": T.vehicle.getLaneID(vid),
                    "road_id": T.vehicle.getRoadID(vid),
                    "lane_pos": float(T.vehicle.getLanePosition(vid)),
                })
            tls = self._tls_info()
            return {
                "ego_alive": True,
                "sim_time": float(T.simulation.getTime()),
                "route_id": self.route_id,
                "ego_x": float(x), "ego_y": float(y),
                "ego_lon": float(lon), "ego_lat": float(lat),
                "ego_speed": float(T.vehicle.getSpeed(self.ego_id)),
                "ego_accel": float(T.vehicle.getAcceleration(self.ego_id)),
                "ego_angle": float(T.vehicle.getAngle(self.ego_id)),
                "ego_lane": int(T.vehicle.getLaneIndex(self.ego_id)),
                "ego_lane_id": T.vehicle.getLaneID(self.ego_id),
                "ego_road_id": T.vehicle.getRoadID(self.ego_id),
                "ego_road_name": self._edge_name(T.vehicle.getRoadID(self.ego_id)),
                "ego_lane_pos": float(T.vehicle.getLanePosition(self.ego_id)),
                "speed_limit": float(T.vehicle.getAllowedSpeed(self.ego_id)),
                "route_progress_m": float(T.vehicle.getDistance(self.ego_id)),
                "route_length_m": float(self.route_len[self.route_id]),
                "next_tls_id": tls[3] if tls else None,
                "next_tls_dist": tls[0] if tls else None,
                "next_tls_state": tls[1] if tls else None,
                "vehicles": vehicles,
            }
        except Exception:
            return {"ego_alive": False, "sim_time": T.simulation.getTime()}

    def _edge_name(self, eid):
        if eid.startswith(":"):
            return "(교차로)"
        try:
            return self.net.getEdge(eid).getName()
        except Exception:
            return ""

    def close(self):
        if self._started:
            try:
                self.T.close()
            except Exception:
                pass
            self._started = False
