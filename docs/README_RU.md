# Карта документации SynAPS

Language: [EN](README.md) | **RU**

Эта директория — основной путеводитель по технической документации SynAPS.

Начинайте здесь, если нужен более широкий системный контекст вокруг текущего ядра планирования.

## Быстрые маршруты

1. Начните с [../README_RU.md](../README_RU.md), чтобы увидеть границы репозитория и команды быстрого старта.
2. Переходите к [../benchmark/README_RU.md](../benchmark/README_RU.md), если нужна воспроизводимая проверка solver-ов.
3. Переходите к [../control-plane/README_RU.md](../control-plane/README_RU.md), если нужна сетевая граница TypeScript-слоя.
4. Открывайте [investor/README_RU.md](investor/README_RU.md) только если нужен опциональный инвесторский слой.

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

## Эволюционные треки

- [evolution/CROSS_VECTOR_INTEGRATION.md](evolution/CROSS_VECTOR_INTEGRATION.md)
- [evolution/V1_DIGITAL_TWIN_DES.md](evolution/V1_DIGITAL_TWIN_DES.md)
- [evolution/V2_LLM_COPILOT.md](evolution/V2_LLM_COPILOT.md)
- [evolution/V3_FEDERATED_LEARNING.md](evolution/V3_FEDERATED_LEARNING.md)
- [evolution/V4_QUANTUM_READINESS.md](evolution/V4_QUANTUM_READINESS.md)

## Исследовательские материалы

- [../research/SYNAPS_OSS_STACK_2026.md](../research/SYNAPS_OSS_STACK_2026.md)
- [../research/SYNAPS_UNIVERSAL_ARCHITECTURE.md](../research/SYNAPS_UNIVERSAL_ARCHITECTURE.md)
- [../research/SYNAPS_AIR_GAPPED_OFFLINE.md](../research/SYNAPS_AIR_GAPPED_OFFLINE.md)

Legacy blueprint и whitepaper narrative-файлы больше не входят в активный исследовательский маршрут.

## Проверка и доказательная база

- [../benchmark/README.md](../benchmark/README.md)
- [../benchmark/README_RU.md](../benchmark/README_RU.md)
- [../control-plane/README.md](../control-plane/README.md)
- [../control-plane/README_RU.md](../control-plane/README_RU.md)
- [../README.md](../README.md)
- [../README_RU.md](../README_RU.md)
- [PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md](PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md)
- [../CONTRIBUTING.md](../CONTRIBUTING.md)
- [../SECURITY.md](../SECURITY.md)

## Опциональный investor pack

`docs/investor/` содержит опциональный пакет материалов для инвесторов и проверки утверждений.

Инженерная поверхность полна и без этой подпапки, поэтому её удаление не должно затрагивать код, тесты, систему бенчмарков и сборку пакета.

Используйте [investor/README_RU.md](investor/README_RU.md) как основной путеводитель по инвесторскому слою. В нём теперь оставлен сокращённый активный пакет и явная граница архива.