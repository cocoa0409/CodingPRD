"""API products, versions, deprecation timelines, roadmap and allocation runs."""
import re
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from constants import (
    DATA_SENSITIVITIES,
    LIFECYCLE_STATES,
    MAX_CONCURRENT_DEPRECATIONS,
    ROLE_DEVELOPER,
    ROLE_DEVREL_MANAGER,
    ROLE_PARTNER_SUPPORT,
    ROLE_PLATFORM_ADMIN,
    ROLE_TRUST_SAFETY,
    SCOPE_SENSITIVITIES,
)
from db import new_id, store, whole_days_between
from errors import ApiError, invalid
from middleware import endpoint, lookup
from response import array_response, enum_filter, object_response, pagination
from serializers import api_product_out, api_version_out, feedback_item_out
from services import feedback, lifecycle, quota
from validation import body

bp = Blueprint("catalog", __name__)

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _product(product_id):
    return lookup(store.api_products, product_id, "ERR_API_PRODUCT_NOT_FOUND")


def _version(version_id):
    return lookup(store.api_versions, version_id, "ERR_API_VERSION_NOT_FOUND")


@bp.post("/api-products")
@endpoint([ROLE_PLATFORM_ADMIN])
def create_product():
    payload = body()
    name = payload.string("name", min_len=1, max_len=120)
    sensitivity = payload.string("data_sensitivity", choices=DATA_SENSITIVITIES)
    catalog = payload.object_array("scope_catalog", min_items=1, max_items=20)
    slugs = payload.string_array("sample_app_slugs", min_items=1, max_items=10)
    sustained_pool = payload.integer("sustained_rpm_pool", minimum=1)
    monthly_pool = payload.integer("monthly_call_pool", minimum=1)
    required_tos = payload.integer("required_tos_version", required=False, minimum=1)

    entries = []
    seen = set()
    for entry in catalog:
        scope = entry.get("scope")
        scope_sensitivity = entry.get("sensitivity")
        if not isinstance(scope, str) or scope == "":
            invalid("scope_catalog entries require a non-empty scope string.")
        if scope_sensitivity not in SCOPE_SENSITIVITIES:
            invalid(
                "scope_catalog sensitivity must be one of %s."
                % ", ".join(SCOPE_SENSITIVITIES)
            )
        if scope in seen:
            invalid("scope_catalog scope values must be unique.")
        seen.add(scope)
        entries.append({"scope": scope, "sensitivity": scope_sensitivity})

    product = {
        "id": new_id(),
        "name": name,
        "data_sensitivity": sensitivity,
        "scope_catalog": entries,
        "sample_app_slugs": list(slugs),
        "sustained_rpm_pool": sustained_pool,
        "monthly_call_pool": monthly_pool,
        "allocated_sustained_rpm": 0,
        "allocated_monthly_calls": 0,
        "required_tos_version": 1 if required_tos is None else required_tos,
        "demand_index": Decimal("0.00"),
    }
    store.stamp_new(product)
    store.api_products[product["id"]] = product
    return object_response(api_product_out(product), 201)


@bp.get("/api-products/<product_id>")
@endpoint(
    [
        ROLE_DEVELOPER,
        ROLE_DEVREL_MANAGER,
        ROLE_PLATFORM_ADMIN,
        ROLE_TRUST_SAFETY,
        ROLE_PARTNER_SUPPORT,
    ]
)
def read_product(product_id):
    return object_response(api_product_out(_product(product_id)))


@bp.get("/api-products")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def list_products():
    limit, offset = pagination()
    sensitivity = enum_filter("data_sensitivity", DATA_SENSITIVITIES)
    records = store.ordered(store.api_products)
    if sensitivity is not None:
        records = [r for r in records if r["data_sensitivity"] == sensitivity]
    total = len(records)
    page = records[offset : offset + limit]
    return array_response([api_product_out(r) for r in page], total, limit, offset)


@bp.post("/api-products/<product_id>/program-adjustments")
@endpoint([ROLE_PLATFORM_ADMIN])
def adjust_product(product_id):
    payload = body()
    sustained_pool = payload.integer("sustained_rpm_pool", required=False, minimum=1)
    monthly_pool = payload.integer("monthly_call_pool", required=False, minimum=1)
    required_tos = payload.integer("required_tos_version", required=False, minimum=1)
    payload.string("adjustment_reason", min_len=1)

    product = _product(product_id)

    if sustained_pool is not None and sustained_pool < product["allocated_sustained_rpm"]:
        raise ApiError(
            "ERR_POOL_BELOW_ALLOCATED",
            "sustained_rpm_pool would fall below the allocated %d."
            % product["allocated_sustained_rpm"],
        )
    if monthly_pool is not None and monthly_pool < product["allocated_monthly_calls"]:
        raise ApiError(
            "ERR_POOL_BELOW_ALLOCATED",
            "monthly_call_pool would fall below the allocated %d."
            % product["allocated_monthly_calls"],
        )

    if sustained_pool is not None:
        product["sustained_rpm_pool"] = sustained_pool
    if monthly_pool is not None:
        product["monthly_call_pool"] = monthly_pool
    if required_tos is not None:
        product["required_tos_version"] = required_tos
    store.touch(product)
    return object_response(api_product_out(product))


@bp.post("/api-products/<product_id>/versions")
@endpoint([ROLE_PLATFORM_ADMIN])
def create_version(product_id):
    payload = body()
    semver = payload.string("semver", min_len=1)
    if not SEMVER_RE.match(semver):
        invalid("semver must match <major>.<minor>.<patch>.")
    breaking = payload.boolean("breaking_change", required=False, default=False)

    product = _product(product_id)

    version = {
        "id": new_id(),
        "api_product_id": product["id"],
        "semver": semver,
        "lifecycle_state": "PREVIEW",
        "breaking_change": bool(breaking),
        "migration_guide_url": None,
        "migration_guide_published_at": None,
        "deprecation_announced_at": None,
        "sunset_at": None,
        "required_notice_days": None,
        "notice_days_at_announcement": None,
        "sunset_completed_at": None,
    }
    store.stamp_new(version)
    store.api_versions[version["id"]] = version
    return object_response(api_version_out(version), 201)


@bp.get("/api-products/<product_id>/versions")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def list_versions(product_id):
    limit, offset = pagination()
    state = enum_filter("lifecycle_state", LIFECYCLE_STATES)
    product = _product(product_id)
    records = [
        v
        for v in store.ordered(store.api_versions)
        if v["api_product_id"] == product["id"]
    ]
    if state is not None:
        records = [r for r in records if r["lifecycle_state"] == state]
    total = len(records)
    page = records[offset : offset + limit]
    return array_response([api_version_out(r) for r in page], total, limit, offset)


@bp.get("/api-products/<product_id>/roadmap")
@endpoint([ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def read_roadmap(product_id):
    limit, offset = pagination()
    product = _product(product_id)
    records = feedback.roadmap_ordered(product["id"])
    total = len(records)
    page = records[offset : offset + limit]
    return array_response([feedback_item_out(r) for r in page], total, limit, offset)


@bp.post("/api-products/<product_id>/upgrade-allocation-run")
@endpoint([ROLE_DEVREL_MANAGER])
def run_allocation(product_id):
    body()
    product = _product(product_id)
    summary = quota.allocation_run(product)
    return object_response(summary)


@bp.get("/api-versions/<version_id>")
@endpoint([ROLE_DEVELOPER, ROLE_DEVREL_MANAGER, ROLE_PLATFORM_ADMIN])
def read_version(version_id):
    return object_response(api_version_out(_version(version_id)))


@bp.post("/api-versions/<version_id>/promote")
@endpoint([ROLE_PLATFORM_ADMIN])
def promote_version(version_id):
    body()
    version = _version(version_id)
    if version["lifecycle_state"] != "PREVIEW":
        raise ApiError(
            "ERR_VERSION_STATE_INVALID",
            "Only a PREVIEW version may be promoted; state is %s."
            % version["lifecycle_state"],
        )
    version["lifecycle_state"] = "GENERAL_AVAILABILITY"
    store.touch(version)
    return object_response(api_version_out(version))


@bp.post("/api-versions/<version_id>/migration-guide")
@endpoint([ROLE_PLATFORM_ADMIN])
def publish_migration_guide(version_id):
    payload = body()
    url = payload.string("migration_guide_url", min_len=1)
    version = _version(version_id)
    if version["lifecycle_state"] == "SUNSET":
        raise ApiError(
            "ERR_VERSION_STATE_INVALID",
            "A migration guide cannot be published on a SUNSET version.",
        )
    version["migration_guide_url"] = url
    version["migration_guide_published_at"] = store.now()
    store.touch(version)
    return object_response(api_version_out(version))


@bp.post("/api-versions/<version_id>/announce-deprecation")
@endpoint([ROLE_PLATFORM_ADMIN])
def announce_deprecation(version_id):
    payload = body()
    notice_days = payload.integer("notice_days", minimum=0)

    version = _version(version_id)
    product = store.api_products.get(version["api_product_id"])

    if version["lifecycle_state"] != "GENERAL_AVAILABILITY":
        raise ApiError(
            "ERR_VERSION_STATE_INVALID",
            "Only a GENERAL_AVAILABILITY version may be deprecated; state is %s."
            % version["lifecycle_state"],
        )

    required = lifecycle.required_notice_days(version, product)
    if notice_days < required:
        raise ApiError(
            "ERR_NOTICE_PERIOD_TOO_SHORT",
            "This version requires at least %d days of notice." % required,
        )

    if lifecycle.announced_count(product["id"], version["id"]) >= (
        MAX_CONCURRENT_DEPRECATIONS
    ):
        raise ApiError(
            "ERR_DEPRECATION_WINDOW_FULL",
            "This product already carries %d announced deprecations."
            % MAX_CONCURRENT_DEPRECATIONS,
        )

    if version["breaking_change"] and not version["migration_guide_url"]:
        raise ApiError(
            "ERR_MIGRATION_GUIDE_MISSING",
            "A breaking version requires a published migration guide.",
        )

    now = store.now()
    sunset_at = now + timedelta(days=notice_days)
    version["required_notice_days"] = required
    version["deprecation_announced_at"] = now
    version["sunset_at"] = sunset_at
    version["notice_days_at_announcement"] = whole_days_between(now, sunset_at)
    version["lifecycle_state"] = "DEPRECATION_ANNOUNCED"
    store.touch(version)
    return object_response(api_version_out(version))
