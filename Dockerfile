FROM python:3.11-slim
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY main.py .
ENV PORT=8080
CMD ["python3", "main.py"]
