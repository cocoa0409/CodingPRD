"""ProgressReport and AwardModification routes."""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    ADJUDICATE_DECISIONS,
    CARRYOVER_AUTO_APPROVE_PCT,
    MODIFICATION_TYPES,
    NCE_MAX_EXTENSION_DAYS,
    REPORT_WINDOW_GRACE_DAYS,
    ROLE_APPLICANT,
    ROLE_GRANTS_OFFICER,
)
from db import STORE, clock_now, new_entity, touch
from errors import fail
from serializers import modification_json, report_json
from services import (
    apply_carryover,
    dec,
    get,
    period_end,
    rhu,
    unobligated,
)
from util import (
    auth_context,
    get_body,
    ok_list,
    ok_object,
    parse_pagination,
    req_dt,
    req_enum,
    req_int,
    req_str,
    opt_str,
    require_owner,
    require_role,
    sort_and_page,
)

bp = Blueprint("postaward", __name__)


def _get_award_or_404(award_id):
    award = get("awards", award_id)
    if award is None:
        fail("ERR_AWARD_NOT_FOUND", "award not found")
    return award


def _require_award_owner(award, user_id):
    app = get("applications", award["application_id"])
    require_owner(app["applicant_id"] if app else None, user_id)


# ---------------------------------------------------------------------------
# ProgressReport
# ---------------------------------------------------------------------------
@bp.route("/grants/awards/<award_id>/progress-reports", methods=["POST"])
def create_progress_report(award_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT,))
    award = _get_award_or_404(award_id)
    body = get_body()
    period_year = req_int(body, "period_year")
    actual = req_int(body, "actual_expenditure_cents", minimum=0)
    publications = req_int(body, "publications_count", minimum=0)
    _require_award_owner(award, user_id)
    if award["status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE", "progress reports require an ACTIVE award")
    if period_year != award["current_period"]:
        fail(
            "ERR_REPORT_PERIOD_MISMATCH",
            "period_year must equal the award's current_period",
        )
    now = clock_now()
    p_end = period_end(award, period_year)
    if now > p_end + timedelta(days=REPORT_WINDOW_GRACE_DAYS):
        fail(
            "ERR_REPORT_WINDOW_CLOSED",
            "the filing window for the current period has closed",
        )
    report = new_entity()
    report.update(
        {
            "award_id": award["id"],
            "period_year": period_year,
            "actual_expenditure_cents": actual,
            "publications_count": publications,
            "submitted_late": now > p_end,
            "status": "SUBMITTED",
        }
    )
    STORE["progress_reports"][report["id"]] = report
    return ok_object(report_json(report), 201)


@bp.route("/grants/awards/<award_id>/progress-reports", methods=["GET"])
def list_progress_reports(award_id):
    auth_context()
    award = _get_award_or_404(award_id)
    limit, offset = parse_pagination(request.args)
    items = [r for r in STORE["progress_reports"].values() if r["award_id"] == award["id"]]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([report_json(r) for r in page], total, limit, offset)


@bp.route("/grants/progress-reports/<report_id>/accept", methods=["POST"])
def accept_progress_report(report_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    report = get("progress_reports", report_id)
    if report is None:
        fail("ERR_PROGRESS_REPORT_NOT_FOUND", "progress report not found")
    if report["status"] != "SUBMITTED":
        fail("ERR_REPORT_INVALID_STATE", "accept requires SUBMITTED status")
    award = get("awards", report["award_id"])
    idx = award["current_period"] - 1
    period_total = (
        award["period_total_cents"][idx] if idx < len(award["period_total_cents"]) else 0
    )
    disbursed = min(report["actual_expenditure_cents"], period_total)
    while len(award["disbursed_per_period_cents"]) <= idx:
        award["disbursed_per_period_cents"].append(0)
    award["disbursed_cents"] += disbursed
    award["disbursed_per_period_cents"][idx] = disbursed
    award["current_period"] += 1
    touch(award)
    institute = get("institutes", award["institute_id"])
    institute["committed_cents"] -= disbursed
    institute["disbursed_cents"] += disbursed
    touch(institute)
    report["status"] = "ACCEPTED"
    touch(report)
    return ok_object(report_json(report))


# ---------------------------------------------------------------------------
# AwardModification
# ---------------------------------------------------------------------------
@bp.route("/grants/awards/<award_id>/modifications", methods=["POST"])
def create_modification(award_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_APPLICANT, ROLE_GRANTS_OFFICER))
    award = _get_award_or_404(award_id)
    body = get_body()
    mod_type = req_enum(body, "type", MODIFICATION_TYPES)
    if role == ROLE_APPLICANT and mod_type == "TERMINATION":
        fail(
            "ERR_MODIFICATION_TYPE_ROLE_MISMATCH",
            "Applicant may create only CARRYOVER or NO_COST_EXTENSION modifications",
        )
    if role == ROLE_GRANTS_OFFICER and mod_type != "TERMINATION":
        fail(
            "ERR_MODIFICATION_TYPE_ROLE_MISMATCH",
            "GrantsOfficer may create only TERMINATION modifications",
        )
    if role == ROLE_APPLICANT:
        _require_award_owner(award, user_id)
    reason = opt_str(body, "reason")
    if award["status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE", "modifications require an ACTIVE award")

    mod = new_entity()
    mod.update(
        {
            "award_id": award["id"],
            "type": mod_type,
            "amount_cents": None,
            "from_period": None,
            "new_end_date": None,
            "reason": reason,
            "auto_approved": False,
            "status": "PENDING_APPROVAL",
        }
    )

    if mod_type == "CARRYOVER":
        amount = req_int(body, "amount_cents", minimum=0)
        from_period = req_int(body, "from_period", minimum=1)
        mod["amount_cents"] = amount
        mod["from_period"] = from_period
        if from_period != award["current_period"] - 1:
            fail(
                "ERR_CARRYOVER_PERIOD_MISMATCH",
                "from_period must equal the award's current_period - 1",
            )
        available = unobligated(award, from_period)
        if amount > available:
            fail(
                "ERR_CARRYOVER_EXCEEDS_UNOBLIGATED",
                "carryover amount exceeds the unobligated balance of from_period",
            )
        auto_limit = int(rhu(dec(available) * dec(CARRYOVER_AUTO_APPROVE_PCT), 0))
        if amount <= auto_limit:
            mod["auto_approved"] = True
            mod["status"] = "AUTO_APPROVED"
            apply_carryover(award, amount, from_period)
    elif mod_type == "NO_COST_EXTENSION":
        new_end = req_dt(body, "new_end_date")
        mod["new_end_date"] = new_end
        if clock_now() > award["end_date"]:
            fail("ERR_NCE_TOO_LATE", "no-cost extension requested after the award end_date")
        if new_end <= award["end_date"]:
            fail("ERR_VALIDATION", "new_end_date must be after the current end_date")
        if new_end - award["end_date"] > timedelta(days=NCE_MAX_EXTENSION_DAYS):
            fail(
                "ERR_NCE_LIMIT_EXCEEDED",
                "requested extension exceeds %d days beyond the current end_date"
                % NCE_MAX_EXTENSION_DAYS,
            )
        prior_approved_nce = any(
            m["award_id"] == award["id"]
            and m["type"] == "NO_COST_EXTENSION"
            and m["status"] in ("APPROVED", "AUTO_APPROVED")
            for m in STORE["award_modifications"].values()
        )
        if not prior_approved_nce:
            mod["auto_approved"] = True
            mod["status"] = "AUTO_APPROVED"
            award["end_date"] = new_end
            touch(award)
    else:  # TERMINATION — always auto-approves at creation
        mod["auto_approved"] = True
        mod["status"] = "AUTO_APPROVED"
        award["status"] = "TERMINATED"
        touch(award)
        institute = get("institutes", award["institute_id"])
        institute["committed_cents"] -= award["total_awarded_cents"] - award["disbursed_cents"]
        touch(institute)

    STORE["award_modifications"][mod["id"]] = mod
    return ok_object(modification_json(mod), 201)


@bp.route("/grants/awards/<award_id>/modifications", methods=["GET"])
def list_modifications(award_id):
    auth_context()
    award = _get_award_or_404(award_id)
    limit, offset = parse_pagination(request.args)
    items = [
        m for m in STORE["award_modifications"].values() if m["award_id"] == award["id"]
    ]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([modification_json(m) for m in page], total, limit, offset)


@bp.route("/grants/award-modifications/<mod_id>/adjudicate", methods=["POST"])
def adjudicate_modification(mod_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    mod = get("award_modifications", mod_id)
    if mod is None:
        fail("ERR_MODIFICATION_NOT_FOUND", "award modification not found")
    body = get_body()
    decision = req_enum(body, "decision", ADJUDICATE_DECISIONS)
    opt_str(body, "denial_reason")
    if mod["status"] != "PENDING_APPROVAL":
        fail("ERR_MODIFICATION_NOT_PENDING", "adjudicate requires PENDING_APPROVAL")
    if decision == "DENY":
        mod["status"] = "DENIED"
        touch(mod)
        return ok_object(modification_json(mod))
    award = get("awards", mod["award_id"])
    if mod["type"] == "CARRYOVER":
        apply_carryover(award, mod["amount_cents"], mod["from_period"])
    elif mod["type"] == "NO_COST_EXTENSION":
        award["end_date"] = mod["new_end_date"]
        touch(award)
    mod["status"] = "APPROVED"
    touch(mod)
    return ok_object(modification_json(mod))
