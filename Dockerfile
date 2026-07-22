FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY metadata ./metadata
COPY evals ./evals
RUN pip install --no-cache-dir .
RUN dak seed --database /app/data/retail.duckdb --orders 8000
EXPOSE 8000
CMD ["dak", "serve", "--host", "0.0.0.0"]
