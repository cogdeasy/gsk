PYTHON ?= python3
export PYTHONPATH := tools

.PHONY: help setup lint test scan scan-report migrate reports check clean

help:
	@echo "setup        install dev dependencies"
	@echo "lint         run ruff"
	@echo "test         run the pytest suite"
	@echo "scan         scan the ABAP estate (summary)"
	@echo "scan-report  regenerate reports/remediation-backlog.md"
	@echo "migrate      run the wave 0 data migration pipeline"
	@echo "reports      regenerate every committed report"
	@echo "check        lint + test + scan gate"

setup:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check tools tests

test:
	$(PYTHON) -m pytest

scan:
	$(PYTHON) -m s4scan scan abap/ecc

scan-report:
	$(PYTHON) -m s4scan scan abap/ecc --format markdown --out reports/remediation-backlog.md
	$(PYTHON) -m s4scan scan abap/ecc --format json --out reports/remediation-backlog.json

migrate:
	$(PYTHON) -m datamig run --wave wave0

reports: scan-report
	$(PYTHON) -m datamig run --wave wave0 --out reports/wave0

check: lint test
	$(PYTHON) -m s4scan scan abap/remediated --fail-on minor

clean:
	rm -rf out .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
