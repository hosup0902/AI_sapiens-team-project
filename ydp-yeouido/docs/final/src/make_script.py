"""최종발표 pptx의 슬라이드 제목 + 노트 → 대본 마크다운.

    python docs/final/src/make_script.py docs/final/최종발표_AI_sapiens.pptx docs/final/최종발표_대본.md
"""
import re
import sys

from pptx import Presentation


def main(src, dst):
    prs = Presentation(src)
    out = ["# 최종발표 대본", "",
           "`최종발표_AI_sapiens.pptx` 슬라이드 노트와 같은 내용이에요. 괄호 안 시간은 목표 길이예요. "
           "수치는 `src/summary.json`(평가·데이터 결과)에서 자동으로 채워져요.", "",
           "- 발표 전 확인: 1번 슬라이드의 팀원 이름·역할을 실제 이름으로 바꿔 주세요.",
           "- 12번 슬라이드 영상은 클릭하면 재생돼요 (`assets/video/yeouido_tour_ppo.mp4`).",
           "- 다시 만들기: `python docs/final/src/make_summary.py` → `node docs/final/src/build.js <out.pptx>` → 이 스크립트.", ""]
    total = 0
    for i, sl in enumerate(prs.slides, 1):
        title = ""
        for sh in sl.shapes:
            if sh.is_placeholder and sh.placeholder_format.type is not None and "TITLE" in str(sh.placeholder_format.type):
                title = sh.text_frame.text.strip()
                break
        if not title:
            texts = [sh.text_frame.text.strip() for sh in sl.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            title = texts[0].split("\n")[0] if texts else f"슬라이드 {i}"
        note = sl.notes_slide.notes_text_frame.text.strip() if sl.has_notes_slide else ""
        m = re.search(r"약 (\d+)초", note)
        total += int(m.group(1)) if m else 0
        out += [f"## {i}. {title}", "", note, ""]
    out[2] += f" 합계 목표 약 {total // 60}분 {total % 60}초."
    open(dst, "w", encoding="utf-8").write("\n".join(out))
    print("저장:", dst, f"({len(prs.slides)} 슬라이드, {total}초)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
