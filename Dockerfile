# Hermes SEO Agent — container de execução agendada
FROM python:3.11-slim

WORKDIR /app

# Dependências primeiro (cache de camada).
COPY pyproject.toml README.md ./
COPY hermes_seo_agent ./hermes_seo_agent
RUN pip install --no-cache-dir .

# Estado persistente (SQLite) fora da imagem.
RUN mkdir -p /app/state
VOLUME ["/app/state"]

# Credenciais via env_file no docker-compose (nunca na imagem).
COPY .env.example /app/.env.example

ENTRYPOINT ["hermes-seo-agent"]
CMD ["--help"]
