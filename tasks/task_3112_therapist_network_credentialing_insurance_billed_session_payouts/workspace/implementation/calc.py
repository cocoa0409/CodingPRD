"""Pinned calculations: rate resolution and the two-variant cost-share estimator."""
from __future__ import annotations

from datetime import datetime

from store import (
    GEOGRAPHY_ACTIVATION,
    license_effective_status,
    table,
)
from util import (
    UTC,
    dec,
    floor_int,
    now,
    parse_ts,
    round_half_up,
)

COPAY_OFFSET_CENTS = 500
COPAY_OFFSET_MIN_COINSURANCE_CENTS = 500
PAYER_ALLOWED_RATIO = dec("0.80")
NEW_CLINICIAN_PCT = dec("0.90")
GEOGRAPHY_PCT = dec("0.90")
GEOGRAPHY_FLAT_BREAKPOINT = 10000
GEOGRAPHY_FLAT_REDUCTION = 1000

_ACTIVATION = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


def _candidates(payer_id, license_type, geography, cpt_code, start):
    out = []
    for row in table("payer_rates").values():
        if row.get("payer_id") != payer_id:
            continue
        if row.get("license_type") != license_type:
            continue
        if row.get("geography") != geography:
            continue
        if row.get("cpt_code") != cpt_code:
            continue
        eff_from = parse_ts(row.get("effective_from"))
        eff_to = parse_ts(row.get("effective_to"))
        if eff_from is None or start < eff_from:
            continue
        if eff_to is not None and start >= eff_to:
            continue
        out.append(row)
    return out


def _pick(candidates):
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda r: (int(r.get("rate_set_version") or 0), r.get("created_at") or ""),
    )[-1]


def _cpt_eligible_license(clinician):
    licenses = [
        r
        for r in table("licenses").values()
        if r.get("clinician_id") == clinician["id"]
        and r.get("license_type") == clinician.get("license_type")
    ]
    if not licenses:
        return None
    verified = [r for r in licenses if license_effective_status(r) == "VERIFIED"]
    pool = verified or licenses
    return sorted(pool, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))[-1]


def resolve_rate(clinician, patient, session):
    """PRD §3.6 'Rate resolution'.  Returns (rate_cents, chosen_row_or_None)."""
    start = parse_ts(session.get("scheduled_start"))
    if start is None or clinician is None or patient is None:
        return 0, None

    payer_id = patient.get("payer_id")
    license_type = clinician.get("license_type")
    cpt_code = session.get("cpt_code")

    chosen = _pick(
        _candidates(payer_id, license_type, clinician.get("primary_state"), cpt_code, start)
    )
    if chosen is None:
        chosen = _pick(
            _candidates(payer_id, license_type, patient.get("state_code"), cpt_code, start)
        )

    rate = int(chosen.get("rate_cents") or 0) if chosen is not None else 0

    # Step 5: telehealth gate -- zeroes the rate and skips Steps 6-7 entirely.
    if session.get("modality") == "VIDEO":
        lic = _cpt_eligible_license(clinician)
        if lic is not None and lic.get("telehealth_eligible") is False:
            return 0, chosen

    # Step 6: new-clinician differential, strictly before onboarded_at + 90 days.
    onboarded = parse_ts(clinician.get("onboarded_at"))
    if onboarded is not None:
        threshold = onboarded.timestamp() + 90 * 86400
        if start.timestamp() < threshold:
            rate = floor_int(dec(rate) * NEW_CLINICIAN_PCT)

    # Step 7: geography differential, at or after the activation instant only.
    if (
        chosen is not None
        and start >= _ACTIVATION
        and chosen.get("geography") != patient.get("state_code")
    ):
        if rate >= GEOGRAPHY_FLAT_BREAKPOINT:
            rate = rate - GEOGRAPHY_FLAT_REDUCTION
        else:
            rate = floor_int(dec(rate) * GEOGRAPHY_PCT)

    return rate, chosen


def session_rate_cents(session):
    clinician = table("clinicians").get(session.get("clinician_id"))
    patient = table("patients").get(session.get("patient_id"))
    rate, _ = resolve_rate(clinician, patient, session)
    return rate


def _shared_cost_share(S, remaining_deductible, coinsurance_rate, copay_cents, oop_room, offset):
    d = min(S, max(0, int(remaining_deductible or 0)))
    after_deductible = S - d
    coins = round_half_up(dec(after_deductible) * dec(coinsurance_rate or 0))
    raw = d + coins + int(copay_cents or 0)
    if offset and coins >= COPAY_OFFSET_MIN_COINSURANCE_CENTS:
        raw = raw - COPAY_OFFSET_CENTS
    room = max(0, int(oop_room or 0))
    return max(0, min(raw, room))


def provisional_quote(snapshot, S):
    """PRD §3.3 provisional variant: reads the snapshot and carries the offset."""
    return _shared_cost_share(
        S,
        snapshot.get("deductible_remaining_cents"),
        snapshot.get("coinsurance_rate"),
        snapshot.get("copay_cents"),
        snapshot.get("oop_remaining_cents"),
        offset=True,
    )


def _paid_responsibility_this_year(patient):
    year = now().year
    claims = []
    for claim in table("claims").values():
        if claim.get("patient_id") != patient["id"]:
            continue
        if claim.get("claim_status") != "PAID":
            continue
        submitted = parse_ts(claim.get("submitted_on"))
        if submitted is None or submitted.year != year:
            continue
        claims.append(claim)
    claims.sort(key=lambda c: (c.get("submitted_on") or "", c.get("id") or ""))
    return sum(int(c.get("patient_resp_cents") or 0) for c in claims)


def final_adjudicated(patient, snapshot, S):
    """PRD §3.3 final variant: live accumulators, never the copay offset."""
    remaining_deductible = max(
        0, int(patient.get("deductible_cents") or 0) - _paid_responsibility_this_year(patient)
    )
    oop_room = max(0, int(patient.get("oop_max_cents") or 0) - int(patient.get("oop_met_cents") or 0))
    return _shared_cost_share(
        S,
        remaining_deductible,
        snapshot.get("coinsurance_rate") if snapshot else 0,
        snapshot.get("copay_cents") if snapshot else 0,
        oop_room,
        offset=False,
    )


def claim_amounts(patient, snapshot, session):
    """PRD §3.5 pinned arithmetic + the exact saturation boundary."""
    billed = session_rate_cents(session)
    allowed = round_half_up(dec(billed) * PAYER_ALLOWED_RATIO)
    patient_resp = final_adjudicated(patient, snapshot, allowed)
    payer_paid = max(0, allowed - patient_resp)

    oop_met = int(patient.get("oop_met_cents") or 0)
    oop_max = int(patient.get("oop_max_cents") or 0)
    if oop_met + patient_resp > oop_max:
        patient_resp = max(0, oop_max - oop_met)
        payer_paid = max(0, allowed - patient_resp)

    return {
        "billed_cents": billed,
        "allowed_cents": allowed,
        "patient_resp_cents": patient_resp,
        "payer_paid_cents": payer_paid,
    }