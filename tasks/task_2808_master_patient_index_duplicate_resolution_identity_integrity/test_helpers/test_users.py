"""Header builders for the five declared roles (PRD §2.1).

Four of the five roles carry an opaque ``X-User-ID`` that the service only
records on the rows it writes.  ``SiteRegistrar`` is the exception: its
``X-User-ID`` must be the identifier of the RegistrationSite the registrar
works at, so registrar headers are always built from a site id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_IDENTITY_ANALYST,
    ROLE_MPI_ADMIN,
    ROLE_PRIVACY_OFFICER,
    ROLE_SITE_REGISTRAR,
    ROLE_STEWARD_APPROVER,
)

# ─── Stable opaque user identifiers ───────────────────
ANALYST_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"
STEWARD_USER_ID = "steward-1"
STEWARD_2_USER_ID = "steward-2"
OFFICER_USER_ID = "officer-1"
ADMIN_USER_ID = "admin-1"


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build request headers for an arbitrary role/user pair."""
    return build_user_headers(user_id, role)


def analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_IDENTITY_ANALYST)


def steward_headers(user_id: str = STEWARD_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_STEWARD_APPROVER)


def officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRIVACY_OFFICER)


def admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_MPI_ADMIN)


def make_site_registrar_headers(site_id: str) -> Dict[str, str]:
    """Registrar headers whose ``X-User-ID`` is the registrar's own site id."""
    return build_user_headers(site_id, ROLE_SITE_REGISTRAR)


# Backwards-friendly alias used by several tests.
registrar_headers = make_site_registrar_headers


def headers_without_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers carrying an ``X-User-ID`` but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_for_role(role: str, site_id: str = "") -> Dict[str, str]:
    """Return usable headers for ``role``, threading ``site_id`` for registrars."""
    if role == ROLE_SITE_REGISTRAR:
        return make_site_registrar_headers(site_id)
    if role == ROLE_IDENTITY_ANALYST:
        return analyst_headers()
    if role == ROLE_STEWARD_APPROVER:
        return steward_headers()
    if role == ROLE_PRIVACY_OFFICER:
        return officer_headers()
    if role == ROLE_MPI_ADMIN:
        return admin_headers()
    raise ValueError(f"unknown role: {role}")
