"""영등포 ~ 여의도 실도로 환경 설정 (도로 / 건물 / 교통).

이 파일이 도로 환경의 원본(source of truth)이다.
값을 고친 뒤 `python view_road.py` (또는 `python -m env.road_builder`)를 실행하면
env/road_builder.py 가 OSM 원본 → SUMO 네트워크·건물·교통 파일을 다시 만든다.

대상 지역
    서울 영등포구 영등포동·당산동·여의도동 일대 (약 4.7 km × 3.3 km)
      - 영등포역 · 영등포 로터리 · 경인로 · 영등포로 · 영중로 · 신길로 · 버드나루로
      - 여의대방로 · 여의대로 · 여의서로 · 여의동로 · 국회대로 · 의사당대로
      - 여의도 진입 교량: 서울교 · 여의교 · 여의2교 · 마포대교 · 서강대교 · 원효대교(일부)
      - 올림픽대로 · 노들로(강변 도시고속도로, 입체 교차)
단위: 거리 m, 속도 m/s (13.89 m/s = 50 km/h)
"""

# ──────────────────────────────────────────────────────────────
# 1) 대상 영역
#    bbox = (남, 서, 북, 동) 위경도. OSM 데이터는 tools/fetch_osm.py 가 받는다.
# ──────────────────────────────────────────────────────────────
REGION = {
    "name": "ydp_yeouido",
    "bbox": (37.5070, 126.8930, 37.5370, 126.9470),
    "osm_file": "data/osm/region.osm",
}

# ──────────────────────────────────────────────────────────────
# 2) 도로망 (netconvert)
# ──────────────────────────────────────────────────────────────
NETWORK = {
    # 차량이 다니는 OSM 도로 등급. 'residential'을 빼면 간선도로만 남아 가벼워진다.
    "road_types": [
        "motorway", "motorway_link", "trunk", "trunk_link",
        "primary", "primary_link", "secondary", "secondary_link",
        "tertiary", "tertiary_link", "unclassified", "residential",
    ],
    # 국내 도로 제한속도 (안전속도 5030 + 도시고속도로)
    #   OSM에 maxspeed 태그가 있으면 그 값이 우선, 없으면 아래 등급별 기본값
    "default_speed_kmh": {
        "motorway": 80, "motorway_link": 50,      # 올림픽대로 80
        "trunk": 70, "trunk_link": 50,            # 노들로 등 도시고속도로
        "primary": 50, "primary_link": 40,
        "secondary": 50, "secondary_link": 40,
        "tertiary": 50, "tertiary_link": 30,
        "unclassified": 30, "residential": 30,    # 이면도로 30
    },
    # OSM에 lanes 태그가 없을 때의 방향별 기본 차로 수 (국내 도시부 간선 기준)
    #   SUMO 기본값은 secondary=1 이라 신길로·도신로 같은 왕복 4차로 간선이 1차로가 되어 정체가 생긴다
    "default_lanes": {
        "motorway": 3, "trunk": 2, "primary": 3, "secondary": 2, "tertiary": 1,
        "motorway_link": 1, "trunk_link": 1, "primary_link": 1, "secondary_link": 1,
        "tertiary_link": 1, "unclassified": 1, "residential": 1,
    },
    "lane_width": 3.2,            # 국내 도시부 차로폭 (m)
    "junction_join_dist": 18.0,   # 가까운 교차점 합치기 (복합 교차로를 하나의 신호로)
    "tls_cycle": 120,             # 신호 주기 (s) — 서울 간선도로 120~160 s 수준
    "tls_yellow": 3,              # 황색 (s)
    "tls_left_green": 6,          # 보호 좌회전 현시 최소 길이 (s)
    "right_on_red": True,         # 적색 시 우회전 허용(일시정지 후 양보)
    # 비보호 좌회전('g') 허용 상한: 반대 방향 차로 속도가 이 값(m/s)을 넘으면 보호 좌회전 현시를 만든다.
    #   netconvert 기본 19.44(70 km/h)는 노들로(70 km/h, 3차로)를 가로지르는 비보호 좌회전까지 허용해
    #   교차로 안 좌회전 대기차와 직진차 충돌이 반복됐다. 국내 간선은 대부분 보호 좌회전 → 40 km/h
    "tls_minor_left_max_speed": 11.11,
    # 반대편이 이 속도(m/s, 60 km/h) 이상·3차로 이상인데 비보호로만 열리는 좌회전은 금지 (road_builder (d))
    "minor_left_ban_speed": 16.6,
    # OSM 신호 태그가 빠진 간선×간선 교차로 → 신호교차로로 지정 (방향별 동시신호)
    "force_tls": [
        {"name": "영중로×문래로", "lonlat": (126.90580, 37.51807), "radius": 30},
    ],
    "keep_main_component": True,  # 연결이 끊긴 작은 조각 도로 제거
    # 비신호 교차로의 "우측 차량 우선(right-before-left)" 사용 여부.
    #   False → 도로 등급(넓은 도로 우선)으로 우선순위를 정한다 (도로교통법 제26조: 폭이 넓은 도로 우선).
    #   이면도로 격자에서 4방향 우측우선은 SUMO에서 교착(gridlock)을 일으키기 쉽다.
    "right_before_left": False,

    # ── OSM 원본 오류 수동 보정 (way id → 태그 덮어쓰기) ──
    #   영등포 로터리 접근부 영등포로: 일방통행 way인데 양방향 합계 차로수(8)가 태그되어 있음
    #   → 실제(2024 평면화 이후) 편도 4차로로 보정
    "osm_fixes": {
        "219138999": {"lanes": "4"},
        "1506103783": {"lanes": "4"},
        #   서울교(경인로 여의도 구간): 일방 way에 6차로 → 실제 편도 4차로(왕복 8차로)
        "453143057": {"lanes": "4"},
        "453143060": {"lanes": "4"},
        # 도로명 단위 보정: "name:<도로명>" 키는 lanes 태그가 없는 그 도로의 모든 way에 적용.
        #   OSM에 차로 수가 없는 간선이 많다(tools/fidelity_check.py 참고: 국회대로 태그율 7%,
        #   경인로 13%, 노들로 4%, 여의동로 1%, 영중로·버드나루로·영신로 0%).
        #   로드뷰·항공사진으로 실제 차로 수를 확인한 뒤에만 채울 것. 예)
        #   "name:국회대로": {"lanes": "8"},   # 양방향 합계 (일방 way면 편도 차로 수)
    },
    # ── 교차점 강제 병합 ──
    #   OSM에서 하나의 교차로가 여러 점으로 쪼개져 있는 곳을 하나의 신호교차로로 합친다.
    #   (lon, lat) 반경 radius m 안의 모든 교차점을 join
    "join_clusters": [
        {"name": "영등포 로터리", "lonlat": (126.9120, 37.5184), "radius": 45},
        {"name": "서울교 북단(여의도 진입)", "lonlat": (126.9173, 37.5214), "radius": 40},
        {"name": "여의교 북단(여의대방로·여의동로)", "lonlat": (126.9284, 37.5169), "radius": 40},
        #   중앙분리 간선끼리의 교차로가 OSM에서 2~3개 신호점으로 갈라져,
        #   교차로 안(길이 0~26 m 엣지)에서 다시 신호 대기 → 꼬리물기·텔레포트 다발 지점
        {"name": "국회대로×버드나루로", "lonlat": (126.9093, 37.5252), "radius": 35},
        {"name": "도신로×신길로", "lonlat": (126.9104, 37.5107), "radius": 30},
    ],
}

# ──────────────────────────────────────────────────────────────
# 3) 건물·배경 (polyconvert) — 시각 요소, 시뮬레이션/학습에는 영향 없음
# ──────────────────────────────────────────────────────────────
BUILDINGS = {
    "enabled": True,
    "landuse": True,      # 한강, 여의도공원, 녹지, 철도부지 등 배경 면
    # 건물 층수(building:levels)로 색을 나눈다: 저층 → 밝게, 고층(여의도 업무지구) → 진하게
    "level_colors": [     # (최소 층수, RGB 0~255)
        (0, (205, 196, 182)),
        (5, (178, 168, 155)),
        (15, (140, 135, 150)),
        (30, (100, 105, 135)),   # IFC, 파크원, 63빌딩 등 초고층
    ],
}

# ──────────────────────────────────────────────────────────────
# 4) 일반 차량(HV) — Krauss / IDM / EIDM / ACC 혼합 + 버스·트럭
# ──────────────────────────────────────────────────────────────
TRAFFIC = {
    "seed": 42,
    "begin": 0,
    "end": 3600,               # 수요 생성 시간 (s)
    "period": 0.50,            # 평균 차량 생성 간격 (s) ≈ 7,200 대/h (영역 전체). 0.45(8,000)부터 텔레포트·충돌 급증
    "fringe_factor": 8.0,      # 출발/도착을 경계(교량·간선 끝)에 몰아주는 정도
    "min_trip_distance": 800,  # 너무 짧은 통행 제외 (m)
    "through_bias": True,      # 간선도로(우선순위 높은 도로)에서 출발/도착 비중 ↑
    "time_to_teleport": 180,   # 정체 고착 감지 시간 (s). 안정성 지표로 텔레포트 수 집계
    # 실행 옵션 (ydp.sumocfg 에 기록 → sumo-gui · 학습 · 데이터 수집 · 안정성 측정 공통)
    "runtime": {
        # 동적 경로 재탐색: 60 s마다 실시간 통행시간으로 경로를 다시 고른다 (내비게이션 이용 운전자).
        #   고정 최단경로만 쓰면 모든 차가 같은 간선으로 몰려 국회대로·로터리 접근부가 과포화된다.
        #   측정(80분, 6,546대): 텔레포트 255 → 28, 종료 시 잔류 342 → 0대, 평균속도 17.8 → 26.6 km/h
        "rerouting_period": 60,
        # 충돌 차량 처리: 'warn'은 충돌 차량이 교차로에 남아 뒤차들의 연쇄 충돌로 부풀려 집계된다
        "collision_action": "remove",
    },
    "controllers": {
        "krauss": {"probability": 0.32, "carFollowModel": "Krauss",
                   "accel": 2.4, "decel": 4.5, "tau": 1.0, "min_gap": 2.5,
                   "sigma": 0.4, "speed_factor": 1.0, "speed_dev": 0.12,
                   "color": "255,220,0"},
        "idm": {"probability": 0.28, "carFollowModel": "IDM",
                "accel": 2.0, "decel": 3.8, "tau": 1.2, "min_gap": 2.0,
                "speed_factor": 0.98, "speed_dev": 0.10, "color": "0,200,230"},
        "eidm": {"probability": 0.20, "carFollowModel": "EIDM",
                 "accel": 2.2, "decel": 4.0, "tau": 1.1, "min_gap": 2.0,
                 "speed_factor": 1.0, "speed_dev": 0.10, "color": "255,140,0"},
        "acc": {"probability": 0.12, "carFollowModel": "ACC",
                "accel": 2.0, "decel": 4.0, "tau": 1.4, "min_gap": 2.2,
                "speed_factor": 1.02, "speed_dev": 0.05, "color": "220,0,220"},
        "bus": {"probability": 0.05, "carFollowModel": "Krauss", "vClass": "bus",
                "accel": 1.2, "decel": 4.0, "tau": 1.3, "min_gap": 3.0,
                "sigma": 0.3, "length": 11.0, "speed_factor": 0.9,
                "speed_dev": 0.05, "color": "40,170,60"},
        "truck": {"probability": 0.03, "carFollowModel": "Krauss", "vClass": "truck",
                  "accel": 1.1, "decel": 4.0, "tau": 1.4, "min_gap": 3.0,
                  "sigma": 0.3, "length": 9.0, "speed_factor": 0.88,
                  "speed_dev": 0.05, "color": "120,120,120"},
    },
    # 차로변경 성향 (SUMO LC2013) — 협조·전략 변경으로 회전차로 진입/합류
    "lane_change": {"lcStrategic": 1.0, "lcCooperative": 1.0,
                    "lcSpeedGain": 1.0, "lcKeepRight": 0.5, "lcAssertive": 1.2},
}

# ──────────────────────────────────────────────────────────────
# 5) 자율주행 차량(AV, ego)
# ──────────────────────────────────────────────────────────────
EGO = {
    "accel": 3.0,
    "decel": 6.0,
    "max_speed": 22.22,    # 80 km/h (올림픽대로 제외 구간은 제한속도가 상한)
    "length": 4.6,
    "color": "255,0,0",
}

# AV 과제 경로 — 출발/도착을 (경도, 위도, 도로 이름 힌트)로 지정한다.
#   모두 영역 경계(교량 끝·간선도로 끝)에서 출발해 다른 경계로 나가는 실제 통행 OD이다.
#   road_builder 가 각 점 반경 80 m 안에서 이름이 맞는 엣지를 골라 최단 시간 경로를 만들고
#   env/sumo/av_routes.json 에 저장한다.
AV_TASKS = [
    {"id": "gyeongin_to_mapo",
     "from": (126.8933, 37.5114, "경인로"), "to": (126.9422, 37.5367, "마포대로"),
     "desc": "경인로(문래) → 영등포역·로터리 → 여의도 → 마포대교"},
    {"id": "daebang_to_seogang",
     "from": (126.9232, 37.5073, "여의대방로"), "to": (126.9251, 37.5367, "국회대로"),
     "desc": "여의대방로(대방역) → 여의도 관통 → 서강대교"},
    {"id": "seogang_to_gyeongin",
     "from": (126.9249, 37.5367, "국회대로"), "to": (126.8933, 37.5116, "경인로"),
     "desc": "서강대교 → 여의도 → 영등포 로터리 → 경인로(문래)"},
    {"id": "mapo_to_singil",
     "from": (126.9417, 37.5367, "마포대로"), "to": (126.9110, 37.5073, "신길로"),
     "desc": "마포대교 → 여의도 → 영등포 → 신길로"},
    {"id": "nodeul_to_dangsan",
     "from": (126.9467, 37.5168, "노들로"), "to": (126.8933, 37.5298, "국회대로"),
     "desc": "노들로(노량진) → 여의도/영등포 → 국회대로(당산)"},
    {"id": "dangsan_to_noryangjin",
     "from": (126.8933, 37.5297, "국회대로"), "to": (126.9467, 37.5133, "노량진로"),
     "desc": "국회대로(당산) → 영등포 → 노량진로"},
    {"id": "olympic_to_singil",
     "from": (126.9467, 37.5175, "올림픽대로"), "to": (126.9110, 37.5073, "신길로"),
     "desc": "올림픽대로 → 진출 램프 → 여의도·영등포 → 신길로"},
]