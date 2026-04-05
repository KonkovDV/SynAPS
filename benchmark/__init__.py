"""Public benchmark helpers for SynAPS.

Keep imports lazy so ``python -m benchmark.generate_instances`` does not trigger
``runpy`` warnings by importing the target module through package initialisation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
	"GenerationSpec",
	"generate_problem",
	"load_problem",
	"preset_spec",
	"run_benchmark",
	"study_routing_boundary",
	"study_solver_scaling",
	"write_problem_instance",
]

if TYPE_CHECKING:
	from .generate_instances import (
		GenerationSpec,
		generate_problem,
		preset_spec,
		write_problem_instance,
	)
	from .run_benchmark import load_problem, run_benchmark
	from .study_routing_boundary import study_routing_boundary
	from .study_solver_scaling import study_solver_scaling


def __getattr__(name: str) -> Any:
	if name in {"GenerationSpec", "generate_problem", "preset_spec", "write_problem_instance"}:
		from . import generate_instances as _generate_instances

		return getattr(_generate_instances, name)
	if name in {"load_problem", "run_benchmark"}:
		from . import run_benchmark as _run_benchmark

		return getattr(_run_benchmark, name)
	if name == "study_routing_boundary":
		from . import study_routing_boundary as _study_routing_boundary

		return _study_routing_boundary.study_routing_boundary
	if name == "study_solver_scaling":
		from . import study_solver_scaling as _study_solver_scaling

		return _study_solver_scaling.study_solver_scaling
	raise AttributeError(f"module 'benchmark' has no attribute {name!r}")
