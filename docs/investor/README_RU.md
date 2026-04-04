---
title: "Инвесторский пакет SynAPS"
status: "active"
version: "2.0.1"
last_updated: "2026-04-03"
date: "2026-04-03"
tags: [synaps, investor, startup, navigation, ru]
mode: "reference"
---

# Инвесторский пакет SynAPS

Language: [EN](README.md) | RU

Эта директория — навигация по инвесторским материалам SynAPS. Оглавление и маршрутная карта, а не полная документация по продукту.

Этот subtree опционален. Его удаление не должно влиять на open-source код, тесты, benchmark harness и package build SynAPS.

## Глоссарий

Если любой термин, акроним или уровень достоверности (C1 / C2 / C3) непонятен — начинайте здесь:

- **RU:** [GLOSSARY_2026_04_RU.md](GLOSSARY_2026_04_RU.md)
- **EN:** [GLOSSARY_2026_04.md](GLOSSARY_2026_04.md)

## Порядок чтения

Документы расположены в последовательности, которая имеет наибольший смысл для первого прочтения. Не обязательно читать все 30 — первые 5–6 дают картину.

1. `GLOSSARY_2026_04_RU.md` — термины, акронимы, уровни достоверности и шкала доказательств
2. `INVESTOR_ONE_PAGER_2026_04.md` — самая быстрая инвесторская сводка
3. `INVESTOR_DECK_2026_04.md` — повествование в формате презентации
4. `INVESTOR_5_SLIDE_DECK_MOSKABEL_2026_04_RU.md` — короткий 5-слайдовый deck для русскоязычного разговора про Москабель, hard/software/math и ask
5. `INVESTOR_5_SLIDE_DECK_MOSKABEL_PPT_READY_2026_04_RU.md` — готовый текст самих слайдов для PowerPoint, Keynote или Figma Slides
6. `INVESTOR_DILIGENCE_PACKET_2026_04.md` — главная поверхность фактов для проверки
7. `MARKET_MODEL_2026_04.md` — рыночная модель с привязкой к источникам
8. `TECHNICAL_VERIFICATION_REPORT_2026_04.md` — свежие результаты технической проверки
9. `BENCHMARK_EVIDENCE_PACKET_2026_04.md` — граница доказательств бенчмарков и стандарт следующей публикации
10. `PILOT_KPI_PROTOCOL_2026_04.md` — как измерять будущие пилоты
11. `INVESTOR_QA_2026_04.md` — краткий Q&A для живых разговоров
12. `ACADEMIC_METHODS_APPENDIX_2026_04.md` — методология, иерархия доказательств, угрозы валидности
13. `COMPLIANCE_TRUST_MATRIX_2026_04.md` — матрица соответствия и границы доверия
14. `CLAIM_EVIDENCE_REGISTER_2026_04.md` — проверяемый реестр активных утверждений
15. `WORLD_CLASS_TECHNICAL_DILIGENCE_FRAMEWORK_2026_04.md` — синтез мировых практик апреля 2026
16. `VERSION_AND_SUPPLY_CHAIN_AUDIT_2026_04.md` — аудит свежести версий, SBOM и происхождения
17. `INTEGRATION_AND_ARCHITECTURE_GAP_AUDIT_2026_04.md` — аудит продуктовой готовности и архитектурных пробелов
18. `VERIFICATION_COVERAGE_AUDIT_2026_04.md` — что реально перепроверено
19. `MATHEMATICAL_AND_RESEARCH_FACT_CHECK_2026_04.md` — проверка формализма и утверждений о solver'е
20. `LONG_HORIZON_STRATEGIC_OPTIONS_2026_04.md` — рамка на 20–45 лет
21. `INVESTOR_RED_TEAM_APPENDIX_2026_04.md` — самые жёсткие возражения и незакрытые пробелы
22. `PITCH_MEMO_2026_04.md` — основное инвесторское повествование (EN)
23. `PITCH_MEMO_2026_04_RU.md` — основное инвесторское повествование (RU)
24. `EVIDENCE_BASE.md` — контроль утверждений и границ доказательств
25. `MARKET_COMPETITION_REPORT_2026_04.md` — конкурентная основа и позиционирование
26. `SYNAPS_VS_APS_INFIMUM_2026_04.md` — глубокое сравнение с вертикальным APS-продуктом
27. `INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04.md` — письмо инвестору по замене APS Infimum на Москабеле
28. `MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04.md` — экономика замены и пороговая модель
29. `GITHUB_COMPARABLES_BEST_PRACTICES_2026_04.md` — лучшие практики GitHub-репозиториев
30. `HYPERDEEP_AUDIT_REPORT_2026_04.md` — проверка фактов по первоисточникам
31. `GITHUB_PUBLIC_EXPORT_AUDIT_2026_04.md` — готовность к публикации и граница верификации

## Где я стою

SynAPS защитим как C2-гипотезу продуктового ядра. Схема, solver, бенчмарк-харнесс и исследовательская документация проверяемы. Инвесторские документы ограничены явными контролями. Рыночная модель привязана к источникам, но ROI из пилотов, лидерство в бенчмарках и регуляторная готовность — открытые пробелы, не закрытые доказательства. Против APS Infimum: SynAPS уже сильнее по открытым техническим доказательствам и дисциплине утверждений, но слабее по развёрнутому вертикальному продукту.

## Техническая поверхность

Если нужен самый короткий технический маршрут в проект, начинайте здесь:

1. `TECHNICAL_VERIFICATION_REPORT_2026_04.md`
2. `MATHEMATICAL_AND_RESEARCH_FACT_CHECK_2026_04.md`
3. `INVESTOR_DILIGENCE_PACKET_2026_04.md`

## Инженерные точки входа

Если сначала нужен технический репозиторий, начинайте здесь:

1. [../../README.md](../../README.md)
2. [../README.md](../README.md)
3. [../../benchmark/README.md](../../benchmark/README.md)
4. [../../SUPPORT.md](../../SUPPORT.md)
5. [../../SECURITY.md](../../SECURITY.md)
6. [../../CONTRIBUTING.md](../../CONTRIBUTING.md)
7. [../../CITATION.cff](../../CITATION.cff)

## Публикационная позиция

Репозиторий подготовлен для консервативного публичного рецензирования и инвесторского обсуждения.

Я не заявляю паритет с полноценными APS-пакетами, подтверждённый пилотами ROI, регуляторную готовность и полное закрытие свежести зависимостей. Пакет выровнен по состоянию на апрель 2026 — публичные руководства GitHub, стандарты цитирования, паттерны из венчурных OSS-репозиториев. Внешний синтез: `GITHUB_COMPARABLES_BEST_PRACTICES_2026_04.md`.

Для продуктового сравнения с вертикальным APS: `SYNAPS_VS_APS_INFIMUM_2026_04.md`. Для инвесторского вывода по экономике Москабеля: `INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04.md` вместе с `MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04.md`.