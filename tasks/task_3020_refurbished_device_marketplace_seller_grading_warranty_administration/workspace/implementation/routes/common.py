"""Shared route plumbing."""

from middleware import authenticate, require_role


def guard(method, path, roles, credentials_optional=False):
    """Run priority 1 (credentials) then priority 3 (role) for this endpoint."""
    principal = authenticate(method, path, credentials_optional=credentials_optional)
    require_role(principal, roles)
    return principal