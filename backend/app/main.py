"""Minimal ASGI application; product routes are intentionally deferred."""

from fastapi import FastAPI

from app.config import load_settings

load_settings()
app = FastAPI(title="Simple Sudoku API", version="0.1.0")
