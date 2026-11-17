# Sourcebound hub
#   make setup            Python environment (.venv); links `sb` into ~/.local/bin
#   make skill            install the lead playbook for Claude Code (~/.claude/skills)
#   make agents           install the subagents at user level (~/.claude/agents/sb-*.md)
#   make install          setup + skill + agents; then run `sb init` once per machine
# Without make (Windows): uv sync, then `uv run sb install`; the targets below only call `sb`.
#   make new P=slug T="Title" [L=de]   new project from templates/project
#   make test             unit tests + offline pipeline tests
#   make status           lake tables and latest snapshots
#   make db-up / db-down  optional Postgres catalog (web apps, several machines)
BIN ?= $(HOME)/.local/bin

setup:
	uv sync
	@.venv/bin/sb install path --bin "$(BIN)"

skill:
	@.venv/bin/sb install skill

# Symlinks, so projects outside this folder use the same agents and follow updates.
agents:
	@.venv/bin/sb install agents

# Everything, then the two folders the user chooses (asked in a terminal; an agent passes them:
# sb init --data-root PATH --projects-dir PATH).
install:
	uv sync
	@.venv/bin/sb install --bin "$(BIN)"

new:
	@test -n "$(P)" -a -n "$(T)" || { echo 'usage: make new P=<slug> T="<title>" [L=de]'; exit 1; }
	.venv/bin/sb new $(P) --title "$(T)" --lang $(or $(L),en)

test:
	.venv/bin/pytest -q

status:
	@.venv/bin/sb lake tables
	@.venv/bin/sb lake snapshots

db-up:
	docker compose up -d
db-down:
	docker compose down

.PHONY: setup skill agents install new test status db-up db-down
