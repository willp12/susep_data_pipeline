.PHONY: install lint fmt test run chat chat-ui dbt-build bootstrap clean

install:
	uv sync --all-groups
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest

run:
	uv run python -m src.main

chat:
	uv run python -m src.chat.cli

chat-ui:
	uv run streamlit run src/chat/app.py

dbt-build:
	cd dbt && uv run dbt build --profiles-dir .

bootstrap:
	bash scripts/bootstrap/run_all.sh

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
