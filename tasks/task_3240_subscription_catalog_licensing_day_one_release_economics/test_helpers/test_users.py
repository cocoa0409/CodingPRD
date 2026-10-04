"""Pre-built role headers for every role declared in the PRD (§2.1).

`Subscriber` is the one entity-backed role: a `Subscriber` request carries the
acting subscriber's `id` in `X-User-ID`, and every ownership check compares a
resource's `subscriber_id` against it. Fixtures that act as a subscriber MUST
call `make_subscriber_headers(subscriber["id"])` with the real entity id rather
than falling back to the shared constant.

`CatalogAdmin`, `CatalogAnalyst` and `Anonymous` hold opaque operator
identifiers that are never compared to any persisted entity, so the shared
constants are the canonical form for those three roles.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the three opaque roles, and for non-ownership
# calls made by a subscriber (the header still has to be present).
TEST_USERS = {
    "admin_headers": build_user_headers("test-catalog-admin-1", "CatalogAdmin"),
    "analyst_headers": build_user_headers("test-catalog-analyst-1", "CatalogAnalyst"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity_backed:Subscriber — fallback only for calls that are not ownership-gated.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
}


def make_subscriber_headers(subscriber_id: str) -> dict:
    """For the `Subscriber` role (entity_backed:Subscriber).

    Pass the actual Subscriber.id as `subscriber_id` whenever the call is
    ownership-gated — which is every subscriber action on a subscription,
    purchase or engagement event.
    """
    return build_user_headers(subscriber_id, "Subscriber")


def make_admin_headers(user_id: str = "test-catalog-admin-1") -> dict:
    """CatalogAdmin is opaque; the identifier is recorded for audit only."""
    return build_user_headers(user_id, "CatalogAdmin")


def make_analyst_headers(user_id: str = "test-catalog-analyst-1") -> dict:
    """CatalogAnalyst is opaque; the identifier is recorded for audit only."""
    return build_user_headers(user_id, "CatalogAnalyst")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    """Anonymous is opaque; the identifier is recorded for audit only."""
    return build_user_headers(user_id, "Anonymous")