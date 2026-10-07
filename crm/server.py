"""CRM server entry. Run: myenv/bin/python -m uvicorn crm.server:app --port 8000."""

from dotenv import load_dotenv

load_dotenv()

from crm import db

db.migrate()

from crm import web  # noqa: E402
from crm.api import api as app  # noqa: E402,F401

web.register_routes(app)
web.register_pages(app)
