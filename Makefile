# =============================================================================
# VietLegalGraphRAG — dev convenience targets
# =============================================================================
# The Open WebUI container takes ~2 minutes to boot (heavy Python import graph
# + embedding model load) before Uvicorn accepts any connection on :8080.
# Connecting before then gives "connection refused" — that is expected.
#
# Use `make up`: it blocks until the container reports (healthy), i.e. until
# http://localhost:8080 is actually reachable, then prints the URL. When your
# shell prompt returns, the app works. No guessing, no early-connect failures.
# =============================================================================

COMPOSE := docker compose --env-file src/infra/.env -f src/infra/docker-compose.yml
URL     := http://localhost:8080

.PHONY: up start restart down stop logs ps

## up: build (if needed), start, and WAIT until the app is reachable
up:
	$(COMPOSE) up -d --build --wait
	@echo ""
	@echo "✅ App is ready → $(URL)"

## start: start existing containers and WAIT until the app is reachable
##        (`docker compose start` has no --wait, so `up --wait` is used; it
##         reuses the existing container when config is unchanged)
start:
	$(COMPOSE) up -d --wait
	@echo ""
	@echo "✅ App is ready → $(URL)"

## restart: recreate and wait until reachable
restart:
	$(COMPOSE) up -d --force-recreate --wait
	@echo ""
	@echo "✅ App is ready → $(URL)"

## logs: follow container logs
logs:
	$(COMPOSE) logs -f

## ps: show container status (look for "healthy")
ps:
	$(COMPOSE) ps

## stop: stop containers (keep them)
stop:
	$(COMPOSE) stop

## down: stop and remove containers
down:
	$(COMPOSE) down
