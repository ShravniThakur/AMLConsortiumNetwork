# ACN case-management API.
# Local-services runtime image — deliberately the light requirements.txt set, NOT the
# torch/PyG ML stack (kept in requirements-ml.txt).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install runtime deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The reusable package and the service code.
COPY acn ./acn
COPY services ./services

EXPOSE 8000

# uvicorn serves the ASGI app; host 0.0.0.0 so the port is reachable from the host.
CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
