# Prosper Challenge — run everything from the repo root.
# Dependencies are managed with uv (https://docs.astral.sh/uv/) and npm.

PROJECT := backend
FRONTEND := frontend

.PHONY: help install run dev test clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

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

test: ## Run the backend tests
	uv run --directory $(PROJECT) pytest

clean: ## Remove the venv, node_modules and Python caches
	rm -rf $(PROJECT)/.venv $(FRONTEND)/node_modules
	find $(PROJECT) -type d -name __pycache__ -prune -exec rm -rf {} +
