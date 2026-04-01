-- db/init-mlflow-db.sql
-- Runs once on empty volume only (alongside init-airflow-db.sql).
-- Creates the dedicated MLflow tracking-store database.
-- The app database (courtaccess) is created by POSTGRES_DB in docker-compose.yml.
CREATE DATABASE mlflow;
