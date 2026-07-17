.PHONY: test coverage lint format install clean docker help

VERSION := 0.6.1

help:
	@echo "Pulse Agent v$(VERSION)"
	@echo ""
	@echo "Available targets:"
	@echo "  install    Install in dev mode (pip install -e '.[dev]')"
	@echo "  test       Run test suite"
	@echo "  coverage   Run tests with coverage report"
	@echo "  lint       Run ruff linter"
	@echo "  format     Auto-format code with ruff"
	@echo "  clean      Remove build artifacts"
	@echo "  docker     Build Docker image"
	@echo "  version    Show current version"

version:
	@echo "Pulse Agent v$(VERSION)"

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -q

coverage:
	python -m pytest tests/ --cov=pulse --cov-report=term-missing

lint:
	ruff check pulse/ tests/ --select E,F,W --ignore E501

format:
	ruff format pulse/ tests/
	ruff check pulse/ tests/ --fix

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info

docker:
	docker build -t pulse-agent:$(VERSION) .
