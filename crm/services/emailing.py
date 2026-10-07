"""
Email provider abstraction (§58). Console provider is the default:
real token flow, delivery goes to server logs until an SMTP/API
provider is configured. No fake success — console IS the delivery.
"""

import logging
import os

logger = logging.getLogger("crm.email")


class EmailProvider:
    def send(self, to: str, subject: str, body: str) -> bool:
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    def send(self, to: str, subject: str, body: str) -> bool:
        logger.info("EMAIL to=%s subject=%s\n%s", to, subject, body)
        print(f"[EMAIL] to={to} subject={subject}\n{body}")
        return True


def get_provider() -> EmailProvider:
    name = os.environ.get("EMAIL_PROVIDER", "console")
    if name == "console":
        return ConsoleEmailProvider()
    raise ValueError(f"unknown EMAIL_PROVIDER: {name}")
