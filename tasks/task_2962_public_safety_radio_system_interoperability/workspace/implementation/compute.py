"""Derived-field recomputation, cascades and the twelve named calculations."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db

# --- fee schedule (PRD 3.9) ------------------------------------------------
TIER1_LIMIT = 50
TIER2_LIMIT = 200
TIER1_RATE_CENTS = 4200
TIER2_RATE_CENTS = 3600
TIER3_RATE_CENTS = 3100
PATCH_AUTHORITY_SURCHARGE_BP = 800
LATE_FEE_BP = 150
PAYMENT_GRACE_DAYS = 30
VOTING_SUSPENSION_GRACE_DAYS = 60
MAX_FEE_PERIOD_DAYS = 366

# --- governance -----------------------------------------------------------
VOTE_WEIGHT_CAP = 5
SUBSCRIBERS_PER_EXTRA_VOTE = 250
QUORUM_NUMERATOR = 3
QUORUM_DENOMINATOR = 5

# --- coverage -------------------------------------------------------------
TIER_A_MIN_RAW = Decimal("97.00")
TIER_B_MIN_RAW = Decimal("90.00")
DERATE = {"A": Decimal("0.5"), "B": Decimal("1.5"), "C": Decimal("3.0")}
BATTERY_ONLY_PENALTY_PP = Decimal("2.0")
MISSION_CRITICAL_MIN = Decimal("97.0")
GENERAL_MIN = Decimal("90.0")

# --- capacity -------------------------------------------------------------
CONTROL_CHANNELS_RESERVED = 1
SURGE_RESERVE_PCT = 25
MAX_RESERVED_TALKPATHS = 4
PRIORITY_CLASS_MAX = 3

# --- backup power / escalation -------------------------------------------
TIER3_MAX_MINUTES = 30
TIER2_MAX_MINUTES = 60
TIER1_MAX_MINUTES = 120

# --- maintenance ----------------------------------------------------------
MAINTENANCE_BUFFER_MINUTES = 45
MAINTENANCE_CONCURRENCY_CAP = 2

# --- retention ------------------------------------------------------------
STATUTORY_RETENTION_DAYS = {
    "LAW": 180,
    "FIRE": 90,
    "EMS": 90,
    "PUBLIC_WORKS": 30,
    "REGIONAL_AUTHORITY": 365,
}
PATCH_RETENTION_MIN_DAYS = 180

NEXT_GEN_STANDARDS = ("P25_PHASE2", "NG_LMR")
BILLABLE_STATUSES = ("ASSIGNED", "SUSPENDED")
LIVE_TALKGROUP_STATUSES = ("ACTIVE", "LOCKED")
OPEN_PATCH_STATUSES = ("REQUESTED", "ACTIVE")
REVISION_LIMIT = 2


def rh(value, dp):
    """Round half up to `dp` decimal places."""
    quant = Decimal(1).scaleb(-dp)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def rh_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply_fields(row, **changes):
    """Write fields; refresh updated_at / version only when something changed."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        db.touch(row)
    return changed


# ---------------------------------------------------------------------------
# Derived counters (PRD 2.7)
# ---------------------------------------------------------------------------
def agency_units(agency_id):
    return [u for u in db.store.units.values() if u["agency_id"] == agency_id]


def recompute_vote_weight(agency):
    """PRD 3.9 governance_vote_weight."""
    if agency["billing_status"] == "SUSPENDED_FROM_VOTING":
        apply_fields(agency, governance_vote_weight=0, voting_eligible=False)
        return
    blocks = agency["billable_subscriber_count"] // SUBSCRIBERS_PER_EXTRA_VOTE
    weight = min(1 + blocks, VOTE_WEIGHT_CAP)
    apply_fields(agency, governance_vote_weight=weight, voting_eligible=True)


def recompute_billable_count(agency):
    count = 0
    for unit in db.store.units.values():
        if unit["agency_id"] == agency["id"] and unit["provision_status"] in BILLABLE_STATUSES:
            count += 1
    apply_fields(agency, billable_subscriber_count=count)
    recompute_vote_weight(agency)


def recompute_active_patch_request_count(agency):
    count = 0
    for patch in db.store.patches.values():
        if patch["requesting_agency_id"] == agency["id"] and patch["status"] in OPEN_PATCH_STATUSES:
            count += 1
    apply_fields(agency, active_patch_request_count=count)


def recompute_talkgroup_patch_count(talkgroup):
    count = 0
    for patch in db.store.patches.values():
        if patch["status"] not in OPEN_PATCH_STATUSES:
            continue
        if talkgroup["id"] in (patch["source_talkgroup_id"], patch["target_talkgroup_id"]):
            count += 1
    apply_fields(talkgroup, active_patch_count=count)


def recompute_template_deployed_count(template):
    count = 0
    for unit in db.store.units.values():
        if unit["template_id"] == template["id"]:
            count += 1
    apply_fields(template, deployed_unit_count=count)


def recompute_keyset_loaded_count(keyset):
    count = 0
    for unit in db.store.units.values():
        if unit["active_keyset_id"] == keyset["id"] and unit["key_status"] == "KEYED":
            count += 1
    apply_fields(keyset, loaded_unit_count=count)


def recompute_site_counters(site):
    """busy_talkpaths, peak_talkpaths, granted/busied counts, grade_of_service_pct."""
    busy = 0
    granted = 0
    busied = 0
    for req in db.store.talkpaths.values():
        if req["site_id"] != site["id"]:
            continue
        outcome = req["outcome"]
        if outcome == "GRANTED" and req["released_at"] is None:
            busy += 1
        if outcome in ("GRANTED", "PREEMPTED", "RELEASED"):
            granted += 1
        elif outcome == "BUSIED":
            busied += 1
    peak = max(site["peak_talkpaths"], busy)
    total = granted + busied
    if total == 0:
        gos = Decimal("100.0")
    else:
        gos = rh(Decimal(100) * Decimal(granted) / Decimal(total), 1)
    apply_fields(
        site,
        busy_talkpaths=busy,
        peak_talkpaths=peak,
        granted_request_count=granted,
        busied_request_count=busied,
        grade_of_service_pct=gos,
    )


# ---------------------------------------------------------------------------
# Patch duration and patch release (PRD 3.6)
# ---------------------------------------------------------------------------
def patch_duration_minutes(patch):
    activated = patch["activated_at"]
    released = patch["released_at"]
    if activated is None or released is None:
        return None
    seconds = (released - activated).total_seconds()
    if seconds < 0:
        seconds = 0
    return int(seconds // 60)


def release_patches(patches, reason):
    """Release a batch of patches and recompute every counter they touch."""
    talkgroup_ids = set()
    agency_ids = set()
    for patch in patches:
        patch["status"] = "RELEASED"
        patch["released_at"] = db.now()
        patch["release_reason"] = reason
        patch["duration_minutes"] = patch_duration_minutes(patch)
        db.touch(patch)
        talkgroup_ids.add(patch["source_talkgroup_id"])
        talkgroup_ids.add(patch["target_talkgroup_id"])
        agency_ids.add(patch["requesting_agency_id"])
    recompute_after_patch_change(talkgroup_ids, agency_ids)


def recompute_after_patch_change(talkgroup_ids, agency_ids):
    for tg_id in talkgroup_ids:
        talkgroup = db.store.talkgroups.get(tg_id)
        if talkgroup is not None:
            recompute_talkgroup_patch_count(talkgroup)
    for agency_id in agency_ids:
        agency = db.store.agencies.get(agency_id)
        if agency is not None:
            recompute_active_patch_request_count(agency)


def open_patches_naming(talkgroup_ids):
    ids = set(talkgroup_ids)
    found = [
        p for p in db.store.patches.values()
        if p["status"] in OPEN_PATCH_STATUSES
        and (p["source_talkgroup_id"] in ids or p["target_talkgroup_id"] in ids)
    ]
    return db.sort_rows(found)


# ---------------------------------------------------------------------------
# Coverage reliability (PRD 3.2)
# ---------------------------------------------------------------------------
def recompute_coverage(site):
    total = site["total_test_points"]
    covered = site["covered_test_points"]
    if total == 0:
        site["coverage_reliability_pct"] = Decimal("0.0")
        site["coverage_derate_tier"] = "NONE"
        site["coverage_class"] = "UNRATED"
        return
    raw = rh(Decimal(100) * Decimal(covered) / Decimal(total), 2)
    if raw >= TIER_A_MIN_RAW:
        tier = "A"
    elif raw >= TIER_B_MIN_RAW:
        tier = "B"
    else:
        tier = "C"
    penalty = BATTERY_ONLY_PENALTY_PP if site["backup_power_type"] == "BATTERY_ONLY" else Decimal("0")
    derated = rh(raw - DERATE[tier] - penalty, 1)
    if derated < 0:
        derated = Decimal("0.0")
    if derated >= MISSION_CRITICAL_MIN:
        klass = "MISSION_CRITICAL"
    elif derated >= GENERAL_MIN:
        klass = "GENERAL"
    else:
        klass = "MARGINAL"
    site["coverage_reliability_pct"] = derated
    site["coverage_derate_tier"] = tier
    site["coverage_class"] = klass


# ---------------------------------------------------------------------------
# Backup power runtime and escalation tier (PRD 3.7)
# ---------------------------------------------------------------------------
def backup_minutes_remaining(site, detected_at):
    capacity = site["battery_runtime_minutes"]
    if site["backup_power_type"] == "GENERATOR":
        capacity += rh_int(Decimal(site["generator_fuel_hours"]) * 60)
    elapsed_seconds = (db.now() - detected_at).total_seconds()
    if elapsed_seconds < 0:
        elapsed_seconds = 0
    elapsed = int(elapsed_seconds // 60)
    remaining = capacity - elapsed
    return remaining if remaining > 0 else 0


def escalation_tier_for(remaining):
    if remaining <= TIER3_MAX_MINUTES:
        return 3
    if remaining <= TIER2_MAX_MINUTES:
        return 2
    if remaining <= TIER1_MAX_MINUTES:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Billing status, the sanction cascade, fees and payments (PRD 3.9)
# ---------------------------------------------------------------------------
def recompute_billing_status(agency):
    balance = agency["fee_balance_cents"]
    due = agency["payment_due_at"]
    if balance <= 0:
        target = "CURRENT"
    elif due is not None and db.now() >= due + timedelta(days=VOTING_SUSPENSION_GRACE_DAYS):
        target = "SUSPENDED_FROM_VOTING"
    elif due is not None and db.now() >= due:
        target = "DELINQUENT"
    else:
        target = "CURRENT"
    apply_fields(agency, billing_status=target)
    recompute_vote_weight(agency)
    if target == "SUSPENDED_FROM_VOTING":
        sanction_cascade(agency)


def sanction_cascade(agency):
    """Four linked consequences of landing in SUSPENDED_FROM_VOTING."""
    apply_fields(agency, governance_vote_weight=0, voting_eligible=False)
    if agency["interop_privilege"] == "PATCH_AUTHORITY":
        apply_fields(agency, interop_privilege="MONITOR")
    doomed = db.sort_rows([
        p for p in db.store.patches.values()
        if p["requesting_agency_id"] == agency["id"] and p["status"] in OPEN_PATCH_STATUSES
    ])
    if doomed:
        release_patches(doomed, "PRIVILEGE_REVOKED")
    recompute_active_patch_request_count(agency)


def period_midnights(period_start, period_end):
    """Every UTC midnight m with period_start <= m < period_end."""
    first = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if first < period_start:
        first = first + timedelta(days=1)
    out = []
    cursor = first
    while cursor < period_end:
        out.append(cursor)
        cursor = cursor + timedelta(days=1)
    return out


def period_length_days(period_start, period_end):
    return int((period_end - period_start).total_seconds() // 86400)


def unit_days_in_service(unit, period_start, period_end):
    assigned = unit["assigned_at"]
    if assigned is None:
        return 0
    retired = unit["retired_at"]
    days = 0
    for midnight in period_midnights(period_start, period_end):
        if assigned <= midnight and (retired is None or retired > midnight):
            days += 1
    return days


def snapshot_tier_subtotal(headcount):
    first = Decimal(min(headcount, TIER1_LIMIT)) * TIER1_RATE_CENTS
    second_count = min(headcount, TIER2_LIMIT) - TIER1_LIMIT
    if second_count < 0:
        second_count = 0
    second = Decimal(second_count) * TIER2_RATE_CENTS
    third_count = headcount - TIER2_LIMIT
    if third_count < 0:
        third_count = 0
    third = Decimal(third_count) * TIER3_RATE_CENTS
    return rh_int(first) + rh_int(second) + rh_int(third)


def rank_rate_cents(rank):
    if rank <= TIER1_LIMIT:
        return TIER1_RATE_CENTS
    if rank <= TIER2_LIMIT:
        return TIER2_RATE_CENTS
    return TIER3_RATE_CENTS


def agency_fee_assessment(agency, period_start, period_end):
    """Steps one to four of the assessment; returns the total assessed cents."""
    period_days = period_length_days(period_start, period_end)
    candidates = db.sort_rows([
        u for u in agency_units(agency["id"])
        if u["provision_status"] in ("ASSIGNED", "SUSPENDED", "RETIRED")
    ])
    # days_in_service_last_period is rewritten under either basis
    for unit in candidates:
        apply_fields(
            unit,
            days_in_service_last_period=unit_days_in_service(unit, period_start, period_end),
        )
    if agency["fee_basis"] == "SNAPSHOT":
        headcount = 0
        for unit in agency_units(agency["id"]):
            if unit["provision_status"] in BILLABLE_STATUSES:
                headcount += 1
        tier_subtotal = snapshot_tier_subtotal(headcount)
    else:
        tier_subtotal = 0
        for index, unit in enumerate(candidates):
            rate = rank_rate_cents(index + 1)
            days = unit["days_in_service_last_period"]
            if period_days <= 0 or days == 0:
                tier_subtotal += 0
                continue
            tier_subtotal += rh_int(Decimal(rate) * Decimal(days) / Decimal(period_days))
    if agency["interop_privilege"] == "PATCH_AUTHORITY":
        surcharge = rh_int(Decimal(tier_subtotal) * Decimal(PATCH_AUTHORITY_SURCHARGE_BP) / Decimal(10000))
    else:
        surcharge = 0
    prior_balance = agency["fee_balance_cents"]
    if prior_balance > 0:
        late_fee = rh_int(Decimal(prior_balance) * Decimal(LATE_FEE_BP) / Decimal(10000))
    else:
        late_fee = 0
    return tier_subtotal + surcharge + late_fee


def governance_standing(agency):
    total_eligible = 0
    for other in db.store.agencies.values():
        if other["voting_eligible"]:
            total_eligible += other["governance_vote_weight"]
    quorum = int(
        (Decimal(QUORUM_NUMERATOR) * Decimal(total_eligible) / Decimal(QUORUM_DENOMINATOR))
        .quantize(Decimal(1), rounding=ROUND_CEILING)
    )
    return {
        "agency_id": agency["id"],
        "billing_status": agency["billing_status"],
        "billable_subscriber_count": agency["billable_subscriber_count"],
        "governance_vote_weight": agency["governance_vote_weight"],
        "voting_eligible": agency["voting_eligible"],
        "total_eligible_weight": total_eligible,
        "quorum_weight_required": quorum,
    }


# ---------------------------------------------------------------------------
# Keyset compromise cascade (PRD 3.5)
# ---------------------------------------------------------------------------
def agency_has_keyed_unit(agency_id):
    for unit in db.store.units.values():
        if unit["agency_id"] == agency_id and unit["key_status"] == "KEYED":
            return True
    return False


def compromise_cascade(keyset):
    # 1. keyed radios holding the bad key go stale (they keep the keyset id)
    stale_units = db.sort_rows([
        u for u in db.store.units.values()
        if u["active_keyset_id"] == keyset["id"] and u["key_status"] == "KEYED"
    ])
    for unit in stale_units:
        apply_fields(unit, key_status="KEY_STALE")
    # 2. encrypted talkgroups whose owner has no keyed radio left lock
    newly_locked = []
    for talkgroup in db.sort_rows(list(db.store.talkgroups.values())):
        if talkgroup["encryption_mode"] != "ENCRYPTED" or talkgroup["status"] != "ACTIVE":
            continue
        if agency_has_keyed_unit(talkgroup["owner_agency_id"]):
            continue
        apply_fields(talkgroup, status="LOCKED", lock_reason="KEY_COMPROMISE")
        newly_locked.append(talkgroup)
    # 3/4. patches riding on the newly locked talkgroups drop
    if newly_locked:
        doomed = open_patches_naming([t["id"] for t in newly_locked])
        if doomed:
            release_patches(doomed, "KEY_COMPROMISE")
    # 5. scheduled campaigns for the compromised keyset abort
    for campaign in db.sort_rows(list(db.store.campaigns.values())):
        if campaign["keyset_id"] == keyset["id"] and campaign["status"] == "SCHEDULED":
            apply_fields(campaign, status="ABORTED")


# ---------------------------------------------------------------------------
# Talkpath allocation (PRD 3.8)
# ---------------------------------------------------------------------------
def usable_channels(site):
    return site["channel_capacity"] - CONTROL_CHANNELS_RESERVED


def talkpath_headroom(site):
    usable = usable_channels(site)
    available = usable - site["busy_talkpaths"]
    if site["capacity_mode"] == "NORMAL":
        reserve = 0
    else:
        reserve = min(usable * SURGE_RESERVE_PCT // 100, MAX_RESERVED_TALKPATHS)
    return available, reserve


def preemption_candidates(site_id):
    """NORMAL grants still held on the site, least important first."""
    candidates = [
        r for r in db.store.talkpaths.values()
        if r["site_id"] == site_id
        and r["outcome"] == "GRANTED"
        and r["released_at"] is None
        and r["request_kind"] == "NORMAL"
    ]
    return sorted(
        candidates,
        key=lambda r: (-r["priority_class_at_grant"], r["created_at"], r["_seq"]),
    )


def hold_seconds_for(request):
    granted = request["granted_at"]
    released = request["released_at"]
    if granted is None or released is None:
        return None
    seconds = (released - granted).total_seconds()
    if seconds < 0:
        seconds = 0
    return int(seconds // 1)


def preempt_request(request):
    request["outcome"] = "PREEMPTED"
    request["released_at"] = db.now()
    request["hold_seconds"] = hold_seconds_for(request)
    db.touch(request)


# ---------------------------------------------------------------------------
# Recorder retention (PRD 2.10)
# ---------------------------------------------------------------------------
def retention_floor(agency):
    floor = STATUTORY_RETENTION_DAYS.get(agency["agency_type"], 0)
    if agency["interop_privilege"] == "PATCH_AUTHORITY":
        floor = max(floor, PATCH_RETENTION_MIN_DAYS)
    return floor


# ---------------------------------------------------------------------------
# Migration readiness (PRD 3.9)
# ---------------------------------------------------------------------------
def agency_has_pending_ng_change(agency_id):
    for change in db.store.change_requests.values():
        if change["target_agency_id"] != agency_id:
            continue
        if change["status"] not in ("APPROVED", "DEPLOYING"):
            continue
        template = db.store.templates.get(change["template_id"])
        if template is not None and template["target_standard"] in NEXT_GEN_STANDARDS:
            return True
    return False


def unit_is_strictly_ready(unit):
    if unit["provision_status"] != "ASSIGNED":
        return False
    if unit["key_status"] != "KEYED":
        return False
    if unit["template_id"] is None:
        return False
    template = db.store.templates.get(unit["template_id"])
    return template is not None and template["target_standard"] in NEXT_GEN_STANDARDS


def migration_readiness(basis, agency_id):
    scope = [
        u for u in db.store.units.values()
        if u["provision_status"] in BILLABLE_STATUSES
        and (agency_id is None or u["agency_id"] == agency_id)
    ]
    evaluated = len(scope)
    planned_cache = {}
    ready = 0
    for unit in scope:
        if unit_is_strictly_ready(unit):
            ready += 1
            continue
        if basis == "PLANNED" and unit["provision_status"] == "ASSIGNED":
            owner = unit["agency_id"]
            if owner not in planned_cache:
                planned_cache[owner] = agency_has_pending_ng_change(owner)
            if planned_cache[owner]:
                ready += 1
    if evaluated == 0:
        pct = Decimal("0.0")
    else:
        pct = rh(Decimal(100) * Decimal(ready) / Decimal(evaluated), 1)
    return {
        "basis": basis,
        "agency_id": agency_id,
        "evaluated_unit_count": evaluated,
        "ready_unit_count": ready,
        "readiness_pct": pct,
    }
