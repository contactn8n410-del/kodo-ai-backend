FROM python:3.11-slim
WORKDIR /app
COPY main.py .
ENV PORT=8080
CMD ["python3", "main.py"]
