"""Cross-entity workflows: assessment-supersede cascade and grant report computation."""
from datetime import timedelta

from errors import ApiError, ERR_INVALID_REQUEST
from services import (
    base_entity,
    compute_patient_charge,
    logical_now,
    parse_ts,
    patient_is_minor,
    touch,
)
from store import store


# ---------------------------------------------------------------------------
# Assessment-supersede cascade (PRD §3.8)
# ---------------------------------------------------------------------------

def recompute_claim_billed(claim):
    enc = store.encounters[claim["encounter_id"]]
    if claim["confidential_suppression"]:
        claim["billed_cents"] = 0
    else:
        from services import find_catalog_entry
        entry = find_catalog_entry(enc["affiliate_id"], enc["service_code"])
        full_fee = entry["full_fee_cents"] if entry else 0
        claim["billed_cents"] = full_fee - enc["patient_charge_cents"]
    claim["net_receivable_cents"] = (
        claim["billed_cents"] - claim["paid_cents"] + claim["recouped_cents"]
    )


def supersede_assessment_cascade(patient, new_assessment):
    """Link 1 handled by caller (status flips). Links 2-4 here."""
    affiliate_id = patient["affiliate_id"]
    repriced_encounters = []
    for enc in store.encounters.values():
        if enc["patient_id"] != patient["id"]:
            continue
        if enc["billing_status"] not in ("UNBILLED", "CLAIMED"):
            continue  # SETTLED and WAIVED are never re-priced
        # Link 2: re-pin + reprice
        enc["assessment_id"] = new_assessment["id"]
        enc["patient_charge_cents"] = compute_patient_charge(enc, new_assessment)
        touch(enc)
        repriced_encounters.append(enc)
        # Link 3: open claim recompute for CLAIMED encounters
        if enc["billing_status"] == "CLAIMED":
            for claim in store.claims.values():
                if claim["encounter_id"] == enc["id"] and claim["status"] not in ("VOID",):
                    recompute_claim_billed(claim)
                    touch(claim)
                    break
    # Link 4: DRAFT grant reports covering a re-priced encounter refresh aggregates
    covered_report_ids = set()
    for enc in repriced_encounters:
        enc_start = parse_ts(enc["scheduled_start"], "scheduled_start")
        for rep in store.grant_reports.values():
            if rep["affiliate_id"] != affiliate_id or rep["status"] != "DRAFT":
                continue
            if rep["id"] in covered_report_ids:
                continue
            if parse_ts(rep["period_start"], "period_start") <= enc_start < parse_ts(rep["period_end"], "period_end"):
                refresh_report_aggregates(rep)
                covered_report_ids.add(rep["id"])


# ---------------------------------------------------------------------------
# Grant report aggregates (PRD §3.10)
# ---------------------------------------------------------------------------

def _completed_encounters_in_period(affiliate_id, period_start, period_end):
    out = []
    for enc in store.encounters.values():
        if enc["affiliate_id"] != affiliate_id or enc["clinical_status"] != "COMPLETED":
            continue
        start = parse_ts(enc["scheduled_start"], "scheduled_start")
        if period_start <= start < period_end:
            out.append(enc)
    return out


def _device_value(affiliate_id, period_start, period_end, variant):
    # Input set: FULFILLED reservations whose encounter scheduled_start in window.
    rows = []
    for res in store.reservations.values():
        if res["status"] != "FULFILLED":
            continue
        enc = store.encounters.get(res["encounter_id"])
        if not enc or enc["affiliate_id"] != affiliate_id:
            continue
        start = parse_ts(enc["scheduled_start"], "scheduled_start")
        if not (period_start <= start < period_end):
            continue
        lot = store.stock_lots.get(res["lot_id"])
        if not lot:
            continue
        rows.append((res, lot))
    if variant == "FIFO":
        total = 0
        for res, lot in sorted(rows, key=lambda rl: (rl[1]["_created_seq"], rl[0]["_created_seq"])):
            total += lot["unit_cost_cents"]
        return total
    # WEIGHTED_AVERAGE: per device_code floored mean * units of code
    by_code = {}
    for res, lot in rows:
        agg = by_code.setdefault(lot["device_code"], [0, 0])
        agg[0] += lot["unit_cost_cents"]
        agg[1] += 1
    total = 0
    for _code, (cost_sum, units) in by_code.items():
        avg = cost_sum // units
        total += avg * units
    return total


def compute_report_aggregates(affiliate, period_start, period_end, valuation_variant):
    encounters = _completed_encounters_in_period(affiliate["id"], period_start, period_end)
    encounter_count = len(encounters)
    low_income = 0
    minor = 0
    for enc in encounters:
        assessment = store.assessments.get(enc["assessment_id"])
        if assessment is not None and assessment["fpl_pct"] < 100:
            low_income += 1
        patient = store.patients.get(enc["patient_id"])
        if patient is not None and patient_is_minor(
            patient, ref=parse_ts(enc["scheduled_start"], "scheduled_start").date()
        ):
            minor += 1
    device_value = _device_value(affiliate["id"], period_start, period_end, valuation_variant)
    if encounter_count == 0:
        quota_met = True
    else:
        quota_met = (low_income * 100) >= (encounter_count * affiliate["low_income_priority_quota"])
    return {
        "encounter_count": encounter_count,
        "low_income_encounter_count": low_income,
        "minor_encounter_count": minor,
        "device_value_cents": device_value,
        "low_income_quota_met": quota_met,
    }


def refresh_report_aggregates(report):
    """Link 4: refresh aggregates of a DRAFT report in place."""
    affiliate = store.affiliates.get(report["affiliate_id"])
    if affiliate is None:
        return
    aggregates = compute_report_aggregates(
        affiliate,
        parse_ts(report["period_start"], "period_start"),
        parse_ts(report["period_end"], "period_end"),
        report["valuation_variant"],
    )
    # encounter_count unchanged per spec note; low_income_encounter_count and
    # device_value_cents re-derived. minor_encounter_count is re-derived too for
    # consistency of the aggregate family.
    report["low_income_encounter_count"] = aggregates["low_income_encounter_count"]
    report["minor_encounter_count"] = aggregates["minor_encounter_count"]
    report["device_value_cents"] = aggregates["device_value_cents"]
    report["low_income_quota_met"] = aggregates["low_income_quota_met"]
    touch(report)
