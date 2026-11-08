"""Public interface exported to the backend and scheduler teammates.

The scheduler is imported lazily by run_simulation only, allowing dataset
preprocessing and scenario generation before scheduler/ is integrated.
"""
from .engine import run_simulation
from .competition import generate_competition_scenario
from .experiments import run_experiment, validate_experiment_config
from .generator import generate_scenario
from .models import ScenarioValidationError, validate_scenario

__all__ = [
    "run_simulation",
    "generate_competition_scenario",
    "run_experiment",
    "validate_experiment_config",
    "generate_scenario",
    "validate_scenario",
    "ScenarioValidationError",
]
