"""Pre-built role headers for every role in the system.

``PlatformAdmin`` is opaque: its identifier is never compared to any entity's
``id``.  ``Account`` and ``Recipient`` are entity-backed, so ownership-gated
calls MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.  Safe for the opaque operator role, and for entity-backed
# roles only in calls whose outcome does not depend on ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Fallback only: ownership-gated Account calls must use make_account_headers().
    "account_headers": build_user_headers("test-account-1", "Account"),
    # Fallback only: ownership-gated Recipient calls must use make_recipient_headers().
    "recipient_headers": build_user_headers("test-recipient-1", "Recipient"),
}


def make_account_headers(account_id: str) -> dict:
    """Headers for an Account (entity_backed:Account).

    Pass the acting account's real ``id`` whenever the endpoint owns or
    scopes resources by ``sender_account_id`` / ``owning_account_id`` /
    ``account_id``.
    """
    return build_user_headers(account_id, "Account")


def make_recipient_headers(recipient_id: str) -> dict:
    """Headers for a Recipient (entity_backed:Recipient).

    Pass the acting recipient's real ``id`` so the recipient acts only on the
    row it names.
    """
    return build_user_headers(recipient_id, "Recipient")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """Headers for the opaque PlatformAdmin role."""
    return build_user_headers(user_id, "PlatformAdmin")