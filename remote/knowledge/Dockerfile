# The knowledge base's indexer, search and MCP server (W10). Build online
# (knowledge.sh build); the image then runs with no internet.
FROM python:3.13-slim
RUN pip install --no-cache-dir --root-user-action=ignore "mcp>=2.2,<3" "uvicorn>=0.30" numpy pyyaml
RUN useradd -r -u 10002 knowledge
WORKDIR /app
COPY kb.py index.py server.py eval.py collections.json ./
COPY cases ./cases
USER knowledge
EXPOSE 8080
CMD ["python", "server.py"]
