"""Entry point: `python main.py` starts the FastAPI server (serves the API
and, if built, the React frontend from frontend/dist)."""

from backend.main import run

if __name__ == "__main__":
    run()