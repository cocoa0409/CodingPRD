"""Business logic: calculations (PRD scaffold 1.3), conserved ledgers
(section 2.10), cascades, and the three ordered clock sweeps (section 2.5).
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C
import db
import logical_clock


# ---------- drive time (calculation: drive_time_minutes) ----------

def haversine_miles(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * C.EARTH_RADIUS_MI * math.asin(math.sqrt(a))


def drive_minutes(veteran, station, geo_classification):
    d = haversine_miles(
        veteran["home_latitude"], veteran["home_longitude"],
        station["latitude"], station["longitude"],
    )
    if geo_classification == "URBAN":
        minutes = d * C.URBAN_CIRCUITY / C.URBAN_SPEED_MPH * 60
    else:  # RURAL
        minutes = d * C.RURAL_CIRCUITY / C.RURAL_SPEED_MPH * 60
    return float(Decimal(repr(minutes)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_eligibility(veteran, station, service_code, service_category, drive_time, choice_requested):
    wait_days = (station["primary_wait_days"] if service_category == "PRIMARY_CARE"
                 else station["specialty_wait_days"])
    service_available = service_code in station["service_codes"]
    drive_standard = (C.DRIVE_TIME_STANDARD_PRIMARY_MIN if service_category == "PRIMARY_CARE"
                      else C.DRIVE_TIME_STANDARD_SPECIALTY_MIN)
    wait_standard = (C.WAIT_TIME_STANDARD_PRIMARY_DAYS if service_category == "PRIMARY_CARE"
                     else C.WAIT_TIME_STANDARD_SPECIALTY_DAYS)
    drive_failed = drive_time > drive_standard  # strict; exactly equal passes
    wait_failed = wait_days > wait_standard     # strict; exactly equal passes
    choice_granted = bool(choice_requested) and veteran["priority_group"] <= C.CHOICE_PRIORITY_MAX
    eligible = (not service_available) or drive_failed or wait_failed or choice_granted
    return {
        "wait_days": wait_days,
        "service_available": service_available,
        "drive_standard_failed": drive_failed,
        "wait_standard_failed": wait_failed,
        "choice_granted": choice_granted,
        "eligible": eligible,
    }


# ---------- episode window / visit ledger (sections 2.10, 3.3) ----------

def recompute_remaining(auth):
    auth["remaining_visits"] = (auth["authorized_visits"] + auth["extended_visits"]
                                - auth["completed_visits"] - auth["reserved_visits"])


def recompute_end_date(auth):
    start = logical_clock.parse_date(auth["start_date"])
    extra = sum(
        e["requested_extra_days"]
        for e in db.all_recs("extension_requests")
        if e["referral_authorization_id"] == auth["id"] and e["status"] == "APPROVED"
    )
    end = start + timedelta(days=auth["duration_days"] + extra)
    auth["end_date_exclusive"] = end.isoformat()


def date_in_episode(auth, d):
    return auth["start_date"] <= d.isoformat() < auth["end_date_exclusive"]


# ---------- documentation helpers (section 3.6) ----------

def docs_pending_for_auth(auth_id):
    return any(
        d["referral_authorization_id"] == auth_id
        and d["status"] in ("AWAITED", "RECEIVED", "OVERDUE")
        for d in db.all_recs("documentations")
    )


def maybe_close(auth):
    """EXPIRED/EXHAUSTED with no non-accepted documentation -> CLOSED."""
    if auth["status"] in ("EXPIRED", "EXHAUSTED") and not docs_pending_for_auth(auth["id"]):
        auth["status"] = "CLOSED"
        db.touch(auth)


def maybe_exhaust(auth):
    """ACTIVE with remaining_visits == 0 -> EXHAUSTED (then maybe CLOSED)."""
    if auth["status"] == "ACTIVE" and auth["remaining_visits"] == 0:
        auth["status"] = "EXHAUSTED"
        db.touch(auth)
        maybe_close(auth)


def on_doc_accepted(doc):
    """Acceptance heals: restore a suspended episode, or close a terminal one."""
    auth = db.get("authorizations", doc["referral_authorization_id"])
    if auth is None or docs_pending_for_auth(auth["id"]):
        return
    if auth["status"] == "DOCS_SUSPENDED":
        auth["status"] = auth["docs_suspension_return_state"] or "AUTHORIZED"
        auth["docs_suspension_return_state"] = None
        db.touch(auth)
    elif auth["status"] in ("EXPIRED", "EXHAUSTED"):
        auth["status"] = "CLOSED"
        db.touch(auth)


# ---------- cascades (state-machine side effects) ----------

def cancel_scheduled_appointments(auth):
    """Expiry/cancel cascade link 1: SCHEDULED appointments -> CANCELLED,
    releasing the reserved visit. Touches each appointment; the caller
    touches the authorization once for the aggregate ledger change."""
    for appt in db.all_recs("appointments"):
        if appt["referral_authorization_id"] == auth["id"] and appt["status"] == "SCHEDULED":
            appt["status"] = "CANCELLED"
            db.touch(appt)
            auth["reserved_visits"] -= 1
    recompute_remaining(auth)


def deny_pending_extensions(auth, reason):
    """Cascade link 2: PENDING extension requests -> DENIED (system denial
    does not bump the authorization version)."""
    for ext in db.all_recs("extension_requests"):
        if ext["referral_authorization_id"] == auth["id"] and ext["status"] == "PENDING":
            ext["status"] = "DENIED"
            ext["denial_reason"] = reason
            ext["decided_at"] = logical_clock.now_iso()
            db.touch(ext)


def finalize_tpa_event(tpa, denied):
    """One claim-finalization event: counters, denial_rate (4dp half-up),
    and the auto-suspension check (>= 5 events AND rate strictly > 0.20)."""
    tpa["adjudicated_events"] += 1
    if denied:
        tpa["denied_events"] += 1
    rate = Decimal(0)
    if tpa["adjudicated_events"] > 0:
        rate = (Decimal(tpa["denied_events"]) / Decimal(tpa["adjudicated_events"])
                ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    tpa["denial_rate"] = float(rate)
    if (tpa["contract_status"] == "ACTIVE"
            and tpa["adjudicated_events"] >= C.MIN_ADJUDICATED_EVENTS
            and rate > Decimal(C.DENIAL_RATE_THRESHOLD)):
        tpa["contract_status"] = "SUSPENDED"
    db.touch(tpa)


def decredential_cascade(provider):
    """CREDENTIALED -> DECREDENTIALED: every RECEIVED claim of the provider is
    auto-denied PROVIDER_DECREDENTIALED; each is a TPA finalization event."""
    for claim in db.all_recs("claims"):
        if claim["provider_id"] == provider["id"] and claim["status"] == "RECEIVED":
            claim["status"] = "DENIED"
            claim["denial_reason"] = "PROVIDER_DECREDENTIALED"
            db.touch(claim)
            tpa = db.get("tpas", claim["tpa_id"])
            if tpa is not None:
                finalize_tpa_event(tpa, denied=True)


# ---------- the three ordered sweeps (section 2.5) ----------

def run_sweeps():
    today = logical_clock.today()
    now_iso = logical_clock.now_iso()

    # 1. Episode expiry sweep
    for auth in db.all_recs("authorizations"):
        if (auth["status"] in ("AUTHORIZED", "ACTIVE")
                and auth["end_date_exclusive"] <= today.isoformat()
                and auth["remaining_visits"] > 0):
            auth["status"] = "EXPIRED"
            cancel_scheduled_appointments(auth)
            deny_pending_extensions(auth, "AUTH_CANCELLED")
            recompute_remaining(auth)
            db.touch(auth)
            maybe_close(auth)

    # 2. Documentation overdue sweep (deadline strictly earlier than now)
    for doc in db.all_recs("documentations"):
        if doc["status"] == "AWAITED" and doc["deadline_at"] < now_iso:
            doc["status"] = "OVERDUE"
            db.touch(doc)
            auth = db.get("authorizations", doc["referral_authorization_id"])
            if auth is not None and auth["status"] in ("AUTHORIZED", "ACTIVE"):
                auth["docs_suspension_return_state"] = auth["status"]
                auth["status"] = "DOCS_SUSPENDED"
                deny_pending_extensions(auth, "DOCS_OVERDUE")
                db.touch(auth)

    # 3. Auto-close sweep
    for auth in db.all_recs("authorizations"):
        maybe_close(auth)


# ---------- claim payment (calculation: claim_payment) ----------

def price_claim_lines(service_lines, provider):
    """Per-line allowed/fee/net (fee rounded half-up per line), then summed.
    Pinned order: never sum-then-round."""
    total = 0
    rates = provider.get("contract_rates") or {}
    for line in service_lines:
        if line["service_code"] in rates:
            rate = rates[line["service_code"]]
        elif line["service_category"] == "PRIMARY_CARE":
            rate = C.MEDICARE_BASE_RATE_PRIMARY_CENTS
        else:
            rate = C.MEDICARE_BASE_RATE_SPECIALTY_CENTS
        allowed = min(line["unit_billed_cents"] * line["units"], rate * line["units"])
        fee = int((Decimal(allowed) * Decimal(C.TPA_ADMIN_FEE_RATE)
                   ).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += allowed - fee
    return total


def billed_total(service_lines):
    return sum(line["unit_billed_cents"] * line["units"] for line in service_lines)


# ---------- urgent care copay (calculation: urgent_care_copay) ----------

def priority_band(priority_group):
    if priority_group <= 3:
        return "LOW"
    if priority_group <= 6:
        return "MID"
    return "HIGH"


def urgent_copay_cents(band, visit_index_in_fy):
    lower = visit_index_in_fy <= C.URGENT_VISIT_LOWER_TIER_MAX
    if band == "LOW":
        return C.COPAY_LOW_CENTS
    if band == "MID":
        return C.COPAY_MID_FIRST_CENTS if lower else C.COPAY_MID_REPEAT_CENTS
    return C.COPAY_HIGH_FIRST_CENTS if lower else C.COPAY_HIGH_REPEAT_CENTS
