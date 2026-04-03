PYTHON=.venv/bin/python

dev-up:
	docker compose -f docker-compose.dev.yml up -d

dev-down:
	docker compose -f docker-compose.dev.yml down

test:
	$(PYTHON) -m pytest

migrate:
	$(PYTHON) manage.py migrate --database=default
	$(PYTHON) manage.py migrate --database=vector

shell:
	$(PYTHON) manage.py shell
