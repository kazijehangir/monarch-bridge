FROM python:3.11-slim

WORKDIR /app

# Install git to clone the fork
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY main.py .

# Persistence volume
RUN mkdir /data
ENV SESSION_FILE=/data/monarch_session.pickle
VOLUME /data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
