FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir "httpx>=0.27,<1.0"

COPY seeder.py ./seeder.py

ENTRYPOINT ["python", "seeder.py"]
CMD ["seed"]
