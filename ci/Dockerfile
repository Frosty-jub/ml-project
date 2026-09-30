FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -qq && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* && python -m venv /opt/project-venv
COPY orchestration/airflow/requirements.lock /tmp/requirements.lock
COPY ci/test-requirements.lock /tmp/test-requirements.lock
RUN /opt/project-venv/bin/pip install --no-cache-dir -r /tmp/requirements.lock -r /tmp/test-requirements.lock
COPY . /opt/project-template
ARG PROJECT_GIT_COMMIT
ENV PROJECT_GIT_COMMIT=${PROJECT_GIT_COMMIT} PROJECT_GIT_DIRTY=false \
    PATH=/opt/project-venv/bin:$PATH PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1
WORKDIR /project
