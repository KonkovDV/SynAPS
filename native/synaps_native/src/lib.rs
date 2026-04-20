use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

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

    safe_weight.ln() - safe_processing.ln() - (slack / (k1 * safe_ready_p_bar)) - setup_penalty - material_penalty
}

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

    // Release the GIL while running data-parallel scoring.
    let scores = py.allow_threads(|| {
        (0..n)
            .into_par_iter()
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
    for machine_indices in &eligible_machine_indices {
        for machine_idx in machine_indices {
            if *machine_idx >= machine_count {
                return Err(PyValueError::new_err(
                    "eligible machine index is out of range",
                ));
            }
        }
    }

    let safe_pressure_denominator = (due_pressure_k1 * avg_total_p).max(1e-6);

    // Release GIL while running data-parallel candidate scoring.
    let metrics = py.allow_threads(|| {
        (0..n)
            .into_par_iter()
            .map(|i| {
                let earliest_machine_ready = if eligible_machine_indices[i].is_empty() {
                    0.0
                } else {
                    eligible_machine_indices[i]
                        .iter()
                        .map(|machine_idx| machine_available_offsets[*machine_idx])
                        .fold(f64::INFINITY, f64::min)
                };

                let est_offset = predecessor_end_offsets[i].max(earliest_machine_ready);
                let slack = due_offsets[i] - (est_offset + rpt_tail_minutes[i]);

                let mut pressure = (order_weights[i] / p_tilde_minutes[i].max(1e-6))
                    * f64::exp(-slack.max(0.0) / safe_pressure_denominator);
                if slack <= 0.0 {
                    pressure *= due_pressure_overdue_boost;
                }

                (slack, pressure)
            })
            .collect::<Vec<(f64, f64)>>()
    });

    let mut slacks = Vec::with_capacity(n);
    let mut pressures = Vec::with_capacity(n);
    for (slack, pressure) in metrics {
        slacks.push(slack);
        pressures.push(pressure);
    }

    Ok((slacks, pressures))
}

#[pymodule]
fn synaps_native(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(compute_atcs_log_score, module)?)?;
    module.add_function(wrap_pyfunction!(compute_atcs_log_scores_batch, module)?)?;
    module.add_function(wrap_pyfunction!(resource_capacity_window_is_feasible, module)?)?;
    module.add_function(wrap_pyfunction!(compute_rhc_candidate_metrics_batch, module)?)?;
    Ok(())
}
