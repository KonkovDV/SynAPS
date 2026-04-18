# Publication pack: SynAPS Habr v3

This file is a helper for publishing the main article draft:

- Draft: `docs/habr/synaps-open-source-habr-v3.md`
- Repo: https://github.com/KonkovDV/SynAPS

## Metadata

- Working title: Планирование без чёрного ящика: что реально умеет SynAPS и почему 50K пока не взлетел
- Alternative title A: APS без нейросети: портфель решателей SynAPS и честный 50K артефакт
- Alternative title B: Планирование, которое можно отлаживать: что SynAPS показывает на 50 000 операций
- Format: engineering deep dive (repo-grounded case)
- Habs: Open source, Python, Алгоритмы, Производство, Оптимизация
- Tags: APS, scheduling, CP-SAT, OR-Tools, ALNS, LBBD, RHC, white-box
- Complexity: сложная
- Target audience: industrial scheduling, OR, planning engineers, anyone who устал от "модель так решила"
- Voice constraints: Russian, no hype, no future-tense drift, keep boundaries explicit
- Short lead (2-3 sentences):
  - В производственном планировании важнее всего воспроизводимость и объяснимость решения. SynAPS - open-source APS-движок без нейросетевого чёрного ящика: конфигурации решателей явные, параметры фиксируемы, допустимость результата проверяется отдельно. В репозитории лежит честный JSON артефакт 50K прогона, который показывает текущий предел RHC в таймбоксе.
- One-sentence thesis:
  - SynAPS ценен не тем, что "победил на 50K", а тем, что даёт белый ящик с воспроизводимыми конфигурациями и артефактами, которые прямо показывают текущую инженерную границу.

## Source pack (for fact checks)

- Public solver registry: `synaps/solvers/registry.py`
- 50K study script: `benchmark/study_rhc_50k.py`
- Saved 50K artifact: `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`
- Scaling benchmark harness: `synaps/benchmarks/run_scaling_benchmark.py`
- Verification semantics: `synaps/validation.py` (see `verify_schedule_result()`)

## Claim register (for self-audit)

### Implemented

- 22 named solver configurations are public (registry-backed).
- Separate feasibility check exists and is part of the workflow.
- 50K study is reproducible and writes a JSON artifact next to code.
- CP-SAT multi-threading can break bit-for-bit reproducibility; single-thread is the safe mode.

### Target direction

- Narrowing the RHC candidate pool so that earliest-frontier is not "almost all" on 50K.
- Improving RHC-ALNS inner solve effectiveness under time pressure.

### Excluded (do not claim)

- "SynAPS solves 50K end-to-end today".
- "Production-ready" or "industrial validated" claims.

## Short-form assets

### Habr teaser (short)

SynAPS - open-source APS без нейросетевого чёрного ящика: выбираемые конфигурации решателей, фиксируемые параметры, отдельная проверка допустимости и артефакты прогона. В репозитории лежит воспроизводимый 50K JSON, который честно показывает предел текущего RHC в таймбоксе и метрики, по которым видно узкое место.

### Telegram teaser (short)

Я выложил в open-source SynAPS (APS без нейросетевого чёрного ящика) и написал разбор "почему 50K пока не взлетел". Там есть воспроизводимый 50K JSON артефакт и конкретные метрики RHC.

Статья: https://github.com/KonkovDV/SynAPS/blob/master/docs/habr/synaps-open-source-habr-v3.md
Repo: https://github.com/KonkovDV/SynAPS

### GitHub snippet (README / pinned issue)

If you want a repo-grounded, reproducible look at large-instance scheduling, start here:

- Habr draft (RU): `docs/habr/synaps-open-source-habr-v3.md`
- 50K study harness: `benchmark/study_rhc_50k.py`
- 50K saved artifact: `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`

## Final audit checklist

- Habr headings in the draft stay within H1-H3.
- No em dashes (U+2014) or curly quotes in the draft.
- D-score gate passes for the draft:
  - `npx ts-node scripts/habr-dscore-check.ts --draft external/SynAPS/docs/habr/synaps-open-source-habr-v3.md`
- No unsupported readiness claims.
- Numbers and file paths match the current repo state.
