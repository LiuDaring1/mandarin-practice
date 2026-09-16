"""Balanced Random Training Generator (v1).

This subpackage implements the training-session generator on top of the
phonology-v1 feature layer.  It reads ``phonology.sqlite3`` and the master
``corpus.sqlite3`` read-only and writes generated sessions / reports to an
isolated output directory.
"""

from .candidates import (
    compute_pool_stats,
    filter_candidates,
    load_items,
)
from .generator import (
    generate_session,
    run_benchmark,
    run_candidate_stats,
)
from .models import (
    GENERATOR_VERSION,
    BalanceDimension,
    GeneratorConfig,
    Item,
    PositionDimension,
    SyllableInfo,
    TrainingProfile,
)

__all__ = [
    "GENERATOR_VERSION",
    "BalanceDimension",
    "GeneratorConfig",
    "Item",
    "PositionDimension",
    "SyllableInfo",
    "TrainingProfile",
    "compute_pool_stats",
    "filter_candidates",
    "generate_session",
    "load_items",
    "run_benchmark",
    "run_candidate_stats",
]
