"""Shared domain machinery: coverage, insurance posture, the fee ledger and the
three compound cascades of PRD section 2.10.

Every walk in this module iterates rows in created_at ascending order.
"""

from flask import g

import calc
import clock
import store

# ---------------------------------------------------------------------------
# version discipline: one authority (or carrier, or contract) row is written at
# most once per request, so its `version` advances by exactly one no matter how
# many hops of one cascade touched it.
# ---------------------------------------------------------------------------


def touch(rec):
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        try:
            seen = g._touched = set()
        except RuntimeError:
            return store.touch(rec)
    key = id(rec)
    rec["updated_at"] = clock.now()
    if key not in seen:
        seen.add(key)
        rec["version"] = rec.get("version", 1) + 1
    return rec


# ------------------------------------------------------------------ fee ledger

def ledger_append(carrier, entry_type, amount_cents, docket_ref, memo):
    entry = store.base_record(mutable=False)
    entry.update({
        "carrier_id": carrier["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "docket_ref": docket_ref,
        "memo": memo,
    })
    store.insert(store.LEDGER, entry)
    if entry_type == "FILING_FEE_DEBIT":
        carrier["fees_assessed_total_cents"] += amount_cents
    elif entry_type == "FILING_FEE_REVERSAL_CREDIT":
        carrier["fees_reversed_total_cents"] += abs(amount_cents)
    elif entry_type == "FEE_PAYMENT_CREDIT":
        carrier["fees_paid_total_cents"] += abs(amount_cents)
    carrier["fee_balance_cents"] = (carrier["fees_assessed_total_cents"]
                                    - carrier["fees_reversed_total_cents"]
                                    - carrier["fees_paid_total_cents"])
    touch(carrier)
    return entry


# ------------------------------------------------- process-agent coverage

def agent_covers(agent, state_code):
    if agent.get("blanket_agent"):
        return True
    return state_code in agent.get("coverage_states", [])


def designation_is_current(row, at=None):
    """Closed interval containment at the given instant."""
    if row["status"] != "ACTIVE":
        return False
    moment = clock.now() if at is None else at
    if row["effective_from"] > moment:
        return False
    if row["effective_to"] is not None and row["effective_to"] < moment:
        return False
    return True


def covered_states(authority):
    covered = set()
    for row in store.designations_of_authority(authority["id"]):
        if designation_is_current(row):
            covered.add(row["state_code"])
    return covered


def recompute_coverage(authority):
    required = list(authority.get("required_jurisdictions") or [])
    covered = covered_states(authority)
    count = len([s for s in required if s in covered])
    authority["designated_state_count"] = count
    authority["designation_coverage_complete"] = (count == len(required))
    touch(authority)
    return authority


# --------------------------------------------------------- insurance posture

BOND_TYPES = ("SURETY_BOND", "TRUST_FUND")


def required_slots(authority):
    """(slot label, accepted filing types, required minimum) triples."""
    slots = []
    if authority["required_bipd_limit_cents"] > 0:
        slots.append(("BIPD", ("BIPD",), authority["required_bipd_limit_cents"]))
    if authority["required_cargo_limit_cents"] > 0:
        slots.append(("CARGO", ("CARGO",), authority["required_cargo_limit_cents"]))
    if authority["required_bond_limit_cents"] > 0:
        slots.append(("BOND", BOND_TYPES, authority["required_bond_limit_cents"]))
    return slots


def required_minimum_for_type(authority, filing_type):
    if filing_type == "BIPD":
        return authority["required_bipd_limit_cents"]
    if filing_type == "CARGO":
        return authority["required_cargo_limit_cents"]
    return authority["required_bond_limit_cents"]


def filing_is_current(filing, at=None):
    """Half-open interval containment: [effective_at, cancellation_effective_at)."""
    if filing["status"] != "ACTIVE":
        return False
    moment = clock.now() if at is None else at
    if filing["effective_at"] > moment:
        return False
    end = filing["cancellation_effective_at"]
    if end is not None and moment >= end:
        return False
    return True


def active_filings(authority_id, types=None):
    rows = []
    for filing in store.filings_of_authority(authority_id):
        if filing["status"] != "ACTIVE":
            continue
        if types is not None and filing["filing_type"] not in types:
            continue
        rows.append(filing)
    return rows


def slot_holder(authority, types, minimum, require_minimum=True):
    """The ACTIVE filing covering the current logical time on this slot."""
    for filing in active_filings(authority["id"], types):
        if not filing_is_current(filing):
            continue
        if require_minimum and filing["coverage_limit_cents"] < minimum:
            continue
        return filing
    return None


def satisfied_slot_count(authority):
    slots = required_slots(authority)
    satisfied = 0
    for _label, types, minimum in slots:
        if slot_holder(authority, types, minimum) is not None:
            satisfied += 1
    return satisfied, len(slots)


def recompute_insurance_status(authority):
    """Recompute the coverage dimension from scratch. Returns (old, new)."""
    old = authority["insurance_status"]
    satisfied, total = satisfied_slot_count(authority)
    if total == 0 or satisfied == total:
        new = "FILED"
    elif old in ("FILED", "LAPSED"):
        new = "LAPSED"
    elif satisfied > 0:
        new = "PARTIAL"
    else:
        new = "NOT_FILED"
    if new != old:
        authority["insurance_status"] = new
        touch(authority)
    return old, new


# ----------------------------------------------------- revocation proceedings

def open_proceeding(authority, reason):
    now = clock.now()
    rec = store.base_record()
    rec.update({
        "authority_id": authority["id"],
        "reason": reason,
        "status": "NOTICE_ISSUED",
        "notice_issued_at": now,
        "cure_deadline_at": calc.cure_deadline(now),
        "cured_at": None,
        "revoked_at": None,
        "replacement_policy_number": None,
    })
    return store.insert(store.PROCEEDINGS, rec)


def has_open_proceeding(authority):
    for proceeding in store.proceedings_of_authority(authority["id"]):
        if proceeding["status"] == "NOTICE_ISSUED":
            return True
    return False


# ---------------------------------------------------------------- cascades

def suspend(authority, reason):
    """PRD 2.10 Suspension. Returns the number of contracts hop two moved."""
    now = clock.now()
    authority["authority_status"] = "SUSPENDED"
    authority["suspended_at"] = now
    authority["suspension_reason"] = reason

    moved = 0
    for contract in store.contracts_of_authority(authority["id"]):
        if contract["status"] != "ACTIVE":
            continue
        contract["status"] = "SUSPENDED_BY_AUTHORITY"
        contract["suspended_at"] = now
        contract["resumed_at"] = None
        embargoed = 0
        for shipment in store.shipments_of_contract(contract["id"]):
            if shipment["status"] not in ("TENDERED", "IN_TRANSIT"):
                continue
            shipment["pre_embargo_status"] = shipment["status"]
            shipment["status"] = "EMBARGOED"
            shipment["embargoed_at"] = now
            touch(shipment)
            embargoed += 1
        contract["embargoed_shipment_count"] = embargoed
        contract["disruption_liability_cents"] = calc.suspension_estimate(contract)
        contract["disruption_liability_variant"] = "SUSPENSION_ESTIMATE"
        touch(contract)
        moved += 1

    authority["active_contract_count"] -= moved
    authority["suspended_contract_count"] += moved
    touch(authority)

    carrier = store.CARRIERS.get(authority["carrier_id"])
    if carrier is not None:
        carrier["active_authority_count"] -= 1
        touch(carrier)
    return moved


def restore(authority):
    """PRD 2.10 Restoration -- the exact compensating inverse of suspend()."""
    now = clock.now()
    authority["authority_status"] = "ACTIVE"
    authority["suspension_reason"] = "NONE"
    authority["suspended_at"] = None

    moved = 0
    for contract in store.contracts_of_authority(authority["id"]):
        if contract["status"] != "SUSPENDED_BY_AUTHORITY":
            continue
        contract["status"] = "ACTIVE"
        contract["resumed_at"] = now
        contract["disruption_liability_cents"] = calc.settled_actual(contract)
        contract["disruption_liability_variant"] = "SETTLED_ACTUAL"
        for shipment in store.shipments_of_contract(contract["id"]):
            if shipment["status"] != "EMBARGOED":
                continue
            shipment["status"] = shipment["pre_embargo_status"]
            shipment["embargo_released_at"] = now
            shipment["embargo_days_accrued"] += clock.ceil_days(shipment["embargoed_at"], now)
            shipment["pre_embargo_status"] = "NONE"
            touch(shipment)
        touch(contract)
        moved += 1

    authority["suspended_contract_count"] -= moved
    authority["active_contract_count"] += moved
    touch(authority)

    carrier = store.CARRIERS.get(authority["carrier_id"])
    if carrier is not None:
        carrier["active_authority_count"] += 1
        touch(carrier)
    return moved


def try_restore(authority):
    """Restore only when all three guards of PRD 3.4 hold."""
    if authority["authority_status"] != "SUSPENDED":
        return 0
    if not authority["designation_coverage_complete"]:
        return 0
    if authority["insurance_status"] != "FILED":
        return 0
    if has_open_proceeding(authority):
        return 0
    return restore(authority)


def _terminate_downstream(authority, now):
    moved = 0
    for contract in store.contracts_of_authority(authority["id"]):
        if contract["status"] not in ("ACTIVE", "SUSPENDED_BY_AUTHORITY"):
            continue
        contract["status"] = "TERMINATED"
        contract["terminated_at"] = now
        for shipment in store.shipments_of_contract(contract["id"]):
            if shipment["status"] not in ("TENDERED", "IN_TRANSIT", "EMBARGOED"):
                continue
            was_embargoed = shipment["status"] == "EMBARGOED"
            shipment["status"] = "DIVERTED"
            shipment["diverted_at"] = now
            if was_embargoed:
                shipment["embargo_released_at"] = now
                shipment["embargo_days_accrued"] += clock.ceil_days(shipment["embargoed_at"], now)
            touch(shipment)
        touch(contract)
        moved += 1
    authority["active_contract_count"] = 0
    authority["suspended_contract_count"] = 0
    touch(authority)
    return moved


def terminate(authority):
    """PRD 2.10 Termination -- the irreversible cascade (REVOKED)."""
    now = clock.now()
    authority["authority_status"] = "REVOKED"
    authority["revoked_at"] = now
    return _terminate_downstream(authority, now)


def rescind(authority):
    """Termination with hop one replaced by a rescission (PRD 2.10, 3.6)."""
    now = clock.now()
    authority["authority_status"] = "RESCINDED"
    authority["rescinded_at"] = now
    moved = _terminate_downstream(authority, now)
    carrier = store.CARRIERS.get(authority["carrier_id"])
    if carrier is not None:
        carrier["active_authority_count"] -= 1
        touch(carrier)
    return moved


# ------------------------------------------------------------ ownership walks

def carrier_of_authority(authority):
    return authority["carrier_id"]


def carrier_of_contract(contract):
    authority = store.AUTHORITIES.get(contract["authority_id"])
    return None if authority is None else authority["carrier_id"]


def carrier_of_shipment(shipment):
    contract = store.CONTRACTS.get(shipment["contract_id"])
    return None if contract is None else carrier_of_contract(contract)
