"""The logical clock and the accredited-representative roster (PRD 2.4, 3.1)."""

from flask import Blueprint, g

import calc
from errors import ApiError
from envelope import list_response, object_response
from guard import (
    authorize, check_shape, filter_rows, invalid_transition, need_representative,
    page_of, run_checks,
)
from store import bump, db, new_row, now_date, now_instant, ordered, parse_date, parse_instant
from views import view, view_all

bp = Blueprint("registry", __name__, url_prefix="/cvso")

ALL_ROLES = ("SystemAdmin", "IntakeClerk", "CountyOfficer", "StateAuditor",
             "VeteranClient")
READ_ROSTER = ("SystemAdmin", "IntakeClerk", "CountyOfficer", "StateAuditor")
READ_CALENDAR = ("SystemAdmin", "CountyOfficer", "StateAuditor")

MIN_RENEWAL_CE_CREDITS = 12


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(("SystemAdmin",))
    body = check_shape({"required": ["current_utc"]})
    run_checks()
    db.clock = parse_instant(body["current_utc"])
    return object_response({"current_utc": now_instant()})


# --------------------------------------------------------------------------
# representatives
# --------------------------------------------------------------------------

def _new_representative(body):
    row = new_row()
    row["_kind"] = "representative"
    row["full_name"] = body["full_name"]
    row["accreditation_number"] = body["accreditation_number"]
    row["accreditation_type"] = body["accreditation_type"]
    row["accreditation_status"] = "PENDING"
    row["accreditation_expires_on"] = body["accreditation_expires_on"]
    row["ce_credits_earned"] = 0
    row["revocation_reason"] = None
    row["active_poa_count"] = 0
    row["caseload_weight"] = 0
    return row


def _duplicate_number(number, exclude_id=None):
    for row in db.representatives.values():
        if row["id"] == exclude_id:
            continue
        if row["accreditation_number"] == number:
            return True
    return False


@bp.post("/representatives")
def create_representative():
    authorize(("SystemAdmin",))
    body = check_shape({
        "required": ["full_name", "accreditation_number", "accreditation_type",
                     "accreditation_expires_on"],
    })

    def unique_number():
        if _duplicate_number(body["accreditation_number"]):
            raise ApiError("ERR_DUPLICATE_ACCREDITATION_NUMBER",
                           "accreditation_number is already held")

    run_checks([(70, unique_number)])
    row = _new_representative(body)
    db.representatives[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/representatives")
def list_representatives():
    authorize(READ_ROSTER)
    run_checks()
    rows = filter_rows(ordered(db.representatives.values()), {
        "accreditation_status": "accreditation_status",
        "accreditation_type": "accreditation_type",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/representatives/<row_id>")
def read_representative(row_id):
    authorize(READ_ROSTER)
    row = need_representative(row_id)
    run_checks()
    return object_response(view(row))


@bp.patch("/representatives/<row_id>")
def patch_representative(row_id):
    authorize(("SystemAdmin",))
    body = check_shape({
        "optional": ["full_name", "accreditation_number", "accreditation_type",
                     "accreditation_expires_on"],
    })
    row = need_representative(row_id)

    def unique_number():
        if "accreditation_number" in body \
                and _duplicate_number(body["accreditation_number"], row_id):
            raise ApiError("ERR_DUPLICATE_ACCREDITATION_NUMBER",
                           "accreditation_number is already held")

    run_checks([(70, unique_number)])
    for field in ("full_name", "accreditation_number", "accreditation_type",
                  "accreditation_expires_on"):
        if field in body:
            row[field] = body[field]
    bump(row)
    return object_response(view(row))


ACCREDITATION_FROM = {
    "ACTIVATE": ("PENDING",),
    "LAPSE": ("ACTIVE",),
    "RENEW": ("LAPSED",),
    "REVOKE": ("ACTIVE", "LAPSED"),
}


@bp.post("/representatives/<row_id>/accreditation")
def drive_accreditation(row_id):
    authorize(("SystemAdmin",))

    def extra(body):
        if body.get("action") == "RENEW":
            if body["ce_credits"] < MIN_RENEWAL_CE_CREDITS:
                raise ApiError("ERR_VALIDATION",
                               "ce_credits must be at least %d"
                               % (MIN_RENEWAL_CE_CREDITS,))
            if parse_date(body["accreditation_expires_on"]) <= now_date():
                raise ApiError(
                    "ERR_VALIDATION",
                    "accreditation_expires_on must fall strictly after the"
                    " logical-clock date")

    body = check_shape({
        "actions": ("ACTIVATE", "LAPSE", "RENEW", "REVOKE"),
        "optional": ["ce_credits", "accreditation_expires_on", "reason"],
        "action_required": {
            "RENEW": ("ce_credits", "accreditation_expires_on"),
            "REVOKE": ("reason",),
        },
        "extra": extra,
    })
    row = need_representative(row_id)
    action = body["action"]

    def from_state():
        if row["accreditation_status"] not in ACCREDITATION_FROM[action]:
            invalid_transition("%s is not available from %s"
                               % (action, row["accreditation_status"]))

    run_checks([(40, from_state)])

    if action == "ACTIVATE":
        row["accreditation_status"] = "ACTIVE"
        calc.refresh_caseload_no_bump(row)
        bump(row)
    elif action == "LAPSE":
        row["accreditation_status"] = "LAPSED"
        bump(row)
    elif action == "RENEW":
        row["accreditation_status"] = "ACTIVE"
        row["accreditation_expires_on"] = body["accreditation_expires_on"]
        row["ce_credits_earned"] = body["ce_credits"]
        bump(row)
    else:
        _revoke_accreditation(row, body["reason"])
    return object_response(view(row))


def _revoke_accreditation(rep, reason):
    """The five-hop revocation cascade of PRD 3.1."""
    # hop one -- the representative, plus the assignment fan-out
    rep["accreditation_status"] = "REVOKED"
    rep["revocation_reason"] = reason
    for veteran in db.veterans.values():
        if veteran.get("assigned_representative_id") == rep["id"]:
            veteran["assigned_representative_id"] = None
            bump(veteran)

    # hop two -- the active designations
    revoked_poa_ids = set()
    for poa in ordered(db.powers_of_attorney.values()):
        if poa["representative_id"] == rep["id"] and poa["status"] == "ACTIVE":
            poa["status"] = "REVOKED"
            poa["revoked_reason"] = "REPRESENTATIVE_ACCREDITATION_REVOKED"
            bump(poa)
            revoked_poa_ids.add(poa["id"])

    # hop three -- the claims those designations supported
    reverted_claims = []
    touched_preparers = set()
    for claim in ordered(db.claims.values()):
        if claim.get("poa_id") not in revoked_poa_ids:
            continue
        touched_preparers.add(claim.get("prepared_by_representative_id"))
        if claim["status"] in ("EVIDENCE_DEVELOPMENT", "PEER_REVIEW",
                               "READY_TO_FILE"):
            claim["status"] = "DRAFT"
            claim["poa_id"] = None
            claim["peer_reviewed_by_representative_id"] = None
            bump(claim)
            reverted_claims.append(claim)
        elif claim["status"] == "DRAFT":
            claim["poa_id"] = None
            bump(claim)

    # hop four -- the scheduled examinations of those claims
    released = {}
    reverted_ids = set(c["id"] for c in reverted_claims)
    for appointment in ordered(db.exam_appointments.values()):
        if appointment["claim_id"] in reverted_ids \
                and appointment["status"] == "SCHEDULED":
            appointment["status"] = "CANCELLED"
            appointment["cancellation_reason"] = "REPRESENTATION_CASCADE"
            bump(appointment)
            released[appointment["exam_site_id"]] = \
                released.get(appointment["exam_site_id"], 0) + 1

    # hop five -- the slot ledgers
    for site_id, count in released.items():
        site = db.exam_sites.get(site_id)
        if site is None:
            continue
        site["booked_slot_count"] = site["booked_slot_count"] - count
        bump(site)

    calc.refresh_caseload_no_bump(rep)
    bump(rep)
    for rep_id in touched_preparers:
        other = db.representatives.get(rep_id)
        if other is not None and other["id"] != rep["id"]:
            calc.refresh_caseload(other)


@bp.get("/representatives/<row_id>/outreach-events")
def read_representative_calendar(row_id):
    authorize(READ_CALENDAR)
    need_representative(row_id)
    run_checks()
    rows = [e for e in ordered(db.outreach_events.values())
            if e["assigned_representative_id"] == row_id]
    rows = filter_rows(rows, {"status": "status"})
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/representatives/<row_id>/caseload")
def read_representative_caseload(row_id):
    authorize(READ_CALENDAR)
    row = need_representative(row_id)
    run_checks()
    parts = calc.caseload_decomposition(row_id)
    eligible = (row["accreditation_status"] == "ACTIVE"
                and row["accreditation_type"] in calc.ASSIGNABLE_TYPES
                and parts["active_poa_count"] < calc.MAX_POA_PER_REPRESENTATIVE)
    return object_response({
        "representative_id": row_id,
        "active_poa_count": parts["active_poa_count"],
        "open_claim_count": parts["open_claim_count"],
        "planned_outreach_count": parts["planned_outreach_count"],
        "caseload_weight": parts["caseload_weight"],
        "assignment_eligible": eligible,
    })
