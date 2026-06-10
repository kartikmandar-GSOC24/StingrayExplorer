"""Shared fixtures for backend service tests.

python-backend is not an installable package (hyphenated dir name), so tests
add it to sys.path and import the same way main.py does (cwd=python-backend).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from stingray import EventList

from services.state_manager import StateManager


def make_event_list(seed: int, n_events: int = 20000, length: float = 64.0) -> EventList:
    """Deterministic synthetic event list spanning [0, length] seconds."""
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0.0, length, n_events))
    energy = rng.uniform(0.5, 10.0, n_events)
    return EventList(time=times, energy=energy, gti=[[0.0, length]])


@pytest.fixture()
def state_manager() -> StateManager:
    return StateManager()


@pytest.fixture()
def loaded_state(state_manager: StateManager) -> StateManager:
    state_manager.add_event_data("ev1", make_event_list(1))
    state_manager.add_event_data("ev2", make_event_list(2))
    return state_manager
