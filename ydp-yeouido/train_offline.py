"""오프라인 강화학습(TD3+BC) 학습 — 수집 데이터(NPZ)만 사용, 환경 상호작용 없음.

    python train_offline.py --data data/ydp_ppo_final.npz data/ydp_ppo_bulk_01.npz --steps 200000
    python evaluate.py --model results/td3bc/model.pt --episodes 100 --workers 4

결과: results/<run>/model.pt (algorithm=td3bc), training_log.csv
"""
import argparse
import csv
import os
import time

import numpy as np
import torch

from algorithms.td3bc import TD3BC

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--steps", type=int, default=200_000)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--alpha", type=float, default=2.5)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run-name", default="td3bc")
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    np.random.seed(a.seed)

    S, A, R, S2, D = [], [], [], [], []
    for p in a.data:
        d = np.load(p)
        S.append(d["observation"]); A.append(d["action_raw"]); R.append(d["reward"])
        S2.append(d["next_observation"]); D.append(d["terminated"])
        print(f"{p}: {len(d['reward'])} transitions")
    S, A, S2 = np.concatenate(S), np.clip(np.concatenate(A), -1, 1), np.concatenate(S2)
    R, D = np.concatenate(R).reshape(-1, 1), np.concatenate(D).reshape(-1, 1)
    n = len(R)
    agent = TD3BC(S.shape[1], A.shape[1], alpha=a.alpha)
    mean, std = S.mean(0), S.std(0) + 1e-3
    agent.obs_mean, agent.obs_std = torch.as_tensor(mean), torch.as_tensor(std)
    St = torch.as_tensor((S - mean) / std, dtype=torch.float32)
    S2t = torch.as_tensor((S2 - mean) / std, dtype=torch.float32)
    At, Rt = torch.as_tensor(A), torch.as_tensor(R, dtype=torch.float32)
    NDt = torch.as_tensor(1.0 - D.astype(np.float32))
    run = os.path.join(BASE, "results", a.run_name)
    os.makedirs(run, exist_ok=True)
    log = []
    t0 = time.time()
    print(f"총 {n} transitions · {a.steps} 업데이트 · batch {a.batch}")
    for it in range(1, a.steps + 1):
        idx = torch.randint(0, n, (a.batch,))
        out = agent.train_step(St[idx], At[idx], Rt[idx], S2t[idx], NDt[idx])
        if it % 5000 == 0:
            row = {"step": it, **{k: round(v, 5) for k, v in out.items()}, "elapsed_s": round(time.time() - t0)}
            log.append(row)
            print(row, flush=True)
    agent.save(os.path.join(run, "model.pt"))
    with open(os.path.join(run, "training_log.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in log for k in r)))
        w.writeheader()
        w.writerows(log)
    print(f"저장: {run}/model.pt ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
