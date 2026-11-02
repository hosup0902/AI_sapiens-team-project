const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
let applyTheme = async () => {};  // 테마 색 적용 도구(선택). 없으면 pptxgenjs 기본 테마 색으로 저장
try { ({ applyTheme } = require(process.env.APPLY_THEME || "./apply_theme.js")); } catch (e) { /* optional */ }

const DIR = __dirname;
const OUT = process.argv[2] || path.join(DIR, "midterm.pptx");
const SCRIPT = JSON.parse(fs.readFileSync(path.join(DIR, "script.json"), "utf8"));

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

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
  pres.title = "영등포–여의도 자율주행 중간발표";
  pres.author = "AI_sapiens";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  // ── layouts ──
  pres.defineSlideMaster({
    title: "TITLE_DARK",
    background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 1.55, w: 6.6, h: 1.9, fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.6, w: 6.4, h: 1.3, fontSize: 18, color: "C9D3E3", valign: "top", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: C.background1 },
    margin: [0.4, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 30, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
      { text: { text: "AI_sapiens · 중간발표 · 영등포–여의도 실도로 SUMO 자율주행", options: { x: 0.6, y: 7.0, w: 9, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: HEX.accent5, align: "right" },
  });

  const I = {
    user: await icon(fa.FaUserCircle, "FFFFFF"),
    rotary: await icon(fa.FaSyncAlt, "FFFFFF"),
    bridge: await icon(fa.FaArchway, "FFFFFF"),
    ramp: await icon(fa.FaRoad, "FFFFFF"),
    layer: await icon(fa.FaLayerGroup, "FFFFFF"),
    grid: await icon(fa.FaThLarge, "FFFFFF"),
    arrow: await icon(fa.FaArrowRight, HEX.accent5),
    db: await icon(fa.FaDatabase, "FFFFFF"),
    pin: await icon(fa.FaMapMarkerAlt, "FFFFFF"),
    plus: await icon(fa.FaPlusCircle, "FFFFFF"),
  };
  const img = (n) => path.join(DIR, n);

  // ════════ 1. 표지 + 팀 ════════
  pres.addSection({ title: "팀" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "팀" });
  s.addText("영등포 로터리부터 여의도까지", { placeholder: "title" });
  s.addText([
    { text: "실제 서울 도시망 위 자율주행 의사결정", options: { breakLine: true } },
    { text: "자율주행 인공지능 및 제어 · 중간발표", options: { color: "FF8A99", fontSize: 16 } },
  ], { placeholder: "body" });
  s.addText("팀 AI_sapiens", { x: 0.7, y: 5.7, w: 4, h: 0.5, fontSize: 20, bold: true, color: C.background1, margin: 0, isTextBox: true, objectName: "team-name" });
  const roles = [
    ["[팀원 A]", "SUMO 도로 환경 구축"],
    ["[팀원 B]", "일반 차량 · 신호 · 안정성"],
    ["[팀원 C]", "AV POMDP · 학습 · 평가"],
    ["[팀원 D]", "데이터셋 · 영상 · 페이지"],
  ];
  roles.forEach(([name, role], i) => {
    const x = 7.75 + (i % 2) * 2.65, y = 1.55 + Math.floor(i / 2) * 2.05;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.45, h: 1.85, fill: { color: C.accent6 }, rectRadius: 0.12, line: { color: C.accent6 }, objectName: `role-card-${i + 1}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.25, w: 0.55, h: 0.55, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `role-dot-${i + 1}` });
    s.addImage({ data: I.user, x: x + 0.36, y: y + 0.36, w: 0.33, h: 0.33, altText: "팀원" });
    s.addText(name, { x: x + 0.25, y: y + 0.88, w: 2.0, h: 0.4, fontSize: 16, bold: true, color: C.background1, margin: 0, isTextBox: true });
    s.addText(role, { x: x + 0.25, y: y + 1.28, w: 2.05, h: 0.45, fontSize: 13, color: "C9D3E3", margin: 0, isTextBox: true, valign: "top" });
  });
  s.addText("역할 분담", { x: 7.75, y: 1.0, w: 3, h: 0.4, fontSize: 14, bold: true, color: "FF8A99", margin: 0, isTextBox: true });
  s.addNotes(SCRIPT[0]);

  // ════════ 2. 선정 지역 ════════
  pres.addSection({ title: "지역과 구조" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "지역과 구조" });
  s.addText("선정 지역: 서울 영등포·당산·여의도 4.8 × 3.4 km", { placeholder: "title" });
  s.addImage({ path: img("map_full.jpg"), x: 0.6, y: 1.4, w: 7.6, h: 5.37, altText: "SUMO로 구현한 영등포~여의도 도로망 전체. 건물, 한강, 신호교차로 표시" });
  s.addText("SUMO 구현 화면 · 빨간 점 = 신호교차로 · 도로·건물 © OpenStreetMap", { x: 0.6, y: 6.62, w: 7.6, h: 0.3, fontSize: 10, color: C.accent5, margin: 0, isTextBox: true });
  const stats = [["107", "신호교차로"], ["519 km", "차로 총연장 (도로 4,422구간)"], ["2,187", "건물 · 한강 · 여의도공원"], ["7개", "AV 실제 출퇴근 경로 (3.5~4.9 km)"]];
  stats.forEach(([v, l], i) => {
    const y = 1.4 + i * 1.33;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.6, y, w: 4.1, h: 1.18, fill: { color: C.background2 }, line: { color: C.background2 }, rectRadius: 0.1, objectName: `stat-${i + 1}` });
    s.addText(v, { x: 8.85, y: y + 0.1, w: 3.7, h: 0.6, fontSize: 30, bold: true, color: i === 3 ? C.accent1 : C.text1, margin: 0, isTextBox: true });
    s.addText(l, { x: 8.85, y: y + 0.7, w: 3.7, h: 0.38, fontSize: 13, color: C.text2, margin: 0, isTextBox: true });
  });
  s.addNotes(SCRIPT[1]);

  // ════════ 3. 구조적 특징 ════════
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "지역과 구조" });
  s.addText("구조적 특징과 SUMO 구현", { placeholder: "title" });
  s.addImage({ path: img("zoom_rotary.jpg"), x: 0.6, y: 1.4, w: 4.75, h: 4.75, altText: "영등포 로터리 일대 확대: 11개 교차점을 하나로 병합한 대형 신호교차로" });
  s.addText("영등포 로터리 (OSM 11개 점 → 신호교차로 1개)", { x: 0.6, y: 6.2, w: 4.75, h: 0.35, fontSize: 11, color: C.accent5, margin: 0, isTextBox: true });
  const feats = [
    [I.rotary, "로터리 → 평면 신호교차로", "영등포 로터리 — 다방향 진입·진출"],
    [I.bridge, "교량 진입·진출", "서울교 · 여의교 · 마포대교 · 서강대교"],
    [I.ramp, "도시고속도로 램프", "올림픽대로 80 km/h · 노들로 합류·분기"],
    [I.layer, "입체 교차", "여의대방로 고가 · 지하차도 3곳"],
    [I.grid, "다차로 간선 + 이면 격자", "여의대로 · 경인로 · 국회대로"],
  ];
  feats.forEach(([ic, h, d], i) => {
    const y = 1.4 + i * 0.86;
    s.addShape(pres.shapes.OVAL, { x: 5.8, y: y + 0.08, w: 0.56, h: 0.56, fill: { color: i === 0 ? C.accent1 : C.accent2 }, line: { color: i === 0 ? C.accent1 : C.accent2 }, objectName: `feat-dot-${i + 1}` });
    s.addImage({ data: ic, x: 5.93, y: y + 0.21, w: 0.3, h: 0.3, altText: h });
    s.addText(h, { x: 6.6, y, w: 6.1, h: 0.38, fontSize: 16, bold: true, color: C.text1, margin: 0, isTextBox: true });
    s.addText(d, { x: 6.6, y: y + 0.38, w: 6.1, h: 0.35, fontSize: 13, color: C.text2, margin: 0, isTextBox: true });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.8, y: 5.85, w: 6.9, h: 0.95, fill: { color: C.background2 }, line: { color: C.background2 }, rectRadius: 0.08, objectName: "impl-box" });
  s.addText([
    { text: "구현: ", options: { bold: true, color: C.text1 } },
    { text: "OSM → netconvert 2단계, 쪼개진 교차로 병합, 국내 제한속도·차로폭, Webster 신호. OSM 대비 도로 포함 97.8 %, 선형 오차 중앙값 0.01 m", options: { color: C.text2 } },
  ], { x: 6.0, y: 5.92, w: 6.55, h: 0.82, fontSize: 12, margin: 0, isTextBox: true, valign: "middle" });
  s.addNotes(SCRIPT[2]);

  // ════════ 4. 상호작용 → 의사결정 ════════
  pres.addSection({ title: "AV 문제" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "AV 문제" });
  s.addText("왜 흥미로운가: 구조 → 차량 상호작용 → AV 의사결정", { placeholder: "title" });
  const cols = [[0.6, 3.4, "도로 구조"], [4.55, 3.9, "차량 상호작용"], [9.0, 3.7, "AV가 해야 할 판단"]];
  cols.forEach(([x, w, h], i) => s.addText(h, { x, y: 1.35, w, h: 0.4, fontSize: 14, bold: true, color: i === 2 ? C.accent1 : C.accent2, margin: 0, isTextBox: true }));
  const rows = [
    ["영등포 로터리", "여러 방향 진입 차량과 교차로 안 상충", "진입 시점·속도 조절, 출구 차로 선택"],
    ["교량 끝 신호교차로", "교량 차량 합류·분기, 신호 대기열", "회전 전 차로 확보, 대기열 정지·출발"],
    ["올림픽대로·노들로 램프", "80 km/h 본선과 합류·진출", "감속·가속, 합류 간격 판단"],
    ["다차로 간선", "느린 버스·트럭, 옆 차로 차량", "안전 간격 확인 후 추월 차선변경"],
  ];
  rows.forEach((r, i) => {
    const y = 1.85 + i * 1.12;
    cols.forEach(([x, w], j) => {
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.92, fill: { color: j === 2 ? "FCE8EB" : C.background2 }, line: { color: j === 2 ? "FCE8EB" : C.background2 }, rectRadius: 0.08, objectName: `cell-${i + 1}-${j + 1}` });
      s.addText(r[j], { x: x + 0.2, y, w: w - 0.4, h: 0.92, fontSize: j === 0 ? 15 : 14, bold: j === 0, color: C.text1, margin: 0, isTextBox: true, valign: "middle" });
    });
    s.addImage({ data: I.arrow, x: 4.12, y: y + 0.33, w: 0.26, h: 0.26, altText: "" });
    s.addImage({ data: I.arrow, x: 8.57, y: y + 0.33, w: 0.26, h: 0.26, altText: "" });
  });
  s.addText("배경 교통: 일반 차량 7,200대/h · Krauss / IDM / EIDM / ACC + 버스·트럭 혼합 · 60초 동적 경로 재탐색", { x: 0.6, y: 6.4, w: 12.1, h: 0.4, fontSize: 13, color: C.text2, margin: 0, isTextBox: true });
  s.addNotes(SCRIPT[3]);

  // ════════ 5. 데이터 컬럼 ════════
  pres.addSection({ title: "데이터" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "데이터" });
  s.addText("수집 데이터 컬럼", { placeholder: "title" });
  const cards = [
    [I.db, C.accent2, "수업 기본 (POMDP transition)", ["episode, t", "observation (44차원)", "action_raw [가감속, 차선]", "lane_change (−1·0·+1)", "reward", "terminated / truncated", "next_observation", "detected_vehicles"]],
    [I.pin, C.accent1, "State — 절대 정보 (필수)", ["ego x, y, 위도·경도", "속도 · 가속도 · 방향각", "차선 · 도로명 · 제한속도", "경로 진행 거리 / 전체 길이", "다음 신호 id · 거리 · 상태", "반경 150 m 주변 차량 (위치·속도·타입)"]],
    [I.plus, C.accent4, "도시망 확장", ["route (7개 OD 중 무엇)", "event: 충돌 · 도착 · 교착", "event: 안전 필터 개입 · 진행률", "관측: 신호 · 교차로 우선권", "관측: 차선별 경로 지속 거리 · TTC"]],
  ];
  cards.forEach(([ic, col, h, items], i) => {
    const x = 0.6 + i * 4.1, w = 3.85;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.4, w, h: 4.4, fill: { color: i === 1 ? "FCE8EB" : C.background2 }, line: { color: i === 1 ? "FCE8EB" : C.background2 }, rectRadius: 0.1, objectName: `data-card-${i + 1}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: 1.65, w: 0.56, h: 0.56, fill: { color: col }, line: { color: col }, objectName: `data-dot-${i + 1}` });
    s.addImage({ data: ic, x: x + 0.43, y: 1.78, w: 0.3, h: 0.3, altText: h });
    s.addText(h, { x: x + 1.0, y: 1.6, w: w - 1.15, h: 0.66, fontSize: 15, bold: true, color: C.text1, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(items.map((t, k) => ({ text: t, options: { bullet: true, breakLine: k < items.length - 1 } })),
      { x: x + 0.25, y: 2.45, w: w - 0.45, h: 3.2, fontSize: 15, color: C.text2, margin: 0, isTextBox: true, valign: "top", paraSpaceAfter: 6 });
  });
  s.addText("저장 형식: JSONL.gz (transition 전체 + privileged state) + NPZ (학습용 배열) → HuggingFace 업로드", { x: 0.6, y: 6.05, w: 12.1, h: 0.4, fontSize: 13, color: C.text2, margin: 0, isTextBox: true });
  s.addNotes(SCRIPT[4]);

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("saved", OUT);
})();
