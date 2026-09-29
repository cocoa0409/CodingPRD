"""Programme-year setup, the operational runs and the logical clock."""
from flask import Blueprint

import calc
import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail, invalid
from store import (canonical_instant, new_id, parse_instant, store)
from validators import (authenticate, body, paginate, v_date, v_instant, v_int,
                        v_number, v_state_code, v_str)

bp = Blueprint("program_years", __name__)

ALL_ROLES = ("ProgramAdmin", "EligibilityOfficer", "ComplianceOfficer",
             "AppealsOfficer", "ExpenseReviewer", "VendorScreener",
             "Guardian", "Provider")


@bp.post("/program-years")
def create_program_year():
    authenticate("ProgramAdmin")
    payload = body()
    label = v_str(payload, "label")
    residency_state = v_state_code(payload, "residency_state")
    total_seats = v_int(payload, "total_seats", minimum=0)
    window_open_at = v_instant(payload, "window_open_at")
    window_close_at = v_instant(payload, "window_close_at")
    term_start_date = v_date(payload, "term_start_date")
    term_end_date = v_date(payload, "term_end_date")
    base_award_cents = v_int(payload, "base_award_cents", required=False,
                             default=731500, minimum=1)
    rollover_cap_pct = v_number(payload, "rollover_cap_pct", required=False,
                                default=0.25, minimum=0, maximum=1)
    admin_fee_pct = v_number(payload, "admin_fee_pct", required=False,
                             default=0.0175, minimum=0, exclusive_maximum=1)
    acceptance_deadline_days = v_int(payload, "acceptance_deadline_days",
                                     required=False, default=14, minimum=1)
    min_assessment_percentile = v_int(payload, "min_assessment_percentile",
                                      required=False, default=40,
                                      minimum=0, maximum=100)
    min_portfolio_artifacts = v_int(payload, "min_portfolio_artifacts",
                                    required=False, default=6, minimum=1)

    if parse_instant(window_close_at) <= parse_instant(window_open_at):
        invalid("window_close_at must be strictly after window_open_at")
    if term_end_date <= term_start_date:
        invalid("term_end_date must be strictly after term_start_date")
    for existing in store.program_years.values():
        if existing["label"] == label:
            invalid("label '%s' is already used by another program year" % label)

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "label": label,
        "residency_state": residency_state,
        "base_award_cents": base_award_cents,
        "total_seats": total_seats,
        "seats_committed": 0,
        "seats_available": 0,
        "rollover_cap_pct": rollover_cap_pct,
        "admin_fee_pct": admin_fee_pct,
        "window_open_at": window_open_at,
        "window_close_at": window_close_at,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "acceptance_deadline_days": acceptance_deadline_days,
        "min_assessment_percentile": min_assessment_percentile,
        "min_portfolio_artifacts": min_portfolio_artifacts,
        "current_quarter": 0,
        "status": "DRAFT",
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.program_years[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/program-years/<pyid>")
def read_program_year(pyid):
    authenticate(*ALL_ROLES)
    return object_response(public(lookups.program_year(pyid)))


@bp.post("/program-years/<pyid>/open-window")
def open_window(pyid):
    authenticate("ProgramAdmin")
    py = lookups.program_year(pyid)
    if py["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION",
             "program year must be DRAFT to open its submission window")
    py["status"] = "WINDOW_OPEN"
    py["seats_committed"] = 0
    py["seats_available"] = py["total_seats"]
    touch(py)
    return object_response(public(py))


@bp.post("/program-years/<pyid>/awarding-runs")
def awarding_run(pyid):
    authenticate("ProgramAdmin")
    py = lookups.program_year(pyid)
    if py["status"] != "WINDOW_OPEN":
        fail("ERR_INVALID_STATE_TRANSITION",
             "award allocation requires the program year to be WINDOW_OPEN")

    # WINDOW_OPEN -> AWARDING (transient, but a real versioned transition).
    py["status"] = "AWARDING"
    touch(py, force=True)

    candidates = [a for a in lookups.applications_of_year(pyid)
                  if a["status"] == "ELIGIBLE"]
    candidates.sort(key=calc.rank_key)
    seats = py["seats_available"]
    if seats < 0:
        seats = 0
    offered = candidates[:seats]
    waitlisted = candidates[seats:]

    deadline = cascades.offer_deadline(py)
    awarded_ids = []
    for app in offered:
        app["status"] = "AWARD_OFFERED"
        app["acceptance_deadline_at"] = deadline
        app["waitlist_position"] = None
        touch(app)
        awarded_ids.append(app["id"])

    waitlist_ids = []
    for index, app in enumerate(waitlisted):
        app["status"] = "WAITLISTED"
        app["waitlist_position"] = index + 1
        touch(app)
        waitlist_ids.append(app["id"])

    cascades.recount_seats(py)
    py["status"] = "ACTIVE"
    touch(py, force=True)

    return object_response({
        "awarded_count": len(awarded_ids),
        "waitlisted_count": len(waitlist_ids),
        "program_year_status": py["status"],
        "seats_committed": py["seats_committed"],
        "seats_available": py["seats_available"],
        "awarded_application_ids": awarded_ids,
        "waitlist_ordered_application_ids": waitlist_ids,
    })


@bp.post("/program-years/<pyid>/disbursement-runs")
def disbursement_run(pyid):
    authenticate("ProgramAdmin")
    payload = body()
    quarter = v_int(payload, "quarter", minimum=0)
    py = lookups.program_year(pyid)
    if py["status"] != "ACTIVE":
        fail("ERR_PROGRAM_YEAR_NOT_ACTIVE",
             "disbursement runs require an ACTIVE program year")
    if quarter != py["current_quarter"] + 1 or quarter > 4:
        fail("ERR_INVALID_STATE_TRANSITION",
             "quarter must be exactly one more than current_quarter")

    now = store.now()
    expired_ids = []
    promoted_ids = []
    # Pass one: expire overdue offers, promoting the waitlist as seats free up.
    for app in lookups.applications_of_year(pyid):
        if app["status"] != "AWARD_OFFERED":
            continue
        deadline = app.get("acceptance_deadline_at")
        if not deadline or deadline > now:
            continue
        app["status"] = "EXPIRED"
        app["acceptance_deadline_at"] = deadline
        touch(app)
        expired_ids.append(app["id"])
        cascades.recount_seats(py)
        promoted = cascades.promote_from_waitlist(py)
        if promoted:
            promoted_ids.append(promoted)

    # Pass two: credit one quarterly slice per eligible ACTIVE account.
    skipped = []
    rows = 0
    total_gross = 0
    total_fee = 0
    total_net = 0
    for acct in lookups.accounts_of_year(pyid):
        if (acct["status"] != "ACTIVE"
                or acct["disbursement_count"] >= acct["quarters_remaining_at_award"]):
            skipped.append(acct["id"])
            continue
        figures = calc.quarterly_disbursement_slice(
            acct["final_award_cents"], acct["lifetime_disbursed_cents"],
            acct["quarters_remaining_at_award"], acct["disbursement_count"],
            py["admin_fee_pct"],
        )
        row = {
            "id": new_id(),
            "account_id": acct["id"],
            "program_year_id": pyid,
            "quarter": quarter,
            "quarters_left_at_issue": figures["quarters_left_at_issue"],
            "gross_amount_cents": figures["gross_amount_cents"],
            "remainder_applied_cents": figures["remainder_applied_cents"],
            "admin_fee_cents": figures["admin_fee_cents"],
            "net_credited_cents": figures["net_credited_cents"],
            "issued_at": now,
            "created_at": store.next_created_at(),
            "_seq": store.next_seq(),
        }
        store.disbursements[row["id"]] = row

        acct["balance_cents"] += figures["net_credited_cents"]
        acct["lifetime_disbursed_cents"] += figures["gross_amount_cents"]
        acct["lifetime_admin_fee_cents"] += figures["admin_fee_cents"]
        acct["disbursement_count"] += 1
        touch(acct)

        rows += 1
        total_gross += figures["gross_amount_cents"]
        total_fee += figures["admin_fee_cents"]
        total_net += figures["net_credited_cents"]

    py["current_quarter"] = quarter
    touch(py)

    return object_response({
        "quarter": quarter,
        "disbursement_count": rows,
        "total_gross_cents": total_gross,
        "total_admin_fee_cents": total_fee,
        "total_net_credited_cents": total_net,
        "skipped_account_ids": skipped,
        "expired_application_ids": expired_ids,
        "promoted_application_ids": promoted_ids,
    })


@bp.post("/program-years/<pyid>/year-end-close")
def year_end_close(pyid):
    authenticate("ProgramAdmin")
    py = lookups.program_year(pyid)
    if py["status"] != "ACTIVE":
        fail("ERR_PROGRAM_YEAR_NOT_ACTIVE",
             "year-end close requires an ACTIVE program year")

    closed = 0
    total_rolled = 0
    total_forfeited = 0
    for acct in lookups.accounts_of_year(pyid):
        if acct["status"] != "ACTIVE":
            continue
        figures = calc.unused_balance_rollover(
            acct["balance_cents"], acct["final_award_cents"],
            py["rollover_cap_pct"],
        )
        acct["rollover_carried_cents"] = figures["rollover_carried_cents"]
        acct["forfeited_cents"] = figures["forfeited_cents"]
        acct["balance_cents"] = figures["rollover_carried_cents"]
        touch(acct)
        closed += 1
        total_rolled += figures["rollover_carried_cents"]
        total_forfeited += figures["forfeited_cents"]

        app = store.applications.get(acct["application_id"])
        if app is not None and app["status"] == "ACCEPTED":
            app["status"] = "COMPLETED"
            touch(app)

    resolved = []
    year_account_ids = set(a["id"] for a in lookups.accounts_of_year(pyid))
    for case in sorted(store.misuse_cases.values(), key=lambda c: c["_seq"]):
        if case["account_id"] not in year_account_ids:
            continue
        if case["status"] != "CLAWBACK_ISSUED":
            continue
        case["status"] = "RESOLVED"
        touch(case)
        resolved.append(case["id"])

    py["status"] = "CLOSED"
    touch(py)

    return object_response({
        "program_year_status": py["status"],
        "closed_account_count": closed,
        "total_rolled_cents": total_rolled,
        "total_forfeited_cents": total_forfeited,
        "resolved_misuse_case_ids": resolved,
    })


@bp.get("/program-years/<pyid>/disbursements")
def list_year_disbursements(pyid):
    authenticate("ProgramAdmin", "ComplianceOfficer")
    lookups.program_year(pyid)
    rows = [d for d in sorted(store.disbursements.values(),
                              key=lambda d: d["_seq"])
            if d["program_year_id"] == pyid]
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate("ProgramAdmin")
    payload = body()
    to_iso8601 = v_instant(payload, "to_iso8601")
    store.clock = canonical_instant(to_iso8601)
    return object_response({"current_utc": store.clock})
