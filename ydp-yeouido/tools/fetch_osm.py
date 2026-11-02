"""OpenStreetMap 원본 데이터 다운로드 (Overpass API).

env/road_config.py 의 REGION["bbox"] 범위 안의
    - 도로(highway), 철도(railway)
    - 건물(building)  → SUMO 건물 폴리곤
    - 토지이용/공원/수면(landuse, leisure, natural, waterway) → 한강·여의도공원 등 배경
를 한 번에 받아 data/osm/region.osm 으로 저장한다.

사용법:
    python tools/fetch_osm.py            # 이미 파일이 있으면 건너뜀
    python tools/fetch_osm.py --force    # 다시 받기

공개 Overpass 서버는 자주 혼잡(504)하므로 여러 미러를 지수 백오프로 돌아가며 시도한다.
"""
import argparse
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from env.road_config import REGION  # noqa: E402

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def build_query(bbox):
    s, w, n, e = bbox
    b = f"({s},{w},{n},{e})"
    parts = [f'way["{k}"]{b};' for k in
             ("highway", "railway", "building", "landuse", "leisure",
              "natural", "waterway", "amenity", "bridge")]
    parts += [f'relation["{k}"]{b};' for k in
              ("building", "landuse", "leisure", "natural", "waterway")]
    # 회전 제한(좌회전 금지·직진 전용 등) — netconvert가 연결(connection)에서 제외한다
    parts += [f'relation["type"="restriction"]{b};']
    return f"[out:xml][timeout:240];({''.join(parts)});(._;>;);out body;"


def fetch(out_path, bbox, tries=6):
    data = urllib.parse.urlencode({"data": build_query(bbox)}).encode()
    wait = 5
    for attempt in range(tries):
        for url in MIRRORS:
            try:
                print(f"[{attempt + 1}/{tries}] {url} ...", flush=True)
                req = urllib.request.Request(url, data=data, headers={
                    "User-Agent": "skku-av-project/1.0 (course project)"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    body = r.read()
                if len(body) < 100_000 or b"<osm" not in body[:500]:
                    raise RuntimeError(f"응답이 너무 작음 ({len(body)} B)")
                tmp = out_path + ".part"
                with open(tmp, "wb") as f:
                    f.write(body)
                os.replace(tmp, out_path)
                print(f"저장: {out_path} ({len(body) / 1e6:.1f} MB)")
                return True
            except Exception as ex:  # noqa: BLE001
                print(f"   실패: {ex}")
        print(f"   {wait}s 대기 후 재시도")
        time.sleep(wait)
        wait *= 2
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    out = os.path.join(BASE, REGION["osm_file"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out) and not args.force:
        print(f"이미 있음: {out} (--force 로 다시 받기)")
        sys.exit(0)
    sys.exit(0 if fetch(out, REGION["bbox"]) else 1)
