# 평가 기준 대조표 (`6_Project_Evaluation.md` 기준)

수업 평가 문서의 항목마다 이 저장소에서 근거가 되는 결과물과 수치를 짝지었다. 수치는 `results/` 아래 JSON과 같다.

## 1. 최종 프로젝트 평가 요소 (2.2)

| 요구 | 기준 | 결과 | 근거 |
|---|---|---|---|
| Collision Rate | < 5 % (100 에피소드) | PPO 3 % (필터 ON) · 3 % (필터 OFF) · 0 % (설계 경로 고정) | `results/final/eval_ppo*.json` |
| 목적지 완주 | Start → Goal | 완주 97 % / 96 % / 100 % | 같은 파일 `success_rate` |
| └ 비정상 정지 | 하지 않는가 | 에피소드별 최장 정지 중앙값이 규칙 전문가와 같은 수준(신호 한 주기). v2 데이터에서는 정지 시간 중 적·황신호 앞 비율을 직접 측정 | `results/analysis/dataset_stats.json` `longest_stop_s`, `stopped_at_red_pct_of_stops` |
| └ 잘못된 Route | 빠지지 않는가 | 재경로를 끈 평가에서 설계 경로 엣지 일치율 94.6 % (나머지는 0.5 s 안에 지나는 교차로 연결 엣지) | `eval_ppo_fixed.json` `route_match_arrived` |
| └ 무한정 대기 | 하지 않는가 | 240 s 연속 정지 = 교착 실패로 종료·집계 (PPO 0~1 %), 원인은 대기열 선두 추적으로 실제 정체 확인 | `results/analysis/failures.md` |
| 충분한 일반 차량 | 일정 수 이상 | HV 7,200 대/h (동시 1,000여 대), Krauss·IDM·EIDM·ACC·버스·트럭 혼합 | `env/road_config.py`, README 4절 |
| 의미 있는 interaction | HV + AV | 에피소드당 교차로 39회 · 신호 정지 1.8회 · 차선변경 2.3회, 반경 50 m 평균 7.3대 | `results/analysis/interaction_summary.json` |
| 도로 형태 | 제한 없음 | 로터리(영등포), 신호교차로 107곳, 교량·램프 합류/분기, 고가·지하차도 | README 1절 |

## 2. 평가 기준 요약표 (2.3)

| 평가 항목 | 이 프로젝트에서 보여주는 것 | 파일 |
|---|---|---|
| 도로 구조 구현 | OSM 대비 도로 포함 97.8 %, 선형 오차 중앙값 0.01 m, 층(고가/평면) 오연결 0 | `tools/fidelity_check.py`, README 4절 |
| 도로 구조의 의미 | 로터리·교량 끝 신호·램프 합류·다차로 간선 → AV 의사결정 | 발표 2~3번 슬라이드 |
| Vehicle Interaction | 상호작용 횟수·주변 차량 수·TTC 분포 정량화 | `tools/interaction_analysis.py`, `assets/figures/interaction_*.png` |
| Simulation 안정성 | 동적 재경로로 텔레포트 255 → 28~43건/80분(9,600여 대 중 0.3~0.45 %), 종료 잔류 0~2대, 시드 4개 | `tools/stability_test.py`, README 4절 |
| AV 주행 성능 | 위 1절 | `results/final/` |
| Traffic 구성 | 7,200 대/h, 컨트롤러 4종 + 버스·트럭, 평균 25.7~26.1 km/h | README 4절 |
| Dataset 구축 | 10^7 이상, 수업 기본 항목 + State 절대 정보 포함 (v2), 항목별 의미·단위·저장 구조 문서화 | `data/`, `docs/data_dictionary.md`, `docs/dataset_card.md`, `tools/dataset_stats.py` |
| 분석 및 설명 | 문제 → 원인 측정 → 해결 → 재측정 9건 | `PROGRESS.md` 문제 해결 목록, 발표 15~16번 |
| 최종 결과물 | 프로젝트 페이지, 코드(환경/학습/평가/수집 분리), 모델, 발표자료(PDF), 데이터 | 아래 3절 |

## 3. 제출물 체크리스트 (2.4, 아이캠퍼스 마감 전)

| 제출물 | 위치 | 상태 |
|---|---|---|
| 프로젝트 페이지 | `docs/index.html` (GitHub Pages로 게시) | 준비됨 — 저장소 Settings → Pages에서 `docs/` 게시 필요 |
| └ 코드 링크 | GitHub `ydp-yeouido/` | 페이지에 연결됨 (main 브랜치 기준 — 작업 브랜치를 main에 병합 필요) |
| └ 발표자료 PDF 링크 | `docs/final/최종발표_AI_sapiens.pdf` | 페이지에 연결됨 (구글 드라이브 링크로 바꾸려면 `tools/build_site.py --slides <링크>`) |
| └ 데이터(HuggingFace) 링크 | `tools/upload_hf.py` | **팀 계정 토큰으로 업로드 필요**, 업로드 전까지 페이지는 GitHub `data/`로 연결 |
| 코드 | `env/`(환경) · `train.py`, `train_offline.py`, `algorithms/`(학습) · `evaluate.py`(평가) · `collect_pomdp_data.py`, `tools/collect_multi.py`(수집) | 준비됨 |
| 학습한 모델 | `results/final/model.pt` (PPO), `results/final/bc/`, `results/final/td3bc/` | 준비됨 |
| 발표자료 | `docs/final/최종발표_AI_sapiens.pptx` + `.pdf`, 대본 `docs/final/최종발표_대본.md` | 준비됨 — 팀원 이름 입력 필요 |
| 주행 데이터 | `data/` (JSONL 전체 컬럼 + NPZ v1/v2) | 준비됨 — HF 업로드 필요 |
| 동료 평가 | 수업 양식 | 발표 당일 |

## 4. 발표 (13분, 동료 평가 10점)

- 슬라이드 17장, 대본 목표 합계 약 12분 40초 (영상 1분 포함). 질문 시간이 따로 없다면 슬라이드 11(정책 비교)을 줄여 조정.
- 동료 평가의 흐름 "왜 이 도로 → 어떤 interaction → AV가 해결 → 데이터에 기록"을 슬라이드 순서(도로 → 학습 → 결과 → 데이터 → 정리)로 따른다.
