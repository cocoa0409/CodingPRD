"""911 fee unit selection, proration and the monthly remittance run (PRD 3.9)."""
import store
import util
from common import bump, new_entity
from errors import ApiError
from services import derive

REMITTANCE_SENTINEL = "system:remittance-run"
BILLABLE_STATUSES = ("VERIFIED", "STALE")


def eligible_registrations(account_id, jurisdiction_id, period_end, effective_cutoff=None):
    """The registrations that bill for a period, read as the world stands now."""
    rows = []
    for reg in store.e911_registrations.values():
        if reg["jurisdiction_id"] != jurisdiction_id or reg["account_id"] != account_id:
            continue
        if reg["verification_status"] not in BILLABLE_STATUSES:
            continue
        if reg["effective_from"] > period_end:
            continue
        if reg["superseded_at"] is not None and reg["superseded_at"] <= period_end:
            continue
        if effective_cutoff is not None and reg["effective_from"] > effective_cutoff:
            continue
        device = store.devices.get(reg["device_id"])
        if device is None or device["assigned_number_id"] is None:
            continue
        rows.append(reg)
    return rows


def _anchor_key(reg):
    return (reg["effective_from"], reg["created_at"], reg["id"])


def build_units(registrations, fee_type):
    """One unit per registration for PER_LINE, per distinct location key otherwise."""
    if fee_type == "PER_LINE":
        anchors = list(registrations)
    else:
        groups = {}
        for reg in registrations:
            groups.setdefault(reg["normalized_location_key"], []).append(reg)
        anchors = [min(members, key=_anchor_key) for members in groups.values()]
    return sorted(anchors, key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]))


def provisional_breakdown(units, monthly_fee_cents, period_start, days_in_month):
    """Per-unit prorated cents, each rounded half up before anything is summed."""
    breakdown = []
    for anchor in units:
        effective = anchor["effective_from"]
        if effective < period_start:
            effective = period_start
        anchor_day = effective.day
        active_days = days_in_month - anchor_day + 1
        breakdown.append(util.round_half_up(monthly_fee_cents * active_days, days_in_month))
    return breakdown


def final_breakdown(units, monthly_fee_cents):
    return [monthly_fee_cents for _ in units]


def new_assessment(account_id, jurisdiction, period_month, variant, breakdown,
                   assessed_by_user_id):
    row = new_entity()
    row.update({
        "account_id": account_id,
        "jurisdiction_id": jurisdiction["id"],
        "period_month": period_month,
        "variant": variant,
        "unit_basis": jurisdiction["fee_type"],
        "billable_units": len(breakdown),
        "unit_fee_breakdown": list(breakdown),
        "amount_cents": sum(breakdown),
        "status": "ASSESSED",
        "assessed_by_user_id": assessed_by_user_id,
        "voided_by_user_id": None,
        "remitted_at": None,
    })
    store.fee_assessments[row["id"]] = row
    return row


def assessments_for(account_id, jurisdiction_id, period_month):
    return [a for a in store.fee_assessments.values()
            if a["account_id"] == account_id
            and a["jurisdiction_id"] == jurisdiction_id
            and a["period_month"] == period_month]


def check_period_closed(jurisdiction, period_month):
    now = store.now()
    if period_month >= util.month_key(now) or now.day < jurisdiction["remit_day_of_month"]:
        raise ApiError("ERR_REMITTANCE_PERIOD_NOT_CLOSED",
                       "The period is not closed for filing yet.")


def run_remittance(jurisdiction, period_month):
    """Void the provisional rows, write and remit a FINAL row per affected account."""
    year, month = util.parse_period(period_month)
    period_start, period_end, days_in_month = util.period_bounds(year, month)
    touched = []

    for row in store.all_of(store.fee_assessments):
        if (row["jurisdiction_id"] == jurisdiction["id"]
                and row["period_month"] == period_month
                and row["variant"] == "PROVISIONAL"
                and row["status"] == "ASSESSED"):
            row["status"] = "VOIDED"
            row["voided_by_user_id"] = REMITTANCE_SENTINEL
            bump(row)
            if row["account_id"] not in touched:
                touched.append(row["account_id"])

    for account in store.all_of(store.accounts):
        existing = assessments_for(account["id"], jurisdiction["id"], period_month)
        if any(a["status"] == "REMITTED" for a in existing):
            continue
        registrations = eligible_registrations(account["id"], jurisdiction["id"], period_end)
        units = build_units(registrations, jurisdiction["fee_type"])
        if not units:
            continue
        breakdown = final_breakdown(units, jurisdiction["monthly_fee_cents"])
        row = new_assessment(account["id"], jurisdiction, period_month, "FINAL",
                             breakdown, REMITTANCE_SENTINEL)
        row["status"] = "REMITTED"
        row["remitted_at"] = store.now()
        if account["id"] not in touched:
            touched.append(account["id"])

    pending = sum(a["amount_cents"] for a in store.fee_assessments.values()
                  if a["jurisdiction_id"] == jurisdiction["id"] and a["status"] == "ASSESSED")
    remitted = sum(a["amount_cents"] for a in store.fee_assessments.values()
                   if a["jurisdiction_id"] == jurisdiction["id"] and a["status"] == "REMITTED")
    jurisdiction["pending_fee_cents"] = pending
    jurisdiction["remitted_fee_cents"] = remitted
    jurisdiction["last_remitted_period"] = period_month
    bump(jurisdiction)
    for account_id in touched:
        derive.recompute_account_liability(store.accounts.get(account_id))
    return jurisdiction
