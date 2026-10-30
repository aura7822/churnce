FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY seed_data ./seed_data

RUN useradd --create-home --uid 10001 churnce
USER churnce

EXPOSE 8000
# Single worker on purpose: the review-gate scheduler runs in-process. State transitions are
# claimed with conditional UPDATEs, so extra replicas are safe, just redundant.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
