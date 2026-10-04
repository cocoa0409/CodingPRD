"""Enterprise support subscriptions and the entitlement-bearing activation path."""

import calc
import constants as K
from auth import roles
from error import (
    CatalogError,
    ERR_ENTITLEMENT_UNITS_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_GROUP_DUPLICATE_MEMBER,
    ERR_LICENSE_GROUP_UNRESOLVED,
    ERR_NO_COVERING_SUBSCRIPTION,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
    ERR_STALE_SUBSCRIPTION_VERSION,
)
from envelope import created, ok, page
from rules import check_subscription_version, resource_or_404
from services import (
    append_audit,
    move_entitlement_ledger,
    recompute_service_ready,
    serialize,
)
from store import DB
from util import by_created, optional, paginate, require, require_enum

GROUP = "subscriptions"


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    deployment = resource_or_404("deployments", require(body, "deployment_id"), "hardware deployment")
    tier = require_enum(require(body, "support_tier"), K.SUPPORT_TIERS, "support_tier")
    seat_count = require(body, "seat_count", "int", positive=True)
    group = optional(body, "licence_group", []) or optional(body, "license_group", []) or []
    if not isinstance(group, list):
        raise CatalogError(ERR_INVALID_REQUEST, "licence_group must be an array.")

    if deployment.get("activation_state") == "TERMINATED":
        raise CatalogError(ERR_NO_COVERING_SUBSCRIPTION)

    # The licence group resolves against the deployment's SKU (priority 20),
    # and a repeated member is refused (ERR_LICENSE_GROUP_DUPLICATE_MEMBER).
    # Each member is the same {license_id, ...} shape the stack manifest uses,
    # so a bare id is accepted for tolerance.
    seen = set()
    resolved = []
    for member in group:
        if isinstance(member, dict):
            license_id = member.get("license_id")
        else:
            license_id = member
        if license_id in seen:
            raise CatalogError(ERR_LICENSE_GROUP_DUPLICATE_MEMBER)
        seen.add(license_id)
        license_row = DB.stack_licenses.get(license_id)
        if license_row is None:
            raise CatalogError(ERR_LICENSE_GROUP_UNRESOLVED)
        if license_row.get("product_sku_id") != deployment.get("product_sku_id"):
            raise CatalogError(ERR_LICENSE_GROUP_UNRESOLVED)
        resolved.append(license_row["id"])

    partner = DB.partners.get(deployment.get("partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)

    subscription = DB.mint({
        "partner_id": partner["id"],
        "deployment_id": deployment["id"],
        "stack_license_id": resolved[0] if resolved else None,
        "licence_group": resolved,
        "bound_stack_ids": list(resolved),
        "support_tier": tier,
        "seat_count": seat_count,
        "annual_fee_cents": 0,
        "support_credit_units": 0,
        "billed_fee_cents": 0,
        "settled_fee_cents": 0,
        "status": "DRAFT",
        "trial_flag": bool(optional(body, "trial_flag", False)),
        "activated_at": None,
    })
    annual, _billed = calc.subscription_fee_provisional(subscription)
    subscription["annual_fee_cents"] = annual
    DB.subscriptions[subscription["id"]] = subscription
    return created(serialize(subscription))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.subscriptions.values()))
    for field in ("partner_id", "deployment_id", "status", "stack_license_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, subscription_id):
    return ok(serialize(resource_or_404("subscriptions", subscription_id, "subscription")))


def _bound_entitlement(subscription):
    """The bound stack's entitlement units (first resolvable member)."""
    if subscription.get("stack_license_id"):
        license_row = DB.stack_licenses.get(subscription["stack_license_id"])
        if license_row is not None:
            return int(license_row.get("entitlement_units", 0))
    for license_id in subscription.get("bound_stack_ids", []) or []:
        license_row = DB.stack_licenses.get(license_id)
        if license_row is not None:
            return int(license_row.get("entitlement_units", 0))
    return 0


def _activate(caller, subscription_id):
    subscription = resource_or_404("subscriptions", subscription_id, "subscription")
    if subscription.get("status") != "DRAFT":
        raise CatalogError(ERR_INVALID_STATE, "Only a DRAFT subscription may be activated.")
    deployment = DB.deployments.get(subscription.get("deployment_id"))
    if deployment is None:
        raise CatalogError(ERR_NO_COVERING_SUBSCRIPTION)
    if deployment.get("activation_state") != "ACTIVATED":
        raise CatalogError(ERR_INVALID_STATE, "The covering deployment is not ACTIVATED.")

    # Every bound stack must be RELEASED.
    for license_id in subscription.get("bound_stack_ids", []) or []:
        license_row = DB.stack_licenses.get(license_id)
        if license_row is None or license_row.get("license_state") != "RELEASED":
            raise CatalogError(ERR_INVALID_STATE, "A bound stack license is not RELEASED.")

    if int(subscription.get("seat_count", 0)) <= 0 or not subscription.get("trial_flag"):
        raise CatalogError(ERR_INVALID_STATE, "seat_count must be positive and trial_flag true.")

    partner = DB.partners.get(subscription.get("partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)

    entitlement = _bound_entitlement(subscription)
    if int(partner.get("entitlement_units_held", 0) or 0) + entitlement > K.ENTITLEMENT_CEILING_UNITS:
        raise CatalogError(ERR_ENTITLEMENT_UNITS_EXCEEDED)

    subscription["status"] = "ACTIVE"
    subscription["activated_at"] = DB.now_text()
    annual, billed = calc.subscription_fee_provisional(subscription)
    subscription["annual_fee_cents"] = annual
    subscription["billed_fee_cents"] = billed
    subscription["support_credit_units"] = calc.support_tier_credit(subscription["seat_count"])
    DB.touch(subscription)

    move_entitlement_ledger(partner, entitlement)
    DB.bump(partner)
    recompute_service_ready(deployment)
    append_audit(partner["id"], "SUBSCRIPTION_ACTIVATED", "EnterpriseSubscription", subscription["id"], caller)
    return ok(serialize(subscription))


def _reinstate(caller, subscription_id):
    subscription = resource_or_404("subscriptions", subscription_id, "subscription")
    if subscription.get("status") != "SUSPENDED":
        raise CatalogError(ERR_INVALID_STATE, "Only a SUSPENDED subscription may be reinstated.")
    partner = DB.partners.get(subscription.get("partner_id"))
    deployment = DB.deployments.get(subscription.get("deployment_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)
    if deployment is None or deployment.get("activation_state") != "ACTIVATED":
        raise CatalogError(ERR_INVALID_STATE, "The covering deployment is not ACTIVATED.")

    subscription["status"] = "ACTIVE"
    subscription["settlement_epoch_index"] = DB.current_epoch_index()
    DB.touch(subscription)
    recompute_service_ready(deployment)
    return ok(serialize(subscription))


def _reclaim(caller, subscription_id):
    subscription = resource_or_404("subscriptions", subscription_id, "subscription")
    if subscription.get("status") not in ("ACTIVE", "SUSPENDED"):
        raise CatalogError(ERR_INVALID_STATE, "Only an ACTIVE or SUSPENDED subscription may be reclaimed.")
    subscription["status"] = "RECLAIMED"
    _billable, settled = calc.subscription_fee_final(subscription)
    subscription["settled_fee_cents"] = settled
    DB.touch(subscription)
    # The entitlement ledger is deliberately untouched by reclaim (PRD 2.8).
    deployment = DB.deployments.get(subscription.get("deployment_id"))
    if deployment is not None:
        recompute_service_ready(deployment)
    return ok(serialize(subscription))


def _evaluate(caller, subscription_id):
    from flask import request
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    subscription = resource_or_404("subscriptions", subscription_id, "subscription")
    expected = body.get("expected_subscription_version")
    if expected is None:
        raise CatalogError(ERR_INVALID_REQUEST, "'expected_subscription_version' is required.")
    if int(expected) != int(subscription.get("version", 1)):
        raise CatalogError(ERR_STALE_SUBSCRIPTION_VERSION)
    subscription["support_credit_units"] = calc.support_tier_credit(subscription.get("seat_count", 0))
    DB.touch(subscription)
    return ok(serialize(subscription))


ROUTES = [
    ("POST", "/accelerators/subscriptions", _create, ("SupportAccountManager",)),
    ("GET", "/accelerators/subscriptions", _list, ("SupportAccountManager",)),
    ("GET", "/accelerators/subscriptions/<subscription_id>", _read, ("SupportAccountManager",)),
    ("POST", "/accelerators/subscriptions/<subscription_id>/activate", _activate, ("SupportAccountManager",)),
    ("POST", "/accelerators/subscriptions/<subscription_id>/reinstate", _reinstate, ("SupportAccountManager",)),
    ("POST", "/accelerators/subscriptions/<subscription_id>/reclaim", _reclaim, ("SupportAccountManager",)),
    ("POST", "/accelerators/subscriptions/<subscription_id>/evaluate", _evaluate, ("PlatformAdmin",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])