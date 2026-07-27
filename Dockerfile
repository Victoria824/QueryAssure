FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY metadata ./metadata
COPY evals ./evals
RUN pip install --no-cache-dir --upgrade "pip>=26.1.2" \
    && pip install --no-cache-dir . \
    && groupadd --system queryassure \
    && useradd --system --gid queryassure --home-dir /app queryassure \
    && mkdir -p /app/data \
    && chown -R queryassure:queryassure /app
USER queryassure
RUN queryassure seed --database /app/data/retail.duckdb --orders 8000
EXPOSE 8000
CMD ["queryassure", "serve", "--host", "0.0.0.0"]
