"""TD3+BC — 오프라인 강화학습 (Fujimoto & Gu, "A Minimalist Approach to Offline RL", NeurIPS 2021).

수집된 데이터(observation, action_raw, reward, next_observation, terminated)만으로 학습한다.
환경과 상호작용하지 않는다 (수업 자료 Option B).

    actor 손실  = −λ · Q(s, π(s)) + (π(s) − a_data)²,   λ = α / mean|Q|
    critic      = TD3: 두 Q의 최솟값 타깃 + 타깃 정책 스무딩 + 지연된 actor 업데이트

BC 항 덕분에 데이터에 없는 행동으로 벗어나는 외삽 오차를 막고, Q 항으로 데이터 안에서 더 나은
행동(충돌 직전 감속, 정체 속 출발 등)을 고른다. 행동 [가감속, 차선] 모두 tanh 연속 출력이고,
차선은 환경에서 ±0.5 문턱으로 −1/0/+1 이 된다 (BCPolicy와 같은 방식).
"""
import copy

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def mlp(i, o, h=(256, 256)):
    layers, d = [], i
    for k in h:
        layers += [nn.Linear(d, k), nn.ReLU()]
        d = k
    layers.append(nn.Linear(d, o))
    return nn.Sequential(*layers)


class Actor(nn.Module):
    def __init__(self, s, a):
        super().__init__()
        self.net = mlp(s, a)

    def forward(self, x):
        return torch.tanh(self.net(x))


class Critic(nn.Module):
    def __init__(self, s, a):
        super().__init__()
        self.q1, self.q2 = mlp(s + a, 1), mlp(s + a, 1)

    def forward(self, s, a):
        x = torch.cat([s, a], -1)
        return self.q1(x), self.q2(x)


class TD3BC:
    def __init__(self, state_dim, action_dim=2, gamma=0.99, tau=0.005, policy_noise=0.2,
                 noise_clip=0.5, policy_freq=2, alpha=2.5, lr=3e-4, device="cpu"):
        self.device = torch.device(device)
        self.actor = Actor(state_dim, action_dim).to(self.device)
        self.actor_t = copy.deepcopy(self.actor)
        self.critic = Critic(state_dim, action_dim).to(self.device)
        self.critic_t = copy.deepcopy(self.critic)
        self.a_opt = torch.optim.Adam(self.actor.parameters(), lr=lr)
        self.c_opt = torch.optim.Adam(self.critic.parameters(), lr=lr)
        self.gamma, self.tau = gamma, tau
        self.policy_noise, self.noise_clip, self.policy_freq, self.alpha = policy_noise, noise_clip, policy_freq, alpha
        self.state_dim, self.action_dim = state_dim, action_dim
        self.obs_mean = torch.zeros(state_dim, device=self.device)
        self.obs_std = torch.ones(state_dim, device=self.device)
        self.it = 0

    def norm(self, s):
        return (s - self.obs_mean) / self.obs_std

    def train_step(self, s, a, r, s2, nd):
        self.it += 1
        with torch.no_grad():
            noise = (torch.randn_like(a) * self.policy_noise).clamp(-self.noise_clip, self.noise_clip)
            a2 = (self.actor_t(s2) + noise).clamp(-1, 1)
            q1t, q2t = self.critic_t(s2, a2)
            target = r + nd * self.gamma * torch.min(q1t, q2t)
        q1, q2 = self.critic(s, a)
        c_loss = F.mse_loss(q1, target) + F.mse_loss(q2, target)
        self.c_opt.zero_grad()
        c_loss.backward()
        self.c_opt.step()
        out = {"critic_loss": c_loss.item()}
        if self.it % self.policy_freq == 0:
            pi = self.actor(s)
            q = self.critic(s, pi)[0]
            lmbda = self.alpha / q.abs().mean().detach()
            bc = F.mse_loss(pi, a)
            a_loss = -lmbda * q.mean() + bc
            self.a_opt.zero_grad()
            a_loss.backward()
            self.a_opt.step()
            for p, pt in zip(self.critic.parameters(), self.critic_t.parameters()):
                pt.data.mul_(1 - self.tau).add_(self.tau * p.data)
            for p, pt in zip(self.actor.parameters(), self.actor_t.parameters()):
                pt.data.mul_(1 - self.tau).add_(self.tau * p.data)
            out.update(actor_loss=a_loss.item(), bc_mse=bc.item(), q_mean=q.mean().item())
        return out

    @torch.no_grad()
    def predict(self, obs, deterministic=True):
        s = torch.as_tensor(np.asarray(obs, np.float32), device=self.device).unsqueeze(0)
        return self.actor(self.norm(s)).squeeze(0).cpu().numpy()

    def save(self, path):
        torch.save({"algorithm": "td3bc", "state_dim": self.state_dim, "action_dim": self.action_dim,
                    "actor": self.actor.state_dict(), "critic": self.critic.state_dict(),
                    "obs_mean": self.obs_mean.cpu(), "obs_std": self.obs_std.cpu()}, path)

    @classmethod
    def load(cls, path, device="cpu"):
        ck = torch.load(path, map_location=device, weights_only=True)
        m = cls(ck["state_dim"], ck["action_dim"], device=device)
        m.actor.load_state_dict(ck["actor"])
        m.critic.load_state_dict(ck["critic"])
        m.obs_mean, m.obs_std = ck["obs_mean"].to(device), ck["obs_std"].to(device)
        return m
