---
title: "Короткий инвесторский deck SynAPS для Москабеля 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-03"
date: "2026-04-03"
tags: [synaps, investor, deck, moskabel, ru, short-deck]
mode: "how-to"
---

# Короткий инвесторский deck SynAPS для Москабеля

Этот документ нужен для короткой живой презентации на 5 слайдов. Он не заменяет [INVESTOR_DILIGENCE_PACKET_2026_04.md](INVESTOR_DILIGENCE_PACKET_2026_04.md), а сжимает SynAPS в форму, понятную инвестору за 5-7 минут.

Если нужен не explanatory surface, а уже готовый slide copy для PowerPoint или Figma Slides, используйте [INVESTOR_5_SLIDE_DECK_MOSKABEL_PPT_READY_2026_04_RU.md](INVESTOR_5_SLIDE_DECK_MOSKABEL_PPT_READY_2026_04_RU.md).

Файл сознательно RU-only: он рассчитан на русскоязычный разговор о кабельном производстве, Москабеле и контрфактической экономике замены APS Infimum. Для общего англоязычного narrative используйте [INVESTOR_DECK_2026_04.md](INVESTOR_DECK_2026_04.md).

## Что считать мировым стандартом для такого deck

Я использую три правила, которые хорошо согласуются между собой.

1. Sequoia: начать с одной ясной формулировки компании, затем показать проблему, решение, why now, рынок, модель и видение.
2. Y Combinator: leave-behind должен быть связным, графика сильнее длинного текста, запрос на финансирование должен быть привязан к правдоподобному milestone, а не к абстрактной амбиции.
3. Собственная дисциплина SynAPS: не смешивать доказанное, target blueprint и гипотезы рынка в один слой утверждений.

## Границы утверждений

Перед показом deck важно держать три границы.

1. **Что доказано в репозитории сегодня:** exact CP-SAT path с sequence-dependent setups и auxiliary resources, bounded incremental repair, benchmark harness, `27/27` текущих тестов, а также smoke benchmark с `42%` преимуществом CP-SAT против greedy baseline в опубликованной investor surface.
2. **Что относится к target blueprint:** hardware-aware hot paths через Rust или PyO3, locality-aware CPU/L3 discipline, Talos/Cilium substrate, optional RDMA lane, LBBD + HGAT scaling path, advisory LLM copilot.
3. **Что нельзя выдавать за факт:** будто SynAPS уже работает на Москабеле, уже превосходит APS Infimum в бою, или уже дал заводу измеренную экономию.

## Слайд 1. Проблема и категория

**Headline**

SynAPS строит переносимое ядро промышленного планирования для заводов, где цена ошибки измеряется переналадками, срывами сроков и дорогим перепланированием.

**3-4 буллита**

1. У setup-heavy производств одна и та же боль: планы хрупкие, интеграции тяжёлые, а перенос на новый завод часто означает почти новую систему.
2. APS Infimum показывает, что эта боль коммерчески реальна именно в кабельной вертикали; значит рынок не нужно выдумывать.
3. Ставка SynAPS не в том, чтобы сразу заменить весь vertical APS, а в том, чтобы создать более переносимое и более проверяемое scheduling kernel.
4. Правильная категория для инвестора: не «ещё один AI для фабрики», а auditable optimization core для сложного дискретного производства.

**Визуал**

Слева хаотический контур завода: переналадки, НЗП, срывы. Справа один слой ядра планирования, который связывает разные отрасли через общую математическую модель.

**Комментарий спикера**

Начинать не с алгоритмов, а с цены хаоса в цехе. Это соответствует как практике Sequoia, так и выводам из сравнения с APS Infimum: инвестор лучше воспринимает реальную боль завода, чем абстрактный AI-first нарратив.

## Слайд 2. Софт и хард как moat

**Headline**

Moat SynAPS складывается не из UI, а из boundary-first software design и hardware-aware пути к industrial latency.

**3-4 буллита**

1. Уже доказанный software layer: универсальная схема, exact CP-SAT scheduling paths, bounded incremental repair и reproducible benchmark harness.
2. Текущий публичный репозиторий прямо отделяет working kernel от roadmap: это снижает риск «архитектурной театральности» для инвестора.
3. Target blueprint включает hardware-aware hot paths через Rust/PyO3, locality-aware design под large L3, pinned hot path для solver loops, Talos/Kubernetes/Cilium и optional RDMA lane только после доказанного сетевого bottleneck.
4. Это важно не ради красоты стека, а ради того, чтобы scheduling engine можно было масштабировать без переписывания ядра при переходе от benchmark к цеху.

**Визуал**

Двухслойная схема: слева «Proven today», справа «Target production substrate». В proven слое отметить schema, CP-SAT, repair, tests, benchmark. В target слое отметить Rust/PyO3, L3 locality, Talos/Cilium, ClickHouse/RDMA lane.

**Комментарий спикера**

Не продавать target blueprint как deployed reality. Продавать его как осмысленный путь развития поверх уже работающего kernel, а не как набор слайдовых фантазий.

## Слайд 3. Математика, которая делает продукт защищаемым

**Headline**

Продукт SynAPS начинается не с AI, а с формальной постановки задачи и управляемого стека solver'ов.

**3-4 буллита**

1. Каноническая форма задачи в документации: `MO-FJSP-SDST-ML-ARC` — multi-objective flexible job shop с sequence-dependent setup times, ML advisory и auxiliary resource constraints.
2. Быстрый контур: ATCS/GREED даёт dispatch baseline; точный контур: CP-SAT закрывает exact segments; оперативный контур: incremental repair чинит только повреждённую часть расписания.
3. Масштабирование вперёд уже зафиксировано как research path: LBBD для decomposition и HGAT для прогнозирования весов до оптимизации.
4. ML и LLM в архитектуре SynAPS описаны как advisor, а не executor: constraint satisfaction и schedule determinism остаются в детерминированном слое.

**Визуал**

Три горизонтальных слоя: формализм задачи, solver stack, advisory layer. Поверх формулы ATCS или канонической аббревиатуры дать очень простую подпись: «математика сначала, AI сверху». 

**Комментарий спикера**

Если инвестор технический, на этом слайде нужно показать, что у SynAPS есть не только narrative, но и формальный объект, который можно разбирать, тестировать и улучшать без потери контроля над ограничениями.

## Слайд 4. Москабель и экономика замены APS Infimum

**Headline**

Для Москабеля история SynAPS сегодня не про мгновенную замену APS Infimum, а про риск-скорректированный путь к дополнительной ценности.

**3-4 буллита**

1. Честная стартовая позиция: APS Infimum сегодня сильнее как действующий вертикальный продукт внутри кабельного производства.
2. SynAPS сильнее как открытое, проверяемое и кросс-отраслевое ядро, которое проще аудировать на уровне кода, тестов и формализма.
3. По текущей контрфактической модели замены SynAPS должен доказать дополнительный годовой эффект **сверх** APS Infimum на уровне `36.3-115.9M RUB/year`, в зависимости от сценария миграции и ставки дисконтирования.
4. Следовательно, правильный go-to-market around Moskabel: shadow mode, parallel run и threshold proof, а не агрессивный rip-and-replace narrative.

**Визуал**

Threshold chart с тремя полосами: minimal, base, full replacement burden. Подпись: «Не заявленная экономия, а required incremental value to justify replacement».

**Комментарий спикера**

Это главный слайд доверия. Он показывает инвестору, что проект не маскирует отсутствие pilot proof громким ROI-заголовком. Для deeptech это часто сильнее, чем попытка продать недоказанную победу.

## Слайд 5. Почему инвестировать сейчас

**Headline**

Раунд в SynAPS покупает не ещё один narrative, а перевод внутренне доказанного kernel из C2 в C3 через внешнюю проверку и заводской контур.

**3-4 буллита**

1. Что уже есть: технически связное ядро, репозиторная проверяемость, benchmark harness, investor diligence surfaces и честная граница утверждений.
2. Что должен купить раунд: pilot KPI protocol, operator surface, field integrations, benchmark family по размерам инстансов и живые pricing signals.
3. Формулировка ask должна быть привязана к следующему fundable milestone на горизонте `12-18` месяцев, а не к общей мечте «построить фабрический AGI».
4. Инвестиционный тезис: vertical APS players доказали наличие боли; SynAPS строит более переносимый и более investor-legible kernel-класс поверх той же экономической реальности.

**Визуал**

Milestone ladder: `Kernel proof -> Parallel pilot -> KPI evidence -> Integration proof -> Fundable next round`.

**Комментарий спикера**

Закрывать разговор нужно не перечислением функций, а ответом на вопрос «что изменится после чека». Если конкретного размера раунда пока нет, говорить о milestone package, а не о псевдоточной сумме.

## Готовый промпт для LLM

Ниже текст, который можно без правок отправлять в LLM для генерации русской версии 5-слайдовой презентации.

```text
Действуй как партнер top-tier венчурного фонда и как редактор investor-grade deeptech pitch decks. Сгенерируй 5 слайдов инвесторской презентации SynAPS на русском языке.

Контекст проекта:
- SynAPS — это переносимое ядро промышленного планирования для setup-heavy производств.
- Доказываемый today layer: exact CP-SAT scheduling paths с sequence-dependent setups и auxiliary resources, bounded incremental repair, benchmark harness, 27/27 текущих тестов, опубликованный smoke benchmark с 42% преимуществом CP-SAT над greedy baseline.
- Target blueprint, который нельзя выдавать за уже развёрнутый runtime: hardware-aware hot paths через Rust/PyO3, locality-aware design под large L3, pinned solver hot path, Talos/Kubernetes/Cilium, optional RDMA lane, LBBD + HGAT scaling path, advisory LLM copilot.
- Математическая форма: MO-FJSP-SDST-ML-ARC; быстрый слой — ATCS/GREED, точный слой — CP-SAT, слой оперативного перепланирования — incremental repair.
- Бизнес-контекст: APS Infimum уже показывает, что кабельное производство платит за APS. Но для Москабеля замена APS Infimum на SynAPS сегодня должна рассматриваться только как риск-скорректированная контрфактическая модель, а не как доказанный ROI.
- Экономический порог замены: SynAPS должен доказать дополнительный годовой эффект сверх APS Infimum в диапазоне 36.3-115.9 млн рублей в год, в зависимости от сценария миграции и ставки дисконтирования.

Следуй мировым практикам Sequoia и Y Combinator:
- Начинай с одной ясной формулировки компании.
- Первый слайд должен начинаться с боли клиента, а не с технологии.
- Слайды должны быть короткими, leave-behind friendly, с минимальным числом буллитов.
- Не раздувай TAM и не придумывай недоказанные claims.
- Финальный ask привязывай к правдоподобному milestone на 12-18 месяцев.

Структура слайдов:
1. Проблема завода и категория SynAPS.
2. Софт и хард как moat: proven layer vs target blueprint.
3. Математика и advisory AI.
4. Экономика Москабеля и честная позиция относительно APS Infimum.
5. Почему инвестировать сейчас и что покупает раунд.

Для каждого слайда выведи:
- Headline
- 3-4 буллита
- Идею визуала
- 1 короткую speaker note

Стиль:
- русский язык
- deeptech, не marketing fluff
- investor-grade honesty
- различай доказанное сегодня, target architecture и гипотезы
```

## Что открыть после deck

1. [INVESTOR_5_SLIDE_DECK_MOSKABEL_PPT_READY_2026_04_RU.md](INVESTOR_5_SLIDE_DECK_MOSKABEL_PPT_READY_2026_04_RU.md) — готовый slide copy для быстрой сборки презентации.
2. [INVESTOR_DECK_2026_04.md](INVESTOR_DECK_2026_04.md) — длинный slide narrative.
3. [PITCH_MEMO_2026_04_RU.md](PITCH_MEMO_2026_04_RU.md) — основной русский narrative.
4. [INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04_RU.md](INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04_RU.md) — инвесторская позиция по Москабелю.
5. [MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04_RU.md](MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04_RU.md) — математика replacement economics.
6. [WORLD_CLASS_TECHNICAL_DILIGENCE_FRAMEWORK_2026_04.md](WORLD_CLASS_TECHNICAL_DILIGENCE_FRAMEWORK_2026_04.md) — синтез мировых best practices.

## Источники

1. Sequoia Capital, `Writing a Business Plan` — структура company purpose -> problem -> solution -> why now -> market -> team -> vision.
2. Y Combinator, `A Guide to Seed Fundraising` — связный leave-behind deck, минимум лишнего текста, fundraising tied to believable milestone, запрет на ridiculous market size numbers.
3. [INVESTOR_DECK_2026_04.md](INVESTOR_DECK_2026_04.md), [INVESTOR_ONE_PAGER_2026_04.md](INVESTOR_ONE_PAGER_2026_04.md), [PITCH_MEMO_2026_04_RU.md](PITCH_MEMO_2026_04_RU.md) — текущий investor narrative SynAPS.
4. [MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04_RU.md](MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04_RU.md) и [INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04_RU.md](INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04_RU.md) — контрфактическая экономика замены APS Infimum.
5. [ATOMIC_ARCHITECTURE_THESIS_2026.md](../architecture/ATOMIC_ARCHITECTURE_THESIS_2026.md), [RESEARCH_ROADMAP_2025_2075.md](../research/RESEARCH_ROADMAP_2025_2075.md), [LITERATURE_REVIEW.md](../research/LITERATURE_REVIEW.md) и [README_RU.md](../../README_RU.md) — граница между proven kernel и target blueprint.