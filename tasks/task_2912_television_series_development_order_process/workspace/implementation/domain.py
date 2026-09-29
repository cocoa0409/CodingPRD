"""Domain constants, computed fields, calculations and serializers.

Every monetary figure is an integer count of cents and every division floors
(PRD 2.7).  No float arithmetic is used for money anywhere in this module.
"""

from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import (add_days, fmt_date, iso3, months_between, ordered, store)
from validators import decimal_to_json

# ---------------------------------------------------------------------------
# domain constants (SCAFFOLD 1.3 constants blocks / PRD 3.x prose)
# ---------------------------------------------------------------------------
PROBATION_SUBMISSION_CAP = 1
PREMIER_SUBMISSION_BONUS = 2

RIGHTS_QUIET_BUFFER_DAYS = 90

GUILD_MIN_CENTS_BASE = {
    "STORY": 3500000,
    "FIRST_DRAFT": 5500000,
    "REVISION": 2500000,
    "POLISH": 1500000,
}
GUILD_TIER_FACTOR_BPS = {"LOW": 10000, "HIGH": 12500}

MAX_OPEN_STEPS_PER_WRITER = 2
MAX_NOTES_ROUNDS = 2
MAX_NEGOTIATION_ROUNDS = 4

MAX_PILOT_VARIANCE_BPS = 1500
POSTURE_RESTRICTED_BPS = 6000

MIN_TEST_PANEL_SIZE = 300
TEST_SCORE_FLOOR = Decimal("62.0")
WEIGHT_OVERALL_BPS = 4550
WEIGHT_INTENT_BPS = 2975
WEIGHT_APPEAL_BPS = 2475

PLATFORM_COST_FACTOR_BPS = {"BROADCAST": 11000, "CABLE": 10500, "STREAMING": 12000}
DEFICIT_TIER1_CENTS = 1500000
TIER0_FACTOR_BPS = 10000
TIER1_FACTOR_BPS = 9500
TIER2_FACTOR_BPS = 9000

TURNAROUND_INTEREST_BPS_PER_YEAR = 900
TURNAROUND_WINDOW_DAYS = 180
HANDLING_TIER1_CENTS = 10000000
HANDLING_TIER2_CENTS = 50000000
HANDLING_FEE_TIER1_CENTS = 250000
HANDLING_FEE_TIER2_CENTS = 750000
HANDLING_FEE_TIER3_CENTS = 1500000
RECOUPMENT_CAP_BPS = 13500

PLATFORMS = ("BROADCAST", "CABLE", "STREAMING")
RELATIONSHIP_TIERS = ("PREMIER", "STANDARD", "PROBATION")
GUILD_TIERS = ("LOW", "HIGH")
STEP_TYPES = ("STORY", "FIRST_DRAFT", "REVISION", "POLISH")
CHAIN_OF_TITLE_STATUSES = ("CLEAN", "DISPUTED", "UNKNOWN")
RIGHTS_RESULT_BY_CHAIN = {"CLEAN": "CLEAR", "DISPUTED": "ENCUMBERED", "UNKNOWN": "BLOCKED"}
PITCH_STATUSES = ("SUBMITTED", "COVERED", "PASSED", "ADVANCED")
RECOMMENDATIONS = ("ADVANCE", "PASS")
DEV_STATUSES = ("ACTIVE_DEVELOPMENT", "SCRIPT_COMPLETE", "PILOT_ORDERED",
                "PILOT_DELIVERED", "SERIES_ORDERED", "ABANDONED")
TURNAROUND_STATUSES = ("NONE", "OFFERED", "EXERCISED")
DEAL_STATUSES = ("EXECUTED", "COMPLETED", "CUT_OFF", "TERMINATED")
STEP_STATUSES = ("PENDING", "EXERCISED", "DELIVERED", "NOTES_ISSUED", "ACCEPTED", "CUT_OFF")
CONTINGENCY_KINDS = ("CASTING", "LOCATION")
CONTINGENCY_RESOLUTIONS = ("SATISFIED", "WAIVED", "FAILED")
CONTINGENCY_STATUSES = ("PENDING", "SATISFIED", "WAIVED", "FAILED")
PRODUCTION_STATUSES = ("ORDERED", "GREEN_TO_SHOOT", "WRAPPED", "COLLAPSED")
SCREENING_STATUSES = ("FIELDED", "CERTIFIED", "INVALIDATED")
NEGOTIATION_STATUSES = ("NETWORK_OFFER", "STUDIO_COUNTER", "AGREED", "WITHDRAWN")
OFFER_SIDES = ("NETWORK", "STUDIO")
GREENLIGHT_STATUSES = ("OPEN", "APPROVED", "REJECTED", "SUPERSEDED")
COMMITTEES = ("CREATIVE", "BUSINESS", "FINANCE")
DECISIONS = ("APPROVED", "REJECTED")
FEASIBILITY_BASES = ("PATTERN", "LICENSE")
EXCLUSIVITY_STATUSES = ("FREE", "HOLDING_DEAL")
HOLDING_DEAL_STATUSES = ("ACTIVE", "TERMINATED")

OPEN_STEP_STATUSES = ("EXERCISED", "DELIVERED", "NOTES_ISSUED")
ENCUMBERING_OPTIONAL_STATUSES = ("EXERCISED", "DELIVERED", "NOTES_ISSUED", "ACCEPTED")
DEV_COST_PILOT_STATUSES = ("ORDERED", "GREEN_TO_SHOOT", "WRAPPED")


def floor_div(numerator, denominator):
    """Integer division discarding the remainder (largest integer <= quotient)."""
    return numerator // denominator


def scale_bps(amount, bps):
    """Multiply first, divide by 10000 second, discarding the remainder."""
    return floor_div(amount * bps, 10000)


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# existence resolution (validation priority 7 and 8)
# ---------------------------------------------------------------------------

def _resolve(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_agency(row_id):
    return _resolve(store.agencies, row_id, "ERR_AGENCY_NOT_FOUND")


def get_slate(row_id):
    return _resolve(store.slates, row_id, "ERR_SLATE_NOT_FOUND")


def get_writer(row_id):
    return _resolve(store.writers, row_id, "ERR_WRITER_NOT_FOUND")


def get_holding_deal(row_id):
    return _resolve(store.holding_deals, row_id, "ERR_HOLDING_DEAL_NOT_FOUND")


def get_pitch(row_id):
    return _resolve(store.pitches, row_id, "ERR_PITCH_NOT_FOUND")


def get_project(row_id):
    return _resolve(store.projects, row_id, "ERR_PROJECT_NOT_FOUND")


def get_script_deal(row_id):
    return _resolve(store.script_deals, row_id, "ERR_SCRIPT_DEAL_NOT_FOUND")


def get_deal_step(deal, step_id):
    if not isinstance(step_id, str):
        raise ApiError("ERR_DEAL_STEP_NOT_FOUND")
    step = store.deal_steps.get(step_id)
    if step is None or step["script_deal_id"] != deal["id"]:
        raise ApiError("ERR_DEAL_STEP_NOT_FOUND")
    return step


def get_pilot_order(row_id):
    return _resolve(store.pilot_orders, row_id, "ERR_PILOT_ORDER_NOT_FOUND")


def get_screening_of(pilot, screening_id):
    if not isinstance(screening_id, str):
        raise ApiError("ERR_SCREENING_NOT_FOUND")
    screening = store.screenings.get(screening_id)
    if screening is None or screening["pilot_order_id"] != pilot["id"]:
        raise ApiError("ERR_SCREENING_NOT_FOUND")
    return screening


def get_screening(row_id):
    return _resolve(store.screenings, row_id, "ERR_SCREENING_NOT_FOUND")


def get_negotiation(row_id):
    return _resolve(store.negotiations, row_id, "ERR_NEGOTIATION_NOT_FOUND")


def get_greenlight(row_id):
    return _resolve(store.greenlights, row_id, "ERR_GREENLIGHT_NOT_FOUND")


# ---------------------------------------------------------------------------
# collection navigation helpers
# ---------------------------------------------------------------------------

def steps_of(deal):
    return sorted(
        (s for s in store.deal_steps.values() if s["script_deal_id"] == deal["id"]),
        key=lambda s: s["step_index"],
    )


def deals_of_project(project):
    return ordered([d for d in store.script_deals.values() if d["project_id"] == project["id"]])


def pilots_of_project(project):
    return ordered([p for p in store.pilot_orders.values() if p["project_id"] == project["id"]])


def negotiations_of_project(project):
    return ordered([n for n in store.negotiations.values() if n["project_id"] == project["id"]])


def screenings_of_pilot(pilot):
    return ordered([s for s in store.screenings.values() if s["pilot_order_id"] == pilot["id"]])


def projects_of_slate(slate):
    return ordered([p for p in store.projects.values() if p["slate_id"] == slate["id"]])


def rights_checks_of_pitch(pitch):
    return ordered([r for r in store.rights_checks.values() if r["pitch_id"] == pitch["id"]])


def slate_of_project(project):
    return store.slates[project["slate_id"]]


def project_of_deal(deal):
    return store.projects[deal["project_id"]]


def project_of_pilot(pilot):
    return store.projects[pilot["project_id"]]


# ---------------------------------------------------------------------------
# script_deal_commitment (SCAFFOLD 1.3 / PRD 3.4)
# ---------------------------------------------------------------------------

def guild_floor_cents(step_type, guild_tier):
    base = GUILD_MIN_CENTS_BASE[step_type]
    return scale_bps(base, GUILD_TIER_FACTOR_BPS[guild_tier])


def effective_fee_cents(step):
    return step["effective_fee_cents"]


def guaranteed_commitment_cents(deal):
    limit = deal["guaranteed_step_count"]
    return sum(s["effective_fee_cents"] for s in steps_of(deal) if s["step_index"] <= limit)


def full_option_exposure_cents(deal):
    return sum(s["effective_fee_cents"] for s in steps_of(deal))


def encumbered_cents(deal):
    limit = deal["guaranteed_step_count"]
    total = 0
    for step in steps_of(deal):
        if step["step_index"] <= limit:
            if step["status"] != "CUT_OFF":
                total += step["effective_fee_cents"]
        else:
            if step["status"] in ENCUMBERING_OPTIONAL_STATUSES:
                total += step["effective_fee_cents"]
    return total


def step_count(deal):
    return len(steps_of(deal))


# ---------------------------------------------------------------------------
# project_cumulative_dev_cost (PRD 2.8)
# ---------------------------------------------------------------------------

def cumulative_dev_cost_cents(project):
    script_spend = sum(encumbered_cents(d) for d in deals_of_project(project))
    pilot_spend = sum(
        p["budget_cents"] for p in pilots_of_project(project)
        if p["production_status"] in DEV_COST_PILOT_STATUSES
    )
    return script_spend + pilot_spend


# ---------------------------------------------------------------------------
# slate_dev_budget_ledger and slate_episode_inventory (PRD 2.8)
# ---------------------------------------------------------------------------

def slate_committed_dev_cents(slate):
    total = 0
    for deal in store.script_deals.values():
        project = store.projects.get(deal["project_id"])
        if project is not None and project["slate_id"] == slate["id"]:
            total += encumbered_cents(deal)
    for pilot in store.pilot_orders.values():
        if pilot["production_status"] not in DEV_COST_PILOT_STATUSES:
            continue
        project = store.projects.get(pilot["project_id"])
        if project is not None and project["slate_id"] == slate["id"]:
            total += pilot["budget_cents"]
    return total


def slate_reserved_holding_cents(slate):
    return sum(
        h["annual_cost_cents"] for h in store.holding_deals.values()
        if h["slate_id"] == slate["id"] and h["status"] == "ACTIVE"
    )


def slate_writeoff_dev_cents(slate):
    return sum(
        p["writeoff_cents"] for p in store.projects.values()
        if p["slate_id"] == slate["id"] and p["dev_status"] == "ABANDONED"
    )


def slate_recouped_dev_cents(slate):
    return sum(
        p["recoupment_paid_cents"] for p in store.projects.values()
        if p["slate_id"] == slate["id"]
    )


def slate_available_dev_cents(slate):
    return (slate["total_dev_budget_cents"]
            - slate_committed_dev_cents(slate)
            - slate_reserved_holding_cents(slate)
            - slate_writeoff_dev_cents(slate)
            + slate_recouped_dev_cents(slate))


def _negotiation_episode_sum(slate, statuses):
    total = 0
    for negotiation in store.negotiations.values():
        if negotiation["status"] not in statuses:
            continue
        project = store.projects.get(negotiation["project_id"])
        if project is not None and project["slate_id"] == slate["id"]:
            total += negotiation["episode_count"]
    return total


def slate_committed_episode_count(slate):
    return _negotiation_episode_sum(slate, ("AGREED",))


def slate_reserved_episode_count(slate):
    return _negotiation_episode_sum(slate, ("NETWORK_OFFER", "STUDIO_COUNTER"))


def slate_available_episode_count(slate):
    return (slate["episode_capacity"]
            - slate_committed_episode_count(slate)
            - slate_reserved_episode_count(slate))


def slate_posture(slate):
    committed = slate_committed_episode_count(slate)
    reserved = slate_reserved_episode_count(slate)
    capacity = slate["episode_capacity"]
    if committed >= capacity:
        return "LOCKED"
    if floor_div((committed + reserved) * 10000, capacity) >= POSTURE_RESTRICTED_BPS:
        return "RESTRICTED"
    return "OPEN"


def require_slate_not_locked(slate):
    """Validation priority 33."""
    if slate_posture(slate) == "LOCKED":
        raise ApiError("ERR_SLATE_POSTURE_LOCKED")


# ---------------------------------------------------------------------------
# HoldingDeal.term_state and Writer computed fields (PRD 3.3 / 3.1)
# ---------------------------------------------------------------------------

def holding_deal_term_state(deal):
    today = store.today()
    if today < deal["term_start_date"]:
        return "PENDING_START"
    if today < deal["term_end_date"]:
        return "IN_TERM"
    return "EXPIRED"


def active_in_term_holds(writer_id):
    return [
        h for h in store.holding_deals.values()
        if h["writer_id"] == writer_id
        and h["status"] == "ACTIVE"
        and holding_deal_term_state(h) == "IN_TERM"
    ]


def writer_exclusivity_status(writer):
    return "HOLDING_DEAL" if active_in_term_holds(writer["id"]) else "FREE"


def writer_open_step_count(writer):
    total = 0
    for step in store.deal_steps.values():
        if step["status"] not in OPEN_STEP_STATUSES:
            continue
        deal = store.script_deals.get(step["script_deal_id"])
        if deal is not None and deal["writer_id"] == writer["id"]:
            total += 1
    return total


# ---------------------------------------------------------------------------
# agency_submission_quota (PRD 3.1)
# ---------------------------------------------------------------------------

def effective_submission_cap(agency):
    tier = agency["relationship_tier"]
    if tier == "PROBATION":
        return PROBATION_SUBMISSION_CAP
    if tier == "PREMIER":
        return agency["annual_submission_cap"] + PREMIER_SUBMISSION_BONUS
    return agency["annual_submission_cap"]


def submissions_used_count(agency, season_year=None):
    total = 0
    for pitch in store.pitches.values():
        if pitch["agency_id"] != agency["id"]:
            continue
        if pitch["status"] not in ("SUBMITTED", "COVERED", "ADVANCED"):
            continue
        if season_year is not None:
            slate = store.slates.get(pitch["slate_id"])
            if slate is None or slate["season_year"] != season_year:
                continue
        total += 1
    return total


# ---------------------------------------------------------------------------
# PilotOrder.budget_variance_bps (PRD 3.5)
# ---------------------------------------------------------------------------

def budget_variance_bps_for(budget_cents, pattern_budget_cents):
    return floor_div((budget_cents - pattern_budget_cents) * 10000, pattern_budget_cents)


def pilot_budget_variance_bps(pilot):
    slate = slate_of_project(project_of_pilot(pilot))
    return budget_variance_bps_for(pilot["budget_cents"],
                                   slate["pattern_budget_per_episode_cents"])


# ---------------------------------------------------------------------------
# weighted_test_score (PRD 3.6)
# ---------------------------------------------------------------------------

def weighted_component(raw_score, weight_bps):
    """raw * weight_bps / 10000 rounded half up to 2 places."""
    return round_half_up(Decimal(raw_score) * Decimal(weight_bps) / Decimal(10000), 2)


def weighted_test_score(overall, intent, appeal, comp_norm_index):
    raw = (weighted_component(overall, WEIGHT_OVERALL_BPS)
           + weighted_component(intent, WEIGHT_INTENT_BPS)
           + weighted_component(appeal, WEIGHT_APPEAL_BPS))
    weighted_raw = round_half_up(raw, 2)
    norm = round_half_up(weighted_raw * Decimal(100) / Decimal(comp_norm_index), 1)
    return weighted_raw, norm


def certified_screenings_of_project(project):
    rows = []
    for pilot in pilots_of_project(project):
        for screening in screenings_of_pilot(pilot):
            if screening["status"] == "CERTIFIED":
                rows.append(screening)
    return rows


def latest_certified_screening(project):
    """Highest certified_at, ties broken by the lowest created_at (PRD 3.7)."""
    rows = sorted(certified_screenings_of_project(project),
                  key=lambda s: (s["created_at"], s["_seq"]))
    best = None
    for screening in rows:
        if best is None or screening["certified_at"] > best["certified_at"]:
            best = screening
    return best


# ---------------------------------------------------------------------------
# pilot_series_feasibility (PRD 3.8)
# ---------------------------------------------------------------------------

def feasibility(project, basis, episode_count):
    slate = slate_of_project(project)
    if basis == "LICENSE":
        cost_base = scale_bps(slate["license_fee_cap_per_episode_cents"],
                              PLATFORM_COST_FACTOR_BPS[slate["platform"]])
    else:
        cost_base = slate["pattern_budget_per_episode_cents"]
    amortised = floor_div(cumulative_dev_cost_cents(project), episode_count)
    per_episode_cost = cost_base + amortised

    provisional_deficit = per_episode_cost - slate["license_fee_cap_per_episode_cents"]
    if provisional_deficit <= 0:
        tier_factor_bps = TIER0_FACTOR_BPS
    elif provisional_deficit <= DEFICIT_TIER1_CENTS:
        tier_factor_bps = TIER1_FACTOR_BPS
    else:
        tier_factor_bps = TIER2_FACTOR_BPS

    tiered_fee = scale_bps(per_episode_cost, tier_factor_bps)
    license_fee_final = min(tiered_fee, slate["license_fee_cap_per_episode_cents"])

    deficit_per_episode = per_episode_cost - license_fee_final
    total_deficit = deficit_per_episode * episode_count
    verdict = "FEASIBLE" if deficit_per_episode <= slate["max_deficit_per_episode_cents"] \
        else "INFEASIBLE"
    return {
        "project_id": project["id"],
        "basis": basis,
        "episode_count": episode_count,
        "per_episode_cost_cents": per_episode_cost,
        "tier_factor_bps": tier_factor_bps,
        "license_fee_final_cents": license_fee_final,
        "deficit_per_episode_cents": deficit_per_episode,
        "total_deficit_cents": total_deficit,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# turnaround_recoupment (PRD 3.9)
# ---------------------------------------------------------------------------

def handling_fee_cents(writeoff_cents):
    if writeoff_cents <= HANDLING_TIER1_CENTS:
        return HANDLING_FEE_TIER1_CENTS
    if writeoff_cents <= HANDLING_TIER2_CENTS:
        return HANDLING_FEE_TIER2_CENTS
    return HANDLING_FEE_TIER3_CENTS


def recoupment_at_clock(project):
    writeoff = project["writeoff_cents"]
    abandoned_at = project["abandoned_at"]
    if abandoned_at is None:
        return 0
    months = months_between(abandoned_at.date(), store.today())
    interest = floor_div(writeoff * TURNAROUND_INTEREST_BPS_PER_YEAR * months, 120000)
    gross = writeoff + interest + handling_fee_cents(writeoff)
    capped = scale_bps(writeoff, RECOUPMENT_CAP_BPS)
    return min(gross, capped)


def turnaround_window_open(project):
    if project["turnaround_status"] != "OFFERED":
        return False
    offered_at = project["turnaround_offered_at"]
    if offered_at is None:
        return False
    return store.now() < add_days(offered_at, TURNAROUND_WINDOW_DAYS)


def recoupment_amount_cents(project):
    status = project["turnaround_status"]
    if status == "EXERCISED":
        return project["recoupment_paid_cents"]
    if status == "OFFERED":
        return recoupment_at_clock(project)
    return 0


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def _common(row):
    return {
        "id": row["id"],
        "created_at": iso3(row["created_at"]),
        "updated_at": iso3(row["updated_at"]),
        "version": row["version"],
    }


def serialize_agency(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "agency_code": row["agency_code"],
        "relationship_tier": row["relationship_tier"],
        "packaging_allowed": row["packaging_allowed"],
        "annual_submission_cap": row["annual_submission_cap"],
        "effective_submission_cap": effective_submission_cap(row),
        "submissions_used_count": submissions_used_count(row),
    })
    return out


def serialize_slate(row):
    out = _common(row)
    out.update({
        "platform": row["platform"],
        "season_year": row["season_year"],
        "total_dev_budget_cents": row["total_dev_budget_cents"],
        "pattern_budget_per_episode_cents": row["pattern_budget_per_episode_cents"],
        "license_fee_cap_per_episode_cents": row["license_fee_cap_per_episode_cents"],
        "max_deficit_per_episode_cents": row["max_deficit_per_episode_cents"],
        "episode_capacity": row["episode_capacity"],
        "default_episode_count": row["default_episode_count"],
        "max_backend_points_bps": row["max_backend_points_bps"],
        "max_concurrent_pilot_shoots": row["max_concurrent_pilot_shoots"],
        "committed_dev_cents": slate_committed_dev_cents(row),
        "reserved_holding_cents": slate_reserved_holding_cents(row),
        "writeoff_dev_cents": slate_writeoff_dev_cents(row),
        "recouped_dev_cents": slate_recouped_dev_cents(row),
        "available_dev_cents": slate_available_dev_cents(row),
        "committed_episode_count": slate_committed_episode_count(row),
        "reserved_episode_count": slate_reserved_episode_count(row),
        "available_episode_count": slate_available_episode_count(row),
        "posture": slate_posture(row),
    })
    return out


def serialize_writer(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "agency_id": row["agency_id"],
        "guild_minimum_tier": row["guild_minimum_tier"],
        "quote_per_step_cents": row["quote_per_step_cents"],
        "exclusivity_status": writer_exclusivity_status(row),
        "open_step_count": writer_open_step_count(row),
    })
    return out


def serialize_holding_deal(row):
    out = _common(row)
    out.update({
        "writer_id": row["writer_id"],
        "slate_id": row["slate_id"],
        "annual_cost_cents": row["annual_cost_cents"],
        "term_start_date": fmt_date(row["term_start_date"]),
        "term_end_date": fmt_date(row["term_end_date"]),
        "status": row["status"],
        "term_state": holding_deal_term_state(row),
        "termination_reason": row["termination_reason"],
    })
    return out


def serialize_pitch(row):
    out = _common(row)
    out.update({
        "agency_id": row["agency_id"],
        "slate_id": row["slate_id"],
        "title": row["title"],
        "logline": row["logline"],
        "packaging_elements": list(row["packaging_elements"]),
        "underlying_ip_key": row["underlying_ip_key"],
        "status": row["status"],
        "coverage_score": decimal_to_json(row["coverage_score"]),
        "coverage_round": row["coverage_round"],
        "recommendation": row["recommendation"],
    })
    return out


def serialize_rights_check(row):
    return {
        "id": row["id"],
        "created_at": iso3(row["created_at"]),
        "pitch_id": row["pitch_id"],
        "underlying_ip_key": row["underlying_ip_key"],
        "chain_of_title_status": row["chain_of_title_status"],
        "holdback_start_date": fmt_date(row["holdback_start_date"]),
        "holdback_end_date": fmt_date(row["holdback_end_date"]),
        "quiet_period_end_date": fmt_date(row["quiet_period_end_date"]),
        "result": row["result"],
    }


def serialize_project(row):
    out = _common(row)
    out.update({
        "pitch_id": row["pitch_id"],
        "slate_id": row["slate_id"],
        "predecessor_project_id": row["predecessor_project_id"],
        "title": row["title"],
        "dev_status": row["dev_status"],
        "turnaround_status": row["turnaround_status"],
        "turnaround_offered_at": iso3(row["turnaround_offered_at"]),
        "turnaround_window_open": turnaround_window_open(row),
        "cumulative_dev_cost_cents": cumulative_dev_cost_cents(row),
        "writeoff_cents": row["writeoff_cents"],
        "abandoned_at": iso3(row["abandoned_at"]),
        "abandon_reason": row["abandon_reason"],
        "recoupment_amount_cents": recoupment_amount_cents(row),
        "recoupment_paid_cents": row["recoupment_paid_cents"],
    })
    return out


def serialize_script_deal(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "writer_id": row["writer_id"],
        "guaranteed_step_count": row["guaranteed_step_count"],
        "option_period_days": row["option_period_days"],
        "deal_status": row["deal_status"],
        "step_count": step_count(row),
        "guaranteed_commitment_cents": guaranteed_commitment_cents(row),
        "full_option_exposure_cents": full_option_exposure_cents(row),
        "encumbered_cents": encumbered_cents(row),
    })
    return out


def serialize_deal_step(row):
    out = _common(row)
    out.update({
        "script_deal_id": row["script_deal_id"],
        "step_index": row["step_index"],
        "step_type": row["step_type"],
        "fee_cents": row["fee_cents"],
        "effective_fee_cents": row["effective_fee_cents"],
        "status": row["status"],
        "option_expires_at": iso3(row["option_expires_at"]),
        "notes_round": row["notes_round"],
        "exercised_at": iso3(row["exercised_at"]),
        "delivered_at": iso3(row["delivered_at"]),
        "accepted_at": iso3(row["accepted_at"]),
        "notes_summary": row.get("notes_summary"),
    })
    return out


def serialize_pilot_order(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "budget_cents": row["budget_cents"],
        "shoot_start_date": fmt_date(row["shoot_start_date"]),
        "shoot_end_date": fmt_date(row["shoot_end_date"]),
        "casting_deadline_date": fmt_date(row["casting_deadline_date"]),
        "location_deadline_date": fmt_date(row["location_deadline_date"]),
        "casting_status": row["casting_status"],
        "location_status": row["location_status"],
        "production_status": row["production_status"],
        "budget_variance_bps": pilot_budget_variance_bps(row),
        "collapsed_reason": row["collapsed_reason"],
    })
    return out


def serialize_screening(row):
    out = _common(row)
    out.update({
        "pilot_order_id": row["pilot_order_id"],
        "panel_size": row["panel_size"],
        "overall_score": row["overall_score"],
        "intent_to_view_score": row["intent_to_view_score"],
        "appeal_score": row["appeal_score"],
        "comp_norm_index": decimal_to_json(row["comp_norm_index"]),
        "weighted_raw_score": decimal_to_json(row["weighted_raw_score"]),
        "norm_adjusted_score": decimal_to_json(row["norm_adjusted_score"]),
        "status": row["status"],
        "certified_at": iso3(row["certified_at"]),
    })
    return out


def serialize_negotiation(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "episode_count": row["episode_count"],
        "license_fee_per_episode_cents": row["license_fee_per_episode_cents"],
        "backend_points_bps": row["backend_points_bps"],
        "network_ownership_pct": row["network_ownership_pct"],
        "studio_ownership_pct": row["studio_ownership_pct"],
        "status": row["status"],
        "round_number": row["round_number"],
        "last_offer_side": row["last_offer_side"],
        "total_license_commitment_cents": (row["episode_count"]
                                          * row["license_fee_per_episode_cents"]),
        "agreed_at": iso3(row["agreed_at"]),
        "withdrawn_reason": row["withdrawn_reason"],
    })
    return out


def serialize_greenlight(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "negotiation_id": row["negotiation_id"],
        "project_version_at_request": row["project_version_at_request"],
        "creative_decision": row["creative_decision"],
        "business_decision": row["business_decision"],
        "finance_decision": row["finance_decision"],
        "creative_decided_by_user_id": row["creative_decided_by_user_id"],
        "business_decided_by_user_id": row["business_decided_by_user_id"],
        "finance_decided_by_user_id": row["finance_decided_by_user_id"],
        "status": row["status"],
        "decided_at": iso3(row["decided_at"]),
    })
    return out


# ---------------------------------------------------------------------------
# system cascades (PRD 2.10 / 3.5 / 3.8 / 3.9)
# ---------------------------------------------------------------------------
from store import touch  # noqa: E402  (kept next to the cascades that use it)


def cascade_pilot_collapse(pilot, collapsed_reason):
    """Links 2 and 3 of the contingency-failure cascade (PRD 3.5).

    The caller has already set the failing dimension and bumped nothing; this
    drives production_status to COLLAPSED, walks the project back and refreshes
    every touched row's updated_at / version.
    """
    pilot["production_status"] = "COLLAPSED"
    pilot["collapsed_reason"] = collapsed_reason
    touch(pilot)

    project = project_of_pilot(pilot)
    if project["dev_status"] == "PILOT_ORDERED":
        project["dev_status"] = "ACTIVE_DEVELOPMENT"
    touch(project)

    # The dollar ledger is derived, so the budget leaves committed_dev_cents by
    # construction; only the slate's version has to be refreshed.
    touch(slate_of_project(project))


def supersede_screenings(pilot, keep_id):
    """A newly fielded screening invalidates the pilot's research history."""
    changed = False
    for screening in screenings_of_pilot(pilot):
        if screening["id"] == keep_id:
            continue
        if screening["status"] in ("FIELDED", "CERTIFIED"):
            screening["status"] = "INVALIDATED"
            touch(screening)
            changed = True
    return changed


def supersede_greenlights(project, keep_id):
    """Every other OPEN request on the project becomes SUPERSEDED (PRD 3.8)."""
    for row in ordered([g for g in store.greenlights.values()
                        if g["project_id"] == project["id"]]):
        if row["id"] == keep_id:
            continue
        if row["status"] == "OPEN":
            row["status"] = "SUPERSEDED"
            touch(row)


def cascade_greenlight_approved(greenlight, project):
    """The four-link join fired by the third approving vote (PRD 3.8)."""
    greenlight["status"] = "APPROVED"
    greenlight["decided_at"] = store.now()

    project["dev_status"] = "SERIES_ORDERED"

    for deal in deals_of_project(project):
        if deal["deal_status"] != "EXECUTED":
            continue
        deal["deal_status"] = "COMPLETED"
        for step in steps_of(deal):
            if step["status"] == "PENDING":
                step["status"] = "CUT_OFF"
                touch(step)
        touch(deal)

    touch(project)
    touch(slate_of_project(project))


def cascade_abandon(project, reason):
    """The ordered abandonment cascade (PRD 3.9).  Link one runs first."""
    # Link 1 -- freeze the accounting before anything is unwound.
    project["writeoff_cents"] = cumulative_dev_cost_cents(project)
    project["abandoned_at"] = store.now()
    project["abandon_reason"] = reason
    project["dev_status"] = "ABANDONED"

    # Link 2 -- terminate every EXECUTED deal and cut off every live step.
    for deal in deals_of_project(project):
        if deal["deal_status"] != "EXECUTED":
            continue
        deal["deal_status"] = "TERMINATED"
        for step in steps_of(deal):
            if step["status"] != "CUT_OFF":
                step["status"] = "CUT_OFF"
                touch(step)
        touch(deal)

    # Link 3 -- withdraw every standing negotiation, releasing its reservation.
    for negotiation in negotiations_of_project(project):
        if negotiation["status"] in ("NETWORK_OFFER", "STUDIO_COUNTER"):
            negotiation["status"] = "WITHDRAWN"
            negotiation["withdrawn_reason"] = reason
            touch(negotiation)

    # Link 4 -- collapse every live pilot; a WRAPPED pilot is left alone.
    for pilot in pilots_of_project(project):
        if pilot["production_status"] in ("ORDERED", "GREEN_TO_SHOOT"):
            pilot["production_status"] = "COLLAPSED"
            pilot["collapsed_reason"] = "PROJECT_ABANDONED"
            touch(pilot)

    touch(project)
    touch(slate_of_project(project))
