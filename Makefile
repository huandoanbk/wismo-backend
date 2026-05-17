PYTHON=.venv/bin/python
PYTEST=.venv/bin/pytest
RUFF=.venv/bin/ruff

check:
	$(PYTHON) manage.py check

test:
	$(PYTEST)

lint:
	$(RUFF) check .

migrations-check:
	$(PYTHON) manage.py makemigrations --check --dry-run

migrate:
	$(PYTHON) manage.py migrate --database=default
	$(PYTHON) manage.py migrate --database=vector

shell:
	$(PYTHON) manage.py shell
