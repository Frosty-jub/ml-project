FROM apache/airflow:3.3.2-python3.12@sha256:9df9c8be4096b9cc626bd7cb1f2b8c712eef66c59c615f8c7e6200871ca10bd1

USER root
RUN rm -f /etc/apt/sources.list.d/docker.list \
          /etc/apt/sources.list.d/mariadb.list \
          /etc/apt/sources.list.d/mssql-release.list \
          /etc/apt/sources.list.d/pgdg.list \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update -qq \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/project-venv \
    && chown -R airflow:root /opt/project-venv

USER airflow
COPY orchestration/airflow/requirements.lock /tmp/project-requirements.txt
RUN /opt/project-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/project-venv/bin/pip install --no-cache-dir \
       -r /tmp/project-requirements.txt

COPY --chown=airflow:root . /opt/project-template
ARG PROJECT_GIT_COMMIT
ARG PROJECT_GIT_DIRTY
ENV PROJECT_GIT_COMMIT=${PROJECT_GIT_COMMIT} PROJECT_GIT_DIRTY=${PROJECT_GIT_DIRTY}
