# mlflow.Dockerfile — pre-built MLflow tracking server
# Extends the official image with backend/artifact store drivers so they
# are baked into the layer at build time rather than installed on every
# container start.
#
# Tag is pinned to match pyproject.toml: mlflow>=2.13.0,<3
FROM ghcr.io/mlflow/mlflow:v3.10.1

RUN pip install --no-cache-dir \
    psycopg2-binary \
    google-cloud-storage \
    "protobuf<5.0.0"
