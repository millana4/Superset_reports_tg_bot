FROM python:3.12-slim

# Не писать .pyc, не буферизовать stdout/stderr (логи сразу видны в docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала зависимости — для кэширования слоёв
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код
COPY . .

# Папка для логов (монтируется как volume в compose)
RUN mkdir -p logs

CMD ["python", "main.py"]