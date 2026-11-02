# 영등포 ~ 여의도 실도로 SUMO 자율주행 환경

> 자율주행 인공지능 및 제어 — 팀 프로젝트 (AI_sapiens)
> **"서울 영등포 로터리 · 여의도 교량 · 신호교차로 106곳이 얽힌 실제 도시망에서, 일반 차량 수천 대 사이를 AV가 출발지부터 목적지까지 스스로 주행한다."**

![map](assets/figures/map_full.png)

## 1. 왜 이 지역인가

| 구조 | 실제 위치 | AV가 해야 하는 의사결정 |
|---|---|---|
| 회전교차로 → 평면 신호교차로 (2024 평면화) | 영등포 로터리 (11개 OSM 점을 1개 교차로로 병합) | 다방향 진입 차량과 상충, 출구 차선 선택 |
| 교량 진입·진출 | 서울교 · 여의교 · 마포대교 · 서강대교 | 교량 끝 신호교차로 직전 차로 합류/분기 |
| 도시고속도로 램프 | 올림픽대로 · 노들로 진출입 | 고속(80 km/h) → 도심(50 km/h) 감속, 램프 합류 |
| 입체 교차 | 여의대방로 고가, 여의교·대방·여의도 지하차도 | 같은 도로명이라도 층이 다른 경로 구분 |
| 다차로 간선 + 이면도로 격자 | 여의대로(편도 4~5), 경인로, 국회대로 | 회전 전 차로 확보, 느린 차 추월, 신호 대기열 |

AV 과제는 영역 경계에서 경계로 나가는 **실제 통행 OD 7개** (3.5~4.9 km, 신호 6~33곳):

| id | 경로 | 길이 | 신호 |
|---|---|---:|---:|
| gyeongin_to_mapo | 경인로(문래) → 영등포역·로터리 → 여의도 → 마포대교 | 4.50 km | 16 |
| daebang_to_seogang | 여의대방로(대방역) → 여의도 관통 → 서강대교 | 3.49 km | 15 |
| seogang_to_gyeongin | 서강대교 → 여의도 → 영등포 로터리 → 경인로 | 3.77 km | 31 |
| mapo_to_singil | 마포대교 → 여의도 → 영등포 → 신길로 | 4.04 km | 10 |
| nodeul_to_dangsan | 노들로(노량진) → 여의도/영등포 → 국회대로(당산) | 4.91 km | 19 |
| dangsan_to_noryangjin | 국회대로(당산) → 영등포 → 노량진로 | 4.76 km | 33 |
| olympic_to_singil | 올림픽대로 → 진출 램프 → 여의도·영등포 → 신길로 | 4.78 km | 6 |

![routes](assets/figures/av_routes.png)

## 2. 구성

```
ydp-yeouido/
├─ env/
│  ├─ road_config.py     도로·교통 설정 (source of truth): 영역, 국내 제한속도/차로 기본값, OSM 보정,
│  │                     교차로 병합, 신호, HV 컨트롤러 믹스, AV 과제 OD
│  ├─ road_builder.py    OSM → netconvert 2단계 → 신호(Webster+연동) → 건물 → 교통 → AV 경로
│  ├─ osm_prep.py        OSM 클리핑 · 건물/한강 multipolygon 조립
│  ├─ mdp_config.py      AV POMDP 정의 (관측 44차원 / 행동 2차원 / 보상)
│  ├─ sumo_env.py        Gymnasium 환경 (YdpCityEnv) — 스냅샷 reset, 신호·경로 관측, 안전 게이트
│  └─ sumo/              생성된 SUMO 파일 (ydp.net.xml, ydp.rou.xml, ydp.tls.xml, ydp.poly.xml, …)
├─ expert_policy.py      규칙 기반 전문가 (IDM + 신호 정지 + 추월) — BC 교사
├─ algorithms/, utils/   수업 제공 PPO / BC / 네트워크 / 평가 / 로거 (그대로 사용)
├─ train.py              PPO 학습 (BC warm start → 미세조정, best 체크포인트)
├─ train_bc.py           Behavior Cloning (수업 코드 그대로)
├─ evaluate.py           100 에피소드 평가 (충돌률 / 완주율 / 경로별)
├─ collect_pomdp_data.py POMDP 데이터 수집 (수업 필수 컬럼 + 도시망 확장, 병렬)
├─ view_road.py          sumo-gui 도로 확인 (수업 view_road.py 대응)
├─ tools/                fetch_osm · render_map · stability_test · fidelity_check · jam_map ·
│                        record_video · upload_hf
├─ docs/                 dataset_card.md (HuggingFace README)
└─ results/final/        최종 모델 · 평가 결과
```

## 3. 실행

```bash
pip install -r requirements.txt            # SUMO는 eclipse-sumo(pip) 또는 설치본 + SUMO_HOME
python tools/fetch_osm.py                  # data/osm/region.osm 이 있으면 건너뜀
python -m env.road_builder                 # 도로·신호·건물·교통·AV 경로 생성 (~30 s)
python view_road.py                        # sumo-gui로 확인 (--av gyeongin_to_mapo: AV 함께)

python tools/stability_test.py --end 4800 --step 0.5 --hotspots   # HV 안정성 (텔레포트·충돌·정체)
python tools/fidelity_check.py             # OSM 대비 도로 일치도

python collect_pomdp_data.py --policy expert --episodes 140 --workers 4 --expert-noise 0.1 --name expert_train
python train_bc.py --data data/expert_train.npz            # BC
python train.py --bc-data data/expert_train.npz --timesteps 200000 --run-name final   # PPO
python evaluate.py --model results/final/model.pt --episodes 100 --workers 4
python tools/record_video.py --model results/final/model.pt --route gyeongin_to_mapo   # 주행 영상
python collect_pomdp_data.py --model results/final/model.pt --episodes 7000 --workers 8 --no-jsonl
python tools/upload_hf.py --repo <hf-id>/ydp-yeouido-av --files "data/*.npz" "data/*.jsonl.gz"
```

<!-- RESULTS -->
