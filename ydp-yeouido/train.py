"""PPO 학습 (수업 algorithms/ppo.py 그대로 사용) — 영등포~여의도 도시망.

    python train.py --bc-data data/expert_train.npz --timesteps 200000
    python train.py --timesteps 300000                       # BC 초기화 없이 처음부터

절차
    1) (선택) BC warm start: 전문가 데이터로 정책 head(가감속 μ·차선 logits)와
       가치 head(할인 리턴 회귀)를 지도학습 — 처음부터 PPO를 돌리면 4~5 km 도시 경로에서
       무작위 정책이 첫 교차로도 못 넘어 학습 신호가 거의 없다.
    2) PPO 미세조정: rollout → GAE → clipped surrogate (수업 코드)
    3) eval_interval 업데이트마다 결정적 정책으로 평가, 충돌률↓·완주율↑ 기준 best 모델 저장
결과: results/<run>/model.pt (best), model_last.pt, training_log.csv, eval_log.csv, 설정 스냅샷
"""
import argparse
import os
import shutil
from collections import deque
from datetime import datetime

import numpy as np
import torch
import torch.nn.functional as F

from env.mdp_config import SIMULATION, OBSERVATION, ACTION
from env.mdp_config import REWARD as REWARD_DEFAULTS

BASE = os.path.dirname(os.path.abspath(__file__))

# ══════════════════════════════════════════════════════════════════
#  보상 튜닝 — env/mdp_config.py 기본값 덮어쓰기 (evaluate/collect도 이 값을 쓴다)
# ══════════════════════════════════════════════════════════════════
REWARD_OVERRIDES = dict()
REWARD = {**REWARD_DEFAULTS, **REWARD_OVERRIDES}

HPARAMS = dict(
    lr=3e-5,                 # BC로 초기화된 정책을 망가뜨리지 않도록 작게
    n_steps=4096,
    n_epochs=5,
    minibatch_size=256,
    gamma=0.99,
    gae_lambda=0.95,
    clip_eps=0.1,
    value_coef=0.5,
    entropy_coef=0.0,
    lane_entropy_coef=0.002,
    max_grad_norm=0.5,
    normalize_advantage=True,
    hidden_sizes=(256, 256),
    activation="relu",
    policy_type="hybrid",    # 가감속 Normal + 차선 Categorical (수업 권장)
    lane_keep_bias=2.0,
    init_log_std=-1.2,       # BC 초기화 후 탐험 폭 σ≈0.30
    seed=0,
    device="cpu",
)


def make_env(seed=0, route_mode="random", shield=True):
    from env.sumo_env import YdpCityEnv
    action = dict(ACTION)
    if not shield:
        action["shield"] = {**ACTION["shield"], "enabled": False}
    return YdpCityEnv(SIMULATION, OBSERVATION, action, REWARD, seed=seed, route_mode=route_mode)


def discounted_returns(rew, ep, term, gamma):
    ret = np.zeros_like(rew)
    g = 0.0
    for i in range(len(rew) - 1, -1, -1):
        if i == len(rew) - 1 or ep[i + 1] != ep[i]:
            g = 0.0
        g = rew[i] + gamma * g
        ret[i] = g
    return ret


def bc_warm_start(agent, paths, epochs=30, batch=512, lr=1e-3, log=print):
    """하이브리드 정책을 전문가 데이터로 초기화: μ ← MSE, 차선 ← CE, V ← 할인 리턴 MSE."""
    obs, act, rew, ep, term = [], [], [], [], []
    off = 0
    for p in paths:
        d = np.load(p)
        obs.append(d["observation"])
        act.append(d["action_raw"])
        rew.append(d["reward"])
        ep.append(d["episode"].astype(np.int64) + off)
        term.append(d["terminated"])
        off = int(ep[-1].max()) + 1
    obs, act = np.concatenate(obs), np.concatenate(act)
    rew, ep, term = np.concatenate(rew), np.concatenate(ep), np.concatenate(term)
    ret = discounted_returns(rew, ep, term, agent.gamma).astype(np.float32)
    lane_idx = (1 - np.round(act[:, 1])).astype(np.int64).clip(0, 2)
    # 차선 변경 샘플은 드물다 → 클래스 가중치
    cnt = np.bincount(lane_idx, minlength=3).astype(np.float64) + 1
    w = torch.as_tensor((cnt.sum() / (3 * cnt)) ** 0.5, dtype=torch.float32)
    X = torch.as_tensor(obs)
    A = torch.as_tensor(act[:, 0:1])
    L = torch.as_tensor(lane_idx)
    R = torch.as_tensor(ret)
    pol = agent.policy
    opt = torch.optim.Adam([p for n, p in pol.named_parameters() if n != "log_std"], lr=lr)
    n = len(X)
    log(f"[BC warm start] transitions {n}, 차선 분포 좌/유지/우 = {np.bincount(lane_idx, minlength=3).tolist()}")
    for e in range(epochs):
        perm = torch.randperm(n)
        tot = [0.0, 0.0, 0.0]
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            mu, _, logits, v = pol(X[idx])
            l_mu = F.mse_loss(mu, A[idx])
            l_lane = F.cross_entropy(logits, L[idx], weight=w)
            l_v = F.mse_loss(v, R[idx])
            loss = l_mu + 0.5 * l_lane + 0.05 * l_v
            opt.zero_grad()
            loss.backward()
            opt.step()
            k = len(idx) / n
            tot[0] += l_mu.item() * k
            tot[1] += l_lane.item() * k
            tot[2] += l_v.item() * k
        if e % 5 == 0 or e == epochs - 1:
            log(f"  epoch {e + 1:3d}/{epochs}  mse(μ)={tot[0]:.4f}  ce(lane)={tot[1]:.4f}  mse(V)={tot[2]:.3f}")


def score(m):
    """best 모델 선택 기준: 충돌률 최소 → 완주율 최대 → 평균속도."""
    return (-m.collision_rate, m.success_rate, m.mean_speed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=200_000)
    ap.add_argument("--bc-data", nargs="*", default=[])
    ap.add_argument("--bc-epochs", type=int, default=30)
    ap.add_argument("--init", default=None, help="이어서 학습할 model.pt")
    ap.add_argument("--eval-interval", type=int, default=5)
    ap.add_argument("--eval-episodes", type=int, default=7)
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    # 환경(SUMO) 스텝이 병목이고 신경망은 작다 → 스레드를 줄여 평가·수집 프로세스와의 CPU 경합(OpenMP 대기)을 막는다
    torch.set_num_threads(2)
    from algorithms.ppo import PPO
    from utils.buffer import RolloutBuffer
    from utils.logger import RunLogger
    from utils.evaluator import evaluate_policy

    run_dir = os.path.join(BASE, "results", a.run_name or datetime.now().strftime("ppo_%Y%m%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    for f in ("env/road_config.py", "env/mdp_config.py", "train.py"):
        shutil.copy(os.path.join(BASE, f), run_dir)
    logger = RunLogger(run_dir)
    print(f"결과 폴더: {run_dir}")

    # libsumo는 프로세스당 SUMO 하나 → 학습·평가가 같은 환경을 쓴다 (수업 코드와 동일)
    env = make_env(seed=a.seed, route_mode="random")
    agent = PPO(obs_dim=env.observation_space.shape[0], act_dim=env.action_space.shape[0],
                buffer=RolloutBuffer(), **{**HPARAMS, "seed": a.seed})
    if a.init:
        agent.load(a.init)
        print(f"초기 가중치: {a.init}")
    if a.bc_data:
        bc_warm_start(agent, a.bc_data, epochs=a.bc_epochs)

    eval_rng_state = env.rng.getstate()

    def evaluate(tag):
        """7개 경로를 한 번씩, 매번 같은 교통 상황(난수 상태 고정)에서 평가 → 업데이트 간 비교 가능."""
        train_state = env.rng.getstate()
        env.rng.setstate(eval_rng_state)
        env.route_mode, env._route_cursor = "cycle", 0
        m = evaluate_policy(agent, env, n_episodes=a.eval_episodes, deterministic=True)
        env.route_mode = "random"
        env.rng.setstate(train_state)
        logger.log_eval(agent.num_timesteps, m.as_dict(), f"[{tag}] " + m.summary(), a.eval_episodes)
        return m

    best = evaluate("init")
    agent.save(os.path.join(run_dir, "model.pt"))
    obs, _ = env.reset()
    ep_stats = [0.0, 0]
    recent = deque(maxlen=20)
    n_updates = 0
    try:
        while agent.num_timesteps < a.timesteps:
            obs, last_v, finished = agent.collect_rollout(env, obs, logger=logger, ep_stats=ep_stats)
            recent.extend(finished)
            adv, ret = agent.buffer.compute_gae(last_v, agent.gamma, agent.gae_lambda)
            stats = agent.update(adv, ret)
            n_updates += 1
            logger.log_train(agent.num_timesteps, {
                "update": n_updates,
                "ep_rew_mean": float(np.mean(recent)) if recent else float("nan"),
                "std": agent.policy.current_std, **stats})
            if a.eval_interval and n_updates % a.eval_interval == 0:
                m = evaluate(f"upd {n_updates}")
                obs, _ = env.reset()
                ep_stats[0], ep_stats[1] = 0.0, 0
                agent.save(os.path.join(run_dir, "model_last.pt"))
                if score(m) >= score(best):
                    best = m
                    agent.save(os.path.join(run_dir, "model.pt"))
                    print(f"  ★ best 갱신: {m.summary()}")
    finally:
        agent.save(os.path.join(run_dir, "model_last.pt"))
        env.close()
        logger.close()
    print(f"\nbest: {best.summary()}\n저장: {os.path.join(run_dir, 'model.pt')}")


if __name__ == "__main__":
    main()
