"""python -m app -> levanta la app (ver nucleo/arranque.py)."""
from app.main import app
from nucleo.arranque import correr

if __name__ == "__main__":
    correr(app)
