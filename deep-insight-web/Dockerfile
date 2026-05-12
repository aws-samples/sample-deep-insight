FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Korean fonts for matplotlib charts (chat_agent.create_chart).
# python:3.12-slim has no Korean font; without this, chart labels render as □□□.
# fontconfig provides fc-cache (not included in slim image); fonts-nanum ships
# NanumGothic which chat_agent prefers as font.family.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-nanum \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 appuser
USER appuser

COPY ops/ ops/
COPY app.py .
COPY chat_agent.py .
COPY static/ static/
COPY sample_data/ sample_data/
COPY sample_reports/ sample_reports/

EXPOSE 8080

CMD ["python", "app.py"]
