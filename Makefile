.PHONY: dev-start dev-restart dev-stop dev-status db-up db-test-up migrate \
	backend frontend test test-backend test-unit test-integration test-frontend \
	e2e-setup test-e2e evaluate evaluate-smoke

# Evaluation inputs are repository-root-relative by default. Override them on the
# command line, for example: make evaluate TRIALS=evaluation/trials/retrieval.json
DATASET ?= evaluation/datasets/starter-general.json
TRIALS ?= evaluation/trials/chunking.json
EVALUATION_RUNNER ?= app.evaluation_wiring:create_runner
EVALUATION_OUTPUT_DIR ?= .evaluation
EVALUATION_RUN_NAME ?= $(notdir $(basename $(DATASET)))-$(notdir $(basename $(TRIALS)))
JSON_OUTPUT ?= $(EVALUATION_OUTPUT_DIR)/$(EVALUATION_RUN_NAME)-results.json
MARKDOWN_OUTPUT ?= $(EVALUATION_OUTPUT_DIR)/$(EVALUATION_RUN_NAME)-summary.md
EVALUATION_ARGS ?=

dev-start:
	@./scripts/dev.sh start

dev-restart:
	@./scripts/dev.sh restart

dev-stop:
	@./scripts/dev.sh stop

dev-status:
	@./scripts/dev.sh status

db-up:
	@./scripts/dev.sh database

db-test-up: db-up

migrate:
	cd backend && uv run alembic upgrade head

backend:
	cd backend && uv run uvicorn app.main:app --reload

frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend: test-unit test-integration

test-unit:
	cd backend && uv run pytest tests/unit

test-integration: db-test-up
	cd backend && uv run --env-file ../.env pytest tests/integration

test-frontend:
	cd frontend && npm test -- --run

e2e-setup:
	cd tests/e2e && npm install && npx playwright install chromium

test-e2e:
	cd tests/e2e && npm test

define run_evaluation
	@test -f "$(DATASET)" || { echo "Evaluation dataset not found: $(DATASET)" >&2; exit 2; }
	@test -f "$(TRIALS)" || { echo "Evaluation trials not found: $(TRIALS)" >&2; exit 2; }
	@mkdir -p "$(dir $(JSON_OUTPUT))" "$(dir $(MARKDOWN_OUTPUT))"
	@echo "Dataset:  $(DATASET)"
	@echo "Trials:   $(TRIALS)"
	@echo "Reports:  $(JSON_OUTPUT), $(MARKDOWN_OUTPUT)"
	cd backend && uv run python -m app.evaluation \
		--dataset "$(abspath $(DATASET))" \
		--trials "$(abspath $(TRIALS))" \
		--runner "$(EVALUATION_RUNNER)" \
		--json-output "$(abspath $(JSON_OUTPUT))" \
		--markdown-output "$(abspath $(MARKDOWN_OUTPUT))" \
		$(EVALUATION_ARGS)
endef

evaluate:
	$(run_evaluation)

evaluate-smoke: DATASET := evaluation/datasets/example.json
evaluate-smoke: TRIALS := evaluation/trials/example.json
evaluate-smoke: EVALUATION_RUN_NAME := smoke
evaluate-smoke:
	$(run_evaluation)
