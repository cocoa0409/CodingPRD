"""Server-owned derived state: inventory census, E911 posture, fee ledger and
the account's ported-number count (PRD 2.11)."""
import store
from common import bump
from util import hours

NUMBER_PARK_HOURS = 168
E911_PROMPT_GRACE_HOURS = 72


# ---------------------------------------------------------------------------
# Inventory census (PRD 3.2)
# ---------------------------------------------------------------------------
def recompute_census(block):
    """Recompute the five counters and increment the block's version by 1."""
    rows = [n for n in store.phone_numbers.values() if n["block_id"] == block["id"]]
    block["minted_count"] = len(rows)
    block["available_count"] = len([n for n in rows if n["status"] == "AVAILABLE"])
    block["reserved_count"] = len([n for n in rows if n["status"] == "RESERVED"])
    block["assigned_count"] = len([n for n in rows if n["status"] == "ASSIGNED"])
    block["parked_count"] = len([n for n in rows if n["status"] == "PARKED"])
    bump(block)
    return block


def park_number(number):
    """Drive a number into PARKED with the cooling-off period."""
    number["status"] = "PARKED"
    number["parked_until"] = store.now() + hours(NUMBER_PARK_HOURS)
    number["park_cycle_count"] = number["park_cycle_count"] + 1
    bump(number)


def other_held_reservation_exists(number_id, excluding_id):
    for r in store.number_reservations.values():
        if r["id"] == excluding_id:
            continue
        if r["number_id"] == number_id and r["status"] == "HELD":
            return True
    return False


# ---------------------------------------------------------------------------
# E911 compliance posture (PRD 3.7)
# ---------------------------------------------------------------------------
def current_registration(device_id):
    for r in store.e911_registrations.values():
        if r["device_id"] == device_id and r["superseded_at"] is None:
            return r
    return None


def _classify(device):
    reg = current_registration(device["id"])
    if reg is not None and reg["verification_status"] == "VERIFIED":
        return "OK"
    if reg is not None and reg["verification_status"] == "STALE":
        return "STALE"
    if reg is not None and reg["verification_status"] == "REJECTED":
        return "HARD_FAIL"
    # No current registration, or a current one still UNVERIFIED.
    if store.now() >= device["registration_prompt_deadline"]:
        return "MISSING_OVERDUE"
    return "MISSING_GRACE"


def compute_posture(account_id):
    population = [
        d for d in store.devices.values()
        if d["account_id"] == account_id and d["assigned_number_id"] is not None
    ]
    classes = [_classify(d) for d in population]
    if any(c in ("HARD_FAIL", "MISSING_OVERDUE") for c in classes):
        return "BLOCKED"
    if any(c in ("STALE", "MISSING_GRACE") for c in classes):
        return "AT_RISK"
    return "COMPLIANT"


def _account_devices(account_id):
    return store.all_of({d["id"]: d for d in store.devices.values()
                         if d["account_id"] == account_id})


def _sweep(account_id, posture):
    if posture == "AT_RISK":
        for d in _account_devices(account_id):
            if d["nomadic"] and d["calling_status"] == "UNRESTRICTED":
                d["calling_status"] = "INTL_BLOCKED"
                bump(d)
    elif posture == "COMPLIANT":
        for d in _account_devices(account_id):
            if d["calling_status"] == "INTL_BLOCKED" and d["fraud_block_count"] == 0:
                d["calling_status"] = "UNRESTRICTED"
                bump(d)
    elif posture == "BLOCKED":
        for d in _account_devices(account_id):
            if d["calling_status"] != "FULL_BLOCKED":
                d["calling_status"] = "FULL_BLOCKED"
                bump(d)


def recompute_posture(account):
    if account is None:
        return
    posture = compute_posture(account["id"])
    if posture != account["e911_compliance_posture"]:
        account["e911_compliance_posture"] = posture
        bump(account)
        _sweep(account["id"], posture)


# ---------------------------------------------------------------------------
# Fee ledger (PRD 3.9)
# ---------------------------------------------------------------------------
def recompute_jurisdiction_ledger(jurisdiction):
    if jurisdiction is None:
        return
    rows = [a for a in store.fee_assessments.values()
            if a["jurisdiction_id"] == jurisdiction["id"]]
    pending = sum(a["amount_cents"] for a in rows if a["status"] == "ASSESSED")
    remitted = sum(a["amount_cents"] for a in rows if a["status"] == "REMITTED")
    if pending != jurisdiction["pending_fee_cents"] or remitted != jurisdiction["remitted_fee_cents"]:
        jurisdiction["pending_fee_cents"] = pending
        jurisdiction["remitted_fee_cents"] = remitted
        bump(jurisdiction)


def recompute_account_liability(account):
    if account is None:
        return
    total = sum(a["amount_cents"] for a in store.fee_assessments.values()
                if a["account_id"] == account["id"] and a["status"] in ("ASSESSED", "REMITTED"))
    if total != account["fee_liability_cents"]:
        account["fee_liability_cents"] = total
        bump(account)


def recompute_ledger(jurisdiction, account_ids):
    recompute_jurisdiction_ledger(jurisdiction)
    for account_id in account_ids:
        recompute_account_liability(store.accounts.get(account_id))


# ---------------------------------------------------------------------------
# Ported number count (PRD 3.6)
# ---------------------------------------------------------------------------
def recompute_ported_number_count(account):
    if account is None:
        return
    total = 0
    for pr in store.port_requests.values():
        if pr["account_id"] == account["id"] and pr["status"] == "COMPLETED":
            total += len(pr["requested_numbers"])
    if total != account["ported_number_count"]:
        account["ported_number_count"] = total
        bump(account)
