# Карта документации SynAPS

Language: [EN](README.md) | **RU**

Эта директория — основной путеводитель по технической документации SynAPS.

Начинайте здесь, если нужен более широкий системный контекст вокруг текущего ядра планирования.

## Быстрые маршруты

1. Начните с [../README_RU.md](../README_RU.md), чтобы увидеть границы репозитория и команды быстрого старта.
2. Переходите к [../benchmark/README_RU.md](../benchmark/README_RU.md), если нужна воспроизводимая проверка решателей.
3. Переходите к [../control-plane/README_RU.md](../control-plane/README_RU.md), если нужна сетевая граница TypeScript-слоя.

## Архитектура

- [architecture/01_OVERVIEW.md](architecture/01_OVERVIEW.md)
- [architecture/02_CANONICAL_FORM.md](architecture/02_CANONICAL_FORM.md)
- [architecture/03_SOLVER_PORTFOLIO.md](architecture/03_SOLVER_PORTFOLIO.md)
- [architecture/04_DATA_MODEL.md](architecture/04_DATA_MODEL.md)
- [architecture/05_DEPLOYMENT.md](architecture/05_DEPLOYMENT.md)
- [architecture/06_LANGUAGE_AND_RUNTIME_STRATEGY.md](architecture/06_LANGUAGE_AND_RUNTIME_STRATEGY.md)
- [architecture/07_RUNTIME_CONTRACT.md](architecture/07_RUNTIME_CONTRACT.md)

## Доменные параметризации

- [domains/DOMAIN_CATALOG.md](domains/DOMAIN_CATALOG.md)
- [domains/aerospace.md](domains/aerospace.md)
- [domains/electronics.md](domains/electronics.md)
- [domains/energy.md](domains/energy.md)
- [domains/food_beverage.md](domains/food_beverage.md)
- [domains/logistics.md](domains/logistics.md)
- [domains/metallurgy.md](domains/metallurgy.md)
- [domains/pharmaceutical.md](domains/pharmaceutical.md)
- [domains/data_center.md](domains/data_center.md)

## Ближайший эволюционный контур

- [evolution/V1_DIGITAL_TWIN_DES.md](evolution/V1_DIGITAL_TWIN_DES.md)

## Исследовательские материалы

- [../research/SYNAPS_OSS_STACK_2026.md](../research/SYNAPS_OSS_STACK_2026.md)

Спекулятивные blueprint- и whitepaper-материалы больше не входят в активный публичный исследовательский маршрут.

## Аудиторские отчёты

- [ACADEMIC_TECHNICAL_REPORT_2026_04.md](audit/ACADEMIC_TECHNICAL_REPORT_2026_04.md) — академический технический аудит: формальная классификация задачи, анализ solver-портфолио, конкурентное позиционирование, рекомендации.
- [SYNAPS_ACADEMIC_AUDIT_COMPREHENSIVE_RU.md](audit/SYNAPS_ACADEMIC_AUDIT_COMPREHENSIVE_RU.md) — аудит архитектуры: incremental repair, feasibility checker, ML advisory, целевой OSS/OSH-стек.
- [SYNAPS_CRITICAL_GAPS_AND_OPTIMIZATIONS_RU.md](audit/SYNAPS_CRITICAL_GAPS_AND_OPTIMIZATIONS_RU.md) — 5 архитектурных узких мест с академическими ссылками и планом усиления. Gap #1 (параллелизм LBBD) уже закрыт.
- [SYNAPS_VS_INFIMUM_MOSKABEL_STRATEGY_RU.md](audit/SYNAPS_VS_INFIMUM_MOSKABEL_STRATEGY_RU.md) — SynAPS vs APS Infimum: алгоритмическое сравнение для кабельного производства.

## Проверка и доказательная база

- [../benchmark/README.md](../benchmark/README.md)
- [../benchmark/README_RU.md](../benchmark/README_RU.md)
- [../control-plane/README.md](../control-plane/README.md)
- [../control-plane/README_RU.md](../control-plane/README_RU.md)
- [../README.md](../README.md)
- [PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md](PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md)
- [../CONTRIBUTING.md](../CONTRIBUTING.md)
- [../SECURITY.md](../SECURITY.md)

Публичный технический роутер намеренно не включает локальный партнёрский пакет.