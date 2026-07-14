.PHONY: test coverage lint install clean docker

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -q

coverage:
	python -m pytest tests/ --cov=pulse --cov-report=term-missing

lint:
	ruff check pulse/ tests/ --select E,F,W --ignore E501

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info

docker:
	docker build -t pulse-agent .
