FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# Baza va PDF hisobotlar shu papkada — hostingda unga doimiy disk (volume) ulanadi
ENV DATA_DIR=/data

CMD ["python", "bot.py"]
