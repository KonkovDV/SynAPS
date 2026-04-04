# Pitch Memo: SynAPS (Industry-Agnostic APS Platform)
**Date:** April 2026
**Sector:** Industrial Optimization / Advanced Planning & Scheduling

## 1. Executive Summary
 SynAPS - отраслево-независимая APS-платформа для дискретно-непрерывного производства. Продуктовая идея состоит в том, чтобы переводить физически разные предприятия в единое математическое представление задач класса flexible job shop scheduling и решать их целевым гибридным стеком: детерминированный исполнительный слой должен гарантировать физическую корректность плана, а AI/XAI-слой ищет более выгодные маршруты, последовательности и режимы загрузки.

Ключевая гипотеза продукта: универсальное оптимизационное ядро может монетизироваться не через одну отраслевую модель, а через общий planning-kernel, который параметризуется под металлургию, фарму, FMCG, электронику и другие производственные домены через universal schema и domain-specific constraints.

## 2. Market Pain Point
Большинство производственных APS-инициатив ломаются на двух уровнях:

1. доменная модель слишком жёстко привязана к одной индустрии и плохо переносится на другую операционную среду;
2. планировщик либо остаётся набором ручных правил, либо превращается в непрозрачный ML-слой без физически строгих ограничений.

В результате предприятие теряет деньги на скрытых переналадках, локальных аварийных пересчётах, несогласованной работе с дефицитной оснасткой и энергопотреблении, а каждая новая площадка требует почти новой системы, а не параметризации общей платформы.

## 3. Why Now

Почему этот тезис может стать продуктом именно сейчас:

1. публичные APS-инкамбенты по-прежнему продают finite-capacity scheduling, rescheduling, scenario analysis и integration, то есть рынок подтверждает важность именно planning kernel, а не абстрактной AI-обёртки;
2. Google OR-Tools и академический baseline по-прежнему подтверждают, что constraint-grounded scheduling остаётся канонической вычислительной основой для серьёзного производственного планирования;
3. NIST AI RMF и OT guidance усиливают ценность explainable, bounded, audit-friendly AI вместо непрозрачного black-box execution;
4. mature open models и on-prem inference stack делают advisory AI layer практически реализуемым без отказа от perimeter-controlled deployment.

## 4. SOTA Solution
SynAPS формализует операционный контур как графовую задачу расписаний. Базовая каноническая форма - `MO-FJSP-SDST-ARC`, а при явном учёте потерь сырья и материалов - расширение до `MO-FJSP-SDST-ML-ARC`.

Архитектурно решение делится на два слоя:

* **Deterministic Core:** целевой constraint layer, который должен проверять прецедентность операций, ограничения мощностей, занятость ресурсов, доступность оснастки и физическую реализуемость расписания.
* **AI / XAI Advisory Layer:** оценивает пространство допустимых решений, подсказывает более выгодные последовательности и объясняет, почему выбранный маршрут уменьшает переналадки, потери или просрочки.

На уровне solver stack продуктовая стратегия строится как hybrid optimization:

* быстрый эвристический слой для глобального распределения;
* точные solver-подзадачи для bottleneck-узлов;
* incremental repair вместо полного пересчёта расписания при локальном сбое;
* on-prem LLM copilot как операторский интерфейс к ERP/MES-данным и статусу плана.

## 5. Technological Moat / Defensibility
* **Universal Operations Abstraction:** единая бизнес-модель поверх общего SQL/DDD-ядра с параметризацией отраслевых ограничений через domain attributes, setup matrices, auxiliary resources и policy packs.
* **Hybrid Solver Portfolio:** сочетание эвристик, exact-подзадач и последующей академической эволюции к Logic-Based Benders Decomposition для критических bottleneck-машин.
* **Incremental Repair Instead of Full Replanning:** локализация радиуса поражения и хирургическая починка расписания вместо глобального коллапса при аварии.
* **Auxiliary Resource Awareness:** планирование не только сырья и операций, но и дефицитной оснастки, тары, форм, штампов и ремонтных окон.
* **Research Runway:** HGAT для потерь агрегации, Digital Twin на DES, Offline RL для безопасной политики ремонта, federated learning для холдинговой оптимизации без обмена чувствительными данными.

## 6. Market Opportunity
Платформа ориентирована на предприятия, где плановая ошибка быстро конвертируется в денежный убыток: металлургия, фармацевтика, FMCG, электроника, энергетика, сборочные, рецептурные и другие resource-constrained цепочки. Ценность возникает не из "AI ради AI", а из конкретных экономических рычагов:

* минимизация sequence-dependent setup time;
* сглаживание энергопотребления по тарифным окнам;
* снижение простоев из-за локальных аварий и перепланирования;
* лучшее использование оборотной оснастки и вспомогательных ресурсов;
* сокращение скрытых потерь при переходах между партиями, сплавами, рецептурами и кассетами.

## 7. Business Model & GTM
* **Модель:** platform license + implementation/integration revenue + recurring support for optimization packs.
* **Packaging:** универсальное ядро продаётся как отраслево-независимая APS-платформа, а monetization усиливается вертикальными constraint packs для конкретных производств.
* **Pricing:** лицензирование по площадкам, числу производственных контуров, depth of optimization и premium-модулям вроде digital twin, energy scheduling и multi-site learning.
* **GTM:** сначала сложные multi-stage производства с высокими setup-cost и bottleneck economics, затем масштабирование через reusable schema, benchmark pack и pilot-to-rollout motion.

## 8. Traction
На текущий момент этот репозиторий фиксирует SynAPS как venture thesis и архитектурно-математическую формализацию, а не как уже реализованный APS runtime. Наиболее сильная текущая часть - не продуктовые KPI, а качественно сформулированный product kernel:

* универсальная экономическая логика для разных производственных доменов;
* явная математическая постановка scheduling-задачи;
* понятная траектория эволюции от heuristic core к академически валидируемому hybrid stack.

Текущая техническая поверхность SynAPS уже даёт первую полноценную доказательную базу: universal schema, solver baseline, benchmark harness, domain examples и research docs. Но digital twin runtime, industrial connectors, broad benchmark corpus, pilot evidence и quantitative head-to-head validation всё ещё относятся к следующему этапу, а не к уже подтверждённой production-grade реализации. После M1 hardening тестовый suite проходит `27/27`, а SDST-паритет закрыт для exact solve, repair и feasibility checking. При этом auxiliary-resource semantics пока доказаны как truth-gate constraint в feasibility checking, а не как полностью реализованная constructive solver-модель во всех текущих путях.

Дополнительно в этом pass был повторно подтверждён standalone proof path: SynAPS прошёл Python `pytest`, targeted `ruff` gate, package build, `twine check`, smoke benchmark и rehearsal без обязательной зависимости от `docs/investor/`.

## 9. Risks and Mitigations

* **Risk: proof gap between architecture and field ROI.**
	Mitigation: build a source-backed market model, broader benchmark family, and pilot KPI protocol before upgrading external claims.
* **Risk: scope inflation toward full-suite APS parity.**
	Mitigation: keep the product framed as an APS kernel and platform foundation, not as an end-to-end supply-chain suite.
* **Risk: auxiliary-resource semantics are not yet fully solver-native across all constructive paths.**
	Mitigation: keep this called out explicitly, maintain truth-gate semantics, and prioritize staged solver hardening.
* **Risk: enterprise integration burden dominates pure optimization value.**
	Mitigation: treat ERP/MES and shop-floor seams as first-class product surfaces instead of late implementation detail.
* **Risk: dependency freshness and runtime hardening lag behind publication polish.**
	Mitigation: keep publication readiness and dependency-upgrade work as separate programs with separate verification gates.

## 10. Claim Confidence
* **C1 (Hypothesis):** TAM/SAM/SOM, cross-industry portability, unit economics внедрения, federated learning network effects, and long-range research upside.
* **C2 (Internal Specification):** формализация проблемы, архитектурная декомпозиция продукта, universal schema, solver baseline, benchmark harness и research roadmap описаны достаточно чётко для roadmap planning и investor discussion.
* **C3 (External Validation):** KPI uplift по throughput, setup reduction, energy smoothing, local repair latency, solver superiority и benchmark leadership требуют pilot data, benchmark pack и внешнего сравнения.

## 11. Internal Evidence Snapshot
* **Current repo truth:** SynAPS now has a visible technical codebase with universal schema DDL, domain examples, Python solver baseline, benchmark harness, CI scaffolding, and research documentation.
* **What is not yet proven:** digital twin runtime, industrial connectors, broad benchmark corpus, pilot KPI evidence, quantitative comparison against named APS alternatives, and full solver-side auxiliary-resource modeling across all constructive paths are still missing as production-grade evidence.
* **Evidence boundary:** current artifacts support the product-kernel thesis and technical direction, but they do not yet prove deployment-grade scheduling superiority or customer ROI.
* **Required next evidence pack:** source-backed TAM/SAM/SOM model, broader benchmark family, DES simulator, pilot KPI protocol, and quantitative comparison against existing APS alternatives. A qualitative competition baseline is now captured in `docs/investor/MARKET_COMPETITION_REPORT_2026_04.md`, while the current proof path includes `27/27` passing tests and a working benchmark harness.

## 12. Market Data Assumptions
* Все TAM/SAM/SOM и profitability claims в документе являются рабочими оценками до source-backed market model.
* Для investor-ready версии обязательны: дата, источник, сегментация по индустриям, сценарии Conservative/Base/Upside и separation between platform revenue and services revenue.
* Численные обещания вроде "2% uplift" или "repair in 3 seconds" должны появляться только после benchmark protocol и pilot evidence.

## 13. Compliance Scope
* Базовый продуктовый контур предполагает on-prem или perimeter-controlled deployment, потому что производственные ERP/MES-данные и плановая логика часто не могут покидать контур предприятия.
* Для отраслевых пакетов потребуется отдельная compliance mapping по доменам: GMP/GxP и auditability для фармы, traceability и change control для regulated manufacturing, data residency и cyber-physical safety для критических площадок.
* Любые утверждения о regulator-ready status должны появляться только после control mapping, audit trail design и formal evidence bundle.

## 14. Sources and References
* `docs/startups/INVESTOR_DOC_STANDARD_2026.md`
* `docs/startups/MARKET_AND_ACADEMIC_SOURCES_2026-03.md`
* `docs/investor/EVIDENCE_BASE.md`
* `docs/investor/MARKET_COMPETITION_REPORT_2026_04.md`
* `docs/investor/INVESTOR_DILIGENCE_PACKET_2026_04.md`
* `LITERATURE_REVIEW.md`
* `BENCHMARK_PROTOCOL.md`
* internal SynAPS concept brief, April 2026
