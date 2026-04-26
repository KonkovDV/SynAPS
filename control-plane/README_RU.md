# TypeScript-шлюз SynAPS

Language: [EN](README.md) | **RU**

Этот пакет — минимальный TypeScript-шлюз поверх Python-ядра SynAPS.

Он не реализует пользовательский интерфейс, адаптеры ERP/MES или долгоживущую оркестрацию процессов.
Он показывает более узкую, но важную границу:

1. проверяет входные запросы по зафиксированным JSON-схемам SynAPS;
2. вызывает Python-ядро через стабильный CLI-контракт;
3. проверяет ответ Python перед возвратом вызывающей стороне.

## Endpoints

- `GET /healthz`
- `GET /metrics` (экспорт Prometheus)
- `GET /openapi.json`
- `GET /api/v1/runtime-contract`
- `POST /api/v1/solve`
- `POST /api/v1/repair`
- `POST /api/v1/ui/gantt-model`

`GET /openapi.json` публикует документ OpenAPI 3.1, собранный из зафиксированных схем SynAPS.

`GET /api/v1/runtime-contract` остаётся более компактной точкой входа: он отдаёт список файлов схем и служебные данные маршрутизации, включая путь до OpenAPI-документа.

`POST /api/v1/ui/gantt-model` возвращает read-only проекцию по дорожкам/блокам
(с графом предшествования и дельтами к baseline), чтобы UI Gantt мог визуализировать
перепланирование без разбора внутренних структур решателя.

## Наблюдаемость и защитные барьеры

Control-plane теперь поддерживает:

1. структурированные события (trace_id/span_id);
2. OpenTelemetry-спаны (при включении);
3. RED-метрики Prometheus через `/metrics` (duration, solver outcomes, limit-guard transitions, bridge errors, feasibility kinds, gap/windows);
4. цепочку резервных переходов limit-guard для `solve`.

Ключевые переменные окружения:

- `SYNAPS_OTEL_ENABLED=1`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://.../v1/traces`
- `SYNAPS_ENABLE_LIMIT_GUARDS=1`
- `SYNAPS_LIMIT_GUARD_CHAIN=CPSAT-30,LBBD-10,RHC-ALNS,GREED`
- `SYNAPS_PYTHON_EXEC_TIMEOUT_MS=...`
- `SYNAPS_PYTHON_MAX_OUTPUT_BYTES=...`

Готовые monitoring-артефакты (Grafana dashboard + Prometheus alert rules):

- `../technical/monitoring/grafana/synaps-control-plane-slo.dashboard.json`
- `../technical/monitoring/prometheus/synaps-control-plane-alerts.yml`

## Локальная подготовка

Этот пакет не является самостоятельным Node-сервисом. `npm test`, `npm run dev` и живые
маршруты `solve/repair` вызывают Python CLI `synaps`, поэтому пакет SynAPS из корня
репозитория должен быть установлен в тот интерпретатор, который использует bridge.

```bash
cd ..
python -m pip install -e ".[dev]"
cd control-plane
npm install
npm run test
npm run build
npm run dev
```

GitHub Actions job `control-plane` теперь повторяет тот же порядок: сначала Python,
затем `pip install -e ".[dev]"`, после этого Node build/test шаги.

## Связь с Python

По умолчанию шлюз ищет Python в таком порядке:

1. `SYNAPS_PYTHON_BIN`
2. ближайший ancestor `.venv`
3. `python` на Windows или `python3` на POSIX

Если в CI или локальной среде нужен конкретный интерпретатор, задайте его явно через
`SYNAPS_PYTHON_BIN`, чтобы не зависеть от ближайшего ancestor virtualenv.

BFF выполняет:

```bash
python -m synaps solve-request <request.json>
python -m synaps repair-request <request.json>
```

## Граница ответственности

Этот пакет намеренно остаётся тонким слоем.

Это слой транспорта и проверки данных. Он не должен пересобирать модели CP-SAT или дублировать логику решателя из Python-ядра.

