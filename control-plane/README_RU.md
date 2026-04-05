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
- `GET /openapi.json`
- `GET /api/v1/runtime-contract`
- `POST /api/v1/solve`
- `POST /api/v1/repair`

`GET /openapi.json` публикует документ OpenAPI 3.1, собранный из зафиксированных схем SynAPS.

`GET /api/v1/runtime-contract` остаётся более компактной точкой входа: он отдаёт список файлов схем и служебные данные маршрутизации, включая путь до OpenAPI-документа.

## Локальные команды

```bash
npm install
npm run test
npm run build
npm run dev
```

## Связь с Python

По умолчанию шлюз ищет Python в таком порядке:

1. `SYNAPS_PYTHON_BIN`
2. ближайший ancestor `.venv`
3. `python` на Windows или `python3` на POSIX

BFF выполняет:

```bash
python -m synaps solve-request <request.json>
python -m synaps repair-request <request.json>
```

## Граница ответственности

Этот пакет намеренно остаётся тонким слоем.

Это слой транспорта и проверки данных. Он не должен пересобирать модели CP-SAT или дублировать solver-логику из Python-ядра.