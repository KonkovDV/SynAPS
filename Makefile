# SynAPS Developer Makefile
# Requires: Python 3.12+, pre-commit, ruff, mypy, pytest, maturin (for native builds)
# On Windows use with `nmake` or run commands directly via PowerShell.

PYTHON := py -3.13
PYTHONPATH := C:/plans/SynAPS

.PHONY: lint format format-fix typecheck test test-fast test-slow clean native-build native-test benchmark-fast precommit help

help: ## Show this help message
	@echo "SynAPS developer targets:"
	@echo "  lint          - Run ruff check on synaps, tests, benchmark"
	@echo "  format        - Run ruff format --check (dry-run)"
	@echo "  format-fix    - Run ruff format (apply fixes)"
	@echo "  typecheck     - Run mypy --strict on synaps"
	@echo "  test          - Run full pytest suite"
	@echo "  test-fast     - Run fast tests only (-m 'not slow')"
	@echo "  test-slow     - Run slow tests only (-m 'slow')"
	@echo "  benchmark-fast- Run quick benchmark subset"
	@echo "  native-build  - Build synaps_native wheel via maturin"
	@echo "  native-test   - Run native accelerator tests"
	@echo "  precommit     - Run pre-commit on all files"
	@echo "  clean         - Remove cache/build artifacts"

lint: ## Run ruff check
	$(PYTHON) -m ruff check synaps tests benchmark

format: ## Check formatting (dry-run)
	$(PYTHON) -m ruff format --check synaps tests benchmark

format-fix: ## Apply formatting fixes
	$(PYTHON) -m ruff format synaps tests benchmark

typecheck: ## Run strict mypy
	$(PYTHON) -m mypy synaps --strict --no-error-summary

test: ## Run full test suite
	$(PYTHON) -m pytest tests/ -v --tb=short

test-fast: ## Run fast tests (excludes slow markers)
	$(PYTHON) -m pytest tests/ -v --tb=short -m "not slow" \
		--cov=synaps --cov-report=term-missing --cov-fail-under=65

test-slow: ## Run slow tests only
	$(PYTHON) -m pytest tests/ -v --tb=short -m "slow"

benchmark-fast: ## Run quick benchmark subset
	$(PYTHON) -m benchmark.study_rhc_50k --quick

native-build: ## Build native PyO3 accelerator wheel
	$(PYTHON) -m maturin build \
		--manifest-path native/synaps_native/Cargo.toml \
		--release --out native-dist
native-test: ## Install built wheel and run native tests
	$(PYTHON) -m pip install --force-reinstall native-dist/*.whl
	$(PYTHON) -m pytest tests/test_native_*.py tests/test_accelerators.py -q

precommit: ## Run all pre-commit hooks
	pre-commit run --all-files

clean: ## Remove build artifacts and caches
	@echo "Cleaning Python caches..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.py[co]" -delete 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name build -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name dist -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name native-dist -exec rm -rf {} + 2>/dev/null || true
	@echo "Done."
