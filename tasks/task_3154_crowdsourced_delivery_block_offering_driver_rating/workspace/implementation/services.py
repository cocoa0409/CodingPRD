"""Business logic: calculations, recomputes, cascades, and serializers.

All rules trace to PRD §2.6-§2.8 and §3, and SCAFFOLD.yaml §1.3.

Tier visibility lead (documented constant — the PRD only specifies strict
ordering "higher tiers see blocks earlier" without concrete numbers):
    STANDARD -> 240 minutes
    PLUS     -> 360 minutes
    PREMIER  -> 480 minutes
Strictly increasing by tier rank, so higher tiers see blocks earlier.
"""

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err, ERR_NOT_FOUND


# ---------------------------------------------------------------------------
# Documented constants
# ---------------------------------------------------------------------------

# Tier visibility lead in minutes — concrete, PRD-consistent numeric scheme.
# PRD §3.2: "Higher tiers see blocks earlier"; strict ordering across tiers.
TIER_LEAD_MIN = {
    "STANDARD": 240,
    "PLUS": 360,
    "PREMIER": 480,
}

TIER_RANK = {"STANDARD": 1, "PLUS": 2, "PREMIER": 3}
VEHICLE_CLASS_RANK = {"SEDAN": 1, "SUV": 2, "VAN": 3}

TIER_BONUS_BP = {"STANDARD": 0, "PLUS": 500, "PREMIER": 1000}
SURCHARGE_PER_KG_CENTS = 155
LATE_PENALTY_CENTS = 200
PHOTO_PENALTY_CENTS = 150
FAILED_PENALTY_CENTS = 500

SURGE_STEP_30_BP = 17500
SURGE_STEP_60_BP = 15000
SURGE_STEP_120_BP = 12500
SURGE_BASE_BP = 10000

CHECK_IN_EARLY_MINUTES = 30
CHECK_IN_LATE_MINUTES = 15
OFFER_BUFFER_MINUTES = 30

NON_TERMINAL_ASSIGNMENT_STATUSES = {"ASSIGNED", "CHECKED_IN", "ROUTE_ASSIGNED", "IN_DELIVERY"}


def round_half_up(value):
    """Round a Decimal (or value convertible to Decimal) to an integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> 404)
# ---------------------------------------------------------------------------

def get_station_or_404(station_id):
    s = db.stations.get(station_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Station %s not found" % station_id)
    return s


def get_driver_or_404(driver_id):
    d = db.drivers.get(driver_id)
    if d is None:
        raise_err(ERR_NOT_FOUND, "Driver %s not found" % driver_id)
    return d


def get_screening_or_404(screening_id):
    s = db.screenings.get(screening_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "BackgroundScreening %s not found" % screening_id)
    return s


def get_vehicle_or_404(vehicle_id):
    v = db.vehicles.get(vehicle_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "Vehicle %s not found" % vehicle_id)
    return v


def get_block_or_404(block_id):
    b = db.blocks.get(block_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "DeliveryBlock %s not found" % block_id)
    return b


def get_offer_or_404(offer_id):
    o = db.offers.get(offer_id)
    if o is None:
        raise_err(ERR_NOT_FOUND, "BlockOffer %s not found" % offer_id)
    return o


def get_assignment_or_404(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "BlockAssignment %s not found" % assignment_id)
    return a


def get_package_or_404(package_id):
    p = db.packages.get(package_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Package %s not found" % package_id)
    return p


def get_pay_statement_or_404(pay_statement_id):
    ps = db.pay_statements.get(pay_statement_id)
    if ps is None:
        raise_err(ERR_NOT_FOUND, "PayStatement %s not found" % pay_statement_id)
    return ps


def get_appeal_or_404(appeal_id):
    a = db.appeals.get(appeal_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Appeal %s not found" % appeal_id)
    return a


def touch(resource):
    """Refresh updated_at and bump version on a mutation."""
    resource["updated_at"] = db.now_iso()
    resource["version"] += 1


def base_resource():
    ts = db.now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


# ---------------------------------------------------------------------------
# Derived / computed views
# ---------------------------------------------------------------------------

def insurance_status(vehicle):
    """Computed view (PRD §3.1): NONE / ATTESTED / EXPIRED vs the logical date."""
    expires = vehicle.get("insurance_expires_on")
    if expires is None:
        return "NONE"
    current_date = db.now().date().isoformat()
    return "ATTESTED" if expires >= current_date else "EXPIRED"


def estimated_pay_cents(block):
    """estimated_block_pay: round_half_up(base_pay_cents * surge_multiplier_bp / 10000)."""
    return round_half_up(Decimal(block["base_pay_cents"]) * Decimal(block["surge_multiplier_bp"]) / Decimal(10000))


def provisional_pay_cents(block, snapshot_bp):
    """provisional_assignment_pay: gross only, on the frozen surge snapshot."""
    return round_half_up(Decimal(block["base_pay_cents"]) * Decimal(snapshot_bp) / Decimal(10000))


# ---------------------------------------------------------------------------
# Driver aggregates: reliability, rating, tier (PRD §2.8, pinned order)
# ---------------------------------------------------------------------------

def recompute_reliability(driver):
    """reliability_score: -500/forfeit, -1000/no-show, within last 30 days inclusive."""
    now = db.now()
    window_start = now - timedelta(days=30)
    strikes = 0
    for a in db.assignments.values():
        if a["driver_id"] != driver["id"]:
            continue
        if a.get("strike_reversed"):
            continue
        if a["status"] == "FORFEITED" and a.get("forfeited_at"):
            ts = db.parse_iso(a["forfeited_at"])
            if ts >= window_start:
                strikes += 500
        elif a["status"] == "NO_SHOW" and a.get("no_show_at"):
            ts = db.parse_iso(a["no_show_at"])
            if ts >= window_start:
                strikes += 1000
    driver["reliability_score_bp"] = max(0, 10000 - strikes)


def recompute_ratings(driver):
    """rolling_rating (90d inclusive) and lifetime_weighted_rating."""
    now = db.now()
    window_start = now - timedelta(days=90)
    events = [e for e in db.rating_events.values() if e["driver_id"] == driver["id"]]

    in_window = [e for e in events if db.parse_iso(e["event_at"]) >= window_start]
    if in_window:
        avg = Decimal(sum(e["points"] for e in in_window)) / Decimal(len(in_window))
        driver["rating_score_x100"] = round_half_up(avg)
    else:
        driver["rating_score_x100"] = 0

    if events:
        num = Decimal(0)
        den = Decimal(0)
        for e in events:
            age_seconds = (now - db.parse_iso(e["event_at"])).total_seconds()
            age_days = int(age_seconds // 86400)
            if age_days <= 30:
                weight = 100
            elif age_days <= 90:
                weight = 50
            else:
                weight = 25
            num += Decimal(e["points"]) * Decimal(weight)
            den += Decimal(weight)
        driver["lifetime_rating_x100"] = round_half_up(num / den)
    else:
        driver["lifetime_rating_x100"] = 0


def recompute_tier(driver):
    """tier_qualification: derived from the two FRESH values; inclusive thresholds.

    On demotion, OFFERED offers whose tier_floor ranks above the new tier -> REVOKED.
    """
    rating = driver["rating_score_x100"]
    reliability = driver["reliability_score_bp"]
    if rating >= 470 and reliability >= 9500:
        new_tier = "PREMIER"
    elif rating >= 430 and reliability >= 8500:
        new_tier = "PLUS"
    else:
        new_tier = "STANDARD"

    old_tier = driver["rating_tier"]
    driver["rating_tier"] = new_tier

    if TIER_RANK[new_tier] < TIER_RANK[old_tier]:
        for offer in db.offers.values():
            if (
                offer["driver_id"] == driver["id"]
                and offer["status"] == "OFFERED"
                and TIER_RANK[offer["tier_floor"]] > TIER_RANK[new_tier]
            ):
                offer["status"] = "REVOKED"
                touch(offer)
    return new_tier


def recompute_driver_aggregates(driver, rating_changed=False, reliability_changed=False):
    """Pinned evaluation order: reliability first, then rating, then tier."""
    if reliability_changed:
        recompute_reliability(driver)
    if rating_changed:
        recompute_ratings(driver)
    recompute_tier(driver)


def recompute_station_liabilities(station):
    """pay_liabilities_aggregation: SUM(final_pay_cents) over SETTLED statements
    of assignments of this station's blocks."""
    total = 0
    for ps in db.pay_statements.values():
        if ps["status"] != "SETTLED":
            continue
        assignment = db.assignments.get(ps["assignment_id"])
        if assignment is None:
            continue
        block = db.blocks.get(assignment["block_id"])
        if block is not None and block["station_id"] == station["id"]:
            total += ps["final_pay_cents"]
    station["pay_liabilities_cents"] = total


# ---------------------------------------------------------------------------
# Acceptance helpers (shared by first-come and offer acceptance)
# ---------------------------------------------------------------------------

def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end).
    Adjacency (end == start) is allowed."""
    return a_start < b_end and b_start < a_end


def check_window_overlap(driver_id, block):
    """Reject when the driver holds a non-terminal assignment whose block window
    overlaps this block's window (half-open semantics)."""
    for a in db.assignments.values():
        if a["driver_id"] != driver_id or a["status"] not in NON_TERMINAL_ASSIGNMENT_STATUSES:
            continue
        other = db.blocks.get(a["block_id"])
        if other is None:
            continue
        if windows_overlap(
            db.parse_iso(other["starts_at"]), db.parse_iso(other["ends_at"]),
            db.parse_iso(block["starts_at"]), db.parse_iso(block["ends_at"]),
        ):
            return True
    return False


def relist_block(block):
    """DeliveryBlock -> PUBLISHED relist: assigned_driver_id cleared; surge and
    estimated pay retained (not reset)."""
    block["status"] = "PUBLISHED"
    block["assigned_driver_id"] = None
    touch(block)


def forfeit_assignment(assignment, cause, recompute_driver=True):
    """FORFEITED transition + cascade: relist, reliability/tier recompute,
    tier-floor offer revocation (via recompute_tier).

    When recompute_driver is False (deactivation cascade), the caller performs
    a single aggregate recompute after all forfeits land.
    """
    assignment["status"] = "FORFEITED"
    assignment["forfeit_cause"] = cause
    assignment["forfeited_at"] = db.now_iso()
    assignment["strike_reversed"] = False
    touch(assignment)

    block = db.blocks.get(assignment["block_id"])
    if block is not None:
        relist_block(block)

    if recompute_driver:
        driver = db.drivers.get(assignment["driver_id"])
        if driver is not None:
            recompute_driver_aggregates(driver, reliability_changed=True)
            driver["updated_at"] = db.now_iso()
            driver["version"] += 1


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_station(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "zone_code": s["zone_code"],
        "surge_enabled": s["surge_enabled"],
        "pay_liabilities_cents": s["pay_liabilities_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_driver(d):
    return {
        "id": d["id"],
        "legal_name": d["legal_name"],
        "email": d["email"],
        "status": d["status"],
        "rating_tier": d["rating_tier"],
        "rating_score_x100": d["rating_score_x100"],
        "lifetime_rating_x100": d["lifetime_rating_x100"],
        "reliability_score_bp": d["reliability_score_bp"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_screening(s):
    return {
        "id": s["id"],
        "driver_id": s["driver_id"],
        "status": s["status"],
        "failure_reason": s["failure_reason"],
        "decided_at": s["decided_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_vehicle(v):
    return {
        "id": v["id"],
        "driver_id": v["driver_id"],
        "vin": v["vin"],
        "vehicle_class": v["vehicle_class"],
        "insurance_expires_on": v["insurance_expires_on"],
        "insurance_status": insurance_status(v),
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_block(b):
    return {
        "id": b["id"],
        "station_id": b["station_id"],
        "starts_at": b["starts_at"],
        "ends_at": b["ends_at"],
        "required_vehicle_class": b["required_vehicle_class"],
        "base_pay_cents": b["base_pay_cents"],
        "surge_multiplier_bp": b["surge_multiplier_bp"],
        "estimated_pay_cents": b["estimated_pay_cents"],
        "status": b["status"],
        "assigned_driver_id": b["assigned_driver_id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_offer(o):
    return {
        "id": o["id"],
        "block_id": o["block_id"],
        "driver_id": o["driver_id"],
        "tier_floor": o["tier_floor"],
        "expires_at": o["expires_at"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_assignment(a):
    return {
        "id": a["id"],
        "block_id": a["block_id"],
        "driver_id": a["driver_id"],
        "offer_id": a["offer_id"],
        "vehicle_id": a["vehicle_id"],
        "status": a["status"],
        "surge_multiplier_snapshot_bp": a["surge_multiplier_snapshot_bp"],
        "tier_at_accept": a["tier_at_accept"],
        "provisional_pay_cents": a["provisional_pay_cents"],
        "check_in_at": a["check_in_at"],
        "forfeited_at": a["forfeited_at"],
        "no_show_at": a["no_show_at"],
        "forfeit_cause": a["forfeit_cause"],
        "strike_reversed": a["strike_reversed"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_package(p):
    return {
        "id": p["id"],
        "assignment_id": p["assignment_id"],
        "tracking_code": p["tracking_code"],
        "billable_weight_kg": p["billable_weight_kg"],
        "promised_by": p["promised_by"],
        "status": p["status"],
        "delivered_at": p["delivered_at"],
        "photo_url": p["photo_url"],
        "photo_gps_tagged": p["photo_gps_tagged"],
        "photo_compliant": p["photo_compliant"],
        "on_time_delivery": p["on_time_delivery"],
        "failure_reason": p["failure_reason"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_rating_event(e):
    return {
        "id": e["id"],
        "driver_id": e["driver_id"],
        "assignment_id": e["assignment_id"],
        "event_type": e["event_type"],
        "points": e["points"],
        "event_at": e["event_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_pay_statement(ps):
    return {
        "id": ps["id"],
        "assignment_id": ps["assignment_id"],
        "status": ps["status"],
        "gross_cents": ps["gross_cents"],
        "tier_bonus_cents": ps["tier_bonus_cents"],
        "surcharges_cents": ps["surcharges_cents"],
        "penalties_cents": ps["penalties_cents"],
        "final_pay_cents": ps["final_pay_cents"],
        "tier_applied": ps["tier_applied"],
        "settled_at": ps["settled_at"],
        "voided_at": ps["voided_at"],
        "created_at": ps["created_at"],
        "updated_at": ps["updated_at"],
        "version": ps["version"],
    }


def serialize_appeal(a):
    return {
        "id": a["id"],
        "driver_id": a["driver_id"],
        "reason": a["reason"],
        "status": a["status"],
        "evidence_count": a["evidence_count"],
        "decision_reason": a["decision_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }
