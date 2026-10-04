"""Core domain services: row factories, serialization, program posture,
alert dismissal and the shared cascade helpers used by the route modules.
"""

from decimal import Decimal

import calc
import db
import errors
import timeutil

# --- entity names ------------------------------------------------------------
BANK_SPONSOR = "BankSponsor"
PROGRAM = "Program"
BRAND_PARTNER = "BrandPartner"
RETAILER_AGREEMENT = "RetailerAgreement"
RELOAD_LOCATION = "ReloadLocation"
CARD_ACCOUNT = "CardAccount"
LOAD_TRANSACTION = "LoadTransaction"
AML_ALERT = "AmlAlert"
DISPUTE_CASE = "DisputeCase"
LOSS_ALLOCATION = "LossAllocation"
SETTLEMENT_BATCH = "SettlementBatch"
FLOAT_WINDOW = "FloatWindow"

DATETIME_FIELDS = {
    BANK_SPONSOR: ("regulator_exam_due_at",),
    PROGRAM: ("oversight_review_due_at", "last_posture_review_at"),
    BRAND_PARTNER: (),
    RETAILER_AGREEMENT: (),
    RELOAD_LOCATION: (),
    CARD_ACCOUNT: ("frozen_at",),
    LOAD_TRANSACTION: ("funded_at", "reversed_at"),
    AML_ALERT: ("window_start_at", "window_end_at"),
    DISPUTE_CASE: ("retailer_response_due_at",),
    LOSS_ALLOCATION: ("posted_at",),
    SETTLEMENT_BATCH: ("period_start_at", "period_end_at", "settled_at"),
    FLOAT_WINDOW: ("window_start_at", "window_end_at"),
}

# --- common fields -----------------------------------------------------------
def common_fields():
    stamp = timeutil.now_iso()
    return {
        "id": db.new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


def touch(row):
    """A mutation, including a derived-field-only recompute, refreshes
    updated_at and increments version."""
    row["updated_at"] = timeutil.now_iso()
    row["version"] = int(row.get("version", 1)) + 1


def public(entity, row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if key in DATETIME_FIELDS.get(entity, ()):
            out[key] = timeutil.iso_instant(value)
        else:
            out[key] = value
    return out


def public_list(entity, rows):
    return [public(entity, r) for r in rows]


# --- lookups ------------------------------------------------------------------
def fetch(store, rid, label="resource"):
    row = store.get(rid)
    if row is None:
        raise errors.entity_not_found("No %s with id %r." % (label, rid))
    return row


def get_bank(bid):
    return fetch(db.bank_sponsors, bid, "BankSponsor")


def get_program(pid):
    return fetch(db.programs, pid, "Program")


def get_brand(bid):
    return fetch(db.brand_partners, bid, "BrandPartner")


def get_agreement(aid):
    return fetch(db.retailer_agreements, aid, "RetailerAgreement")


def get_location(lid):
    return fetch(db.reload_locations, lid, "ReloadLocation")


def get_account(aid):
    return fetch(db.card_accounts, aid, "CardAccount")


def get_load(lid):
    return fetch(db.load_transactions, lid, "LoadTransaction")


def get_alert(aid):
    return fetch(db.aml_alerts, aid, "AmlAlert")


def get_dispute(did):
    return fetch(db.dispute_cases, did, "DisputeCase")


def get_allocation(aid):
    return fetch(db.loss_allocations, aid, "LossAllocation")


def get_batch(bid):
    return fetch(db.settlement_batches, bid, "SettlementBatch")


def get_float_window(fid):
    return fetch(db.float_windows, fid, "FloatWindow")


def ref(store, rid, label="resource"):
    """Resolve an identifier supplied in a request body.

    A body reference that does not resolve is ERR_REFERENCED_RESOURCE_NOT_FOUND
    (404), distinct from a path identifier's ERR_ENTITY_NOT_FOUND.
    """
    row = store.get(rid)
    if row is None:
        raise errors.referenced_not_found("No %s with id %r." % (label, rid))
    return row


def ref_bank(bid):
    return ref(db.bank_sponsors, bid, "BankSponsor")


def ref_program(pid):
    return ref(db.programs, pid, "Program")


def ref_brand(bid):
    return ref(db.brand_partners, bid, "BrandPartner")


def ref_agreement(aid):
    return ref(db.retailer_agreements, aid, "RetailerAgreement")


def ref_location(lid):
    return ref(db.reload_locations, lid, "ReloadLocation")


def ref_account(aid):
    return ref(db.card_accounts, aid, "CardAccount")


def ref_load(lid):
    return ref(db.load_transactions, lid, "LoadTransaction")


def ref_dispute(did):
    return ref(db.dispute_cases, did, "DisputeCase")


def program_of_agreement(agreement):
    return get_program(agreement["program_id"])


def program_of_brand(brand):
    return get_program(brand["program_id"])


def agreement_of_location(location):
    return get_agreement(location["retailer_agreement_id"])


def program_of_location(location):
    return program_of_agreement(agreement_of_location(location))


def program_of_account(account):
    return get_program(account["program_id"])


def program_of_load(load):
    return program_of_location(get_location(load["reload_location_id"]))


def loads_of(store, **filters):
    rows = [r for r in db.ordered(store.values())]
    for key, value in filters.items():
        if value is None or value == "":
            continue
        rows = [r for r in rows if r.get(key) == value]
    return rows


# --- program posture gating ---------------------------------------------------
def programme_frozen(program):
    return program["compliance_posture"] == "FROZEN"


def guard_not_frozen(program):
    if programme_frozen(program):
        raise errors.program_frozen(
            "Program %s has compliance_posture FROZEN." % program["id"]
        )


def guard_not_restricted(program):
    if program["compliance_posture"] == "RESTRICTED":
        raise errors.program_restricted(
            "Program %s has compliance_posture RESTRICTED." % program["id"]
        )


def guard_not_frozen_or_restricted(program):
    guard_not_frozen(program)
    guard_not_restricted(program)


# --- effective account hold ---------------------------------------------------
def applied_hold_status(account):
    """A program whose posture is FROZEN has already cascaded every account of
    the program to FROZEN; the stored dimension is therefore reported as FROZEN
    while the program stays frozen."""
    program = db.programs.get(account["program_id"])
    if program is not None and program["compliance_posture"] == "FROZEN":
        return "FROZEN"
    return account["compliance_hold_status"]


# --- rollover -----------------------------------------------------------------
def _dec(value):
    """Money fields carry whole cents or 2-dp half-up shares; keep exactness."""
    return Decimal(str(value))


def money_add(a, b):
    """Add two money values, rendering the result as a 2-dp JSON number."""
    return calc.num(_dec(a) + _dec(b))


def money_sub(a, b):
    return calc.num(_dec(a) - _dec(b))


def rollover_location(location):
    """Reset the location's daily counters at a logical-day rollover."""
    current = timeutil.current_epoch_index()
    if location.get("last_epoch_index") != current:
        location["daily_accepted_cents"] = 0
        location["daily_txn_count"] = 0
        location["last_epoch_index"] = current


# --- window recomputation -----------------------------------------------------
def account_loads(account):
    return [
        l
        for l in db.ordered(db.load_transactions.values())
        if l["card_account_id"] == account["id"]
    ]


def location_loads(location):
    return [
        l
        for l in db.ordered(db.load_transactions.values())
        if l["reload_location_id"] == location["id"]
    ]


def recompute_account_window(account):
    """Trailing-24h variant: per-load admission control and structuring."""
    now = timeutil.now()
    loads = account_loads(account)
    count, cents, breached = calc.velocity_trip(loads, now)
    s_count, s_total, is_structuring = calc.structuring_trip(loads, now)
    account["window_load_count"] = count
    account["window_load_cents"] = cents
    account["structuring_txn_count"] = s_count
    account["is_structuring"] = is_structuring
    account["_structuring_total_cents"] = s_total
    account["_structuring_total_cents"] = s_total


def recompute_location(location):
    """The location's daily counters are the epoch-day variant: posted totals of
    the current logical day's FUNDED/SETTLED loads, reset at rollover."""
    loads = location_loads(location)
    qualifying = [
        l
        for l in loads
        if l["load_status"] in ("FUNDED", "SETTLED")
        and l.get("epoch_index") == timeutil.current_epoch_index()
    ]
    count = len(qualifying)
    cents = sum((_dec(l["posted_total_cents"]) for l in qualifying), Decimal(0))
    location["daily_txn_count"] = count
    location["daily_accepted_cents"] = calc.num(cents)
    location["last_epoch_index"] = timeutil.current_epoch_index()
    location["is_velocity_breached"] = calc.velocity_alert_predicate(count, cents)
    location["aml_velocity_score"] = calc.num(
        Decimal(100)
        * min(
            Decimal(count) / Decimal(calc.VELOCITY_TXN_LIMIT),
            cents / Decimal(calc.VELOCITY_AMOUNT_LIMIT_CENTS),
        )
    )


def refresh_account(account):
    """Recompute the clock-derived window fields for reporting.

    The trailing 24h window moves with every read and nothing is ever reset, so
    the reported counters are recomputed at read time.  This is not a mutation:
    version and updated_at are left untouched.
    """
    recompute_account_window(account)
    return account


def refresh_location(location):
    recompute_location(location)
    return location


def refresh_program(program):
    recompute_program(program)
    return program


def effective_per_transaction_limit(location):
    limit = agreement_of_location(location)["per_transaction_limit_cents"]
    if location["location_status"] == "RESTRICTED":
        return int(limit) // 2
    return int(limit)


# --- alert helpers ------------------------------------------------------------
def alerts_of_account(account_id):
    return [
        a
        for a in db.ordered(db.aml_alerts.values())
        if a["card_account_id"] == account_id
    ]


def has_non_terminal_alert(account_id):
    return any(a["alert_status"] in ("OPEN", "UNDER_REVIEW") for a in alerts_of_account(account_id))


def has_unresolved_confirmed_alert(account_id):
    return any(a["alert_status"] == "CONFIRMED" for a in alerts_of_account(account_id))


def open_alert_load_ids(account, alert_type=None):
    now = timeutil.now()
    qualifying = calc.velocity_qualifiers(account_loads(account), now)
    if alert_type == "STRUCTURING":
        return [l["id"] for l in calc.structuring_qualifiers(account_loads(account), now)]
    return [l["id"] for l in qualifying]


def severity_for(count, cents):
    ratio = max(
        Decimal(count) / Decimal(calc.VELOCITY_TXN_LIMIT),
        Decimal(cents) / Decimal(calc.VELOCITY_AMOUNT_LIMIT_CENTS),
    )
    if ratio >= Decimal(1):
        return "HIGH"
    if ratio >= Decimal("0.5"):
        return "MEDIUM"
    return "LOW"


def build_alert(program, account, alert_type, window_start_at, window_end_at,
                raised_by_analyst_id, resolution_note=None):
    now = timeutil.now()
    loads = account_loads(account)
    qualifying = calc.velocity_qualifiers(loads, now)
    s_count, s_total, _ = calc.structuring_trip(loads, now)
    observed_count = len(qualifying)
    observed_total = sum(int(l["principal_cents"]) for l in qualifying)
    if alert_type == "STRUCTURING":
        linked = [l["id"] for l in calc.structuring_qualifiers(loads, now)]
    else:
        linked = [l["id"] for l in qualifying]

    row = common_fields()
    row.update(
        {
            "program_id": program["id"],
            "card_account_id": account["id"],
            "alert_type": alert_type,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "observed_txn_count": observed_count,
            "observed_total_cents": observed_total,
            "structuring_hit_count": s_count,
            "severity": severity_for(observed_count, observed_total),
            "alert_status": "OPEN",
            "raised_by_analyst_id": raised_by_analyst_id,
            "assigned_analyst_id": None,
            "confirmed_by_analyst_id": None,
            "linked_load_ids": linked,
            "resolution_note": resolution_note,
        }
    )
    db.register(db.aml_alerts, row)
    return row


def dismiss_stale_alerts(account):
    """The system dismisses OPEN alerts whose predicate the account no longer
    satisfies."""
    dismissed = 0
    for alert in alerts_of_account(account["id"]):
        if alert["alert_status"] != "OPEN":
            continue
        if alert["alert_type"] == "STRUCTURING":
            if not account["is_structuring"]:
                alert["alert_status"] = "DISMISSED"
                touch(alert)
                dismissed += 1
        elif alert["alert_type"] == "VELOCITY":
            if not calc.velocity_alert_predicate(
                account["window_load_count"], account["window_load_cents"]
            ):
                alert["alert_status"] = "DISMISSED"
                touch(alert)
                dismissed += 1
    return dismissed


def maybe_raise_velocity_alert(program, account):
    """Idempotent: an account never accumulates a second OPEN VELOCITY alert."""
    if not calc.velocity_alert_predicate(account["window_load_count"], account["window_load_cents"]):
        return None
    for alert in alerts_of_account(account["id"]):
        if alert["alert_type"] == "VELOCITY" and alert["alert_status"] == "OPEN":
            return None
    now = timeutil.now()
    from datetime import timedelta

    return build_alert(
        program,
        account,
        "VELOCITY",
        now - timedelta(hours=24),
        now,
        raised_by_analyst_id="system",
    )


# --- program recomputation ----------------------------------------------------
def recompute_program(program):
    """Recompute every derived program field.

    This deliberately does not touch the row: a plain recompute is not by
    itself a mutation.  Callers that changed the program (including callers
    whose only change is a derived counter) must call touch(program) so the
    version advances exactly once per mutating request.
    """
    alerts = [
        a for a in db.aml_alerts.values() if a["program_id"] == program["id"]
    ]
    program["open_aml_alert_count"] = sum(
        1 for a in alerts if a["alert_status"] in ("OPEN", "UNDER_REVIEW")
    )
    confirmed = [a for a in alerts if a["alert_status"] == "CONFIRMED"]
    brands = [b for b in db.brand_partners.values() if b["program_id"] == program["id"]]
    program["suspended_brand_count"] = sum(
        1 for b in brands if b["partner_status"] == "SUSPENDED"
    )
    program["posture_breach_count"] = len(confirmed) + sum(
        1
        for b in brands
        if b["partner_status"] == "SUSPENDED" and b["suspension_source"] == "COMPLIANCE"
    )

    due = program.get("oversight_review_due_at")
    program["is_oversight_overdue"] = due is not None and timeutil.now() > due

    lam = calc.lambda_for(program["is_oversight_overdue"], False)
    program["posture_score"] = calc.posture_score(program["posture_breach_count"], lam)

    allocations = [
        a
        for a in db.loss_allocations.values()
        if a["program_id"] == program["id"]
        and a["allocation_status"] in ("POSTED", "RECOVERED")
    ]
    program["allocated_loss_total_cents"] = sum(
        int(a["total_loss_cents"]) for a in allocations
    )

    covered = {a["load_transaction_id"] for a in allocations}
    unallocated = 0
    for load in db.load_transactions.values():
        if load["load_status"] != "REVERSED":
            continue
        if load["reversal_reason"] != "AML_CONFIRMED":
            continue
        if load["id"] in covered:
            continue
        if program_of_load(load)["id"] != program["id"]:
            continue
        unallocated += int(load["principal_cents"])
    program["unallocated_confirmed_loss_cents"] = unallocated
    return program


def recompute_sponsor(sponsor):
    count = sum(
        1 for p in db.programs.values() if p["sponsor_bank_id"] == sponsor["id"]
    )
    sponsor["active_program_count"] = count
    sponsor["is_capacity_exhausted"] = count >= int(sponsor["sponsorship_capacity_programs"])
    return sponsor


# --- account ledger recomputation ---------------------------------------------
def recompute_account_ledger(account):
    balance = calc.balance_of(account["ledger_posted_cents"], account["ledger_reversed_cents"])
    account["balance_cents"] = balance
    account["funding_status"] = calc.funding_status_of(
        account["ledger_posted_cents"], balance
    )


# --- load reversal ------------------------------------------------------------
def reverse_load(load, reason, finalize=True, unwind_agreement=True):
    """The money-unwinding half of a reversal (hops shared by every caller).

    When `finalize` is false the enclosing cascade is responsible for
    recomputing and touching the program once at its end.

    When `unwind_agreement` is false the agreement's accrual and float are left
    untouched: the clawback reversal adjusts each affected account's balance and
    ledger only, because §3.8 compensates the agreement explicitly afterwards
    (float_position_cents decreases by the batch's float_retained_cents and
    accrual_pending_cents is restored by the accrued_retailer_share_cents).
    """
    account = get_account(load["card_account_id"])
    location = get_location(load["reload_location_id"])
    agreement = agreement_of_location(location)
    program = get_program(agreement["program_id"])

    load["load_status"] = "REVERSED"
    load["reversal_reason"] = reason
    load["reversed_at"] = timeutil.now()
    touch(load)

    account["balance_cents"] = max(0, int(account["balance_cents"]) - int(load["principal_cents"]))
    account["ledger_reversed_cents"] = int(account["ledger_reversed_cents"]) + int(load["principal_cents"])
    recompute_account_window(account)
    account["funding_status"] = calc.funding_status_of(
        account["ledger_posted_cents"], account["balance_cents"]
    )
    touch(account)

    location["daily_accepted_cents"] = money_sub(
        location["daily_accepted_cents"], load["posted_total_cents"]
    )
    location["daily_txn_count"] = int(location["daily_txn_count"]) - 1
    recompute_location(location)
    touch(location)

    if unwind_agreement:
        agreement["accrual_pending_cents"] = calc.num(
            _dec(agreement["accrual_pending_cents"]) - _dec(load["retailer_fee_share_cents"])
        )
        agreement["float_position_cents"] = money_sub(
            agreement["float_position_cents"], load["posted_total_cents"]
        )
        touch(agreement)

    dismiss_stale_alerts(account)
    if finalize:
        recompute_program(program)
        touch(program)
    return account, location, agreement, program


def recover_allocations_for(load_ids):
    recovered = []
    for allocation in db.loss_allocations.values():
        if allocation["allocation_status"] == "POSTED" and allocation["load_transaction_id"] in load_ids:
            allocation["allocation_status"] = "RECOVERED"
            touch(allocation)
            recovered.append(allocation)
    return recovered


def allocations_covering(load_id):
    return [
        a
        for a in db.loss_allocations.values()
        if a["load_transaction_id"] == load_id
        and a["allocation_status"] in ("POSTED", "RECOVERED")
    ]