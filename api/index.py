"""Vercel entrypoint for the FastAPI application."""

from app.main import create_app

app = create_app()
