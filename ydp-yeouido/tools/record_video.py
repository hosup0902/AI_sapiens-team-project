"""AV 주행 영상 녹화 (sumo-gui 화면 캡처 → mp4). 발표용 30초 이상 실주행 영상.

    python tools/record_video.py --model results/ppo_final/model.pt --route gyeongin_to_mapo
    python tools/record_video.py --policy expert --route olympic_to_singil --every 2 --fps 20
    (리눅스 서버: xvfb-run -a -s "-screen 0 1920x1080x24" python tools/record_video.py …)

sumo-gui가 ego(빨간 차)를 따라가며 확대 화면을 찍고, 각 프레임 위에
경로·속도·제한속도·다음 신호·진행률·주변 차량 수를 표시한 뒤 ffmpeg로 묶는다.
결과: assets/video/<route>_<policy>.mp4
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)


def overlay(path, lines, minimap=None):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    font = None
    try:   # pip install koreanize-matplotlib → 나눔고딕 포함
        import koreanize_matplotlib as _km
        km_font = os.path.join(os.path.dirname(_km.__file__), "fonts", "NanumGothic.ttf")
    except Exception:
        km_font = ""
    for f in (km_font, "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "C:/Windows/Fonts/malgun.ttf",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            font = ImageFont.truetype(f, 22)
            break
    font = font or ImageFont.load_default()
    h = 30 * len(lines) + 16
    d.rectangle([10, 10, 520, 10 + h], fill=(0, 0, 0, 160))
    for i, (txt, col) in enumerate(lines):
        d.text((22, 18 + 30 * i), txt, fill=col, font=font)
    im.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=["expert", "bc", "ppo"], default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--route", default="gyeongin_to_mapo")
    ap.add_argument("--every", type=int, default=2, help="N 스텝마다 1프레임 (0.5 s × N)")
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--zoom", type=float, default=3500)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--snapshot-index", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.policy is None:
        from collect_pomdp_data import detect_algorithm
        a.policy = detect_algorithm(a.model) if a.model else "expert"

    from env.mdp_config import SIMULATION, OBSERVATION, ACTION
    from env.sumo_env import YdpCityEnv
    from train import REWARD
    from evaluate import load_policy
    sim = {**SIMULATION, "gui_zoom": a.zoom, "gui_delay": 0}
    env = YdpCityEnv(sim, OBSERVATION, ACTION, REWARD, gui=True, gui_autostart=True, seed=a.seed,
                     routes=[a.route])
    pol = load_policy(a, env)
    W, H = (int(x) for x in a.size.split("x"))
    tmp = tempfile.mkdtemp(prefix="avvid_")
    frames = []
    try:
        obs, info = env.reset(seed=a.seed, options={"snapshot": env.snapshots[a.snapshot_index]})
        T = env.T
        view = T.gui.getIDList()[0]
        T.gui.setSchema(view, "real world")
        T.gui.trackVehicle(view, env.ego_id)
        T.gui.setZoom(view, a.zoom)
        step, done = 0, False
        pending = None
        while not done:
            act = pol.predict(obs, deterministic=True)
            if step % a.every == 0:
                fpath = os.path.join(tmp, f"f{len(frames):05d}.png")
                T.gui.screenshot(view, fpath, W, H)      # 다음 simulationStep 시점에 저장됨
                st = env.get_privileged_state()
                tls = env._tls_info() if st.get("ego_alive") else None
                sig = "-" if not tls or tls[0] > 150 else \
                    f"{tls[0]:.0f} m {'초록' if tls[1] > 0.5 else ('황색' if tls[1] > -0.5 else '적색')}"
                pending = (fpath, [
                    (f"AV 과제: {a.route}  ({a.policy.upper()})", (255, 255, 255)),
                    (f"도로: {st.get('ego_road_name', '')}", (255, 255, 255)),
                    (f"속도 {3.6 * st.get('ego_speed', 0):5.1f} km/h / 제한 {3.6 * st.get('speed_limit', 0):.0f}",
                     (120, 230, 255)),
                    (f"다음 신호: {sig}", (255, 220, 120)),
                    (f"진행 {min(100.0, 100 * st.get('route_progress_m', 0) / max(st.get('route_length_m', 1), 1)):5.1f} %"
                     f"  ·  주변 150 m 차량 {len(st.get('vehicles', []))}대  ·  t={T.simulation.getTime():.0f}s",
                     (200, 255, 200)),
                ])
                frames.append(pending)
            obs, r, term, trunc, inf = env.step(act)
            step += 1
            done = term or trunc or (a.max_steps and step >= a.max_steps)
        outcome = "충돌" if inf["collided"] else "목적지 도착" if inf["arrived"] else "중단"
        T.simulationStep() if not inf["arrived"] else None
    finally:
        env.close()
    frames = [f for f in frames if os.path.exists(f[0])]
    for i, (p, lines) in enumerate(frames):
        if i == len(frames) - 1:
            lines = lines + [(f"결과: {outcome}", (255, 120, 120) if outcome == "충돌" else (120, 255, 120))]
        overlay(p, lines)
    for k in range(a.fps * 2):          # 마지막 장면 2초 정지
        shutil.copy(frames[-1][0], os.path.join(tmp, f"f{len(frames) + k:05d}.png"))
    out = a.out or os.path.join(BASE, "assets", "video", f"{a.route}_{a.policy}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i",
                    os.path.join(tmp, "f%05d.png"), "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", out], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    dur = (len(frames) + a.fps * 2) / a.fps
    print(f"영상 저장: {out} ({dur:.0f} s, 실제 주행 {step * 0.5:.0f} s, 결과 {outcome})")


if __name__ == "__main__":
    main()
