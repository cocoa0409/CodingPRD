"""The four decision policies (SCAFFOLD decision_policies).

No selector may consult an entity id / UUID ordering as a ranking input.
"""

from db import db, parse_iso, MID_TIER_DAYS, FREE_EXTENSION_DAYS
from errors import fail
from services import common


def _created_at(row):
    return parse_iso(row.get("created_at"))


def rate_lock_application_selector(contract):
    """SELECTOR-01: prefer QUALIFIED over EXPIRED, then earliest created_at."""
    pool = [
        app
        for app in common.applications_of_contract(contract["id"])
        if app.get("application_status") in ("QUALIFIED", "EXPIRED")
    ]
    if not pool:
        fail(
            "ERR_NO_QUALIFIED_APPLICATION",
            "no LoanApplication in QUALIFIED or EXPIRED status exists for this contract",
        )
    rank = {"QUALIFIED": 0, "EXPIRED": 1}
    pool.sort(
        key=lambda app: (
            rank.get(app.get("application_status"), 9),
            _created_at(app),
            app.get("application_number") or "",
        )
    )
    return pool[0]


def forward_commitment_selector(contract):
    """SELECTOR-02: same community, OPEN, units_available >= 1, window contains clock."""
    community = common.community_of(contract)
    if community is None:
        fail("ERR_FORWARD_COMMITMENT_EXHAUSTED", "contract has no community")
    clock_iso = db.clock
    pool = []
    for commitment in db.forward_commitments.values():
        if commitment.get("community_id") != community["id"]:
            continue
        if commitment.get("commitment_status") != "OPEN":
            continue
        if int(commitment.get("units_available") or 0) < 1:
            continue
        if not _within_window(commitment, clock_iso):
            continue
        pool.append(commitment)
    if not pool:
        fail(
            "ERR_FORWARD_COMMITMENT_EXHAUSTED",
            "no OPEN forward commitment with available units covers the current clock",
        )
    pool.sort(
        key=lambda c: (
            int(c.get("committed_rate_bps") or 0),
            parse_iso(c.get("commitment_start_iso")),
            _created_at(c),
            c.get("commitment_code") or "",
        )
    )
    return pool[0]


def _within_window(commitment, clock_iso):
    start = parse_iso(commitment.get("commitment_start_iso"))
    end = parse_iso(commitment.get("commitment_end_iso"))
    now = parse_iso(clock_iso)
    if start is None or end is None or now is None:
        return False
    return start <= now <= end


def deposit_statute_class_selector(contract):
    """SELECTOR-03: cancellation_reason together with Buyer.state_code."""
    reason = contract.get("cancellation_reason")
    buyer = db.buyers.get(contract.get("buyer_id"))
    state = (buyer or {}).get("state_code")
    if reason == "BUYER_DEFAULT":
        if state in ("FL", "TX"):
            return "FULL_FORFEITURE"
        if state in ("CA", "NY", "IL"):
            return "PARTIAL_FORFEITURE"
        fail(
            "ERR_FORFEITURE_STATUTE_UNDETERMINED",
            "no deposit-forfeiture statute applies in the buyer's jurisdiction",
        )
    if reason in ("CONSTRUCTION_DELAY", "RATE_SHOCK", "FINANCING_DENIED", None):
        return "RESTITUTION_REQUIRED"
    fail(
        "ERR_FORFEITURE_STATUTE_UNDETERMINED",
        "cancellation reason carries no mapped deposit statute",
    )


def incentive_bucket_priority_selector():
    """SELECTOR-04: fixed priority order PRICE_REDUCTION > CLOSING_COSTS > RATE_BUYDOWN."""
    from db import PRIORITY_ORDER
    return list(PRIORITY_ORDER)