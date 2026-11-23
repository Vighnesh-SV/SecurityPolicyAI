FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# First start builds the knowledge base (needs GEMINI_API_KEY in .env), later starts are instant.
CMD ["sh", "-c", "[ -d data/chroma ] || python scripts/setup.py --no-memory; uvicorn spai.api:app --host 0.0.0.0 --port 8000"]
EXPOSE 8000
