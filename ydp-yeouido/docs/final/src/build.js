// 최종발표 PPT 생성 (pptxgenjs). 수치는 summary.json(make_summary.py)에서 읽는다.
//   npm install pptxgenjs react-icons react react-dom sharp
//   python docs/final/src/make_summary.py && node docs/final/src/build.js docs/final/최종발표_AI_sapiens.pptx
const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
let applyTheme = async () => {};
try { ({ applyTheme } = require(process.env.APPLY_THEME || "./apply_theme.js")); } catch (e) { /* optional */ }

const DIR = __dirname;
const ROOT = path.resolve(DIR, "../../..");
const OUT = process.argv[2] || path.join(DIR, "final.pptx");
const S = JSON.parse(fs.readFileSync(path.join(DIR, "summary.json"), "utf8"));
const IMG = (n) => path.join(DIR, "img", n);
const pct = (x, d = 0) => (x === null || x === undefined ? "–" : (100 * x).toFixed(d) + " %");
const num = (x) => x.toLocaleString("en-US");
const E = S.eval, DT = S.data, IN = S.interaction;
const M = IN.mean_per_episode;

const THEME = {
  name: "YDP Yeouido AV",
  headFontFace: "Malgun Gothic",
  bodyFontFace: "Malgun Gothic",
  colors: {
    dk1: "14213D", lt1: "FFFFFF", dk2: "3E4757", lt2: "F1F3F7",
    accent1: "C8102E", accent2: "1F5FA8", accent3: "E09A2B", accent4: "2E7D5B",
    accent5: "6B7280", accent6: "24345C", hlink: "1F5FA8", folHlink: "6B7280",
  },
};
const HEX = THEME.colors;
const PINK = "FCE8EB";

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = "영등포–여의도 자율주행 최종발표";
  pres.author = "AI_sapiens";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "TITLE_DARK", background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.4, w: 6.4, h: 2.0, fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.55, w: 6.2, h: 1.4, fontSize: 18, color: "C9D3E3", valign: "top", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT", background: { color: C.background1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 30, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
      { text: { text: "AI_sapiens · 최종발표 · 영등포–여의도 실도로 SUMO 자율주행", options: { x: 0.6, y: 7.0, w: 9, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: HEX.accent5, align: "right" },
  });
  pres.defineSlideMaster({
    title: "SECTION_DARK", background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 0.5, w: 12, h: 0.9, fontSize: 30, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: "9AA5B8", align: "right" },
  });

  const I = {
    user: await icon(fa.FaUserCircle, "FFFFFF"), rotary: await icon(fa.FaSyncAlt, "FFFFFF"),
    bridge: await icon(fa.FaArchway, "FFFFFF"), ramp: await icon(fa.FaRoad, "FFFFFF"),
    layer: await icon(fa.FaLayerGroup, "FFFFFF"), grid: await icon(fa.FaThLarge, "FFFFFF"),
    arrow: await icon(fa.FaArrowRight, HEX.accent5), traffic: await icon(fa.FaTrafficLight, "FFFFFF"),
    brain: await icon(fa.FaBrain, "FFFFFF"), shield: await icon(fa.FaShieldAlt, "FFFFFF"),
    eye: await icon(fa.FaEye, "FFFFFF"), hand: await icon(fa.FaHandPaper, "FFFFFF"),
    db: await icon(fa.FaDatabase, "FFFFFF"), pin: await icon(fa.FaMapMarkerAlt, "FFFFFF"),
    plus: await icon(fa.FaPlusCircle, "FFFFFF"),
  };
  const NOTES = [];
  const card = (s, x, y, w, h, fill, name) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.1, objectName: name });
  const dot = (s, x, y, d, col, ic, alt, name) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: col }, line: { color: col }, objectName: name });
    s.addImage({ data: ic, x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52, altText: alt });
  };
  const tx = (s, t, o) => s.addText(t, { margin: 0, isTextBox: true, ...o });

  // 1. 표지 + 팀 ─────────────────────────────
  pres.addSection({ title: "도로" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "도로" });
  s.addText("영등포 로터리부터 여의도까지", { placeholder: "title" });
  s.addText([{ text: "실제 서울 도시망에서 일반 차량 7,200대/h 사이를 달리는 자율주행 차량", options: { breakLine: true } },
             { text: "자율주행 인공지능 및 제어 · 최종발표 · 팀 AI_sapiens", options: { color: "FF8A99", fontSize: 15 } }], { placeholder: "body" });
  [["[팀원 A]", "도로 환경 구축"], ["[팀원 B]", "일반 차량 · 안정성"], ["[팀원 C]", "AV 학습 · 평가"], ["[팀원 D]", "데이터 · 영상 · 페이지"]].forEach(([n, r], i) => {
    const x = 7.75 + (i % 2) * 2.65, y = 1.55 + Math.floor(i / 2) * 2.05;
    card(s, x, y, 2.45, 1.85, C.accent6, `role-${i}`);
    dot(s, x + 0.25, y + 0.25, 0.55, C.accent1, I.user, "팀원", `role-dot-${i}`);
    tx(s, n, { x: x + 0.25, y: y + 0.88, w: 2.0, h: 0.4, fontSize: 16, bold: true, color: C.background1 });
    tx(s, r, { x: x + 0.25, y: y + 1.28, w: 2.05, h: 0.45, fontSize: 13, color: "C9D3E3", valign: "top" });
  });
  NOTES.push(`[약 30초] 안녕하세요, 팀 AI_sapiens입니다. 저희는 서울 영등포 로터리부터 여의도까지 실제 도심 도로를 SUMO로 옮기고, 시간당 7,200대의 일반 차량 사이에서 자율주행 차량이 출발지부터 목적지까지 스스로 주행하도록 학습했습니다. 도로 환경, 일반 차량과 안정성, AV 학습과 평가, 데이터와 결과물 정리로 역할을 나눴습니다. 도로, 학습, 결과, 데이터, 문제 해결 순서로 말씀드리겠습니다.`);

  // 2. 선정 지역 ─────────────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "도로" });
  s.addText("왜 영등포·여의도인가: 도심 자율주행 구조가 한곳에", { placeholder: "title" });
  s.addImage({ path: IMG("map_full.jpg"), x: 0.6, y: 1.4, w: 7.6, h: 5.37, altText: "SUMO로 구현한 영등포~여의도 도로망 전체" });
  [["107", "신호교차로"], ["519 km", "차로 총연장"], ["2,187", "건물 · 한강 · 여의도공원"], ["7개", "실제 출퇴근 OD 경로 (3.5~4.9 km)"]].forEach(([v, l], i) => {
    const y = 1.4 + i * 1.33;
    card(s, 8.6, y, 4.1, 1.18, C.background2, `stat-${i}`);
    tx(s, v, { x: 8.85, y: y + 0.1, w: 3.7, h: 0.6, fontSize: 30, bold: true, color: i === 3 ? C.accent1 : C.text1 });
    tx(s, l, { x: 8.85, y: y + 0.7, w: 3.7, h: 0.38, fontSize: 13, color: C.text2 });
  });
  NOTES.push(`[약 40초] 선정 지역은 영등포·당산·여의도 일대 4.8 km × 3.4 km입니다. 오픈스트리트맵에서 처음부터 만들었고, 신호교차로 107곳, 차로 519 km, 건물 2,187동과 한강까지 들어 있습니다. 이 지역을 고른 이유는 2024년에 평면화된 영등포 로터리, 서울교·마포대교 같은 교량 진입로, 올림픽대로 램프, 고가와 지하차도, 다차로 간선이 한 영역에 모두 있어서, 도심 자율주행에서 만나는 의사결정 문제가 거의 다 나오기 때문입니다. AV 과제는 영역 끝에서 끝으로 가는 실제 출퇴근 경로 7개입니다.`);

  // 3. 구조 → 상호작용 → 판단 ─────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "도로" });
  s.addText("도로 구조 → 차량 상호작용 → AV 의사결정", { placeholder: "title" });
  s.addImage({ path: IMG("zoom_rotary.jpg"), x: 0.6, y: 1.4, w: 4.2, h: 4.2, altText: "영등포 로터리 확대: 11개 교차점을 하나의 신호교차로로 병합" });
  tx(s, "영등포 로터리 — OSM 11개 점을 신호교차로 1개로 병합", { x: 0.6, y: 5.7, w: 4.2, h: 0.5, fontSize: 11, color: C.accent5, valign: "top" });
  const rows = [[I.rotary, "영등포 로터리", "다방향 진입 차량과 상충", "진입 시점·속도, 출구 차로"],
                [I.bridge, "교량 끝 신호교차로", "합류·분기, 신호 대기열", "회전 전 차로 확보, 정지·출발"],
                [I.ramp, "올림픽대로·노들로 램프", "80 km/h 본선 합류", "감속·가속, 합류 간격"],
                [I.grid, "다차로 간선", "느린 버스·트럭", "안전 간격 확인 후 추월"]];
  rows.forEach(([ic, a, b, c], i) => {
    const y = 1.4 + i * 1.18;
    dot(s, 5.15, y + 0.2, 0.55, i === 0 ? C.accent1 : C.accent2, ic, a, `rdot-${i}`);
    tx(s, a, { x: 5.85, y: y + 0.05, w: 2.3, h: 0.85, fontSize: 15, bold: true, color: C.text1, valign: "middle" });
    card(s, 8.2, y + 0.05, 2.15, 0.85, C.background2, `rb-${i}`);
    tx(s, b, { x: 8.32, y: y + 0.05, w: 1.95, h: 0.85, fontSize: 12, color: C.text1, valign: "middle" });
    card(s, 10.5, y + 0.05, 2.2, 0.85, PINK, `rc-${i}`);
    tx(s, c, { x: 10.62, y: y + 0.05, w: 2.0, h: 0.85, fontSize: 12, color: C.text1, valign: "middle" });
  });
  tx(s, "상호작용", { x: 8.2, y: 1.05, w: 2.1, h: 0.3, fontSize: 12, bold: true, color: C.accent2 });
  tx(s, "AV가 해야 할 판단", { x: 10.5, y: 1.05, w: 2.2, h: 0.3, fontSize: 12, bold: true, color: C.accent1 });
  NOTES.push(`[약 45초] 이 구조들이 곧 상호작용을 만들고, 상호작용이 AV의 판단 문제가 됩니다. 로터리에서는 여러 방향 진입 차량과 상충해서 진입 시점과 출구 차로를 골라야 하고, 교량 끝 신호교차로에서는 회전 전에 차로를 확보하고 대기열에서 멈췄다 출발해야 합니다. 램프에서는 시속 80 km 본선과 합류하고, 다차로 간선에서는 느린 버스나 트럭을 안전하게 추월해야 합니다. 왼쪽은 영등포 로터리인데, 오픈스트리트맵에서는 11개 점으로 쪼개져 있어서 교차로 안에서 다시 신호를 기다리는 문제가 있었고, 하나의 신호교차로로 합쳤습니다.`);

  // 4. 도로 구축 + 일치도 ─────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "도로" });
  s.addText("도로 구축: 국내 규칙을 반영하고, 실제 지도와 대조", { placeholder: "title" });
  const steps = ["OSM 수집 · 영역 경계에서 도로 절단", "국내 제한속도 5030 · 차로폭 3.2 m", "쪼개진 교차로 5곳 병합 (고가 위 노드 제외)", "보호 좌회전 · 적색 우회전 · 고속 비보호 좌회전 금지", "Webster 신호 주기 + 녹색 연동 (107곳)"];
  steps.forEach((t, i) => {
    const y = 1.45 + i * 0.95;
    s.addShape(pres.shapes.OVAL, { x: 0.6, y: y + 0.08, w: 0.5, h: 0.5, fill: { color: C.accent2 }, line: { color: C.accent2 }, objectName: `step-${i}` });
    tx(s, String(i + 1), { x: 0.6, y: y + 0.08, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle" });
    tx(s, t, { x: 1.3, y, w: 5.3, h: 0.66, fontSize: 15, color: C.text1, valign: "middle" });
  });
  [["97.8 %", "도로 포함 (OSM 대비)"], ["0.01 m", "선형 오차 중앙값 (99 %: 4.8 m)"], ["99.5 %", "차로 수 일치 (OSM 태그 구간)"], ["0건", "층이 다른 도로의 평면 연결"]].forEach(([v, l], i) => {
    const x = 7.0 + (i % 2) * 2.9, y = 1.45 + Math.floor(i / 2) * 1.9;
    card(s, x, y, 2.7, 1.7, C.background2, `fid-${i}`);
    tx(s, v, { x: x + 0.25, y: y + 0.25, w: 2.3, h: 0.7, fontSize: 30, bold: true, color: C.text1 });
    tx(s, l, { x: x + 0.25, y: y + 1.0, w: 2.3, h: 0.55, fontSize: 12, color: C.text2, valign: "top" });
  });
  tx(s, "한계: OSM에 차로 수가 없는 간선은 등급별 추정, 회전 제한은 OSM 재수집 후 반영 예정", { x: 7.0, y: 5.4, w: 5.7, h: 0.6, fontSize: 12, color: C.accent5, valign: "top" });
  NOTES.push(`[약 45초] 도로는 오픈스트리트맵에서 국내 규칙을 반영해 만들었습니다. 제한속도 5030과 차로폭 3.2 m, 쪼개진 교차로 병합, 보호 좌회전과 적색 우회전, 그리고 도로교통법상 표지가 있어야만 하는 비보호 좌회전을 시속 60 km 이상 3차로 도로에서는 금지했습니다. 신호 107곳은 Webster 방식으로 주기를 잡고 녹색 연동을 걸었습니다. 만든 도로가 실제와 같은지 검사하는 도구도 만들었는데, 오픈스트리트맵 대비 도로의 97.8 %를 포함하고 위치 오차는 중앙값 1 cm 수준이며, 고가와 평면 도로가 잘못 연결된 곳은 없습니다. 이 검사로 여의교 북단에서 고가 차량이 평면 신호를 받던 오류를 찾아 고쳤습니다.`);

  // 5. HV 교통 · 안정성 ───────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "도로" });
  s.addText("일반 차량 7,200대/h: 멈추지 않고 흐르게", { placeholder: "title" });
  const st = [["80분 시뮬레이션", "수요/h", "텔레포트", "종료 시 잔류", "평균속도"],
              ["교차로 병합 + Webster 신호", "6,546", "255", "342", "17.8 km/h"],
              ["+ 60초 동적 경로 재탐색 · 충돌 차량 제거", "6,546", "28", "0", "26.6 km/h"],
              ["최종: + 보호좌회전 · 교차로 보정 (시드 4개)", "7,200", "28~43", "0~2", "26 km/h"]];
  s.addTable(st.map((r, i) => r.map((c, j) => ({ text: c, options: { bold: i === 0 || i === 3, color: HEX.dk1, fill: { color: i === 3 ? PINK : (i === 0 ? HEX.lt2 : "FFFFFF") }, align: j === 0 ? "left" : "right", fontSize: 14 } }))),
    { x: 0.6, y: 1.5, w: 12.1, colW: [5.3, 1.6, 1.6, 1.8, 1.8], border: { type: "solid", pt: 0.75, color: "E1DDD3" }, rowH: 0.55, margin: 0.08 });
  tx(s, "일반 차량 구성: Krauss 32 · IDM 28 · EIDM 20 · ACC 12 · 버스 5 · 트럭 3 %. 8,000대/h부터 텔레포트가 급증해 7,200대/h를 채택. 남은 HV 충돌(0.6~0.8 %)은 대부분 교차로 내부 저속 접촉.", { x: 0.6, y: 4.0, w: 12.1, h: 0.9, fontSize: 14, color: C.text2, valign: "top" });
  NOTES.push(`[약 40초] 일반 차량은 Krauss, IDM, EIDM, ACC 네 가지 컨트롤러와 버스·트럭을 섞어 시간당 7,200대를 넣었습니다. 처음에는 모든 차가 고정 최단경로로 같은 간선에 몰려 80분에 텔레포트가 255건, 끝날 때 342대가 갇혀 있었습니다. 내비게이션처럼 60초마다 경로를 다시 찾게 하자 텔레포트는 28건, 잔류는 0대로 줄었고 평균속도도 시속 18에서 27 km로 올랐습니다. 이후 보호 좌회전과 교차로 보정을 더해 교통량을 10 % 늘린 상태에서도 시드 4개 모두 비슷하게 안정적이었습니다.`);

  // 6. AV 문제 정의 ───────────────────────────
  pres.addSection({ title: "학습" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "학습" });
  s.addText("AV 문제 정의: 관측 44 · 행동 2 · 보상", { placeholder: "title" });
  [[I.eye, C.accent2, "관측 44차원", "수업 31차원(속도, 5개 차선 앞뒤 차량, 밀도) + 신호 거리·상태·남은 시간, 교차로 우선권, 차선별 경로 지속 거리, 필요 차선 변경, 제한속도, TTC"],
   [I.hand, C.accent1, "행동 2차원", "[가감속, 차선변경 −1·0·+1] — 수업과 동일. 차선변경은 측면 간격·경로 이탈 게이트를 통과할 때만 실행"],
   [I.traffic, C.accent4, "보상", "속도·진행 (+) · 근접·TTC·불필요 정지·급가감속 (−) · 충돌 −10 · 도착 +5 · 교착 −5"]].forEach(([ic, col, h, b], i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.45, 3.85, 4.3, C.background2, `pomdp-${i}`);
    dot(s, x + 0.3, 1.7, 0.6, col, ic, h, `pdot-${i}`);
    tx(s, h, { x: x + 1.05, y: 1.7, w: 2.6, h: 0.6, fontSize: 18, bold: true, color: C.text1, valign: "middle" });
    tx(s, b, { x: x + 0.3, y: 2.55, w: 3.3, h: 3.0, fontSize: 14, color: C.text2, valign: "top" });
  });
  tx(s, "에피소드: 교통이 이미 찬 SUMO 상태(스냅샷 9개)에서 시작 → 7개 경로 중 하나를 목적지까지 (최대 40분, 0.5 s step)", { x: 0.6, y: 6.0, w: 12.1, h: 0.5, fontSize: 13, color: C.text2 });
  NOTES.push(`[약 40초] AV 문제는 수업의 관측 31차원에 도시 주행에 필요한 13차원을 더했습니다. 다음 신호까지의 거리와 상태, 남은 시간, 교차로 우선권, 그리고 차선마다 경로를 계속 갈 수 있는 거리를 넣어서 회전 전에 어느 차선에 있어야 하는지 알 수 있게 했습니다. 행동은 수업과 같은 가감속과 차선변경이고, 보상은 속도와 진행에 더해 근접, 위험, 불필요한 정지를 감점합니다. 매 에피소드는 교통이 이미 찬 상태에서 시작해서 실제 혼잡 속을 달립니다.`);

  // 7. 안전 계층 ─────────────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "학습" });
  s.addText("누가 무엇을 책임지는가", { placeholder: "title" });
  [[I.traffic, C.accent2, "SUMO 법규 계층", "신호 정지 · 교차로 우선권 — 법규는 학습 대상이 아닌 규칙"],
   [I.brain, C.accent1, "학습 정책 (PPO)", "속도 선택 · 추돌 회피(SUMO 안전거리 끔) · 추월 차선변경 · 정체 속 출발 시점"],
   [I.eye, C.text1, "장애물 인식", "교차로에 갇힌 교차 차량을 같은 평면 기하 검사로 찾아 '경로 위 정지 장애물'로 관측"],
   [I.shield, C.text1, "안전 필터 · 오토홀드", `급정거에도 멈출 수 있는 속도로만 제한 (개입 ${pct(E.ppo.shield_rate, 2)}) · 정지 중엔 분명한 출발 명령이 있어야 출발`]].forEach(([ic, col, h, b], i) => {
    const y = 1.45 + i * 1.2;
    card(s, 0.6, y, 12.1, 1.05, C.background2, `layer-${i}`);
    dot(s, 0.85, y + 0.22, 0.6, col, ic, h, `ldot-${i}`);
    tx(s, h, { x: 1.65, y, w: 3.2, h: 1.05, fontSize: 17, bold: true, color: C.text1, valign: "middle" });
    tx(s, b, { x: 4.9, y, w: 7.6, h: 1.05, fontSize: 14, color: C.text2, valign: "middle" });
  });
  tx(s, `필터를 끄고 평가해도 충돌률 ${pct(E.ppo_noshield.collision_rate)} — 기준(≤ 5 %)을 정책 스스로 만족`, { x: 0.6, y: 6.35, w: 12.1, h: 0.45, fontSize: 15, bold: true, color: C.accent1 });
  NOTES.push(`[약 40초] 안전을 누가 책임지는지 계층을 나눴습니다. 신호와 교차로 우선권은 법규라서 SUMO가 지키고, 속도 선택과 추돌 회피, 추월은 정책이 배웁니다. 추돌 회피를 배우게 하려고 SUMO의 안전거리 기능은 껐습니다. 교차로 안에 갇힌 차량은 기하 검사로 찾아 장애물로 관측하고, 안전 필터는 정말 피할 수 없는 상황에서만 개입합니다. 개입률은 ${pct(E.ppo.shield_rate, 2)}이고, 필터를 끄고 평가해도 충돌률 ${pct(E.ppo_noshield.collision_rate)}로 기준을 만족합니다. 즉 필터가 대신 운전하는 구조가 아닙니다.`);

  // 8. 학습 과정 ─────────────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "학습" });
  s.addText("학습: 규칙 교사로 시작해 PPO로 다듬기", { placeholder: "title" });
  ["① 규칙 전문가(IDM+신호) 23.7만 transition으로 수업 PPO 정책 초기화", "② PPO 8.2만 스텝 (필터 ON) → 필터 끄면 충돌 7 %", "③ 필터 OFF 미세조정 + 오토홀드 → 필터 없이 충돌 3 %"].forEach((t, i) => {
    const x = 0.6 + i * 4.1;
    card(s, x, 1.4, 3.85, 1.15, C.background2, `ts-${i}`);
    tx(s, t, { x: x + 0.2, y: 1.4, w: 3.45, h: 1.15, fontSize: 13.5, color: C.text1, valign: "middle" });
  });
  s.addImage({ path: IMG("training_curve.png"), x: 0.6, y: 2.75, w: 12.1, h: 3.39, altText: "PPO 학습 곡선: 학습 리턴, 평가 리턴, 평가 평균속도와 충돌률, 세 학습 단계" });
  NOTES.push(`[약 45초] 무작위 정책으로 시작하면 4~5 km 경로에서 첫 교차로도 넘지 못해 학습 신호가 거의 없습니다. 그래서 규칙 기반 전문가의 주행 데이터로 수업 PPO 정책을 먼저 초기화하고, PPO로 미세조정했습니다. 그런데 안전 필터를 켜고 학습한 정책은 필터를 끄면 충돌이 7 %였습니다. 필터에 기대고 있었던 겁니다. 필터 없이 다시 학습하고, 신호 대기 중 조금씩 밀려 나가는 습관을 오토홀드로 막아서 필터 없이도 3 %가 됐습니다. 그래프의 점선이 이 세 단계 경계입니다.`);

  // 9. 결과 KPI ─────────────────────────────
  pres.addSection({ title: "결과" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "결과" });
  s.addText(`최종 PPO: ${E.ppo.episodes} 에피소드, 7개 경로, 일반 차량 7,200대/h`, { placeholder: "title" });
  const fx = E.ppo_fixed;
  [[pct(E.ppo.collision_rate), "충돌률 (기준 ≤ 5 %)", C.accent1], [pct(E.ppo.success_rate), "목적지 완주율", C.text1],
   [pct(E.ppo.av_fault_rate), "AV 과실 충돌 (나머지는 HV가 추돌)", C.text1],
   [fx ? pct(fx.success_rate) : "–", `설계 경로 고정 시 완주율 (충돌 ${fx ? pct(fx.collision_rate) : "–"}, 경로 일치 ${fx ? pct(fx.route_match_arrived, 1) : "–"})`, C.text1]].forEach(([v, l, col], i) => {
    const x = 0.6 + i * 3.08;
    card(s, x, 1.45, 2.9, 2.4, C.background2, `kpi-${i}`);
    tx(s, v, { x: x + 0.25, y: 1.65, w: 2.5, h: 1.0, fontSize: 44, bold: true, color: col });
    tx(s, l, { x: x + 0.25, y: 2.75, w: 2.5, h: 0.95, fontSize: 13, color: C.text2, valign: "top" });
  });
  tx(s, `평균 통행시간 ${Math.round(E.ppo.mean_travel_time_s)} s (평균 4.3 km) · 평균속도 ${E.ppo.mean_speed_kmh.toFixed(1)} km/h · 시간 초과 ${pct(E.ppo.timeout_rate)} · 교착 ${pct(E.ppo.stuck_rate)}`, { x: 0.6, y: 4.15, w: 12.1, h: 0.45, fontSize: 15, color: C.text2 });
  tx(s, "충돌률은 평가 기준 정의 그대로(충돌로 끝난 에피소드 / 전체), AV가 받힌 경우도 포함한 엄격한 값", { x: 0.6, y: 4.65, w: 12.1, h: 0.45, fontSize: 13, color: C.accent5 });
  const RN = { gyeongin_to_mapo: "경인로→마포대교", daebang_to_seogang: "대방→서강대교", seogang_to_gyeongin: "서강대교→경인로",
               mapo_to_singil: "마포대교→신길로", nodeul_to_dangsan: "노들로→당산", dangsan_to_noryangjin: "당산→노량진",
               olympic_to_singil: "올림픽대로→신길로" };
  tx(s, "경로별 완주율 (기본 / 설계 경로 고정)", { x: 0.6, y: 5.2, w: 6, h: 0.35, fontSize: 13, bold: true, color: C.text1 });
  Object.keys(RN).forEach((k, i) => {
    const x = 0.6 + i * 1.74, a = E.ppo.per_route[k], f = fx ? fx.per_route[k] : null;
    card(s, x, 5.6, 1.62, 1.15, C.background2, `route-${i}`);
    tx(s, RN[k], { x: x + 0.1, y: 5.65, w: 1.45, h: 0.45, fontSize: 10.5, bold: true, color: C.text1, valign: "middle" });
    tx(s, `${pct(a.success_rate)} / ${f ? pct(f.success_rate) : "–"}`, { x: x + 0.1, y: 6.1, w: 1.45, h: 0.55, fontSize: 14, color: a.success_rate < 1 ? C.accent1 : C.text2, valign: "middle" });
  });
  NOTES.push(`[약 45초] 최종 PPO의 결과입니다. ${E.ppo.episodes} 에피소드를 7개 경로에 고르게 돌렸고, 충돌률 ${pct(E.ppo.collision_rate)}, 목적지 완주율 ${pct(E.ppo.success_rate)}입니다. 충돌률은 AV가 받힌 경우까지 센 엄격한 값이고, AV 과실만 보면 ${pct(E.ppo.av_fault_rate)}입니다. 평가 기준의 '잘못된 경로로 빠지지 않는가'를 확인하려고, 내비게이션식 재탐색을 끄고 설계한 경로 그대로 달리게 한 평가도 했고, 완주율은 ${fx ? pct(fx.success_rate) : "–"}, 충돌률은 ${fx ? pct(fx.collision_rate) : "–"}입니다.`);

  // 10. 정책 비교 ─────────────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "결과" });
  s.addText("정책 비교 (각 100 에피소드, 같은 교통 조건)", { placeholder: "title" });
  const comp = [["정책", "충돌률", "완주율", "통행시간", "평균속도"]];
  [["PPO 최종 (필터 ON)", E.ppo], ["PPO 최종 (필터 OFF)", E.ppo_noshield], ["PPO, 설계 경로 고정", E.ppo_fixed],
   ["BC (PPO 데이터 모방)", E.bc], ["TD3+BC (오프라인 RL)", E.td3bc], ["규칙 전문가 (교사)", E.expert]].forEach(([n, e]) => {
    if (e) comp.push([n, pct(e.collision_rate), pct(e.success_rate), Math.round(e.mean_travel_time_s) + " s", e.mean_speed_kmh.toFixed(1) + " km/h"]);
  });
  s.addTable(comp.map((r, i) => r.map((c, j) => ({ text: c, options: { bold: i === 0 || i === 1, color: HEX.dk1, fill: { color: i === 1 ? PINK : (i === 0 ? HEX.lt2 : "FFFFFF") }, align: j === 0 ? "left" : "right", fontSize: 14 } }))),
    { x: 0.6, y: 1.45, w: 12.1, colW: [4.9, 1.8, 1.8, 1.8, 1.8], border: { type: "solid", pt: 0.75, color: "E1DDD3" }, rowH: 0.5, margin: 0.08 });
  tx(s, "100 에피소드에서 0~3건 차이는 통계적으로 크지 않음 (3/100의 95 % 구간 ≈ 0.6~8.5 %). TD3+BC는 수집 데이터만으로 학습(환경 상호작용 없음).", { x: 0.6, y: 5.3, w: 12.1, h: 0.7, fontSize: 13, color: C.text2, valign: "top" });
  NOTES.push(`[약 40초] 같은 교통 조건에서 정책을 비교했습니다. 필터를 켜도 꺼도 PPO는 기준을 만족합니다. 수업 흐름대로 PPO가 모은 데이터를 모방한 BC, 그리고 추가로 수집 데이터만으로 학습한 오프라인 강화학습 TD3+BC도 평가했습니다. 규칙 기반 전문가가 이 환경에서 강한 기준선이라는 점도 그대로 보여드립니다. 다만 100 에피소드에서 0건과 3건의 차이는 통계적으로 크지 않습니다.`);

  // 11. 상호작용 정량 ──────────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "결과" });
  s.addText("상호작용은 실제로 얼마나 일어나는가", { placeholder: "title" });
  s.addImage({ path: IMG("interaction_counts.png"), x: 0.6, y: 1.4, w: 7.4, h: 3.31, altText: "에피소드당 상호작용 이벤트 수" });
  [[String(IN.vehicles_within_50m.mean) + "대", "반경 50 m 안 평균 차량 (상위 10 %: " + IN.vehicles_within_50m.p90 + "대)"],
   [String(IN.vehicles_within_150m.mean) + "대", "반경 150 m 안 평균 차량"],
   [IN.ttc_lt4_pct_of_time + " %", "앞 장애물 TTC < 4 s 인 시간"]].forEach(([v, l], i) => {
    const y = 1.4 + i * 1.12;
    card(s, 8.4, y, 4.3, 1.0, C.background2, `int-${i}`);
    tx(s, v, { x: 8.6, y: y + 0.05, w: 1.8, h: 0.9, fontSize: 24, bold: true, color: C.text1, valign: "middle" });
    tx(s, l, { x: 10.35, y: y + 0.05, w: 2.25, h: 0.9, fontSize: 12, color: C.text2, valign: "middle" });
  });
  tx(s, `에피소드당 교차로 ${M["교차로 통과"]}회 통과 · 신호 정지 ${M["신호 정지"]}회 · 차선변경 ${(M["차선변경 (경로 유지)"] + M["차선변경 (정책 재량)"]).toFixed(1)}회. 주변 차량 구성: Krauss 33 · IDM 25 · EIDM 21 · ACC 12 · 버스 6 · 트럭 3 %`, { x: 0.6, y: 4.95, w: 12.1, h: 0.8, fontSize: 13, color: C.text2, valign: "top" });
  NOTES.push(`[약 40초] 상호작용이 실제로 얼마나 일어나는지 데이터에서 셌습니다. 한 에피소드에 교차로를 약 ${Math.round(M["교차로 통과"])}번 지나고, 신호에 ${M["신호 정지"]}번 멈추고, 차선을 ${(M["차선변경 (경로 유지)"] + M["차선변경 (정책 재량)"]).toFixed(1)}번 바꿉니다. AV 주변 50 m 안에는 평균 ${IN.vehicles_within_50m.mean}대, 붐비는 구간에서는 ${IN.vehicles_within_50m.p90}대가 있고, 네 종류 컨트롤러와 버스·트럭을 고루 만납니다. 다만 올림픽대로처럼 한산한 구간도 있어서 이 점은 한계로 적었습니다.`);

  // 12. 주행 영상 ─────────────────────────────
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "결과" });
  s.addText("주행 영상: 서쪽 끝 경인로 → 영등포 로터리 → 여의도 한 바퀴", { placeholder: "title" });
  s.addMedia({ type: "video", path: path.join(ROOT, "assets", "video", "yeouido_tour_ppo.mp4"), cover: "data:image/jpeg;base64," + fs.readFileSync(path.join(DIR, "img", "tour_cover.jpg")).toString("base64"), x: 0.7, y: 1.55, w: 8.53, h: 4.8 });
  s.addImage({ path: IMG("tour_map.jpg"), x: 9.5, y: 1.55, w: 3.2, h: 2.26, altText: "투어 경로 지도" });
  tx(s, "8.3 km · 신호 20곳 · 실제 20.7분 → 43초 · 결과: 목적지 도착 · 빨간 차 = AV (sumo-gui 실제 화면)", { x: 9.5, y: 4.0, w: 3.2, h: 2.3, fontSize: 13, color: "C9D3E3", valign: "top" });
  NOTES.push(`[약 60초, 영상 재생] 실제 주행 영상입니다. 영역 맨 서쪽 경인로에서 출발해 영등포역과 영등포 로터리를 지나 서울교로 여의도에 들어가고, 여의서로와 여의동로를 한 바퀴 돕니다. 8.3 km, 신호 20곳이고 실제 20분 42초를 43초로 줄였습니다. 빨간 차가 AV이고, 신호 대기열에서 멈췄다 출발하고, 교량 진입에서 합류하는 장면을 볼 수 있습니다. 다른 경로 영상 두 편은 프로젝트 페이지에 있습니다.`);

  // 13. 데이터셋 ─────────────────────────────
  pres.addSection({ title: "데이터" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "데이터" });
  s.addText("주행 데이터셋", { placeholder: "title" });
  card(s, 0.6, 1.45, 4.6, 4.6, C.text1, "data-hero");
  tx(s, (DT.total / 1e6).toFixed(2) + "M", { x: 0.85, y: 1.75, w: 4.1, h: 1.2, fontSize: 54, bold: true, color: C.background1 });
  tx(s, "transition 합계", { x: 0.85, y: 2.95, w: 4.1, h: 0.4, fontSize: 15, color: "C9D3E3" });
  tx(s, [{ text: `PPO 전체 컬럼(JSONL) ${num(123356)}`, options: { breakLine: true } },
         { text: `PPO 학습용(NPZ) ${num(DT.ppo_total - 123356)}`, options: { breakLine: true } },
         { text: `전문가(초기화용) ${num(DT.expert)}` }], { x: 0.85, y: 3.55, w: 4.1, h: 1.4, fontSize: 13, color: "C9D3E3", valign: "top", paraSpaceAfter: 4 });
  tx(s, (DT.ppo_total >= 1e7 ? `PPO 정책 데이터 ${(DT.ppo_total / 1e6).toFixed(2)}M → 10⁷ 달성. ` : "") + "다중 AV 수집: 시뮬레이션 하나에 AV 12대 → SUMO 비용을 나눠 약 2배 빠르게", { x: 0.85, y: 5.0, w: 4.1, h: 0.9, fontSize: 12, color: "FF8A99", valign: "top" });
  [[I.db, C.accent2, "수업 필수", "episode · t · observation(44) · action_raw · lane_change · reward · terminated · truncated · next_observation · detected_vehicles"],
   [I.pin, C.accent1, "State 절대 정보", "AV 위치(m)·경위도·속도·가속도·방향·차선·도로명·제한속도·경로 진행·다음 신호, 반경 150 m 차량"],
   [I.plus, C.accent4, "도시 확장", "route · 충돌/도착/교착 · 안전필터 개입 · 진행률 · 다중 AV 수(n_av)"]].forEach(([ic, col, h, b], i) => {
    const y = 1.45 + i * 1.55;
    card(s, 5.5, y, 7.2, 1.4, C.background2, `dc-${i}`);
    dot(s, 5.75, y + 0.38, 0.6, col, ic, h, `dd-${i}`);
    tx(s, h, { x: 6.55, y: y + 0.1, w: 5.9, h: 0.4, fontSize: 15, bold: true, color: C.text1 });
    tx(s, b, { x: 6.55, y: y + 0.5, w: 5.95, h: 0.85, fontSize: 12, color: C.text2, valign: "top" });
  });
  NOTES.push(`[약 45초] 데이터는 수업 수집 코드의 필수 항목을 그대로 두고, 절대 정보 State와 도시망 항목을 더했습니다. 각 항목의 의미, 단위, 왜 필요한지는 데이터 컬럼 사전 문서에 정리했습니다. 규모는 총 ${(DT.total / 1e6).toFixed(2)}백만 transition이고, 그중 최종 PPO 정책이 만든 데이터가 ${(DT.ppo_total / 1e6).toFixed(2)}백만으로 ${DT.ppo_total >= 1e7 ? "목표였던 10의 7승을 넘었습니다" : "목표 10의 7승에 근접했습니다"}. AV 한 대 환경은 시간의 75 %가 SUMO 계산이라 느려서, 시뮬레이션 하나에 AV 12대를 함께 넣어 비용을 나누는 수집기를 만들었고, AV끼리는 먼저 들어온 차에 우선권을 주는 규칙으로 서로 막히거나 부딪히지 않게 했습니다. 이 데이터의 에피소드 충돌률은 ${pct(DT.multi_collision_rate, 1)}입니다. 모든 데이터는 저장소에 올렸고 HuggingFace 업로드 스크립트도 준비했습니다.`);

  // 14. 문제와 해결 ───────────────────────────
  pres.addSection({ title: "정리" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "정리" });
  s.addText("부딪힌 문제와 해결", { placeholder: "title" });
  const pr = [["문제", "원인", "해결 → 효과"],
              ["간선 과포화", "고정 최단경로에 모든 차가 몰림", "60초 동적 재경로 → 텔레포트 255→28"],
              ["고가 차량이 신호를 받음", "반경 병합이 고가 램프 합류점까지 포함", "층 검사로 제외 → 해당 교차로 충돌 7→2"],
              ["AV가 교차로 안 차량과 충돌", "SUMO 교차로 감속이 안전거리 비트에 묶임", "같은 평면 기하 검사로 장애물 인식"],
              ["PPO가 안전 필터에 의존", "필터 켠 채 학습", "필터 OFF 미세조정 → 7 %→3 %"],
              ["신호 대기 중 미세 전진 추돌", "정지 시 평균 출력이 0보다 약간 큼", "오토홀드 → 필터 OFF 충돌 10 %→1~3 %"],
              ["AV가 설계 경로를 벗어남", "HV용 동적 재경로가 AV에도 적용", "경로 고정 AV 타입 + 경로 일치율 평가"]];
  s.addTable(pr.map((r, i) => r.map((c, j) => ({ text: c, options: { bold: i === 0 || j === 0, color: HEX.dk1, fill: { color: i === 0 ? HEX.lt2 : "FFFFFF" }, fontSize: 13 } }))),
    { x: 0.6, y: 1.4, w: 12.1, colW: [3.3, 4.3, 4.5], border: { type: "solid", pt: 0.75, color: "E1DDD3" }, rowH: 0.62, margin: 0.08 });
  NOTES.push(`[약 60초] 문제를 해결한 과정입니다. 모두 측정하고, 원인을 찾고, 고친 뒤 다시 측정했습니다. 동적 재경로로 과포화를 풀었고, 고가 위 노드가 평면 교차로에 섞인 오류를 층 검사로 찾았습니다. AV가 교차로 안에 갇힌 차량과 부딪히는 문제는 SUMO의 교차로 감속이 안전거리 기능에 묶여 있어서였고, 기하 검사로 장애물을 인식하게 했습니다. PPO가 안전 필터에 기대는 문제는 필터 없이 다시 학습해서, 신호 대기 중 미세 전진 추돌은 오토홀드로 해결했습니다. 마지막으로 AV에도 동적 재경로가 걸려 설계 경로를 벗어날 수 있다는 점을 찾아, 경로를 고정한 평가를 따로 했습니다.`);

  // 15. 실패 분석 ─────────────────────────────
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "정리" });
  s.addText("남은 실패는 어디서, 왜 일어나는가", { placeholder: "title" });
  s.addImage({ path: IMG("stop_map.jpg"), x: 0.6, y: 1.4, w: 6.9, h: 4.89, altText: "AV 정지 위치와 원인 지도" });
  [["교차로 내부", "최종 평가의 충돌은 모두 교차로 안. 직선 추돌·차선변경 측면 충돌 0건"],
   ["피추돌이 다수", "일반 차량이 AV를 들이받은 경우가 과반 — HV끼리도 80분에 41~59건 나는 SUMO 교차로 모델 현상"],
   ["교착 = 실제 정체", "영등포 로터리·서울교 북단 신호 대기열(28~80대)이 원인. AV는 대기열 중간에서 기다린 것"]].forEach(([h, b], i) => {
    const y = 1.4 + i * 1.65;
    card(s, 7.8, y, 4.9, 1.5, C.background2, `fa-${i}`);
    tx(s, h, { x: 8.05, y: y + 0.12, w: 4.4, h: 0.4, fontSize: 16, bold: true, color: C.text1 });
    tx(s, b, { x: 8.05, y: y + 0.55, w: 4.45, h: 0.9, fontSize: 12.5, color: C.text2, valign: "top" });
  });
  NOTES.push(`[약 40초] 남은 실패도 분석했습니다. 왼쪽은 AV가 멈춘 위치와 원인을 지도에 찍은 것입니다. 충돌은 모두 교차로 안에서 났고, 직선 구간 추돌이나 차선변경 측면 충돌은 한 건도 없었습니다. 충돌의 과반은 일반 차량이 AV를 들이받은 경우로, 일반 차량끼리도 생기는 SUMO 교차로 모델의 현상입니다. 교착은 대기열 맨 앞 차를 추적해 보니 영등포 로터리와 서울교 북단 신호의 실제 정체였습니다.`);

  // 16. 결론 ─────────────────────────────────
  s = pres.addSlide({ masterName: "SECTION_DARK", sectionTitle: "정리" });
  s.addText("정리와 남은 과제", { placeholder: "title" });
  tx(s, `실제 서울 도시망에서, 일반 차량 7,200대/h 사이를, 안전 필터 없이도 충돌 ${pct(E.ppo_noshield.collision_rate)}로 목적지까지.`, { x: 0.7, y: 1.8, w: 11.6, h: 1.5, fontSize: 30, bold: true, color: C.background1, valign: "top" });
  [["남은 과제", "회전 제한 반영(OSM 재수집) · 차로 수 미표기 간선 로드뷰 보정 · 교차로 피추돌 감소(상충 차량 TTC 관측)"],
   ["결과물", "코드 · 모델 · 데이터: github.com/hosup0902/AI_sapiens-team-project (ydp-yeouido/) · 데이터: [HuggingFace 링크] · 프로젝트 페이지: [링크]"]].forEach(([h, b], i) => {
    const x = 0.7 + i * 6.0;
    card(s, x, 3.9, 5.7, 2.3, C.accent6, `end-${i}`);
    tx(s, h, { x: x + 0.3, y: 4.1, w: 5.1, h: 0.45, fontSize: 17, bold: true, color: "FF8A99" });
    tx(s, b, { x: x + 0.3, y: 4.6, w: 5.1, h: 1.45, fontSize: 13, color: "C9D3E3", valign: "top" });
  });
  NOTES.push(`[약 30초] 정리하면, 실제 서울 도시망에서 시간당 7,200대 사이를 안전 필터 없이도 충돌 ${pct(E.ppo_noshield.collision_rate)}로 목적지까지 달리는 AV를 만들었습니다. 남은 과제는 회전 제한 반영, 차로 수 보정, 교차로 피추돌 감소입니다. 코드, 모델, 데이터는 모두 저장소와 프로젝트 페이지에 있습니다. 감사합니다.`);

  (pres.slides || pres._slides).forEach((sl, i) => sl.addNotes(NOTES[i] || ""));
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  fs.writeFileSync(path.join(DIR, "notes.json"), JSON.stringify(NOTES, null, 1));
  console.log("saved", OUT, "slides", pres.slides.length);
})();
