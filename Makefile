.PHONY: install demo api test lint type quality

install:
	python -m pip install -e ".[dev]"

demo:
	inventory-platform demo --containers 40 --seed 42

api:
	inventory-platform serve

test:
	pytest --cov=inventory_event_platform --cov-report=term-missing --cov-fail-under=80

lint:
	ruff check src tests

type:
	mypy src

quality: lint type test
