# app/main.py
from __future__ import annotations

# Re-export dell'app FastAPI definita in main.py (root)
from main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
