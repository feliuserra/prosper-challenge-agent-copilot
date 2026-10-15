# Prosper Challenge — run everything from the repo root.
# Dependencies are managed with uv (https://docs.astral.sh/uv/) and npm.

PROJECT := backend
FRONTEND := frontend
TECTONIC ?= tectonic

.PHONY: help install run dev test clinic-reset synth detect detect-eval eval spend memo clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (from uv.lock) and frontend (from package-lock.json) dependencies
	uv sync --directory $(PROJECT)
	npm ci --prefix $(FRONTEND)

run: ## Run the voice agent only (then open http://localhost:7860/client)
	uv run --directory $(PROJECT) python bot.py

# One shell for the whole recipe (macOS ships make 3.81, which has no .ONESHELL):
# the runner runs in the background and is stopped when the frontend exits.
dev: ## Run the voice agent and the editor together (then open http://localhost:5173)
	uv run --directory $(PROJECT) python bot.py & runner=$$!; \
	trap 'kill $$runner 2>/dev/null' EXIT; \
	npm run dev --prefix $(FRONTEND)

test: ## Run the backend and frontend tests
	uv run --directory $(PROJECT) pytest
	npm test --prefix $(FRONTEND)

clinic-reset: ## Restore the live clinics (bookings made in calls) to their seeds
	rm -rf $(PROJECT)/clinic/state $(PROJECT)/clinic/state.json

synth: ## Write synthetic call logs with planted defects to backend/.synth (#57; no model calls)
	uv run --directory $(PROJECT) python -m detect synth

detect: ## Print the ranked issues found in the call logs (#58; no model calls)
	uv run --directory $(PROJECT) python -m detect run

detect-eval: ## Measure detection against the planted defects, with recall by rate and volume (#58)
	uv run --directory $(PROJECT) python -m detect eval

eval: ## Run the reference suite (#27; model calls, cached): AGENT=path for another agent, NO_CACHE=1, ONLY=test-id
	uv run --directory $(PROJECT) python -m eval $(if $(AGENT),--agent $(abspath $(AGENT))) $(if $(NO_CACHE),--no-cache) $(if $(ONLY),--only $(ONLY))

spend: ## Print the estimated model spend by day and source from the spend log (#27; SINCE=YYYY-MM-DD)
	uv run --directory $(PROJECT) python -m sim spend $(if $(SINCE),--since $(SINCE))

memo: ## Build docs/memo/memo.pdf (Tectonic; pass TECTONIC=/path/to/tectonic if it is not on PATH)
	$(TECTONIC) docs/memo/memo.tex

clean: ## Remove the venv, node_modules and Python caches
	rm -rf $(PROJECT)/.venv $(FRONTEND)/node_modules
	find $(PROJECT) -type d -name __pycache__ -prune -exec rm -rf {} +
