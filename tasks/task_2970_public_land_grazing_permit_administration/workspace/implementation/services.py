"""Side effects, cascades and shared state transitions (PRD 2.11, 3.5, 3.6, 3.10)."""

from decimal import Decimal

import calc
import constants as K
import derive
import store

ZERO = Decimal("0")


# ------------------------------------------------------------------------ bills


def create_bill(permittee_id, bill_type, money, aoi_id=None,
                trespass_incident_id=None, project_id=None,
                superseded_bill_id=None):
    record = {
        "permittee_id": permittee_id,
        "aoi_id": aoi_id,
        "trespass_incident_id": trespass_incident_id,
        "project_id": project_id,
        "superseded_bill_id": superseded_bill_id,
        "bill_type": bill_type,
        "billed_aums": money["billed_aums"],
        "fee_rate_cents_per_aum": money["fee_rate_cents_per_aum"],
        "base_amount_cents": money["base_amount_cents"],
        "admin_fee_cents": money["admin_fee_cents"],
        "penalty_amount_cents": money["penalty_amount_cents"],
        "total_amount_cents": money["total_amount_cents"],
        "amount_paid_cents": 0,
        "due_date": store.add_days(store.clock_date(),
                                   K.PAYMENT_TERM_DAYS).isoformat(),
        "bill_status": "ISSUED",
        "void_reason": None,
    }
    return store.insert("bills", record)


def adjustment_money(delta_cents):
    return {
        "billed_aums": Decimal("0.00"),
        "fee_rate_cents_per_aum": K.GRAZING_FEE_RATE_CENTS_PER_AUM,
        "base_amount_cents": delta_cents,
        "admin_fee_cents": 0,
        "penalty_amount_cents": 0,
        "total_amount_cents": delta_cents,
    }


def void_bill(bill, void_reason=None):
    """PRD 3.6: the bill is voided and its two conditional effects follow."""
    bill["bill_status"] = "VOIDED"
    if void_reason is not None:
        bill["void_reason"] = void_reason
    store.touch(bill)
    if bill["bill_type"] == "UNAUTHORIZED_USE" and bill["trespass_incident_id"]:
        incident = store.get("trespass_incidents", bill["trespass_incident_id"])
        if incident is not None and incident["incident_status"] == "BILLED":
            incident["incident_status"] = "DETECTED"
            store.touch(incident)
    refresh_account_status(bill["permittee_id"])


def outstanding_use_bill(aoi_id):
    """The instruction's live use bill, if any."""
    found = None
    for bill in store.rows("bills"):
        if bill["aoi_id"] != aoi_id:
            continue
        if bill["bill_type"] not in K.USE_BILL_TYPES:
            continue
        if bill["bill_status"] not in ("ISSUED", "DELINQUENT"):
            continue
        if found is None or bill["_seq"] > found["_seq"]:
            found = bill
    return found


def issue_use_bill(aoi, bill_type, billed_aums, superseded_bill_id=None):
    money = calc.use_bill_money(billed_aums)
    return create_bill(derive.permittee_of_aoi(aoi), bill_type, money,
                       aoi_id=aoi["id"], superseded_bill_id=superseded_bill_id)


def settle_use_bill(aoi, bill_type, billed_aums, create_if_missing=False):
    """PRD 2.11 / 3.6 step five: an unpaid bill is superseded, a partly paid bill
    is left standing and the difference is issued as an adjustment."""
    money = calc.use_bill_money(billed_aums)
    existing = outstanding_use_bill(aoi["id"])
    if existing is None:
        if not create_if_missing or money["total_amount_cents"] == 0:
            return None
        return create_bill(derive.permittee_of_aoi(aoi), bill_type, money,
                           aoi_id=aoi["id"])
    if existing["amount_paid_cents"] == 0:
        void_bill(existing)
        return create_bill(derive.permittee_of_aoi(aoi), bill_type, money,
                           aoi_id=aoi["id"], superseded_bill_id=existing["id"])
    delta = money["total_amount_cents"] - existing["total_amount_cents"]
    if delta == 0:
        return None
    kind = "ADJUSTMENT_DEBIT" if delta > 0 else "ADJUSTMENT_CREDIT"
    return create_bill(existing["permittee_id"], kind, adjustment_money(delta),
                       aoi_id=aoi["id"])


# ------------------------------------------------------------ permittee posture


def refresh_account_status(permittee_id):
    """Hop five of every cascade: re-derive account_status from the live bills."""
    if not permittee_id:
        return
    delinquent = derive.has_delinquent_bill(permittee_id)
    target = "DELINQUENT" if delinquent else "CURRENT"
    for permit in store.rows("permits"):
        if permit["permittee_id"] != permittee_id:
            continue
        if permit["permit_status"] not in ("PENDING_REVIEW", "ISSUED", "SUSPENDED"):
            continue
        if permit["account_status"] != target:
            permit["account_status"] = target
            store.touch(permit)


# --------------------------------------------------------------- non-use counter


def nonuse_run(permit):
    """PRD 3.5: the longest counting run ending at the most recent counting year."""
    by_year = {}
    for aoi in store.rows("aois"):
        if aoi["permit_id"] != permit["id"]:
            continue
        if aoi["aoi_status"] not in ("ISSUED", "USE_REPORTED", "BILLED", "CLOSED"):
            continue
        counts = (aoi["nonuse_aums"] > 0 and aoi["nonuse_reason"]
                  in ("RESOURCE_CONSERVATION", "PERSONAL_CONVENIENCE"))
        by_year[aoi["grazing_year"]] = by_year.get(aoi["grazing_year"], False) or counts
    counting_years = sorted([year for year, counts in by_year.items() if counts])
    if not counting_years:
        run = 0
    else:
        last = counting_years[-1]
        run = 0
        year = last
        while by_year.get(year, False):
            run += 1
            year -= 1
    return run


def recompute_consecutive_nonuse_years(permit):
    run = nonuse_run(permit)
    if permit["consecutive_nonuse_years"] != run:
        permit["consecutive_nonuse_years"] = run
        store.touch(permit)
    return run


# ------------------------------------------------------------ instruction voiding


def void_aoi(aoi, void_reason=None):
    """PRD 3.5: void the instruction, void its unpaid bills, release capacity."""
    aoi["aoi_status"] = "VOIDED"
    if void_reason is not None:
        aoi["void_reason"] = void_reason
    store.touch(aoi)
    for bill in store.rows("bills"):
        if bill["aoi_id"] == aoi["id"] and bill["bill_status"] in ("ISSUED",
                                                                  "DELINQUENT"):
            void_bill(bill)
    permit = store.get("permits", aoi["permit_id"])
    if permit is not None:
        refresh_account_status(permit["permittee_id"])


# ------------------------------------------------------- reduction source ledger


def recompute_stocking_pct(allotment):
    """Hop one of PRD 3.10: the strongest active source, never the sum."""
    orders = [order for order in store.rows("closure_orders")
              if order["allotment_id"] == allotment["id"]
              and order["order_status"] == "ACTIVE"]
    for order in orders:
        if order["order_type"] in K.FULL_CLOSURE_TYPES:
            return Decimal("1.0000")
    strongest = ZERO
    for order in orders:
        strongest = max(strongest, calc.dec(order["reduction_pct"]))
    for decision in store.rows("decisions"):
        if decision["allotment_id"] != allotment["id"]:
            continue
        if decision["decision_type"] != "STOCKING_ADJUSTMENT":
            continue
        if decision["decision_status"] != "EFFECTIVE":
            continue
        if decision["adjustment_pct"] is not None:
            strongest = max(strongest, calc.dec(decision["adjustment_pct"]))
    if strongest > K.MAX_STOCKING_ADJUSTMENT_PCT:
        strongest = K.MAX_STOCKING_ADJUSTMENT_PCT
    return calc.pct4(strongest)


def terminate_projects(allotment):
    """PRD 3.12: closing an allotment terminates its APPROVED projects."""
    for project in store.rows("projects"):
        if project["allotment_id"] == allotment["id"] \
                and project["project_status"] == "APPROVED":
            project["project_status"] = "TERMINATED"
            store.touch(project)


def apply_stocking_pct(allotment, new_pct, bump_version=True, force=False):
    """Hops two through five of PRD 3.10, run as a single pass."""
    new_pct = calc.pct4(new_pct)
    old_pct = calc.pct4(allotment["stocking_adjustment_pct"])
    moved = new_pct != old_pct or force
    allotment["stocking_adjustment_pct"] = new_pct
    old_posture = allotment["allotment_status"]
    allotment["allotment_status"] = calc.posture(new_pct)
    if allotment["allotment_status"] == "CLOSED" and old_posture != "CLOSED":
        terminate_projects(allotment)
    if moved:
        year = store.current_grazing_year()
        touched_permittees = []
        for aoi in derive.aois_of_allotment(allotment["id"]):
            if aoi["grazing_year"] != year:
                continue
            if aoi["aoi_status"] not in ("ISSUED", "USE_REPORTED"):
                continue
            fresh = calc.reauthorized_aums(aoi["authorized_aums_at_issue"], new_pct)
            if fresh != aoi["authorized_aums"]:
                aoi["authorized_aums"] = fresh
                store.touch(aoi)
            settle_use_bill(aoi, "REVISED_USE", derive.billable_aums(aoi))
            permittee_id = derive.permittee_of_aoi(aoi)
            if permittee_id and permittee_id not in touched_permittees:
                touched_permittees.append(permittee_id)
        for permittee_id in touched_permittees:
            refresh_account_status(permittee_id)
    if bump_version:
        store.touch(allotment)


def run_reallocation(allotment, bump_version=True):
    apply_stocking_pct(allotment, recompute_stocking_pct(allotment),
                       bump_version=bump_version)


# --------------------------------------------------------- pasture aggregate


def pasture_scheduled_conflict(pasture, subject_record_id, aoi, window_start,
                               window_end, subject_planned_aums):
    """PRD 3.4 temporal aggregate. Returns True when the pasture would be over
    capacity for the window under evaluation."""
    total = calc.dec(subject_planned_aums)
    for record in store.rows("use_records"):
        if record["pasture_id"] != pasture["id"]:
            continue
        if record["id"] == subject_record_id:
            continue
        other = store.get("aois", record["aoi_id"])
        if other is None or other["grazing_year"] != aoi["grazing_year"]:
            continue
        start = store.parse_instant(record["planned_entry_date"] + "T00:00:00Z")
        end = store.parse_instant(record["planned_exit_date"] + "T00:00:00Z")
        if start.date() < window_end and window_start < end.date():
            total += calc.dec(record["planned_aums"])
    return total > calc.dec(pasture["pasture_aum_capacity"])


# ------------------------------------------------------------- decision cascades


def cascade_decision_effect(decision, allotment):
    """PRD 3.8: the four type-specific cascades. The allotment version bump is
    performed by the caller, once."""
    kind = decision["decision_type"]
    if kind == "STOCKING_ADJUSTMENT":
        apply_stocking_pct(allotment, recompute_stocking_pct(allotment),
                           bump_version=False)
        return
    if kind == "SUSPENSION":
        permit = store.get("permits", decision["permit_id"])
        if permit is not None and permit["permit_status"] == "ISSUED":
            permit["permit_status"] = "SUSPENDED"
            permit["suspension_reason"] = "DECISION"
            store.touch(permit)
        if permit is not None:
            year = store.current_grazing_year()
            for aoi in store.rows("aois"):
                if aoi["permit_id"] == permit["id"] \
                        and aoi["grazing_year"] == year \
                        and aoi["aoi_status"] == "DRAFT":
                    void_aoi(aoi)
        return
    if kind == "CANCELLATION":
        permit = store.get("permits", decision["permit_id"])
        if permit is not None:
            permit["permit_status"] = "CANCELLED"
            permit["suspension_reason"] = None
            store.touch(permit)
            for aoi in store.rows("aois"):
                if aoi["permit_id"] == permit["id"] \
                        and aoi["aoi_status"] in ("DRAFT", "ISSUED"):
                    void_aoi(aoi)
        return
    # ISSUANCE runs no cascade whatsoever.


def cascade_decision_vacatur(decision, allotment):
    """PRD 3.8 four-hop restoration. The caller bumps the allotment version."""
    kind = decision["decision_type"]
    if kind == "STOCKING_ADJUSTMENT":
        restored = decision["pre_decision_adjustment_pct"]
        if restored is None:
            restored = recompute_stocking_pct(allotment)
        apply_stocking_pct(allotment, restored, bump_version=False)
        return
    if kind == "SUSPENSION":
        permit = store.get("permits", decision["permit_id"])
        if permit is not None and permit["permit_status"] == "SUSPENDED":
            permit["permit_status"] = "ISSUED"
            permit["suspension_reason"] = None
            store.touch(permit)
        return
    # A vacated CANCELLATION resurrects nothing; a vacated ISSUANCE unwinds nothing.
