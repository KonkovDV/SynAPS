# Архитектурный Переход: Уровень 2 (Stateful Rustification)

Статус: active roadmap, partially implemented as of 2026-04-21.

Этот документ фиксирует переход SynAPS от набора точечных PyO3-ускорителей к stateful Rust-ядру, которое кэширует статические данные графа и постепенно забирает на себя hot path `RHC`/`ALNS`.

## 1. Что уже есть в коде

### 1.1 Level 1 hardening нативного hot path

В `native/synaps_native/src/lib.rs` уже реализованы и проверены следующие опоры:

- `fast_exp` зажимает вход в `[-700, 700]`
- little-endian bit-trick изолирован через `#[cfg(target_endian = "little")]`, на остальных таргетах используется точный `exp()`
- batch-handles отпускают GIL через `py.allow_threads(...)`
- branchless overdue-boost убирает лишнее ветвление в `rhc_element_csr`
- residual-domain correction поверх Schraudolph bucket'ов сохраняет строгий порядок близких positive slack-значений на native path

Важно: это не попытка превратить `fast_exp` в scientific-reference реализацию. Цель текущего hardening — убрать коллапс соседних candidate pressure при близких входах и сохранить детерминированность ранжирования.

### 1.2 Python-side база для Level 2 уже landed

На Python-стороне уже есть то, на что будет опираться Level 2:

- `ALNS` умеет принимать partial warm start, достраивать недостающие назначения и пересчитывать setup-поля перед локальным поиском
- `RHC` переносит overlap-tail в следующее `ALNS`-окно
- candidate scoring уже вынесен в NumPy/native batch seam

Именно поэтому следующий шаг должен быть не новый эвристический слой, а перенос статического графового состояния из Python в Rust.

### 1.3 Первый Stage 1 scaffold `SynApsEngine`

В нативном модуле теперь существует минимальный `SynApsEngine`:

```rust
#[pyclass]
struct SynApsEngine {
    machine_count: usize,
    avg_total_p: f64,
    predecessor_ids: Vec<i64>,
    base_durations: Vec<f64>,
    order_weights: Vec<f64>,
    p_tilde_minutes: Vec<f64>,
    successor_offsets: Vec<usize>,
    successor_indices: Vec<usize>,
}
```

Что он делает сейчас:

- принимает `machine_count` и `avg_total_p` в конструкторе
- принимает статические NumPy-массивы через `load_graph(...)`
- копирует их в Rust-owned `Vec`
- строит successor-index из `predecessor_ids`
- держит всё это состояние внутри себя между вызовами Python

Что он пока не делает:

- не вычисляет окно через `evaluate_window_candidates(...)`
- не хранит frozen overlap tails внутри ядра
- не заменяет `RHC` loop на стороне Python

То есть это настоящий Stage 1 scaffold, а не finished engine.

## 2. Где сейчас главный налог

Текущий bottleneck остаётся прежним: на каждой итерации `RHC` Python продолжает собирать временные списки и NumPy-буферы для candidate scoring.

Типичный путь сейчас такой:

1. Python строит `due_offsets`, `rpt_tail_minutes`, `order_weights`, `p_tilde_minutes`
2. NumPy формирует contiguous arrays
3. PyO3 вызывает batch-native seam
4. Rust считает `slack`/`pressure` и возвращает массивы обратно

Это уже лучше, чем per-candidate Python math, но FFI-налог всё ещё платится на каждом окне. Level 2 нужен именно для того, чтобы перестать передавать один и тот же статический граф на каждой итерации.

## 3. Ближайший план Level 2

### Этап 1. Зафиксировать входную stateful boundary

Сделать `SynApsEngine.load_graph(...)` единственной точкой загрузки статических графовых данных.

Текущий минимальный контракт:

```python
from synaps_native import SynApsEngine

engine = SynApsEngine(machine_count, avg_total_p)
engine.load_graph(
    predecessor_ids,
    base_durations,
    order_weights,
    p_tilde_minutes,
)
```

Ближайшее расширение этого этапа:

- добавить остальные статические массивы, которые реально участвуют в candidate scoring
- не дублировать эти же данные в Python-словарях после загрузки
- оставить Python только горячие window-specific входы

### Этап 2. Перевести scoring на объектную модель

Следующая целевая точка:

```python
candidate_slacks, candidate_pressures = engine.evaluate_window_candidates(
    machine_available_offsets_vector,
    eligible_machine_indices,
    predecessor_end_offsets,
    due_offsets,
    rpt_tail_minutes,
)
```

Здесь смысл в том, что `order_weights` и `p_tilde_minutes` должны браться из кеша `SynApsEngine`, а не сериализоваться заново на каждом окне.

### Этап 3. Внутренний lifecycle для overlap-tail

После того как scoring будет жить внутри `SynApsEngine`, следующий шаг — перестать гонять overlap-tail обратно через Python-объекты `Assignment`.

Целевой паттерн:

- Python сообщает ядру, какие операции приняты в commit boundary
- ядро само замораживает принятые узлы
- overlap-tail сохраняется внутри engine для следующего окна

Рабочий кандидат интерфейса:

```python
engine.commit_window(accepted_operation_ids)
```

## 4. Рекомендации, зафиксированные в плане

### 4.1 Память: flat vectors first, arena allocators when mutation justifies it

Для графа и window-state нельзя уходить в `Rc<RefCell<_>>` или разрозненные boxed-структуры. Базовая стратегия:

- сначала хранить граф индексами в плоских `Vec`
- arena allocator вводить там, где `ALNS` действительно начинает генерировать массу короткоживущих кандидатов и профилирование подтверждает allocator pressure

То есть `bumpalo`/`typed-arena` — это следующий шаг после stateful graph cache, а не замена ему.

### 4.2 GIL: отпускать только там, где Rust уже владеет данными

Рекомендация из аудита остаётся в силе, но в узкой форме:

- во время тяжёлой перепаковки и построения внутренних индексов GIL нужно отпускать
- перед этим Python-owned данные должны быть либо скопированы, либо иным образом безопасно закреплены

Текущее `load_graph(...)` уже делает это для построения successor-index поверх Rust-owned данных.

### 4.3 Level 3 research не смешивать с текущим implementation path

Следующие темы остаются в backlog/research track, а не в текущем runtime claim:

- CPCS / critical-path cut strengthening для `LBBD`
- multicut generation
- GNN-biased warm starts
- retroactive competitive benchmark on real factory history

Они важны, но не должны подменять собой ближайшую инженерную задачу: убрать повторную сериализацию статических данных между Python и Rust.

## 5. Definition of done для Level 2

Level 2 можно считать достигнутым, когда одновременно выполняются все условия:

1. `SynApsEngine` хранит весь статический граф и solver-side invariants внутри Rust
2. candidate scoring не требует повторной передачи `order_weights` и `p_tilde_minutes` из Python на каждом окне
3. overlap-tail и commit state живут внутри engine, а не переносятся наружу как промежуточные Python-структуры
4. Python orchestration становится тонкой boundary-обвязкой, а не местом, где заново собирается вычислительная топология

До этого момента Level 2 остаётся целевым направлением, а не завершённым архитектурным фактом.
