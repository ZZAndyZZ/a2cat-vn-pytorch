from common.train_wrappers import wrap
from common.env_wrappers import ColorObservationWrapper
import os
import gym
from functools import reduce
from math import sqrt
from common import register_trainer, make_trainer, register_agent, make_agent
from a2c import A2CTrainerDynamicBatch as A2CTrainer
from a2c.model import TimeDistributedConv
import numpy as np
from gym.wrappers import TimeLimit
from baselines.common.atari_wrappers import make_atari, wrap_deepmind

class FlatWrapper(gym.ObservationWrapper):
    def observation(self, observation):
        return np.reshape(observation, [-1])


@register_trainer(max_time_steps = 10e6, validation_period = None,  episode_log_interval = 10, save = False)
class Trainer(A2CTrainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_envs = 16
        self.n_steps = 5
        self.total_timesteps = 10e6
        self.gamma = .99
        self.devices = ['cuda:0']

    def create_model(self):
        return TimeDistributedConv(self.env.observation_space.shape[0], self.env.action_space.n)

def default_args():
    return dict(
        env_kwargs = 'BreakoutNoFrameskip-v4',
        model_kwargs = dict()
    )