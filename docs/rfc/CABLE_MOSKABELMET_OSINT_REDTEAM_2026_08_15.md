# Moskabelmet OSINT + algebra/code Red Team — 2026-08-15

Hostile pass on public plant narrative, vendor APS claims, cable-domain
encode-first, COVER exhaust-stay, and the 1 600-order nervous month.
Claim level: **experiment**. Not live MES. Not INFIMUM. Not SOTA.

Fetched 2026-08-15. Primary pages, not recaps.

## Verdict

**ship with residuals.** Public Moskabelmet pain is real and mostly
*policy + PDM + SMED + MES*, not a missing kernel constraint. SynAPS
now has an honest encode-first cable adapter and a **COVER-feasible**
synthetic month at 8 and 16 machines/stage. That does **not** mean
SynAPS plans Moskabelmet, matches INFIMUM, or measured −24% drums.

C5a stays gated: leftover calendar on the tight shop was setup minutes,
not drum hold. Exhaust stay (Mahmoodi/Dooley + Flynn) closed coverage
without opening the kernel.

## 1. Entity map (do not collapse the group)

| Legal / brand | What the public record actually is | Trap |
|---------------|-------------------------------------|------|
| ГК «Москабельмет» | Holding, 2-я Кабельная д. 2, Moscow. MTO cable/wire, 125 years (2020). | Treating holding KPI as one shop |
| «Завод Москабель» | FCK/LEAN pilot 2021–22: freeze, drums 80→61, MAPRE/Drum Twister SMED, +46M ₽, +20% output without new lines | Mixing with Fujikura |
| «Москабель-Фуджикура» | Separate FCK plant: stranding WIP 124→52 km (−58%), cycle 8→5 days (−30%) | Not the 3-day freeze story |
| ООО «МОСИТЛАБ» | Internal IT: 1С:КоМод, MES, СОКОЛ, Периметр RFID, Печкин, APS INFIMUM | APS ≠ PDM ≠ RFID |

Primary: [Ruscable FCK film 2022-11-14](https://www.ruscable.ru/news/2022/11/14/_Faktor_proizvoditelynosti_bolyshoj_filym_o_bolysh/),
[FCK Fujikura](https://производительность.рф/presscenter/news/moskovskij-zavod-moskabel-fudzhikura-blagodarya-resheniyam-fck-na-tret-uvelichil-skorost-proizvodstva-produkcii/),
[mKM.ru INFIMUM 2.0 2024-11-14](https://www.mkm.ru/news/-MOSITLAB--PREDSTAVLYAET-NOVUYU-VERSIYU-APS-INFIMUM/).

## 2. Pain stack (OSINT, with algebra)

Plant pain is a **stack**. APS sits near the top. Collapsing it into
“need a faster solver” is the first Red Team miss.

| Layer | Public fact | Source | SynAPS isomorphism | Honesty gap |
|-------|-------------|--------|--------------------|-------------|
| Margin | Standard SKU 2–3%; materials ≤80% of cost; specialised 10–15% after PDM | [CFO Russia 2025-10-08](https://www.cfo-russia.ru/stati/?article=94367) (Yan Anisov) | `material_loss` on SDST; `CABLE_PVC_WEIGHTS.material=1.0` | GREEDY/COVER **do not** search those weights (C-R1) |
| Quote funnel | 10–15 of 100 enquiries become orders | same | not modelled | Sales/ATP, not FJSP |
| PDM | 1С:КоМод: specs/routings in minutes; project sales ×4.6; registry №2023662428 | [Ruscable 2026-06-02](https://www.ruscable.ru/news/2026/06/02/_mositlab_poluchil_premiu_lidery_tsifrovizatsii_/) | `Order.quantity` stores metres; kernel ignores it | APS without PDM is blind (C0) |
| Stages | 4–25 process stages; tens of thousands of SKUs; MTO only | CFO 2025; Moriyakov on GIA 2025 | 6-stage nervous month; `predecessor_op_id` inside one reel | Cross-order WIP feed illegal (C5d) |
| Rush inserts | Emergency order → extra drum, crane, setup, park WIP | [Ruscable 2022-11-22](https://www.ruscable.ru/article/ruscable/faktor_proizvoditelnosti_moskabelmet_den/) | `freeze_horizon_end` + `allow_freeze_break` | Boolean policy, not ACL (C-R7) |
| Freeze | 3-day frozen plan: drums **80→61 (−24%)** while output **+20%** | same; FCK national project | C1 repair freeze; nervous waves 72 h + 7 d | Directional KPI only. Do not claim −24% |
| SMED | MAPRE full clean+screw **405→346 min** (79/year); Drum Twister **311→138 min** (−56%, 180/year) | same article | parametric 240/360/400/120 | Order of magnitude, not stopwatch (C-R5). Shop SMED ≠ sequencing |
| Tare / drums | Shortage of take-up drums; expensive, floor space, forklift tetris | same | Cumulative `[start−σ, end)`; `peak_wip_drums` = reel span | Occupancy ≠ WIP (C-R2 / C5a) |
| Lot combining | INFIMUM “launches −10×”; 2.0 auto-batches by due similarity + tare capacity + alt routes | CFO 2025; [mKM.ru 2024-11-14](https://www.mkm.ru/news/-MOSITLAB--PREDSTAVLYAET-NOVUYU-VERSIYU-APS-INFIMUM/) | campaign `earliest_start` snap | Not merge. Cross-order predecessors rejected |
| Nervousness | INFIMUM 2.0: continuity with previous plan for nearest shifts | mKM.ru 2024-11-14 | Hamming \(R\) on `(wc, start)` | Functional, not search term |
| MES / RFID | Terminals + e-sign; Периметр RFID zone crossing; MAGNETAG cable | [Ruscable 2022-07-25](https://www.ruscable.ru/news/2022/07/25/Totalynyj_kontroly_novaya_razrabotka_ot_Moskabely/) | out of kernel | Prysmian Alesea class (C-R8) |
| Vision QA | talc, geometry, insulation defects (СОКОЛ) | CFO 2025 | out of kernel | Not APS |

LEAN article is explicit: after freeze, **administrative** setup-count
reduction was treated as exhausted; remaining MAPRE minutes were
*internal/external SMED*, not a new dispatcher.

Fujikura FCK (stranding WIP −58%) is a **different shop**. Do not add
it to the Zavod Moskabel freeze arithmetic.

## 3. Vendor APS ledger (unpublished algebra)

INFIMUM is in-house MOSITLAB. No paper, no instance, no checker, no
reproducible run. Treat every number below as **marketing**.

| Claim | Where | Why it is not a SynAPS target |
|-------|-------|-------------------------------|
| Envelope: 50k ops, 50 lines, 10k setups, 50 stages, 90-day horizon | [Ruscable 2023-04-26](https://www.ruscable.ru/news/2023/04/26/APS_INFIMUM__novaya_razrabotka_MOSITLAB_/) | Capacity postcard. 2023 Q1 effect “19M ₽” is not a model |
| First-4 criteria (paraphrase): due dates, utilisation, fewer changeovers, combine semi-finished lots | CFO 2025-10-08 | Matches C3/C4 *intent*, not encoding |
| 2.0 extras: scrap metres; shift continuity; tare turnover | mKM.ru 2024-11-14 | `material_loss`, Hamming \(R\), \(D_{\max}\) — last two not in search |
| 39 000 ops / 40 min | same | Different model. SynAPS 20 316 cover is 4–14 s list-schedule, not a bake-off |
| Launches −10×; output +8% without capex; turnover 10–15B ₽ | CFO 2025 | No instance |
| 2.0 OEE +1.2%; scrap −26%; waste weight +3.4% margin/year | mKM.ru 2024-11-14 | Internal vs previous INFIMUM, not vs SynAPS |
| Combined v1+v2 vs no-APS: output +9.8%, OEE +9.3%, margin +10.2% | [Ruscable TAdviser 2024-12-24](https://www.ruscable.ru/news/2024/12/24/Novaya_APS_INFIMUM_predstavlena_na_TAdviser_SummIT/) | **Stacked baseline**. Do not add to 2.0 +1.2% OEE |
| +78M ₽/year margin; time loss −46%; net profit +8%; 27 days/year | [mKM.ru GIA 2025-12-09](https://www.mkm.ru/news/APS-INFIMUM-PRIZNANA-INNOVATSIEY-GODA/); [Ruscable Insider 2026-08-03](https://www.ruscable.ru/news/2026/08/03/_supersily_promyshlennogo_masshtaba_moskabelymet_/) | Award copy. Algebra unpublished |
| “No ready IT tool of this depth exists” | GIA page | False as a market sentence: ADVARIS Cable exists since 1997. True only as *Russian in-house* |

2023 Anisov quote already names three of the later “golden” criteria
(setup time, due dates, near-horizon continuity). 2.0 added scrap,
tare turnover, and auto-batching — not a new physics.

## 4. Algebra encoded vs plant / papers

Hard FEASIBLE contract unchanged. Grain `max(1, ceil(base/speed))`.

| Plant / paper | Formula or rule | In SynAPS? |
|---------------|-----------------|------------|
| Length → time | \(p_o=\max(1,\lceil L_{\text{reel}}/v_{\text{stage}}\rceil)\) | Adapter writes `base_duration_min`. Kernel still ignores `Order.quantity` |
| Zhu et al. *Processes* 14(5):769 (2026) | \(n_j=\lceil L_j/L_{\text{reel}}\rceil\), sequential sub-reels | **Pre-split**, not a search decision (C5c gated) |
| Additive SKU SDST | \(\sigma=\sigma_{\text{Cu}}+\sigma_{\text{ins}}+\sigma_{\text{sec}}+\sigma_{\text{col}}\) | `setup_transition` **adds** all deltas. Plant often pays **one** dominant change (head **or** colour). Over-counts stacked SKU jumps |
| MAPRE 405/346, DT 311/138 | hours-scale SMED | Parametric 240/360/400 is the same **order**, not those numbers |
| Drum processing | Cumulative on \([s-\sigma, s+p)\) | Default `hold_semantics=processing_only` |
| Drum WIP | \(D(t)=\|\{c:S_{\text{first}}(c)\le t<C_{\text{last}}(c)\}\|\), \(D_{\max}=\max_t D(t)\) | `peak_wip_drums` only. Not CP-SAT |
| Freeze | issued \(s_o < t_{\text{freeze}}\) immutable except breakdown | `frozen_ids_for_repair`; `pin_issued_plan` on first solve |
| Stability | \(R=\) share of baseline ops whose `(wc,start)` moved | `assignment_hamming`, in `[0,1]` |
| INFIMUM lot combine | merge across `order_id` by due similarity + tare | **Illegal** today. Campaign snaps `earliest_start` |
| Kolisch 1996 | parallel SGS = non-delay | Native cover append-only; `gap_inserted=0` at month scale |
| Artigues/Lopez/Ayache 2005 | insertion SGS is active under SDST | Python insertion capped; hung at month scale (killed) |
| Lee–Bhaskaran–Pinedo ATCS | k1/k2 look-ahead, not floor jump | Window 0 default. General window 240 collapsed 16-stage (0.986) |
| Mahmoodi/Dooley IJPR 1991; Flynn JOM 1987 | exhaustive family; stay on hot machine | `cover_atcs_exhaust_window` + `prefers_cover_slot` when exhaust>0 |
| Schaller/Gupta cells | dedicated family + overflow | mix-sized PVC/XLPE + 1 flex; colour cells **opt-in** (hurt 8-stage) |

Budget that closed 8-stage coverage (seed=1, 20 316 ops, processing
385 818 min, calendar 2 073 600 min):

\[
\bar\sigma \le \frac{2\,073\,600 - 385\,818}{20\,316} \approx 83\ \text{min/op}.
\]

Observed: FIFO ~175; family+wheel without stay ~99; **exhaust stay 49.1**.
C5a does not add those minutes. Pool 48→96 identical placement.

## 5. Attacks that had to land

| Attack | Result |
|--------|--------|
| Collapse ГК / Завод Москабель / Фуджикура / МОСИТЛАБ | **blocked** — freeze −24% drums is Zavod Moskabel; Fujikura −30% cycle is another FCK; INFIMUM is MOSITLAB |
| Quote 10–15/100 as an APS KPI | **blocked** — CFO text is the sales funnel before PDM |
| 1С:КоМод as a scheduler | **blocked** — PDM/routings. APS is INFIMUM |
| Периметр RFID as COVER | **blocked** — zone crossing into 1С. C-R8 |
| MAPRE 405→346 as adapter constants | **blocked** — SMED card + preheat, not SDST table |
| Additive SDST as plant truth | **lands as residual** — stacked colour+section+insulation can exceed a single head change |
| INFIMUM 39k/40 min = SynAPS 20k/4 s | **blocked** |
| Stack TAdviser +9.8% with 2.0 OEE +1.2% | **blocked** — different baselines |
| +78M ₽ / 27 days / −46% time as SynAPS evidence | **blocked** |
| “No cable APS exists” from GIA copy | **blocked** — ADVARIS exists; honest sentence is “no OSS cable APS” |
| 50k GREEDY_COVER as cable | **blocked** — April `50k_scale_academic_audit.md` named Moskabelmet as a scale metaphor; August plan forbids the mix |
| C5a “for 8-machine cover” | **falsified** — stay cut \(\bar\sigma\) 98→49; drums unchanged |
| General ATCS floor window = exhaust | **blocked** — exhaust is continuation-only + hot-machine stay |
| Colour cells close 8-stage | **falsified** — coverage 0.854 vs FEASIBLE without cells |
| Family lines as 16-stage default | **blocked** — tardiness 3 670 > 1 922; opt-in at 16, auto-on at ≤8 |
| Campaign snap-to-due | **closed** 2026-08-14 — gate is min release in `(state, due-slot)` |
| `allow_freeze_break` as security | **lands** — boolean. Any caller can set true |
| `CABLE_PVC_WEIGHTS` on COVER | **lands** — construction ignores the vector |
| \(D_{\max}\) vs pool 96 | **lands** — 16-stage cover-only WIP 94 (ATCS) to 265 (FIFO-era); still a functional |
| 8-machine FEASIBLE without notary | **closed this pass** — exhaustive notary 0, stabilize True, clipped 0 (seed=1, 2026-08-15) |
| 8-machine FIFO is FEASIBLE | **blocked** — FIFO coverage 0.50 |
| Seed=1 as a distribution | **lands** — N-R6 still open |
| Native wheel on py3.12 while probes use 3.13 | **lands as ops residual** — maturin defaulted to 3.12; probes used `C:\py313` junction |
| Zhu −9.8% makespan / 18 h→0.83 h repair | **blocked** — their ACO-VNS, their data |
| Processes 2025 AMR 15% makespan | **blocked** — C5b/C-R8 |
| Cross-order `predecessor_op_id` to fake 10× launches | **blocked** by validator (C5d) |

## 6. Closed this pass (code + probes + OSINT)

| ID | Close |
|----|-------|
| N-R1 1600@8 | COVER-feasible: family flex + 6-colour wheel + exhaust stay. 20 316/20 316, 4.3–4.7 s, \(\bar\sigma=49.1\), tardiness 87 134, notary 0, `temporal_stabilization_converged=1` |
| Exhaust ≠ window | `cover_atcs_exhaust_window` scores setup-0 continuations; `prefers_cover_slot` keeps the hot machine. 16-stage exhaust stays 0 (tardiness **1 922** unchanged) |
| Colour-within-family | Implemented and tested; **not** the 8-stage default |
| OSINT entity split | This RFC. Fujikura FCK must not feed Zavod freeze arithmetic |
| C5a gate note | Algebra + pool 48→96 + exhaust stay. Still gated |

Tests: `tests/test_rhc_cover.py` (jump / window / exhaust / hot-machine),
`tests/test_domain_cable.py` (family mix, colour-within-family, tight-shop
defaults), `tests/test_cli.py` tiny GREED month.

## 7. Live residuals (honest)

| ID | Sev | Finding | Why it stays |
|----|-----|---------|--------------|
| C-R1 | P1 | COVER/ATCS ignore `CABLE_PVC_WEIGHTS` | Wiring it in would change universal construction. Plant scrap pain is therefore **measured**, not **searched** |
| C-R2 | P1 | \(D_{\max}\) ≠ Cumulative | Hold-until-successor is C5a. 8-stage cover did not need it |
| C-R4 | P2 | Campaign ≠ INFIMUM batching | Snap `earliest_start`. No foreign genealogy |
| C-R5 | P2 | Additive parametric SDST | May over-penalise stacked SKU jumps vs one physical head change |
| C-R7 | P2 | Freeze break is a flag | Policy, not cryptography |
| C-R8 | P2 | RFID / blocking / AMR | Out of kernel |
| C-R9 | P1 | 8-stage tardiness 87 134 vs 16-stage 1 922 | Coverage closed; due-date quality did not. Plant CFO pain is still tardiness |
| C-R10 | P2 | Exhaust stay can prefer a later hot machine | Unit test asserts that. Month-scale tardiness is the cost |
| N-R6 | P2 | seed=1 only | No CI over 1..5 |
| N-R3 | P2 | Wave “full resolve” is the same instance | Not a new parent dump except `new_rush` |
| OPS-WHEEL | P2 | cp312 vs cp313 native | Documented; probes used 3.13 |
| PDM | P0 | No 1С/MES ingest | Encode-first by design |

## 8. Forbidden claims (repeat)

Do not add: INFIMUM 39k/40 min, 50k/50 lines/90 days, +78M ₽, 27 days,
−46% time, launches −10×, output +8%, TAdviser +9.8%/+9.3%/+10.2%,
Zhu −9.8% makespan, Prysmian drum −25%, Fujikura −30% as Zavod freeze,
FCK +46M ₽ as APS, SynAPS 499 770/145 s as cable, N-1, SAIDI, SOTA,
“we replaced INFIMUM”, “SynAPS now plans Moskabelmet”, “−24% drums
measured on the generator”, “8-machine FIFO is FEASIBLE”.

## 9. Next honest step

C6a (multiseed 1..5 @1600×8 cover+notary) and C6b (freeze-pair seeds 1–2)
are **done**. Occupancy 21 ≪ pool 48 ≪ span 155–222; rush WIP Δ flips
sign. Next is C6c weighted residual/ALNS on a downscaled instance. Do
not open C5a. Do not ingest 1С. Plan: `CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`.

## Sources (retrieved 2026-08-15)

- [CFO Russia, Anisov, 2025-10-08](https://www.cfo-russia.ru/stati/?article=94367)
- [Ruscable, «Фактор производительности», 2022-11-22](https://www.ruscable.ru/article/ruscable/faktor_proizvoditelnosti_moskabelmet_den/)
- [Ruscable, FCK film, 2022-11-14](https://www.ruscable.ru/news/2022/11/14/_Faktor_proizvoditelynosti_bolyshoj_filym_o_bolysh/)
- [Ruscable, FCK stage 2, 2023-02-01](https://www.ruscable.ru/news/2023/02/01/_Proizvoditelynosty_truda_chasty_2_novyj_etap_ra/)
- [FCK, Moskabel-Fujikura](https://производительность.рф/presscenter/news/moskovskij-zavod-moskabel-fudzhikura-blagodarya-resheniyam-fck-na-tret-uvelichil-skorost-proizvodstva-produkcii/)
- [Ruscable, INFIMUM launch, 2023-04-26](https://www.ruscable.ru/news/2023/04/26/APS_INFIMUM__novaya_razrabotka_MOSITLAB_/)
- [mKM.ru, INFIMUM 2.0, 2024-11-14](https://www.mkm.ru/news/-MOSITLAB--PREDSTAVLYAET-NOVUYU-VERSIYU-APS-INFIMUM/)
- [Ruscable, TAdviser SummIT, 2024-12-24](https://www.ruscable.ru/news/2024/12/24/Novaya_APS_INFIMUM_predstavlena_na_TAdviser_SummIT/)
- [mKM.ru, GIA, 2025-12-09](https://www.mkm.ru/news/APS-INFIMUM-PRIZNANA-INNOVATSIEY-GODA/)
- [Ruscable, AOIP, 2025-11-06](https://www.ruscable.ru/news/2025/11/06/Realynoe_primenenie_II_v_kabelynom_proizvodstve_O/)
- [Ruscable Insider, 2026-08-03](https://www.ruscable.ru/news/2026/08/03/_supersily_promyshlennogo_masshtaba_moskabelymet_/)
- [Ruscable, КоМод award, 2026-06-02](https://www.ruscable.ru/news/2026/06/02/_mositlab_poluchil_premiu_lidery_tsifrovizatsii_/)
- [Ruscable, Периметр RFID, 2022-07-25](https://www.ruscable.ru/news/2022/07/25/Totalynyj_kontroly_novaya_razrabotka_ot_Moskabely/)
- Zhu et al., *Processes* 14(5):769 (2026), doi:10.3390/pr14050769
- Zhu et al., *Mathematics* 13(8):1235 (2025), doi:10.3390/math13081235
- Mahmoodi & Dooley, *Int. J. Prod. Res.* 29(9):1923–1939 (1991)
- Flynn, *J. Oper. Manag.* 7(1–2):203–216 (1987)
- Kolisch, *Eur. J. Oper. Res.* 90 (1996); Artigues, Lopez, Ayache, *Ann. Oper. Res.* (2005)
