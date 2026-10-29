from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import product
from typing import Any

from app.evaluation.models import ParameterTrial


def expand_parameter_grid(
    parameter_grid: Mapping[str, Sequence[Any]],
    *,
    base_parameters: Mapping[str, Any] | None = None,
    id_prefix: str = "trial",
) -> tuple[ParameterTrial, ...]:
    """Build deterministic Cartesian trials for exhaustive, reproducible sweeps."""

    keys = tuple(sorted(parameter_grid))
    value_sets = tuple(parameter_grid[key] for key in keys)
    if any(not values for values in value_sets):
        raise ValueError("every parameter grid entry needs at least one value")
    combinations = product(*value_sets) if keys else [()]
    return tuple(
        ParameterTrial(
            id=f"{id_prefix}-{index:03d}",
            parameters={
                **dict(base_parameters or {}),
                **dict(zip(keys, values, strict=True)),
            },
            tags=("grid",),
        )
        for index, values in enumerate(combinations, start=1)
    )


__all__ = ["expand_parameter_grid"]
