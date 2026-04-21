use numpy::{PyArray1, PyArrayMethods, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

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
    let bits = ((a * x + b) as i64) << 32;
    f64::from_bits(bits as u64)
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
                let (slack, pressure) = rhc_element_csr(
                    i,
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
                let (slack, pressure) = rhc_element_csr(
                    i,
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
                let (slack, pressure) = rhc_element_csr(
                    i,
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
// Module registration.
// ---------------------------------------------------------------------------

#[pymodule]
fn synaps_native(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(compute_atcs_log_score, module)?)?;
    module.add_function(wrap_pyfunction!(compute_atcs_log_scores_batch, module)?)?;
    module.add_function(wrap_pyfunction!(resource_capacity_window_is_feasible, module)?)?;
    module.add_function(wrap_pyfunction!(compute_rhc_candidate_metrics_batch, module)?)?;
    module.add_function(wrap_pyfunction!(compute_rhc_candidate_metrics_batch_np, module)?)?;
    module.add_function(wrap_pyfunction!(
        compute_rhc_candidate_metrics_batch_np_jagged,
        module
    )?)?;
    Ok(())
}
