FROM python:3.12-slim
ENV PYTHONPATH=/srv PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt ./
RUN pip install --disable-pip-version-check -r requirements.txt
COPY app/ ./app/
COPY sql/ ./sql/
CMD ["python", "-m", "app.gateway"]
