"""Partner accounts: registration, qualification pipeline and standing."""

import constants as K
from auth import require_self, roles
from error import (
    CatalogError,
    ERR_INVALID_STATE,
    ERR_QUALIFICATION_NOT_MET,
)
from envelope import created, ok, page
from calc import partner_priority_class
from rules import partner_or_404, require_open_epoch
from services import (
    append_audit,
    derive_available,
    move_entitlement_ledger,
    recompute_service_ready,
    serialize,
)
from store import DB
from util import by_created, optional, paginate, require, require_enum

GROUP = "partners"


def _view(partner):
    return serialize(partner)


# ------------------------------------------------------------ registration --
def _register(caller):
    from flask import request
    body = request.raw_payload or {}
    partner_type = require_enum(require(body, "partner_type"), K.PARTNER_TYPES, "partner_type")
    tier = optional(body, "export_restriction_tier", "LICENSE_EXCEPTION")
    partner = DB.mint({
        "legal_name": require(body, "legal_name"),
        "partner_type": partner_type,
        "destination_country": require(body, "destination_country"),
        "export_restriction_tier": require_enum(tier, K.EXPORT_RESTRICTION_TIERS, "export_restriction_tier"),
        "origin_epoch_index": int(optional(body, "origin_epoch_index", 0) or 0),
        "qualification_status": "APPLIED",
        "qualification_attempt_count": 0,
        "allocation_priority_class": "UNQUALIFIED",
        "entitlement_units_held": 0,
        "capacity_ledger_net": 0,
        "cancellation_forfeit_rate": 0.0,
        "committed_volume_units": 0,
        "lifecycle_floor_expires_at": None,
        "eligibility_deadline_at": None,
        "status": "ACTIVE",
        "total_deliveries": 0,
        "on_time_deliveries": 0,
    })
    DB.partners[partner["id"]] = partner
    return created(_view(partner))


def _read(caller, partner_id):
    partner = partner_or_404(partner_id)
    require_self(caller, partner["id"])
    return ok(_view(partner))


def _audit_entries(caller, partner_id):
    from flask import request
    partner = partner_or_404(partner_id)
    rows = [
        serialize(entry) for entry in by_created(list(DB.audits.values()))
        if entry.get("partner_id") == partner["id"]
    ]
    window, meta = paginate(rows, request.args)
    return page(window, meta)


# ------------------------------------------------------------- validation --
def _file_evidence(caller, partner_id):
    from flask import request
    partner = partner_or_404(partner_id)
    body = request.raw_payload or {}
    validation_minutes = require(body, "validation_minutes", "int")
    test_count = require(body, "test_count", "int")
    blueprint_id = require(body, "blueprint_id")

    # Priority 3/4: the path resource first, then the body reference.
    blueprint = DB.blueprints.get(blueprint_id)
    if blueprint is None:
        from error import ERR_BLUEPRINT_NOT_FOUND
        raise CatalogError(ERR_BLUEPRINT_NOT_FOUND)

    # Priority 5: APPLIED -> IN_VALIDATION is the only admission.
    if partner.get("status") != "ACTIVE":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not ACTIVE.")
    if partner.get("qualification_status") != "APPLIED":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not APPLIED.")

    evidence = DB.mint({
        "partner_id": partner["id"],
        "blueprint_id": blueprint["id"],
        "validation_minutes": validation_minutes,
        "test_count": test_count,
        "evidence_pack_status": "SUBMITTED",
        "era_index": int(blueprint.get("era_index", 1)),
    })
    DB.evidences[evidence["id"]] = evidence
    partner["qualification_status"] = "IN_VALIDATION"
    DB.touch(partner)
    return created(serialize(evidence))


def _qualify(caller, partner_id):
    partner = partner_or_404(partner_id)
    if partner.get("qualification_status") != "IN_VALIDATION":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not IN_VALIDATION.")
    require_open_epoch()
    accepted = [
        row for row in DB.evidences.values()
        if row.get("partner_id") == partner["id"] and row.get("evidence_pack_status") == "ACCEPTED"
    ]
    if not accepted:
        raise CatalogError(ERR_QUALIFICATION_NOT_MET, "No accepted evidence pack exists.")
    for evidence in accepted:
        blueprint = DB.blueprints.get(evidence.get("blueprint_id"))
        if blueprint is None or blueprint.get("blueprint_status") != "CERTIFIED":
            raise CatalogError(ERR_QUALIFICATION_NOT_MET, "The accepted blueprint is not CERTIFIED.")
    supported = K.PARTNER_TYPE_SUPPORTS_BLUEPRINT_TYPE.get(partner.get("partner_type"), set())
    for evidence in accepted:
        blueprint = DB.blueprints.get(evidence.get("blueprint_id"))
        if blueprint.get("blueprint_type") not in supported:
            raise CatalogError(
                ERR_QUALIFICATION_NOT_MET,
                "The partner type does not support blueprint type '%s'." % blueprint.get("blueprint_type"),
            )
    partner["qualification_status"] = "QUALIFIED"
    DB.touch(partner)
    append_audit(partner["id"], "PARTNER_QUALIFIED", "PartnerAccount", partner["id"], caller)
    return ok(_view(partner))


def _reject(caller, partner_id):
    partner = partner_or_404(partner_id)
    if partner.get("qualification_status") != "IN_VALIDATION":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not IN_VALIDATION.")
    # Blueprints for which this partner holds ACCEPTED evidence in the
    # blueprint's current era lose it with the round.
    losing = set()
    for evidence in DB.evidences.values():
        if evidence.get("partner_id") != partner["id"]:
            continue
        if evidence.get("evidence_pack_status") != "ACCEPTED":
            continue
        blueprint = DB.blueprints.get(evidence.get("blueprint_id"))
        if blueprint is None:
            continue
        if int(evidence.get("era_index", 1)) == int(blueprint.get("era_index", 1)):
            losing.add(blueprint["id"])

    partner["qualification_status"] = "APPLIED"
    partner["qualification_attempt_count"] = int(partner.get("qualification_attempt_count", 0)) + 1
    DB.touch(partner)

    # depth-1: every SUBMITTED pack for this partner becomes REJECTED.
    for evidence in DB.evidences.values():
        if evidence.get("partner_id") != partner["id"]:
            continue
        if evidence.get("evidence_pack_status") == "SUBMITTED":
            evidence["evidence_pack_status"] = "REJECTED"
            DB.touch(evidence)

    # depth-2: supersede the era on each blueprint that lost its accepted round.
    for blueprint_id in losing:
        blueprint = DB.blueprints[blueprint_id]
        blueprint["era_index"] = int(blueprint.get("era_index", 1)) + 1
        DB.touch(blueprint)

    append_audit(partner["id"], "PARTNER_REJECTED", "PartnerAccount", partner["id"], caller)
    return ok(_view(partner))


# --------------------------------------------------------------- standing --
def _suspend(caller, partner_id):
    partner = partner_or_404(partner_id)
    if partner.get("qualification_status") != "QUALIFIED":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not QUALIFIED.")
    if partner.get("status") != "ACTIVE":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not ACTIVE.")
    partner["qualification_status"] = "SUSPENDED"
    partner["status"] = "SUSPENDED"
    DB.touch(partner)

    # depth-1: ACTIVE subscriptions of this partner become SUSPENDED.
    touched_subscriptions = [
        sub for sub in DB.subscriptions.values()
        if sub.get("partner_id") == partner["id"] and sub.get("status") == "ACTIVE"
    ]
    for sub in touched_subscriptions:
        sub["status"] = "SUSPENDED"
        DB.touch(sub)

    # depth-2 / depth-3: readiness drops, and a ready deployment terminates.
    for sub in touched_subscriptions:
        deployment = DB.deployments.get(sub.get("deployment_id"))
        if deployment is None:
            continue
        ready = recompute_service_ready(deployment)
        if not ready and deployment.get("activation_state") == "ACTIVATED":
            _terminate_deployment(deployment, caller)
    return ok(_view(partner))


def _reinstate(caller, partner_id):
    partner = partner_or_404(partner_id)
    if partner.get("status") != "SUSPENDED":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not SUSPENDED.")
    partner["qualification_status"] = "QUALIFIED"
    partner["status"] = "ACTIVE"
    DB.touch(partner)
    # Subscriptions are deliberately not auto-reactivated; each is reinstated
    # individually via POST /subscriptions/{id}/reinstate (PRD 3.2).
    return ok(_view(partner))


def _terminate(caller, partner_id):
    partner = partner_or_404(partner_id)
    status = partner.get("qualification_status")
    if partner.get("status") == "TERMINATED":
        raise CatalogError(ERR_INVALID_STATE, "The partner is already TERMINATED.")
    if status == "QUALIFIED":
        for sub in DB.subscriptions.values():
            if sub.get("partner_id") != partner["id"]:
                continue
            if sub.get("status") == "ACTIVE":
                raise CatalogError(
                    ERR_INVALID_STATE,
                    "An ACTIVE subscription must be reclaimed or expired first.",
                )
    elif status == "SUSPENDED":
        if int(partner.get("qualification_attempt_count", 0)) < 1:
            raise CatalogError(ERR_INVALID_STATE, "A qualification attempt is required.")
    else:
        raise CatalogError(ERR_INVALID_STATE, "The partner cannot be terminated from %s." % status)
    partner["status"] = "TERMINATED"
    DB.touch(partner)
    return ok(_view(partner))


def _reapply(caller, partner_id):
    partner = partner_or_404(partner_id)
    if partner.get("status") != "TERMINATED":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not TERMINATED.")
    for hold in DB.holds.values():
        if hold.get("partner_id") == partner["id"] and hold.get("state") in ("REQUESTED", "COMMITTED"):
            raise CatalogError(ERR_INVALID_STATE, "An ACTIVE allocation hold blocks re-application.")
    partner["qualification_status"] = "APPLIED"
    partner["status"] = "ACTIVE"
    DB.touch(partner)
    return ok(_view(partner))


def _terminate_deployment(deployment, caller):
    """The termination cascade, shared by the suspend path (PRD 3.2).

    The suspension path releases entitlement and subtracts the allocation, but
    it deliberately does NOT reclaim the subscription: depth 1 already moved it
    to SUSPENDED and the bind relationship is preserved so that an individual
    reinstatement can restore it.
    """
    from services import released_entitlement_for, refresh_density

    released = released_entitlement_for(deployment)
    deployment["activation_state"] = "TERMINATED"
    deployment["service_ready"] = False
    DB.touch(deployment)
    partner = DB.partners.get(deployment.get("partner_id"))
    product = DB.products.get(deployment.get("product_sku_id"))
    if partner is not None:
        move_entitlement_ledger(partner, -released)
    if product is not None:
        effect = min(released, int(product.get("allocated_units", 0) or 0))
        deployment["termination_effect_units"] = effect
        product["allocated_units"] = max(0, int(product.get("allocated_units", 0)) - effect)
        refresh_density(product, declared=False)
        derive_available(product)
        DB.touch(product)
    return deployment


def _priority_class_body(caller, partner_id):
    partner = partner_or_404(partner_id)
    return ok({"allocation_priority_class": partner_priority_class(partner)})


ROUTES = [
    ("POST", "/accelerators/partners", _register, ("PartnerOps",)),
    ("GET", "/accelerators/partners/<partner_id>", _read, ("PartnerOps",)),
    ("GET", "/accelerators/partners/<partner_id>/audit-entries", _audit_entries, ("SupplyComplianceOfficer",)),
    ("POST", "/accelerators/partners/<partner_id>/validations", _file_evidence, ("PartnerProgramManager",)),
    ("POST", "/accelerators/partners/<partner_id>/qualify", _qualify, ("PartnerProgramManager",)),
    ("POST", "/accelerators/partners/<partner_id>/reject", _reject, ("PartnerProgramManager",)),
    ("POST", "/accelerators/partners/<partner_id>/suspend", _suspend, ("PartnerProgramManager",)),
    ("POST", "/accelerators/partners/<partner_id>/reinstate", _reinstate, ("PlatformAdmin",)),
    ("POST", "/accelerators/partners/<partner_id>/terminate", _terminate, ("PlatformAdmin",)),
    ("POST", "/accelerators/partners/<partner_id>/reapply", _reapply, ("PlatformAdmin",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])