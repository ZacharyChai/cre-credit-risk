# CRE Credit Risk — one command reproduces everything end to end.
# `make all` runs the full pipeline from a clean clone.

VENV   := .venv
PYTHON := $(VENV)/bin/python
DB     := data/processed/loans.db

.PHONY: all setup fetch parse load benchmark segment drivers clean

all: setup drivers ## Full pipeline: setup -> fetch -> parse -> load -> benchmark -> segment -> drivers/charts

setup: $(VENV)/.installed ## Create venv and install requirements
$(VENV)/.installed: requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -q --upgrade pip
	$(PYTHON) -m pip install -q -r requirements.txt
	touch $@

fetch: setup ## Pull ABS-EE EX-102 XML from EDGAR into data/raw/
	$(PYTHON) src/fetch_absee.py

parse: fetch ## Parse XML into a tidy per-loan CSV
	$(PYTHON) src/parse_absee.py

load: parse ## Load tidy loans into SQLite ($(DB))
	$(PYTHON) src/parse_absee.py --load

benchmark: load ## Pull the H.15 Treasury benchmark, compute the rate-gap field
	$(PYTHON) src/rate_gap.py

segment: benchmark ## Run the risk-tier segmentation SQL
	sqlite3 $(DB) < src/segment.sql

drivers: segment ## Driver analysis + export charts
	$(PYTHON) src/drivers.py

clean: ## Remove generated data (keeps raw downloads)
	rm -f $(DB) data/processed/*.csv
	rm -f analysis/charts/*.png

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
