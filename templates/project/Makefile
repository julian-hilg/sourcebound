# Project build. Inside a hub it uses <hub>/.venv; anywhere else the `sb` on PATH (sb init, sb doctor).
# Without make (Windows): `sb run` does the same (sb run = make all; sb run analysis figures; ...).
#   make all       analysis -> figures -> bib -> lineage -> paper -> check
#   make analysis  every analysis/*.py in name order (records results, writes tables)
#   make figures   figures/make_figures.py
#   make paper     sb build: sb sync -> LaTeX -> deliverables/<slug>.pdf (skipped if LaTeX is not installed)
#   make handover  sb handover: dist/handover (Markdown, results, tables, figures) for other renderers
#   make check     sb check (ledger, citations, results, contracts)
#   make publish   sb publish (bundle + gates; push only with: make push)
HUB  ?= $(shell d="$(CURDIR)"; while [ "$$d" != / ]; do [ -f "$$d/hub.toml" ] && echo "$$d" && break; d=$$(dirname "$$d"); done)
SB   ?= $(if $(HUB),$(HUB)/.venv/bin/sb,sb)
PY   ?= $(shell $(SB) which python 2>/dev/null)
PAPER:= deliverables/paper

all: analysis figures bib lineage paper check

hub:
	@test -n "$(PY)" -a -x "$(PY)" || { echo "Sourcebound environment not found: run make setup in the checkout, then sb init"; exit 1; }

analysis: hub
	$(SB) run analysis

figures: hub
	$(SB) run figures

bib: hub
	$(SB) bib sync

lineage: hub
	$(SB) lineage

paper: hub
	$(SB) build

handover: hub
	$(SB) handover

check: hub
	$(SB) check

publish: hub
	$(SB) publish

push: hub
	$(SB) publish --push

clean:
	-cd $(PAPER) && latexmk -c
	rm -rf dist

.PHONY: all hub analysis figures bib lineage paper handover check publish push clean
