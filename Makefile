.PHONY: install lint fmt test run chat chat-ui dbt-build dbt-unit bootstrap clean \
	eval-truth eval-dry eval-smoke eval eval-score

install:
	uv sync --all-groups
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src evals

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

# Experimento de precisão e custo por camada (evals/precisao/README.md).
# Ordem: eval-truth → eval-dry → eval-smoke → eval → eval-score.
EVAL_RESULTS := evals/precisao/results
EVAL_TRUTH := $(EVAL_RESULTS)/truth.json

eval-truth:
	uv run python -m evals.precisao.truth --out $(EVAL_TRUTH)

eval-dry:
	uv run python -m evals.precisao.run --dry-run

eval-smoke:
	uv run python -m evals.precisao.run --out $(EVAL_RESULTS)/smoke --questions q1 --reps 1 --truth $(EVAL_TRUTH)

eval:
	uv run python -m evals.precisao.run --out $(EVAL_RESULTS)/full --reps 3 --truth $(EVAL_TRUTH)

eval-score:
	uv run python -m evals.precisao.score $(EVAL_RESULTS)/full --truth $(EVAL_TRUTH)

# Residual bootstrap (APIs + ingestion_log table). The infra proper is
# Terraform: cd infra && terraform apply.
bootstrap:
	bash scripts/bootstrap/run_all.sh

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
