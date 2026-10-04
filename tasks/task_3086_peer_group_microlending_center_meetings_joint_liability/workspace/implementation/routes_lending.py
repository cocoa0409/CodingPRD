"""Routes: loan applications, consensus votes, disbursement, loans,
restructures, center meetings, attendance, collections, reconciliation,
repayment transactions."""
from datetime import timedelta

from flask import Blueprint, request

import core as C

bp = Blueprint("lending", __name__)


def ok(data, status=200, meta_extra=None):
    from app import envelope_ok
    return envelope_ok(data, status=status, meta_extra=meta_extra)


def list_response(items, serializer):
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    page, meta = C.paginate(items)
    return ok([serializer(r) for r in page], meta_extra=meta)


# ---------------------------------------------------------------------------
# Loan applications & consensus
# ---------------------------------------------------------------------------


@bp.post("/peer-groups/<gid>/loan-applications")
def draft_application(gid):
    g = C.lookup("peer_groups", gid, "ERR_PEER_GROUP_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["member_id", "requested_amount_cents"])
    member_id = body.get("member_id")
    if not C.is_str(member_id):
        raise C.err("ERR_INVALID_REQUEST", "member_id must be a string")
    amount = body.get("requested_amount_cents")
    if not C.is_int(amount) or amount <= 0 or amount % 100 != 0:
        raise C.err("ERR_INVALID_REQUEST",
                    "requested_amount_cents must be a positive multiple of 100")
    C.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    a = {"peer_group_id": gid, "member_id": member_id,
         "requested_amount_cents": amount, "status": "DRAFT",
         "voting_deadline_dt": None, "applied_ceiling_cents": None}
    C.stamp_new(a)
    C.STORE["loan_applications"][a["id"]] = a
    return ok(C.ser_application(a), status=201)


@bp.get("/loan-applications")
def list_applications():
    items = list(C.STORE["loan_applications"].values())
    group_id = request.args.get("peer_group_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if group_id is not None:
        items = [a for a in items if a["peer_group_id"] == group_id]
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, C.ser_application)


@bp.get("/loan-applications/<aid>")
def get_application(aid):
    a = C.lookup("loan_applications", aid, "ERR_APPLICATION_NOT_FOUND")
    return ok(C.ser_application(a))


@bp.post("/loan-applications/<aid>/submit")
def submit_application(aid):
    a = C.lookup("loan_applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "DRAFT":
        raise C.err("ERR_APPLICATION_NOT_DRAFT", "Application is not DRAFT")
    m = C.STORE["members"][a["member_id"]]
    if m["status"] == "BLACKLISTED":
        raise C.err("ERR_MEMBER_BLACKLISTED", "Member is blacklisted")
    if m["status"] not in ("ELIGIBLE", "ACTIVE_BORROWER"):
        raise C.err("ERR_MEMBER_NOT_ELIGIBLE",
                    "Member is not ELIGIBLE or ACTIVE_BORROWER")
    if m["consecutive_absence_streak"] >= 2:
        raise C.err("ERR_ATTENDANCE_INELIGIBLE",
                    "Member's consecutive absence streak is 2 or more")
    for other in C.STORE["loan_applications"].values():
        if other["id"] != a["id"] and other["member_id"] == m["id"] \
                and other["status"] in ("DRAFT", "VOTING", "APPROVED"):
            raise C.err("ERR_MEMBER_HAS_OPEN_APPLICATION",
                        "Member already has an open application")
    for l in C.STORE["loans"].values():
        if l["member_id"] == m["id"] and l["status"] in ("ACTIVE", "DELINQUENT"):
            raise C.err("ERR_MEMBER_HAS_ACTIVE_LOAN",
                        "Member has a loan in ACTIVE or DELINQUENT")
    g = C.STORE["peer_groups"].get(a["peer_group_id"])
    if g is None or g["status"] != "ACTIVE":
        raise C.err("ERR_GROUP_NOT_ACTIVE", "Group is not ACTIVE")
    a["status"] = "VOTING"
    a["voting_deadline_dt"] = C.logical_now() + timedelta(days=7)
    C.touch(a)
    return ok(C.ser_application(a))


@bp.post("/loan-applications/<aid>/votes")
def cast_vote(aid):
    voter_id = request.headers.get("X-User-ID")
    a = C.lookup("loan_applications", aid, "ERR_APPLICATION_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["decision"])
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise C.err("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT")
    if a["status"] != "VOTING":
        raise C.err("ERR_APPLICATION_NOT_VOTING", "Application is not VOTING")
    voter = C.STORE["members"].get(voter_id)
    if voter is None or voter.get("peer_group_id") != a["peer_group_id"]:
        raise C.err("ERR_VOTER_NOT_GROUP_PEER",
                    "Voter is not a member of the applicant's group")
    if a["member_id"] == voter_id:
        raise C.err("ERR_VOTER_IS_APPLICANT",
                    "Applicant may not vote on their own application")
    for v in C.STORE["consensus_votes"].values():
        if v["loan_application_id"] == aid and v["voter_member_id"] == voter_id:
            raise C.err("ERR_ALREADY_VOTED", "Voter has already voted on this application")
    if a.get("voting_deadline_dt") is not None \
            and C.logical_now() >= a["voting_deadline_dt"]:
        raise C.err("ERR_VOTING_WINDOW_EXPIRED", "Voting window has closed")
    v = {"loan_application_id": aid, "voter_member_id": voter_id, "decision": decision}
    v["id"] = C.new_id()
    v["created_at"] = C.fmt_created(C.now_dt())
    C.STORE["consensus_votes"][v["id"]] = v
    if decision == "REJECT":
        a["status"] = "REJECTED"
        C.touch(a)
    else:
        peers = [m for m in C.group_members(a["peer_group_id"],
                                            exclude_blacklisted=True)
                 if m["id"] != a["member_id"]]
        approvals = {x["voter_member_id"] for x in C.STORE["consensus_votes"].values()
                     if x["loan_application_id"] == aid and x["decision"] == "APPROVE"}
        if len(approvals) >= 4 and all(p["id"] in approvals for p in peers):
            g = C.STORE["peer_groups"].get(a["peer_group_id"])
            if g is not None and g["status"] == "ACTIVE":
                a["status"] = "APPROVED"
                C.touch(a)
    return ok(C.ser_vote(v), status=201)


@bp.get("/loan-applications/<aid>/votes")
def list_votes(aid):
    C.lookup("loan_applications", aid, "ERR_APPLICATION_NOT_FOUND")
    votes = [v for v in C.STORE["consensus_votes"].values()
             if v["loan_application_id"] == aid]
    return list_response(votes, C.ser_vote)


@bp.get("/loan-applications/<aid>/loan")
def get_application_loan(aid):
    C.lookup("loan_applications", aid, "ERR_APPLICATION_NOT_FOUND")
    loans = [l for l in C.STORE["loans"].values() if l["loan_application_id"] == aid]
    return list_response(loans, C.ser_loan)


@bp.post("/loan-applications/<aid>/disburse")
def disburse(aid):
    a = C.lookup("loan_applications", aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "APPROVED":
        raise C.err("ERR_APPLICATION_NOT_APPROVED", "Application is not APPROVED")
    g = C.STORE["peer_groups"].get(a["peer_group_id"])
    if g is None or g["status"] != "ACTIVE":
        raise C.err("ERR_GROUP_RESTRICTED", "Applicant's group is not ACTIVE")
    m = C.STORE["members"][a["member_id"]]
    if m["status"] not in ("ELIGIBLE", "ACTIVE_BORROWER"):
        raise C.err("ERR_MEMBER_NOT_ELIGIBLE",
                    "Member is not ELIGIBLE or ACTIVE_BORROWER")
    ceiling = C.next_loan_ceiling(m)
    if a["requested_amount_cents"] > ceiling:
        raise C.err("ERR_LADDER_CEILING_EXCEEDED",
                    "requested_amount_cents exceeds the ladder ceiling")
    term = 24
    weekly, savings = C.split_amounts(a["requested_amount_cents"], term,
                                      m["cycle_level"], m)
    loan = {
        "member_id": m["id"], "loan_application_id": a["id"],
        "cycle_level": m["cycle_level"], "principal_cents": a["requested_amount_cents"],
        "term_weeks": term, "weekly_installment_cents": weekly,
        "savings_required_cents": savings,
        "principal_outstanding_cents": term * weekly,
        "next_due_dt": C.logical_now() + timedelta(days=7),
        "installments_on_time": 0, "installments_missed": 0,
        "arrears_retired": 0, "installment_applied_total": 0,
        "status": "ACTIVE", "terminal_at_dt": None,
        # The loan's lifetime for the FINAL score's attendance window runs on
        # the logical clock (PRD 2.4: every time-dependent rule reads it),
        # from the disbursement instant through the terminal transition.
        "disbursed_at_dt": C.logical_now(),
    }
    C.stamp_new(loan)
    C.STORE["loans"][loan["id"]] = loan
    if m["status"] == "ELIGIBLE":
        m["status"] = "ACTIVE_BORROWER"
        C.touch(m)
    C.open_savings_account_if_absent(m)
    # The PROVISIONAL report's score is pinned by the PRD's provisional
    # formula over the just-created loan (a mid-cycle loan with no activity
    # reads 600 + 5 * term_weeks), evaluated here before any cascade mutates
    # the loan's counters.
    provisional_at_filing = C.clamp_score(
        C.SCORE_BASE + C.PER_ON_TIME * 0 + C.PER_PROJECTED * term
        - C.PER_MISSED * 0 - C.PER_STRIKE * m["attendance_strikes"]
    )
    C.file_bureau_report(m, loan, "PROVISIONAL", provisional_at_filing)
    a["applied_ceiling_cents"] = ceiling
    a["status"] = "DISBURSED"
    C.touch(a)
    return ok(C.ser_loan(loan))


# ---------------------------------------------------------------------------
# Loans & restructures
# ---------------------------------------------------------------------------


@bp.get("/loans")
def list_loans():
    items = list(C.STORE["loans"].values())
    member_id = request.args.get("member_id")
    app_id = request.args.get("loan_application_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [l for l in items if l["member_id"] == member_id]
    if app_id is not None:
        items = [l for l in items if l["loan_application_id"] == app_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items, C.ser_loan)


@bp.get("/loans/<lid>")
def get_loan(lid):
    l = C.lookup("loans", lid, "ERR_LOAN_NOT_FOUND")
    return ok(C.ser_loan(l))


@bp.post("/loans/<lid>/restructures")
def create_restructure(lid):
    loan = C.lookup("loans", lid, "ERR_LOAN_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["new_term_weeks", "expected_loan_version"])
    new_term = C.require_int(body, "new_term_weeks")
    expected = C.require_int(body, "expected_loan_version")
    if new_term not in C.ALLOWED_RESTRUCTURE_TERMS:
        raise C.err("ERR_INVALID_REQUEST", "new_term_weeks must be one of 12, 24, 36, 48")
    applied = loan.get("installment_applied_total", 0)
    if new_term <= applied:
        raise C.err("ERR_INVALID_REQUEST",
                    "new_term_weeks must exceed the number of installments already applied")
    if expected != loan["version"]:
        raise C.err("ERR_STALE_LOAN_VERSION",
                    "expected_loan_version does not match the loan's current version")
    for r in C.STORE["loan_restructures"].values():
        if r["loan_id"] == lid and r["status"] == "ACTIVE":
            r["status"] = "SUPERSEDED"
            C.touch(r)
    member = C.STORE["members"][loan["member_id"]]
    weekly, savings = C.split_amounts(loan["principal_outstanding_cents"], new_term,
                                      loan["cycle_level"], member)
    loan["term_weeks"] = new_term
    loan["weekly_installment_cents"] = weekly
    loan["savings_required_cents"] = savings
    rec = {"loan_id": lid, "new_term_weeks": new_term, "status": "ACTIVE"}
    C.stamp_new(rec)
    C.STORE["loan_restructures"][rec["id"]] = rec
    C.touch(loan)
    return ok(C.ser_restructure(rec), status=201)


@bp.get("/loans/<lid>/restructures")
def list_restructures(lid):
    C.lookup("loans", lid, "ERR_LOAN_NOT_FOUND")
    items = [r for r in C.STORE["loan_restructures"].values() if r["loan_id"] == lid]
    return list_response(items, C.ser_restructure)


@bp.get("/loans/<lid>/bureau-reports")
def list_loan_reports(lid):
    C.lookup("loans", lid, "ERR_LOAN_NOT_FOUND")
    items = [r for r in C.STORE["credit_bureau_reports"].values() if r["loan_id"] == lid]
    return list_response(items, C.ser_report)


# ---------------------------------------------------------------------------
# Center meetings
# ---------------------------------------------------------------------------


@bp.post("/center-meetings")
def create_meeting():
    body = request.get_json(silent=True)
    C.require_fields(body, ["center_id", "scheduled_start", "scheduled_end"])
    center_id = body.get("center_id")
    if not C.is_str(center_id):
        raise C.err("ERR_INVALID_REQUEST", "center_id must be a string")
    start_dt = C.parse_iso(body.get("scheduled_start"))
    end_dt = C.parse_iso(body.get("scheduled_end"))
    if start_dt is None or end_dt is None:
        raise C.err("ERR_INVALID_REQUEST",
                    "scheduled_start and scheduled_end must be ISO8601 timestamps")
    center = C.lookup("centers", center_id, "ERR_CENTER_NOT_FOUND")
    if end_dt <= start_dt:
        raise C.err("ERR_INVALID_TIME_RANGE",
                    "scheduled_end must be strictly after scheduled_start")
    if start_dt.weekday() != center["meeting_day_of_week"]:
        raise C.err("ERR_MEETING_DAY_MISMATCH",
                    "scheduled_start weekday does not match the center's meeting_day_of_week")
    for other in C.STORE["center_meetings"].values():
        if other["center_id"] != center_id or other["status"] == "CANCELLED":
            continue
        if start_dt < other["end_dt"] and other["start_dt"] < end_dt:
            raise C.err("ERR_MEETING_OVERLAP",
                        "Meeting overlaps another meeting of the same center")
    mtg = {"center_id": center_id, "start_dt": start_dt, "end_dt": end_dt,
           "status": "SCHEDULED", "settlement_status": "PENDING",
           "declared_cash_cents": None, "closer_user_id": None, "closed_at_dt": None}
    C.stamp_new(mtg)
    C.STORE["center_meetings"][mtg["id"]] = mtg
    return ok(C.ser_meeting(mtg), status=201)


@bp.get("/center-meetings")
def list_meetings():
    items = list(C.STORE["center_meetings"].values())
    center_id = request.args.get("center_id")
    status = request.args.get("status")
    if center_id is not None:
        items = [m for m in items if m["center_id"] == center_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response(items, C.ser_meeting)


@bp.get("/center-meetings/<mid>")
def get_meeting(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    return ok(C.ser_meeting(mtg))


def require_center_manager(mtg):
    caller = request.headers.get("X-User-ID")
    center = C.STORE["centers"].get(mtg["center_id"])
    if center is None or caller != center["center_manager_id"]:
        raise C.err("ERR_NOT_CENTER_MANAGER",
                    "Acting CenterManager is not the manager of the meeting's center")


@bp.post("/center-meetings/<mid>/open")
def open_meeting(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    if mtg["status"] != "SCHEDULED":
        raise C.err("ERR_MEETING_NOT_SCHEDULED", "Meeting is not SCHEDULED")
    require_center_manager(mtg)
    mtg["status"] = "OPEN"
    C.touch(mtg)
    return ok(C.ser_meeting(mtg))


@bp.post("/center-meetings/<mid>/cancel")
def cancel_meeting(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    if mtg["status"] != "SCHEDULED":
        raise C.err("ERR_MEETING_NOT_SCHEDULED", "Meeting is not SCHEDULED")
    mtg["status"] = "CANCELLED"
    C.touch(mtg)
    return ok(C.ser_meeting(mtg))


@bp.post("/center-meetings/<mid>/attendance")
def record_attendance(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["member_id", "present"])
    member_id = body.get("member_id")
    if not C.is_str(member_id):
        raise C.err("ERR_INVALID_REQUEST", "member_id must be a string")
    present = body.get("present")
    if not C.is_bool(present):
        raise C.err("ERR_INVALID_REQUEST", "present must be a boolean")
    m = C.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if mtg["status"] != "OPEN":
        raise C.err("ERR_MEETING_NOT_OPEN", "Meeting is not OPEN")
    g = C.member_group(m)
    if g is None or g["center_id"] != mtg["center_id"]:
        raise C.err("ERR_MEMBER_NOT_AT_CENTER",
                    "Member's group is not at this meeting's center")
    row = C.attendance_record(mid, member_id)
    if row is not None:
        row["present"] = present
    else:
        row = {"center_meeting_id": mid, "member_id": member_id, "present": present}
        row["id"] = C.new_id()
        row["created_at"] = C.fmt_created(C.now_dt())
        C.STORE["meeting_attendance"][row["id"]] = row
    return ok(C.ser_attendance(row), status=201)


@bp.get("/center-meetings/<mid>/attendance")
def list_meeting_attendance(mid):
    C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    rows = [a for a in C.STORE["meeting_attendance"].values()
            if a["center_meeting_id"] == mid]
    return list_response(rows, C.ser_attendance)


# ---------------------------------------------------------------------------
# Collections (repayment transactions)
# ---------------------------------------------------------------------------


def apply_collection(meeting, member, loan, amount, account):
    """Four-bucket waterfall (PRD 3.5). Returns a new POSTED transaction."""
    savings = loan["savings_required_cents"]
    weekly = loan["weekly_installment_cents"]
    remaining = amount - savings
    consumed_unpaid = C.count_consumed_unpaid(loan)
    was_delinquent = loan["status"] == "DELINQUENT"
    arrears_applied = min(remaining, consumed_unpaid * weekly)
    installment_applied = arrears_applied
    rem_after_arrears = remaining - arrears_applied
    current_applied = min(rem_after_arrears, weekly)
    installment_applied += current_applied
    rem_after_arrears -= current_applied
    prepayment = min(rem_after_arrears,
                     loan["principal_outstanding_cents"] - installment_applied)
    principal_applied = installment_applied + prepayment

    units = installment_applied // weekly
    new_arrears_retired = min(loan.get("arrears_retired", 0) + units,
                              loan["installments_missed"])
    on_time_this_txn = 0
    if C.logical_now() <= loan["next_due_dt"]:
        on_time_this_txn = units

    txn = {
        "center_meeting_id": meeting["id"], "loan_id": loan["id"],
        "member_id": member["id"], "amount_cents": amount,
        "savings_applied_cents": savings,
        "installment_applied_cents": installment_applied,
        "principal_applied_cents": principal_applied,
        "status": "POSTED",
        "units_applied": units, "on_time_applied": on_time_this_txn,
        "arrears_retired_delta": new_arrears_retired - loan.get("arrears_retired", 0),
    }
    C.stamp_new(txn)
    C.STORE["repayment_transactions"][txn["id"]] = txn

    loan["arrears_retired"] = new_arrears_retired
    loan["installment_applied_total"] = loan.get("installment_applied_total", 0) + units
    loan["installments_on_time"] += on_time_this_txn
    loan["principal_outstanding_cents"] -= principal_applied
    C.touch(loan)

    if account is not None:
        C.recompute_savings(account)
        C.touch(account)

    # Cure (PRD 3.6): the arrears bucket retired every consumed unpaid
    # installment when the count of retired arrears reaches the consumed
    # count. Partial-cent remainders against the oldest due are partial
    # payments, not retired installments — only whole weekly_installment_cents
    # units consume an installment ("each fully covered installment consumes
    # one weekly_installment_cents"). A single collection can fire both the
    # cure chain and the payoff chain (PRD 3.5 names them independently).
    arrears_now_unpaid = loan["installments_missed"] - loan["arrears_retired"]
    if was_delinquent and arrears_now_unpaid == 0:
        C.cure_loan(loan)
    if loan["principal_outstanding_cents"] == 0:
        C.loan_payoff(loan)
    return txn


@bp.post("/center-meetings/<mid>/collections")
def collect(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["member_id", "loan_id", "amount_cents"])
    member_id = body.get("member_id")
    loan_id = body.get("loan_id")
    if not C.is_str(member_id) or not C.is_str(loan_id):
        raise C.err("ERR_INVALID_REQUEST", "member_id and loan_id must be strings")
    amount = C.require_int(body, "amount_cents")
    m = C.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    loan = C.lookup("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    if mtg["status"] != "OPEN":
        raise C.err("ERR_MEETING_NOT_OPEN", "Meeting is not OPEN")
    if loan["member_id"] != member_id:
        raise C.err("ERR_LOAN_MEMBER_MISMATCH",
                    "Collection loan_id does not belong to member_id")
    g = C.member_group(m)
    if g is None or g["center_id"] != mtg["center_id"]:
        raise C.err("ERR_MEMBER_NOT_AT_CENTER",
                    "Member's group is not at this meeting's center")
    if loan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise C.err("ERR_LOAN_NOT_REPAYABLE",
                    "Collection target loan is not ACTIVE or DELINQUENT")
    savings = loan["savings_required_cents"]
    if amount < savings + 1:
        raise C.err("ERR_COLLECTION_BELOW_SAVINGS_MINIMUM",
                    "amount_cents is below savings_required_cents + 1")
    if amount > savings + loan["principal_outstanding_cents"]:
        raise C.err("ERR_COLLECTION_EXCEEDS_OUTSTANDING",
                    "amount_cents exceeds savings_required_cents plus outstanding")
    account = C.member_savings_account(member_id)
    txn = apply_collection(mtg, m, loan, amount, account)
    return ok(C.ser_txn(txn), status=201)


# ---------------------------------------------------------------------------
# Meeting close & reconcile
# ---------------------------------------------------------------------------


@bp.post("/center-meetings/<mid>/close")
def close_meeting(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    if mtg["status"] != "OPEN":
        raise C.err("ERR_MEETING_NOT_OPEN", "Meeting is not OPEN")
    require_center_manager(mtg)
    mtg["closer_user_id"] = request.headers.get("X-User-ID")
    mtg["status"] = "CLOSED"
    mtg["settlement_status"] = "POSTED"
    mtg["closed_at_dt"] = C.logical_now()
    C.touch(mtg)
    center_id = mtg["center_id"]
    counted = []
    for g in C.STORE["peer_groups"].values():
        if g["center_id"] != center_id:
            continue
        for m in C.group_members(g["id"]):
            if m["status"] in C.COUNTED_MEMBER_STATUSES:
                counted.append(m)
    for m in counted:
        if C.attendance_record(mid, m["id"]) is None:
            row = {"center_meeting_id": mid, "member_id": m["id"], "present": False}
            row["id"] = C.new_id()
            row["created_at"] = C.fmt_created(C.now_dt())
            C.STORE["meeting_attendance"][row["id"]] = row
    for m in counted:
        row = C.attendance_record(mid, m["id"])
        old_streak = m["consecutive_absence_streak"]
        new_streak = 0 if row["present"] else old_streak + 1
        if new_streak != old_streak:
            m["consecutive_absence_streak"] = new_streak
            if m["status"] in C.COUNTED_MEMBER_STATUSES:
                C.touch(m)
        if new_streak == 2 and old_streak != 2:
            m["attendance_strikes"] += 1
            C.record_strike(m)
    return ok(C.ser_meeting(mtg))


@bp.post("/center-meetings/<mid>/reconcile")
def reconcile_meeting(mid):
    mtg = C.lookup("center_meetings", mid, "ERR_MEETING_NOT_FOUND")
    body = request.get_json(silent=True)
    C.require_fields(body, ["declared_cash_cents"])
    declared = C.require_int(body, "declared_cash_cents")
    if mtg["status"] != "CLOSED":
        raise C.err("ERR_MEETING_NOT_CLOSED", "Meeting is not CLOSED")
    if mtg["settlement_status"] == "RECONCILED":
        raise C.err("ERR_ALREADY_RECONCILED", "Meeting is already RECONCILED")
    caller = request.headers.get("X-User-ID")
    if caller == mtg.get("closer_user_id"):
        raise C.err("ERR_SEGREGATION_OF_DUTIES",
                    "Reconciler may not be the meeting's closer")
    posted_total = sum(t["amount_cents"]
                       for t in C.STORE["repayment_transactions"].values()
                       if t["center_meeting_id"] == mid and t["status"] == "POSTED")
    if declared == posted_total:
        mtg["settlement_status"] = "RECONCILED"
        mtg["declared_cash_cents"] = declared
        C.touch(mtg)
        return ok(C.ser_meeting(mtg))
    mtg["settlement_status"] = "DISPUTED"
    mtg["declared_cash_cents"] = declared
    C.touch(mtg)
    raise C.err("ERR_RECONCILIATION_MISMATCH",
                "declared_cash_cents does not match the posted total")


# ---------------------------------------------------------------------------
# Repayment transactions
# ---------------------------------------------------------------------------


@bp.get("/repayment-transactions")
def list_transactions():
    items = list(C.STORE["repayment_transactions"].values())
    meeting_id = request.args.get("center_meeting_id")
    loan_id = request.args.get("loan_id")
    member_id = request.args.get("member_id")
    if meeting_id is not None:
        items = [t for t in items if t["center_meeting_id"] == meeting_id]
    if loan_id is not None:
        items = [t for t in items if t["loan_id"] == loan_id]
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    return list_response(items, C.ser_txn)


@bp.get("/repayment-transactions/<tid>")
def get_transaction(tid):
    t = C.lookup("repayment_transactions", tid, "ERR_TRANSACTION_NOT_FOUND")
    return ok(C.ser_txn(t))


@bp.post("/repayment-transactions/<tid>/void")
def void_transaction(tid):
    t = C.lookup("repayment_transactions", tid, "ERR_TRANSACTION_NOT_FOUND")
    if t["status"] != "POSTED":
        raise C.err("ERR_TXN_NOT_POSTED", "Transaction is not POSTED")
    mtg = C.STORE["center_meetings"].get(t["center_meeting_id"])
    if mtg is not None and mtg["settlement_status"] == "RECONCILED":
        raise C.err("ERR_MEETING_ALREADY_RECONCILED",
                    "Void is blocked once the meeting is RECONCILED")
    t["status"] = "VOIDED"
    C.touch(t)
    loan = C.STORE["loans"].get(t["loan_id"])
    if loan is not None:
        loan["principal_outstanding_cents"] += t["principal_applied_cents"]
        loan["installments_on_time"] -= t.get("on_time_applied", 0)
        loan["installment_applied_total"] = loan.get("installment_applied_total", 0) \
            - t.get("units_applied", 0)
        loan["arrears_retired"] = loan.get("arrears_retired", 0) \
            - t.get("arrears_retired_delta", 0)
        C.touch(loan)
    member = C.STORE["members"].get(t["member_id"])
    account = C.member_savings_account(t["member_id"])
    if account is not None:
        C.recompute_savings(account)
        C.touch(account)
    return ok(C.ser_txn(t))
