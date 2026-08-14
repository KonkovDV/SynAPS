//! Parallel (non-delay) list-schedule cover for GREEDY_COVER.
//!
//! Academic basis: Kolisch (1996) parallel SGS / Pinedo list scheduling.
//! At 100k–500k ops the serial insertion SGS fragments the calendar; this
//! kernel appends to machine tails (ready heap by earliest floor), then
//! delay-bumps auxiliary capacity on a shortlist of machines.
//!
//! Sequential main loop (precedence). Prefetch irregular CSR/SDST gathers.
//! Target ISA: AVX2+FMA3. Do not emit AVX-512 (Raptor Lake hybrid).

use std::cmp::Reverse;
use std::collections::BinaryHeap;

use numpy::{PyArray1, PyArrayMethods, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::cpu::{prefetch_f64_at, prefetch_i64_at, PREFETCH_DISTANCE};

const AUX_BUMP_ITERS: usize = 256;
const EPS: f64 = 1e-9;

#[derive(Clone, Copy, Eq, PartialEq, Ord, PartialOrd)]
struct ReadyKey {
    floor_us: i64,
    seq: i32,
    uuid_rank: i32,
    idx: u32,
}

#[inline(always)]
fn floor_key(minutes: f64) -> i64 {
    (minutes * 1_000_000.0).round() as i64
}

/// Canonical reservation grain: max(1, ceil(base / speed)). Matches Python timegrain.
#[inline(always)]
fn grain_duration(base: f64, speed: f64) -> f64 {
    let speed = if speed > 0.0 { speed } else { 1.0 };
    (base / speed).ceil().max(1.0)
}

#[inline(always)]
fn capacity_window_ok(
    windows: &[(f64, f64, i32)],
    candidate_start: f64,
    candidate_end: f64,
    requested: i64,
    pool: i64,
) -> bool {
    let mut active: i64 = 0;
    let mut events: Vec<(f64, i64)> = Vec::new();
    for &(other_start, other_end, quantity) in windows {
        let qty = i64::from(quantity);
        if other_start >= candidate_end || other_end <= candidate_start {
            continue;
        }
        if other_start <= candidate_start && candidate_start < other_end {
            active += qty;
        } else {
            events.push((other_start, qty));
        }
        if candidate_start < other_end && other_end < candidate_end {
            events.push((other_end, -qty));
        }
    }
    if active + requested > pool {
        return false;
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
        active += delta;
        if active + requested > pool {
            return false;
        }
    }
    true
}

fn delay_start_for_aux(
    mut start: f64,
    duration: f64,
    setup: f64,
    cap: f64,
    aux_res: &[i64],
    aux_qty: &[i32],
    row_start: usize,
    row_end: usize,
    occupancy: &[Vec<(f64, f64, i32)>],
    pools: &[i32],
) -> Option<f64> {
    if row_start == row_end {
        return if start + duration <= cap + EPS {
            Some(start)
        } else {
            None
        };
    }
    for _ in 0..AUX_BUMP_ITERS {
        let end = start + duration;
        if end > cap + EPS {
            return None;
        }
        let aux_start = start - setup;
        let mut blocked_until = start;
        let mut feasible = true;
        for k in row_start..row_end {
            let res = aux_res[k];
            if res < 0 {
                continue;
            }
            let r = res as usize;
            if r >= occupancy.len() || r >= pools.len() {
                continue;
            }
            let requested = i64::from(aux_qty[k]);
            let pool = i64::from(pools[r]);
            if capacity_window_ok(&occupancy[r], aux_start, end, requested, pool) {
                continue;
            }
            feasible = false;
            let mut min_end = f64::INFINITY;
            for &(w_start, w_end, _) in &occupancy[r] {
                if w_start < end + EPS && w_end > aux_start - EPS {
                    min_end = min_end.min(w_end);
                }
            }
            if min_end.is_finite() {
                blocked_until = blocked_until.max(min_end);
            }
        }
        if feasible {
            return Some(start);
        }
        if blocked_until <= start + EPS {
            return None;
        }
        start = blocked_until;
    }
    None
}

struct CoverArrays<'a> {
    durations: &'a [f64],
    preds: &'a [i64],
    seq: &'a [i32],
    uuid_rank: &'a [i32],
    earliest: &'a [f64],
    latest: &'a [f64],
    elig_off: &'a [i64],
    elig_idx: &'a [i64],
    states: &'a [i64],
    sdst: &'a [f64],
    speeds: &'a [f64],
    aux_off: &'a [i64],
    aux_res: &'a [i64],
    aux_qty: &'a [i32],
    pools: &'a [i32],
    n_wc: usize,
    n_states: usize,
    horizon: f64,
}

fn run_list_schedule(a: CoverArrays<'_>) -> (Vec<f64>, Vec<f64>, Vec<i64>, Vec<i64>) {
    let n = a.durations.len();
    let mut starts = vec![0.0f64; n];
    let mut ends = vec![0.0f64; n];
    let mut machines = vec![-1i64; n];
    let mut setups = vec![0i64; n];
    if n == 0 || a.n_wc == 0 {
        return (starts, ends, machines, setups);
    }

    let mut succ_count = vec![0u32; n];
    for pred in a.preds {
        if *pred >= 0 {
            let p = *pred as usize;
            if p < n {
                succ_count[p] += 1;
            }
        }
    }
    let mut succ_off = vec![0i64; n + 1];
    for i in 0..n {
        succ_off[i + 1] = succ_off[i] + i64::from(succ_count[i]);
    }
    let mut succ_idx = vec![0u32; succ_off[n] as usize];
    let mut cursor = succ_off.clone();
    for i in 0..n {
        let pred = a.preds[i];
        if pred >= 0 {
            let p = pred as usize;
            if p < n {
                let slot = cursor[p] as usize;
                succ_idx[slot] = i as u32;
                cursor[p] += 1;
            }
        }
    }

    let n_aux = a.pools.len();
    let mut occupancy: Vec<Vec<(f64, f64, i32)>> = (0..n_aux).map(|_| Vec::new()).collect();
    let mut machine_tail = vec![0.0f64; a.n_wc];
    let mut machine_last_state = vec![-1i64; a.n_wc];
    let mut aux_cands: Vec<(f64, f64, f64, usize)> = Vec::new();

    let mut heap: BinaryHeap<Reverse<ReadyKey>> = BinaryHeap::new();
    for i in 0..n {
        if a.preds[i] < 0 {
            heap.push(Reverse(ReadyKey {
                floor_us: floor_key(a.earliest[i]),
                seq: a.seq[i],
                uuid_rank: a.uuid_rank[i],
                idx: i as u32,
            }));
        }
    }

    let has_aux = a.aux_off.len() == n + 1 && a.aux_off[n] > 0;

    while let Some(Reverse(ready)) = heap.pop() {
        let i = ready.idx as usize;
        let pred_end = if a.preds[i] >= 0 {
            let p = a.preds[i] as usize;
            if p < n {
                ends[p]
            } else {
                0.0
            }
        } else {
            0.0
        };
        let floor = pred_end.max(a.earliest[i]);
        let cap = a.horizon.min(a.latest[i]);
        let row_start = a.elig_off[i] as usize;
        let row_end = a.elig_off[i + 1] as usize;
        let aux_s = if has_aux { a.aux_off[i] as usize } else { 0 };
        let aux_e = if has_aux { a.aux_off[i + 1] as usize } else { 0 };
        let needs_aux = aux_e > aux_s;

        let placed = if needs_aux {
            place_with_aux_delay(
                &a,
                i,
                floor,
                cap,
                row_start,
                row_end,
                aux_s,
                aux_e,
                &machine_tail,
                &machine_last_state,
                &occupancy,
                &mut aux_cands,
            )
        } else {
            place_append_only(
                &a,
                i,
                floor,
                cap,
                row_start,
                row_end,
                &machine_tail,
                &machine_last_state,
            )
        };

        if let Some((start, end, setup, machine)) = placed {
            starts[i] = start;
            ends[i] = end;
            machines[i] = machine as i64;
            setups[i] = setup.round() as i64;
            machine_tail[machine] = end;
            machine_last_state[machine] = a.states[i];
            if needs_aux {
                let aux_start = start - setup;
                for k in aux_s..aux_e {
                    let res = a.aux_res[k];
                    if res < 0 {
                        continue;
                    }
                    let r = res as usize;
                    if r < occupancy.len() {
                        occupancy[r].push((aux_start, end, a.aux_qty[k]));
                    }
                }
            }
            let s0 = succ_off[i] as usize;
            let s1 = succ_off[i + 1] as usize;
            for slot in s0..s1 {
                let succ = succ_idx[slot] as usize;
                let succ_floor = end.max(a.earliest[succ]);
                heap.push(Reverse(ReadyKey {
                    floor_us: floor_key(succ_floor),
                    seq: a.seq[succ],
                    uuid_rank: a.uuid_rank[succ],
                    idx: succ as u32,
                }));
            }
        }
    }

    (starts, ends, machines, setups)
}

fn setup_on_machine(
    a: &CoverArrays<'_>,
    op: usize,
    machine: usize,
    last_state: i64,
) -> f64 {
    if last_state >= 0 && a.states[op] >= 0 {
        let prev_s = last_state as usize;
        let curr_s = a.states[op] as usize;
        if prev_s < a.n_states && curr_s < a.n_states {
            return a.sdst[machine * a.n_states * a.n_states + prev_s * a.n_states + curr_s];
        }
    }
    0.0
}

fn place_append_only(
    a: &CoverArrays<'_>,
    i: usize,
    floor: f64,
    cap: f64,
    row_start: usize,
    row_end: usize,
    machine_tail: &[f64],
    machine_last_state: &[i64],
) -> Option<(f64, f64, f64, usize)> {
    let mut best_end = f64::INFINITY;
    let mut best_start = 0.0;
    let mut best_setup = 0.0;
    let mut best_machine: Option<usize> = None;
    for k in row_start..row_end {
        if k + PREFETCH_DISTANCE < row_end {
            let ahead = a.elig_idx[k + PREFETCH_DISTANCE] as usize;
            prefetch_f64_at(a.speeds, ahead);
            prefetch_f64_at(machine_tail, ahead);
        }
        let m = a.elig_idx[k];
        if m < 0 {
            continue;
        }
        let machine = m as usize;
        if machine >= a.n_wc {
            continue;
        }
        let duration = grain_duration(a.durations[i], a.speeds[machine]);
        let setup = setup_on_machine(a, i, machine, machine_last_state[machine]);
        let start = floor.max(machine_tail[machine] + setup);
        let end = start + duration;
        if end > cap + EPS {
            continue;
        }
        if end < best_end || (end == best_end && machine < best_machine.unwrap_or(usize::MAX)) {
            best_end = end;
            best_start = start;
            best_setup = setup;
            best_machine = Some(machine);
        }
    }
    best_machine.map(|machine| (best_start, best_end, best_setup, machine))
}

fn place_with_aux_delay(
    a: &CoverArrays<'_>,
    i: usize,
    floor: f64,
    cap: f64,
    row_start: usize,
    row_end: usize,
    aux_s: usize,
    aux_e: usize,
    machine_tail: &[f64],
    machine_last_state: &[i64],
    occupancy: &[Vec<(f64, f64, i32)>],
    cands: &mut Vec<(f64, f64, f64, usize)>,
) -> Option<(f64, f64, f64, usize)> {
    cands.clear();
    for k in row_start..row_end {
        let m = a.elig_idx[k];
        if m < 0 {
            continue;
        }
        let machine = m as usize;
        if machine >= a.n_wc {
            continue;
        }
        let duration = grain_duration(a.durations[i], a.speeds[machine]);
        let setup = setup_on_machine(a, i, machine, machine_last_state[machine]);
        let start = floor.max(machine_tail[machine] + setup);
        let end = start + duration;
        if end > cap + EPS {
            continue;
        }
        cands.push((end, start, setup, machine));
    }
    cands.sort_unstable_by(|left, right| {
        left.0
            .partial_cmp(&right.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.3.cmp(&right.3))
    });
    let mut best: Option<(f64, f64, f64, usize)> = None;
    for &(_end, start, setup, machine) in cands.iter() {
        let duration = grain_duration(a.durations[i], a.speeds[machine]);
        let Some(delayed) = delay_start_for_aux(
            start,
            duration,
            setup,
            cap,
            a.aux_res,
            a.aux_qty,
            aux_s,
            aux_e,
            occupancy,
            a.pools,
        ) else {
            continue;
        };
        let delayed_end = delayed + duration;
        if best.is_none_or(|b| delayed_end < b.0 || (delayed_end == b.0 && machine < b.3)) {
            best = Some((delayed_end, delayed, setup, machine));
        }
    }
    best.map(|(end, start, setup, machine)| (start, end, setup, machine))
}

#[pyfunction]
pub fn list_schedule_cover<'py>(
    py: Python<'py>,
    base_durations: PyReadonlyArray1<'py, f64>,
    predecessor_indices: PyReadonlyArray1<'py, i64>,
    seq_in_order: PyReadonlyArray1<'py, i32>,
    uuid_rank: PyReadonlyArray1<'py, i32>,
    earliest: PyReadonlyArray1<'py, f64>,
    latest_finish: PyReadonlyArray1<'py, f64>,
    eligible_offsets: PyReadonlyArray1<'py, i64>,
    eligible_indices: PyReadonlyArray1<'py, i64>,
    state_ids: PyReadonlyArray1<'py, i64>,
    sdst_setup_flat: PyReadonlyArray1<'py, f64>,
    n_wc: usize,
    n_states: usize,
    speed_factors: PyReadonlyArray1<'py, f64>,
    horizon_minutes: f64,
    aux_offsets: PyReadonlyArray1<'py, i64>,
    aux_resource_indices: PyReadonlyArray1<'py, i64>,
    aux_quantities: PyReadonlyArray1<'py, i32>,
    aux_pool_sizes: PyReadonlyArray1<'py, i32>,
) -> PyResult<(
    Py<PyArray1<f64>>,
    Py<PyArray1<f64>>,
    Py<PyArray1<i64>>,
    Py<PyArray1<i64>>,
)> {
    let durations = base_durations.as_slice()?;
    let preds = predecessor_indices.as_slice()?;
    let seq = seq_in_order.as_slice()?;
    let uuid_rank = uuid_rank.as_slice()?;
    let earliest = earliest.as_slice()?;
    let latest = latest_finish.as_slice()?;
    let elig_off = eligible_offsets.as_slice()?;
    let elig_idx = eligible_indices.as_slice()?;
    let states = state_ids.as_slice()?;
    let sdst = sdst_setup_flat.as_slice()?;
    let speeds = speed_factors.as_slice()?;
    let aux_off = aux_offsets.as_slice()?;
    let aux_res = aux_resource_indices.as_slice()?;
    let aux_qty = aux_quantities.as_slice()?;
    let pools = aux_pool_sizes.as_slice()?;

    let n = durations.len();
    if preds.len() != n
        || seq.len() != n
        || uuid_rank.len() != n
        || earliest.len() != n
        || latest.len() != n
        || states.len() != n
    {
        return Err(PyValueError::new_err(
            "list_schedule_cover: per-op arrays must have identical length N",
        ));
    }
    if elig_off.len() != n + 1 {
        return Err(PyValueError::new_err(
            "list_schedule_cover: eligible_offsets must have length N+1",
        ));
    }
    if speeds.len() != n_wc {
        return Err(PyValueError::new_err(
            "list_schedule_cover: speed_factors must have length n_wc",
        ));
    }
    let expected_sdst = n_wc.saturating_mul(n_states).saturating_mul(n_states);
    if sdst.len() != expected_sdst {
        return Err(PyValueError::new_err(
            "list_schedule_cover: sdst_setup_flat must have length n_wc * n_states * n_states",
        ));
    }
    if !aux_off.is_empty() && aux_off.len() != n + 1 {
        return Err(PyValueError::new_err(
            "list_schedule_cover: aux_offsets must be empty or length N+1",
        ));
    }
    if aux_res.len() != aux_qty.len() {
        return Err(PyValueError::new_err(
            "list_schedule_cover: aux_resource_indices and aux_quantities must match",
        ));
    }

    let empty_off: [i64; 0] = [];
    let aux_off_use: &[i64] = if aux_off.is_empty() { &empty_off } else { aux_off };

    let out_starts = PyArray1::<f64>::zeros(py, n, false);
    let out_ends = PyArray1::<f64>::zeros(py, n, false);
    let out_machines = PyArray1::<i64>::zeros(py, n, false);
    let out_setups = PyArray1::<i64>::zeros(py, n, false);
    let starts_slice = unsafe { out_starts.as_slice_mut()? };
    let ends_slice = unsafe { out_ends.as_slice_mut()? };
    let machines_slice = unsafe { out_machines.as_slice_mut()? };
    let setups_slice = unsafe { out_setups.as_slice_mut()? };

    py.allow_threads(|| {
        if n > PREFETCH_DISTANCE {
            prefetch_f64_at(durations, PREFETCH_DISTANCE);
            prefetch_i64_at(preds, PREFETCH_DISTANCE);
            prefetch_i64_at(states, PREFETCH_DISTANCE);
        }
        let (starts_v, ends_v, machines_v, setups_v) = run_list_schedule(CoverArrays {
            durations,
            preds,
            seq,
            uuid_rank,
            earliest,
            latest,
            elig_off,
            elig_idx,
            states,
            sdst,
            speeds,
            aux_off: aux_off_use,
            aux_res,
            aux_qty,
            pools,
            n_wc,
            n_states,
            horizon: horizon_minutes,
        });
        starts_slice.copy_from_slice(&starts_v);
        ends_slice.copy_from_slice(&ends_v);
        machines_slice.copy_from_slice(&machines_v);
        setups_slice.copy_from_slice(&setups_v);
    });

    Ok((
        out_starts.into(),
        out_ends.into(),
        out_machines.into(),
        out_setups.into(),
    ))
}

#[cfg(test)]
mod tests {
    use super::grain_duration;

    #[test]
    fn grain_matches_python_ceil() {
        assert_eq!(grain_duration(10.0, 3.0), 4.0);
        assert_eq!(grain_duration(0.0, 1.0), 1.0);
        assert_eq!(grain_duration(10.0, 0.0), 10.0);
    }
}
