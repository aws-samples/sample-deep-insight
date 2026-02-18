FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 appuser
USER appuser

COPY app.py .
COPY static/ static/
COPY sample_data/ sample_data/
COPY sample_reports/ sample_reports/

EXPOSE 8080

CMD ["python", "app.py"]
