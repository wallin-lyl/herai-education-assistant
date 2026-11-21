FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY bankend/requirements.txt /app/bankend/requirements.txt
RUN pip install --no-cache-dir -r /app/bankend/requirements.txt

COPY bankend /app/bankend
COPY deploy/web /app/build/web

WORKDIR /app/bankend

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
