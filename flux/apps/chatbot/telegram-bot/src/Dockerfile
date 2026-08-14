FROM python:3.11-slim

WORKDIR /app

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin bot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

USER 1000

CMD ["python3", "-u", "bot.py"]
