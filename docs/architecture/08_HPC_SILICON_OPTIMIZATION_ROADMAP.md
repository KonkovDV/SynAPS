# 08 — HPC Silicon-Level Optimization Roadmap

> **Scope**: Extreme hardware-aware optimizations for `synaps_native` kernel, profiled against a concrete development machine.

<details><summary>🇷🇺 Краткое описание</summary>

Дорожная карта оптимизаций вычислительного ядра SynAPS на уровне кремния: branchless-программирование, настройка Rayon под гибридные P/E-ядра Raptor Lake, анализ кэш-иерархии DDR5, план внедрения явных AVX2+FMA3 интринсиков и будущий GPU-оффлоадинг.
</details>

---

## 1. Target Hardware Profile

Profiled on a development workstation (CPU-Z verified, April 2026):

| Component | Specification | Scheduling Implication |
|-----------|--------------|----------------------|
| **CPU** | Intel Core i5-13600KF (Raptor Lake) | Hybrid P/E architecture — asymmetric core speeds |
| **Cores** | 6P (5.1 GHz) + 8E (~3.9 GHz) = 20 threads | Work-stealing chunk size must be small (256) |
| **ISA** | MMX, SSE 1-4.2, SSSE3, EM64T, AES, AVX, AVX2, AVX-VNNI, FMA3, SHA | **No AVX-512** — hardware disabled on hybrid |
| **Cache L1** | 6×48 KB + 8×32 KB (data) | 288 + 256 = 544 KB total L1D |
| **Cache L2** | 6×2 MB + 2×4 MB | **20 MB total** — fits 50k SoA working set |
| **Cache L3** | 24 MB shared | Full 4.4 MB working set is L3-resident |
| **Memory** | 4×8 GB DDR5-6000 (Patriot 6000 Series, SK Hynix) | Dual-channel, 4 DIMMs |
| **RAM Timings** | **CL40**-40-40-80 (JEDEC baseline) | EXPO CL30 available but not active |
| **Motherboard** | Gigabyte B760 GAMING X (PCIe 4.0 x16) | Intel B760 chipset |
| **RAM Latency** | ~13.3 ns at CL40 / ~10.0 ns at CL30 (EXPO) | 67 / 50 empty CPU cycles at 5 GHz |

---

## 2. Implemented Optimizations (v0.3.0)

### 2.1 Branchless Overdue Boost

**Problem**: The RHC scoring kernel contained a conditional branch:
```rust
if slack <= 0.0 {
    pressure *= due_pressure_overdue_boost;
}
```
The `slack` value depends on due dates and is chaotic — approximately 50% positive, 50% negative. The branch predictor cannot learn this pattern, causing **~50% misprediction rate** with a penalty of 15–20 wasted pipeline stages per miss.

**Solution**: Replaced with branchless arithmetic:
```rust
let overdue = (slack <= 0.0) as u8 as f64;  // 0.0 or 1.0
let pressure = pressure * (1.0 + overdue * (due_pressure_overdue_boost - 1.0));
```

**Impact**: Compiles to a single `cmov` or comparison+blend instruction. Zero pipeline flushes. Expected **5–15% throughput gain** on the scoring inner loop at 50k+ scale.

### 2.2 Hybrid P/E Core Work-Stealing (RAYON_MIN_CHUNK = 256)

**Problem**: With `RAYON_MIN_CHUNK = 1024` and 50k elements, Rayon creates ~50 tasks distributed across 20 threads. Fast P-cores (5.1 GHz) complete their share ~30% faster than E-cores (~3.9 GHz) and then **idle**, waiting for the slowest E-core thread to finish (straggler effect).

**Solution**: Reduced `RAYON_MIN_CHUNK` from 1024 to 256. This creates ~195 tasks for 50k elements — enough for P-cores to "steal" unfinished work from E-core queues.

**Tuning rationale** (Blumofe & Leiserson 1999):
- At 256 elements/chunk: ~195 tasks for 50k → ~10 tasks/thread, good steal granularity
- Each chunk: 256 × ~30 ns/elem ≈ 7.7 μs compute — well above rayon overhead (~50–100 ns/steal)
- P-cores process chunks ~30% faster → steal ~2–3 extra chunks from E-core queues

**Impact**: Expected **10–25% wall-time reduction** at 50k+ scale on hybrid architectures.

### 2.3 target-cpu=native (AVX2/FMA3 Auto-Vectorization)

`.cargo/config.toml` enables LLVM to use AVX2/FMA3 instructions during auto-vectorization. The `fast_exp` computation and min-scan loop are primary beneficiaries.

**Critical**: The config explicitly targets `native` (which resolves to AVX2 on Raptor Lake), NOT AVX-512 which would cause `Illegal Instruction` on this hardware.

---

## 3. Near-Term Roadmap

### 3.1 Software Prefetch Hints (_mm_prefetch)

**Analysis**: The 7-stream SoA access pattern (`peo`, `d_off`, `rpt`, `ow`, `ptm` + CSR `offsets`/`indices`) exceeds the hardware prefetcher's typical 4–8 stream tracking limit. At DDR5 CL40, each cache miss costs ~67 CPU cycles.

**Proposed implementation**:
```rust
#[cfg(target_arch = "x86_64")]
unsafe {
    use core::arch::x86_64::{_mm_prefetch, _MM_HINT_T0};
    // Prefetch element i+8 while computing element i.
    // Distance 8: 8 × 8 bytes = 64 bytes = 1 cache line.
    if i + 8 < n {
        _mm_prefetch(peo_raw.as_ptr().add(i + 8) as *const i8, _MM_HINT_T0);
        _mm_prefetch(d_off_raw.as_ptr().add(i + 8) as *const i8, _MM_HINT_T0);
        _mm_prefetch(ow_raw.as_ptr().add(i + 8) as *const i8, _MM_HINT_T0);
    }
}
```

**Expected impact**: 5–10% at 500k+ scale where working set exceeds L3. Negligible at 50k (4.4 MB fits in L3).

**Dependency**: Rust `_mm_prefetch` API changed to const generics in Rust 1.78. Implementation gated on confirmed toolchain version.

### 3.2 Explicit AVX2+FMA3 SIMD Kernel

**Analysis**: LLVM auto-vectorization is conservative — the `fast_exp` bit trick and the conditional min-scan break vectorization. An explicit AVX2 kernel can process 4 `f64` elements per cycle across the batch dimension.

**Architecture** (4-wide processing):
```
For i in 0..n step 4:
    // Scalar: CSR min-scan (variable-length rows, not SIMD-friendly)
    emr[0..4] = [min_scan(csr_row(i+k)) for k in 0..4]

    // AVX2: vectorized pressure math (4 elements × 1 cycle)
    est_v   = _mm256_max_pd(peo_v, emr_v)
    slack_v = _mm256_sub_pd(doff_v, _mm256_add_pd(est_v, rpt_v))

    // FMA3: fused multiply-add for pressure base
    //   pressure = (ow / ptm) * fast_exp_avx2(-max(0, slack) / denom)
    base_v = _mm256_div_pd(ow_v, ptm_v)
    pressure_v = _mm256_mul_pd(base_v, fast_exp_avx2_v)

    // AVX2 branchless blend for overdue boost
    mask = _mm256_cmp_pd(slack_v, zero_v, _CMP_LE_OQ)
    boost_v = _mm256_blendv_pd(one_v, boost_v, mask)
    pressure_v = _mm256_mul_pd(pressure_v, boost_v)
```

**Vectorized fast_exp (Schraudolph AVX2)**:
```rust
#[target_feature(enable = "avx2")]
unsafe fn fast_exp_avx2(x: __m256d) -> __m256d {
    let a = _mm256_set1_pd(1048576.0 / core::f64::consts::LN_2);
    let b = _mm256_set1_pd(1072693248.0 - 60801.0);
    let clamp_lo = _mm256_set1_pd(-700.0);
    let clamp_hi = _mm256_set1_pd(700.0);
    let x = _mm256_max_pd(_mm256_min_pd(x, clamp_hi), clamp_lo);
    // a*x + b → cast to i64 → shift left 32 → reinterpret as f64
    let v = _mm256_add_pd(_mm256_mul_pd(a, x), b);
    let vi = _mm256_cvttpd_epi32(v);  // truncate to i32
    // ... bit manipulation to reconstruct IEEE-754 doubles
    // (requires AVX2 integer shifts on __m256i)
}
```

**Expected impact**: 2–4× throughput gain on the pressure math portion. Since the workload is memory-bound, net improvement is **1.5–2.5×** on top of Phase 1 optimizations.

**Status**: Code sketch. Requires stable Rust nightly-free `std::arch::x86_64` intrinsics and extensive testing with edge cases (NaN, subnormals, overflow).

### 3.3 Cache-Aligned Memory Allocation

Ensure NumPy arrays are allocated on 64-byte boundaries (cache line size) to prevent cache-line splits. NumPy's default allocator on modern systems typically provides 16-byte alignment, not 64.

```python
# In accelerators.py, replace:
np.asarray(data, dtype=np.float64)
# With:
np.require(np.asarray(data, dtype=np.float64), requirements=['C_CONTIGUOUS', 'ALIGNED'])
```

Or allocate via `numpy.empty()` with explicit `order='C'` and verify alignment:
```python
assert arr.ctypes.data % 64 == 0, "Array not cache-line aligned"
```

---

## 4. Future Vision

### 4.1 GPU Offload (CUDA / Vulkan Compute)

The RHC candidate scoring matrix is **embarrassingly parallel** — each candidate's score is independent. At N > 5,000,000, CPU bandwidth saturates even with optimal AVX2 utilization.

**Architecture**:
```
Python (NumPy/CuPy) → synaps_cuda (PTX kernel) → GPU
                    ↘ synaps_native (Rust/CPU) → CPU (fallback)
```

**Implementation path**:
1. `rust-gpu` crate for writing GPU shaders in Rust
2. `wgpu` / Vulkan Compute for cross-vendor support
3. `cudarc` crate for direct CUDA PTX execution
4. Tensor cores for `exp()` computation (specialized hardware units)

**Break-even point**: GPU offload becomes advantageous when N > ~500k due to PCIe transfer overhead (~5 μs baseline + 8 GB/s bandwidth). At N = 5M, GPU expected to be 50–100× faster than CPU.

### 4.2 BIOS-Level Optimization (DDR5 EXPO/XMP)

**Current state**: DDR5-6000 running at JEDEC CL40 (conservative defaults).
**Available**: EXPO-6000 profile with CL30 (SPD verified on Patriot 6000 Series modules).

**Impact estimation**:
- CL40 → CL30: latency reduction from ~13.3 ns to ~10.0 ns (25% improvement)
- For memory-bound workloads: **15–20% free speedup** without any code changes
- Particularly impactful for "ragged" CSR access patterns in `machine_available_offsets`

**Risk**: Requires motherboard BIOS configuration. No code changes needed.

---

## 5. Memory Bandwidth Analysis (i5-13600KF + DDR5-6000)

### Working Set at N = 50,000

| Buffer | Size | Access Pattern | Cache Residency |
|--------|------|---------------|-----------------|
| `machine_available_offsets` | 128 × 8 = 1 KB | Random (via CSR) | L1 ✓ |
| `emi_offsets` | 50,001 × 8 = 400 KB | Sequential | L2 ✓ |
| `emi_indices` | ~150k × 8 = 1.2 MB | Sequential/CSR | L2 ✓ |
| SoA arrays (5×) | 5 × 400 KB = 2 MB | Sequential | L2/L3 ✓ |
| Output arrays (2×) | 2 × 400 KB = 800 KB | Sequential write | L2/L3 ✓ |
| **Total** | **~4.4 MB** | | **L3-resident** (24 MB) |

On this hardware, the 50k working set fits entirely in L2+L3. The 20 MB of L2 cache (2 MB per P-core) means each P-core can hold its entire chunk locally. This is why the current implementation is already fast — and why further gains require silicon-level tricks rather than algorithmic changes.

### Theoretical Throughput

$$T(N) \approx T_{\text{overhead}} + \frac{N \cdot B_{\text{elem}}}{BW_{\text{eff}} \cdot P}$$

Where:
- $T_{\text{overhead}}$ = GIL release + rayon wakeup + numpy alloc ≈ 0.1–0.5 ms
- $B_{\text{elem}}$ ≈ 80 bytes/element
- $BW_{\text{eff}}$ ≈ 45 GB/s (DDR5-6000 dual-channel, practical)
- $P$ ≈ 0.75–0.90 (parallel efficiency with chunk=256 and work-stealing)

| N | Before v0.3.0 | After v0.3.0 | With AVX2 SIMD | Memory BW limit |
|------|-----------|-------------|---------------|-----------------|
| 10k | ~2–4 ms | ~1.5–3 ms | ~0.8–1.5 ms | ~0.15 ms |
| 50k | ~10–20 ms | ~6–12 ms | ~3–6 ms | ~0.7 ms |
| 100k | ~20–40 ms | ~12–24 ms | ~6–12 ms | ~1.4 ms |
| 500k | ~100–200 ms | ~60–120 ms | ~30–60 ms | ~7 ms |

---

## 6. Raptor Lake Specific Considerations

### 6.1 P-Core vs E-Core Asymmetry

| Property | P-Core (Golden Cove) | E-Core (Gracemont) |
|----------|---------------------|-------------------|
| **Frequency** | 5.1 GHz (turbo) | ~3.9 GHz |
| **L2 Cache** | 2 MB per core | 4 MB per 4-core cluster |
| **AVX2** | Full width (256-bit) | Full width (256-bit) |
| **Pipeline depth** | ~20 stages | ~16 stages |
| **OoO window** | 512 entries | 256 entries |

Both core types support AVX2 at full 256-bit width — the SIMD kernel will run correctly on both. The frequency difference (~30%) is handled by rayon work-stealing with small chunk sizes.

### 6.2 Why No AVX-512

Intel disabled AVX-512 on 12th–14th Gen hybrid processors. The E-cores (Gracemont microarchitecture) do not have AVX-512 execution units. Running an AVX-512 instruction triggers `#UD` (Illegal Instruction) fault.

Even on CPUs where AVX-512 is available (Xeon, older i9), it causes:
- **Frequency throttling**: 512-bit operations reduce clock by 10–20%
- **License switching**: transitioning to/from AVX-512 incurs ~10 μs penalty
- **Thermal pressure**: doubled power draw per vector operation

For SynAPS on Raptor Lake: **AVX2 is the ceiling**. The 256-bit width processing 4×f64 is the maximum vector throughput achievable.

### 6.3 DDR5-6000 Bandwidth Topology

With 4 DIMMs across 2 channels:
- **Theoretical peak**: 2 × 6000 MT/s × 8 bytes = 96 GB/s
- **Practical sustained**: ~45–55 GB/s (with interleaving overhead)
- **Random access**: ~15–25 GB/s (depends on DRAM page hit rate)

The CSR `machine_available_offsets` random access pattern (128 entries, 1 KB) fits entirely in L1 — no DDR5 bandwidth consumed for the random part.

---

## 7. Anti-Patterns

1. **Using AVX-512 intrinsics** on Raptor Lake or any hybrid Intel CPU → `Illegal Instruction`.
2. **Large rayon chunks** (1024+) on hybrid architectures → straggler effect from E-cores.
3. **Assuming uniform core speed** when computing expected wall-time → actual speedup is weighted by P/E core distribution.
4. **Ignoring BIOS memory settings** → 25% latency penalty from CL40 vs CL30.
5. **Premature GPU offload** at N < 500k → PCIe transfer overhead dominates.
