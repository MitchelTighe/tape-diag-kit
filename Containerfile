ARG PYTHON_IMAGE=docker.io/library/python:3.9.25-slim-bookworm
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY requirements-dev.txt requirements-build.txt /src/
RUN python -m pip install --no-cache-dir -r requirements-dev.txt -r requirements-build.txt
COPY . /src/
RUN python -m build --no-isolation --outdir /dist && python -m pip install --no-deps /dist/*.whl
WORKDIR /tmp
CMD ["sh", "/src/scripts/check-container.sh"]
