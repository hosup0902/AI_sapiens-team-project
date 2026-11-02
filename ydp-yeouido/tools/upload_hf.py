"""수집한 주행 데이터를 Hugging Face Hub(datasets)에 업로드.

    pip install huggingface_hub
    huggingface-cli login                      # 또는 환경변수 HF_TOKEN
    python tools/upload_hf.py --repo <사용자명>/ydp-yeouido-av --files data/pomdp_*.npz data/pomdp_*.jsonl.gz

데이터 카드(README.md)는 docs/dataset_card.md 를 그대로 올린다.
큰 파일은 huggingface_hub 가 자동으로 LFS/xet 업로드한다.
"""
import argparse
import glob
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="예: myname/ydp-yeouido-av")
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args()
    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(a.repo, repo_type="dataset", private=a.private, exist_ok=True)
    card = os.path.join(BASE, "docs", "dataset_card.md")
    if os.path.exists(card):
        api.upload_file(path_or_fileobj=card, path_in_repo="README.md", repo_id=a.repo, repo_type="dataset")
    files = sorted({f for pat in a.files for f in glob.glob(pat)})
    for f in files:
        print(f"업로드: {f} ({os.path.getsize(f) / 2 ** 20:.1f} MB)")
        api.upload_file(path_or_fileobj=f, path_in_repo=f"data/{os.path.basename(f)}",
                        repo_id=a.repo, repo_type="dataset")
    print(f"완료 → https://huggingface.co/datasets/{a.repo}")


if __name__ == "__main__":
    main()
