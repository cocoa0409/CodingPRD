"""Statutory authorizations for convenience-fee services (PRD section 3.2).
Windows are closed intervals; in_effect is computed from the logical clock."""
from flask import Blueprint, request

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_instant, as_int, as_str, body, req_field

bp = Blueprint("authorizations", __name__)


@bp.route("/portal/statutory-authorizations", methods=["POST"])
def create_authorization():
    caller({"AgencyAdmin"})
    data = body()
    service_id = as_str(req_field(data, "service_id"), "service_id")
    statute_citation = as_str(req_field(data, "statute_citation"), "statute_citation")
    disclosure = as_str(
        req_field(data, "disclosure_text_version"), "disclosure_text_version"
    )
    fee_cap = as_int(req_field(data, "fee_cap_cents"), "fee_cap_cents")
    eff_from, eff_from_raw = as_instant(req_field(data, "effective_from"), "effective_from")
    eff_to, eff_to_raw = as_instant(req_field(data, "effective_to"), "effective_to")
    # priority 3: body foreign key
    helpers.get_service(service_id)
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "service_id": service_id,
        "statute_citation": statute_citation,
        "disclosure_text_version": disclosure,
        "fee_cap_cents": fee_cap,
        "effective_from": eff_from,
        "effective_from_raw": eff_from_raw,
        "effective_to": eff_to,
        "effective_to_raw": eff_to_raw,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.authorizations[rec["id"]] = rec
    return envelope.obj(serialize.authorization(rec), 201)


@bp.route("/portal/statutory-authorizations/<rid>/approve", methods=["POST"])
def approve_authorization(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_authorization(rid)
    # priority 5: DRAFT only; parent service must exist and not be DEACTIVATED
    if rec["status"] != "DRAFT":
        invalid_state("Only a DRAFT authorization can be approved")
    svc = store.services.get(rec["service_id"])
    if svc is None or svc["status"] == "DEACTIVATED":
        invalid_state("The parent service does not exist or is DEACTIVATED")
    # priority 8: closed-window non-overlap among APPROVED authorizations of
    # the same service; effective_from == other.effective_to IS an overlap
    for other in store.authorizations.values():
        if (
            other["service_id"] == rec["service_id"]
            and other["id"] != rec["id"]
            and other["status"] == "APPROVED"
        ):
            if rec["effective_from"] <= other["effective_to"] and (
                other["effective_from"] <= rec["effective_to"]
            ):
                raise_err(
                    "ERR_AUTHORIZATION_WINDOW_OVERLAP",
                    409,
                    "Authorization window overlaps another APPROVED "
                    "authorization of the same service",
                )
    rec["status"] = "APPROVED"
    helpers.touch(rec)
    return envelope.obj(serialize.authorization(rec))


@bp.route("/portal/services/<rid>/authorizations", methods=["GET"])
def list_authorizations(rid):
    caller({"PlatformAdmin", "AgencyAdmin", "ComplianceAuditor"})
    helpers.get_service(rid)
    items = [a for a in store.authorizations.values() if a["service_id"] == rid]
    items.sort(key=lambda a: (a["created_at"], a["created_seq"]))
    return envelope.page([serialize.authorization(a) for a in items], request.args)
