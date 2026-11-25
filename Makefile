# Mars EVA Planner: run the whole demo with one command.
#   make doctor   check that everything needed is installed and downloaded
#   make demo     install, download the data and start the app (first time)
#   make run      start the app again later (PORT=8001 to change the port)
# Without make (Windows): python tools/demo.py <command> does exactly the same.

PYTHON ?= $(shell python3 -c "import sys" >/dev/null 2>&1 && echo python3 || echo python)
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help doctor setup data run demo test

help doctor setup data run demo test:
	$(PYTHON) tools/demo.py $@ --port $(PORT)
