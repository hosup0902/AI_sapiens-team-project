"""프로젝트 페이지(docs/) 조립 — 평가 결과·그림·영상을 모아 docs/results.json 과 index.html 에 반영.

    python tools/build_site.py --main results/final/eval_ppo.json \
        --policies "PPO (최종)=results/final/eval_ppo.json" "BC=results/final/eval_bc.json" \
                   "전문가(IDM 규칙)=results/final/eval_expert.json" \
        --videos assets/video/*.mp4 --hf https://huggingface.co/datasets/<id> --slides <pdf 링크>

GitHub Pages: 저장소 Settings → Pages 에서 이 폴더를 게시하거나, docs/ 내용을 gh-pages 브랜치에 올린다.
"""
import argparse
import glob
import json
import os
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, "docs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", required=True)
    ap.add_argument("--policies", nargs="+", required=True, help='"표시이름=eval.json"')
    ap.add_argument("--videos", nargs="*", default=[])
    ap.add_argument("--hf", default=None)
    ap.add_argument("--slides", default="https://github.com/hosup0902/AI_sapiens-team-project/blob/main/ydp-yeouido/docs/final/"
                    "%EC%B5%9C%EC%A2%85%EB%B0%9C%ED%91%9C_AI_sapiens.pdf",
                    help="발표자료 PDF 링크 (기본: 저장소의 docs/final/최종발표_AI_sapiens.pdf, 구글 드라이브 링크로 바꿔도 됨)")
    ap.add_argument("--train-html", default="")
    ap.add_argument("--data-html", default="")
    a = ap.parse_args()

    os.makedirs(os.path.join(DOCS, "img"), exist_ok=True)
    os.makedirs(os.path.join(DOCS, "video"), exist_ok=True)
    for f in ("map_full.png", "av_routes.png", "zoom_rotary.png"):
        src = os.path.join(BASE, "assets", "figures", f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DOCS, "img", f))
    videos = []
    for pat in a.videos:
        for v in sorted(glob.glob(pat)):
            dst = os.path.join(DOCS, "video", os.path.basename(v))
            shutil.copy(v, dst)
            name = os.path.splitext(os.path.basename(v))[0]
            videos.append({"src": f"video/{os.path.basename(v)}",
                           "caption": f"{name} — 빨간 차가 AV. sumo-gui 실제 시뮬레이션 화면 (2 step/프레임)"})

    main_eval = json.load(open(a.main, encoding="utf-8"))
    pols = []
    for item in a.policies:
        name, path = item.split("=", 1)
        s = json.load(open(path, encoding="utf-8"))["summary"]
        pols.append({"name": name, **s})
    out = {
        "main": {"name": a.policies[0].split("=", 1)[0], **main_eval["summary"]},
        "per_route": main_eval["per_route"],
        "policies": pols,
        "videos": videos,
        "links": {"hf": a.hf, "slides": a.slides},
        "train_html": a.train_html,
        "data_html": a.data_html,
    }
    with open(os.path.join(DOCS, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    # file:// 로 열어도 보이도록 HTML 안에도 넣는다
    html_path = os.path.join(DOCS, "index.html")
    html = open(html_path, encoding="utf-8").read()
    start = html.find('<script id="results-data"')
    if start >= 0:
        end = html.find("</script>", start) + len("</script>")
        html = html[:start] + html[end:]
    blob = json.dumps(out, ensure_ascii=False).replace("</", "<\\/")
    tag = f'<script id="results-data" type="application/json">{blob}</script>\n'
    html = html.replace("<script>\n// 결과 값은", tag + "<script>\n// 결과 값은", 1)
    html = html.replace('fetch("results.json").then(r => r.ok ? r.json() : null)',
                        'Promise.resolve(JSON.parse(document.getElementById("results-data").textContent))')
    open(html_path, "w", encoding="utf-8").write(html)
    print(f"페이지 갱신: {html_path} (정책 {len(pols)}개, 영상 {len(videos)}개)")


if __name__ == "__main__":
    main()
