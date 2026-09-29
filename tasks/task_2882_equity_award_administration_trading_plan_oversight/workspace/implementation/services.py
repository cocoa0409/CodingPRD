"""Shared lookups, gates and cascades used by more than one route module."""

import calc
import clock
import store
from errors import ApiError

INSIDER_REPORTABLE = ("SECTION_16_OFFICER", "DESIGNATED_INSIDER")


# --- lookups ----------------------------------------------------------------

def find(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def plan_or_404(plan_id):
    return find(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")


def participant_or_404(participant_id):
    return find(store.participants, participant_id, "ERR_PARTICIPANT_NOT_FOUND")


def grant_or_404(grant_id):
    return find(store.grants, grant_id, "ERR_GRANT_NOT_FOUND")


def tranche_or_404(tranche_id):
    return find(store.tranches, tranche_id, "ERR_TRANCHE_NOT_FOUND")


def cycle_or_404(cycle_id):
    return find(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")


def event_or_404(event_id):
    return find(store.events, event_id, "ERR_VESTING_EVENT_NOT_FOUND")


def window_or_404(window_id):
    return find(store.windows, window_id, "ERR_WINDOW_NOT_FOUND")


def preclearance_or_404(request_id):
    return find(store.preclearances, request_id, "ERR_PRECLEARANCE_NOT_FOUND")


def trading_plan_or_404(plan_id):
    return find(store.trading_plans, plan_id, "ERR_TRADING_PLAN_NOT_FOUND")


def report_or_404(report_id):
    return find(store.reports, report_id, "ERR_REPORT_NOT_FOUND")


def authority_or_404(authority_id):
    return find(store.authorities, authority_id, "ERR_AUTHORITY_NOT_FOUND")


def tranches_of(grant_id):
    rows = [t for t in store.tranches.values() if t["grant_id"] == grant_id]
    return sorted(rows, key=lambda t: (t["tranche_index"], t["_seq"]))


def grants_of_participant(participant_id):
    rows = [g for g in store.grants.values() if g["participant_id"] == participant_id]
    return store.sort_default(rows)


def events_of_tranche(tranche_id):
    rows = [e for e in store.events.values() if e["tranche_id"] == tranche_id]
    return store.sort_default(rows)


def participant_of_tranche(tranche):
    return store.participants[store.grants[tranche["grant_id"]]["participant_id"]]


def participant_id_of_event(event):
    tranche = store.tranches[event["tranche_id"]]
    return store.grants[tranche["grant_id"]]["participant_id"]


def plan_of_grant(grant):
    return store.plans[grant["plan_id"]]


# --- plan gates -------------------------------------------------------------

def require_plan_active(plan):
    """PRD 2.10: a FROZEN or TERMINATED plan refuses new commitments."""
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_FROZEN")


def require_plan_not_terminated(plan):
    if plan["status"] == "TERMINATED":
        raise ApiError("ERR_PLAN_FROZEN")


# --- plan recomputation -----------------------------------------------------

def recompute_reserve(plan):
    plan["available_reserve_shares"] = calc.available_reserve(
        plan["total_authorized_shares"],
        plan["shares_committed_cumulative"],
        plan["shares_returned_cumulative"],
    )
    plan["reserve_posture"] = calc.reserve_posture(
        plan["available_reserve_shares"],
        plan["low_reserve_threshold_bps"],
        plan["total_authorized_shares"],
    )


def recompute_burn_rates(plan):
    plan["gross_burn_rate_bps"] = calc.gross_burn_rate_bps(
        plan["fiscal_year_gross_granted_shares"], plan["common_shares_outstanding"]
    )
    plan["net_burn_rate_bps"] = calc.net_burn_rate_bps(
        plan["fiscal_year_gross_granted_shares"],
        plan["fiscal_year_returned_shares"],
        plan["common_shares_outstanding"],
    )


def weighted_for(grant, plan, rows=None):
    rows = tranches_of(grant["id"]) if rows is None else rows
    committed = calc.committed_shares(rows)
    return calc.fungible_weighted_shares(
        grant["award_type"], committed, plan["fungible_ratio_full_value_bps"]
    )


def recompute_grant_shares(grant, plan):
    """Rewrites weighted_reserve_shares / outstanding_shares; returns the weight delta."""
    rows = tranches_of(grant["id"])
    previous = grant["weighted_reserve_shares"]
    grant["weighted_reserve_shares"] = weighted_for(grant, plan, rows)
    grant["outstanding_shares"] = calc.outstanding_shares(rows)
    return grant["weighted_reserve_shares"] - previous


def apply_weight_delta(plan, delta):
    if delta > 0:
        plan["shares_committed_cumulative"] += delta
        plan["fiscal_year_gross_granted_shares"] += delta
    elif delta < 0:
        plan["shares_returned_cumulative"] += -delta
        plan["fiscal_year_returned_shares"] += -delta


def forfeiture_grant_status(grant, rows):
    """PRD 3.8 hop 2 status resolution, shared with the cancelled-cycle cascade."""
    if grant["status"] not in ("GRANTED", "PARTIALLY_FORFEITED"):
        return None
    if grant["outstanding_shares"] > 0:
        return "PARTIALLY_FORFEITED"
    if not any(t["status"] == "SETTLED" for t in rows):
        return "FORFEITED"
    return None


# --- vesting event helpers --------------------------------------------------

def delete_tax_rows(event):
    for row_id in [
        r["id"] for r in store.tax_allocations.values() if r["vesting_event_id"] == event["id"]
    ]:
        del store.tax_allocations[row_id]


def new_vesting_event(tranche, grant, fmv_per_share_cents, withholding_method,
                      vested_instant):
    row = store.base_row()
    row.update({
        "tranche_id": tranche["id"],
        "vest_date": clock.fmt_date(vested_instant.date()),
        "gross_shares": tranche["shares"],
        "fmv_per_share_cents": fmv_per_share_cents,
        "taxable_income_cents": tranche["shares"] * fmv_per_share_cents,
        "sourcing_start_date": grant["grant_date"],
        "total_workdays": 0,
        "total_tax_cents": 0,
        "blended_rate_bps": 0,
        "withholding_method": withholding_method,
        "shares_withheld": 0,
        "shares_sold": 0,
        "net_shares_delivered": 0,
        "residual_cash_cents": 0,
        "cash_due_cents": 0,
        "tax_status": "PENDING_ALLOCATION",
        "settlement_status": "PENDING_TAX",
        "reversal_reason": None,
    })
    store.events[row["id"]] = row
    return row


def reverse_pending_tax_events(tranche, reason):
    """Clawback support: settlements still awaiting tax treatment are reversed."""
    for event in events_of_tranche(tranche["id"]):
        if event["settlement_status"] == "PENDING_TAX":
            event["settlement_status"] = "REVERSED"
            event["reversal_reason"] = reason
            event["tax_status"] = "PENDING_ALLOCATION"
            event["total_tax_cents"] = 0
            event["total_workdays"] = 0
            event["blended_rate_bps"] = 0
            event["shares_withheld"] = 0
            event["shares_sold"] = 0
            event["residual_cash_cents"] = 0
            event["cash_due_cents"] = 0
            event["net_shares_delivered"] = event["gross_shares"]
            delete_tax_rows(event)
            store.touch(event)


def tranche_has_settled_event(tranche_id):
    return any(
        e["settlement_status"] == "SETTLED" for e in store.events.values()
        if e["tranche_id"] == tranche_id
    )


# --- section 16 reports -----------------------------------------------------

def maybe_create_report(participant, source_type, source_id, transaction_at, shares):
    status = participant["insider_status"]
    if status not in INSIDER_REPORTABLE:
        return None
    row = store.base_row()
    row.update({
        "participant_id": participant["id"],
        "source_type": source_type,
        "source_id": source_id,
        "transaction_at": clock.fmt_instant(transaction_at),
        "shares": shares,
        "form_type": "FORM_4" if status == "SECTION_16_OFFICER" else "FORM_5",
        "due_at": clock.fmt_instant(calc.report_due_at(transaction_at)),
        "filed_at": None,
        "status": "PENDING",
    })
    store.reports[row["id"]] = row
    return row


def delete_pending_reports(source_type, source_id):
    for row_id in [
        r["id"] for r in store.reports.values()
        if r["source_type"] == source_type and r["source_id"] == source_id
        and r["status"] == "PENDING"
    ]:
        del store.reports[row_id]


# --- trading window cascades ------------------------------------------------

def requests_of_window(window_id):
    rows = [r for r in store.preclearances.values() if r["window_id"] == window_id]
    return store.sort_default(rows)


def recompute_window_cumulative(window):
    total = 0
    for row in requests_of_window(window["id"]):
        if row["status"] in ("APPROVED", "EXECUTED"):
            total += row["requested_shares"]
    window["approved_shares_cumulative"] = total


def window_is_tradeable(window):
    if window["status"] != "OPEN":
        return False
    instant = clock.now()
    return clock.parse_instant(window["open_at"]) <= instant < clock.parse_instant(
        window["close_at"]
    )


def suspend_window_cascade(window, reason):
    for row in requests_of_window(window["id"]):
        if row["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED"):
            row["status"] = "VOID"
            store.touch(row)
    recompute_window_cumulative(window)


def close_window_cascade(window):
    for row in requests_of_window(window["id"]):
        if row["status"] == "APPROVED":
            row["status"] = "EXPIRED"
            store.touch(row)
        elif row["status"] in ("SUBMITTED", "INFO_REQUESTED"):
            row["status"] = "VOID"
            store.touch(row)
    recompute_window_cumulative(window)
