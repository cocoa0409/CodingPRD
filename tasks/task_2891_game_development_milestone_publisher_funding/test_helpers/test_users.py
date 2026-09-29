"""Auth headers for every acting principal of PRD §2.1.

Three of the four roles are entity-backed, so their `X-User-ID` must be the id of
a row created earlier in the same test: a `Developer` presents its `Studio` id and
both publisher-side roles present their `PublisherUser` id. Only `PlatformAdmin`
is opaque, so it is the single role with a fixed constant identifier here; every
other header set is built per instance from a real row.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DEVELOPER,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER_FINANCE,
    ROLE_PUBLISHER_REVIEWER,
)

# PRD §2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque
# operator identifier not tied to any persisted entity."
PLATFORM_ADMIN_ID = "ops-platform-admin-01"

ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"user_id": PLATFORM_ADMIN_ID, "role": ROLE_PLATFORM_ADMIN},
    "developer": {"user_id": "<Studio.id>", "role": ROLE_DEVELOPER},
    "publisher_reviewer": {"user_id": "<PublisherUser.id>", "role": ROLE_PUBLISHER_REVIEWER},
    "publisher_finance": {"user_id": "<PublisherUser.id>", "role": ROLE_PUBLISHER_FINANCE},
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_developer_headers(studio_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting `Studio` (PRD §2.1)."""
    return build_user_headers(studio_id, ROLE_DEVELOPER)


def make_publisher_reviewer_headers(publisher_user_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting `PublisherUser` (PRD §2.1)."""
    return build_user_headers(publisher_user_id, ROLE_PUBLISHER_REVIEWER)


def make_publisher_finance_headers(publisher_user_id: str) -> Dict[str, str]:
    """`X-User-ID` is likewise the `id` of the acting `PublisherUser` (PRD §2.1)."""
    return build_user_headers(publisher_user_id, ROLE_PUBLISHER_FINANCE)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary role string, including unrecognized ones."""
    return build_user_headers(user_id, role)


# PRD §2.1: "If either header is absent, empty, or contains only whitespace..."
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """An empty header value — never a whitespace string, which the HTTP client rejects."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}
