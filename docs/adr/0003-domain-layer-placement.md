# ADR-0003: Domain-layer placement (in-kernel vs separate repository)

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** this Red Team close-out (P3). Not a customer contract.

## Context

SynAPS currently uses two incompatible placement patterns:

- **(a) In-kernel domain** — cable (`synaps/domains/cable/`, `docs/domains/cable.md`,
  CLI `cable-demo` / `cable-nervous-month`). Named weights `CABLE_PVC_WEIGHTS`
  do not mutate `DEFAULT_WEIGHTS`. Encode-first: metres → `base_duration_min`,
  drums as aux, campaign `earliest_start`.
- **(b) Separate repository** — GridPlan (energy ТОиР) and MobiRoute
  (accessible DARP / PDPTW). Kernel pin by SHA, own checker, own README,
  own application packet. Not imported under `synaps/domains/`.

Road-sign / C5a work is out of scope for this ADR.

## Decision drivers

| Question | In-kernel (a) | Separate repo (b) |
| --- | --- | --- |
| Does the domain have its own buyer, contest packet, or public showcase? | No — stays a kernel example | Yes — own README, `APPLICATION.md`, version |
| Independent checker (fail-closed, not the searcher)? | Kernel `FeasibilityChecker` is enough if constraints are MO-FJSP-SDST-ARC | Required if domain rules are not kernel algebra (crew/window/ЗИП, DARP pairing) |
| Separate funding / application? | No | Yes |
| Changes kernel algebra (new constraint class, new objective term in COVER, new status)? | Forbidden without a kernel RFC | Encode into existing algebra, or keep a domain checker. Do not silently extend COVER |
| Needs a different default branch, SBOM, or native crate? | Follows kernel | Own repo |
| Pin policy | N/A (it *is* the kernel) | SHA pin, never a floating branch tip |

## Decision

Use **(a)** only when all of the following hold:

1. The domain is an encoding of MO-FJSP-SDST-ARC (data + named weights + CLI demo).
2. There is no separate customer, contest, or product README.
3. Feasibility is the kernel notary (`FEASIBLE` ⇒ `proven_hard_violations = ∅`).
4. No new solver, heuristic, or COVER weight channel is introduced.

Use **(b)** when any of the following hold:

1. Own buyer / application / showcase.
2. Constraints the kernel checker does not own (GridPlan: outage windows, qualifications, spares-as-stock, frozen ПЛ; MobiRoute: pairing, wheelchair, driver).
3. Independent checker is part of the product claim.
4. Kernel must remain uncontaminated (no GridPlan/MobiRoute/AeroBIM under `synaps/domains/`).

Cable stays (a). GridPlan and MobiRoute stay (b). AeroBIM is a separate IFC product, not a SynAPS domain at all.

## Consequences

- Do not move GridPlan or MobiRoute into `synaps/domains/`.
- Do not add a road-sign domain in-kernel until P0–P2 of the 2026-08-26 honesty close are done (separate freeze).
- A domain that starts as (a) and later gains a buyer **must** split to (b); do not grow a second product README inside the kernel.
