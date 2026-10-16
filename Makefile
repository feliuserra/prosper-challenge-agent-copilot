# Prosper Challenge — run everything from the repo root.
# Dependencies are managed with uv (https://docs.astral.sh/uv/) and npm.

PROJECT := backend
FRONTEND := frontend
TECTONIC ?= tectonic

.PHONY: help install run dev test clinic-reset synth detect detect-eval demo-seed demo-calls judge judge-eval eval spec build record spend memo clean

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
dev: ## Run the voice agent and the editor together (then open http://localhost:5173): STUB=name replays the Copilot's recorded streams (no model calls), RECORD=name records live ones (#31; folders in backend/copilot/recordings/)
	$(if $(STUB),COPILOT_REPLAY=copilot/recordings/$(STUB)) $(if $(RECORD),COPILOT_RECORD=copilot/recordings/$(RECORD)) \
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

demo-seed: ## Install the demo's weak Linden Grove agent, its 22 mock production calls and 3 tickets as agents/linden-grove.json and workspaces/linden-grove/ (#32; no model calls): FORCE=1 to replace a changed agent
	uv run --directory $(PROJECT) python -m demo install $(if $(FORCE),--force)

demo-calls: ## Make the demo's mock production calls that are not in backend/demo/workspace yet (#32; model calls, about 9 cents a call; all 22 cost $1.94): ONLY=c01,c02, FORCE=1 to make them again
	uv run --directory $(PROJECT) python -m demo calls $(if $(ONLY),--only $(ONLY)) $(if $(FORCE),--force)

judge: ## The model judge on a workspace's flagged calls plus a sample (#32; model calls, stored per call: the 22 demo calls cost about $0.40, a rerun nothing): WORKSPACE=linden-grove, RATE=1 (the share of unflagged calls), FORCE=1
	uv run --directory $(PROJECT) python -m detect judge $(or $(WORKSPACE),linden-grove) --rate $(or $(RATE),1) $(if $(FORCE),--force)

judge-eval: ## Measure the judge's stored results against the demo's planted defects (#32; no model calls)
	uv run --directory $(PROJECT) python -m demo eval

eval: ## Run the reference suite (#27; model calls, cached): AGENT=path for another agent, NO_CACHE=1, ONLY=test-id; MUTANTS=1 for the mutants; JUDGE=model to calibrate a judge; SPEC=workspace to check a spec (#29); COPILOT=1 to build clinic-a's agent and test it (#30; about $12 uncached; WORKSPACE=id, RESPEC=1, NO_LOOP=1 for the build alone, about $2.20)
	uv run --directory $(PROJECT) python -m eval $(if $(COPILOT),--copilot $(if $(WORKSPACE),--workspace $(WORKSPACE)) $(if $(RESPEC),--respec) $(if $(NO_LOOP),--no-loop)) $(if $(SPEC),--spec $(SPEC)) $(if $(JUDGE),--judge $(JUDGE)) $(if $(MUTANTS),--mutants) $(if $(AGENT),--agent $(abspath $(AGENT))) $(if $(NO_CACHE),--no-cache) $(if $(ONLY),--only $(ONLY))

spec: ## Write a workspace's spec from its guidelines (#29; model calls, about $0.35): WORKSPACE=id, GUIDELINES=path to paste a file first
	uv run --directory $(PROJECT) python -m copilot spec $(WORKSPACE) $(if $(GUIDELINES),--guidelines $(abspath $(GUIDELINES)))

build: ## Build a workspace's agent from the template and loop until its approved tests pass (#30; model calls, about $1.50 and up): WORKSPACE=id, NO_CACHE=1
	uv run --directory $(PROJECT) python -m copilot build $(WORKSPACE) $(if $(NO_CACHE),--no-cache)

record: ## Write replayable Copilot streams from a workspace's stored spec and proposal (#31; no model calls): WORKSPACE=id, PROPOSAL=n
	uv run --directory $(PROJECT) python -m copilot record $(WORKSPACE) $(if $(PROPOSAL),--proposal $(PROPOSAL))

spend: ## Print the estimated model spend by day and source from the spend log (#27; SINCE=YYYY-MM-DD)
	uv run --directory $(PROJECT) python -m sim spend $(if $(SINCE),--since $(SINCE))

memo: ## Build docs/memo/memo.pdf (Tectonic; pass TECTONIC=/path/to/tectonic if it is not on PATH)
	$(TECTONIC) docs/memo/memo.tex

clean: ## Remove the venv, node_modules and Python caches
	rm -rf $(PROJECT)/.venv $(FRONTEND)/node_modules
	find $(PROJECT) -type d -name __pycache__ -prune -exec rm -rf {} +
