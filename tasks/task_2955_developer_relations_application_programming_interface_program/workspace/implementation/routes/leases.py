"""Sandbox leases: provisioning, validation and early release."""
from datetime import timedelta

from flask import Blueprint

from constants import (
    LEASE_STATES,
    MAX_LEASE_DAYS,
    MIN_LEASE_DAYS,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PLATFORM_ADMIN,
)
from db import new_id, store
from errors import ApiError, invalid
from middleware import endpoint, lookup, require_not_revoked, require_owner
from response import (
    array_response,
    enum_filter,
    object_response,
    pagination,
    string_filter,
)
from serializers import sandbox_lease_out
from services import trust
from services.common import (
    require_docs_acknowledged,
    require_good_standing,
    require_tos_current,
)
from validation import body

bp = Blueprint("leases", __name__)


def _lease(lease_id):
    return lookup(store.sandbox_leases, lease_id, "ERR_SANDBOX_LEASE_NOT_FOUND")


@bp.post("/sandbox-leases")
@endpoint([ROLE_DEVELOPER])
def create_lease():
    payload = body()
    developer_id = payload.string("developer_id", min_len=1)
    product_id = payload.string("api_product_id", min_len=1)
    starts_at = payload.instant("starts_at")
    lease_days = payload.integer(
        "lease_days", minimum=MIN_LEASE_DAYS, maximum=MAX_LEASE_DAYS
    )
    slug = payload.string("sample_app_slug", min_len=1)

    developer = lookup(store.developers, developer_id, "ERR_DEVELOPER_NOT_FOUND")
    product = lookup(store.api_products, product_id, "ERR_API_PRODUCT_NOT_FOUND")

    if slug not in product["sample_app_slugs"]:
        invalid("sample_app_slug must appear in the product's sample_app_slugs.")

    require_owner(developer["id"])
    require_good_standing(developer)
    require_not_revoked()
    require_tos_current(developer, product)
    require_docs_acknowledged(developer)

    expires_at = starts_at + timedelta(days=lease_days)

    for existing in store.sandbox_leases.values():
        if (
            existing["developer_id"] != developer["id"]
            or existing["api_product_id"] != product["id"]
            or existing["state"] != "ACTIVE"
        ):
            continue
        # half-open intervals: exact adjacency never overlaps
        if starts_at < existing["expires_at"] and existing["starts_at"] < expires_at:
            raise ApiError(
                "ERR_SANDBOX_INTERVAL_OVERLAP",
                "The requested interval overlaps an active lease on this product.",
            )

    lease = {
        "id": new_id(),
        "developer_id": developer["id"],
        "api_product_id": product["id"],
        "starts_at": starts_at,
        "lease_days": lease_days,
        "expires_at": expires_at,
        "sample_app_slug": slug,
        "state": "ACTIVE",
        "released_at": None,
        "closed_reason": None,
    }
    store.stamp_new(lease)
    store.sandbox_leases[lease["id"]] = lease
    return object_response(sandbox_lease_out(lease), 201)


@bp.get("/sandbox-leases/<lease_id>")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def read_lease(lease_id):
    lease = _lease(lease_id)
    require_owner(lease["developer_id"])
    return object_response(sandbox_lease_out(lease))


@bp.get("/sandbox-leases")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def list_leases():
    limit, offset = pagination()
    developer_id = string_filter("developer_id")
    product_id = string_filter("api_product_id")
    state = enum_filter("state", LEASE_STATES)

    records = store.ordered(store.sandbox_leases)
    if developer_id is not None:
        records = [r for r in records if r["developer_id"] == developer_id]
    if product_id is not None:
        records = [r for r in records if r["api_product_id"] == product_id]
    if state is not None:
        records = [r for r in records if r["state"] == state]

    total = len(records)
    page = records[offset : offset + limit]
    return array_response([sandbox_lease_out(r) for r in page], total, limit, offset)


@bp.post("/sandbox-leases/<lease_id>/validate")
@endpoint([ROLE_DEVELOPER])
def validate_lease(lease_id):
    body()
    lease = _lease(lease_id)
    require_owner(lease["developer_id"])

    if lease["state"] != "ACTIVE":
        raise ApiError(
            "ERR_LEASE_NOT_ACTIVE",
            "Only an ACTIVE lease may be validated; state is %s." % lease["state"],
        )

    require_not_revoked()

    if not lease["sample_app_slug"]:
        invalid("The lease carries no sample application to validate.")

    developer = store.developers[lease["developer_id"]]
    store.touch(lease)

    if developer["onboarding_state"] == "DOCS_ACKNOWLEDGED":
        developer["onboarding_state"] = "SANDBOX_VALIDATED"
    trust.refresh_snapshot(developer)
    store.touch(developer)

    return object_response(sandbox_lease_out(lease))


@bp.post("/sandbox-leases/<lease_id>/release")
@endpoint([ROLE_DEVELOPER])
def release_lease(lease_id):
    body()
    lease = _lease(lease_id)
    require_owner(lease["developer_id"])

    if lease["state"] != "ACTIVE":
        raise ApiError(
            "ERR_LEASE_NOT_ACTIVE",
            "Only an ACTIVE lease may be released; state is %s." % lease["state"],
        )

    require_not_revoked()

    lease["state"] = "RELEASED"
    lease["released_at"] = store.now()
    lease["closed_reason"] = "DEVELOPER_RELEASE"
    store.touch(lease)
    return object_response(sandbox_lease_out(lease))
