//! CPU micro-architecture helpers for SynAPS native kernels.
//!
//! Prefetch distance 8 × 8 bytes = one 64-byte cache line (Intel SDM Vol. 2,
//! PREFETCHT0 / `_MM_HINT_T0`). Used on irregular CSR/SDST gathers that the
//! hardware stride prefetcher cannot track (typically 4–8 streams).
//!
//! Target ISA: AVX2+FMA3 (Raptor Lake class). AVX-512 is hardware-disabled on
//! hybrid P/E parts — do not emit it. See `docs/architecture/08_HPC_SILICON_OPTIMIZATION_ROADMAP.md`.

/// Elements ahead of the current index to prefetch (one cache line of f64).
pub const PREFETCH_DISTANCE: usize = 8;

#[inline(always)]
pub fn prefetch_t0(ptr: *const u8) {
    #[cfg(target_arch = "x86_64")]
    unsafe {
        core::arch::x86_64::_mm_prefetch::<{ core::arch::x86_64::_MM_HINT_T0 }>(ptr as *const i8);
    }
    #[cfg(not(target_arch = "x86_64"))]
    {
        let _ = ptr;
    }
}

/// Prefetch `base[idx]` when `idx` is in-range. No-op on empty/OOB.
#[inline(always)]
pub fn prefetch_f64_at(base: &[f64], idx: usize) {
    if idx < base.len() {
        prefetch_t0(unsafe { base.as_ptr().add(idx) as *const u8 });
    }
}

/// Prefetch `base[idx]` for i64 CSR index streams.
#[inline(always)]
pub fn prefetch_i64_at(base: &[i64], idx: usize) {
    if idx < base.len() {
        prefetch_t0(unsafe { base.as_ptr().add(idx) as *const u8 });
    }
}

/// Prefetch the sequential RHC SoA streams one cache line ahead.
/// Hardware prefetchers typically track 4–8 streams; this kernel has seven.
#[inline(always)]
pub fn prefetch_rhc_soa(
    i: usize,
    n: usize,
    peo: &[f64],
    d_off: &[f64],
    rpt: &[f64],
    ow: &[f64],
    ptm: &[f64],
    offsets: &[i64],
) {
    let ahead = i + PREFETCH_DISTANCE;
    if ahead < n {
        prefetch_f64_at(peo, ahead);
        prefetch_f64_at(d_off, ahead);
        prefetch_f64_at(rpt, ahead);
        prefetch_f64_at(ow, ahead);
        prefetch_f64_at(ptm, ahead);
        prefetch_i64_at(offsets, ahead + 1);
    }
}
