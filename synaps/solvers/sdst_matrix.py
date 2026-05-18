"""Compressed SDST matrix — NumPy-backed O(1) lookup for large-scale solvers.

Replaces Python dict[tuple[UUID, UUID, UUID], int] with flat NumPy arrays for
cache-friendly iteration during ALNS destroy/repair scoring.

Reference: Compressed Sparse Row (CSR) concept adapted for 3-key SDST.
Academic basis: Data-Oriented Design for scheduling hot-paths (Matsuzaki et al., 2024).

Backend Decision Matrix
-----------------------

| Backend          | Best for                       | Lookup complexity   |
|------------------|--------------------------------|---------------------|
| dense_numpy      | small/dense state spaces       | O(1)                |
| csr_python       | large sparse matrices          | O(log row nnz)      |
| csr_native       | hot random sparse + native ext | amortized O(1)      |

Current implementation: dense_numpy (default and only backend).
Future backends (csr_python, csr_native) will be added when memory
constraints require sparse representation for very large state spaces.

Selection heuristic (used by ``from_problem``):
- density >= 0.3 or n_states <= 50  → dense_numpy
- density < 0.3 and n_states > 50   → csr_python (future)
- native module available + sparse   → csr_native (future)

All backends expose a consistent interface:
- ``get_setup(wc, from_state, to_state) -> float`` — returns 0.0 for unknown triples
- ``memory_bytes() -> int`` — total memory footprint
- ``sdst_backend: str`` — identifies the active backend
- ``sdst_memory_bytes: int`` — memory footprint (property alias)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import ScheduleProblem


class SdstMatrix:
    """Flat NumPy representation of the SDST setup-time graph.

    Keyed by (work_center_index, from_state_index, to_state_index).
    All lookups are O(1) via direct numpy indexing.

    Attributes:
        setup_minutes: 3D array [n_wc, n_states, n_states] of int32.
        material_loss: 3D array [n_wc, n_states, n_states] of float32.
        energy_kwh: 3D array [n_wc, n_states, n_states] of float32.
        wc_id_to_idx: mapping from UUID → int index.
        state_id_to_idx: mapping from UUID → int index.
        idx_to_wc_id: reverse mapping int → UUID.
        idx_to_state_id: reverse mapping int → UUID.
    """

    __slots__ = (
        "energy_kwh",
        "idx_to_state_id",
        "idx_to_wc_id",
        "material_loss",
        "n_states",
        "n_wc",
        "sdst_backend",
        "setup_minutes",
        "state_id_to_idx",
        "wc_id_to_idx",
    )

    def __init__(
        self,
        setup_minutes: np.ndarray,
        material_loss: np.ndarray,
        energy_kwh: np.ndarray,
        wc_id_to_idx: dict[UUID, int],
        state_id_to_idx: dict[UUID, int],
        sdst_backend: str = "dense_numpy",
    ) -> None:
        self.setup_minutes = setup_minutes
        self.material_loss = material_loss
        self.energy_kwh = energy_kwh
        self.wc_id_to_idx = wc_id_to_idx
        self.state_id_to_idx = state_id_to_idx
        self.idx_to_wc_id = {v: k for k, v in wc_id_to_idx.items()}
        self.idx_to_state_id = {v: k for k, v in state_id_to_idx.items()}
        self.n_wc = len(wc_id_to_idx)
        self.n_states = len(state_id_to_idx)
        self.sdst_backend = sdst_backend

    @property
    def sdst_memory_bytes(self) -> int:
        """Memory footprint of the numpy arrays (property alias for metadata)."""
        return self.memory_bytes()

    @classmethod
    def from_problem(cls, problem: ScheduleProblem) -> SdstMatrix:
        """Build compressed matrix from a ScheduleProblem.

        Auto-selects backend based on measured density and size:
        - Currently always selects dense_numpy (only implemented backend).
        - Future: when density < 0.3 and n_states > 50, will select csr_python
          or csr_native if the native module is available.
        """
        wc_id_to_idx: dict[UUID, int] = {wc.id: i for i, wc in enumerate(problem.work_centers)}
        state_id_to_idx: dict[UUID, int] = {s.id: i for i, s in enumerate(problem.states)}
        n_wc = len(wc_id_to_idx)
        n_states = len(state_id_to_idx)

        setup_minutes = np.zeros((n_wc, n_states, n_states), dtype=np.int32)
        material_loss = np.zeros((n_wc, n_states, n_states), dtype=np.float32)
        energy_kwh = np.zeros((n_wc, n_states, n_states), dtype=np.float32)

        for entry in problem.setup_matrix:
            wi = wc_id_to_idx.get(entry.work_center_id)
            fi = state_id_to_idx.get(entry.from_state_id)
            ti = state_id_to_idx.get(entry.to_state_id)
            if wi is None or fi is None or ti is None:
                continue
            setup_minutes[wi, fi, ti] = entry.setup_minutes
            material_loss[wi, fi, ti] = entry.material_loss
            energy_kwh[wi, fi, ti] = entry.energy_kwh

        # Backend auto-selection (future expansion point):
        # max_possible_entries = n_wc * n_states * (n_states - 1)
        # actual_entries = len(problem.setup_matrix)
        # density = actual_entries / max(max_possible_entries, 1)
        # if density < 0.3 and n_states > 50: select csr_python or csr_native
        backend = "dense_numpy"

        return cls(
            setup_minutes=setup_minutes,
            material_loss=material_loss,
            energy_kwh=energy_kwh,
            wc_id_to_idx=wc_id_to_idx,
            state_id_to_idx=state_id_to_idx,
            sdst_backend=backend,
        )

    def get_setup(self, wc_id: UUID, from_state: UUID, to_state: UUID) -> float:
        """O(1) setup-time lookup. Returns 0.0 for unknown triples.

        Interface contract: all backends return float. Unknown (wc, from_state,
        to_state) triples — including completely unknown UUIDs — return 0.0
        consistently (never KeyError, never NaN).
        """
        wi = self.wc_id_to_idx.get(wc_id)
        fi = self.state_id_to_idx.get(from_state)
        ti = self.state_id_to_idx.get(to_state)
        if wi is None or fi is None or ti is None:
            return 0.0
        return float(self.setup_minutes[wi, fi, ti])

    def get_material_loss(self, wc_id: UUID, from_state: UUID, to_state: UUID) -> float:
        """O(1) material-loss lookup."""
        wi = self.wc_id_to_idx.get(wc_id)
        fi = self.state_id_to_idx.get(from_state)
        ti = self.state_id_to_idx.get(to_state)
        if wi is None or fi is None or ti is None:
            return 0.0
        return float(self.material_loss[wi, fi, ti])

    def total_setup_for_sequence(
        self,
        wc_id: UUID,
        state_sequence: list[UUID],
    ) -> int:
        """Compute total setup time for a sequence of states on one machine."""
        wi = self.wc_id_to_idx.get(wc_id)
        if wi is None or len(state_sequence) < 2:
            return 0
        total = 0
        mat = self.setup_minutes[wi]
        for k in range(len(state_sequence) - 1):
            fi = self.state_id_to_idx.get(state_sequence[k])
            ti = self.state_id_to_idx.get(state_sequence[k + 1])
            if fi is not None and ti is not None:
                total += int(mat[fi, ti])
        return total

    def vectorized_setup_row(
        self,
        wc_id: UUID,
        from_state: UUID,
    ) -> np.ndarray:
        """Return the full row of setup times from a given state on a machine.

        Useful for ALNS scoring: evaluate all possible next-states in one shot.
        Returns: int32 array of shape (n_states,).
        """
        wi = self.wc_id_to_idx.get(wc_id)
        fi = self.state_id_to_idx.get(from_state)
        if wi is None or fi is None:
            return np.zeros(self.n_states, dtype=np.int32)
        return cast("np.ndarray", self.setup_minutes[wi, fi])

    def memory_bytes(self) -> int:
        """Total memory footprint of the numpy arrays."""
        return self.setup_minutes.nbytes + self.material_loss.nbytes + self.energy_kwh.nbytes

    def get_setup_batch(
        self,
        wc_indices: np.ndarray,
        from_state_indices: np.ndarray,
        to_state_indices: np.ndarray,
    ) -> np.ndarray:
        """Batch lookup — uses native when available, falls back to numpy indexing.

        Args:
            wc_indices: int array of work center indices
            from_state_indices: int array of from-state indices
            to_state_indices: int array of to-state indices

        Returns:
            float64 array of setup_minutes values. Out-of-bounds indices produce 0.0.
        """
        from synaps.accelerators import native_sdst_batch_lookup

        wc_arr = np.asarray(wc_indices, dtype=np.int64)
        from_arr = np.asarray(from_state_indices, dtype=np.int64)
        to_arr = np.asarray(to_state_indices, dtype=np.int64)

        # Try native batch path
        native_result = native_sdst_batch_lookup(
            self.setup_minutes.astype(np.float64),
            self.n_wc,
            self.n_states,
            wc_arr,
            from_arr,
            to_arr,
        )
        if native_result is not None:
            return native_result

        # Python fallback: numpy fancy indexing with bounds clamping
        n = len(wc_arr)
        result = np.zeros(n, dtype=np.float64)

        # Mask valid indices
        valid = (
            (wc_arr >= 0)
            & (wc_arr < self.n_wc)
            & (from_arr >= 0)
            & (from_arr < self.n_states)
            & (to_arr >= 0)
            & (to_arr < self.n_states)
        )

        if valid.any():
            result[valid] = self.setup_minutes[
                wc_arr[valid], from_arr[valid], to_arr[valid]
            ].astype(np.float64)

        return result
