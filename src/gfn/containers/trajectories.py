from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from gfn.envs import Env
    from gfn.containers.states import States

import torch
from torchtyping import TensorType

from gfn.containers.base import Container
from gfn.containers.transitions import Transitions

# Typing  --- n_transitions is an int
Tensor2D = TensorType["max_length", "n_trajectories", torch.long]
Tensor2D2 = TensorType["n_trajectories", "shape"]
Tensor1D = TensorType["n_trajectories", torch.long]
FloatTensor1D = TensorType["n_trajectories", torch.float]


class Trajectories(Container):
    def __init__(
        self,
        env: Env,
        states: States | None = None,
        actions: Tensor2D | None = None,
        when_is_done: Tensor1D | None = None,
        is_backward: bool = False,
        rewards: FloatTensor1D | None = None,
        log_pfs: FloatTensor1D | None = None,  # log_probs of the trajectories
        log_pbs: FloatTensor1D | None = None,  # log_probs of the backward trajectories
    ) -> None:
        """Container for complete trajectories (starting in s_0 and ending in s_f).
        Trajectories are represented as a States object with bi-dimensional batch shape.
        The first dimension represents the time step, the second dimension represents the trajectory index.
        Because different trajectories may have different lengths, shorter trajectories are padded with
        the tensor representation of the terminal state (s_f or s_0 depending on the direction of the trajectory), and
        actions is appended with -1's.
        The actions are represented as a two dimensional tensor with the first dimension representing the time step
        and the second dimension representing the trajectory index.
        The when_is_done tensor represents the time step at which each trajectory ends.
        The log_pfs tensor represents the log probability (P_F) of each trajectory.
        The log_pbs tensor represents the log probability (P_B) of each trajectory.


        Args:
            env (Env): The environment in which the trajectories are defined.
            states (States, optional): The states of the trajectories. Defaults to None.
            actions (Tensor2D, optional): The actions of the trajectories. Defaults to None.
            when_is_done (Tensor1D, optional): The time step at which each trajectory ends. Defaults to None.
            is_backward (bool, optional): Whether the trajectories are backward or forward. Defaults to False.
            rewards (FloatTensor1D, optional): The rewards of the trajectories. Defaults to None.
            log_pfs (FloatTensor1D, optional): The log probability (P_F) of each trajectory. Defaults to None.
            log_pbs (FloatTensor1D, optional): The log probability (P_B) of each trajectory. Defaults to None.

        If states is None, then the states are initialized to an empty States object, that can be populated on the fly.
        If rewards is None, then `env.reward` is used to compute the rewards, at each call of self.rewards
        """
        self.env = env
        self.is_backward = is_backward
        self.states = (
            states
            if states is not None
            else env.States.from_batch_shape(batch_shape=(0, 0))
        )
        assert len(self.states.batch_shape) == 2
        self.actions = (
            actions
            if actions is not None
            else torch.full(size=(0, 0), fill_value=-1, dtype=torch.long)
        )
        self.when_is_done = (
            when_is_done
            if when_is_done is not None
            else torch.full(size=(0,), fill_value=-1, dtype=torch.long)
        )
        self._rewards = rewards
        self.log_pfs = log_pfs
        self.log_pbs = log_pbs

    def __repr__(self) -> str:
        states = self.states.states_tensor.transpose(0, 1)
        assert states.ndim == 3
        trajectories_representation = ""
        for traj in states[:10]:
            one_traj_repr = []
            for step in traj:
                one_traj_repr.append(str(step.numpy()))
                if step.equal(self.env.s0 if self.is_backward else self.env.sf):
                    break
            trajectories_representation += "-> ".join(one_traj_repr) + "\n"
        return (
            f"Trajectories(n_trajectories={self.n_trajectories}, max_length={self.max_length}, First 10 trajectories:"
            + f"states=\n{trajectories_representation}, actions=\n{self.actions.transpose(0, 1)[:10].numpy()}, "
            + f"when_is_done={self.when_is_done[:10].numpy()})"
        )

    @property
    def n_trajectories(self) -> int:
        return self.states.batch_shape[1]

    def __len__(self) -> int:
        return self.n_trajectories

    @property
    def max_length(self) -> int:
        if len(self) == 0:
            return 0

        return self.actions.shape[0]

    @property
    def last_states(self) -> States:
        return self.states[self.when_is_done - 1, torch.arange(self.n_trajectories)]

    @property
    def rewards(self) -> FloatTensor1D | None:
        if self._rewards is not None:
            assert self._rewards.shape == (self.n_trajectories,)
            return self._rewards
        if self.is_backward:
            return None
        return self.env.reward(self.last_states)

    def __getitem__(self, index: int | Sequence[int]) -> Trajectories:
        "Returns a subset of the `n_trajectories` trajectories."
        if isinstance(index, int):
            index = [index]
        when_is_done = self.when_is_done[index]
        new_max_length = when_is_done.max().item() if len(when_is_done) > 0 else 0
        states = self.states[:, index]
        actions = self.actions[:, index]
        states = states[: 1 + new_max_length]
        actions = actions[:new_max_length]
        rewards = self._rewards[index] if self._rewards is not None else None
        log_pfs = self.log_pfs[index] if self.log_pfs is not None else None
        log_pbs = self.log_pbs[index] if self.log_pbs is not None else None
        return Trajectories(
            env=self.env,
            states=states,
            actions=actions,
            when_is_done=when_is_done,
            is_backward=self.is_backward,
            rewards=rewards,
            log_pfs=log_pfs,
            log_pbs=log_pbs,
        )

    def extend(self, other: Trajectories) -> None:
        """Extend the trajectories with another set of trajectories."""
        self.extend_actions(required_first_dim=max(self.max_length, other.max_length))
        other.extend_actions(required_first_dim=max(self.max_length, other.max_length))

        self.states.extend(other.states)
        self.actions = torch.cat((self.actions, other.actions), dim=1)
        self.when_is_done = torch.cat((self.when_is_done, other.when_is_done), dim=0)
        if self.log_pfs is not None and other.log_pfs is not None:
            self.log_pfs = torch.cat((self.log_pfs, other.log_pfs), dim=0)
        else:
            self.log_pfs = None
        if self.log_pbs is not None and other.log_pbs is not None:
            self.log_pbs = torch.cat((self.log_pbs, other.log_pbs), dim=0)
        else:
            self.log_pbs = None
        if self._rewards is not None and other._rewards is not None:
            self._rewards = torch.cat((self._rewards, other._rewards), dim=0)
        else:
            self._rewards = None

    def extend_actions(self, required_first_dim: int) -> None:
        """Extends the actions along the first dimension by by adding -1s as necessary.
        This is useful for extending trajectories of different lengths."""
        if self.max_length >= required_first_dim:
            return
        self.actions = torch.cat(
            (
                self.actions,
                torch.full(
                    size=(
                        required_first_dim - self.actions.shape[0],
                        self.n_trajectories,
                    ),
                    fill_value=-1,
                    dtype=torch.long,
                ),
            ),
            dim=0,
        )

    @staticmethod
    def revert_backward_trajectories(trajectories: Trajectories) -> Trajectories:

        assert trajectories.is_backward
        new_actions = torch.full_like(trajectories.actions, -1)
        new_actions = torch.cat(
            [new_actions, torch.full((1, len(trajectories)), -1)], dim=0
        )
        new_states = trajectories.env.s_f.repeat(  # type: ignore
            trajectories.when_is_done.max() + 1, len(trajectories), 1
        )
        new_when_is_done = trajectories.when_is_done + 1
        for i in range(len(trajectories)):
            new_actions[trajectories.when_is_done[i], i] = (
                trajectories.env.n_actions - 1
            )
            new_actions[: trajectories.when_is_done[i], i] = trajectories.actions[
                : trajectories.when_is_done[i], i
            ].flip(0)
            new_states[
                : trajectories.when_is_done[i] + 1, i
            ] = trajectories.states.states_tensor[
                : trajectories.when_is_done[i] + 1, i
            ].flip(
                0
            )
        new_states = trajectories.env.States(new_states)
        return Trajectories(
            env=trajectories.env,
            states=new_states,
            actions=new_actions,
            when_is_done=new_when_is_done,
            is_backward=False,
        )

    def to_transitions(self) -> Transitions:
        """Returns a `Transitions` object from the trajectories"""
        states = self.states[:-1][self.actions != -1]
        next_states = self.states[1:][self.actions != -1]
        actions = self.actions[self.actions != -1]
        is_done = (
            next_states.is_sink_state
            if not self.is_backward
            else next_states.is_initial_state
        )
        if self._rewards is None:
            rewards = None
        else:
            rewards = torch.full_like(actions, fill_value=-1.0, dtype=torch.float)
            rewards[is_done] = torch.cat(
                [
                    self._rewards[self.when_is_done == i]
                    for i in range(self.when_is_done.max() + 1)
                ],
                dim=0,
            )
        return Transitions(
            env=self.env,
            states=states,
            actions=actions,
            is_done=is_done,
            next_states=next_states,
            is_backward=self.is_backward,
            rewards=rewards,
        )

    def to_states(self) -> States:
        """Returns a `States` object from the trajectories, containing all states in the trajectories"""
        states = self.states.flatten()
        return states[~states.is_sink_state]

    def to_non_initial_intermediary_and_terminating_states(
        self,
    ) -> tuple[States, States]:
        """Returns a tuple of `States` objects from the trajectories, containing all non-initial intermediary and terminating states in the trajectories

        Returns:
            Tuple[States, States]: - All the intermediary states in the trajectories that are not s0.
                                   - All the terminating states in the trajectories that are not s0.
        """
        states = self.states[:-1][self.actions != self.env.n_actions - 1]
        intermediary_states = states[~states.is_sink_state & ~states.is_initial_state]
        terminating_states = self.last_states
        terminating_states = terminating_states[~terminating_states.is_initial_state]
        return intermediary_states, terminating_states

    # def copy(self) -> Trajectories:
    #     return Trajectories(
    #         env=self.env,
    #         states=self.states.copy(),
    #         actions=self.actions.clone(),
    #         when_is_done=self.when_is_done.clone(),
    #         is_backward=self.is_backward,
    #         log_pfs=self.log_pfs.clone() if self.log_pfs is not None else None,
    #         log_pbs=self.log_pbs.clone() if self.log_pbs is not None else None,
    #     )
