"""RateLock endpoints: creation, void, extend and relock."""

from flask import Blueprint

from db import db, parse_iso, MAX_RELOCKS
from errors import fail
from response import ok
from checks import (
    authenticate, body, require_fields, int_field, get_application, get_rate_lock,
    get_commitment, check_application_version, check_buyer_ownership,
)
from services import common, calc, selectors, cascades
from services import lock_flows, contract_flows

bp = Blueprint("rate_locks", __name__)

READ_ROLES = [
    "PlatformAdmin",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
    "Buyer",
]


def _contract_of(application):
    contract = db.contracts.get(application.get("contract_id"))
    if contract is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the application has no parent contract")
    return contract


def _active_locks(application_id):
    return [
        l
        for l in lock_flows.locks_of_application(application_id)
        if l.get("lock_status") == "ACTIVE"
    ]


def _resolve_commitment(payload, contract, application):
    """SELECTOR-02 when the caller did not name a commitment."""
    named = payload.get("commitment_id")
    if named is not None:
        commitment = get_commitment(named)
        if commitment.get("community_id") != (common.community_of(contract) or {}).get("id"):
            fail("ERR_RESOURCE_NOT_FOUND", "the commitment belongs to another community")
        return commitment, True
    return selectors.forward_commitment_selector(contract), False


def _window_overlap_ok(commitment, start_iso, end_iso, units_available):
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    overlapping = 0
    for lock in db.rate_locks.values():
        if lock.get("commitment_id") != commitment["id"]:
            continue
        if lock.get("lock_status") != "ACTIVE":
            continue
        other_start = parse_iso(lock.get("lock_start_iso"))
        other_end = parse_iso(lock.get("lock_expires_iso"))
        if other_start is None or other_end is None:
            continue
        if start <= other_end and other_start <= end:
            overlapping += 1
    return overlapping < int(units_available)


@bp.post("/housing/loan-applications/<application_id>/rate-locks")
def create_rate_lock(application_id):
    authenticate(["MortgageBanker"])
    application = get_application(application_id)
    payload = body()
    contract = _contract_of(application)

    # Priority 4 (state): the application must sit in QUAISFIED or EXPIRED.
    if application.get("application_status") not in ("QUALIFIED", "EXPIRED"):
        pool = [
            a
            for a in common.applications_of_contract(contract["id"])
            if a.get("application_status") in ("QUALIFIED", "EXPIRED")
        ]
        if not pool:
            fail(
                "ERR_NO_QUALIFIED_APPLICATION",
                "no LoanApplication in QUALIFIED or EXPIRED status exists for this contract",
            )
        fail("ERR_INVALID_STATE", "the application is not in a lockable state")

    commitment, named = _resolve_commitment(payload, contract, application)

    lock_rate_bps = payload.get("lock_rate_bps")
    lock_days = payload.get("lock_days")
    home_site = db.home_sites.get(contract.get("home_site_id"))

    # Priority 12: the commitment window must contain the current clock.
    start_iso = commitment.get("commitment_start_iso")
    end_iso = commitment.get("commitment_end_iso")
    if not (parse_iso(start_iso) <= parse_iso(db.clock) <= parse_iso(end_iso)):
        fail("ERR_COMMITMENT_WINDOW_CLOSED", "the commitment window does not cover the clock")

    # Priority 13: the advertised below-market rate is a time-limited offer.
    if (
        home_site is not None
        and lock_rate_bps is not None
        and lock_rate_bps == home_site.get("advertised_rate_bps")
    ):
        if parse_iso(db.clock) > parse_iso(home_site.get("advertised_rate_expires_iso")):
            fail(
                "ERR_ADVERTISED_RATE_EXPIRED",
                "the advertised below-market rate may no longer be quoted",
            )

    # Priority 17: the new closed interval must fit the commitment unit pool.
    common.recompute_commitment_counters(commitment)
    if lock_days is not None and isinstance(lock_days, int) and not isinstance(lock_days, bool):
        from db import add_days_from_clock

        proposed_end = add_days_from_clock(lock_days)
        if not _window_overlap_ok(
            commitment, db.clock, proposed_end, commitment.get("units_available") or 0
        ):
            fail(
                "ERR_LOCK_WINDOW_OVERLAP",
                "too many concurrent ACTIVE locks for the commitment's available units",
            )

    # Priority 18: the selected commitment must have at least one unit available.
    if named and commitment.get("commitment_status") != "OPEN":
        fail("ERR_FORWARD_COMMITMENT_EXHAUSTED", "the named commitment is not OPEN")
    if int(commitment.get("units_available") or 0) < 1:
        fail("ERR_FORWARD_COMMITMENT_EXHAUSTED", "the commitment has no unit available")

    # Priority 22: at most one ACTIVE lock per application.
    if _active_locks(application_id):
        fail("ERR_DUPLICATE_ACTIVE_LOCK", "the application already holds an ACTIVE lock")

    # Priority 23: optimistic concurrency on the application.
    check_application_version(payload, application)

    # Priority 24 / 25: required fields, then types and bounds.
    require_fields(payload, ["lock_rate_bps", "lock_days", "expected_application_version"])
    rate_value = int_field(payload, "lock_rate_bps", minimum=0, maximum=2000)
    days_value = int_field(payload, "lock_days", minimum=15, maximum=360)

    row = lock_flows.create_lock(application, commitment, rate_value, days_value)
    return ok(common.dump(row), 201)


@bp.get("/housing/rate-locks/<rate_lock_id>")
def get_rate_lock_detail(rate_lock_id):
    authenticate(READ_ROLES)
    lock = get_rate_lock(rate_lock_id)
    application = db.loan_applications.get(lock.get("application_id"))
    contract = db.contracts.get(application.get("contract_id")) if application else None
    check_buyer_ownership({"buyer_id": contract.get("buyer_id") if contract else None}, "buyer_id")
    return ok(common.dump(lock), 200)


@bp.post("/housing/rate-locks/<rate_lock_id>/void")
def void_rate_lock(rate_lock_id):
    authenticate(["MortgageBanker"])
    lock = get_rate_lock(rate_lock_id)
    # Priority 14: the lock must be ACTIVE and unexpired.
    if lock.get("lock_status") != "ACTIVE":
        fail("ERR_RATE_LOCK_EXPIRED", "the lock is not ACTIVE")
    if parse_iso(db.clock) > parse_iso(lock.get("lock_expires_iso")):
        fail("ERR_RATE_LOCK_EXPIRED", "the lock has already expired")
    lock_flows.void_lock(lock)
    return ok(common.dump(lock), 200)


@bp.post("/housing/rate-locks/<rate_lock_id>/extend")
def extend_rate_lock(rate_lock_id):
    authenticate(["MortgageBanker"])
    lock = get_rate_lock(rate_lock_id)
    if lock.get("lock_status") != "ACTIVE":
        fail("ERR_RATE_LOCK_EXPIRED", "the lock is not ACTIVE")
    if parse_iso(db.clock) > parse_iso(lock.get("lock_expires_iso")):
        fail("ERR_RATE_LOCK_EXPIRED", "the lock has already expired")
    payload = body()
    require_fields(payload, ["new_lock_days"])
    new_lock_days = int_field(payload, "new_lock_days", minimum=15, maximum=360)
    lock_flows.extend_lock(lock, new_lock_days)
    return ok(common.dump(lock), 200)


@bp.post("/housing/rate-locks/<rate_lock_id>/relock")
def relock_rate_lock(rate_lock_id):
    authenticate(["MortgageBanker"])
    lock = get_rate_lock(rate_lock_id)
    # Priority 4: only an EXPIRED lock may be revived.
    if lock.get("lock_status") != "EXPIRED":
        fail("ERR_INVALID_STATE", "only an EXPIRED lock may be relocked")
    application = db.loan_applications.get(lock.get("application_id"))
    commitment = db.forward_commitments.get(lock.get("commitment_id"))
    if application is None or commitment is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the lock has no resolvable parent rows")

    # Priority 12: the commitment window must still cover the clock.
    if not (
        parse_iso(commitment.get("commitment_start_iso"))
        <= parse_iso(db.clock)
        <= parse_iso(commitment.get("commitment_end_iso"))
    ):
        fail("ERR_COMMITMENT_WINDOW_CLOSED", "the commitment window does not cover the clock")

    # Priority 15: the relock budget.
    if int(lock.get("relock_count") or 0) >= MAX_RELOCKS:
        fail("ERR_RELOCK_LIMIT_REACHED", "the lock has been relocked the maximum number of times")

    # Priority 22: at most one ACTIVE lock per application.
    if _active_locks(application["id"]):
        fail("ERR_DUPLICATE_ACTIVE_LOCK", "the application already holds an ACTIVE lock")

    # Preconditions.
    if application.get("application_status") != "QUALIFIED":
        fail("ERR_INVALID_STATE", "the application is not QUALIFIED")
    if commitment.get("commitment_status") != "OPEN":
        fail("ERR_INVALID_STATE", "the commitment is not OPEN")
    common.recompute_commitment_counters(commitment)
    if int(commitment.get("units_available") or 0) < 1:
        fail("ERR_INVALID_STATE", "the commitment has no unit available")

    lock_flows.relock_rate_lock(lock)
    rl_contract = db.contracts.get(application.get("contract_id"))
    if rl_contract is not None:
        for disc in common.disclosures_of_contract(rl_contract["id"]):
            if disc.get("disclosure_status") == "ISSUED":
                disc["disclosure_status"] = "ACKNOWLEDGED"
                common.touch(disc)
        buyer = cascades.buyer_of_contract(rl_contract)
        cascades.refresh_buyer(buyer)
    return ok(common.dump(lock), 200)