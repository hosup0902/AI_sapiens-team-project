# 진행 상황 (작업 인계용)

영등포 ~ 여의도 일대 실도로 SUMO 환경. 수업 저장소(bmil-ssu/Artificial-Intelligence-and-Control-for-Autonomous-Driving)
의 `road_config.py → road_builder.py → env/sumo/` 구조를 따르되, 도로는 OpenStreetMap에서 **처음부터 새로** 만든다.
(이전 `yeongdeungpo-rotary` 프로젝트의 OSM 파일·빌드 도구는 쓰지 않음)

## 완료

| 단계 | 내용 | 파일 |
|---|---|---|
| OSM 수집 | bbox (37.507, 126.893) ~ (37.537, 126.947), 약 4.8 km × 3.4 km. 도로·건물·토지이용·한강·공원·철도 | `tools/fetch_osm.py` → `data/osm/region.osm` |
| 도로 클리핑 | OSM way를 bbox 경계에서 정확히 자르고 경계 노드 생성 (올림픽대로 등이 영역 밖으로 뻗지 않게) | `env/osm_prep.py: clip_roads` |
| OSM 오류 보정 | 일방 way에 왕복 차로수 태그된 영등포로·서울교 → 편도 4차로 | `road_config.NETWORK["osm_fixes"]` |
| 도로망 | netconvert 2단계(OSM→plain XML→보정→net). 국내 제한속도(5030, 올림픽대로 80), 등급별 기본 차로수, 차로폭 3.2 m, 유턴 금지(막다른 길 제외), 램프·회전교차로 추정, 우측우선 대신 넓은 도로 우선 | `env/road_builder.py: build_net` |
| 교차로 병합 | 영등포 로터리(11점), 서울교 북단(2점), 여의교 북단(4점)을 하나의 신호교차로로 | `NETWORK["join_clusters"]` |
| 신호 | OSM 신호 + 간선 교차로 추정 → 106개. 간선×간선 = 방향별 동시신호(incoming), 간선×이면/횡단보도 = 양방향 동시(opposites), 적색 우회전 허용, Webster 주기·녹색시간(58~114 s) + 녹색 연동 offset | `build_net`, `build_tls` → `env/sumo/ydp.tls.xml` |
| 건물·배경 | 건물 2,187동(층수별 색·레이어), 한강·샛강, 여의도공원·한강공원, 국회 등. multipolygon even-odd 조립, 구멍 있는 폴리곤은 분할 (SUMO poly는 hole 미지원) | `osm_prep.build_polygons` → `ydp.poly.xml` |
| HV 교통 | Krauss 32 / IDM 28 / EIDM 20 / ACC 12 / 버스 5 / 트럭 3 %, 6,546 대/h, randomTrips(경계 출발 가중, 차로수·속도 가중) | `build_traffic` → `ydp.vtypes.xml`, `ydp.rou.xml` |
| AV 과제 | 경계→경계 7개 OD (3.5~4.9 km, 신호 6~33곳): 경인로→마포대교, 여의대방로→서강대교, 서강대교→경인로, 마포대교→신길로, 노들로→국회대로, 국회대로→노량진로, 올림픽대로→신길로 | `road_config.AV_TASKS` → `env/sumo/av_routes.json` |
| 시각화 | 전체/확대/AV 경로 지도 | `tools/render_map.py` → `assets/figures/` |
| 안정성 측정 | 텔레포트·고유 충돌쌍·120 s 이상 정지·처리량·정체 위치 | `tools/stability_test.py`, `tools/jam_map.py` |

## 안정성 개선 이력 (seed 42, step 0.5 s)

| 변경 | 구간 | 텔레포트 | 충돌 | 120 s+ 정지 | 비고 |
|---|---|---:|---:|---:|---|
| 초기 | 0~1800 s | 158 | 626* | 1379 | *매 스텝 중복 집계 |
| 로터리 병합·OSM 보정·우측우선 제거 | 0~1800 s | 92 | 30 | 1101 | |
| 등급별 기본 차로수 | 0~1800 s | 173 | 38 | 1278 | |
| 방향별 동시신호 | 0~1800 s | 79 | 10 | 757 | |
| 서울교·여의교 북단 병합 | 0~1800 s | 35 | 13 | 295 | |
| 〃 (80분, 수요 종료 후 20분 해소 관찰) | 0~4800 s | 285 | 35 | 2816 | 종료 시 375대 잔류 → 후반 과포화 |
| **Webster + 녹색 연동 + 간선/이면 현시 구분** | — | — | — | — | **측정 전 (빌드 완료, 테스트 중단됨)** |

## 다음 할 일

1. `python tools/stability_test.py --end 4800 --step 0.5 --hotspots` 로 신호 최적화 효과 측정
   - 아직 과포화면 `TRAFFIC["period"]` 0.55 → 0.7~0.8 (약 4,500~5,100 대/h) 로 조정하거나 남은 정체 지점을 `join_clusters`/`osm_fixes`로 보정
   - 목표: 텔레포트 ≈ 0, 충돌 ≈ 0, 수요 종료 후 전량 해소. 최종 확인은 `--step 0.1`, 여러 seed
2. `view_road.py` (수업 구조와 같은 GUI 확인 스크립트) 작성 — sumo-gui `ydp.sumocfg` (real world 스킴, 건물 표시)
3. `env/sumo_env.py` / `mdp_config.py`: 수업 코드의 Gymnasium 환경을 이 도시망에 맞게 — AV를 `av_routes.json` 경로로 투입, 관측에 신호 상태·정지선 거리·경로 차로 정보 추가
4. 전문가 정책 → BC → PPO, `collect_pomdp_data.py`로 10^7 transition, HuggingFace 업로드, 프로젝트 페이지

## 빌드 / 실행

```bash
pip install -r requirements.txt
python tools/fetch_osm.py                 # data/osm/region.osm 이 이미 있으면 건너뜀
python -m env.road_builder                # 전체 생성 (--only net|poly|traffic|av)
python tools/render_map.py --tls --labels # assets/figures/map_full.png
python tools/stability_test.py --end 3600 --hotspots
sumo-gui -c env/sumo/ydp.sumocfg
```

주의: Windows에서 SUMO는 한글 경로를 처리하지 못하므로 `road_builder._run`이 `env/sumo`에서 상대경로로 실행한다.
