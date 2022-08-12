from abc import ABC, abstractmethod
from torchtyping import TensorType
from gfn.envs.env import Env, AbstractStatesBatch
from typing import Tuple


class Preprocessor(ABC):
    """
    Base class for Preprocessors. The goal is to transform tensors representing raw states
    to tensors that can be used as input to neural networks.
    """

    def __init__(self, env: Env) -> None:
        self.env = env

    @property
    @abstractmethod
    def output_dim(self) -> Tuple:
        pass

    @abstractmethod
    def preprocess(self, states: AbstractStatesBatch) -> TensorType['batch_shape', 'dim_in', float]:
        pass

    def __call__(self, states):
        return self.preprocess(states)


class IdentityPreprocessor(Preprocessor):
    "simple preprocessor applicable to environments with unidimensional states."
    @property
    def output_dim(self):
        return self.env.ndim

    def preprocess(self, states):
        return states.states.float()