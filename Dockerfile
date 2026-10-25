FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Зависимости отдельным слоем — кэшируются, пока requirements.txt не меняется
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY mock_operator ./mock_operator
COPY config ./config
COPY migrations ./migrations

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000 9100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
