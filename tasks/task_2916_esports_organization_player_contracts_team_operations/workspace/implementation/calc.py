"""Every calculation rule of SCAFFOLD section 1.3, written to the normative step orders
spelled out in PRD sections 3.1, 3.4, 3.5, 3.6, 3.8 and 3.9.
"""

from datetime import timedelta
from decimal import Decimal

import db
from db import (
    BP_DENOMINATOR,
    MINUTES_PER_HOUR,
    MONTH_DAYS,
    MONTHS_PER_YEAR,
    SEASON_DAYS,
    WEEK_DAYS,
    apply_bp,
    round_half_up,
    store,
)

# ---- burnout weights and thresholds (SCAFFOLD calculations.burnout_score) -------------
WEIGHT_PRACTICE = Decimal("0.50")
WEIGHT_LOAD = Decimal("0.30")
WEIGHT_STREAM = Decimal("0.20")
BURNOUT_WARN_THRESHOLD = 70
BURNOUT_BREACH_THRESHOLD = 85
WELLNESS_HOLD_DAYS = 7
ROLLING_WINDOW_DAYS = 7

# ---- prize waterfall (SCAFFOLD calculations.prize_allocation) -------------------------
RESIDENT_WITHHOLDING_BP = 1500
NONRESIDENT_WITHHOLDING_BP = 3000
MINOR_ESCROW_BP = 1000

# ---- transfer settlement (SCAFFOLD calculations.transfer_settlement) ------------------
COMMISSION_TIER_BREAKPOINT_CENTS = 5000000
COMMISSION_TIER_LOW_BP = 500
COMMISSION_TIER_HIGH_BP = 300

# ---- defaults ------------------------------------------------------------------------
DEFAULT_MINOR_AGE_THRESHOLD_YEARS = 18


# ======================================================================================
# league resolution -- PRD section 3.1: "which league governs a given operation is found
# by walking the graph"
# ======================================================================================

def league_of_organization(organization):
    if organization is None:
        return None
    return store.leagues.get(organization.get("league_id"))


def league_of_contract(contract):
    if contract is None:
        return None
    return league_of_organization(store.organizations.get(contract.get("organization_id")))


def league_of_offer(offer):
    if offer is None:
        return None
    return league_of_organization(store.organizations.get(offer.get("organization_id")))


# ======================================================================================
# calculations.league_window_state
# ======================================================================================

def roster_lock_active(league):
    """true when current_utc >= League.roster_lock_at (a deadline, so >=)."""
    if league is None:
        return False
    return db.now() >= league["roster_lock_at"]


def transfer_window_open(league):
    """Half-open [transfer_window_open_at, transfer_window_close_at)."""
    if league is None:
        return False
    instant = db.now()
    return league["transfer_window_open_at"] <= instant < league["transfer_window_close_at"]


def offer_expired(offer):
    """true once current_utc has reached offer.expires_at."""
    return db.now() >= offer["expires_at"]


def free_agency_cooldown_hit(player, organization_id):
    """All three conditions of PRD section 3.1 must hold."""
    ends_at = player.get("free_agency_window_ends_at")
    if ends_at is None:
        return False
    if not db.now() < ends_at:
        return False
    return organization_id == player.get("last_release_organization_id")


# ======================================================================================
# calculations.player_minor_status
# ======================================================================================

def age_years(player):
    """Whole years between birth_date and the current instant; an anniversary falling
    exactly on the current date counts as reached (PRD section 3.2)."""
    birth = db.parse_date(player["birth_date"])
    if birth is None:
        return 0
    today = db.now()
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def governing_league_for_player(player, fallback_organization=None):
    """The league of current_organization_id's organization when the player has one,
    otherwise the league of the organization named in the request being evaluated."""
    current_org_id = player.get("current_organization_id")
    if current_org_id:
        league = league_of_organization(store.organizations.get(current_org_id))
        if league is not None:
            return league
    if fallback_organization is not None:
        return league_of_organization(fallback_organization)
    return None


def minor_age_threshold(league):
    if league is None:
        return DEFAULT_MINOR_AGE_THRESHOLD_YEARS
    return league["minor_age_threshold_years"]


def is_minor(player, fallback_organization=None, league=None):
    if league is None:
        league = governing_league_for_player(player, fallback_organization)
    return age_years(player) < minor_age_threshold(league)


def guardian_consent_status(player, fallback_organization=None, league=None):
    """NOT_REQUIRED for an adult, GRANTED for a minor with consent on file, otherwise
    REQUIRED (PRD section 3.2)."""
    if not is_minor(player, fallback_organization, league):
        return "NOT_REQUIRED"
    if player.get("guardian_consent_recorded"):
        return "GRANTED"
    return "REQUIRED"


# ======================================================================================
# calculations.org_salary_commitment
# ======================================================================================

def contracts_of_organization(organization_id):
    return [c for c in store.contracts.values() if c["organization_id"] == organization_id]


def committed_salary_cents(organization):
    """Sum of the FROZEN provisional_cap_charge_cents over ACTIVE and SUSPENDED
    contracts -- no rounding happens because only frozen integers are summed."""
    total = 0
    for contract in contracts_of_organization(organization["id"]):
        if contract["contract_status"] in ("ACTIVE", "SUSPENDED"):
            total += contract["provisional_cap_charge_cents"]
    return total


def uncommitted_salary_cents(organization):
    return organization["annual_salary_budget_cents"] - committed_salary_cents(organization)


def active_roster_count(organization):
    return len([c for c in contracts_of_organization(organization["id"])
                if c["contract_status"] == "ACTIVE"])


def prize_payable_cents(organization):
    total = 0
    for dist in store.distributions.values():
        if dist["organization_id"] != organization["id"]:
            continue
        if dist["distribution_status"] in ("CALCULATED", "APPROVED"):
            total += dist["org_share_cents"]
    return total


# ======================================================================================
# calculations.salary_cap_charge
# ======================================================================================

def prorated_cap_charge(base_salary_cents, signing_bonus_cents, effective_at, league):
    """PRORATED_REMAINING_TERM: round_half_up(base * remaining_season_days / 365)
    plus the signing bonus in full (the bonus is never prorated)."""
    remaining_season_days = db.whole_days_between(effective_at, league["season_end_at"])
    prorated = round_half_up(
        Decimal(int(base_salary_cents)) * Decimal(remaining_season_days) / Decimal(SEASON_DAYS)
    )
    return prorated + int(signing_bonus_cents)


def final_cap_charge(contract):
    """FULL_SEASON_EQUIVALENT: the whole annual salary plus the bonus, recomputed on
    every read and never frozen."""
    return contract["base_salary_cents"] + contract["signing_bonus_cents"]


def provisional_committed_cents(organization):
    return committed_salary_cents(organization)


def final_committed_cents(organization):
    total = 0
    for contract in contracts_of_organization(organization["id"]):
        if contract["contract_status"] in ("ACTIVE", "SUSPENDED"):
            total += final_cap_charge(contract)
    return total


# ======================================================================================
# calculations.weekly_hour_cap
# ======================================================================================

def contract_of_player(player_id, statuses=("ACTIVE", "SUSPENDED")):
    """The player's employment in one of `statuses`, or None.  At most one contract can
    sit in {ACTIVE, SUSPENDED} at a time (ERR_PLAYER_ALREADY_SIGNED enforces that)."""
    found = [c for c in store.contracts.values()
             if c["player_id"] == player_id and c["contract_status"] in statuses]
    if not found:
        return None
    return db.in_creation_order(found)[-1]


def contracts_of_player(player_id):
    return [c for c in store.contracts.values() if c["player_id"] == player_id]


def blocks_of_player(player_id, statuses=("SCHEDULED", "HELD")):
    return [b for b in store.practice_blocks.values()
            if b["block_status"] in statuses and player_id in b["participant_player_ids"]]


def scheduled_minutes(player_id, instant, extra_blocks=()):
    """Sum of duration_minutes over SCHEDULED or HELD blocks -- in any team house of any
    organization -- whose starts_at falls in the week window containing `instant`.
    A block is attributed in its entirety to the week that contains its starts_at."""
    start = db.week_start(instant)
    end = db.add_days(start, WEEK_DAYS)
    total = 0
    for block in blocks_of_player(player_id):
        if start <= block["starts_at"] < end:
            total += block["duration_minutes"]
    for block in extra_blocks:
        if player_id in block["participant_player_ids"] and start <= block["starts_at"] < end:
            total += block["duration_minutes"]
    return total


def streaming_minutes_charged(player, minor_flag):
    """PRD section 3.5: the contract's streaming_hours_per_week * 60 for a MINOR that owns
    an ACTIVE or SUSPENDED contract; zero for an adult or for a player with no such
    contract."""
    if not minor_flag:
        return 0
    contract = contract_of_player(player["id"])
    if contract is None:
        return 0
    return contract["streaming_hours_per_week"] * MINUTES_PER_HOUR


def cap_minutes(player, league, minor_flag=None, education_reserved_override=None):
    """PRD section 3.5.  For an adult, the league's adult ceiling.  For a minor, the
    smaller of the league ceiling and the guardian ceiling (a null guardian cap counts as
    the league ceiling), reduced by the education reserve only for ENROLLED_FULL_TIME."""
    if league is None:
        return 0
    if minor_flag is None:
        minor_flag = is_minor(player, league=league)
    if not minor_flag:
        return league["adult_max_weekly_minutes"]
    guardian_cap = player.get("guardian_weekly_cap_minutes")
    league_cap = league["minor_max_weekly_minutes"]
    base = min(league_cap, league_cap if guardian_cap is None else guardian_cap)
    reserved = league["education_reserved_minutes"]
    if education_reserved_override is not None:
        reserved = education_reserved_override
    if player.get("education_enrollment_status") == "ENROLLED_FULL_TIME":
        base = base - reserved
    return base


def weekly_committed_minutes(player, instant, league, minor_flag=None, extra_blocks=()):
    if minor_flag is None:
        minor_flag = is_minor(player, league=league)
    scheduled = scheduled_minutes(player["id"], instant, extra_blocks)
    streaming = streaming_minutes_charged(player, minor_flag)
    return scheduled, streaming, scheduled + streaming


# ======================================================================================
# calculations.burnout_score
# ======================================================================================

def _component_ratio(numerator, denominator):
    """min(1, numerator / denominator), with a zero/absent denominator yielding 0."""
    if denominator is None or denominator <= 0:
        return Decimal(0)
    ratio = Decimal(int(numerator)) / Decimal(int(denominator))
    return ratio if ratio < 1 else Decimal(1)


def _score(practice_minutes, cap, contract):
    """The shared scoring function of PRD section 3.6: three normalised components summed
    at full precision, multiplied by 100 and rounded half up exactly once."""
    if cap is not None and cap > 0:
        practice_component = _component_ratio(practice_minutes, cap)
    else:
        # A non-positive cap leaves the ratio undefined; an overshoot saturates at 1.
        practice_component = Decimal(1) if int(practice_minutes) > 0 else Decimal(0)
    load_component = Decimal(int(contract["last_self_reported_load"])) / Decimal(10)
    stream_commit = contract["streaming_hours_per_week"] * MINUTES_PER_HOUR
    stream_component = _component_ratio(contract["reported_streaming_minutes_7d"], stream_commit)
    weighted = (WEIGHT_PRACTICE * practice_component
                + WEIGHT_LOAD * load_component
                + WEIGHT_STREAM * stream_component)
    return round_half_up(Decimal(100) * weighted)


def rolling_practice_minutes(contract):
    """HELD blocks whose starts_at falls in (current_utc - 7 days, current_utc]."""
    instant = db.now()
    window_start = db.add_days(instant, -ROLLING_WINDOW_DAYS)
    total = 0
    for block in blocks_of_player(contract["player_id"], statuses=("HELD",)):
        if window_start < block["starts_at"] <= instant:
            total += block["duration_minutes"]
    return total


def _cap_for_contract(contract):
    player = store.players.get(contract["player_id"])
    league = league_of_contract(contract)
    if player is None or league is None:
        return 0
    return cap_minutes(player, league)


def rolling_burnout_score(contract):
    return _score(rolling_practice_minutes(contract), _cap_for_contract(contract), contract)


def season_burnout_score(contract):
    """SEASON_CUMULATIVE: season_practice_minutes / weeks_elapsed, rounded half up before
    scoring; weeks_elapsed has a floor of one week."""
    elapsed_days = db.whole_days_between(contract["effective_at"], db.now())
    weeks = db.ceil_div(elapsed_days, WEEK_DAYS)
    if weeks < 1:
        weeks = 1
    season_avg = round_half_up(
        Decimal(int(contract["season_practice_minutes"])) / Decimal(weeks)
    )
    return _score(season_avg, _cap_for_contract(contract), contract)


# ======================================================================================
# calculations.facility_slot_conflict / participant_double_booking / facility_capacity
# ======================================================================================

def _live_blocks():
    return [b for b in store.practice_blocks.values()
            if b["block_status"] in ("SCHEDULED", "HELD")]


def _overlaps(a_start, a_end, b_start, b_end):
    """Strictly-before comparison on both sides (PRD section 3.5)."""
    return a_start < b_end and b_start < a_end


def facility_slot_conflict(team_house, starts_at, ends_at, exclude_block_id=None):
    """The CANDIDATE ONLY is padded by turnaround_buffer_minutes at each end; existing
    bookings keep their raw intervals so the changeover is never double-counted."""
    buffer_minutes = team_house["turnaround_buffer_minutes"]
    padded_start = starts_at - timedelta(minutes=buffer_minutes)
    padded_end = ends_at + timedelta(minutes=buffer_minutes)
    for block in _live_blocks():
        if block["team_house_id"] != team_house["id"]:
            continue
        if exclude_block_id is not None and block["id"] == exclude_block_id:
            continue
        if _overlaps(padded_start, padded_end, block["starts_at"], block["ends_at"]):
            return True
    return False


def participant_double_booked(player_id, starts_at, ends_at, exclude_block_id=None):
    """No padding at all -- the changeover belongs to the room, not to the person."""
    for block in _live_blocks():
        if exclude_block_id is not None and block["id"] == exclude_block_id:
            continue
        if player_id not in block["participant_player_ids"]:
            continue
        if _overlaps(starts_at, ends_at, block["starts_at"], block["ends_at"]):
            return True
    return False


def facility_capacity_exceeded(team_house, seats_needed):
    """Exactly equal to concurrent_seat_capacity is allowed."""
    return seats_needed > team_house["concurrent_seat_capacity"]


# ======================================================================================
# calculations.deliverable_fee_share
# ======================================================================================

def assignments_of_deal(deal_id):
    return [a for a in store.assignments.values() if a["sponsorship_deal_id"] == deal_id]


def deal_assigned_count(deal):
    return len([a for a in assignments_of_deal(deal["id"])
                if a["assignment_status"] != "VOIDED"])


def deal_approved_count(deal):
    return len([a for a in assignments_of_deal(deal["id"])
                if a["assignment_status"] == "APPROVED"])


def per_item_fee_cents(deal):
    """floor(total_fee_cents / deliverable_count_required) -- TRUNCATING, one of the two
    documented exceptions to the round-half-up default (PRD section 2.7)."""
    required = deal["deliverable_count_required"]
    if required <= 0:
        return 0
    return db.floor_div(deal["total_fee_cents"], required)


def earned_fee_cents(deal):
    """The per-item share times approved_count, plus the truncation residue once and only
    once the quota is fully approved, so a FULFILLED deal has earned total_fee_cents."""
    per_item = per_item_fee_cents(deal)
    approved = deal_approved_count(deal)
    required = deal["deliverable_count_required"]
    earned = per_item * approved
    if approved == required:
        earned += deal["total_fee_cents"] - per_item * required
    return earned


def deal_is_fulfilled(deal):
    return deal_approved_count(deal) >= deal["deliverable_count_required"]


# ======================================================================================
# calculations.exclusivity_conflict
# ======================================================================================

def exclusivity_conflict(deal, contract_id):
    """CONFLICT when another deal of the same organization, in ACTIVE or FULFILLED, with a
    case-sensitively identical exclusivity_category and a half-open overlapping coverage
    window, already carries a non-VOIDED deliverable on the same contract."""
    for other in store.deals.values():
        if other["id"] == deal["id"]:
            continue
        if other["deal_status"] not in ("ACTIVE", "FULFILLED"):
            continue
        if other["organization_id"] != deal["organization_id"]:
            continue
        if other["exclusivity_category"] != deal["exclusivity_category"]:
            continue
        if not (other["starts_at"] < deal["ends_at"] and deal["starts_at"] < other["ends_at"]):
            continue
        for assignment in assignments_of_deal(other["id"]):
            if assignment["assignment_status"] == "VOIDED":
                continue
            if assignment["contract_id"] == contract_id:
                return True
    return False


def exclusivity_conflict_on_activation(deal):
    """Activation re-runs the check for every contract this deal already touches.  A DRAFT
    deal normally carries no deliverables (placement requires an ACTIVE deal), so the loop
    is usually empty -- which is exactly why DRAFT deals never conflict."""
    for assignment in assignments_of_deal(deal["id"]):
        if assignment["assignment_status"] == "VOIDED":
            continue
        if exclusivity_conflict(deal, assignment["contract_id"]):
            return True
    return False


# ======================================================================================
# calculations.prize_allocation -- STEP ORDER IS NORMATIVE (PRD section 3.8)
# ======================================================================================

def eligible_prize_contracts(distribution):
    """Step 3: ACTIVE contracts of the distributing organization whose effective_at is at
    or before tournament_end_at.  SUSPENDED, TERMINATED and later signings are excluded."""
    eligible = [c for c in contracts_of_organization(distribution["organization_id"])
                if c["contract_status"] == "ACTIVE"
                and c["effective_at"] <= distribution["tournament_end_at"]]
    return db.in_creation_order(eligible)


def prize_waterfall(distribution, league, organization):
    """Returns (totals_dict, [row_dict, ...]) or raises nothing -- the caller has already
    verified that the eligible set is non-empty."""
    gross = distribution["gross_prize_cents"]

    # step 1 -- the association's cut off the gross.
    association_levy = apply_bp(gross, league["player_association_levy_bp"])
    distributable = gross - association_levy

    # step 2 -- the house's cut off what step 1 left.
    org_share = apply_bp(distributable, organization["org_prize_share_bp"])
    player_pool = distributable - org_share

    # step 3 -- weights over the eligible population.
    eligible = eligible_prize_contracts(distribution)
    weight_total = sum(c["prize_split_player_pct_bp"] for c in eligible)

    # step 4 -- floor every row, then hand the WHOLE remainder to exactly one row.
    rows = []
    for contract in eligible:
        weight = contract["prize_split_player_pct_bp"]
        if weight_total > 0:
            floor_share = db.floor_div(player_pool * weight, weight_total)
        else:
            floor_share = 0
        rows.append({"contract": contract, "weight_bp": weight, "floor": floor_share})
    remainder = player_pool - sum(r["floor"] for r in rows)
    remainder_row = None
    for row in rows:
        # `rows` is already in created_at ASC order, so a strict > keeps the earliest
        # contract on a tie.
        if remainder_row is None or row["floor"] > remainder_row["floor"]:
            remainder_row = row
    for row in rows:
        row["gross_share_cents"] = row["floor"] + (remainder if row is remainder_row else 0)

    # step 5 -- deductions computed from each row's OWN final gross share.
    org_jurisdiction = organization["tax_jurisdiction_code"]
    for row in rows:
        contract = row["contract"]
        gross_share = row["gross_share_cents"]
        if contract["tax_residency_code"] == org_jurisdiction:
            rate_bp = RESIDENT_WITHHOLDING_BP
        else:
            rate_bp = NONRESIDENT_WITHHOLDING_BP
        row["withholding_rate_bp"] = rate_bp
        row["withholding_cents"] = apply_bp(gross_share, rate_bp)
        player = store.players.get(contract["player_id"])
        minor = player is not None and is_minor(player, organization)
        row["escrow_holdback_cents"] = apply_bp(gross_share, MINOR_ESCROW_BP) if minor else 0
        row["net_cents"] = (gross_share
                            - row["withholding_cents"]
                            - row["escrow_holdback_cents"])

    # step 6 -- freeze the totals.
    allocated = sum(r["gross_share_cents"] for r in rows)
    totals = {
        "association_levy_cents": association_levy,
        "org_share_cents": org_share,
        "allocated_cents": allocated,
        "withholding_total_cents": sum(r["withholding_cents"] for r in rows),
        "escrow_total_cents": sum(r["escrow_holdback_cents"] for r in rows),
        "unallocated_cents": gross - association_levy - org_share - allocated,
    }
    return totals, rows


# ======================================================================================
# calculations.transfer_settlement -- STEP ORDER IS NORMATIVE (PRD section 3.9)
# ======================================================================================

def remaining_whole_months(contract, instant):
    """Step 1: whole days from `instant` to the contract's frozen ends_at with the fraction
    discarded and a floor of zero, then raised to the next whole 30-day month."""
    remaining_days = db.whole_days_between(instant, contract["ends_at"])
    if remaining_days < 0:
        remaining_days = 0
    return db.ceil_div(remaining_days, MONTH_DAYS)


def monthly_rate_cents(contract):
    """Step 2: the BASE SALARY alone divided by 12, rounded half up.  Never a cap charge."""
    return round_half_up(
        Decimal(int(contract["base_salary_cents"])) / Decimal(MONTHS_PER_YEAR)
    )


def transfer_settlement(move, contract):
    """Steps 1-7 for a TRANSFER_OUT.  Returns the five money fields; `net_to_org_cents` may
    be negative and the caller must refuse the execution when it is."""
    months = remaining_whole_months(contract, db.now())
    monthly = monthly_rate_cents(contract)

    # step 3 -- the buyout credit owed to the departing player.
    buyout_credit = apply_bp(monthly * months, contract["buyout_multiplier_bp"])

    # step 4 -- the gross settlement the releasing organization retains.
    gross_settlement = move["gross_transfer_fee_cents"] - buyout_credit

    # step 5 -- the tier is selected from the GROSS settlement, before any commission.
    if gross_settlement < COMMISSION_TIER_BREAKPOINT_CENTS:
        tier_bp = COMMISSION_TIER_LOW_BP
    else:
        tier_bp = COMMISSION_TIER_HIGH_BP
    commission = apply_bp(gross_settlement, tier_bp)

    # step 6 -- what the organization actually keeps.
    net_to_org = gross_settlement - commission

    # step 7 -- cap relief from the contract's FROZEN provisional charge.
    released_cap = contract["provisional_cap_charge_cents"]

    return {
        "buyout_credit_cents": buyout_credit,
        "commission_tier_bp": tier_bp,
        "agent_commission_cents": commission,
        "net_to_org_cents": net_to_org,
        "released_cap_cents": released_cap,
    }


def release_settlement(contract):
    """A RELEASE runs step 7 only; the other four money fields stay at 0."""
    return {
        "buyout_credit_cents": 0,
        "commission_tier_bp": 0,
        "agent_commission_cents": 0,
        "net_to_org_cents": 0,
        "released_cap_cents": contract["provisional_cap_charge_cents"],
    }
