"""Resolving the real client address."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """The caller's address.

    This reads `request.client.host` and nothing else. When the app runs behind
    a reverse proxy, uvicorn must be started with `--proxy-headers` and
    `--forwarded-allow-ips` so it rewrites that value from X-Forwarded-For for
    trusted peers only.

    Deliberately NOT parsing X-Forwarded-For here: the header is attacker-
    controlled, and reading it without knowing the trusted hop count lets any
    client claim any address — which would let one attacker evade an IP rate
    limit indefinitely while framing arbitrary third parties in the audit log.
    """
    return request.client.host if request.client else "unknown"
