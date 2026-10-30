FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY projectsync ./projectsync
COPY prompts ./prompts
COPY dify ./dify
RUN mkdir -p /app/data
EXPOSE 8080
CMD ["uvicorn", "projectsync.main:app", "--host", "0.0.0.0", "--port", "8080"]
