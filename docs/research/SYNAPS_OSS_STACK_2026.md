# SynAPS: Аудит Open-Source Стека (Ревизия: Апрель 2026)

> **Классификация**: `CURRENT` = используется в текущем репозитории; `TARGET` = целевой стек, отсутствует в repo.
> Термины и границы текущей реализации задаются [README.md](../README.md) и [docs/architecture/02_CANONICAL_FORM.md](../docs/architecture/02_CANONICAL_FORM.md).

Данный документ описывает Open-Source решения для архитектуры SynAPS. Каждая подсистема разделена на **текущее состояние** (что реально используется в коде) и **целевой стек** (что планируется и исследуется, но ещё не реализовано).

Во всех секциях `TARGET` конкретные версии и продукты ниже нужно читать как target candidates, а не как уже внедрённые зависимости standalone-репозитория.

---

## 1. Блок Оптимизации и Точной Математики (Solver Portfolio)

### Текущее состояние (`CURRENT`)

| Компонент | Версия / Статус | Основание |
| --- | --- | --- |
| Google OR-Tools (CP-SAT) | `>=9.10` в `pyproject.toml` | Точный solver для Job-Shop Scheduling. Активный evidence pack фиксирует последний полностью задокументированный прогон `149/149`, при том что текущий репозиторий собирает `175` тестов |
| HiGHS | `>=1.8` (через `highspy`) | LP/MIP solver. Используется в LBBD-декомпозиции |
| Python 3.12+ / 3.13 | CI-тестирование на обоих | Основная runtime-среда |

CP-SAT (Google) остаётся одним из самых сильных открытых точных решателей для scheduling-задач этого класса. HiGHS — высокопроизводительный открытый LP/MIP solver, заменивший Coin-OR (CBC) в данном стеке. Эта связка образует текущий solver-стек SynAPS.

### Целевой стек (`TARGET`)

* Интеграция CP-SAT с **Rust** (через крейты-биндинги) для микросекундной генерации матриц. Rust-ядро SynAPS V3 — на стадии исследования, код отсутствует в репозитории.

---

## 2. Блок Machine Learning

### Текущее состояние (`CURRENT`)

В текущем репозитории SynAPS **нет ML-кода**. Все solver-пути — чисто алгоритмические (CP-SAT, greedy dispatch, incremental repair, LBBD). ML-компоненты описаны в архитектурных документах как направления исследований.

### Целевой стек (`TARGET`)

**2.1. Графовые Нейросети (HGAT)**
* **PyTorch Geometric (PyG)** + PyTorch 2.6+ (`torch.compile` / Inductor). Для GNN-driven aggregation в операционных контурах, где тысячи мелких операций теряют микро-детали при агрегации.
* Для площадок среднего размера PyG достаточен; для распределённых контуров стоит рассмотреть DGL (AWS).

**2.2. Offline Reinforcement Learning**
* **TorchRL** (Meta/PyTorch Core) вместо Stable-Baselines3. Нативные высокопроизводительные Replay Buffers и оптимизация через Tensordict.
* Обучение через цифровой двойник для безопасного планирования ремонта.

---

## 3. Блок LLM и Natural Language (On-Premise Copilot)

### Текущее состояние (`CURRENT`)

В текущем репозитории SynAPS **нет LLM-кода**. LLM Copilot описан как целевая архитектура.

### Целевой стек (`TARGET`)

* **Inference Engine**: SGLang или vLLM (v0.8+). SGLang показывает лучшую пропускную способность для RAG благодаря RadixAttention.
* **Vector DB**: pgvector (PostgreSQL 17+) для HNSW-индексов в одной операционной БД.
* **Модели**: GLM-5 (744B MoE, API), GLM-4-32B (on-prem), Llama 3.1 8B, Qwen 2.5 / Qwen3 (легковесные агенты).

---

## 4. Блок Симуляции (Цифровой Двойник / Digital Twin)

### Текущее состояние (`CURRENT`)

В текущем репозитории SynAPS **нет симулятора**. Benchmark harness для solver-портфолио существует, но это не DES-симулятор.

### Целевой стек (`TARGET`)

* **SimPy** (Python) — удобен, но однопоточен (GIL) и непригоден для миллионов Monte Carlo сценариев.
* **Rust DES backend** — параллельный симулятор для Offline RL, массовой генерации State/Action траекторий.
* Альтернатива: **Salabim** (визуализация) или мультипроцессорная обёртка над SimPy.

---

## 5. Блок Edge AI и Federated Learning

### Текущее состояние (`CURRENT`)

В текущем репозитории **нет Edge AI или Federated Learning кода**.

### Целевой стек (`TARGET`)

**5.1. Edge Computing**
* **ExecuTorch** (Meta, наследник PyTorch Mobile). Экспорт обученных GNN-моделей на Edge-контроллеры (ПЛК, STM32) без промежуточных форматов.

**5.2. Federated Learning**
* **Flower (v1.10+)** — наиболее активный Open Source фреймворк для FL (>4k GitHub stars, поддержка PyTorch/TensorFlow/JAX). Дифференциальная конфиденциальность, безопасная агрегация.
* Confidential Computing (Intel TDX / AMD SEV) для криптографических гарантий приватности между площадками.

---

## 6. Базовый Бэкенд (Транспорт и Данные)

### Текущее состояние (`CURRENT`)

| Компонент | Статус |
| --- | --- |
| PostgreSQL (через схему) | SQL-схема и доменные примеры существуют в `schema/` |
| Fastify + AJV (TypeScript BFF) | Минимальный control-plane, payload-валидация, Python-bridge |

### Целевой стек (`TARGET`)

* **NATS JetStream (v2.12+)** — эталон для микросервисов IoT-класса (в 10 раз легче Kafka на мелких сообщениях).
* **Temporal (v1.26+)** — координация долгих процессов (ожидание сборки, Workflow orchestration).
* **ClickHouse** — хранение телеметрии с оборудования и логов IoT.

---

## Итоговая Матрица: CURRENT vs TARGET

| Слой | CURRENT (в repo) | TARGET (исследование) |
| --- | --- | --- |
| **Core Runtime** | Python 3.12+/3.13 | + Rust (performance) |
| **OR Engine** | OR-Tools (CP-SAT) + HiGHS | — |
| **ML & GNN** | — | PyTorch 2.6 (TorchRL + Inductor) + PyG |
| **LLM Copilot** | — | GLM-4/5, Qwen, SGLang, pgvector |
| **Digital Twin** | — | SimPy / Rust DES |
| **Edge AI** | — | ExecuTorch |
| **Federated Learning** | — | Flower |
| **Data Transport** | PostgreSQL (schema), Fastify BFF | + NATS JetStream, Temporal, ClickHouse |

Текущий SynAPS — это **Python-based solver portfolio** (CP-SAT + HiGHS + greedy + LBBD + incremental repair) с минимальным TypeScript control-plane. Всё остальное — целевой стек, требующий реализации.
