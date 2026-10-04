"""Role headers for every caller the tests use.

The two entity-backed roles (Talent, Buyer) get a per-instance builder: any
call that is ownership-gated must carry ``X-User-ID`` equal to the acting
entity's own ``id``, so headers are built from the entity the fixture just
created.  The opaque roles (Moderator, PlatformAdmin) use shared constants
because the server does not compare their ``X-User-ID`` to any entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Shared constants (opaque roles and non-ownership call sites) ────────

TEST_USERS = {
    "talent_headers": build_user_headers("test-talent-1", UserRole.TALENT.value),
    "buyer_headers": build_user_headers("test-buyer-1", UserRole.BUYER.value),
    "moderator_headers": build_user_headers(
        "test-moderator-1", UserRole.MODERATOR.value
    ),
    "admin_headers": build_user_headers(
        "test-admin-1", UserRole.PLATFORM_ADMIN.value
    ),
}


def make_talent_headers(talent_id):
    """Headers for a Talent acting as itself.

    ``talent_id`` must be the talent record's own ``id`` whenever the call is
    ownership-gated (identity submit, rates, pause/resume, accept/decline,
    video upload, tax-document submission).
    """

    return build_user_headers(str(talent_id), UserRole.TALENT.value)


def make_buyer_headers(buyer_id):
    """Headers for a Buyer acting as itself.

    ``buyer_id`` must be the buyer record's own ``id`` whenever the call is
    ownership-gated (order creation, attest/decline, confirm, re-record,
    dispute, license grant).
    """

    return build_user_headers(str(buyer_id), UserRole.BUYER.value)


def make_moderator_headers(operator_id="test-moderator-1"):
    """Moderator identity is opaque; any stable operator id is acceptable."""

    return build_user_headers(str(operator_id), UserRole.MODERATOR.value)


def make_admin_headers(operator_id="test-admin-1"):
    """PlatformAdmin identity is opaque; any stable operator id is acceptable."""

    return build_user_headers(str(operator_id), UserRole.PLATFORM_ADMIN.value)


ADMIN = TEST_USERS["admin_headers"]
MODERATOR = TEST_USERS["moderator_headers"]
