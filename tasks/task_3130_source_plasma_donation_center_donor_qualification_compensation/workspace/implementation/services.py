"""Business logic: calculations, state-machine side effects, scheduled transitions.

All constants and rules are taken from SCAFFOLD.yaml sections 1.2/1.3 and PRD section 3.
"""
from datetime import datetime, timedelta, timezone

import db
import errors

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------
APPLICANT_WINDOW_DAYS = 180
LOOKBACK_WINDOW_DAYS = 180
ROLLING_FREQUENCY_DAYS = 7
FREQUENCY_MAX_PER_WINDOW = 2
MIN_INTER_DONATION_HOURS = 48
OBSERVATION_MINUTES = 15
SEVERE_REACTION_DEFERRAL_DAYS = 7
MIN_ABORT_PAYOUT_CENTS = 500
TAX_REPORTING_THRESHOLD_CENTS = 60000

SCREENING_EXPIRY = timedelta(hours=24)
DONATION_NO_SHOW = timedelta(hours=6)

REACTIVE_VALUES = ("REACTIVE",)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def center_view(c):
    return {
        "id": c["id"],
        "center_code": c["center_code"],
        "legal_name": c["legal_name"],
        "state_code": c["state_code"],
        "screening_lanes": c["screening_lanes"],
        "donor_floor_beds": c["donor_floor_beds"],
        "observation_chairs": c["observation_chairs"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def donor_view(d):
    return {
        "id": d["id"],
        "external_donor_ref": d["external_donor_ref"],
        "legal_first_name": d["legal_first_name"],
        "legal_last_name": d["legal_last_name"],
        "date_of_birth": d["date_of_birth"],
        "weight_kg": d["weight_kg"],
        "home_center_id": d["home_center_id"],
        "donor_status": d["donor_status"],
        "applicant_window_started_on": d["applicant_window_started_on"],
        "deferral_ends_on": d["deferral_ends_on"],
        "deferred_reason_code": d["deferred_reason_code"],
        "lifetime_donation_count": d["lifetime_donation_count"],
        "ytd_compensation_cents": d["ytd_compensation_cents"],
        "requires_1099": d["requires_1099"],
        "active_deferral_id": d["active_deferral_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def screening_visit_view(v):
    return {
        "id": v["id"],
        "donor_id": v["donor_id"],
        "center_id": v["center_id"],
        "scheduled_for": v["scheduled_for"],
        "screening_lane_index": v["screening_lane_index"],
        "identity_verified": v["identity_verified"],
        "health_history_recorded": v["health_history_recorded"],
        "physical_exam_recorded": v["physical_exam_recorded"],
        "viral_marker_recorded": v["viral_marker_recorded"],
        "visit_status": v["visit_status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def sub_record_view(r):
    return {
        "id": r["id"],
        "screening_visit_id": r["screening_visit_id"],
        "record_type": r["record_type"],
        "payload": r["payload"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "outcome": r["outcome"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def donation_visit_view(v):
    return {
        "id": v["id"],
        "donor_id": v["donor_id"],
        "center_id": v["center_id"],
        "screening_visit_id": v["screening_visit_id"],
        "scheduled_for": v["scheduled_for"],
        "bed_index": v["bed_index"],
        "observation_chair_index": v["observation_chair_index"],
        "programmed_volume_ml": v["programmed_volume_ml"],
        "actual_volume_ml": v["actual_volume_ml"],
        "visit_status": v["visit_status"],
        "compensation_payment_id": v["compensation_payment_id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def adverse_reaction_view(r):
    return {
        "id": r["id"],
        "donation_visit_id": r["donation_visit_id"],
        "severity": r["severity"],
        "reaction_code": r["reaction_code"],
        "observed_at": r["observed_at"],
        "notes": r["notes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def unit_view(u):
    return {
        "id": u["id"],
        "donation_visit_id": u["donation_visit_id"],
        "donor_id": u["donor_id"],
        "center_id": u["center_id"],
        "volume_ml": u["volume_ml"],
        "collected_at": u["collected_at"],
        "unit_status": u["unit_status"],
        "released_at": u["released_at"],
        "destroyed_at": u["destroyed_at"],
        "destruction_reason": u["destruction_reason"],
        "lookback_case_id": u["lookback_case_id"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def schedule_view(s):
    return {
        "id": s["id"],
        "center_id": s["center_id"],
        "effective_from": s["effective_from"],
        "effective_to": s["effective_to"],
        "base_cents_first_donation": s["base_cents_first_donation"],
        "base_cents_second_donation": s["base_cents_second_donation"],
        "base_cents_subsequent_donation": s["base_cents_subsequent_donation"],
        "promo_code": s["promo_code"],
        "promo_bonus_cents": s["promo_bonus_cents"],
        "promo_qualifying_donation_count": s["promo_qualifying_donation_count"],
        "schedule_status": s["schedule_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def payment_view(p):
    return {
        "id": p["id"],
        "donation_visit_id": p["donation_visit_id"],
        "donor_id": p["donor_id"],
        "center_id": p["center_id"],
        "schedule_id": p["schedule_id"],
        "base_cents": p["base_cents"],
        "promo_cents": p["promo_cents"],
        "net_cents": p["net_cents"],
        "payment_status": p["payment_status"],
        "variant": p["variant"],
        "variant_switched_at": p["variant_switched_at"],
        "payment_issued_on": p["payment_issued_on"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def deferral_view(e):
    return {
        "id": e["id"],
        "donor_id": e["donor_id"],
        "reason_code": e["reason_code"],
        "deferral_type": e["deferral_type"],
        "deferral_ends_on": e["deferral_ends_on"],
        "source_center_id": e["source_center_id"],
        "filed_by_user_id": e["filed_by_user_id"],
        "registry_status": e["registry_status"],
        "override_rationale": e["override_rationale"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def lookback_case_view(c):
    return {
        "id": c["id"],
        "donor_id": c["donor_id"],
        "triggering_screening_sub_record_id": c["triggering_screening_sub_record_id"],
        "triggering_donation_visit_id": c["triggering_donation_visit_id"],
        "lookback_window_days": c["lookback_window_days"],
        "case_status": c["case_status"],
        "opened_at": c["opened_at"],
        "resolved_at": c["resolved_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def snapshot_view(s):
    return {
        "id": s["id"],
        "center_id": s["center_id"],
        "snapshot_at": s["snapshot_at"],
        "screening_lanes_in_use": s["screening_lanes_in_use"],
        "donor_floor_beds_in_use": s["donor_floor_beds_in_use"],
        "observation_chairs_in_use": s["observation_chairs_in_use"],
        "pending_releases_count": s["pending_releases_count"],
        "trigger_event": s["trigger_event"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_center_or_404(center_id):
    c = db.DB["plasma_centers"].get(center_id)
    if c is None:
        raise errors.err_not_found("plasma center not found")
    return c


def get_donor_or_404(donor_id):
    d = db.DB["donors"].get(donor_id)
    if d is None:
        raise errors.err_not_found("donor not found")
    return d


def get_screening_visit_or_404(visit_id):
    v = db.DB["screening_visits"].get(visit_id)
    if v is None:
        raise errors.err_not_found("screening visit not found")
    return v


def get_donation_visit_or_404(visit_id):
    v = db.DB["donation_visits"].get(visit_id)
    if v is None:
        raise errors.err_not_found("donation visit not found")
    return v


def get_schedule_or_404(schedule_id):
    s = db.DB["compensation_schedules"].get(schedule_id)
    if s is None:
        raise errors.err_not_found("compensation schedule not found")
    return s


def get_deferral_entry_or_404(entry_id):
    e = db.DB["deferral_registry_entries"].get(entry_id)
    if e is None:
        raise errors.err_not_found("deferral registry entry not found")
    return e


def get_unit_or_404(unit_id):
    u = db.DB["donation_units"].get(unit_id)
    if u is None:
        raise errors.err_not_found("donation unit not found")
    return u


def get_lookback_case_or_404(case_id):
    c = db.DB["lookback_cases"].get(case_id)
    if c is None:
        raise errors.err_not_found("look-back case not found")
    return c


def get_center(center_id):
    return db.DB["plasma_centers"].get(center_id)


def get_donor(donor_id):
    return db.DB["donors"].get(donor_id)


def active_deferral_for(donor_id):
    for e in db.DB["deferral_registry_entries"].values():
        if e["donor_id"] == donor_id and e["registry_status"] == "ACTIVE":
            return e
    return None


def sub_records_of(screening_visit_id):
    return [
        r for r in db.DB["screening_sub_records"].values()
        if r["screening_visit_id"] == screening_visit_id
    ]


def sub_record_of_type(screening_visit_id, record_type):
    for r in db.DB["screening_sub_records"].values():
        if r["screening_visit_id"] == screening_visit_id and r["record_type"] == record_type:
            return r
    return None


def completed_visits_for_donor(donor_id):
    return [
        v for v in db.DB["donation_visits"].values()
        if v["donor_id"] == donor_id and v["visit_status"] == "COMPLETED"
    ]


def open_lookback_case_for(donor_id):
    for c in db.DB["lookback_cases"].values():
        if c["donor_id"] == donor_id and c["case_status"] in ("OPEN", "UNITS_QUARANTINED"):
            return c
    return None


# ---------------------------------------------------------------------------
# Capacity snapshot (SCAFFOLD 1.3 capacity_occupancy)
# ---------------------------------------------------------------------------
def write_snapshot(center_id, trigger_event):
    now = db.now()
    lanes_in_use = 0
    for v in db.DB["screening_visits"].values():
        if v["center_id"] != center_id or v["visit_status"] != "IN_PROGRESS":
            continue
        sf = v.get("_scheduled_for_dt")
        if sf is not None and sf <= now < sf + SCREENING_EXPIRY:
            lanes_in_use += 1
    beds_in_use = sum(
        1 for v in db.DB["donation_visits"].values()
        if v["center_id"] == center_id and v["visit_status"] == "IN_PROGRESS"
    )
    chairs_in_use = sum(
        1 for v in db.DB["donation_visits"].values()
        if v["center_id"] == center_id and v["visit_status"] == "OBSERVATION"
    )
    pending = sum(
        1 for u in db.DB["donation_units"].values()
        if u["center_id"] == center_id and u["unit_status"] == "QUARANTINED"
    )
    snap = {
        "id": db.next_id(),
        "center_id": center_id,
        "snapshot_at": db.ts(),
        "screening_lanes_in_use": lanes_in_use,
        "donor_floor_beds_in_use": beds_in_use,
        "observation_chairs_in_use": chairs_in_use,
        "pending_releases_count": pending,
        "trigger_event": trigger_event,
    }
    db.stamp_new(snap)
    db.DB["capacity_snapshots"][snap["id"]] = snap
    return snap


# ---------------------------------------------------------------------------
# Slot assignment (SCAFFOLD 1.3 lowest_free_slot_assignment)
# ---------------------------------------------------------------------------
def lowest_free_index(capacity, occupied):
    for i in range(capacity):
        if i not in occupied:
            return i
    return None


def occupied_beds(center_id):
    return {
        v["bed_index"]
        for v in db.DB["donation_visits"].values()
        if v["center_id"] == center_id
        and v["visit_status"] == "IN_PROGRESS"
        and v["bed_index"] is not None
    }


def occupied_chairs(center_id):
    return {
        v["observation_chair_index"]
        for v in db.DB["donation_visits"].values()
        if v["center_id"] == center_id
        and v["visit_status"] == "OBSERVATION"
        and v["observation_chair_index"] is not None
    }


def occupied_lanes(center_id):
    return {
        v["screening_lane_index"]
        for v in db.DB["screening_visits"].values()
        if v["center_id"] == center_id
        and v["visit_status"] == "IN_PROGRESS"
        and v["screening_lane_index"] is not None
    }


def assign_lane(center, visit):
    """Lowest-index lane assignment at the first sub-record write.

    Center-wide rule: pick the lowest lane index in [0, screening_lanes) not
    currently held by another IN_PROGRESS screening at this center. When every
    lane is occupied, wrap to lane 0 (screening admission is not gated).
    """
    occupied = occupied_lanes(center["id"])
    idx = lowest_free_index(center["screening_lanes"], occupied)
    if idx is None:
        idx = 0
    visit["screening_lane_index"] = idx
    return idx


def assign_bed(center):
    return lowest_free_index(center["donor_floor_beds"], occupied_beds(center["id"]))


def assign_chair(center):
    return lowest_free_index(center["observation_chairs"], occupied_chairs(center["id"]))


# ---------------------------------------------------------------------------
# Plasma volume calculation (SCAFFOLD 1.3 plasma_volume_ml)
# ---------------------------------------------------------------------------
def plasma_volume_ml(weight_kg):
    w = float(weight_kg)
    if w < 50.0:
        raise errors.err_donor_underweight()
    if w < 68.0:
        return 625
    if w < 79.0:
        return 690
    if w < 110.0:
        return 825
    return 880


# ---------------------------------------------------------------------------
# Sub-record outcome computation (SCAFFOLD 1.1 ScreeningSubRecord.outcome)
# ---------------------------------------------------------------------------
RECORD_TYPES = ("IDENTITY", "HEALTH_HISTORY", "PHYSICAL_EXAM", "VIRAL_MARKER")

PHYSICAL_EXAM_FIELDS = (
    "weight_kg",
    "pulse_bpm",
    "systolic_mmhg",
    "diastolic_mmhg",
    "temperature_c",
    "hematocrit_pct",
    "total_protein_g_dl",
)

VIRAL_MARKER_FIELDS = ("hiv_ag_ab", "hbv_surface_ag", "hcv_ab")


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_sub_record_payload(record_type, payload):
    """Validate payload shape (ERR_INVALID_REQUEST) and compute outcome."""
    if not isinstance(payload, dict):
        raise errors.err_invalid_request("payload must be an object")

    if record_type == "IDENTITY":
        doc = payload.get("document_number")
        if doc is not None and not isinstance(doc, str):
            raise errors.err_invalid_request("payload.document_number must be a string")
        outcome = "PASS" if isinstance(doc, str) and doc != "" else "FAIL"
        return outcome

    if record_type == "HEALTH_HISTORY":
        flags = payload.get("risk_flags")
        if not isinstance(flags, list) or any(not isinstance(f, str) for f in flags):
            raise errors.err_invalid_request("payload.risk_flags must be an array of strings")
        outcome = "FAIL" if len(flags) > 0 else "PASS"
        return outcome

    if record_type == "PHYSICAL_EXAM":
        for field in PHYSICAL_EXAM_FIELDS:
            if field not in payload:
                raise errors.err_invalid_request(f"payload.{field} is required")
            if not _is_number(payload[field]):
                raise errors.err_invalid_request(f"payload.{field} must be a number")
        weight = float(payload["weight_kg"])
        if weight < 50.0:
            # Per PRD 3.3: underweight physical exam surfaces ERR_DONOR_UNDERWEIGHT (422).
            raise errors.err_donor_underweight()
        fail = False
        pulse = float(payload["pulse_bpm"])
        sys_ = float(payload["systolic_mmhg"])
        dia = float(payload["diastolic_mmhg"])
        temp = float(payload["temperature_c"])
        hema = float(payload["hematocrit_pct"])
        prot = float(payload["total_protein_g_dl"])
        if pulse < 50 or pulse > 100:
            fail = True
        if sys_ < 90 or sys_ > 180:
            fail = True
        if dia < 50 or dia > 100:
            fail = True
        if temp < 35.5 or temp > 37.5:
            fail = True
        if hema < 38 or hema > 54:
            fail = True
        if prot < 6.0 or prot > 9.0:
            fail = True
        return "FAIL" if fail else "PASS"

    if record_type == "VIRAL_MARKER":
        for field in VIRAL_MARKER_FIELDS:
            if field not in payload:
                raise errors.err_invalid_request(f"payload.{field} is required")
            if payload[field] not in ("NON_REACTIVE", "REACTIVE"):
                raise errors.err_invalid_request(
                    f"payload.{field} must be NON_REACTIVE or REACTIVE"
                )
        fail = any(payload[f] == "REACTIVE" for f in VIRAL_MARKER_FIELDS)
        return "FAIL" if fail else "PASS"

    raise errors.err_invalid_request("unknown record_type")


# ---------------------------------------------------------------------------
# Donation scheduling helpers
# ---------------------------------------------------------------------------
def screening_consumed(screening_visit_id, exclude_visit_id=None):
    """A screening is consumed when another DonationVisit referencing it is
    IN_PROGRESS or COMPLETED (SCAFFOLD 1.2 check-in preconditions)."""
    for v in db.DB["donation_visits"].values():
        if v["screening_visit_id"] != screening_visit_id:
            continue
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        if v["visit_status"] in ("IN_PROGRESS", "COMPLETED"):
            return True
    return False


def active_schedule_for(center_id, instant):
    """The ACTIVE schedule for a center covering `instant`, or None."""
    for s in db.DB["compensation_schedules"].values():
        if s["center_id"] != center_id or s["schedule_status"] != "ACTIVE":
            continue
        ef = db.parse_dt(s["effective_from"])
        et = db.parse_dt(s["effective_to"])
        if ef is not None and et is not None and ef <= instant < et:
            return s
    return None


# ---------------------------------------------------------------------------
# Compensation calculations (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------
def _completed_in_month(donor_id, year, month, exclude_visit_id=None):
    visits = []
    for v in completed_visits_for_donor(donor_id):
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        ca = v.get("_collected_at_dt")
        if ca is not None and ca.year == year and ca.month == month:
            visits.append(v)
    return visits


def compute_base_cents(donor_id, schedule, visit, variant, checkin_dt):
    """Base component per base_compensation_cents.

    ordinal = count of the donor's COMPLETED visits in the same calendar month
    as this visit's check-in date, counting PRIOR completions only. In the
    FINAL variant this visit is itself completed by the time the recompute
    runs, so this visit must be excluded from the prior count (per PRD 3.8 the
    final ordinal of the just-completed visit equals the number of PRIOR
    completions in the month).
    """
    prior = _completed_in_month(
        donor_id, checkin_dt.year, checkin_dt.month, exclude_visit_id=visit["id"]
    )
    ordinal = len(prior)
    if ordinal == 0:
        return schedule["base_cents_first_donation"]
    if ordinal == 1:
        return schedule["base_cents_second_donation"]
    return schedule["base_cents_subsequent_donation"]


def _finalized_promo_exists(donor_id, schedule_id, exclude_payment_id=None):
    for p in db.DB["compensation_payments"].values():
        if p["donor_id"] != donor_id:
            continue
        if p["schedule_id"] != schedule_id:
            continue
        if exclude_payment_id is not None and p["id"] == exclude_payment_id:
            continue
        if p["payment_status"] == "FINALIZED" and p["promo_cents"] > 0:
            return True
    return False


def _completed_in_window(donor_id, ef, et, exclude_visit_id=None):
    visits = []
    for v in completed_visits_for_donor(donor_id):
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        ca = v.get("_collected_at_dt")
        if ca is not None and ef <= ca < et:
            visits.append(v)
    return visits


def compute_promo_cents(donor_id, schedule, visit, variant):
    """Promo component per promo_compensation_cents."""
    if schedule.get("promo_code") is None or schedule.get("promo_qualifying_donation_count", 0) == 0:
        return 0
    ef = db.parse_dt(schedule["effective_from"])
    et = db.parse_dt(schedule["effective_to"])
    qualifying = schedule["promo_qualifying_donation_count"]
    payment_id = visit.get("compensation_payment_id")
    if variant == "PROVISIONAL":
        count_excl = len(_completed_in_window(donor_id, ef, et, exclude_visit_id=visit["id"]))
        if count_excl + 1 >= qualifying and not _finalized_promo_exists(
            donor_id, schedule["id"], exclude_payment_id=payment_id
        ):
            return schedule["promo_bonus_cents"]
        return 0
    # FINAL variant: this visit has completed by the time we recompute.
    count_incl = len(_completed_in_window(donor_id, ef, et))
    if count_incl >= qualifying and not _finalized_promo_exists(
        donor_id, schedule["id"], exclude_payment_id=payment_id
    ):
        return schedule["promo_bonus_cents"]
    return 0


def recompute_payment(payment, visit, variant):
    donor_id = payment["donor_id"]
    schedule = db.DB["compensation_schedules"].get(payment["schedule_id"])
    checkin_dt = visit.get("_checkin_dt") or db.now()
    base = compute_base_cents(donor_id, schedule, visit, variant, checkin_dt)
    promo = compute_promo_cents(donor_id, schedule, visit, variant)
    payment["base_cents"] = base
    payment["promo_cents"] = promo
    payment["net_cents"] = base + promo


def compute_abort_cents(donor_id, schedule, visit, checkin_dt):
    """Abort compensation per abort_compensation_cents."""
    actual = visit["actual_volume_ml"]
    if actual is None:
        return 0
    base_final = compute_base_cents(donor_id, schedule, visit, "FINAL", checkin_dt)
    fraction = float(actual) / float(visit["programmed_volume_ml"])
    abort = int(base_final * fraction)  # floor for positive values
    if 0 < abort < MIN_ABORT_PAYOUT_CENTS:
        abort = MIN_ABORT_PAYOUT_CENTS
    return abort


# ---------------------------------------------------------------------------
# YTD accumulator (SCAFFOLD 1.3 ytd_compensation_accumulator)
# ---------------------------------------------------------------------------
def recompute_ytd(donor_id):
    donor = db.DB["donors"].get(donor_id)
    if donor is None:
        return
    year = db.now().year
    total = 0
    for p in db.DB["compensation_payments"].values():
        if p["donor_id"] != donor_id or p["payment_status"] != "FINALIZED":
            continue
        pio = p.get("_payment_issued_on_dt")
        if pio is not None and pio.year == year:
            total += p["net_cents"]
    donor["ytd_compensation_cents"] = total
    # Sticky-downward: only set true, never clear.
    if total >= TAX_REPORTING_THRESHOLD_CENTS:
        donor["requires_1099"] = True
    db.touch(donor)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def create_unit(visit, donor, now):
    unit = {
        "id": db.next_id(),
        "donation_visit_id": visit["id"],
        "donor_id": donor["id"],
        "center_id": visit["center_id"],
        "volume_ml": visit["actual_volume_ml"],
        "collected_at": db.ts(now),
        "unit_status": "QUARANTINED",
        "released_at": None,
        "destroyed_at": None,
        "destruction_reason": None,
        "lookback_case_id": None,
    }
    db.stamp_new(unit)
    db.DB["donation_units"][unit["id"]] = unit
    return unit


def move_scheduled_visits_to_no_show(donor_id=None, center_id=None):
    for v in db.DB["donation_visits"].values():
        if v["visit_status"] != "SCHEDULED":
            continue
        if donor_id is not None and v["donor_id"] != donor_id:
            continue
        if center_id is not None and v["center_id"] != center_id:
            continue
        v["visit_status"] = "NO_SHOW"
        db.touch(v)


def expire_scheduled_screenings(center_id=None):
    for v in db.DB["screening_visits"].values():
        if v["visit_status"] != "SCHEDULED":
            continue
        if center_id is not None and v["center_id"] != center_id:
            continue
        v["visit_status"] = "EXPIRED"
        db.touch(v)


def destroy_units(units, reason):
    now = db.now()
    for u in units:
        u["unit_status"] = "DESTROYED"
        u["destroyed_at"] = db.ts(now)
        u["destruction_reason"] = reason
        db.touch(u)


def destroy_units_and_clawback(units, reason):
    """LOOKBACK_HOLD -> DESTROYED with compensation claw-back."""
    now = db.now()
    affected_donors = set()
    for u in units:
        u["unit_status"] = "DESTROYED"
        u["destroyed_at"] = db.ts(now)
        u["destruction_reason"] = reason
        db.touch(u)
        visit = db.DB["donation_visits"].get(u["donation_visit_id"])
        if visit is not None:
            pid = visit.get("compensation_payment_id")
            payment = db.DB["compensation_payments"].get(pid) if pid else None
            if payment is not None and payment["payment_status"] == "FINALIZED":
                payment["payment_status"] = "CLAWED_BACK"
                db.touch(payment)
                affected_donors.add(payment["donor_id"])
    for donor_id in affected_donors:
        recompute_ytd(donor_id)


def resolve_cases_after_mass_destroy(donor_id):
    """After a cascade destroys LOOKBACK_HOLD units, resolve any case whose
    held units are now all destroyed."""
    for case in db.DB["lookback_cases"].values():
        if case["donor_id"] != donor_id or case["case_status"] != "UNITS_QUARANTINED":
            continue
        held = [
            u for u in db.DB["donation_units"].values()
            if u.get("lookback_case_id") == case["id"] and u["unit_status"] == "LOOKBACK_HOLD"
        ]
        if not held:
            case["case_status"] = "RESOLVED_DESTROYED"
            case["resolved_at"] = db.ts()
            db.touch(case)


def promote_donor_to_qualified(donor):
    """APPLICANT -> QUALIFIED cascade (SCAFFOLD 1.2 Donor transitions)."""
    now = db.now()
    donor["donor_status"] = "QUALIFIED"
    db.touch(donor)
    # Release QUARANTINED units whose triggering visit's screening had no
    # reactive viral marker.
    for u in db.DB["donation_units"].values():
        if u["donor_id"] != donor["id"] or u["unit_status"] != "QUARANTINED":
            continue
        visit = db.DB["donation_visits"].get(u["donation_visit_id"])
        reactive = False
        if visit is not None:
            vm = sub_record_of_type(visit["screening_visit_id"], "VIRAL_MARKER")
            if vm is not None and vm["outcome"] == "FAIL":
                reactive = True
        if not reactive:
            u["unit_status"] = "RELEASED"
            u["released_at"] = db.ts(now)
            db.touch(u)
    write_snapshot(donor["home_center_id"], "donor.qualified")


def open_lookback_case(donor, sub_record, now):
    """Viral-marker FAIL cascade (SCAFFOLD 1.2 ScreeningVisit FAILED side effects)."""
    triggering_donation_visit_id = None
    for v in db.DB["donation_visits"].values():
        if v["screening_visit_id"] == sub_record["screening_visit_id"]:
            triggering_donation_visit_id = v["id"]
            break
    case = {
        "id": db.next_id(),
        "donor_id": donor["id"],
        "triggering_screening_sub_record_id": sub_record["id"],
        "triggering_donation_visit_id": triggering_donation_visit_id,
        "lookback_window_days": LOOKBACK_WINDOW_DAYS,
        "case_status": "OPEN",
        "opened_at": db.ts(now),
        "resolved_at": None,
    }
    db.stamp_new(case)
    db.DB["lookback_cases"][case["id"]] = case

    window_start = now - timedelta(days=LOOKBACK_WINDOW_DAYS)
    moved = 0
    for u in db.DB["donation_units"].values():
        if u["donor_id"] != donor["id"]:
            continue
        if u["unit_status"] not in ("QUARANTINED", "RELEASED"):
            continue
        ca = db.parse_dt(u["collected_at"])
        if ca is None or not (window_start <= ca <= now):
            continue
        u["unit_status"] = "LOOKBACK_HOLD"
        u["lookback_case_id"] = case["id"]
        db.touch(u)
        moved += 1

    case["case_status"] = "UNITS_QUARANTINED"
    db.touch(case)
    if moved == 0:
        case["case_status"] = "RESOLVED_DESTROYED"
        case["resolved_at"] = case["opened_at"]
        db.touch(case)
    return case


def auto_file_severe_deferral(donor, center_id, now):
    """SEVERE adverse reaction auto-deferral (PRD 3.9)."""
    ends = now + timedelta(days=SEVERE_REACTION_DEFERRAL_DAYS)
    entry = {
        "id": db.next_id(),
        "donor_id": donor["id"],
        "reason_code": "ADVERSE_REACTION_SEVERE",
        "deferral_type": "TEMPORARY",
        "deferral_ends_on": db.ts(ends),
        "source_center_id": center_id,
        "filed_by_user_id": "system",
        "registry_status": "ACTIVE",
        "override_rationale": None,
    }
    db.stamp_new(entry)
    db.DB["deferral_registry_entries"][entry["id"]] = entry

    donor["donor_status"] = "DEFERRED_TEMP"
    donor["active_deferral_id"] = entry["id"]
    donor["deferral_ends_on"] = entry["deferral_ends_on"]
    donor["deferred_reason_code"] = entry["reason_code"]
    db.touch(donor)
    move_scheduled_visits_to_no_show(donor_id=donor["id"])
    return entry


# ---------------------------------------------------------------------------
# Scheduled (time-based) transitions — fired on clock set, chronological order
# ---------------------------------------------------------------------------
def run_scheduled_transitions():
    now = db.now()
    while True:
        candidates = []
        for v in db.DB["screening_visits"].values():
            if v["visit_status"] in ("SCHEDULED", "IN_PROGRESS"):
                sf = v.get("_scheduled_for_dt")
                if sf is not None and now >= sf + SCREENING_EXPIRY:
                    candidates.append((sf + SCREENING_EXPIRY, "screening_expire", v))
        for v in db.DB["donation_visits"].values():
            if v["visit_status"] == "SCHEDULED":
                sf = v.get("_scheduled_for_dt")
                if sf is not None and now >= sf + DONATION_NO_SHOW:
                    candidates.append((sf + DONATION_NO_SHOW, "donation_no_show", v))
        for e in db.DB["deferral_registry_entries"].values():
            if e["registry_status"] == "ACTIVE" and e["deferral_type"] == "TEMPORARY":
                ends = db.parse_dt(e["deferral_ends_on"])
                if ends is not None and now >= ends:
                    candidates.append((ends, "deferral_clear", e))
        if not candidates:
            break
        candidates.sort(key=lambda c: c[0])
        _, kind, obj = candidates[0]
        if kind == "screening_expire":
            obj["visit_status"] = "EXPIRED"
            db.touch(obj)
            write_snapshot(obj["center_id"], "screening.expired")
        elif kind == "donation_no_show":
            obj["visit_status"] = "NO_SHOW"
            db.touch(obj)
        elif kind == "deferral_clear":
            donor = db.DB["donors"].get(obj["donor_id"])
            obj["registry_status"] = "CLEARED"
            db.touch(obj)
            if donor is not None and donor.get("active_deferral_id") == obj["id"]:
                donor["active_deferral_id"] = None
                donor["deferral_ends_on"] = None
                donor["deferred_reason_code"] = None
                if donor["donor_status"] == "DEFERRED_TEMP":
                    donor["donor_status"] = (
                        "APPLICANT" if donor["lifetime_donation_count"] == 0 else "QUALIFIED"
                    )
                db.touch(donor)


def assert_center_operational(center):
    if center["status"] != "OPERATIONAL":
        raise errors.err_center_not_operational()
