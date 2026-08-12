PYTHON ?= python3
HOST ?= 127.0.0.1
PORT ?= 8765
PID_FILE := .dashboard.pid
LOG_FILE := .dashboard.log

.PHONY: up down restart status test

up:
	@if [ -f "$(PID_FILE)" ]; then \
		pid=$$(cat "$(PID_FILE)"); \
		if kill -0 "$$pid" 2>/dev/null && ps -p "$$pid" -o command= | grep -Fq "app.py"; then \
			echo "Dashboard already running at http://$(HOST):$(PORT) (PID $$pid)"; \
			exit 0; \
		fi; \
		rm -f "$(PID_FILE)"; \
	fi
	@nohup "$(PYTHON)" app.py --host "$(HOST)" --port "$(PORT)" >"$(LOG_FILE)" 2>&1 & echo $$! >"$(PID_FILE)"
	@sleep 1
	@if kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null; then \
		echo "Dashboard running at http://$(HOST):$(PORT)"; \
	else \
		echo "Dashboard failed to start. See $(LOG_FILE)."; \
		rm -f "$(PID_FILE)"; \
		exit 1; \
	fi

down:
	@if [ ! -f "$(PID_FILE)" ]; then \
		echo "Dashboard is not running."; \
		exit 0; \
	fi
	@pid=$$(cat "$(PID_FILE)"); \
	if kill -0 "$$pid" 2>/dev/null && ps -p "$$pid" -o command= | grep -Fq "app.py"; then \
		kill "$$pid"; \
		for attempt in 1 2 3 4 5; do \
			kill -0 "$$pid" 2>/dev/null || break; \
			sleep 1; \
		done; \
		if kill -0 "$$pid" 2>/dev/null; then \
			echo "Dashboard did not stop. PID file retained."; \
			exit 1; \
		fi; \
	fi; \
	rm -f "$(PID_FILE)"; \
	echo "Dashboard stopped."

restart: down up

status:
	@if [ -f "$(PID_FILE)" ] && kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null && ps -p "$$(cat "$(PID_FILE)")" -o command= | grep -Fq "app.py"; then \
		echo "Dashboard running at http://$(HOST):$(PORT) (PID $$(cat "$(PID_FILE)"))"; \
	else \
		echo "Dashboard is not running."; \
	fi

test:
	@"$(PYTHON)" -m unittest discover -s tests -v
