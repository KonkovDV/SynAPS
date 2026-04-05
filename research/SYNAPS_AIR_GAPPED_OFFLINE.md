# SynAPS: Air-Gapped (Полный Offline-Режим) — CURRENT vs TARGET

> **Классификация**: `CURRENT` = реализовано и работает сейчас; `TARGET` = целевая архитектура, требует реализации.
> **Термины**: [GLOSSARY](../docs/investor/GLOSSARY_2026_04.md).

Среда критической инфраструктуры требует **Air-Gapped** развёртывания — работы без доступа к внешнему интернету. Этот документ разделяет то, что **уже работает offline** в текущем SynAPS, от того, что является **целевой архитектурой** для полностью изолированного промышленного развёртывания.

---

## 1. Текущее Состояние: Что Уже Работает Offline (`CURRENT`)

### 1.1. Математическое Ядро — Offline By Design

Решатели CP-SAT (Google OR-Tools) и HiGHS — полностью автономные C++ библиотеки.

* Они импортируются как Wheel-пакеты (Python) или скомпилированные C++ бинарники.
* Эти модули **не имеют сетевых протоколов** (no telemetry, no phone-home).
* Они на 100% air-gapped «из коробки» и стабильно работают на локальном CPU.
* В отличие от коммерческих решателей (Gurobi — внешний сервер лицензий, Cloud token validation), SynAPS не требует сетевого доступа для работы solver-портфолио.

### 1.2. Python Runtime и Зависимости

Текущий SynAPS (`pyproject.toml`) зависит от:

| Зависимость | Offline-статус |
| --- | --- |
| `ortools` (CP-SAT) | ✅ Полностью offline, C++ бинарник |
| `highspy` (HiGHS) | ✅ Полностью offline, C++ бинарник |
| `pydantic` | ✅ Pure Python, без сетевых вызовов |
| `numpy` | ✅ Без сетевых вызовов |

Для air-gapped установки достаточно предварительно скачать wheels и установить через `pip install --no-index --find-links ./wheels/`.

### 1.3. TypeScript Control-Plane

Минимальный BFF (Fastify + AJV) тоже не требует внешних сетевых подключений в runtime. JSON Schema валидация и Python-bridge работают локально.

**Вывод**: Текущий SynAPS solver pipeline уже функционален в offline-среде. Требуется только предварительная подготовка Python-окружения.

---

## 2. Целевая Архитектура: Полный Air-Gapped ЦОД (`TARGET`)

Всё, что описано ниже, **не реализовано в текущем репозитории** и является архитектурным планом для промышленного развёртывания.

### 2.1. Единый Artifact Registry (`TARGET`)

* **Sonatype Nexus** или **Harbor** внутри DMZ.
* PyPI Mirror для Python-зависимостей: `pip --index-url http://nexus.local/pypi/simple`.
* Crates.io Mirror (через `panamax`) для будущего Rust-ядра.
* Docker Registry (Harbor с Trivy/Clair сканером).

### 2.2. ИИ и ML в Offline-Режиме (`TARGET`)

**LLM:**
* Скачать веса GLM-4-32B / Qwen 2.5 в `.safetensors` формате.
* Перенести в локальную директорию, установить `HF_DATASETS_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_OFFLINE=1`.
* SGLang/vLLM: указать абсолютный путь вместо имени модели.

**GNN и Offline RL:**
* PyTorch 2.6 + `torch.compile` (Inductor) — компиляция локально через GCC/Clang.
* Траектории сохраняются в локальную ClickHouse или HDF5 файлы.

### 2.3. Edge-Инфраструктура на ПЛК (`TARGET`)

* Обучение GNN модели в изолированном ЦОД.
* Экспорт в ExecuTorch (.pte).
* Развёртывание на Edge-контроллеры через локальный MQTT-брокер (EMQX).
* Inference < 10 мс, данные не покидают локальную подсеть.

### 2.4. Оркестрация: Air-Gapped Kubernetes (`TARGET`)

* RKE2 или K3s для Edge-зон.
* ISO-образ со всеми скомпилированными контейнерами.
* Temporal — локально на Postgres-backend.
* NATS JetStream — кластерный режим (Raft) на внутренних IP.
* Локальный Hardware NTP Server (GPS-антенна) для синхронизации времени без внешних серверов.

---

## Итоговая Матрица

| Слой | Offline-статус | Что нужно для air-gap |
| --- | --- | --- |
| **Solver (CP-SAT + HiGHS)** | ✅ CURRENT — offline by design | Предварительная загрузка wheels |
| **Python runtime** | ✅ CURRENT — offline при наличии wheels | `pip install --no-index` |
| **TypeScript BFF** | ✅ CURRENT — offline при наличии node_modules | `npm pack` / offline install |
| **LLM Copilot** | ❌ TARGET | Оффлайн-модели + SGLang + registry |
| **GNN / ML** | ❌ TARGET | Offline PyTorch + model weights |
| **Edge AI** | ❌ TARGET | ExecuTorch + local MQTT |
| **Kubernetes оркестрация** | ❌ TARGET | RKE2/K3s air-gapped install |
| **Телеметрия** | ❌ TARGET | ClickHouse + Grafana локально |

Текущий SynAPS solver pipeline **уже работает offline**. Полная «суверенная система судного дня» — целевая архитектура, требующая реализации.
