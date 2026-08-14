"""Business logic layer.

Endpoints stay thin: validate, delegate here, shape the response. Anything that
touches more than one table, or that has a rule worth testing on its own, lives
in a service rather than in a route handler.
"""

from app.services import auth_service, otp_service, token_service

__all__ = ["auth_service", "otp_service", "token_service"]
