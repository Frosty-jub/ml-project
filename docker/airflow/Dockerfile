FROM apache/airflow:3.3.2-python3.12@sha256:9df9c8be4096b9cc626bd7cb1f2b8c712eef66c59c615f8c7e6200871ca10bd1
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/ml && chown -R airflow:0 /opt/ml
USER airflow
COPY docker/airflow/requirements-ml.lock.txt /tmp/ml-requirements.txt
# Keep ML dependencies separate from Airflow's own constrained environment.
RUN /opt/ml/bin/pip install --no-cache-dir -r /tmp/ml-requirements.txt
ENV PATH="/opt/ml/bin:${PATH}"
RUN git config --global --add safe.directory /workspace
WORKDIR /workspace
