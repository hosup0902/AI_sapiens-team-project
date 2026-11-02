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
| Webster + 녹색 연동 + 간선/이면 현시 구분 | 0~4800 s | 354 | 63 | 4155 | 종료 시 320대 잔류. 같은 빌드에서 tls.xml 제외 시 689 / 88 / 6642 (811대 잔류) → 신호 최적화 효과 확인 |
| 국회대로×버드나루로, 도신로×신길로 병합 | 0~4800 s | 257 | 45 | 3377 | 교차로 안 0~26 m 엣지에서 재차 신호 대기하던 지점 제거 |
| 여의교 북단 병합에서 고가(layer 1) 노드 제외 | 0~4800 s | 255 | 59 | 3654 | 여의교 북단 충돌 7→2. 아직 과포화(342대 잔류) |
| **60 s 동적 재경로** (`device.rerouting`) | 0~4800 s | 47 | 80* | 458 | 잔류 342 → 0, 평균속도 17.8 → 26.6 km/h. *warn 이라 연쇄 충돌 중복 |
| + `collision.action=remove` (연쇄 충돌 제거) | 0~4800 s | 28 | 41 | 356 | 충돌 1건이 7건으로 집계되던 문제 해소 |
| + 보호좌회전 40 km/h, 고속 비보호 좌회전 금지, 영중로×문래로 신호 | 0~4800 s | 19 | 35 | 302 | 6,546 대/h |
| 〃 수요 **7,200 대/h** (채택) | 0~4800 s | 28 | 53 | 421 | 잔류 2, 평균 25.7 km/h |
| 〃 수요 8,000 대/h | 0~4800 s | 53 | 72 | 678 | 보정 전 69 / 112 |
| 〃 수요 9,000 대/h (보정 전) | 0~4800 s | 76 | 134 | 1074 | 잔류 15 |

※ 위 3행부터 SUMO 1.28 (pip eclipse-sumo) 기준. 이전 행과 SUMO 버전이 달라 절대값 직접 비교는 주의.

## 실제 도로 일치도 검사 (`python tools/fidelity_check.py`)

OSM 원본을 실제 도로 기준으로 SUMO 도로망을 항목별 대조 (2026-11-02):

| 항목 | 결과 | 판단 |
|---|---|---|
| 도로 포함 | 263.3 / 269.1 km (97.8%) | 빠진 5.8 km는 영역 경계 조각(강변북로·대방천로·도림천로 끝단)과 고립 조각 — 의도된 제거 |
| 선형 | 엣지 4,422개, 중앙값 0.01 m · 99% 4.8 m · 최대 7.8 m | 차로 폭 수준 — 실제 위치와 일치 |
| 제한속도 | maxspeed 태그 123개 전부 일치 | 태그 없는 도로는 5030 기본값 |
| 차로 수 | 태그 있는 48.7 km 중 99.5% 일치 | **태그 없는 214.5 km는 등급별 기본값(추정)** — 국회대로·경인로·노들로·여의동로·영중로·버드나루로·영신로 등 확인 필요 |
| 통행 방향 | 불일치 8건 (이면도로 소규모, 영등포로57길 등) | 경미 |
| 신호 | OSM 신호 56곳 중 50곳 반영 · 106개 중 72개는 추정 추가 | OSM 신호 태그가 드문 지역이라 간선 교차로 추정 필요 |
| 입체 교차 | 다른 층 도로를 평면으로 합친 교차로 0건 | 여의교 북단에서 1건 발견 → 수정 (`join_clusters`가 고가 노드 제외) |
| 회전 제한 | **0개** | `fetch_osm.py` 쿼리에 restriction relation이 빠져 있었음 → 쿼리 수정함. **`python tools/fetch_osm.py --force` 후 재빌드 필요** (클라우드 세션은 Overpass 접근 차단) |

결론: 위치·선형·연결 구조·속도는 OSM과 사실상 동일. 실제 도로와 "완전히 동일"하지 않은 부분은
(1) OSM에 차로 수가 없는 간선의 차로 수, (2) 회전 제한 미반영, (3) 추정 신호의 위치·현시(실제 신호 운영 데이터 아님),
(4) 회전 전용차로·포켓 길이, 버스전용차로 미반영. (1)은 로드뷰로 확인해 `road_config.NETWORK["osm_fixes"]`의
`"name:<도로명>"` 보정으로 채운다.

## AV 학습 파이프라인 (2026-11-02 세션)

| 단계 | 내용 | 파일 |
|---|---|---|
| 환경 | Gymnasium `YdpCityEnv`: 교통 스냅샷(900~3300 s) reset, 7개 OD, 관측 44차원(수업 31 + 신호·교차로·경로 차로·TTC), 행동 [가감속, 차선], 오토홀드, 차선변경 안전·경로 게이트, 종방향 안전 필터 | `env/sumo_env.py`, `env/mdp_config.py` |
| 교차로 장애물 인식 | SUMO `getJunctionFoes` + 같은 평면 기하 검사(경로 중심선 ↔ 차체)로 교차로에 갇힌 교차 차량을 경로 장애물로 관측 | `_junction_blockers`, `_geometric_blockers` |
| 전문가 | IDM + 신호 정지 + 추월 (관측만 사용) — 100 ep: 충돌 1 %, 완주 98 % | `expert_policy.py` |
| PPO | 수업 PPO(hybrid). 전문가 데이터로 BC 초기화 → 필터 ON 8.2만 스텝 → 필터 OFF 미세조정 → 오토홀드 후 미세조정 | `train.py`, `results/final/` |
| 평가 | 100 ep, 경로 순환, 충돌 상세 기록 | `evaluate.py` |
| 데이터 | 수업 필수 컬럼 + 도시망 확장, 병렬, 부모 종료 시 워커 종료 | `collect_pomdp_data.py` |
| BC | 수업 `train_bc.py`로 PPO 수집 데이터 모방 | `results/bc_final/` |
| 영상 | 헤드리스 sumo-gui(xvfb) 캡처 + 한글 정보 패널 → mp4 | `tools/record_video.py`, `assets/video/` |
| 페이지 | 정적 프로젝트 페이지 + 결과 주입 | `docs/index.html`, `tools/build_site.py` |

### 최종 결과 (100 에피소드)

| 정책 | 충돌률 | 완주율 | 비고 |
|---|---:|---:|---|
| **PPO 최종 (안전 필터 ON)** | **3 %** | **97 %** | AV 과실 1 %, 2건은 HV가 AV를 들이받음. 필터 개입 0.17 % |
| PPO 최종 (필터 OFF) | 3 % | 96 % | 교착 1 % |
| PPO 필터 ON 학습만 (필터 OFF로 평가) | 7 % | 92 % | 필터 의존 → 필터 OFF 미세조정 계기 |
| 전문가 (필터 ON / OFF, 오토홀드 이전) | 1 % / 1 % | 98 % / 99 % | |

### 이번 세션에서 겪은 문제와 해결 (발표 '문제 해결' 소재)

1. 고정 경로 과포화 → 60 s 동적 재경로 (텔레포트 255 → 28, 잔류 342 → 0)
2. `collision.action=warn`의 연쇄 충돌 집계 → remove
3. 노들로 70 km/h 3차로 횡단 비보호 좌회전 → 국내 법규 기준 금지 규칙
4. AV가 교차로 안 갇힌 차량과 충돌 (SUMO 교차로 감속이 bit0에 묶임) → 경로 장애물 인식
5. 기하 검사가 고가 아래 차량·합류 대기 차량을 오인 → 같은 평면·차체 기준 판정
6. `pkill`로 중단한 수집의 고아 워커가 같은 파일에 계속 기록 → 부모 감시 후 종료
7. PyTorch 스레드 경합으로 BC 초기화가 수십 배 느려짐 → 스레드 2개
8. PPO 필터 의존(필터 OFF 시 7 %) → 필터 OFF 미세조정
9. 정지 중 미세 전진 추돌 → 오토홀드 (필터 OFF 충돌 10 % → 1~3 %)

## 다음 할 일

0. (로컬) `python tools/fetch_osm.py --force` → `python -m env.road_builder` 로 회전 제한 반영, 간선 차로 수 확인·보정
   - 도로망이 바뀌면 관측 의미가 바뀌므로 전문가 데이터 → PPO를 다시 학습할 것
1. 10^7 transition: `python collect_pomdp_data.py --model results/final/model.pt --episodes 6000 --workers <코어수> --no-jsonl --name ydp_ppo_bulk_02`
2. HuggingFace 업로드: `python tools/upload_hf.py --repo <id>/ydp-yeouido-av --files "data/ydp_ppo_*"`
3. 프로젝트 페이지: `python tools/build_site.py ... --hf <링크> --slides <링크>` 후 GitHub Pages 게시
4. 발표자료(13분), 팀 역할 분담, 30초 이상 영상(assets/video) 삽입
5. (개선) 교차로 피추돌 감소: 여의교 북단 등 HV 충돌 다발 교차로 형상 보정, AV 교차로 진입 시 상충 차량 TTC 관측 추가

## 빌드 / 실행

```bash
pip install -r requirements.txt
python tools/fetch_osm.py                 # data/osm/region.osm 이 이미 있으면 건너뜀
python -m env.road_builder                # 전체 생성 (--only net|poly|traffic|av)
python tools/render_map.py --tls --labels # assets/figures/map_full.png
python tools/stability_test.py --end 4800 --step 0.5 --hotspots
python view_road.py                       # sumo-gui (수업 view_road.py 대응)
python evaluate.py --model results/final/model.pt --episodes 100 --workers 4
```

주의: Windows에서 SUMO는 한글 경로를 처리하지 못하므로 `road_builder._run`이 `env/sumo`에서 상대경로로 실행한다.
