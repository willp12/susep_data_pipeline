.PHONY: install lint fmt test run chat chat-ui dbt-build dbt-unit bootstrap clean

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

# dbt unit tests only (dbt build already runs them before each model).
dbt-unit:
	cd dbt && uv run dbt test --select "test_type:unit" --profiles-dir .

# Residual bootstrap (APIs + ingestion_log table). The infra proper is
# Terraform: cd infra && terraform apply.
bootstrap:
	bash scripts/bootstrap/run_all.sh

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
