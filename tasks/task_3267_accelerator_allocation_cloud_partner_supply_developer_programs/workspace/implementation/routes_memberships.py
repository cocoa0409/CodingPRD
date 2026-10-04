"""Developer program memberships, confidentiality acknowledgements and preview grants."""

import constants as K
from auth import roles
from error import (
    CatalogError,
    ERR_INVALID_STATE,
    ERR_NDA_NOT_BOUND,
    ERR_NDA_WINDOW_OVERLAP,
    ERR_PARTNER_NOT_FOUND,
    ERR_PREVIEW_GRANT_WINDOW_OVERLAP,
)
from envelope import created, ok, page
from calc import advance_tier, developer_tier_provision
from rules import resolve, resource_or_404
from services import serialize
from store import DB
from util import by_created, optional, paginate, parse_utc, require, require_enum

GROUP = "memberships"


def _caller_partner(caller):
    partner = resolve("partners", caller.user_id)
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND, "X-User-ID does not name a partner account.")
    return partner


def _membership_view(membership):
    return serialize(membership)


# -------------------------------------------------------------- membership --
def _create(caller):
    from flask import request
    body = request.raw_payload or {}
    partner = _caller_partner(caller)
    if partner.get("status") != "ACTIVE":
        raise CatalogError(ERR_INVALID_STATE, "The partner is not ACTIVE.")
    membership = DB.mint({
        "partner_id": partner["id"],
        "requested_tier": require_enum(require(body, "requested_tier"), K.TIER_ORDER, "requested_tier"),
        "stored_tier": "COMMUNITY",
        "preview_kit_units": 0,
        "support_incidents_included": 0,
        "evaluation_deadline_at": None,
        "status": "REQUESTED",
    })
    DB.memberships[membership["id"]] = membership
    return created(_membership_view(membership))


def _list(caller):
    from flask import request
    rows = by_created(list(DB.memberships.values()))
    partner_id = request.args.get("partner_id")
    if partner_id:
        rows = [row for row in rows if row.get("partner_id") == partner_id]
    window, meta = paginate([_membership_view(row) for row in rows], request.args)
    return page(window, meta)


def _list_enriched(caller):
    """GET /memberships: memberships together with their grants and acks."""
    from flask import request
    rows = by_created(list(DB.memberships.values()))
    partner_id = request.args.get("partner_id")
    if partner_id:
        rows = [row for row in rows if row.get("partner_id") == partner_id]
    payload = []
    for membership in rows:
        view = _membership_view(membership)
        view["preview_grants"] = [
            serialize(grant) for grant in by_created(list(DB.grants.values()))
            if grant.get("membership_id") == membership["id"]
        ]
        view["confidentiality_acks"] = [
            serialize(ack) for ack in by_created(list(DB.acks.values()))
            if ack.get("membership_id") == membership["id"]
        ]
        payload.append(view)
    window, meta = paginate(payload, request.args)
    return page(window, meta)


def _read(caller, membership_id):
    return ok(_membership_view(resource_or_404("memberships", membership_id, "membership")))


def _provision(membership):
    partner = DB.partners.get(membership.get("partner_id"))
    kits, incidents = developer_tier_provision(DB, membership, partner)
    membership["preview_kit_units"] = kits
    membership["support_incidents_included"] = incidents


def _evaluate(caller, membership_id):
    membership = resource_or_404("memberships", membership_id, "membership")
    if membership.get("status") != "REQUESTED":
        raise CatalogError(ERR_INVALID_STATE, "Only a REQUESTED membership may be evaluated.")
    partner = DB.partners.get(membership.get("partner_id"))
    if partner is None:
        raise CatalogError(ERR_PARTNER_NOT_FOUND)
    if partner.get("qualification_status") != "QUALIFIED":
        from error import ERR_QUALIFICATION_NOT_MET
        raise CatalogError(ERR_QUALIFICATION_NOT_MET)
    accepted = [
        row for row in DB.evidences.values()
        if row.get("partner_id") == partner["id"] and row.get("evidence_pack_status") == "ACCEPTED"
    ]
    if not accepted:
        from error import ERR_QUALIFICATION_NOT_MET
        raise CatalogError(ERR_QUALIFICATION_NOT_MET, "No accepted evidence pack exists.")

    membership["status"] = "UNDER_EVALUATION"
    membership["evaluation_deadline_at"] = _plus_days(K.MEMBERSHIP_GRACE_DAYS)
    _provision(membership)
    DB.touch(membership)
    return ok(_membership_view(membership))


def _plus_days(days):
    from datetime import timedelta
    from util import format_utc
    return format_utc(DB.clock + timedelta(days=days))


def _renew(caller, membership_id):
    membership = resource_or_404("memberships", membership_id, "membership")
    status = membership.get("status")
    if status not in ("UNDER_EVALUATION", "LAPSED"):
        raise CatalogError(ERR_INVALID_STATE, "The membership cannot be renewed from %s." % status)
    deadline = membership.get("evaluation_deadline_at")
    if deadline is None or DB.clock < parse_utc(deadline):
        raise CatalogError(ERR_INVALID_STATE, "The evaluation window has not elapsed.")

    if status == "LAPSED":
        membership["status"] = "UNDER_EVALUATION"
        if deadline is None:
            membership["evaluation_deadline_at"] = _plus_days(K.MEMBERSHIP_GRACE_DAYS)
        _provision(membership)
        DB.touch(membership)
        return ok(_membership_view(membership))

    partner = DB.partners.get(membership.get("partner_id"))
    accepted = [
        row for row in DB.evidences.values()
        if row.get("partner_id") == membership.get("partner_id")
        and row.get("evidence_pack_status") == "ACCEPTED"
    ]
    if not accepted:
        from error import ERR_QUALIFICATION_NOT_MET
        raise CatalogError(ERR_QUALIFICATION_NOT_MET, "No accepted evidence pack exists.")

    membership["stored_tier"] = advance_tier(
        membership.get("stored_tier", "COMMUNITY"), membership.get("requested_tier", "COMMUNITY")
    )
    membership["status"] = "ACTIVE"
    _provision(membership)
    DB.touch(membership)
    return ok(_membership_view(membership))


def _lapse(caller, membership_id):
    membership = resource_or_404("memberships", membership_id, "membership")
    if membership.get("status") != "ACTIVE":
        raise CatalogError(ERR_INVALID_STATE, "Only an ACTIVE membership may lapse.")
    membership["status"] = "LAPSED"
    DB.touch(membership)
    for grant in DB.grants.values():
        if grant.get("membership_id") != membership["id"]:
            continue
        if grant.get("grant_status") == "OPEN":
            grant["grant_status"] = "REVOKED"
            DB.touch(grant)
    return ok(_membership_view(membership))


def _revoke(caller, membership_id):
    membership = resource_or_404("memberships", membership_id, "membership")
    _revoke_membership(membership)
    return ok(_membership_view(membership))


def _revoke_membership(membership):
    membership["status"] = "REVOKED"
    membership["preview_kit_units"] = 0
    DB.touch(membership)
    for grant in DB.grants.values():
        if grant.get("membership_id") != membership["id"]:
            continue
        if grant.get("grant_status") == "OPEN":
            grant["grant_status"] = "REVOKED"
            DB.touch(grant)


# ------------------------------------------------- confidentiality acks ----
def _month_index(value):
    dt = parse_utc(value)
    return dt.year * 12 + (dt.month - 1)


def _create_ack(caller):
    from flask import request
    body = request.raw_payload or {}
    membership = resource_or_404("memberships", require(body, "membership_id"), "membership")
    stack = resource_or_404("stack_licenses", require(body, "stack_license_id"), "software stack license")
    acknowledged_at = require(body, "acknowledged_at")

    # Open month windows on the same stack license: an acknowledgement covers its
    # own month and a one-month grace tail, so a new window in the immediately
    # following month still collides while one two months later clears the tail
    # (PRD 3.6; design seed confidentiality_ack_open_month_windows_with_grace_tail).
    new_start = _month_index(acknowledged_at)
    for ack in DB.acks.values():
        if ack.get("stack_license_id") != stack["id"]:
            continue
        existing_start = _month_index(ack.get("acknowledged_at"))
        if new_start <= existing_start + 1:
            raise CatalogError(ERR_NDA_WINDOW_OVERLAP)

    ack_row = DB.mint({
        "partner_id": membership.get("partner_id"),
        "membership_id": membership["id"],
        "stack_license_id": stack["id"],
        "acknowledged_at": acknowledged_at,
        "ack_status": "BOUND",
    })
    DB.acks[ack_row["id"]] = ack_row
    return created(serialize(ack_row))


def _list_acks(caller):
    from flask import request
    rows = by_created(list(DB.acks.values()))
    for field in ("partner_id", "membership_id", "stack_license_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_ack(caller, ack_id):
    return ok(serialize(resource_or_404("acks", ack_id, "confidentiality acknowledgement")))


# ----------------------------------------------------------- preview grants --
def _create_grant(caller):
    from flask import request
    body = request.raw_payload or {}
    stack = resource_or_404("stack_licenses", require(body, "stack_license_id"), "software stack license")
    device_serial = require(body, "device_serial")
    boundary = require(body, "commitment_boundary_at")
    expires = require(body, "commitment_expires_at")
    ack_id = require(body, "confidentiality_ack_id")
    ack = DB.acks.get(ack_id)
    if ack is None or ack.get("ack_status") != "BOUND":
        raise CatalogError(ERR_NDA_NOT_BOUND)

    partner_id = ack.get("partner_id")

    # Closed day windows with a 30-day buffer on the existing grant's end.
    from datetime import timedelta

    new_start = parse_utc(boundary)
    new_end = parse_utc(expires)
    for grant in DB.grants.values():
        if grant.get("partner_id") != partner_id:
            continue
        if grant.get("stack_license_id") != stack["id"]:
            continue
        existing_start = parse_utc(grant.get("commitment_boundary_at"))
        existing_end = parse_utc(grant.get("commitment_expires_at"))
        buffered_end = existing_end + timedelta(days=K.PREVIEW_GRANT_BUFFER_DAYS)
        if new_start <= buffered_end and new_end >= existing_start:
            raise CatalogError(ERR_PREVIEW_GRANT_WINDOW_OVERLAP)

    grant = DB.mint({
        "membership_id": ack.get("membership_id"),
        "partner_id": partner_id,
        "stack_license_id": stack["id"],
        "device_serial": device_serial,
        "commitment_boundary_at": boundary,
        "commitment_expires_at": expires,
        "confidentiality_ack_id": ack["id"],
        "grant_status": "OPEN",
    })
    DB.grants[grant["id"]] = grant
    return created(serialize(grant))


def _list_grants(caller):
    from flask import request
    rows = by_created(list(DB.grants.values()))
    for field in ("membership_id", "partner_id", "stack_license_id", "confidentiality_ack_id"):
        value = request.args.get(field)
        if value:
            rows = [row for row in rows if row.get(field) == value]
    window, meta = paginate([serialize(row) for row in rows], request.args)
    return page(window, meta)


def _read_grant(caller, grant_id):
    return ok(serialize(resource_or_404("grants", grant_id, "preview software grant")))


def _revoke_grant(caller, grant_id):
    grant = resource_or_404("grants", grant_id, "preview software grant")
    if grant.get("grant_status") != "OPEN":
        raise CatalogError(ERR_INVALID_STATE, "Only an OPEN grant may be revoked.")
    grant["grant_status"] = "REVOKED"
    DB.touch(grant)
    membership = DB.memberships.get(grant.get("membership_id"))
    if membership is not None:
        _revoke_membership(membership)
    return ok(serialize(grant))


ROUTES = [
    ("POST", "/accelerators/developer-memberships", _create, ("PartnerOps",)),
    ("GET", "/accelerators/developer-memberships", _list, ("PartnerProgramManager",)),
    ("GET", "/accelerators/memberships", _list_enriched, ("PartnerProgramManager",)),
    ("GET", "/accelerators/developer-memberships/<membership_id>", _read, ("PartnerProgramManager",)),
    ("POST", "/accelerators/developer-memberships/<membership_id>/evaluate", _evaluate, ("PartnerProgramManager",)),
    ("POST", "/accelerators/developer-memberships/<membership_id>/renew", _renew, ("PartnerProgramManager",)),
    ("POST", "/accelerators/developer-memberships/<membership_id>/lapse", _lapse, ("PartnerProgramManager",)),
    ("POST", "/accelerators/developer-memberships/<membership_id>/revoke", _revoke, ("SupplyComplianceOfficer",)),
    ("POST", "/accelerators/confidentiality-acks", _create_ack, ("SupplyComplianceOfficer",)),
    ("GET", "/accelerators/confidentiality-acks", _list_acks, ("SupplyComplianceOfficer",)),
    ("GET", "/accelerators/confidentiality-acks/<ack_id>", _read_ack, ("SupplyComplianceOfficer",)),
    ("POST", "/accelerators/preview-grants", _create_grant, ("PartnerProgramManager",)),
    ("GET", "/accelerators/preview-grants", _list_grants, ("PartnerProgramManager",)),
    ("GET", "/accelerators/preview-grants/<grant_id>", _read_grant, ("PartnerProgramManager",)),
    ("POST", "/accelerators/preview-grants/<grant_id>/revoke", _revoke_grant, ("SupplyComplianceOfficer",)),
]


def register(app):
    for method, path, handler, allowed in ROUTES:
        endpoint = "%s_%s" % (GROUP, path.replace("/", "_").replace("<", "").replace(">", ""))
        app.add_url_rule(path, endpoint + method, roles(*allowed)(handler), methods=[method])