PY ?= python

.PHONY: all data analyze figures docx verify cpsat venv-ortools clean

all: data analyze figures docx verify

data:
	$(PY) collect_experiments.py
	$(PY) collect_extended.py
	$(PY) collect_adaptive.py
	$(PY) collect_validation.py
	$(PY) collect_gap.py
	$(PY) collect_research.py
	$(PY) make_slices.py
	$(PY) collect_derived.py
	$(PY) offline_bruteforce.py

analyze:
	$(PY) stats_analysis.py
	$(PY) analyze_adaptive.py
	$(PY) analyze_research.py

figures:
	$(PY) make_diagrams.py
	$(PY) make_figures.py
	$(PY) make_research_figures.py
	$(PY) make_adaptive_figures.py
	$(PY) make_validation_figure.py

docx:
	@if [ -f report.md ]; then $(PY) make_docx.py; else echo "report.md 未提供，跳过 docx"; fi

verify:
	$(PY) verify.py

venv-ortools:
	$(PY) -m venv .venv-ortools
	.venv-ortools/bin/python -m pip install -U pip
	.venv-ortools/bin/pip install -r requirements-ortools.txt

cpsat:
	.venv-ortools/bin/python cpsat_offline.py

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .venv-ortools