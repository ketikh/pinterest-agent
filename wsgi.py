"""Gunicorn entry point."""

from ai_bag_agent import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
