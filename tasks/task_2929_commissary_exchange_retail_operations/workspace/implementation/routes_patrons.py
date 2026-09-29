"""Patron enrolment, the eligibility record, the card axis and compliance
reviews (PRD 3.2, 3.7)."""

from flask import Blueprint

import constants as C
import lookups
import service_patron
import serialize
import validation as V
from db import db, new_record, sorted_records, touch
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("patrons", __name__)


@bp.post("/patrons")
def create_patron():
    V.authenticate(("ComplianceOfficer",))
    body = V.raw_body()
    full_name = V.want_string(body, "full_name", required=True, min_len=1, max_len=120)
    id_card_class = V.want_enum(body, "id_card_class", C.ID_CARD_CLASSES, required=True)
    sponsor_patron_id = V.want_string(body, "sponsor_patron_id", required=False)

    # Body references are resolved before cross-field consistency is judged.
    if sponsor_patron_id is not None:
        lookups.patron(sponsor_patron_id)

    if id_card_class == "DEPENDENT":
        if sponsor_patron_id is None:
            raise ApiError("ERR_SPONSOR_REQUIRED")
    elif sponsor_patron_id is not None:
        raise ApiError("ERR_SPONSOR_REQUIRED")

    patron = new_record()
    patron.update({
        "full_name": full_name,
        "id_card_class": id_card_class,
        "sponsor_patron_id": sponsor_patron_id,
        "card_status": "VALID",
        "suspension_reason": None,
        "resale_watch_status": "CLEAR",
        "resale_risk_score": 0,
        "recent_sales_risk_score": 0,
        "restricted_units_30d": 0,
        "flagged_sale_count_30d": 0,
        "manual_strike_count": 0,
    })
    db.patrons[patron["id"]] = patron
    return object_response(serialize.patron_out(patron), 201)


@bp.get("/patrons")
def list_patrons():
    V.authenticate(("ComplianceOfficer", "StoreCashier"))
    limit, offset = V.pagination()
    sponsor_patron_id = V.query_string("sponsor_patron_id")
    id_card_class = V.query_enum("id_card_class", C.ID_CARD_CLASSES)
    card_status = V.query_enum("card_status", C.CARD_STATUSES)
    resale_watch_status = V.query_enum("resale_watch_status", C.RESALE_WATCH_STATUSES)
    rows = sorted_records(db.patrons)
    if sponsor_patron_id is not None:
        rows = [r for r in rows if r["sponsor_patron_id"] == sponsor_patron_id]
    if id_card_class is not None:
        rows = [r for r in rows if r["id_card_class"] == id_card_class]
    if card_status is not None:
        rows = [r for r in rows if r["card_status"] == card_status]
    if resale_watch_status is not None:
        rows = [r for r in rows if r["resale_watch_status"] == resale_watch_status]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.patron_out(r) for r in page], limit, offset, total)


@bp.get("/patrons/<patron_id>")
def read_patron(patron_id):
    caller = V.authenticate(("ComplianceOfficer", "StoreCashier", "Patron"))
    if caller.role == "Patron" and caller.user_id != patron_id:
        raise ApiError("ERR_PATRON_SCOPE_VIOLATION")
    patron = lookups.patron(patron_id)
    return object_response(serialize.patron_out(patron), 200)


@bp.post("/patrons/<patron_id>/card-status")
def set_card_status(patron_id):
    V.authenticate(("ComplianceOfficer",))
    patron = lookups.patron(patron_id)
    body = V.raw_body()
    action = V.want_enum(body, "action", C.CARD_ACTIONS, required=True)
    V.want_string(body, "reason", required=False)

    if action == "SUSPEND":
        if patron["card_status"] != "VALID":
            raise ApiError("ERR_PATRON_CARD_NOT_VALID")
        patron["card_status"] = "SUSPENDED"
        patron["suspension_reason"] = "ADMIN_ACTION"
        touch(patron)
        service_patron.cascade_suspension(patron)
    elif action == "REINSTATE":
        if patron["card_status"] != "SUSPENDED":
            raise ApiError("ERR_PATRON_CARD_NOT_VALID")
        patron["card_status"] = "VALID"
        patron["suspension_reason"] = None
        touch(patron)
        service_patron.cascade_reinstatement(patron)
    else:  # REVOKE
        if patron["card_status"] != "SUSPENDED":
            raise ApiError("ERR_PATRON_CARD_NOT_VALID")
        patron["card_status"] = "REVOKED"
        # suspension_reason is left exactly as it stands.
        touch(patron)
        service_patron.cascade_revocation(patron)

    return object_response(serialize.patron_out(patron), 200)


@bp.post("/patrons/<patron_id>/compliance-review")
def compliance_review(patron_id):
    V.authenticate(("ComplianceOfficer",))
    patron = lookups.patron(patron_id)
    body = V.raw_body()
    decision = V.want_enum(body, "decision", C.COMPLIANCE_DECISIONS, required=True)

    if decision == "CONFIRM_STRIKE":
        if patron["card_status"] == "REVOKED":
            raise ApiError("ERR_PATRON_CARD_NOT_VALID")
        snapshot = service_patron.snapshot_state(patron)
        patron["manual_strike_count"] += 1
        service_patron.recompute_risk(patron, bump=False)
        if service_patron.state_changed(patron, snapshot):
            touch(patron)
        service_patron.flag_open_sales_of_patron(patron["id"])
    else:  # CLEAR_WATCH
        snapshot = service_patron.snapshot_state(patron)
        patron["manual_strike_count"] = 0
        service_patron.recompute_risk(patron, bump=False)
        if service_patron.state_changed(patron, snapshot):
            touch(patron)
        service_patron.clear_open_sales_of_patron(patron["id"])

    return object_response(serialize.patron_out(patron), 200)
