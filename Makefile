# Conexiones del MariaDB de desarrollo (ver docker-compose.dev.yml). Sobrescribe si usas otro servidor.
DEV_DB      ?= mariadb+pymysql://lic:lic_dev_pass@127.0.0.1:3306/licenses
TEST_DB     ?= mariadb+pymysql://lic:lic_dev_pass@127.0.0.1:3306/licenses_test
TEST_MIG_DB ?= mariadb+pymysql://lic:lic_dev_pass@127.0.0.1:3306/licenses_mig_test

.PHONY: install db-up db-down db-reset dev test migrate css css-watch
install:        ## dependencias de Python
	pip install -r requirements-dev.txt
db-up:          ## levanta MariaDB de desarrollo/pruebas (Docker)
	docker compose -f docker-compose.dev.yml up -d --wait
db-down:
	docker compose -f docker-compose.dev.yml down
db-reset:       ## BORRA los datos de desarrollo y vuelve a crear las bases
	docker compose -f docker-compose.dev.yml down -v && $(MAKE) db-up
migrate:
	LICENSE_DB_URL=$(DEV_DB) python -m app.cli db upgrade
dev: migrate    ## servidor con recarga contra el MariaDB de desarrollo
	LICENSE_DB_URL=$(DEV_DB) LICENSE_COOKIE_SECURE=false uvicorn app.main:app --reload
test:           ## pruebas contra el MariaDB de pruebas
	TEST_DATABASE_URL=$(TEST_DB) TEST_MIGRATIONS_DATABASE_URL=$(TEST_MIG_DB) python -m pytest -q
css:            ## compila Tailwind -> app/web/static/css/app.css
	cd frontend && npm install && npm run build
css-watch:
	cd frontend && npm run css:watch
