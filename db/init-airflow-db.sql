-- db/init-airflow-db.sql
-- Runs once on empty volume only. Creates the Airflow metadata database.
-- The app database (courtaccess) is created by POSTGRES_DB in docker-compose.yml.
CREATE DATABASE airflow_metadata;
