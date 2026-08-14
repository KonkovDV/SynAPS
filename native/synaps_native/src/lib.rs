mod cpu;

use numpy::{PyArray1, PyArrayMethods, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

use cpu::{prefetch_f64_at, prefetch_i64_at, prefetch_rhc_soa, PREFETCH_DISTANCE};

// ---------------------------------------------------------------------------
// Fast approximate exp (Schraudolph 1999, IEEE-754 bit trick).
// Max relative error ≈ 4% — acceptable for scheduling pressure heuristics
// where ranking throughput matters more than full IEEE precision.
//
// The bit-trick reconstruction relies on little-endian IEEE-754 layout.
// On non-little-endian targets, we fall back to exact exp() to preserve
// correctness instead of emitting a silently wrong approximation.
// ---------------------------------------------------------------------------

#[inline(always)]
fn fast_exp(x: f64) -> f64 {
    fast_exp_impl(x.clamp(-700.0, 700.0))
}

#[cfg(target_endian = "little")]
#[inline(always)]
fn fast_exp_impl(x: f64) -> f64 {
    let a = 1048576.0 / core::f64::consts::LN_2; // 2^20 / ln(2)
    let b = 1072693248.0 - 60801.0; // bias correction (Schraudolph constant)
    let scaled = a * x + b;
    let quantized = scaled as i64;
    let bits = quantized << 32;
    let approx = f64::from_bits(bits as u64);

    // The Schraudolph bit trick is piecewise constant inside each quantization
    // bucket. Re-introduce the sub-bucket slope with a tiny residual-domain
    // polynomial so close candidate pressures stay strictly ordered.
    let quantized_x = ((quantized as f64) - b) / a;
    let residual = x - quantized_x;
    approx * (1.0 + residual * (1.0 + 0.5 * residual))
}

#[cfg(not(target_endian = "little"))]
#[inline(always)]
fn fast_exp_impl(x: f64) -> f64 {
    x.exp()
}

// ---------------------------------------------------------------------------
// Wrapper to send raw pointer across thread boundary.
// SAFETY: caller must guarantee disjoint-index writes and that the backing
// buffer outlives the rayon region. This establishes memory safety only; it
// does not eliminate cache-line contention or other performance effects.
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
struct SendPtr(*mut f64);
unsafe impl Send for SendPtr {}
unsafe impl Sync for SendPtr {}

impl SendPtr {
    /// Write value at index. SAFETY: caller must ensure disjoint-index access.
    #[inline(always)]
    unsafe fn write_at(self, i: usize, val: f64) {
        *self.0.add(i) = val;
    }
}

/// Minimum rayon chunk size for lightweight per-element kernels.
/// Tuned for hybrid P-core/E-core architectures (Intel 12th–14th Gen Raptor Lake):
/// small chunks (256) enable aggressive work-stealing so fast P-cores (5.1 GHz)
/// compensate for slower E-cores (~3.9 GHz), avoiding the "straggler" effect.
/// See: Blumofe & Leiserson 1999, rayon `with_min_len` guidance.
const RAYON_MIN_CHUNK: usize = 256;

fn build_successor_index(predecessor_ids: &[i64]) -> PyResult<(Vec<usize>, Vec<usize>)> {
    let op_count = predecessor_ids.len();
    let mut successor_offsets = vec![0usize; op_count + 1];

    for &predecessor_idx in predecessor_ids {
        if predecessor_idx < 0 {
            continue;
        }

        let predecessor_idx = predecessor_idx as usize;
        if predecessor_idx >= op_count {
            return Err(PyValueError::new_err(
                "predecessor index is out of range",
            ));
        }

        successor_offsets[predecessor_idx + 1] += 1;
    }

    for idx in 0..op_count {
        successor_offsets[idx + 1] += successor_offsets[idx];
    }

    let mut write_positions = successor_offsets[..op_count].to_vec();
    let mut successor_indices = vec![0usize; successor_offsets[op_count]];

    for (child_idx, &predecessor_idx) in predecessor_ids.iter().enumerate() {
        if predecessor_idx < 0 {
            continue;
        }

        let predecessor_idx = predecessor_idx as usize;
        let slot = write_positions[predecessor_idx];
        successor_indices[slot] = child_idx;
        write_positions[predecessor_idx] += 1;
    }

    Ok((successor_offsets, successor_indices))
}

#[pyclass]
struct SynApsEngine {
    machine_count: usize,
    avg_total_p: f64,
    predecessor_ids: Vec<i64>,
    base_durations: Vec<f64>,
    order_weights: Vec<f64>,
    p_tilde_minutes: Vec<f64>,
    successor_offsets: Vec<usize>,
    successor_indices: Vec<usize>,
}

#[pymethods]
impl SynApsEngine {
    #[new]
    fn new(machine_count: usize, avg_total_p: f64) -> Self {
        Self {
            machine_count,
            avg_total_p,
            predecessor_ids: Vec::new(),
            base_durations: Vec::new(),
            order_weights: Vec::new(),
            p_tilde_minutes: Vec::new(),
            successor_offsets: vec![0],
            successor_indices: Vec::new(),
        }
    }

    #[getter]
    fn machine_count(&self) -> usize {
        self.machine_count
    }

    #[getter]
    fn avg_total_p(&self) -> f64 {
        self.avg_total_p
    }

    fn graph_loaded(&self) -> bool {
        !self.predecessor_ids.is_empty()
    }

    fn operation_count(&self) -> usize {
        self.predecessor_ids.len()
    }

    fn successor_edge_count(&self) -> usize {
        self.successor_indices.len()
    }

    fn clear_graph(&mut self) {
        self.predecessor_ids.clear();
        self.base_durations.clear();
        self.order_weights.clear();
        self.p_tilde_minutes.clear();
        self.successor_offsets.clear();
        self.successor_offsets.push(0);
        self.successor_indices.clear();
    }

    fn load_graph(
        &mut self,
        py: Python<'_>,
        predecessor_ids: PyReadonlyArray1<'_, i64>,
        base_durations: PyReadonlyArray1<'_, f64>,
        order_weights: PyReadonlyArray1<'_, f64>,
        p_tilde_minutes: PyReadonlyArray1<'_, f64>,
    ) -> PyResult<()> {
        let predecessor_ids = predecessor_ids.as_slice()?.to_vec();
        let base_durations = base_durations.as_slice()?.to_vec();
        let order_weights = order_weights.as_slice()?.to_vec();
        let p_tilde_minutes = p_tilde_minutes.as_slice()?.to_vec();

        let op_count = predecessor_ids.len();
        if base_durations.len() != op_count
            || order_weights.len() != op_count
            || p_tilde_minutes.len() != op_count
        {
            return Err(PyValueError::new_err(
                "SynApsEngine graph vectors must have identical lengths",
            ));
        }

        let (successor_offsets, successor_indices) =
            py.allow_threads(|| build_successor_index(&predecessor_ids))?;

        self.predecessor_ids = predecessor_ids;
        self.base_durations = base_durations;
        self.order_weights = order_weights;
        self.p_tilde_minutes = p_tilde_minutes;
        self.successor_offsets = successor_offsets;
        self.successor_indices = successor_indices;

        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Scalar ATCS — unchanged interface (single-operation scoring).
// ---------------------------------------------------------------------------

#[pyfunction]
fn compute_atcs_log_score(
    weight: f64,
    processing_minutes: f64,
    slack: f64,
    ready_p_bar: f64,
    setup_minutes: f64,
    setup_scale: f64,
    k1: f64,
    k2: f64,
    material_loss: f64,
    material_scale: f64,
    k3: f64,
) -> f64 {
    let safe_weight = weight.max(1e-9);
    let safe_processing = processing_minutes.max(0.1);
    let safe_ready_p_bar = ready_p_bar.max(1e-9);

    let setup_penalty = if setup_minutes > 0.0 {
        setup_minutes / (k2 * setup_scale)
    } else {
        0.0
    };

    let material_penalty = if material_loss > 0.0 {
        material_loss / (k3 * material_scale)
    } else {
        0.0
    };

    safe_weight.ln() - safe_processing.ln() - (slack / (k1 * safe_ready_p_bar))
        - setup_penalty
        - material_penalty
}

// ---------------------------------------------------------------------------
// Batch ATCS — Vec interface kept for backward compatibility.
// ---------------------------------------------------------------------------

#[pyfunction]
fn compute_atcs_log_scores_batch(
    py: Python<'_>,
    weights: Vec<f64>,
    processing_minutes: Vec<f64>,
    slack: Vec<f64>,
    ready_p_bar: f64,
    setup_minutes: Vec<f64>,
    setup_scale: Vec<f64>,
    k1: f64,
    k2: f64,
    material_loss: Vec<f64>,
    material_scale: f64,
    k3: f64,
) -> PyResult<Vec<f64>> {
    let n = weights.len();
    if processing_minutes.len() != n
        || slack.len() != n
        || setup_minutes.len() != n
        || setup_scale.len() != n
        || material_loss.len() != n
    {
        return Err(PyValueError::new_err(
            "ATCS batch vectors must have identical lengths",
        ));
    }

    let scores = py.allow_threads(|| {
        (0..n)
            .into_par_iter()
            .with_min_len(RAYON_MIN_CHUNK)
            .map(|i| {
                let safe_weight = weights[i].max(1e-9);
                let safe_processing = processing_minutes[i].max(0.1);
                let safe_ready_p_bar = ready_p_bar.max(1e-9);

                let setup_penalty = if setup_minutes[i] > 0.0 {
                    setup_minutes[i] / (k2 * setup_scale[i])
                } else {
                    0.0
                };

                let material_penalty = if material_loss[i] > 0.0 {
                    material_loss[i] / (k3 * material_scale)
                } else {
                    0.0
                };

                safe_weight.ln()
                    - safe_processing.ln()
                    - (slack[i] / (k1 * safe_ready_p_bar))
                    - setup_penalty
                    - material_penalty
            })
            .collect::<Vec<f64>>()
    });

    Ok(scores)
}

// ---------------------------------------------------------------------------
// Resource capacity feasibility — unchanged interface.
// ---------------------------------------------------------------------------

#[pyfunction]
fn resource_capacity_window_is_feasible(
    window_starts: Vec<f64>,
    window_ends: Vec<f64>,
    window_quantities: Vec<i64>,
    candidate_start: f64,
    candidate_end: f64,
    requested_quantity: i64,
    pool_size: i64,
) -> PyResult<bool> {
    let n = window_starts.len();
    if window_ends.len() != n || window_quantities.len() != n {
        return Err(PyValueError::new_err(
            "resource window vectors must have identical lengths",
        ));
    }

    let mut active_demand: i64 = 0;
    let mut events: Vec<(f64, i64)> = Vec::new();

    for i in 0..n {
        let other_start = window_starts[i];
        let other_end = window_ends[i];
        let quantity = window_quantities[i];

        if other_start >= candidate_end || other_end <= candidate_start {
            continue;
        }

        if other_start <= candidate_start && candidate_start < other_end {
            active_demand += quantity;
        } else {
            events.push((other_start, quantity));
        }

        if candidate_start < other_end && other_end < candidate_end {
            events.push((other_end, -quantity));
        }
    }

    if active_demand + requested_quantity > pool_size {
        return Ok(false);
    }

    events.sort_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                let left_prio = if left.1 < 0 { 0 } else { 1 };
                let right_prio = if right.1 < 0 { 0 } else { 1 };
                left_prio.cmp(&right_prio)
            })
    });

    for (_, delta) in events {
        active_demand += delta;
        if active_demand + requested_quantity > pool_size {
            return Ok(false);
        }
    }

    Ok(true)
}

// ---------------------------------------------------------------------------
// Shared per-element RHC kernel used by both Vec and numpy paths.
// ---------------------------------------------------------------------------

#[inline(always)]
fn rhc_element_csr(
    i: usize,
    offsets: &[i64],
    indices: &[i64],
    mao: &[f64],
    machine_count: usize,
    peo: &[f64],
    d_off: &[f64],
    rpt: &[f64],
    ow: &[f64],
    ptm: &[f64],
    safe_pressure_denominator: f64,
    due_pressure_overdue_boost: f64,
) -> (f64, f64) {
    let row_start = offsets[i] as usize;
    let row_end = offsets[i + 1] as usize;

    let earliest_machine_ready = if row_start == row_end {
        0.0
    } else {
        let mut min_val = f64::INFINITY;
        for k in row_start..row_end {
            // Irregular mao[] gather: hardware stride prefetch cannot follow CSR.
            if k + PREFETCH_DISTANCE < row_end {
                let ahead = indices[k + PREFETCH_DISTANCE] as usize;
                prefetch_f64_at(mao, ahead);
            }
            let idx = indices[k] as usize;
            if idx < machine_count {
                let val = unsafe { *mao.get_unchecked(idx) };
                if val < min_val {
                    min_val = val;
                }
            }
        }
        min_val
    };

    let est_offset = peo[i].max(earliest_machine_ready);
    let slack = d_off[i] - (est_offset + rpt[i]);

    let pressure =
        (ow[i] / ptm[i].max(1e-6)) * fast_exp(-slack.max(0.0) / safe_pressure_denominator);

    // Branchless overdue boost: eliminates ~15-20 cycle branch misprediction
    // penalty on hybrid P/E architectures where slack sign is ~50/50 random.
    // Compiles to a single cmov/blend — no pipeline flush.
    let overdue = (slack <= 0.0) as u8 as f64;
    let pressure = pressure * (1.0 + overdue * (due_pressure_overdue_boost - 1.0));

    (slack, pressure)
}

#[inline(always)]
fn score_rhc_element(
    i: usize,
    n: usize,
    offsets: &[i64],
    indices: &[i64],
    mao: &[f64],
    machine_count: usize,
    peo: &[f64],
    d_off: &[f64],
    rpt: &[f64],
    ow: &[f64],
    ptm: &[f64],
    safe_pressure_denominator: f64,
    due_pressure_overdue_boost: f64,
) -> (f64, f64) {
    prefetch_rhc_soa(i, n, peo, d_off, rpt, ow, ptm, offsets);
    rhc_element_csr(
        i,
        offsets,
        indices,
        mao,
        machine_count,
        peo,
        d_off,
        rpt,
        ow,
        ptm,
        safe_pressure_denominator,
        due_pressure_overdue_boost,
    )
}

// ---------------------------------------------------------------------------
// Legacy Vec<Vec<usize>> interface — kept for backward compatibility.
// Now internally converts to CSR and uses the shared kernel + with_min_len.
// ---------------------------------------------------------------------------

#[pyfunction]
fn compute_rhc_candidate_metrics_batch(
    py: Python<'_>,
    machine_available_offsets: Vec<f64>,
    eligible_machine_indices: Vec<Vec<usize>>,
    predecessor_end_offsets: Vec<f64>,
    due_offsets: Vec<f64>,
    rpt_tail_minutes: Vec<f64>,
    order_weights: Vec<f64>,
    p_tilde_minutes: Vec<f64>,
    avg_total_p: f64,
    due_pressure_k1: f64,
    due_pressure_overdue_boost: f64,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let n = eligible_machine_indices.len();
    if predecessor_end_offsets.len() != n
        || due_offsets.len() != n
        || rpt_tail_minutes.len() != n
        || order_weights.len() != n
        || p_tilde_minutes.len() != n
    {
        return Err(PyValueError::new_err(
            "RHC candidate metric vectors must have identical lengths",
        ));
    }

    let machine_count = machine_available_offsets.len();

    // Build CSR in Rust — single pass, two allocations.
    let mut csr_offsets: Vec<i64> = Vec::with_capacity(n + 1);
    let mut csr_indices: Vec<i64> = Vec::new();
    csr_offsets.push(0);
    for machine_indices in &eligible_machine_indices {
        for &machine_idx in machine_indices {
            if machine_idx >= machine_count {
                return Err(PyValueError::new_err(
                    "eligible machine index is out of range",
                ));
            }
            csr_indices.push(machine_idx as i64);
        }
        csr_offsets.push(csr_indices.len() as i64);
    }

    let safe_pressure_denominator = (due_pressure_k1 * avg_total_p).max(1e-6);

    let mut slacks = vec![0.0f64; n];
    let mut pressures = vec![0.0f64; n];

    py.allow_threads(|| {
        let s_ptr = SendPtr(slacks.as_mut_ptr());
        let p_ptr = SendPtr(pressures.as_mut_ptr());

        (0..n)
            .into_par_iter()
            .with_min_len(RAYON_MIN_CHUNK)
            .for_each(|i| {
                let (slack, pressure) = score_rhc_element(
                    i,
                    n,
                    &csr_offsets,
                    &csr_indices,
                    &machine_available_offsets,
                    machine_count,
                    &predecessor_end_offsets,
                    &due_offsets,
                    &rpt_tail_minutes,
                    &order_weights,
                    &p_tilde_minutes,
                    safe_pressure_denominator,
                    due_pressure_overdue_boost,
                );
                // SAFETY: each rayon task writes to a unique index i — no data races.
                unsafe {
                    s_ptr.write_at(i, slack);
                    p_ptr.write_at(i, pressure);
                }
            });
    });

    Ok((slacks, pressures))
}

// ---------------------------------------------------------------------------
// Zero-copy numpy + CSR interface for 50k+ scale.
//
// P1 fix: writes directly into pre-allocated numpy arrays — eliminates 3
// intermediate Vec allocations + Zip copy from the previous implementation.
//
// P2 fix: rayon with_min_len(1024) — amortizes scheduler overhead for
// lightweight per-element kernels.
//
// Accepts EITHER pre-built CSR numpy arrays (from Python _build_csr_from_jagged)
// OR the new _jagged variant below builds CSR in Rust (P3 fix).
// ---------------------------------------------------------------------------

#[pyfunction]
fn compute_rhc_candidate_metrics_batch_np<'py>(
    py: Python<'py>,
    machine_available_offsets: PyReadonlyArray1<'py, f64>,
    emi_offsets: PyReadonlyArray1<'py, i64>,
    emi_indices: PyReadonlyArray1<'py, i64>,
    predecessor_end_offsets: PyReadonlyArray1<'py, f64>,
    due_offsets: PyReadonlyArray1<'py, f64>,
    rpt_tail_minutes: PyReadonlyArray1<'py, f64>,
    order_weights: PyReadonlyArray1<'py, f64>,
    p_tilde_minutes: PyReadonlyArray1<'py, f64>,
    avg_total_p: f64,
    due_pressure_k1: f64,
    due_pressure_overdue_boost: f64,
) -> PyResult<(Py<PyArray1<f64>>, Py<PyArray1<f64>>)> {
    let mao = machine_available_offsets.as_array();
    let offsets = emi_offsets.as_array();
    let indices = emi_indices.as_array();
    let peo = predecessor_end_offsets.as_array();
    let d_off = due_offsets.as_array();
    let rpt = rpt_tail_minutes.as_array();
    let ow = order_weights.as_array();
    let ptm = p_tilde_minutes.as_array();

    let n = peo.len();
    if offsets.len() != n + 1 {
        return Err(PyValueError::new_err("emi_offsets length must be N+1"));
    }
    if d_off.len() != n || rpt.len() != n || ow.len() != n || ptm.len() != n {
        return Err(PyValueError::new_err(
            "RHC candidate metric vectors must have identical lengths",
        ));
    }

    let machine_count = mao.len();
    let offsets_raw = offsets.as_slice().unwrap();
    let indices_raw = indices.as_slice().unwrap();
    let mao_raw = mao.as_slice().unwrap();
    let peo_raw = peo.as_slice().unwrap();
    let d_off_raw = d_off.as_slice().unwrap();
    let rpt_raw = rpt.as_slice().unwrap();
    let ow_raw = ow.as_slice().unwrap();
    let ptm_raw = ptm.as_slice().unwrap();

    let safe_pressure_denominator = (due_pressure_k1 * avg_total_p).max(1e-6);

    // P1: Pre-allocate output arrays while GIL is held. numpy memory is
    // GC-pinned for the duration of allow_threads — safe to write via raw ptr.
    let out_slacks = PyArray1::<f64>::zeros(py, n, false);
    let out_pressures = PyArray1::<f64>::zeros(py, n, false);

    let s_ptr = SendPtr(unsafe { out_slacks.as_slice_mut().unwrap().as_mut_ptr() });
    let p_ptr = SendPtr(unsafe { out_pressures.as_slice_mut().unwrap().as_mut_ptr() });

    // Release GIL while running data-parallel scoring.
    // SAFETY: each rayon task writes to a unique index i — no data races.
    // Output pointers are stable: numpy buffers are not moved while GIL is released.
    py.allow_threads(|| {
        (0..n)
            .into_par_iter()
            .with_min_len(RAYON_MIN_CHUNK)
            .for_each(|i| {
                let (slack, pressure) = score_rhc_element(
                    i,
                    n,
                    offsets_raw,
                    indices_raw,
                    mao_raw,
                    machine_count,
                    peo_raw,
                    d_off_raw,
                    rpt_raw,
                    ow_raw,
                    ptm_raw,
                    safe_pressure_denominator,
                    due_pressure_overdue_boost,
                );
                unsafe {
                    s_ptr.write_at(i, slack);
                    p_ptr.write_at(i, pressure);
                }
            });
    });

    Ok((out_slacks.into(), out_pressures.into()))
}

// ---------------------------------------------------------------------------
// P3: CSR-in-Rust variant — accepts jagged Vec<Vec<i64>> directly from Python,
// builds CSR internally (eliminates Python _build_csr_from_jagged loop).
// ---------------------------------------------------------------------------

#[pyfunction]
fn compute_rhc_candidate_metrics_batch_np_jagged<'py>(
    py: Python<'py>,
    machine_available_offsets: PyReadonlyArray1<'py, f64>,
    eligible_machine_indices: Vec<Vec<i64>>,
    predecessor_end_offsets: PyReadonlyArray1<'py, f64>,
    due_offsets: PyReadonlyArray1<'py, f64>,
    rpt_tail_minutes: PyReadonlyArray1<'py, f64>,
    order_weights: PyReadonlyArray1<'py, f64>,
    p_tilde_minutes: PyReadonlyArray1<'py, f64>,
    avg_total_p: f64,
    due_pressure_k1: f64,
    due_pressure_overdue_boost: f64,
) -> PyResult<(Py<PyArray1<f64>>, Py<PyArray1<f64>>)> {
    let mao = machine_available_offsets.as_array();
    let peo = predecessor_end_offsets.as_array();
    let d_off = due_offsets.as_array();
    let rpt = rpt_tail_minutes.as_array();
    let ow = order_weights.as_array();
    let ptm = p_tilde_minutes.as_array();

    let n = eligible_machine_indices.len();
    if peo.len() != n || d_off.len() != n || rpt.len() != n || ow.len() != n || ptm.len() != n {
        return Err(PyValueError::new_err(
            "RHC candidate metric vectors must have identical lengths",
        ));
    }

    let machine_count = mao.len();

    // Build CSR in Rust — single pass, two allocations (P3).
    let mut csr_offsets: Vec<i64> = Vec::with_capacity(n + 1);
    let mut csr_indices: Vec<i64> = Vec::new();
    csr_offsets.push(0);
    for row in &eligible_machine_indices {
        for &idx in row {
            if (idx as usize) >= machine_count {
                return Err(PyValueError::new_err(
                    "eligible machine index is out of range",
                ));
            }
            csr_indices.push(idx);
        }
        csr_offsets.push(csr_indices.len() as i64);
    }

    let mao_raw = mao.as_slice().unwrap();
    let peo_raw = peo.as_slice().unwrap();
    let d_off_raw = d_off.as_slice().unwrap();
    let rpt_raw = rpt.as_slice().unwrap();
    let ow_raw = ow.as_slice().unwrap();
    let ptm_raw = ptm.as_slice().unwrap();

    let safe_pressure_denominator = (due_pressure_k1 * avg_total_p).max(1e-6);

    let out_slacks = PyArray1::<f64>::zeros(py, n, false);
    let out_pressures = PyArray1::<f64>::zeros(py, n, false);

    let s_ptr = SendPtr(unsafe { out_slacks.as_slice_mut().unwrap().as_mut_ptr() });
    let p_ptr = SendPtr(unsafe { out_pressures.as_slice_mut().unwrap().as_mut_ptr() });

    py.allow_threads(|| {
        (0..n)
            .into_par_iter()
            .with_min_len(RAYON_MIN_CHUNK)
            .for_each(|i| {
                let (slack, pressure) = score_rhc_element(
                    i,
                    n,
                    &csr_offsets,
                    &csr_indices,
                    mao_raw,
                    machine_count,
                    peo_raw,
                    d_off_raw,
                    rpt_raw,
                    ow_raw,
                    ptm_raw,
                    safe_pressure_denominator,
                    due_pressure_overdue_boost,
                );
                unsafe {
                    s_ptr.write_at(i, slack);
                    p_ptr.write_at(i, pressure);
                }
            });
    });

    Ok((out_slacks.into(), out_pressures.into()))
}

// ---------------------------------------------------------------------------
// P4.1a: Vectorized objective evaluation for ALNS inner loop.
//
// Academic basis: Ropke & Pisinger (2006, C&OR) §4.2 — objective recomputation
// dominates ALNS runtime at scale. Moving to Rust + rayon yields 15–30x.
//
// Interface: receives flat numpy arrays (assignment-level data) + dense 3D SDST
// matrices. Returns a scalar (cost, makespan, setup, material_loss, tardiness)
// tuple — no Python object allocation in the hot path.
// ---------------------------------------------------------------------------

/// Per-machine objective kernel — runs inside rayon task.
#[inline]
fn machine_objective_kernel(
    assignment_indices: &[usize],
    end_offsets: &[f64],
    wc_idx: usize,
    state_ids: &[i64],
    sdst_setup: &[f64],      // flattened [n_wc, n_states, n_states]
    sdst_loss: &[f64],       // flattened [n_wc, n_states, n_states]
    n_states: usize,
) -> (f64, f64, f64) {
    // (makespan, setup, material_loss)
    if assignment_indices.is_empty() {
        return (0.0, 0.0, 0.0);
    }

    // Sort indices by end_offset (stable sort for determinism)
    let mut sorted_indices: Vec<usize> = assignment_indices.to_vec();
    sorted_indices.sort_by(|&a, &b| end_offsets[a].total_cmp(&end_offsets[b]));

    let makespan = end_offsets[sorted_indices[sorted_indices.len() - 1]];
    let mut setup = 0.0;
    let mut loss = 0.0;

    let wc_offset = wc_idx * n_states * n_states;

    for pair in sorted_indices.windows(2) {
        let prev_state = state_ids[pair[0]];
        let curr_state = state_ids[pair[1]];
        if prev_state >= 0 && curr_state >= 0 {
            let ps = prev_state as usize;
            let cs = curr_state as usize;
            if ps < n_states && cs < n_states {
                let idx = wc_offset + ps * n_states + cs;
                setup += sdst_setup[idx];
                loss += sdst_loss[idx];
            }
        }
    }

    (makespan, setup, loss)
}

#[pyfunction]
fn evaluate_objective_batch<'py>(
    py: Python<'py>,
    // Per-assignment arrays (N assignments)
    end_offsets: PyReadonlyArray1<'py, f64>,
    wc_indices: PyReadonlyArray1<'py, i64>,
    state_ids: PyReadonlyArray1<'py, i64>,
    order_indices: PyReadonlyArray1<'py, i64>,
    // Dense SDST matrices flattened to 1D: [n_wc * n_states * n_states]
    sdst_setup_flat: PyReadonlyArray1<'py, f64>,
    sdst_loss_flat: PyReadonlyArray1<'py, f64>,
    n_wc: usize,
    n_states: usize,
    // Order due offsets (M orders)
    order_due_offsets: PyReadonlyArray1<'py, f64>,
    // Objective weights
    w_makespan: f64,
    w_setup: f64,
    w_loss: f64,
    w_tardiness: f64,
) -> PyResult<(f64, f64, f64, f64, f64)> {
    let eo = end_offsets.as_slice()?;
    let wc = wc_indices.as_slice()?;
    let si = state_ids.as_slice()?;
    let oi = order_indices.as_slice()?;
    let sdst_s = sdst_setup_flat.as_slice()?;
    let sdst_l = sdst_loss_flat.as_slice()?;
    let odo = order_due_offsets.as_slice()?;

    let n = eo.len();
    if wc.len() != n || si.len() != n || oi.len() != n {
        return Err(PyValueError::new_err(
            "evaluate_objective_batch: all per-assignment arrays must have identical lengths",
        ));
    }
    let expected_sdst_len = n_wc * n_states * n_states;
    if sdst_s.len() != expected_sdst_len || sdst_l.len() != expected_sdst_len {
        return Err(PyValueError::new_err(
            "evaluate_objective_batch: SDST flat arrays must have length n_wc * n_states * n_states",
        ));
    }

    // Group assignment indices by machine
    let mut by_machine: Vec<Vec<usize>> = vec![Vec::new(); n_wc];
    for i in 0..n {
        let machine = wc[i] as usize;
        if machine < n_wc {
            by_machine[machine].push(i);
        }
    }

    // Parallel per-machine evaluation
    let machine_results: Vec<(f64, f64, f64)> = py.allow_threads(|| {
        by_machine
            .par_iter()
            .enumerate()
            .map(|(wc_idx, indices)| {
                machine_objective_kernel(indices, eo, wc_idx, si, sdst_s, sdst_l, n_states)
            })
            .collect()
    });

    // Aggregate
    let mut total_makespan = 0.0f64;
    let mut total_setup = 0.0f64;
    let mut total_loss = 0.0f64;
    for &(ms, su, lo) in &machine_results {
        if ms > total_makespan {
            total_makespan = ms;
        }
        total_setup += su;
        total_loss += lo;
    }

    // Tardiness: max completion per order
    let n_orders = odo.len();
    let mut order_completion = vec![0.0f64; n_orders];
    for i in 0..n {
        let order_idx = oi[i] as usize;
        if order_idx < n_orders && eo[i] > order_completion[order_idx] {
            order_completion[order_idx] = eo[i];
        }
    }
    let mut total_tardiness = 0.0f64;
    for j in 0..n_orders {
        let tard = order_completion[j] - odo[j];
        if tard > 0.0 {
            total_tardiness += tard;
        }
    }

    let cost = w_makespan * total_makespan
        + w_setup * total_setup
        + w_loss * total_loss
        + w_tardiness * total_tardiness;

    Ok((cost, total_makespan, total_setup, total_loss, total_tardiness))
}

// ---------------------------------------------------------------------------
// P4.1c: Vectorized temporal stabilization (precedence + machine repair).
//
// Kahn's topological sort + forward-only shift passes on flat numpy arrays.
// In-place mutation of start_offsets/end_offsets — zero-copy writeback.
// ---------------------------------------------------------------------------

#[pyfunction]
fn stabilize_temporal_batch<'py>(
    py: Python<'py>,
    start_offsets: &Bound<'py, PyArray1<f64>>,
    end_offsets: &Bound<'py, PyArray1<f64>>,
    wc_indices: PyReadonlyArray1<'py, i64>,
    state_ids: PyReadonlyArray1<'py, i64>,
    predecessor_ids: PyReadonlyArray1<'py, i64>, // -1 = no predecessor
    sdst_setup_flat: PyReadonlyArray1<'py, f64>,
    n_wc: usize,
    n_states: usize,
    max_passes: i32,
) -> PyResult<(i32, i32, i32)> {
    let wc = wc_indices.as_slice()?;
    let si = state_ids.as_slice()?;
    let pred = predecessor_ids.as_slice()?;
    let sdst_s = sdst_setup_flat.as_slice()?;

    let so = unsafe { start_offsets.as_slice_mut()? };
    let eo = unsafe { end_offsets.as_slice_mut()? };

    let n = so.len();
    if eo.len() != n || wc.len() != n || si.len() != n || pred.len() != n {
        return Err(PyValueError::new_err(
            "stabilize_temporal_batch: all arrays must have identical lengths",
        ));
    }

    // Kahn's topological sort
    let mut indegree = vec![0i32; n];
    let mut successors: Vec<Vec<usize>> = vec![Vec::new(); n];
    for i in 0..n {
        if pred[i] >= 0 {
            let p = pred[i] as usize;
            if p < n {
                indegree[i] += 1;
                successors[p].push(i);
            }
        }
    }

    let mut topo_order: Vec<usize> = Vec::with_capacity(n);
    let mut queue: std::collections::VecDeque<usize> = std::collections::VecDeque::new();
    for i in 0..n {
        if indegree[i] == 0 {
            queue.push_back(i);
        }
    }
    while let Some(node) = queue.pop_front() {
        topo_order.push(node);
        for &succ in &successors[node] {
            indegree[succ] -= 1;
            if indegree[succ] == 0 {
                queue.push_back(succ);
            }
        }
    }
    // Add remaining (cycle-breaking fallback) — O(n) via visited bitmap.
    let mut visited = vec![false; n];
    for &node in &topo_order {
        visited[node] = true;
    }
    for i in 0..n {
        if !visited[i] {
            topo_order.push(i);
        }
    }

    let (passes, precedence_shifts, machine_shifts) = py.allow_threads(|| {
        let mut precedence_shifts: i32 = 0;
        let mut machine_shifts: i32 = 0;
        let mut passes: i32 = 0;

        for pass_idx in 0..max_passes {
            let mut changed = false;
            passes = pass_idx + 1;

            // Precedence repair
            for &i in &topo_order {
                if pred[i] < 0 {
                    continue;
                }
                let p = pred[i] as usize;
                if p >= n {
                    continue;
                }
                if so[i] < eo[p] {
                    let delta = eo[p] - so[i];
                    so[i] += delta;
                    eo[i] += delta;
                    precedence_shifts += 1;
                    changed = true;
                }
            }

            // Machine overlap repair (sort by start_offset per machine)
            let mut by_machine: Vec<Vec<usize>> = vec![Vec::new(); n_wc];
            for i in 0..n {
                let m = wc[i] as usize;
                if m < n_wc {
                    by_machine[m].push(i);
                }
            }

            for machine_indices in &mut by_machine {
                machine_indices.sort_by(|&a, &b| so[a].total_cmp(&so[b]));

                for pair in machine_indices.windows(2) {
                    let prev = pair[0];
                    let curr = pair[1];

                    let mut required_setup = 0.0;
                    let prev_state = si[prev];
                    let curr_state = si[curr];
                    let m = wc[curr] as usize;
                    if prev_state >= 0 && curr_state >= 0 && m < n_wc {
                        let ps = prev_state as usize;
                        let cs = curr_state as usize;
                        if ps < n_states && cs < n_states {
                            required_setup = sdst_s[m * n_states * n_states + ps * n_states + cs];
                        }
                    }

                    let min_start = eo[prev] + required_setup;
                    if so[curr] < min_start {
                        let delta = min_start - so[curr];
                        so[curr] += delta;
                        eo[curr] += delta;
                        machine_shifts += 1;
                        changed = true;
                    }
                }
            }

            if !changed {
                break;
            }
        }

        (passes, precedence_shifts, machine_shifts)
    });

    Ok((passes, precedence_shifts, machine_shifts))
}

// ---------------------------------------------------------------------------
// Task 11b: Native SDST Batch Lookup — dense 3D storage with vectorized batch API.
//
// Academic basis: reducing FFI overhead by batching many lookups into a single
// call. For dense state spaces (3–20 states, typical in SynAPS), the underlying
// storage is a flat Vec<f64> indexed as [wc_idx * n_states * n_states + from_idx * n_states + to_idx].
// This gives O(1) per-element lookup with excellent cache locality for sequential access.
// ---------------------------------------------------------------------------

#[pyclass]
struct NativeSdstBatchLookup {
    /// Flattened dense 3D storage: setup_values[wc_idx * n_states * n_states + from_idx * n_states + to_idx]
    setup_values: Vec<f64>,
    n_wc: usize,
    n_states: usize,
}

#[pymethods]
impl NativeSdstBatchLookup {
    /// Construct from a flat array of setup values.
    ///
    /// Args:
    ///     setup_values_flat: flattened [n_wc, n_states, n_states] array of f64
    ///     n_wc: number of work centers
    ///     n_states: number of states
    ///
    /// The flat array must have exactly n_wc * n_states * n_states elements.
    #[new]
    fn new(setup_values_flat: Vec<f64>, n_wc: usize, n_states: usize) -> PyResult<Self> {
        let expected_len = n_wc * n_states * n_states;
        if setup_values_flat.len() != expected_len {
            return Err(PyValueError::new_err(format!(
                "NativeSdstBatchLookup: setup_values_flat length {} != expected {} (n_wc={} * n_states={} * n_states={})",
                setup_values_flat.len(), expected_len, n_wc, n_states, n_states
            )));
        }
        Ok(Self {
            setup_values: setup_values_flat,
            n_wc,
            n_states,
        })
    }

    /// Single-triple lookup. Returns 0.0 for out-of-bounds indices.
    fn get_setup(&self, wc_idx: usize, from_state_idx: usize, to_state_idx: usize) -> f64 {
        if wc_idx >= self.n_wc || from_state_idx >= self.n_states || to_state_idx >= self.n_states {
            return 0.0;
        }
        let idx = wc_idx * self.n_states * self.n_states
            + from_state_idx * self.n_states
            + to_state_idx;
        self.setup_values[idx]
    }

    /// Batch lookup — accepts numpy int64 index arrays and returns a numpy float64 array.
    ///
    /// All three index arrays must have the same length N. Returns an array of N
    /// setup values. Out-of-bounds indices produce 0.0 in the corresponding output slot.
    fn get_setup_batch<'py>(
        &self,
        py: Python<'py>,
        wc_indices: PyReadonlyArray1<'py, i64>,
        from_state_indices: PyReadonlyArray1<'py, i64>,
        to_state_indices: PyReadonlyArray1<'py, i64>,
    ) -> PyResult<Py<PyArray1<f64>>> {
        let wc = wc_indices.as_slice()?;
        let from_s = from_state_indices.as_slice()?;
        let to_s = to_state_indices.as_slice()?;

        let n = wc.len();
        if from_s.len() != n || to_s.len() != n {
            return Err(PyValueError::new_err(
                "NativeSdstBatchLookup.get_setup_batch: all index arrays must have identical lengths",
            ));
        }

        let n_wc = self.n_wc;
        let n_states = self.n_states;
        let values = &self.setup_values;

        // Pre-allocate output numpy array
        let out = PyArray1::<f64>::zeros(py, n, false);
        let out_ptr = SendPtr(unsafe { out.as_slice_mut().unwrap().as_mut_ptr() });

        // Release GIL for parallel batch lookup
        py.allow_threads(|| {
            (0..n)
                .into_par_iter()
                .with_min_len(RAYON_MIN_CHUNK)
                .for_each(|i| {
                    let wi = wc[i];
                    let fi = from_s[i];
                    let ti = to_s[i];

                    let val = if wi < 0
                        || fi < 0
                        || ti < 0
                        || (wi as usize) >= n_wc
                        || (fi as usize) >= n_states
                        || (ti as usize) >= n_states
                    {
                        0.0
                    } else {
                        let idx = (wi as usize) * n_states * n_states
                            + (fi as usize) * n_states
                            + (ti as usize);
                        values[idx]
                    };

                    // SAFETY: each rayon task writes to a unique index i — no data races.
                    unsafe {
                        out_ptr.write_at(i, val);
                    }
                });
        });

        Ok(out.into())
    }

    #[getter]
    fn n_wc(&self) -> usize {
        self.n_wc
    }

    #[getter]
    fn n_states(&self) -> usize {
        self.n_states
    }
}

// ---------------------------------------------------------------------------
// Task 4.1 + 4.2: Native ALNS Destroy Worst Scoring.
//
// Computes per-operation setup-cost contributions for the "worst removal"
// destroy operator. For each assignment i on machine m:
//   score = setup(pred→i) + setup(i→succ) - setup(pred→succ)
// Edge cases:
//   - First on machine: score = setup(i→succ)
//   - Last on machine: score = setup(pred→i)
//   - Alone on machine: score = 0.0
//
// Input is structure-of-arrays with CSR machine grouping. Python remains
// responsible for UUID→index mapping; this function operates on integer indices.
// ---------------------------------------------------------------------------

#[pyfunction]
fn compute_destroy_worst_scores<'py>(
    py: Python<'py>,
    // CSR machine grouping: machine_offsets[m]..machine_offsets[m+1] gives
    // the range of assignment indices belonging to machine m (sorted by start_time).
    machine_offsets: PyReadonlyArray1<'py, i64>,
    // Flat array of assignment indices per machine (the CSR column data).
    // Each value is an index into the state_ids array.
    assignment_indices: PyReadonlyArray1<'py, i64>,
    // Per-assignment state IDs (integer indices into the SDST state dimension).
    state_ids: PyReadonlyArray1<'py, i64>,
    // Dense SDST setup values flattened as [n_wc * n_states * n_states].
    sdst_setup_flat: PyReadonlyArray1<'py, f64>,
    // Per-assignment work center index (integer index into the SDST wc dimension).
    wc_indices: PyReadonlyArray1<'py, i64>,
    // Dimensions
    n_wc: usize,
    n_states: usize,
) -> PyResult<Py<PyArray1<f64>>> {
    let offsets = machine_offsets.as_slice()?;
    let indices = assignment_indices.as_slice()?;
    let states = state_ids.as_slice()?;
    let sdst = sdst_setup_flat.as_slice()?;
    let wc = wc_indices.as_slice()?;

    let n_machines = if offsets.is_empty() {
        0
    } else {
        offsets.len() - 1
    };
    let n_assignments = states.len();

    if wc.len() != n_assignments {
        return Err(PyValueError::new_err(
            "compute_destroy_worst_scores: state_ids and wc_indices must have identical lengths",
        ));
    }
    let expected_sdst_len = n_wc * n_states * n_states;
    if sdst.len() != expected_sdst_len {
        return Err(PyValueError::new_err(
            "compute_destroy_worst_scores: sdst_setup_flat must have length n_wc * n_states * n_states",
        ));
    }

    // Pre-allocate output array (one score per assignment)
    let out = PyArray1::<f64>::zeros(py, n_assignments, false);
    let out_ptr = SendPtr(unsafe { out.as_slice_mut().unwrap().as_mut_ptr() });

    py.allow_threads(|| {
        (0..n_machines)
            .into_par_iter()
            .for_each(|m| {
                let row_start = offsets[m] as usize;
                let row_end = offsets[m + 1] as usize;
                let machine_len = row_end - row_start;

                if machine_len == 0 {
                    return;
                }

                for pos in 0..machine_len {
                    let assign_idx = indices[row_start + pos] as usize;
                    if assign_idx >= n_assignments {
                        continue;
                    }

                    let wc_idx = wc[assign_idx] as usize;
                    if wc_idx >= n_wc {
                        // SAFETY: unique index per assignment
                        unsafe { out_ptr.write_at(assign_idx, 0.0) };
                        continue;
                    }

                    let wc_offset = wc_idx * n_states * n_states;
                    let curr_state = states[assign_idx];

                    if curr_state < 0 || (curr_state as usize) >= n_states {
                        unsafe { out_ptr.write_at(assign_idx, 0.0) };
                        continue;
                    }

                    let cs = curr_state as usize;
                    let mut score = 0.0;

                    // Setup cost from predecessor to current
                    if pos > 0 {
                        let prev_idx = indices[row_start + pos - 1] as usize;
                        if prev_idx < n_assignments {
                            let prev_state = states[prev_idx];
                            if prev_state >= 0 && (prev_state as usize) < n_states {
                                let ps = prev_state as usize;
                                score += sdst[wc_offset + ps * n_states + cs];
                            }
                        }
                    }

                    // Setup cost from current to successor
                    if pos < machine_len - 1 {
                        let next_idx = indices[row_start + pos + 1] as usize;
                        if next_idx < n_assignments {
                            let next_state = states[next_idx];
                            if next_state >= 0 && (next_state as usize) < n_states {
                                let ns = next_state as usize;
                                score += sdst[wc_offset + cs * n_states + ns];
                            }
                        }
                    }

                    // Subtract setup cost from predecessor directly to successor
                    // (the cost that would remain if we remove this operation)
                    if pos > 0 && pos < machine_len - 1 {
                        let prev_idx = indices[row_start + pos - 1] as usize;
                        let next_idx = indices[row_start + pos + 1] as usize;
                        if prev_idx < n_assignments && next_idx < n_assignments {
                            let prev_state = states[prev_idx];
                            let next_state = states[next_idx];
                            if prev_state >= 0
                                && next_state >= 0
                                && (prev_state as usize) < n_states
                                && (next_state as usize) < n_states
                            {
                                let ps = prev_state as usize;
                                let ns = next_state as usize;
                                score -= sdst[wc_offset + ps * n_states + ns];
                            }
                        }
                    }

                    // SAFETY: each assignment_idx is unique across the CSR structure,
                    // so each rayon task writes to a disjoint output index.
                    unsafe { out_ptr.write_at(assign_idx, score) };
                }
            });
    });

    Ok(out.into())
}

// ---------------------------------------------------------------------------
// Task 20.1: Greedy Repair Batch — simplified greedy dispatch in Rust.
//
// Assigns operations in topological order to their earliest-available eligible
// machine, respecting:
//   - Precedence constraints (operation can't start before predecessor ends)
//   - Machine availability (no overlap on same machine)
//   - Setup times (SDST between consecutive operations on same machine)
//
// This is a SIMPLIFIED greedy — no auxiliary resource constraints, no gap-insertion.
// It is meant as a fast initial seed for ALNS repair, not a full feasibility-
// guaranteed dispatch. Operations MUST be provided in valid topological order
// (predecessors before successors).
//
// The main loop is sequential (topological dependency prevents parallelism),
// but per-operation eligible-machine scanning is a tight inner loop that
// benefits from cache-friendly linear access patterns.
//
// Academic basis: greedy dispatch heuristics for FJSP (Brandimarte 1993,
// Mastrolilli & Gambardella 2000). Speed factor per machine models heterogeneous
// parallel machines (Pm||Cmax variant).
// ---------------------------------------------------------------------------

#[pyfunction]
fn greedy_repair_batch<'py>(
    py: Python<'py>,
    // Operation data (N operations, in topological order)
    base_durations: PyReadonlyArray1<'py, f64>,      // [N] duration in minutes
    predecessor_indices: PyReadonlyArray1<'py, i64>,  // [N] -1 = no predecessor
    // Eligible machines per operation (CSR format)
    eligible_offsets: PyReadonlyArray1<'py, i64>,     // [N+1] CSR row pointers
    eligible_indices: PyReadonlyArray1<'py, i64>,     // flat eligible machine indices
    // SDST data
    state_ids: PyReadonlyArray1<'py, i64>,           // [N] state index per operation
    sdst_setup_flat: PyReadonlyArray1<'py, f64>,     // [n_wc * n_states * n_states]
    n_wc: usize,
    n_states: usize,
    // Machine speed factors
    speed_factors: PyReadonlyArray1<'py, f64>,       // [n_wc]
) -> PyResult<(Py<PyArray1<f64>>, Py<PyArray1<f64>>, Py<PyArray1<i64>>)> {
    let durations = base_durations.as_slice()?;
    let preds = predecessor_indices.as_slice()?;
    let elig_off = eligible_offsets.as_slice()?;
    let elig_idx = eligible_indices.as_slice()?;
    let states = state_ids.as_slice()?;
    let sdst = sdst_setup_flat.as_slice()?;
    let speeds = speed_factors.as_slice()?;

    let n = durations.len();

    // Validate input dimensions
    if preds.len() != n || states.len() != n {
        return Err(PyValueError::new_err(
            "greedy_repair_batch: base_durations, predecessor_indices, and state_ids must have identical lengths",
        ));
    }
    if elig_off.len() != n + 1 {
        return Err(PyValueError::new_err(
            "greedy_repair_batch: eligible_offsets must have length N+1",
        ));
    }
    if speeds.len() != n_wc {
        return Err(PyValueError::new_err(
            "greedy_repair_batch: speed_factors must have length n_wc",
        ));
    }
    let expected_sdst_len = n_wc * n_states * n_states;
    if sdst.len() != expected_sdst_len {
        return Err(PyValueError::new_err(
            "greedy_repair_batch: sdst_setup_flat must have length n_wc * n_states * n_states",
        ));
    }

    // Pre-allocate output arrays
    let out_starts = PyArray1::<f64>::zeros(py, n, false);
    let out_ends = PyArray1::<f64>::zeros(py, n, false);
    let out_machines = PyArray1::<i64>::zeros(py, n, false);

    let starts_slice = unsafe { out_starts.as_slice_mut()? };
    let ends_slice = unsafe { out_ends.as_slice_mut()? };
    let machines_slice = unsafe { out_machines.as_slice_mut()? };

    // Release GIL during computation — the main loop is sequential but
    // avoids holding the GIL for potentially long 50K-operation dispatches.
    let mut failed_op: Option<usize> = None;
    py.allow_threads(|| {
        // Per-machine state: availability time and last state index
        let mut machine_available_at = vec![0.0f64; n_wc];
        let mut machine_last_state = vec![-1i64; n_wc];

        // Per-operation end time (for predecessor lookups)
        let mut op_end = vec![0.0f64; n];

        for i in 0..n {
            // Sequential SoA + next CSR row (software pipeline, one cache line ahead).
            if i + PREFETCH_DISTANCE < n {
                prefetch_f64_at(durations, i + PREFETCH_DISTANCE);
                prefetch_i64_at(preds, i + PREFETCH_DISTANCE);
                prefetch_i64_at(states, i + PREFETCH_DISTANCE);
                prefetch_i64_at(elig_off, i + 1 + PREFETCH_DISTANCE);
                let next_row = elig_off[i + PREFETCH_DISTANCE] as usize;
                prefetch_i64_at(elig_idx, next_row);
            }

            // Predecessor constraint
            let pred_end = if preds[i] >= 0 {
                let pred_idx = preds[i] as usize;
                if pred_idx < n {
                    op_end[pred_idx]
                } else {
                    0.0
                }
            } else {
                0.0
            };

            let row_start = elig_off[i] as usize;
            let row_end = elig_off[i + 1] as usize;

            let mut best_start = f64::INFINITY;
            let mut best_end = f64::INFINITY;
            let mut best_machine: i64 = -1;

            // Scan eligible machines for earliest completion
            for k in row_start..row_end {
                if k + PREFETCH_DISTANCE < row_end {
                    let m_ahead = elig_idx[k + PREFETCH_DISTANCE] as usize;
                    prefetch_f64_at(&speeds, m_ahead);
                    prefetch_f64_at(&machine_available_at, m_ahead);
                    if m_ahead < n_wc && machine_last_state[m_ahead] >= 0 && states[i] >= 0 {
                        let prev_s = machine_last_state[m_ahead] as usize;
                        let curr_s = states[i] as usize;
                        if prev_s < n_states && curr_s < n_states {
                            prefetch_f64_at(
                                sdst,
                                m_ahead * n_states * n_states + prev_s * n_states + curr_s,
                            );
                        }
                    }
                }
                let m = elig_idx[k] as usize;
                if m >= n_wc {
                    continue;
                }

                // Duration adjusted by machine speed factor
                let speed = speeds[m];
                let duration = if speed > 0.0 {
                    durations[i] / speed
                } else {
                    durations[i]
                };

                // Setup time from previous operation on this machine
                let setup = if machine_last_state[m] >= 0 && states[i] >= 0 {
                    let prev_s = machine_last_state[m] as usize;
                    let curr_s = states[i] as usize;
                    if prev_s < n_states && curr_s < n_states {
                        sdst[m * n_states * n_states + prev_s * n_states + curr_s]
                    } else {
                        0.0
                    }
                } else {
                    0.0
                };

                // Earliest start respecting both predecessor and machine availability + setup
                let earliest = pred_end.max(machine_available_at[m] + setup);
                let end = earliest + duration;

                if end < best_end {
                    best_start = earliest;
                    best_end = end;
                    best_machine = m as i64;
                }
            }

            // Empty CSR row: fail closed. Machine-0 + 1e6 was a silent lie vs
            // the Python contract (eligible=[] means all work centers).
            if best_machine < 0 {
                failed_op = Some(i);
                return;
            }

            starts_slice[i] = best_start;
            ends_slice[i] = best_end;
            machines_slice[i] = best_machine;
            op_end[i] = best_end;

            let bm = best_machine as usize;
            machine_available_at[bm] = best_end;
            machine_last_state[bm] = states[i];
        }
    });

    if let Some(i) = failed_op {
        return Err(PyValueError::new_err(format!(
            "greedy_repair_batch: operation {i} has empty eligible machine set"
        )));
    }

    Ok((out_starts.into(), out_ends.into(), out_machines.into()))
}

// ---------------------------------------------------------------------------
// Module registration.
// ---------------------------------------------------------------------------

#[pymodule]
fn synaps_native(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<SynApsEngine>()?;
    module.add_class::<NativeSdstBatchLookup>()?;
    module.add_function(wrap_pyfunction!(compute_atcs_log_score, module)?)?;
    module.add_function(wrap_pyfunction!(compute_atcs_log_scores_batch, module)?)?;
    module.add_function(wrap_pyfunction!(resource_capacity_window_is_feasible, module)?)?;
    module.add_function(wrap_pyfunction!(compute_rhc_candidate_metrics_batch, module)?)?;
    module.add_function(wrap_pyfunction!(compute_rhc_candidate_metrics_batch_np, module)?)?;
    module.add_function(wrap_pyfunction!(
        compute_rhc_candidate_metrics_batch_np_jagged,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(evaluate_objective_batch, module)?)?;
    module.add_function(wrap_pyfunction!(stabilize_temporal_batch, module)?)?;
    module.add_function(wrap_pyfunction!(compute_destroy_worst_scores, module)?)?;
    module.add_function(wrap_pyfunction!(greedy_repair_batch, module)?)?;
    Ok(())
}
