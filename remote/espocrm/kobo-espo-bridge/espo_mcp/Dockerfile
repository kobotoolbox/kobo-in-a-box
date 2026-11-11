# The EspoCRM MCP: the SDK only; the code is mounted at /bridge (read-only)
FROM python:3.13-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /bridge
CMD ["python3", "-I", "-u", "/bridge/espo_mcp/server.py"]
