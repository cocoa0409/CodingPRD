"""The pinned seven-step operations run (PRD 3.5).

Nothing in this network drifts forward on its own: every lapse, expiry, match,
completion, listing and probation decision happens here, inside one request,
against MatchingRun.as_of_utc.
"""

from datetime import timedelta

import calc
from store import (db, touch, parse_date, parse_instant, format_instant,
                   MATCH_HOLD_HOURS, GETAWAY_SWEEP_WITHIN_DAYS, STAY_NIGHTS)
from services import deposits as deposit_service
from services import ledger
from services import requests as request_service
from services import resorts as resort_service

COUNTERS = [
    "lapsed_member_count",
    "expired_deposit_count",
    "probation_resort_count",
    "expired_request_count",
    "denied_request_count",
    "matched_count",
    "waitlisted_count",
    "completed_confirmation_count",
    "getaway_listed_count",
]


def next_sequence():
    highest = 0
    for row in db.matching_runs.values():
        if row["run_sequence"] > highest:
            highest = row["run_sequence"]
    return highest + 1


def _by_created(rows):
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def execute(note):
    as_of = db.now()
    run = db.new_row({
        "run_sequence": next_sequence(),
        "as_of_utc": format_instant(as_of),
        "note": note,
        "status": "PENDING",
    })
    for name in COUNTERS:
        run[name] = 0
    db.matching_runs[run["id"]] = run

    _step_0_dues_lapse(run, as_of)
    expired_resort_ids = _step_1_deposit_expiry(run, as_of)
    _step_2_request_sweep(run, as_of)
    _step_3_matching_pass(run, as_of)
    _step_4_confirmation_completion(run, as_of)
    _step_5_getaway_listing(run, as_of)
    _step_6_resort_probation(run, as_of, expired_resort_ids)

    run["status"] = "COMPLETED"
    return run


# ---------------------------------------------------------------------------
# step 0 -- dues lapse
# ---------------------------------------------------------------------------
def _step_0_dues_lapse(run, as_of):
    today = as_of.date()
    for member in _by_created(list(db.members.values())):
        if member["enrollment_status"] != "ACTIVE":
            continue
        paid_through = parse_date(member["dues_paid_through"]) if member["dues_paid_through"] else None
        if paid_through is None or paid_through < today:
            member["enrollment_status"] = "LAPSED"
            touch(member)
            run["lapsed_member_count"] += 1


# ---------------------------------------------------------------------------
# step 1 -- deposit expiry
# ---------------------------------------------------------------------------
def _step_1_deposit_expiry(run, as_of):
    rows = [d for d in db.deposits.values() if d["deposit_status"] == "BANKED"]
    rows.sort(key=lambda d: (d["expires_at"], d["created_at"], d["_seq"]))
    touched_resorts = []
    for deposit in rows:
        if parse_instant(deposit["expires_at"]) > as_of:
            continue
        resort = db.resorts[deposit["resort_id"]]
        owner = db.members[deposit["member_id"]]
        deposit_service.expire_deposit(deposit, resort, owner)
        run["expired_deposit_count"] += 1
        if resort["id"] not in touched_resorts:
            touched_resorts.append(resort["id"])
    return touched_resorts


# ---------------------------------------------------------------------------
# step 2 -- request expiry and denial
# ---------------------------------------------------------------------------
def _step_2_request_sweep(run, as_of):
    today = as_of.date()
    for request in _by_created(list(db.exchange_requests.values())):
        member = db.members[request["member_id"]]
        left = None
        if (request["status"] == "MATCHED" and request["matched_hold_expires_at"]
                and parse_instant(request["matched_hold_expires_at"]) <= as_of):
            request_service.release_hold(request)
            request["status"] = "EXPIRED"
            left = "EXPIRED"
        elif (request["status"] in ("SUBMITTED", "WAITLISTED")
              and parse_date(request["window_end_date"]) < today):
            request["status"] = "EXPIRED"
            left = "EXPIRED"
        elif (request["status"] == "WAITLISTED" and request["funding_mode"] == "DEPOSIT_FIRST"
              and request["deposit_id"]):
            funding = db.deposits.get(request["deposit_id"])
            if funding is not None and funding["deposit_status"] not in ("BANKED", "RESERVED"):
                request["status"] = "DENIED"
                left = "DENIED"
        if left is None:
            continue
        touch(request)
        request_service.refund_charge(request, member)
        request_service.sync_active_count(member)
        if left == "EXPIRED":
            run["expired_request_count"] += 1
        else:
            run["denied_request_count"] += 1


# ---------------------------------------------------------------------------
# step 3 -- the matching pass
# ---------------------------------------------------------------------------
def _score(request, as_of):
    member = db.members[request["member_id"]]
    tier = db.membership_tiers[member["tier_id"]]
    paid_through = parse_date(member["dues_paid_through"]) if member["dues_paid_through"] else None
    return calc.priority_score(
        tier["tier_code"], request["funding_mode"],
        parse_date(member["created_at"][:10]), as_of.date(),
        request["decline_count"], paid_through,
        parse_date(request["window_start_date"]))


def _candidates(request, as_of):
    member = db.members[request["member_id"]]
    tier = db.membership_tiers[member["tier_id"]]
    window_start = parse_date(request["window_start_date"])
    window_end = parse_date(request["window_end_date"])
    pool = []
    for deposit in db.deposits.values():
        if deposit["resort_id"] != request["requested_resort_id"]:
            continue
        if deposit["unit_size"] != request["requested_unit_size"]:
            continue
        if deposit["deposit_status"] != "BANKED":
            continue
        if deposit["rental_status"] != "NOT_LISTED":
            continue
        if deposit["member_id"] == request["member_id"]:
            continue
        if parse_instant(deposit["expires_at"]) <= as_of:
            continue
        check_in = parse_date(deposit["check_in_date"])
        if check_in < window_start or check_in > window_end:
            continue
        if (check_in - as_of.date()).days > tier["priority_window_days"]:
            continue
        resort = db.resorts[deposit["resort_id"]]
        settlement = deposit_service.settlement_value(deposit, resort, as_of)
        if settlement > request["power_budget"]:
            continue
        pool.append((deposit, settlement))
    pool.sort(key=lambda pair: (-pair[1], pair[0]["check_in_date"],
                               pair[0]["created_at"], pair[0]["_seq"]))
    return pool


def _step_3_matching_pass(run, as_of):
    live = [r for r in db.exchange_requests.values() if r["status"] in ("SUBMITTED", "WAITLISTED")]
    for request in _by_created(live):
        score = _score(request, as_of)
        if request["priority_score"] != score:
            request["priority_score"] = score
            touch(request)
    live.sort(key=lambda r: (-r["priority_score"], r["created_at"], r["_seq"]))
    for request in live:
        pool = _candidates(request, as_of)
        member = db.members[request["member_id"]]
        if pool:
            deposit = pool[0][0]
            resort = db.resorts[deposit["resort_id"]]
            deposit_service.freeze_settlement(deposit, resort, as_of)
            deposit["deposit_status"] = "RESERVED"
            touch(deposit)
            request["status"] = "MATCHED"
            request["matched_deposit_id"] = deposit["id"]
            request["matched_hold_expires_at"] = format_instant(
                as_of + timedelta(hours=MATCH_HOLD_HOURS))
            touch(request)
            run["matched_count"] += 1
        else:
            if request["status"] != "WAITLISTED":
                request["status"] = "WAITLISTED"
            if request["waitlisted_at"] is None:
                request["waitlisted_at"] = format_instant(as_of)
            touch(request)
            run["waitlisted_count"] += 1
        request_service.sync_active_count(member)


# ---------------------------------------------------------------------------
# step 4 -- confirmation completion
# ---------------------------------------------------------------------------
def _step_4_confirmation_completion(run, as_of):
    rows = [c for c in db.confirmations.values() if c["status"] == "CONFIRMED"]
    rows.sort(key=lambda c: (c["awarded_check_in_date"], c["created_at"], c["_seq"]))
    today = as_of.date()
    for confirmation in rows:
        stay_end = parse_date(confirmation["awarded_check_in_date"]) + timedelta(days=STAY_NIGHTS)
        if stay_end <= today:
            confirmation["status"] = "COMPLETED"
            touch(confirmation)
            run["completed_confirmation_count"] += 1


# ---------------------------------------------------------------------------
# step 5 -- getaway listing
# ---------------------------------------------------------------------------
def _step_5_getaway_listing(run, as_of):
    rows = [d for d in db.deposits.values()
            if d["deposit_status"] == "BANKED" and d["rental_status"] == "NOT_LISTED"]
    rows.sort(key=lambda d: (d["expires_at"], d["created_at"], d["_seq"]))
    today = as_of.date()
    for deposit in rows:
        expiry_day = parse_instant(deposit["expires_at"]).date()
        if (expiry_day - today).days > GETAWAY_SWEEP_WITHIN_DAYS:
            continue
        resort = db.resorts[deposit["resort_id"]]
        owner = db.members[deposit["member_id"]]
        deposit_service.list_on_getaway(deposit, resort, owner, as_of, run["id"])
        run["getaway_listed_count"] += 1


# ---------------------------------------------------------------------------
# step 6 -- resort probation
# ---------------------------------------------------------------------------
def _step_6_resort_probation(run, as_of, expired_resort_ids):
    rows = _by_created([db.resorts[rid] for rid in expired_resort_ids if rid in db.resorts])
    for resort in rows:
        if resort["affiliation_status"] != "ACTIVE":
            continue
        if resort_service.shortfall_by_stay_year(resort) >= 1:
            resort["affiliation_status"] = "PROBATION"
            touch(resort)
            run["probation_resort_count"] += 1
