"""수집한 주행 데이터를 Hugging Face Hub(datasets)에 업로드.

    pip install huggingface_hub
    huggingface-cli login                      # 또는 환경변수 HF_TOKEN
    python tools/upload_hf.py --repo <사용자명>/ydp-yeouido-av \
        --files "data/*.npz" "data/*.jsonl.gz" "data/multi/*.npz" "data/multi_v2/*.npz"

저장소 안 경로(data/multi_v2/... 등)를 그대로 유지하고, 파일 수가 많아도 한 번의 커밋으로 올린다.

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
    from huggingface_hub import CommitOperationAdd
    ops = [CommitOperationAdd(path_in_repo=os.path.relpath(os.path.abspath(f), BASE).replace(os.sep, "/"),
                              path_or_fileobj=f) for f in files]
    for i in range(0, len(ops), 50):         # 50개씩 커밋 (큰 커밋 실패 시 재시도 단위를 작게)
        api.create_commit(repo_id=a.repo, repo_type="dataset", operations=ops[i:i + 50],
                          commit_message=f"Add data files {i + 1}-{min(i + 50, len(ops))}")
        print(f"  {min(i + 50, len(ops))}/{len(ops)} 업로드")
    print(f"완료 → https://huggingface.co/datasets/{a.repo}")


if __name__ == "__main__":
    main()
