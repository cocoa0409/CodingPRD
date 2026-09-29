"""Cascade discipline (PRD 2.9): seat pool, hold release, suspension spread."""
import calc
import lookups
from envelope import touch
from store import add_days, store

AUTO_DELIST_REASON = "AUTO_DELISTED_SURVEILLANCE_SCORE"
AUTO_PROBATION_REASON = "AUTO_PROBATION_SURVEILLANCE_SCORE"
COMMITTED_STATUSES = ("AWARD_OFFERED", "ACCEPTED")
OPEN_APPROVAL_STATUSES = ("PENDING_REVIEW", "APPROVED")
# A request whose money track already reached PAID, REVERSED or CANCELLED is
# not "open": its hold is gone, so a cascade must not void it or release a
# hold twice (PRD 2.9 -- compensation is exact; PRD 3.7 -- PAID is not voidable).
OPEN_SETTLEMENT_STATUSES = ("UNSETTLED", "CLAIMED")
LIVE_CASE_STATUSES = ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED",
                      "CLAWBACK_ISSUED", "UNDER_APPEAL")


def is_open_request(pr):
    return (pr["approval_status"] in OPEN_APPROVAL_STATUSES
            and pr["settlement_status"] in OPEN_SETTLEMENT_STATUSES)


# --- seat pool (PRD 2.10) ---------------------------------------------------
def recount_seats(py, bump=True):
    committed = sum(
        1 for a in store.applications.values()
        if a["program_year_id"] == py["id"] and a["status"] in COMMITTED_STATUSES
    )
    available = py["total_seats"] - committed
    if available < 0:
        available = 0
    changed = (py["seats_committed"] != committed
               or py["seats_available"] != available)
    py["seats_committed"] = committed
    py["seats_available"] = available
    if changed and bump:
        touch(py)
    return py


def offer_deadline(py):
    return add_days(store.now(), py["acceptance_deadline_days"])


def promote_from_waitlist(py):
    """Hand a freed seat to the lowest waitlist_position.  Returns the id or None."""
    recount_seats(py)
    if py["seats_available"] < 1:
        return None
    waiting = [a for a in store.applications.values()
               if a["program_year_id"] == py["id"] and a["status"] == "WAITLISTED"]
    if not waiting:
        return None
    waiting.sort(key=lambda a: (a["waitlist_position"] is None,
                                a["waitlist_position"] or 0, a["created_at"]))
    head = waiting[0]
    head["status"] = "AWARD_OFFERED"
    head["waitlist_position"] = None
    head["acceptance_deadline_at"] = offer_deadline(py)
    touch(head)
    recount_seats(py)
    return head["id"]


# --- hold release / voiding (PRD 2.11, 3.7) --------------------------------
def release_hold(acct, request):
    acct["encumbered_cents"] -= request["amount_cents"]
    acct["balance_cents"] += request["amount_cents"]
    touch(acct)


def void_open_requests_of_account(acct, release_holds):
    voided = []
    for pr in lookups.purchase_requests_of_account(acct["id"]):
        if not is_open_request(pr):
            continue
        was_approved = pr["approval_status"] == "APPROVED"
        pr["approval_status"] = "VOID"
        pr["settlement_status"] = "CANCELLED"
        touch(pr)
        if was_approved and release_holds:
            release_hold(acct, pr)
        voided.append(pr["id"])
    return voided


def suspend_account(acct, reason):
    acct["status"] = "SUSPENDED"
    acct["suspension_reason"] = reason
    touch(acct)
    void_open_requests_of_account(acct, release_holds=True)
    return acct


def close_account(acct):
    """Withdrawal closure: balances are frozen as they stand, no money moves."""
    acct["status"] = "CLOSED"
    touch(acct)
    void_open_requests_of_account(acct, release_holds=False)
    return acct


def account_has_live_case(account_id, ignore_case_id=None):
    for case in lookups.misuse_cases_of_account(account_id):
        if ignore_case_id is not None and case["id"] == ignore_case_id:
            continue
        if case["status"] in LIVE_CASE_STATUSES:
            return True
    return False


# --- provider sanctions (PRD 3.6) -----------------------------------------
def delist_provider(prov, reason):
    prov["status"] = "DELISTED"
    prov["sanction_reason"] = reason
    touch(prov)
    for pr in lookups.purchase_requests_of_provider(prov["id"]):
        if not is_open_request(pr):
            continue
        was_approved = pr["approval_status"] == "APPROVED"
        pr["approval_status"] = "VOID"
        pr["settlement_status"] = "CANCELLED"
        touch(pr)
        if was_approved:
            acct = store.accounts.get(pr["account_id"])
            if acct is not None:
                release_hold(acct, pr)
    return prov


def recompute_surveillance(prov):
    prov["surveillance_score"] = calc.surveillance_decayed_score(
        prov["screening_score"], prov.get("screened_at"), store.now(),
        prov["substantiated_case_count"],
    )
    touch(prov)
    score = prov["surveillance_score"]
    if score >= 90:
        if prov["status"] in ("APPROVED", "PROBATION"):
            delist_provider(prov, AUTO_DELIST_REASON)
    elif score >= 75:
        if prov["status"] == "APPROVED":
            prov["status"] = "PROBATION"
            prov["sanction_reason"] = AUTO_PROBATION_REASON
            touch(prov)
    return prov
