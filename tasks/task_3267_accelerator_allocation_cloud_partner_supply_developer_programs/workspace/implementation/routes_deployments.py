"""Hardware deployments: registration, export gating, activation and termination."""

import calc
import constants as K
from auth import require_self, roles
from error import (
    CatalogError,
    ERR_EXPORT_LICENSE_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_GROUP_UNRESOLVED,
    ERR_NDA_NOT_BOUND,
    ERR_NO_COVERING_SUBSCRIPTION,
    ERR_PARTNER_NOT_FOUND,
    ERR_QUALIFICATION_NOT_MET,
)
from envelope import created, ok, page
from rules import (
    classification_for,
    check_export_gate,
    resource_or_404,
)
from services import (
    append_audit,
    bound_stack_ids_for,
    check_separation_of_duties,
    derive_available,
    move_entitlement_ledger,
    recompute_bound_deployment_count,
    recompute_service_ready,
    refresh_density,
    released_entitlement_for,
    serialize,
)
from store import DB
from util import by_created, optional, paginate, require

GROUP = "deployments"


def _resolve_manifest(product, manifest):
    """Every manifest entry's licence group must resolve on the SKU (PRD 3.7)."""
    resolved = []
    for entry in manifest or []:
        if not isinstance(entry, dict):
            raise CatalogError(ERR_INVALID_REQUEST, "Each stack entry must be an object.")
        license_id = entry.get("license_id")
        license_row = DB.stack_licenses.get(license_id)
        if license_row is None:
            raise CatalogError(ERR_LICENSE_GROUP_UNRESOLVED, "The stack license does not exist.")
        if license_row.get("product_sku_id") != product["id"]:
            raise CatalogError(ERR_LICENSE_GROUP_UNRESOLVED)
        resolved.append({
            "license_id": license_row["id"],
            "entitlement_units": entry.get("entitlement_units", license_row.get("entitlement_units")),
        })
    return resolved


def _operating_partner(body):
    """Resolve the partner operating a newly registered deployment.

    ``partner_id`` is a declared input field on ``HardwareDeployment`` (the
    partner operating the deployment); the activation qualification gate, the
    confidentiality gate and the suspension/termination cascades all read it.
    """
    partner_id = optional(body, "partner_id")
    if partner_id is None or partner_id == "":
        return None
    return DB.partners.get(partner_id)


def _deployment_partner(deployment):
    """The partner operating ``deployment``."""
    return DB.partners.get(deployment.get("partner_id"))


def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    product = resource_or_404("products", require(body, "product_sku_id"), "accelerator product")
    destination = require(body, "destination_country_code")
    if destination not in K.DESTINATION_COUNTRIES:
        raise CatalogError(ERR_INVALID_REQUEST, "destination_country_code is not permitted.")

    manifest = _resolve_manifest(product, optional(body, "stack_manifest", []))
    # Priority 6 also guards registration: the classification is resolved here
    # and the prohibited / unlicensed destinations are refused up front, before
    # any body FK is resolved.
    classification = check_export_gate(product, destination)

    # Priority 4: the body-declared partner reference resolves to a PartnerAccount.
    partner = _operating_partner(body)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "The operating partner does not exist.")

    deployment = DB.mint({
        "product_sku_id": product["id"],
        "partner_id": partner["id"],
        "destination_country_code": destination,
        "export_classification": classification,
        "stack_manifest": manifest,
        "activation_state": "PENDING",
        "bound_stack_ids": [],
        "service_ready": False,
        "termination_effect_units": 0,
        "expected_product_version": optional(body, "expected_product_version"),
        "activation_actor_user_id": None,
    })
    DB.deployments[deployment["id"]] = deployment
    return created(serialize(deployment))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.deployments.values()))
    for field in ("product_sku_id", "partner_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read(caller, deployment_id):
    return ok(serialize(resource_or_404("deployments", deployment_id, "hardware deployment")))


def _activate(caller, deployment_id):
    deployment = resource_or_404("deployments", deployment_id, "hardware deployment")
    if deployment.get("activation_state") != "PENDING":
        raise CatalogError(ERR_INVALID_STATE, "Only a PENDING deployment may be activated.")
    product = DB.products.get(deployment.get("product_sku_id"))
    if product is None:
        raise CatalogError(ERR_RESOURCE_NOT_FOUND, "The parent product does not exist.")
    # Priority 6 sits above the qualification gate, so the export classification
    # is resolved (and can refuse) before the operating partner is considered.
    destination = deployment.get("destination_country_code")
    classification = check_export_gate(product, destination)
    deployment["export_classification"] = classification

    partner = _deployment_partner(deployment)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)
    if int(product.get("allocated_units", 0) or 0) <= 0:
        raise CatalogError(ERR_INVALID_STATE, "The parent product has no allocated units.")

    bound = sorted(set(bound_stack_ids_for(deployment)))

    deployment["activation_state"] = "ACTIVATED"
    deployment["bound_stack_ids"] = bound
    deployment["activation_actor_user_id"] = caller.user_id
    DB.touch(deployment)

    # The computed variant of export_density_band runs on activation, and the
    # first activation on a promoted SKU creates the evaluation ring fence
    # (evaluation_ring_fence / PRD 3.1, PRD 3.8).
    if not product.get("_ever_activated"):
        product["reserved_evaluation_units"] = calc.ring_fence_for_ratio(
            int(product.get("supply_ceiling_units", 0))
        )
        product["_ever_activated"] = True
    refresh_density(product, declared=False)
    derive_available(product)
    DB.touch(product)

    append_audit(partner["id"], "DEPLOYMENT_ACTIVATED", "HardwareDeployment", deployment["id"], caller)
    _activation_cascade(deployment)
    recompute_bound_deployment_count()
    return ok(serialize(deployment))


def _activation_cascade(deployment):
    """depth-1 grants fulfilled, depth-2 acks fulfilled, depth-3 provisioning."""
    for license_id in deployment.get("bound_stack_ids", []) or []:
        for grant in DB.grants.values():
            if grant.get("stack_license_id") != license_id:
                continue
            if grant.get("grant_status") != "OPEN":
                continue
            if grant.get("partner_id") != deployment.get("partner_id"):
                continue
            grant["grant_status"] = "FULFILLED"
            DB.touch(grant)
            ack = DB.acks.get(grant.get("confidentiality_ack_id"))
            if ack is not None:
                ack["ack_status"] = "FULFILLED"
                DB.touch(ack)
            membership = DB.memberships.get(grant.get("membership_id"))
            if membership is not None:
                from calc import developer_tier_provision
                kits, incidents = developer_tier_provision(DB, membership, DB.partners.get(membership.get("partner_id")))
                membership["preview_kit_units"] = kits
                membership["support_incidents_included"] = incidents
                DB.touch(membership)


def _terminate(caller, deployment_id):
    deployment = resource_or_404("deployments", deployment_id, "hardware deployment")
    if deployment.get("activation_state") != "ACTIVATED":
        raise CatalogError(ERR_INVALID_STATE, "Only an ACTIVATED deployment may be terminated.")

    product = DB.products.get(deployment.get("product_sku_id"))
    partner = _deployment_partner(deployment)
    if product is None or partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)

    # Priority 6: exit licensing is evaluated before the actor comparison.
    check_export_gate(product, deployment.get("destination_country_code"))

    # Priority 19: a deployment with no covering subscription cannot terminate.
    # Any subscription bound to the deployment counts as covering; one already
    # RECLAIMED or EXPIRED simply contributes nothing to the release, and only
    # an ACTIVE or SUSPENDED row moves at depth 1 (PRD 3.7).
    bound_subs = [
        sub for sub in DB.subscriptions.values()
        if sub.get("deployment_id") == deployment["id"]
    ]
    if not bound_subs:
        raise CatalogError(ERR_NO_COVERING_SUBSCRIPTION)
    covering = [sub for sub in bound_subs if sub.get("status") in ("ACTIVE", "SUSPENDED")]

    # Priority 8: separation of duties, ordered below the rule above.
    check_separation_of_duties(deployment, caller)

    released = released_entitlement_for(deployment)
    deployment["activation_state"] = "TERMINATED"
    deployment["service_ready"] = False
    DB.touch(deployment)

    # depth-1
    for sub in covering:
        sub["status"] = "RECLAIMED"
        _finalise_settled_fee(sub)
        DB.touch(sub)

    # depth-2
    move_entitlement_ledger(partner, -released)

    # depth-3
    effect = min(released, int(product.get("allocated_units", 0) or 0))
    deployment["termination_effect_units"] = effect
    product["allocated_units"] = max(0, int(product.get("allocated_units", 0) or 0) - effect)
    refresh_density(product, declared=False)
    derive_available(product)
    DB.touch(product)
    recompute_bound_deployment_count()
    return ok(serialize(deployment))


def _finalise_settled_fee(sub):
    billable, settled = calc.subscription_fee_final(sub)
    sub["settled_fee_cents"] = settled
    return billable


def _reinstate(caller, deployment_id):
    deployment = resource_or_404("deployments", deployment_id, "hardware deployment")
    if deployment.get("activation_state") != "TERMINATED":
        raise CatalogError(ERR_INVALID_STATE, "Only a TERMINATED deployment may be reinstated.")
    for sub in DB.subscriptions.values():
        if sub.get("deployment_id") != deployment["id"]:
            continue
        if sub.get("status") == "ACTIVE":
            raise CatalogError(ERR_INVALID_STATE, "An ACTIVE subscription blocks reinstatement.")
    deployment["activation_state"] = "PENDING"
    DB.touch(deployment)
    return ok(serialize(deployment))


def _handover(caller, deployment_id):
    from flask import request
    body = request.raw_payload if isinstance(request.raw_payload, dict) else {}
    deployment = resource_or_404("deployments", deployment_id, "hardware deployment")
    require(body, "handover_reason")
    deployment["activation_actor_user_id"] = caller.user_id
    DB.touch(deployment)
    append_audit(deployment.get("partner_id"), "DEPLOYMENT_HANDOVER", "HardwareDeployment", deployment["id"], caller)
    return ok(serialize(deployment))


ROUTES = [
    ("POST", "/accelerators/deployments", _create, ("SupportAccountManager",)),
    ("GET", "/accelerators/deployments", _list, ("SupportAccountManager",)),
    ("GET", "/accelerators/deployments/<deployment_id>", _read, ("SupportAccountManager",)),
    ("POST", "/accelerators/deployments/<deployment_id>/activate", _activate, ("SupportAccountManager",)),
    ("POST", "/accelerators/deployments/<deployment_id>/terminate", _terminate, ("SupportAccountManager",)),
    ("POST", "/accelerators/deployments/<deployment_id>/reinstate", _reinstate, ("SupportAccountManager",)),
    ("POST", "/accelerators/deployments/<deployment_id>/handover", _handover, ("SupportAccountManager",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])