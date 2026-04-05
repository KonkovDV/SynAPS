---
title: "SynAPS Investor Pack Errata 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, investor, errata, docs]
mode: "reference"
---

# SynAPS Investor Pack Errata 2026-04

Date: 2026-04-05
Status: active
Scope: exact text-level corrections applied after the 2026-04-04 investor-pack slimming pass

## Why This Exists

The reduced investor layer shipped with three concrete issues:

1. mojibake in several active English-language surfaces;
2. benchmark wording that overstated what the current active evidence packet proves;
3. route ambiguity between the concise Russian summary and the preserved long Russian investor narrative.

This errata records the exact replacements and routing corrections applied on 2026-04-05.

## Exact Replacement Rules

| Old text or token | Replacement | Reason |
| --- | --- | --- |
| `вЂ”` | ` - ` or `-` depending on sentence context | mojibake from a mis-decoded dash |
| `Г—` | `x` | mojibake from a mis-decoded multiplication sign |
| `В§5` | `section 5` | mojibake from a mis-decoded section sign |
| `В№`, `ВІ`, `Ві`, `вЃґ`, `вЃµ` | removed from inline prose; source numbering stays in the Sources block | mojibake from broken footnote markers |
| `[Р“Р›РћРЎРЎРђР РР™ (RU)](...)` | `[GLOSSARY (RU)](...)` | broken bilingual link label |
| `tiny 3Г—3` | `tiny 3x3` | broken instance-size label |

## Claim Corrections Applied

The active benchmark evidence packet and technical verification report currently support only the verified smoke-instance result on `tiny_3x3.json`:

- `GREED`: `106.67` minutes
- `CPSAT-10`: `82.0` minutes
- delta: `24.67` minutes or approximately `23.1%`

Therefore the following wording was replaced in active investor docs:

| Old wording | New wording |
| --- | --- |
| `CP-SAT solver produces schedules 42% faster than the greedy baseline, and the LBBD solver achieves a 45% makespan reduction on medium-stress instances` | `on the verified smoke instance, CPSAT-10 improves makespan from 106.67 to 82.0 minutes, or about 23.1% versus GREED; broader benchmark coverage remains open` |
| `CP-SAT на 42% быстрее жадного базового решения, а LBBD достигает 45% снижения makespan на средненагруженных задачах` | `на верифицированном smoke-инстансе tiny_3x3 CPSAT-10 улучшает makespan с 106.67 до 82.0 минут, то есть примерно на 23.1% относительно GREED; более широкая benchmark-картина остаётся открытой` |

## Route Corrections Applied

1. `HYPER_DEEP_REPORT_2026_04_RU.md` is now treated explicitly as the concise Russian summary surface.
2. The preserved full Russian investor narrative is routed through the archive copy of `HYPER_DEEP_REPORT_2026_04_RU_v2.md`.
3. Default technical reading routes now point first to `VERIFICATION_COVERAGE_AUDIT_2026_04.md`, while `HYPERDEEP_AUDIT_REPORT_2026_04.md` remains available as an optional deep-audit surface.

## Why The Technical Route Changed

`HYPERDEEP_AUDIT_REPORT_2026_04.md` was rewritten into a readable active summary during the same 2026-04-05 hardening pass, and the raw historical snapshot was preserved in the archive.

For the bounded active technical route, the cleaner order is:

1. `TECHNICAL_VERIFICATION_REPORT_2026_04.md`
2. `CLAIM_EVIDENCE_REGISTER_2026_04.md`
3. `VERIFICATION_COVERAGE_AUDIT_2026_04.md`
4. `HYPERDEEP_AUDIT_REPORT_2026_04.md` when a second-pass fact-check surface is needed

## Files Corrected In This Pass

1. `docs/investor/README.md`
2. `docs/investor/README_RU.md`
3. `docs/investor/HYPER_DEEP_REPORT_2026_04_RU.md`
4. `docs/investor/HYPER_DEEP_REPORT_2026_04_RU_v2.md` (removed from active tree; archive copy retained)
5. active English investor router surfaces and glossary/market references
6. `docs/investor/TECHNICAL_VERIFICATION_REPORT_2026_04.md`
