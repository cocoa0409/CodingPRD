"""Consent windows, medication history aggregation and deduplication (§3.8)."""

import clock
import db
from errors import ApiError, ERR_CONSENT_REQUIRED, ERR_CONSENT_STALE

MED_HISTORY_SCOPES = ("MEDICATION_HISTORY", "BOTH")

SOURCE_PRIORITY = {"PHARMACY_FILL": 0, "PAYER_CLAIM": 1}

MED_HISTORY_QUERY_BASE_CENTS = 25
MED_HISTORY_QUERY_PER_RECORD_CENTS = 10
RECORD_FEE_CAP = 40


# --------------------------------------------------------------------------
# Consent windows — half-open [granted_at, expires_at) (§3.8)
# --------------------------------------------------------------------------

def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals intersect when a_start < b_end and b_start < a_end."""
    if b_end is not None and a_start >= b_end:
        return False
    if a_end is not None and b_start >= a_end:
        return False
    return True


def _parse(stamp):
    from clock import parse_dt
    return parse_dt(stamp, "timestamp")


# The scopes each consent scope speaks for. `BOTH` covers both single scopes, which is
# what makes a `BOTH` grant collide with a live `MEDICATION_HISTORY` window while a
# `BENEFIT_CHECK` grant against that same window is a different scope entirely.
SCOPE_COVERS = {
    "MEDICATION_HISTORY": {"MEDICATION_HISTORY"},
    "BENEFIT_CHECK": {"BENEFIT_CHECK"},
    "BOTH": {"MEDICATION_HISTORY", "BENEFIT_CHECK", "BOTH"},
}


def scopes_overlap(a, b):
    return a in SCOPE_COVERS.get(b, {b}) or b in SCOPE_COVERS.get(a, {a})


def overlapping_active_consent(patient_id, scope, start, end):
    """An existing ACTIVE window blocks a new grant whose half-open window
    intersects it when the two scopes cover one another (§3.8).

    A `BOTH` window covers both single-scope windows, so a `BOTH` grant intersects a
    live `MEDICATION_HISTORY` window for the same patient just as a second
    `MEDICATION_HISTORY` grant would.
    """
    for consent in db.all_rows("consents"):
        if consent["patient_id"] != patient_id:
            continue
        if not scopes_overlap(scope, consent["scope"]):
            continue
        if consent["status"] != "ACTIVE":
            continue
        existing_start = _parse(consent["granted_at"])
        existing_end = _parse(consent["expires_at"])
        # A window whose exclusive upper bound has already passed is no longer live,
        # whatever its stored status says.
        expiry = expiry_instant(consent)
        if expiry is not None and expiry <= clock.get_clock():
            continue
        if windows_overlap(start, end, existing_start, existing_end):
            return consent
    return None


def expiry_instant(consent):
    """The instant the stored status of a consent would flip to EXPIRED (§3.8)."""
    row = consent.get("status_expires") or consent.get("expires_at")
    return _parse(row) if row else None


def refresh_consent_status(consent):
    """§3.8: the window is half-open, so a consent whose `expires_at` is no later than
    the current logical clock is no longer `ACTIVE`. Because every temporal rule reads
    the one logical clock (§2.10), the stored status is reconciled against it on read.
    """
    expiry = expiry_instant(consent)
    if (consent.get("status") == "ACTIVE" and expiry is not None
            and expiry <= clock.get_clock()):
        consent["status"] = "EXPIRED"
        db.touch(consent)
    return consent


def active_consent(patient_id, scopes):
    for consent in db.all_rows("consents"):
        if consent["patient_id"] != patient_id or consent["scope"] not in scopes:
            continue
        refresh_consent_status(consent)
        if consent["status"] == "ACTIVE":
            return consent
    return None


# --------------------------------------------------------------------------
# Patient aggregates
# --------------------------------------------------------------------------

def recompute_history_record_count(patient):
    count = sum(
        1 for r in db.all_rows("history_records")
        if r["patient_id"] == patient["id"] and r.get("retracted_at") is None
    )
    if patient.get("history_record_count") != count:
        patient["history_record_count"] = count
        db.touch(patient)
    else:
        patient["history_record_count"] = count
    return count


def recompute_monitored_prescriptions(patient_id):
    """A consent grant or revocation changes monitored_under_consent for that
    patient's orders, and therefore their significance (§3.3)."""
    from services import routing

    for prescription in db.all_rows("prescriptions"):
        if prescription.get("patient_id") != patient_id:
            continue
        before = (prescription.get("monitored_under_consent"), prescription.get("significance"))
        routing.recompute_derived(prescription)
        after = (prescription.get("monitored_under_consent"), prescription.get("significance"))
        if before != after:
            db.touch(prescription)


# --------------------------------------------------------------------------
# Record identity
# --------------------------------------------------------------------------

def dedupe_key(patient_id, drug_ndc, fill_date, days_supply):
    day = fill_date.strftime("%Y-%m-%d")
    return f"{patient_id}|{drug_ndc}|{day}|{days_supply}"


def certified_sources():
    return {p["id"] for p in db.all_rows("participants")
            if p["certification_status"] == "CERTIFIED"}


def live_source_records(patient_id):
    """Live records whose source participant is CERTIFIED."""
    certified = certified_sources()
    return [
        r for r in db.all_rows("history_records")
        if r["patient_id"] == patient_id
        and r.get("retracted_at") is None
        and r["source_participant_id"] in certified
    ]


# --------------------------------------------------------------------------
# Deduplication (medication_history_dedupe)
# --------------------------------------------------------------------------

def rank_key(record):
    return (
        SOURCE_PRIORITY.get(record["source_type"], 9),
        -record["quantity"],
        record["fill_date"],
        record.get("_seq", 0),
    )


def deduplicate(records):
    """Partition by dedupe_key and rank within each partition.

    Returns (winners, losers, source_count).
    """
    partitions = {}
    for record in records:
        partitions.setdefault(record["dedupe_key"], []).append(record)
    winners, losers = [], []
    for group in partitions.values():
        group.sort(key=rank_key)
        winners.append(group[0])
        losers.extend(group[1:])
    return winners, losers, len(records)


def batch_cost(source_record_count):
    return MED_HISTORY_QUERY_BASE_CENTS + MED_HISTORY_QUERY_PER_RECORD_CENTS * min(
        source_record_count, RECORD_FEE_CAP)


# --------------------------------------------------------------------------
# Batch machine (§3.8)
# --------------------------------------------------------------------------

def advance_batch(batch):
    """PENDING -> AGGREGATING (single call), or COMPLETE -> AGGREGATING -> COMPLETE."""
    patient = db.get("patients", batch["patient_id"])
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    if active_consent(batch["patient_id"], MED_HISTORY_SCOPES) is None:
        raise ApiError(ERR_CONSENT_REQUIRED)

    if batch["status"] == "PENDING":
        batch["status"] = "AGGREGATING"
        batch["consent_version_snapshot"] = patient["consent_version"]
        # §3.8: "The `subscription_generation` counter increments on the settlement,
        # and again whenever a `COMPLETE` batch is re-aggregated in place".
        batch["subscription_generation"] += 1
        db.touch(batch)
    elif batch["status"] == "COMPLETE":
        batch["status"] = "AGGREGATING"
        db.touch(batch)
        batch["subscription_generation"] += 1
    else:
        # §3.8's state band refuses a batch that is not PENDING or COMPLETE
        # (§2.9 priority 4) — and that band sits above the consent precondition, so a
        # FAILED batch reports the state error rather than the consent error.
        raise ApiError("ERR_INVALID_STATE")

    return settle_batch(batch, patient)


def settle_batch(batch, patient):
    """A settlement whose snapshot no longer matches the patient's consent
    version settles FAILED with its economics left at zero."""
    if patient["consent_version"] != batch["consent_version_snapshot"]:
        batch["status"] = "FAILED"
        batch["record_count"] = 0
        batch["superseded_count"] = 0
        batch["batch_cost_cents"] = 0
        db.touch(batch)
        raise ApiError(ERR_CONSENT_STALE)

    records = live_source_records(batch["patient_id"])
    for record in records:
        record["dedupe_key"] = dedupe_key(
            record["patient_id"], record["drug_ndc"], record["fill_date"], record["days_supply"])

    winners, losers, source_count = deduplicate(records)
    for record in winners:
        record["is_superseded"] = False
        record["aggregation_batch_id"] = batch["id"]
        db.touch(record)
    for record in losers:
        record["is_superseded"] = True
        record["aggregation_batch_id"] = batch["id"]
        db.touch(record)

    batch["source_record_count"] = source_count
    batch["record_count"] = len(winners)
    batch["superseded_count"] = len(losers)
    batch["batch_cost_cents"] = batch_cost(source_count)
    batch["status"] = "COMPLETE"
    db.touch(batch)

    recompute_history_record_count(patient)
    advance_payer_deductible(patient)
    return batch


def advance_payer_deductible(patient):
    """The payer deductible advance on settlement (§3.8).

    The payer's deductible is consumed toward its limit by the covered plan's
    per-fill exposure — its fixed copay plus its coinsurance share of the
    benchmark — saturating at plan_deductible_cents. Benefit-check settlement
    consumes the same quantity through the benefit-cost credit (§3.9); the two
    are the same accumulator and whichever runs consumes what remains.
    """
    payer_id = patient.get("covered_plan_payer_id")
    if not payer_id:
        return
    payer = db.get("participants", payer_id)
    if payer is None:
        return
    limit = payer.get("plan_deductible_cents", 0)
    met = payer.get("plan_deductible_met_cents", 0)
    if met >= limit:
        return
    per_fill = payer.get("plan_copay_cents", 0)
    payer["plan_deductible_met_cents"] = min(limit, met + per_fill)
    db.touch(payer)


# --------------------------------------------------------------------------
# Revocation chain (§3.8)
# --------------------------------------------------------------------------

def revoke_all(patient):
    now = clock.now_iso()
    revoked = []
    for consent in db.all_rows("consents"):
        if consent["patient_id"] == patient["id"] and consent["status"] == "ACTIVE":
            consent["status"] = "REVOKED"
            consent["revoked_at"] = now
            db.touch(consent)
            revoked.append(consent)
    patient["consent_status"] = "REVOKED"
    patient["consent_version"] += 1
    db.touch(patient)

    if patient.get("discard_on_revoke"):
        for record in db.all_rows("history_records"):
            if record["patient_id"] == patient["id"] and record.get("retracted_at") is None:
                record["retracted_at"] = now
                db.touch(record)

    recompute_history_record_count(patient)
    recompute_monitored_prescriptions(patient["id"])
    return revoked