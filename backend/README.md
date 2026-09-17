# Backend — Finance Support API

FastAPI backend for the AI-Powered Personal Financial Decision Support System.

## Quick Start

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Start the server (from backend/ directory)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

| Method | Path              | Description                  |
| ------ | ----------------- | ---------------------------- |
| GET    | `/api/health`     | Application liveness check   |
| GET    | `/api/health/db`  | Database connectivity check  |

## API Documentation

Once the server is running:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
