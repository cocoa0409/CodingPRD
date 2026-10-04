"""Offer lifecycle: respond, suitability, clearance, EOD, appointment
(PRD 3.8, 3.9)."""
from flask import Blueprint

from auth import get_auth, require_applicant_owner, require_roles
from cascade import eval_offer, offer_not_selected_cascade
from envelope import success_list, success_object
from errors import fail, not_found
from serializers import appointment_out, clearance_out, offer_out, suitability_out
from store import DB, base_fields, now, touch
from validate import get_body, opt_query, opt_str, parse_pagination, req_dt, req_enum

bp = Blueprint("offers", __name__)

SUITABILITY_OUTCOMES = ["FAVORABLE", "UNFAVORABLE"]
CLEARANCE_OUTCOMES = ["FAVORABLE_INTERIM", "FAVORABLE_FINAL", "UNFAVORABLE"]


def get_offer_or_404(offer_id):
    row = DB.offers.get(offer_id)
    if row is None:
        not_found("offer")
    return row


def _favorable_suitability(offer):
    return any(
        r["offer_id"] == offer["id"] and r["outcome"] == "FAVORABLE"
        for r in DB.suitability.values()
    )


def _clearance_gate_satisfied(offer):
    """Sensitivity gate: NONE needs no record; SECRET accepts interim or
    final; TOP_SECRET insists on final."""
    app_row = DB.applications[offer["application_id"]]
    ann = DB.announcements[app_row["announcement_id"]]
    position = DB.positions[ann["position_id"]]
    level = position["sensitivity_level"]
    if level == "NONE":
        return True
    outcomes = {c["outcome"] for c in DB.clearances.values() if c["offer_id"] == offer["id"]}
    if level == "SECRET":
        return bool(outcomes & {"FAVORABLE_INTERIM", "FAVORABLE_FINAL"})
    return "FAVORABLE_FINAL" in outcomes


@bp.route("/hiring/offers", methods=["GET"])
def list_offers():
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    for o in DB.offers.values():
        eval_offer(o)
    limit, offset = parse_pagination()
    f_app = opt_query("application_id")
    f_entry = opt_query("certificate_entry_id")
    f_status = opt_query("status")
    items = list(DB.offers.values())
    if f_app is not None:
        items = [o for o in items if o["application_id"] == f_app]
    if f_entry is not None:
        items = [o for o in items if o["certificate_entry_id"] == f_entry]
    if f_status is not None:
        items = [o for o in items if o["status"] == f_status]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([offer_out(o) for o in page], limit, offset, total)


@bp.route("/hiring/offers/<offer_id>", methods=["GET"])
def read_offer(offer_id):
    user_id, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial", "Applicant"])
    row = get_offer_or_404(offer_id)
    if role == "Applicant":
        app_row = DB.applications[row["application_id"]]
        require_applicant_owner(user_id, app_row["applicant_id"])
    eval_offer(row)
    return success_object(offer_out(row))


@bp.route("/hiring/offers/<offer_id>/respond", methods=["POST"])
def respond_offer(offer_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant"])
    body = get_body()
    response = req_enum(body, "response", ["ACCEPT", "DECLINE"])
    row = get_offer_or_404(offer_id)
    app_row = DB.applications[row["application_id"]]
    require_applicant_owner(user_id, app_row["applicant_id"])
    # Temporal check runs BEFORE the state check on this operation (PRD 2.7).
    if row["status"] == "TENTATIVE" and now() >= row["response_due_at"]:
        row["status"] = "OFFER_EXPIRED"
        touch(row)
        offer_not_selected_cascade(row)
        fail("ERR_OFFER_RESPONSE_EXPIRED", "response deadline has been reached")
    if row["status"] != "TENTATIVE":
        fail("ERR_OFFER_NOT_ACTIONABLE", "offer is not TENTATIVE")
    row["responded_at"] = now()
    if response == "ACCEPT":
        row["status"] = "ACCEPTED"
        touch(row)
    else:
        row["status"] = "DECLINED"
        touch(row)
        offer_not_selected_cascade(row)
    return success_object(offer_out(row))


@bp.route("/hiring/offers/<offer_id>/suitability-reviews", methods=["POST"])
def record_suitability(offer_id):
    user_id, role = get_auth()
    require_roles(role, ["SuitabilityReviewer"])
    body = get_body()
    outcome = req_enum(body, "outcome", SUITABILITY_OUTCOMES)
    notes = opt_str(body, "notes")
    offer = get_offer_or_404(offer_id)
    eval_offer(offer)
    if offer["status"] != "ACCEPTED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "suitability review requires an ACCEPTED offer")
    for c in DB.clearances.values():
        if c["offer_id"] == offer["id"] and c["adjudicator_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "suitability reviewer must differ from the clearance adjudicator")
    if any(r["offer_id"] == offer["id"] for r in DB.suitability.values()):
        fail("ERR_REVIEW_ALREADY_RECORDED", "a suitability review is already recorded")
    row = base_fields()
    row.update({
        "offer_id": offer["id"], "reviewer_id": user_id,
        "outcome": outcome, "notes": notes, "recorded_at": now(),
    })
    DB.suitability[row["id"]] = row
    offer["suitability_reviewer_id"] = user_id
    if outcome == "UNFAVORABLE":
        offer["status"] = "RESCINDED"
        touch(offer)
        offer_not_selected_cascade(offer)
    else:
        touch(offer)
    return success_object(suitability_out(row), 201)


@bp.route("/hiring/offers/<offer_id>/suitability-reviews", methods=["GET"])
def list_suitability(offer_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial", "SuitabilityReviewer"])
    offer = get_offer_or_404(offer_id)
    limit, offset = parse_pagination()
    items = [r for r in DB.suitability.values() if r["offer_id"] == offer["id"]]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([suitability_out(r) for r in page], limit, offset, total)


@bp.route("/hiring/offers/<offer_id>/security-clearances", methods=["POST"])
def record_clearance(offer_id):
    user_id, role = get_auth()
    require_roles(role, ["SecurityAdjudicator"])
    body = get_body()
    outcome = req_enum(body, "outcome", CLEARANCE_OUTCOMES)
    offer = get_offer_or_404(offer_id)
    eval_offer(offer)
    if offer["status"] != "ACCEPTED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "clearance requires an ACCEPTED offer")
    if offer.get("suitability_reviewer_id") is not None \
            and offer["suitability_reviewer_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "clearance adjudicator must differ from the suitability reviewer")
    if not _favorable_suitability(offer):
        fail("ERR_SUITABILITY_NOT_FAVORABLE",
             "a FAVORABLE suitability review must precede clearance")
    if any(c["offer_id"] == offer["id"] for c in DB.clearances.values()):
        fail("ERR_REVIEW_ALREADY_RECORDED", "a security clearance is already recorded")
    app_row = DB.applications[offer["application_id"]]
    ann = DB.announcements[app_row["announcement_id"]]
    position = DB.positions[ann["position_id"]]
    row = base_fields()
    row.update({
        "offer_id": offer["id"], "adjudicator_id": user_id,
        "level_required": position["sensitivity_level"],
        "outcome": outcome, "recorded_at": now(),
    })
    DB.clearances[row["id"]] = row
    if outcome == "UNFAVORABLE":
        offer["status"] = "RESCINDED"
        touch(offer)
        offer_not_selected_cascade(offer)
    return success_object(clearance_out(row), 201)


@bp.route("/hiring/offers/<offer_id>/security-clearances", methods=["GET"])
def list_clearances(offer_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial", "SecurityAdjudicator"])
    offer = get_offer_or_404(offer_id)
    limit, offset = parse_pagination()
    items = [c for c in DB.clearances.values() if c["offer_id"] == offer["id"]]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([clearance_out(c) for c in page], limit, offset, total)


@bp.route("/hiring/offers/<offer_id>/schedule-eod", methods=["POST"])
def schedule_eod(offer_id):
    _, role = get_auth()
    require_roles(role, ["SelectingOfficial"])
    body = get_body()
    eod_date = req_dt(body, "eod_date")
    offer = get_offer_or_404(offer_id)
    eval_offer(offer)
    if offer["status"] != "ACCEPTED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "schedule-eod requires an ACCEPTED offer")
    if not _favorable_suitability(offer):
        fail("ERR_SUITABILITY_NOT_FAVORABLE", "no FAVORABLE suitability review on file")
    if not _clearance_gate_satisfied(offer):
        fail("ERR_CLEARANCE_INSUFFICIENT",
             "clearance outcome does not satisfy the position sensitivity")
    if eod_date.date() < now().date():
        fail("ERR_EOD_DATE_INVALID", "eod_date is earlier than the current date")
    offer["eod_date"] = eod_date
    offer["status"] = "EOD_SCHEDULED"
    touch(offer)
    return success_object(offer_out(offer))


@bp.route("/hiring/offers/<offer_id>/confirm-eod", methods=["POST"])
def confirm_eod(offer_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    get_body()
    offer = get_offer_or_404(offer_id)
    eval_offer(offer)
    if offer["status"] != "EOD_SCHEDULED":
        fail("ERR_OFFER_NOT_ACTIONABLE", "confirm-eod requires an EOD_SCHEDULED offer")
    if not _favorable_suitability(offer):
        fail("ERR_SUITABILITY_NOT_FAVORABLE", "no FAVORABLE suitability review on file")
    if not _clearance_gate_satisfied(offer):
        fail("ERR_CLEARANCE_INSUFFICIENT",
             "clearance outcome does not satisfy the position sensitivity")
    if now() < offer["eod_date"]:
        fail("ERR_EOD_DATE_INVALID", "logical clock has not reached eod_date")
    offer["status"] = "ENTERED_ON_DUTY"
    touch(offer)
    app_row = DB.applications[offer["application_id"]]
    if app_row["status"] == "SELECTED":
        app_row["status"] = "HIRED"
        touch(app_row)
    ann = DB.announcements[app_row["announcement_id"]]
    if ann["hiring_authority"] == "COMPETITIVE":
        appt_type = "COMPETITIVE"
    elif ann["hiring_authority"] == "DIRECT_HIRE":
        appt_type = "DIRECT_HIRE"
    else:
        appt_type = "SPECIAL_AUTHORITY"
    appt = base_fields()
    appt.update({
        "offer_id": offer["id"], "appointment_type": appt_type,
        "eod_date": offer["eod_date"],
    })
    DB.appointments[appt["id"]] = appt
    return success_object(offer_out(offer))


@bp.route("/hiring/offers/<offer_id>/appointments", methods=["GET"])
def list_appointments(offer_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    offer = get_offer_or_404(offer_id)
    limit, offset = parse_pagination()
    items = [a for a in DB.appointments.values() if a["offer_id"] == offer["id"]]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([appointment_out(a) for a in page], limit, offset, total)
