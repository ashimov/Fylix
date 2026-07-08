.PHONY: help master-key certs up down logs migrate revision test lint fmt clean admin-create age-key backup restore audit scan

help:
	@echo "Targets:"
	@echo "  make master-key  - generate secrets/master_key (one-off)"
	@echo "  make certs       - generate dev self-signed TLS"
	@echo "  make up          - docker compose up -d"
	@echo "  make down        - docker compose down"
	@echo "  make logs        - docker compose logs -f"
	@echo "  make migrate     - run alembic upgrade head inside api container"
	@echo "  make revision m=xxx - new alembic revision"
	@echo "  make test        - run backend tests (pytest)"
	@echo "  make lint        - ruff + mypy"
	@echo "  make fmt         - ruff format"
	@echo "  make clean       - prune containers + volumes (DESTRUCTIVE)"
	@echo "  make age-key     - generate age backup key pair (one-off)"
	@echo "  make backup      - create encrypted backup (requires age)"
	@echo "  make restore file=<path> - restore from backup (DESTRUCTIVE)"
	@echo "  make rotate-key  - rotate master encryption key"

master-key:
	./scripts/gen_master_key.sh

certs:
	./scripts/gen_dev_certs.sh

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(m)"

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app

fmt:
	cd backend && uv run ruff format .

clean:
	docker compose down -v
	rm -rf data/postgres data/redis data/minio

admin-create:
	@test -n "$(email)" || (echo "usage: make admin-create email=x pw=y"; exit 1)
	@test -n "$(pw)" || (echo "usage: make admin-create email=x pw=y"; exit 1)
	docker compose exec api /opt/venv/bin/python scripts/create_admin.py --email "$(email)" --password "$(pw)"

age-key:
	./scripts/age-keygen.sh

backup:
	./scripts/backup.sh

restore:
	@test -n "$(file)" || (echo "usage: make restore file=backups/fylix-backup-*.tar.age"; exit 1)
	./scripts/restore.sh "$(file)"

rotate-key:
	./scripts/rotate_master_key.sh

audit:
	cd backend && uv export --frozen --no-dev > /tmp/requirements-frozen.txt && \
	  pip-audit -r /tmp/requirements-frozen.txt --strict && \
	  rm /tmp/requirements-frozen.txt

scan:
	@echo "Running bandit..."
	cd backend && bandit -c pyproject.toml -r app/ -ll -i
	@echo ""
	@echo "Running trivy on api image..."
	docker build -f backend/Dockerfile -t fylix-api:local backend/
	trivy image --severity HIGH,CRITICAL --ignore-unfixed fylix-api:local
