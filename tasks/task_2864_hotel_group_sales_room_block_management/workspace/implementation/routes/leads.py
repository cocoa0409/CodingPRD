"""Lead capture and qualification, meeting space, displacement review."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import analysis_json, hold_json, lead_json

bp = Blueprint("leads", __name__)

ANALYSIS_LEAD_STATES = ("QUALIFIED", "CLEARED", "QUOTED", "DISPLACEMENT_REVIEW")
DECIDE_LEAD_STATES = ("DISPLACEMENT_REVIEW", "CLEARED", "QUOTED")


# --------------------------------------------------------------------- leads

@bp.route("/group-sales/leads", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER])
def create_lead():
    body = body_json()
    account_id = v_id(body, "account_id")
    program_name = v_string(body, "program_name", min_len=1, max_len=120)
    arrival = v_date(body, "arrival_date")
    departure = v_date(body, "departure_date")
    peak_rooms = v_int(body, "peak_rooms", minimum=1)
    total_rn = v_int(body, "total_requested_room_nights", minimum=1)
    sqft = v_int(body, "meeting_space_sqft_needed", minimum=0)
    deadline = v_instant(body, "decision_deadline_at")
    need_account(account_id)
    if departure <= arrival:
        fail("ERR_INVALID_DATE_RANGE",
             "'departure_date' must be strictly later than 'arrival_date'.")
    row = new_row({
        "account_id": account_id,
        "owner_user_id": actor(),
        "program_name": program_name,
        "arrival_date": iso_date(arrival),
        "departure_date": iso_date(departure),
        "nights_count": whole_days(departure, arrival),
        "peak_rooms": peak_rooms,
        "total_requested_room_nights": total_rn,
        "meeting_space_sqft_needed": sqft,
        "decision_deadline_at": iso_instant(deadline),
        "status": "NEW",
        "qualification_score": None,
        "estimated_room_night_value_cents": None,
    })
    store.leads[row["id"]] = row
    return ok(lead_json(row), 201)


@bp.route("/group-sales/leads/<lead_id>", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_ACCOUNTING_CLERK, ROLE_GROUP_CONTACT])
def read_lead(lead_id):
    lead = need_lead(lead_id)
    require_owner(owner_of_lead(lead))
    return ok(lead_json(lead))


@bp.route("/group-sales/leads/<lead_id>/qualify", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER])
def qualify_lead(lead_id):
    lead = need_lead(lead_id)
    if lead["status"] != "NEW":
        fail("ERR_LEAD_INVALID_STATE",
             "Qualification is declared only from NEW; the lead is %s."
             % lead["status"])
    days = stay_dates(lead["arrival_date"], lead["departure_date"])
    require_calendar(days)
    account = need_account(lead["account_id"])
    score = lead_qualification_score(lead, account)
    lead["qualification_score"] = score
    lead["estimated_room_night_value_cents"] = lead_room_night_value(lead)
    if score >= QUALIFICATION_FLOOR:
        lead["status"] = "QUALIFIED"
    else:
        lead["status"] = "TURNED_DOWN"
        release_held_space(lead["id"])
    touch(lead)
    return ok(lead_json(lead))


@bp.route("/group-sales/leads/<lead_id>/displacement-analyses", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN])
def list_lead_analyses(lead_id):
    status = q_enum("status", ANALYSIS_STATUSES)
    variant = q_enum("analysis_variant", ANALYSIS_VARIANTS)
    limit, offset = q_pagination()
    need_lead(lead_id)
    rows = analyses_of_lead(lead_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if variant is not None:
        rows = [r for r in rows if r["analysis_variant"] == variant]
    page, total = paginate(rows, limit, offset)
    return ok_list([analysis_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/leads/<lead_id>/function-space-holds", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN])
def list_lead_holds(lead_id):
    space_code = q_enum("space_code", SPACE_CODES)
    status = q_enum("status", HOLD_STATUSES)
    limit, offset = q_pagination()
    need_lead(lead_id)
    rows = sorted(holds_of_lead(lead_id), key=lambda r: (r["start_at"], r["_seq"]))
    if space_code is not None:
        rows = [r for r in rows if r["space_code"] == space_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([hold_json(r) for r in page], limit, offset, total)


# ---------------------------------------------------------- function space

@bp.route("/group-sales/function-space-holds", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER])
def create_hold():
    body = body_json()
    lead_id = v_id(body, "lead_id")
    space_code = v_enum(body, "space_code", SPACE_CODES)
    start_at = v_instant(body, "start_at")
    end_at = v_instant(body, "end_at")
    attendees = v_int(body, "attendee_count", minimum=1)
    need_lead(lead_id)
    if end_at <= start_at:
        fail("ERR_INVALID_DATE_RANGE", "'end_at' must be strictly after 'start_at'.")
    check_space_conflict(space_code, start_at, end_at)
    row = new_row({
        "lead_id": lead_id,
        "space_code": space_code,
        "start_at": iso_instant(start_at),
        "end_at": iso_instant(end_at),
        "attendee_count": attendees,
        "status": "HELD",
    })
    store.holds[row["id"]] = row
    return ok(hold_json(row), 201)


@bp.route("/group-sales/function-space-holds/<hold_id>", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN])
def read_hold(hold_id):
    return ok(hold_json(need_hold(hold_id)))


@bp.route("/group-sales/function-space-holds/<hold_id>/release", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER])
def release_hold(hold_id):
    hold = need_hold(hold_id)
    if hold["status"] not in ("HELD", "CONFIRMED"):
        fail("ERR_HOLD_INVALID_STATE",
             "Release is declared from HELD or CONFIRMED; the hold is %s."
             % hold["status"])
    hold["status"] = "RELEASED"
    touch(hold)
    return ok(hold_json(hold))


# --------------------------------------------------- displacement analyses

@bp.route("/group-sales/displacement-analyses", methods=["POST"])
@endpoint([ROLE_REVENUE_MANAGER])
def create_analysis():
    body = body_json()
    lead_id = v_id(body, "lead_id")
    variant = v_enum(body, "analysis_variant", ANALYSIS_VARIANTS)
    lead = need_lead(lead_id)
    if lead["status"] not in ANALYSIS_LEAD_STATES:
        fail("ERR_LEAD_INVALID_STATE",
             "A displacement study is admissible from %s; the lead is %s."
             % (", ".join(ANALYSIS_LEAD_STATES), lead["status"]))
    require_calendar(stay_dates(lead["arrival_date"], lead["departure_date"]))
    figures = displacement_cost(lead, variant)
    row = new_row({
        "lead_id": lead_id,
        "analysis_variant": variant,
        "requested_by_user_id": actor(),
        "decided_by_user_id": None,
        "status": "PENDING",
        "verdict": figures["verdict"],
        "displaced_room_nights": figures["displaced_room_nights"],
        "displaced_revenue_cents": figures["displaced_revenue_cents"],
        "group_revenue_cents": figures["group_revenue_cents"],
        "ancillary_projection_cents": figures["ancillary_projection_cents"],
        "net_benefit_cents": figures["net_benefit_cents"],
        "override_reason": None,
    })
    store.analyses[row["id"]] = row
    # Only the first study moves the negotiation stage (PRD §3.3).
    if lead["status"] == "QUALIFIED":
        lead["status"] = "DISPLACEMENT_REVIEW"
    touch(lead)
    return ok(analysis_json(row), 201)


@bp.route("/group-sales/displacement-analyses/<analysis_id>", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN])
def read_analysis(analysis_id):
    return ok(analysis_json(need_analysis(analysis_id)))


@bp.route("/group-sales/displacement-analyses/<analysis_id>/decide",
          methods=["POST"])
@endpoint([ROLE_REVENUE_MANAGER])
def decide_analysis(analysis_id):
    body = body_json()
    decision = v_enum(body, "decision", DECISIONS)
    expected = v_int(body, "expected_lead_version", minimum=0)
    override = v_string(body, "override_reason", required=False, min_len=None,
                        max_len=500, allow_blank=True)
    analysis = need_analysis(analysis_id)
    lead = need_lead(analysis["lead_id"])
    if expected != lead["version"]:
        fail("ERR_STALE_LEAD_VERSION",
             "expected_lead_version %s does not match the lead's version %s."
             % (expected, lead["version"]))
    if actor() == analysis["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The user who requested the study may not decide it.")
    # PRD §2.8: the declared-transition gate (priority 10) sits above the
    # one-shot replay guard (priority 11).
    if lead["status"] not in DECIDE_LEAD_STATES:
        fail("ERR_LEAD_INVALID_STATE",
             "The lead must be in %s to decide a study; it is %s."
             % (", ".join(DECIDE_LEAD_STATES), lead["status"]))
    if analysis["status"] != "PENDING":
        fail("ERR_ANALYSIS_ALREADY_DECIDED",
             "The analysis was already decided as %s." % analysis["status"])
    if decision == "APPROVE":
        has_reason = override is not None and override.strip() != ""
        if analysis["verdict"] != "ACCEPT" and not has_reason:
            fail("ERR_DISPLACEMENT_NET_BENEFIT_NEGATIVE",
                 "Approving a negative net benefit requires 'override_reason'.")
        analysis["status"] = "APPROVED"
        analysis["decided_by_user_id"] = actor()
        analysis["override_reason"] = override if has_reason else None
        touch(analysis)
        if lead["status"] == "DISPLACEMENT_REVIEW":
            lead["status"] = "CLEARED"
        touch(lead)
    else:
        analysis["status"] = "REJECTED"
        analysis["decided_by_user_id"] = actor()
        touch(analysis)
        lead["status"] = "LOST"
        withdraw_quotes_of_lead(lead["id"])
        release_held_space(lead["id"])
        touch(lead)
    return ok(analysis_json(analysis))
