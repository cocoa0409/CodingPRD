"""Member lifecycle: registration, screening, decisions and wallet (PRD §3.1, §3.2, §3.14)."""

from db import STORE, ordered, paginate
from errors import fail
from middleware import require_owner
from services import lookup
from services.calculations import (WEIGHTS, strike_fee_cents)

KINDS = ("INDIVIDUAL", "STUDENT", "EMPLOYEE")
APPLICATION_STATUSES = ("APPLIED", "SCREENING", "APPROVED", "DECLINED")
DECISIONS = ("NONE", "CLEAR", "REFERRED", "FAILED")


def serialize(member):
    return {k: v for k, v in member.items() if not k.startswith("_")}


def _email_taken(email):
    for m in STORE.members.values():
        if m.get("email") == email:
            return True
    return False


def register(data, fields):
    """POST /car-share/member-registrations (Anonymous) — PRD §3.1."""
    full_name = fields.field(data, "full_name", "string", required=True)
    email = fields.field(data, "email", "string", required=True)
    kind = fields.field(data, "kind", "string", required=True, enum=KINDS)
    anchor = fields.field(data, "last_accident_fee_block", "integer", default=0)

    if _email_taken(email):
        fail("ERR_MEMBER_EMAIL_TAKEN", "A member with this email already exists.")

    member = STORE.create(
        STORE.members,
        full_name=full_name,
        email=email,
        kind=kind,
        application_status="APPLIED",
        screen_result="NONE",
        application_decided_at=None,
        last_accident_fee_block=anchor,
        strikes=0,
        referral_invites=0,
        wallet_credit_cents=0,
        wallet_hold_cents=0,
        violations=[],
        froze_for_incident=None,
        reopened=False,
    )
    return member


def list_members(application_status, kind, limit, offset):
    rows = ordered(STORE.members.values())
    if application_status:
        rows = [r for r in rows if r.get("application_status") == application_status]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    return paginate(rows, limit, offset)


def get(member_id):
    return lookup.member(member_id)


def _latest_report(member_id):
    reports = [r for r in ordered(STORE.driving_reports.values())
               if r.get("member_id") == member_id]
    return reports[-1] if reports else None


def submit_driving_record(member_id, data, fields, identity, role):
    """POST /car-share/members/{id}/driving-record-reports (Member) — PRD §3.1."""
    member = lookup.member(member_id)
    require_owner(identity, role, member["id"])

    license_state = fields.field(data, "license_state", "string", required=True)
    years = fields.field(data, "license_years_held", "integer", required=True)
    decision = fields.field(data, "report_decision", "string", default=None, enum=DECISIONS)

    if member["application_status"] not in ("APPLIED", "SCREENING"):
        fail("ERR_INVALID_STATE",
             "A driving-record report may only be submitted from APPLIED or SCREENING.")

    if _latest_report(member_id) is not None and \
            _latest_report(member_id).get("report_status") == "SUBMITTED":
        fail("ERR_DRIVING_RECORD_PENDING",
             "A driving-record report for this member is still awaiting a decision.")

    report = STORE.create(
        STORE.driving_reports,
        member_id=member_id,
        license_state=license_state,
        license_years_held=years,
        report_status="SUBMITTED",
        report_decision=decision if decision is not None else "NONE",
        screen_completed_at=None,
    )
    member["application_status"] = "SCREENING"
    STORE.bump(member)
    return report


def record_report_decision(report_id, data, fields):
    """POST /car-share/driving-record-reports/{id}/decision (PodOperator)."""
    report = lookup.driving_report(report_id)
    decision = fields.field(data, "report_decision", "string", required=True, enum=DECISIONS)

    member = lookup.member(report["member_id"])
    report["report_decision"] = decision
    report["report_status"] = "RECORDED"
    report["screen_completed_at"] = STORE.now_iso()
    STORE.bump(report)
    member["screen_result"] = decision
    STORE.bump(member)
    return report


def application_decision(member_id, data, fields):
    """POST /car-share/members/{id}/application-decision (PodOperator) — PRD §3.1."""
    member = lookup.member(member_id)
    decision = fields.field(data, "decision", "string", required=True,
                            enum=("APPROVE", "DECLINE"))

    if member["application_status"] != "SCREENING":
        fail("ERR_INVALID_STATE",
             "Only an application in SCREENING may be decided.")

    if member.get("screen_result") in (None, "NONE"):
        fail("ERR_INVALID_STATE",
             "The application's latest report carries no recorded decision yet.")

    if decision == "APPROVE" and member["screen_result"] != "CLEAR":
        fail("ERR_SCREENING_NOT_CLEAR",
             "Only a CLEAR screening outcome permits approval.")

    member["application_decided_at"] = STORE.now_iso()

    if decision == "APPROVE":
        member["application_status"] = "APPROVED"
        if member["kind"] == "INDIVIDUAL":
            create_individual_membership(member)
    else:
        member["application_status"] = "DECLINED"
        for m in STORE.memberships.values():
            if m.get("member_id") == member["id"] and m.get("status") in ("ACTIVE", "SUSPENDED"):
                m["status"] = "CLOSED"
                STORE.bump(m)

    STORE.bump(member)
    return member


def create_individual_membership(member):
    from services.memberships import derive_billing
    billing = derive_billing()
    return STORE.create(
        STORE.memberships,
        account_id=None,
        member_id=member["id"],
        department_code="UNSPONSORED",
        tier="STANDARD",
        primary_flag=True,
        status="ACTIVE",
        status_before_freeze="NONE",
        membership_billing_cents=billing,
        residual_released_cents=0,
    )


def reopen_application(member_id):
    """POST /car-share/members/{id}/reopen-application (PodOperator) — PRD §3.2."""
    member = lookup.member(member_id)

    if member["application_status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED application may be reopened.")

    if member.get("screen_result") in (None, "NONE"):
        fail("ERR_INVALID_STATE", "The latest report carries no recorded decision.")
    if member["screen_result"] != "CLEAR":
        fail("ERR_SCREENING_NOT_CLEAR",
             "A REFERRED or FAILED screening outcome blocks the reopen.")

    if int(member.get("strikes") or 0) != 0:
        fail("ERR_INVALID_STATE", "A member carrying strikes may not be reopened.")

    has_membership = any(m.get("member_id") == member["id"]
                         for m in STORE.memberships.values())
    for r in STORE.reservations.values():
        if r.get("status") == "CANCELLED" or r.get("member_id") != member["id"]:
            continue
        if has_membership:
            fail("ERR_INVALID_STATE",
                 "A membership of this member is referenced by a live reservation.")

    decided_at = member.get("application_decided_at")
    if not decided_at:
        fail("ERR_INVALID_STATE", "The application carries no decision timestamp.")
    from db import parse_ts, fmt_ts
    from datetime import timedelta
    window_close = parse_ts(decided_at) + timedelta(hours=24)
    if not (STORE.now() < window_close):
        fail("ERR_REOPEN_WINDOW_CLOSED",
             "The early-grade revert window has closed.")

    member["application_status"] = "SCREENING"
    for m in STORE.memberships.values():
        if m.get("member_id") == member["id"] and m.get("status") == "ACTIVE":
            m["status"] = "CLOSED"
            STORE.bump(m)
    member["application_decided_at"] = None
    report = _latest_report(member["id"])
    if report is not None:
        report["report_status"] = "SUBMITTED"
        report["report_decision"] = None
        STORE.bump(report)
    STORE.bump(member)
    return member


def wallet_adjustment(member_id, data, fields):
    """POST /car-share/members/{id}/wallet-adjustments (PodOperator) — PRD §3.14."""
    member = lookup.member(member_id)
    amount = fields.field(data, "amount_cents", "integer", required=True)
    fields.field(data, "reason", "string", required=True)

    if amount == 0:
        fail("ERR_WALLET_ADJUSTMENT_INVALID", "A zero wallet adjustment is refused.")
    if amount < 0 and abs(amount) > int(member.get("wallet_credit_cents") or 0):
        fail("ERR_WALLET_ADJUSTMENT_INVALID",
             "A debit may not exceed the member's spendable balance.")

    member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) + amount
    STORE.bump(member)
    return member


# ---- violations and strikes (C8) -------------------------------------------
def record_violation(member, kind):
    """Record a terminal quality/access violation type for the member."""
    if member is None:
        return
    member.setdefault("violations", []).append({
        "type": kind,
        "created_at": STORE.now_iso(),
        "seq": STORE.next_seq(),
    })


def cumulative_load(member):
    """Sum of WEIGHTS over the frozen snapshot: one position per distinct type,
    ordered by that type's first application (PRD §3.7 / scaffold C8)."""
    seen = {}
    for v in member.get("violations", []):
        t = v["type"]
        if t not in seen or (v["created_at"], v["seq"]) < (seen[t]["created_at"], seen[t]["seq"]):
            seen[t] = v
    ordered_types = sorted(seen.items(), key=lambda kv: (kv[1]["created_at"], kv[1]["seq"]))
    return sum(WEIGHTS.get(t, 0) for t, _ in ordered_types)


def recompute_strikes(member):
    load = cumulative_load(member)
    strikes = -(-load // 2)  # ceil(load / 2)
    member["strikes"] = strikes
    STORE.touch(member)
    return strikes, load


def violation_fee_cents(member):
    return strike_fee_cents(int(member.get("strikes") or 0))