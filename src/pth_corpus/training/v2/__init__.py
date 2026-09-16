"""Training Session Generator v2: structure-first balanced random sessions."""

from .schema import (
    V2Bucket,
    V2Profile,
    load_v2_profiles,
)
from .engine import (
    classify_item,
    compute_availability,
    matched_patterns,
    signature_of,
)
from .generator import (
    generate_session_v2,
    run_availability_v2,
    run_benchmark_v2,
)

__all__ = [
    "V2Bucket",
    "V2Profile",
    "classify_item",
    "compute_availability",
    "generate_session_v2",
    "load_v2_profiles",
    "matched_patterns",
    "run_availability_v2",
    "run_benchmark_v2",
    "signature_of",
]
