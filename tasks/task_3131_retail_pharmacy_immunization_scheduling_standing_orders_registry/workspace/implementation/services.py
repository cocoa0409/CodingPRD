"""Business logic: logical clock sweeps, eligibility, calculations."""
import json
import uuid
from datetime import datetime, timedelta, timezone

from db import DB
from errors import err


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def iso_now():
    """Timestamp string for created_at/updated_at (millis, Z suffix)."""
    return fmt_ts(DB.clock)


def fmt_ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_ts(dt=None):
    """Logical-clock stamp in the clock's canonical form (no fractional digits).

    The PRD pins three-fractional-digit formatting only on created_at,
    updated_at, and api_request_timestamp; fields "stamped from the logical
    clock" (administered_at, due_at, started_at, ended_at, submitted_at,
    acknowledged_at) echo the clock's own canonical rendering, e.g.
    2026-09-01T00:00:00Z.
    """
    dt = dt if dt is not None else DB.clock
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 datetime; raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Expected ISO 8601 timestamp string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Expected ISO 8601 date string")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 date")


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1


def age_on(dob, on_date):
    """Whole years of age on the given date (birthday-inclusive)."""
    a = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        a -= 1
    return a


# ---------------------------------------------------------------------------
# Logical clock sweeps (PRD 2.4)
# ---------------------------------------------------------------------------

def run_sweeps():
    now = DB.clock
    # Appointment no-show / expire sweeps
    for appt in DB.appointments.values():
        if appt["status"] != "SCHEDULED":
            continue
        slot = parse_dt(appt["slot_start"])
        if not appt["is_walk_in"]:
            if now > slot + timedelta(minutes=60):
                appt["status"] = "NO_SHOW"
                touch(appt)
        else:
            day_end = slot.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            if now >= day_end:
                appt["status"] = "EXPIRED"
                touch(appt)
    # Registry lateness sweep
    for sub in DB.registry_submissions.values():
        if sub["status"] in ("PENDING", "REJECTED"):
            if now > parse_dt(sub["due_at"]):
                sub["status"] = "LATE_UNRESOLVED"
                sub["is_late"] = True
                touch(sub)
    # Clinic event activation sweep
    for ev in DB.clinic_events.values():
        if ev["status"] != "PLANNED":
            continue
        start = parse_dt(ev["event_start"])
        end = parse_dt(ev["event_end"])
        if start <= now < end:
            ev["status"] = "ACTIVE"
            touch(ev)
            lot = DB.lots.get(ev["mobile_lot_id"])
            if lot is not None:
                lot["doses_available"] = max(0, lot["doses_available"] - ev["doses_reserved"])
                touch(lot)


# ---------------------------------------------------------------------------
# Eligibility helpers
# ---------------------------------------------------------------------------

def prior_records(patient_id, product_id):
    """COMPLETED immunization records of this patient for this product, in
    scaffold order: administered_at ASC, ties broken by created_at ASC."""
    out = []
    for rec in DB.immunization_records.values():
        if rec["patient_id"] != patient_id or rec["status"] != "COMPLETED":
            continue
        lot = DB.lots.get(rec["lot_id"])
        if lot is None or lot["vaccine_product_id"] != product_id:
            continue
        out.append(rec)
    out.sort(key=lambda r: (parse_dt(r["administered_at"]), parse_dt(r["created_at"])))
    return out


def compute_dose_number(patient_id, product_id, product, slot_start):
    priors = prior_records(patient_id, product_id)
    dose_number = 1 + len(priors)
    if dose_number > product["doses_per_series"]:
        raise err("ERR_SERIES_ALREADY_COMPLETE",
                  "Patient already completed the product's dose series")
    if dose_number >= 2:
        last = priors[-1]
        earliest = parse_dt(last["administered_at"]) + timedelta(days=product["min_interval_days"])
        if slot_start < earliest:
            raise err("ERR_MIN_INTERVAL_NOT_MET",
                      "Prior dose administered fewer than min_interval_days before slot_start")
    return dose_number


def scheduled_dose_count_today(patient_id, store_id, ref_dt):
    """Count of the patient's COMPLETED administrations (records) at this store
    on the reference calendar day. Counted by administration day, not booking
    slot day, so a patient cannot defeat the daily dose cap by booking several
    appointments for one future day and taking walk-in doses today."""
    day = ref_dt.date()
    count = 0
    for rec in DB.immunization_records.values():
        if rec["patient_id"] != patient_id or rec["status"] != "COMPLETED":
            continue
        appt = DB.appointments.get(rec["appointment_id"])
        if appt is None or appt["store_id"] != store_id:
            continue
        if parse_dt(rec["administered_at"]).date() == day:
            count += 1
    return count


def eligible_lot_exists(store_id, product_id, ref_date):
    for lot in DB.lots.values():
        if (lot["store_id"] == store_id
                and lot["vaccine_product_id"] == product_id
                and lot["status"] == "RELEASED"
                and lot["doses_available"] > 0
                and parse_date(lot["expiration_date"]) > ref_date):
            return True
    return False


# ---------------------------------------------------------------------------
# Contraindication computation
# ---------------------------------------------------------------------------

CONTRA_ANSWER_KEYS = ("FEVER_TODAY", "PREGNANT", "IMMUNOCOMPROMISED", "PRIOR_ANAPHYLAXIS")
CONTRA_ALLERGY_TOKENS = ("ALLERGY", "CONTRA")


def _truthy_answer(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().upper() in ("YES", "TRUE", "Y")
    return bool(v)


def compute_contraindication(answers, allergy_flags):
    """True when any flagged answer is truthy, or any patient allergy flag is
    marked as a vaccine contraindication (flag contains ALLERGY/CONTRA)."""
    if isinstance(answers, dict):
        for key, value in answers.items():
            if str(key).upper() in CONTRA_ANSWER_KEYS and _truthy_answer(value):
                return True
    for flag in allergy_flags or []:
        token = str(flag).upper()
        if any(t in token for t in CONTRA_ALLERGY_TOKENS):
            return True
    return False


# ---------------------------------------------------------------------------
# Charge waterfall (PRD 3.6)
# ---------------------------------------------------------------------------

def adjudicate(product, plan):
    """Returns (charge_cents, billing_channel). Integer cents; floor only at
    the coinsurance multiplication step. Read-only w.r.t. the plan row."""
    price = product["cash_price_cents"]
    if plan is not None:
        covered = product["cvx_code"] in (plan.get("covered_cvx_codes") or [])
        if covered and plan["benefit_type"] in ("PHARMACY", "BOTH"):
            return min(plan["copay_cents"], price), "PHARMACY_BENEFIT"
        if covered and plan["benefit_type"] in ("MEDICAL", "BOTH"):
            deductible_applied = min(plan["deductible_remaining_cents"], price)
            remainder = price - deductible_applied
            coinsurance_cents = (remainder * plan["coinsurance_pct"]) // 100
            charge = deductible_applied + int(coinsurance_cents)
            return charge, "MEDICAL_BENEFIT"
    return price, "CASH"


# ---------------------------------------------------------------------------
# Excursion grading (PRD 3.2)
# ---------------------------------------------------------------------------

def round_half_up_2(value):
    """Round a float to 2 decimals, half-up, without float for money paths."""
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def peak_delta_tier(product, temperature_c):
    """Returns (is_excursion, tier). Rounds the raw delta to 2dp BEFORE tier
    comparison (pinned order)."""
    tmin = float(product["fridge_temp_min_c"])
    tmax = float(product["fridge_temp_max_c"])
    t = float(temperature_c)
    delta_raw = max(0.0, t - tmax, tmin - t)
    delta_c = round_half_up_2(delta_raw)
    if delta_c == 0:
        return False, "NONE"
    if delta_c <= 2.0:
        return True, "MINOR"
    if delta_c <= 5.0:
        return True, "MODERATE"
    return True, "SEVERE"


def cumulative_minutes_tier(lot_id):
    """Cumulative variant: sum over each run of consecutive out-of-band
    readings of (recorded_at[i+1] - recorded_at[i]) in minutes, tiered as
    <=30 MINOR, 30-120 MODERATE, >120 SEVERE."""
    readings = [r for r in DB.temperature_readings.values() if r["lot_id"] == lot_id]
    readings.sort(key=lambda r: (parse_dt(r["recorded_at"]), parse_dt(r["created_at"])))
    total_minutes = 0.0
    run = []
    for r in readings:
        if r["is_excursion"]:
            run.append(r)
        else:
            total_minutes += _run_minutes(run)
            run = []
    total_minutes += _run_minutes(run)
    if total_minutes <= 30:
        return "MINOR"
    if total_minutes <= 120:
        return "MODERATE"
    return "SEVERE"


def _run_minutes(run):
    if len(run) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(run, run[1:]):
        total += (parse_dt(b["recorded_at"]) - parse_dt(a["recorded_at"])).total_seconds() / 60.0
    return total


# ---------------------------------------------------------------------------
# Registry payload rendering (PRD 3.8)
# ---------------------------------------------------------------------------

def render_payload(fmt, record, patient, product, lot, appt):
    if fmt == "HL7_VXU":
        return (
            "MSH|^~\\&|IMMUNIZATION|PHARMACY|REGISTRY|STATE|{ts}||VXU^V04^VXU_V04|{rid}|P|2.5.1\r"
            "PID|1||{pid}||{name}||{dob}\r"
            "RXA|0|1|{ts}||{cvx}^{pname}^CVX|1|||{lot}|{store}\r"
            "ORC|RE||{appt}"
        ).format(
            ts=parse_dt(record["administered_at"]).strftime("%Y%m%d%H%M%S"),
            rid=record["id"],
            pid=patient["id"],
            name=patient["full_name"].replace(" ", "^"),
            dob=patient["date_of_birth"].replace("-", ""),
            cvx=product["cvx_code"],
            pname=product["name"],
            lot=lot["lot_number"],
            store=appt["store_id"],
            appt=appt["id"],
        )
    if fmt == "FLAT_FILE_CSV":
        header = "record_id,patient_id,patient_name,date_of_birth,cvx_code,product_name,lot_number,administered_at,dose_number,store_id"
        row = ",".join([
            record["id"], patient["id"], patient["full_name"], patient["date_of_birth"],
            product["cvx_code"], product["name"], lot["lot_number"],
            record["administered_at"], str(record["dose_number"]), appt["store_id"],
        ])
        return header + "\n" + row
    # STATE_API_JSON
    return json.dumps({
        "record_id": record["id"],
        "patient": {
            "id": patient["id"],
            "full_name": patient["full_name"],
            "date_of_birth": patient["date_of_birth"],
        },
        "vaccine": {
            "cvx_code": product["cvx_code"],
            "name": product["name"],
            "lot_number": lot["lot_number"],
        },
        "administered_at": record["administered_at"],
        "dose_number": record["dose_number"],
        "store_id": appt["store_id"],
    }, sort_keys=True)
