"""Business calculations, derived fields and reconciliation helpers.

Every rule here is transcribed from SCAFFOLD.yaml §1.1 (computed fields), §1.2
(state machines) and §1.3 (calculation rules), together with the matching PRD
prose in §2 and §3. Where the PRD prose and the scaffold disagree, the PRD's
stated behaviour wins.

Rounding is always Decimal + ROUND_HALF_UP, applied once, at the end, on the
whole amount.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, to_iso, parse_iso8601

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD.yaml §1.3 `constants` blocks)
# ---------------------------------------------------------------------------
SERVICE_LIST_PRICE_CENTS_PER_LOAD = 125000
LIVES_EXHAUSTION_SURCHARGE_CENTS = 45000
BASELINE_FLOOR_CASES = 8
HIGH_FLOOR_CASES = 15
EXPANSION_READY_FLOOR_CASES = 22
CONSTRUCTION_UPLIFT_BASE_CENTS = 304800
CONSTRUCTION_UPLIFT_ESCALATION_CENTS = 76200
NEAR_MISS_TOLERANCE_CM = 5
MIN_SERVICE_TIER_INDEX = 2
DIMENSIONAL_UPLIFT_PER_TWO_CLEARANCES_CENTS = 150000
INTEGRATION_UPLIFT_PER_TIER_CENTS = 250000
IDN_VOLUME_DISCOUNT_PER_PEER = Decimal("0.02")
IDN_VOLUME_DISCOUNT_CAP = Decimal("0.04")
SHORTFALL_GRACE_PROCEDURES = 2
SHORTFALL_RATE_BASIS_POINTS = 200
TIER_SCALE_DIVISOR = 1000000
MAX_PENALTY_POINTS = 15
MONTHLY_DECAY_POINTS = 1
GRACE_HOURS = 6
ESCALATION_HOURS = 24
LOANER_WINDOW_DAYS = 14
LOANER_BUFFER_HOURS = 4
LOANER_BORROW_LIMIT_DAYS = 17
TRANSFER_GRACE_DAYS = 3
MIN_SIMULATION_MODULES = 3
ACTIVITY_TIER_FLOOR = 2
EXPANSION_VOLUME_TARGET = 22
MAX_POOL_UTILISATION_UNITS = 25
SURPLUS_POOL_BUDGET = 30
TURNOVER_BUFFER_MINUTES = 30
ESCALATION_MODULUS = 7
ACCEPTANCE_WINDOW_DAYS = 30
CREDENTIAL_VALIDITY_DAYS = 365
EVIDENCE_GRACE_DAYS = 60
EXPIRING_SOON_DAYS = 30
INTERVAL_DAYS = 30
GLOBAL_CAPACITY_CEILING = 34
CAPACITY_HALF_FRACTION = Decimal("0.5")

# PRD §2.8 / §3.3 — the response-time ladder. The nesting is load-bearing: the
# inner floor at 4 hours is applied BEFORE the outer ceiling at 24, which is
# what pulls the COMPREHENSIVE branch down from 36 hours to 24.
TIER_INDEX_BY_COVERAGE = {
    "COMPREHENSIVE": 3,
    "STANDARD": 2,
    "LIMITED": 1,
    "PARTS_ONLY": 0,
}
BASE_RESPONSE_HOURS = 48
HOURS_REDUCTION_PER_TIER = 12
# The enumerated commitment ladder of PRD §2.8. See `contract_response_hours`.
RESPONSE_HOURS_BY_COVERAGE = {
    "COMPREHENSIVE": 24,
    "STANDARD": 12,
    "LIMITED": 18,
    "PARTS_ONLY": 24,
}
MIN_RESPONSE_HOURS = 4
MAX_RESPONSE_HOURS = 24

SERVICE_LINE_TIER_NAMES = {
    0: "OBSERVATIONAL",
    1: "ESTABLISHED",
    2: "DEVELOPING",
    3: "ADVANCED",
    4: "REFERENCE",
}

# PRD §2.10 — the exhaustion surcharge bites at this many consumed loads.
DEPLETION_FLOOR_LOADS = 8

TRAINING_REQUIREMENT_UNITS = 2
GREEN_BAND_UNITS = 2

SURGEON_STATUS_LABELS = {
    0: "INACTIVE",
    1: "PROVISIONAL",
    2: "ACTIVE",
}


def round_half_up(value):
    """Round to a whole number with ROUND_HALF_UP (never banker's rounding)."""
    if isinstance(value, float):
        value = Decimal(repr(value))
    elif not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dt(record, field):
    return parse_iso8601((record or {}).get(field))


# The module-level pinned datetimes are read through this alias so callers that
# work with raw field names (rather than a record) stay readable.
parse_iso = parse_iso8601


# ---------------------------------------------------------------------------
# Collection lookups
# ---------------------------------------------------------------------------

def systems_of_account(account_id):
    return [s for s in DB.robot_systems.values() if s.get("hospital_account_id") == account_id]


def reviews_of_account(account_id):
    return [r for r in DB.site_readiness_reviews.values()
            if r.get("hospital_account_id") == account_id]


def agreements_of_account(account_id):
    return [a for a in DB.placement_agreements.values()
            if a.get("hospital_account_id") == account_id]


def cases_of_system(system_id):
    return [c for c in DB.procedure_cases.values() if c.get("robot_system_id") == system_id]


def cases_of_agreement(agreement_id):
    return [c for c in DB.procedure_cases.values()
            if c.get("placement_agreement_id") == agreement_id]


def training_records_of_account(account_id):
    return [t for t in DB.surgeon_training_records.values()
            if t.get("hospital_account_id") == account_id]


def evidence_of_record(record_id):
    return [e for e in DB.credentialing_evidence.values()
            if e.get("surgeon_training_record_id") == record_id]


def contracts_of_system(system_id):
    return [c for c in DB.service_contracts.values() if c.get("robot_system_id") == system_id]


def incidents_of_system(system_id):
    return [i for i in DB.incidents.values() if i.get("robot_system_id") == system_id]


def dispatches_of_system(system_id):
    return [d for d in DB.loaner_dispatches.values() if d.get("robot_system_id") == system_id]


def cycles_of_system(system_id):
    return [c for c in DB.utilization_cycles.values() if c.get("robot_system_id") == system_id]


def cycles_of_agreement(agreement_id):
    return [c for c in DB.utilization_cycles.values()
            if c.get("placement_agreement_id") == agreement_id]


def ledgers_of_account(account_id):
    return [l for l in DB.consumption_ledgers.values()
            if l.get("hospital_account_id") == account_id]


def releases_of_configuration(config_id):
    return [r for r in DB.software_releases.values()
            if r.get("system_configuration_id") == config_id]


def deployments_of_system(system_id):
    return [d for d in DB.software_deployments.values()
            if d.get("robot_system_id") == system_id]


def proctor_cases_of_record(record_id):
    return [p for p in DB.proctor_cases.values()
            if p.get("surgeon_training_record_id") == record_id]


def reviews_of_account_expansion(account_id):
    return [r for r in DB.expansion_reviews.values()
            if r.get("hospital_account_id") == account_id]


def active_contract(system_id):
    """The system's ACTIVE in-window custody contract, if any (PRD §2.8).

    The window is inclusive of the start and exclusive of the end; the logical
    clock must sit strictly before the end instant.
    """
    now = DB.clock
    for contract in sorted(contracts_of_system(system_id), key=lambda c: c.get("_seq") or 0):
        if contract.get("contract_status") != "ACTIVE":
            continue
        end = contract_end(contract)
        if end is not None and now < end:
            return contract
    return None


def any_active_contract(system_id):
    for contract in contracts_of_system(system_id):
        if contract.get("contract_status") == "ACTIVE":
            return contract
    return None


# ---------------------------------------------------------------------------
# HospitalAccount posture and service-line tier
# ---------------------------------------------------------------------------

def account_posture(account):
    """Pinned order per PRD §2.5: EXPANSION_BLOCKED, then ONBOARDING_GATE,
    then ACTIVE."""
    if account is None:
        return None
    account_id = account.get("id")
    for system in systems_of_account(account_id):
        if system.get("service_status") == "SERVICE_ACTION_REQUIRED":
            return "EXPANSION_BLOCKED"
    reviews = reviews_of_account(account_id)
    if not reviews:
        return "ONBOARDING_GATE"
    for review in reviews:
        if review.get("readiness_status") in ("PENDING_REVIEW", "CONDITIONAL", "REJECTED"):
            return "ONBOARDING_GATE"
    return "ACTIVE"


def service_line_tier_index(account):
    """distinct COMPLETED procedure families minus 1, clamped to 0..4."""
    if account is None:
        return 0
    families = set()
    for case in DB.procedure_cases.values():
        if case.get("hospital_account_id") != account.get("id"):
            continue
        if case.get("case_status") != "COMPLETED":
            continue
        family = case.get("procedure_family")
        if family:
            families.add(family)
    index = len(families) - 1
    if index < 0:
        index = 0
    if index > 4:
        index = 4
    return index


def service_line_tier_label(account):
    return SERVICE_LINE_TIER_NAMES.get(service_line_tier_index(account))


# ---------------------------------------------------------------------------
# SiteReadinessReview: tolerance band, clearances, construction uplift
# ---------------------------------------------------------------------------

DIMENSIONAL_CHECKS = (
    ("operating_room_length_cm", "min_operating_room_length_cm"),
    ("operating_room_width_cm", "min_operating_room_width_cm"),
    ("table_throw_radius_cm", "min_table_throw_radius_cm"),
    ("ceiling_clearance_cm", "min_ceiling_clearance_cm"),
)


def _review_dimension_counts(review):
    """(unmet, near_miss) over the four dimensional checks."""
    config = DB.system_configurations.get((review or {}).get("evaluated_configuration_id"))
    unmet = 0
    near = 0
    for field, minimum_field in DIMENSIONAL_CHECKS:
        value = review.get(field)
        minimum = (config or {}).get(minimum_field)
        if value is None or minimum is None:
            continue
        value = int(value)
        minimum = int(minimum)
        if value < minimum:
            unmet += 1
        elif minimum < value < minimum + NEAR_MISS_TOLERANCE_CM:
            near += 1
    return unmet, near


def conditional_clearance_count(review):
    """Checks that miss an exact match but sit inside the conditional band.

    A measurement exactly at the minimum is a clean match and contributes
    nothing; strictly above the minimum but below minimum + 5 cm increments the
    count by one.
    """
    if review is None:
        return 0
    _, near = _review_dimension_counts(review)
    return near


def construction_uplift_fee(review):
    """304800 per uplift unit + 76200 for each unit past the first."""
    if review is None:
        return 0
    unmet, near = _review_dimension_counts(review)
    units = unmet + near
    if units == 0:
        return 0
    return (CONSTRUCTION_UPLIFT_BASE_CENTS * units
            + CONSTRUCTION_UPLIFT_ESCALATION_CENTS * max(0, units - 1))


def room_requirements_met(review):
    """Every dimension and the throw radius must meet or exceed the minimums."""
    config = DB.system_configurations.get((review or {}).get("evaluated_configuration_id"))
    if config is None:
        return True
    for field, minimum_field in DIMENSIONAL_CHECKS:
        value = review.get(field)
        minimum = config.get(minimum_field)
        if value is None or minimum is None:
            continue
        if int(value) < int(minimum):
            return False
    return True


def integration_requirements_met(review):
    """(power_ok, fiber_ok) against the evaluated configuration."""
    config = DB.system_configurations.get((review or {}).get("evaluated_configuration_id")) or {}
    power_ok = True
    fiber_ok = True
    if config.get("requires_dedicated_power_circuit") and not review.get("has_dedicated_power_circuit"):
        power_ok = False
    if config.get("requires_dark_fiber") and not review.get("has_dark_fiber_run"):
        fiber_ok = False
    return power_ok, fiber_ok


# ---------------------------------------------------------------------------
# PlacementAgreement: commitment interval and committed cases
# ---------------------------------------------------------------------------

def agreement_cycle_end(agreement):
    if agreement is None:
        return None
    start = _dt(agreement, "cycle_start_utc")
    if start is None:
        return None
    months = int(agreement.get("interval_months") or 1)
    return start + timedelta(days=INTERVAL_DAYS * months)


def committed_cases(agreement):
    """SCHEDULED or COMPLETED cases inside [cycle_start, cycle_end)."""
    if agreement is None:
        return 0
    start = _dt(agreement, "cycle_start_utc")
    end = agreement_cycle_end(agreement)
    if start is None or end is None:
        return 0
    count = 0
    for case in cases_of_agreement(agreement.get("id")):
        if case.get("case_status") not in ("SCHEDULED", "COMPLETED"):
            continue
        started = _dt(case, "case_started_at")
        if started is None:
            continue
        if start <= started < end:
            count += 1
    return count


def idn_scale(account):
    """Accounts sharing the idn_group_code that are ACTIVE or DORMANT."""
    if account is None:
        return 0
    code = account.get("idn_group_code")
    return sum(1 for a in DB.hospital_accounts.values()
               if a.get("idn_group_code") == code
               and a.get("account_status") in ("ACTIVE", "DORMANT"))


def placement_fee(account, review, config):
    """Pinned order per PRD §3.1.2 / SCAFFOLD §1.3 `placement_fee`.

    The ladder is read at the instant the computation runs, so a submit (while
    the account is still CONTRACTED) scores a lower idn_scale than the accept
    that follows it.
    """
    clearances = conditional_clearance_count(review)
    dimensional_uplift = math.ceil(clearances / 2.0) * DIMENSIONAL_UPLIFT_PER_TWO_CLEARANCES_CENTS
    integration_uplift = int((config or {}).get("integration_tier") or 0) * INTEGRATION_UPLIFT_PER_TIER_CENTS
    gross = (int((config or {}).get("base_placement_fee_cents") or 0)
             + dimensional_uplift + integration_uplift)
    scale = idn_scale(account)
    rate = min(IDN_VOLUME_DISCOUNT_CAP, IDN_VOLUME_DISCOUNT_PER_PEER * scale)
    discount = Decimal(gross) * rate
    return round_half_up(Decimal(gross) - discount)


# ---------------------------------------------------------------------------
# RobotSystem derived fields
# ---------------------------------------------------------------------------

def entitled_feature_codes(config, installed_index):
    """Feature codes whose min_release_index has been reached."""
    if not config:
        return []
    entitlements = config.get("feature_entitlements") or []
    if isinstance(entitlements, dict):
        entitlements = [{"feature_code": k, "min_release_index": v}
                        for k, v in entitlements.items()]
    codes = []
    for entry in entitlements:
        if not isinstance(entry, dict):
            continue
        minimum = int(entry.get("min_release_index") or 0)
        if int(installed_index or 0) >= minimum:
            code = entry.get("feature_code")
            if code is not None:
                codes.append(code)
    return codes


def instrument_lives_remaining(system):
    """config.max_instrument_lives minus the approved loads still held."""
    if system is None:
        return 0
    config = DB.system_configurations.get(system.get("system_configuration_id"))
    if config is None:
        return 0
    total = int(config.get("max_instrument_lives") or 0)
    used = 0
    # A replacement accessory set is provisioned by an explicit reset; it is "the
    # only action that raises the count", restoring `max_instrument_lives` in full
    # and discarding everything consumed before it, while consumption after the
    # reset still counts. The system carries the sequence watermark of its last
    # provisioning, so only later rows are drawn from the fresh set.
    watermark = int(system.get("_lives_watermark") or 0)
    for case in cases_of_system(system.get("id")):
        if case.get("case_status") not in ("SCHEDULED", "COMPLETED"):
            continue
        if int(case.get("_seq") or 0) <= watermark:
            continue
        used += int(case.get("approved_instrument_load") or 0)
    for entry in (system.get("_accessory_load_ledger") or []):
        if int(entry.get("_seq") or 0) <= watermark:
            continue
        used += int(entry.get("approved_load") or 0)
    return max(0, total - used)


def accessory_set_status(system):
    return "EXHAUSTED" if instrument_lives_remaining(system) <= 0 else "AVAILABLE"


def current_cycle(system):
    if system is None:
        return None
    return DB.utilization_cycles.get(system.get("current_utilization_cycle_id"))


def expansion_eligible(system):
    """Three-part conjunction per PRD §3.7 / SCAFFOLD §1.3."""
    if system is None:
        return False
    if system.get("service_status") != "IN_SERVICE":
        return False
    contract = active_contract(system.get("id"))
    if contract is None:
        return False
    if service_tier_index(contract) < MIN_SERVICE_TIER_INDEX:
        return False
    cycle = current_cycle(system)
    completed = completed_case_count(cycle) if cycle else 0
    agreement = DB.placement_agreements.get(system.get("placement_agreement_id"))
    minimum = int((agreement or {}).get("minimum_procedures_per_cycle") or 0)
    return completed >= minimum


# ---------------------------------------------------------------------------
# UtilizationCycle derived state
# ---------------------------------------------------------------------------

def cycle_end(cycle):
    if cycle is None:
        return None
    start = _dt(cycle, "cycle_start_utc")
    if start is None:
        return None
    return start + timedelta(days=INTERVAL_DAYS)


def _cases_in_cycle(cycle):
    system_id = cycle.get("robot_system_id")
    start = _dt(cycle, "cycle_start_utc")
    end = cycle_end(cycle)
    if start is None or end is None:
        return []
    out = []
    for case in cases_of_system(system_id):
        started = _dt(case, "case_started_at")
        if started is None:
            continue
        if start <= started < end:
            out.append(case)
    return out


def scheduled_case_count(cycle):
    if cycle is None:
        return 0
    return sum(1 for c in _cases_in_cycle(cycle) if c.get("case_status") != "CANCELLED")


def completed_case_count(cycle):
    if cycle is None:
        return 0
    return sum(1 for c in _cases_in_cycle(cycle) if c.get("case_status") == "COMPLETED")


def utilization_band(cycle):
    """Boundaries inclusive on the lower edge (PRD §2.11)."""
    if cycle is None:
        return "UNDERUTILIZED"
    count = completed_case_count(cycle)
    if count >= EXPANSION_READY_FLOOR_CASES:
        return "EXPANSION_READY"
    if count >= HIGH_FLOOR_CASES:
        return "HIGH"
    if count >= BASELINE_FLOOR_CASES:
        return "BASELINE"
    return "UNDERUTILIZED"


def _buffered_span(case):
    started = _dt(case, "case_started_at")
    if started is None:
        return None
    minutes = int(case.get("duration_minutes") or 0) + TURNOVER_BUFFER_MINUTES
    return started, started + timedelta(minutes=minutes)


def same_hour_conflict_count(cycle):
    """Other non-cancelled cases on the same system whose buffered occupancy
    overlaps this cycle's own scheduled case intervals."""
    if cycle is None:
        return 0
    system_id = cycle.get("robot_system_id")
    mine = [c for c in _cases_in_cycle(cycle) if c.get("case_status") != "CANCELLED"]
    if not mine:
        return 0
    mine_ids = set(c.get("id") for c in mine)
    spans = [s for s in (_buffered_span(c) for c in mine) if s]
    conflicting = set()
    for other in cases_of_system(system_id):
        if other.get("id") in mine_ids:
            continue
        if other.get("case_status") == "CANCELLED":
            continue
        span = _buffered_span(other)
        if span is None:
            continue
        for start, end in spans:
            if start < span[1] and end > span[0]:
                conflicting.add(other.get("id"))
                break
    return len(conflicting)


# ---------------------------------------------------------------------------
# ProcedureCase billing
# ---------------------------------------------------------------------------

def _base_instrument_billing(agreement, load):
    """Steps 1-3 of `instrument_billing_amount` (the arrangement ladder)."""
    if agreement is None:
        return 0
    arrangement = agreement.get("arrangement_type")
    if arrangement == "PURCHASE":
        return int(load or 0) * SERVICE_LIST_PRICE_CENTS_PER_LOAD
    if arrangement == "LEASE":
        return 0
    if arrangement == "USAGE_BASED":
        fee = Decimal(int(agreement.get("placement_fee_cents") or 0))
        bps = Decimal(int(agreement.get("usage_rate_basis_points") or 0))
        return round_half_up(fee * bps / Decimal(10000))
    return 0


def instrument_billing(case, load=None, mode="settle"):
    """The pinned order of `instrument_billing_amount` joined with
    `accessory_lives_billing`.

    mode="quote"  — evaluated at creation: reads the attempted load and skips
                    the not-COMPLETED override (PRD §3.4).
    mode="settle" — evaluated at completion: reads the approved (clamped) load
                    and refuses to bill anything not COMPLETED.
    """
    if case is None:
        return 0
    agreement = DB.placement_agreements.get(case.get("placement_agreement_id"))
    if load is None:
        if mode == "settle":
            load = case.get("approved_instrument_load") or 0
        else:
            load = case.get("instrument_load") or 0
    amount = _base_instrument_billing(agreement, load)

    system = DB.robot_systems.get(case.get("robot_system_id"))
    # Rule 5 — a system in SERVICE_ACTION_REQUIRED is never billable.
    if system is not None and system.get("service_status") == "SERVICE_ACTION_REQUIRED":
        return 0
    # Rule 4 — a non-COMPLETED case is never billable (settle variant only).
    if mode == "settle" and case.get("case_status") != "COMPLETED":
        return 0

    # accessory_lives_billing — the threshold surcharge. PRD §2.10 bills a case
    # "at the base amount" unless the set is already dry, charging the surcharge
    # "for every case after that, until a replacement accessory set is
    # provisioned". So the threshold reads the set before this case draws on it:
    # the case that merely consumes the last life is still base-priced.
    approved = int(case.get("approved_instrument_load") or 0)
    if approved > 0 and system is not None:
        if instrument_lives_remaining(system) + approved <= 0:
            amount += LIVES_EXHAUSTION_SURCHARGE_CENTS
    return amount


def approved_load_total(system_id):
    total = 0
    for case in cases_of_system(system_id):
        if case.get("case_status") in ("SCHEDULED", "COMPLETED"):
            total += int(case.get("approved_instrument_load") or 0)
    return total


def reported_instrument_billing(case):
    """The figure the API reports for a case, choosing the variant by status.

    A SCHEDULED case reports the quote (the attempted load, before clamping) so
    the hospital's scheduling paperwork can be produced; every other status is
    read through the settle variant, which reports 0 for anything that is not
    COMPLETED (PRD §3.4).
    """
    if case is None:
        return 0
    if case.get("case_status") == "SCHEDULED":
        return instrument_billing(case, load=case.get("instrument_load") or 0, mode="quote")
    return instrument_billing(case, mode="settle")


def clamp_load(attempted, remaining):
    """min(attempted, remaining) — never above the remaining lives."""
    return max(0, min(int(attempted or 0), int(remaining or 0)))


def schedule_conflict(candidate_start, duration_minutes, siblings, ignore_case_id=None):
    """Half-open buffered occupancy overlap; adjacency is not a conflict."""
    if candidate_start is None:
        return False
    cand_start = candidate_start
    cand_end = candidate_start + timedelta(
        minutes=int(duration_minutes or 0) + TURNOVER_BUFFER_MINUTES)
    for sibling in siblings:
        if sibling.get("id") == ignore_case_id:
            continue
        if sibling.get("case_status") == "CANCELLED":
            continue
        span = _buffered_span(sibling)
        if span is None:
            continue
        if cand_start < span[1] and cand_end > span[0]:
            return True
    return False


# ---------------------------------------------------------------------------
# Surgeon training pathway
# ---------------------------------------------------------------------------

def simulation_ready(record):
    return int((record or {}).get("simulation_modules_completed") or 0) >= MIN_SIMULATION_MODULES


def proctoring_ready(record):
    return simulation_ready(record) and int((record or {}).get("required_proctored_cases") or 0) >= 1


def proctoring_satisfied(record):
    if not proctoring_ready(record):
        return False
    return (int(record.get("proctored_cases_completed") or 0)
            >= int(record.get("required_proctored_cases") or 0))


def credentialing_ready(record):
    if not proctoring_satisfied(record):
        return False
    for evidence in evidence_of_record(record.get("id")):
        if evidence.get("evidence_status") in ("VALID", "EXPIRING_SOON"):
            return True
    return False


def credential_valid(record):
    """Step 5 — inclusive against the evidence grace instant."""
    if record is None or record.get("training_status") != "CREDENTIALED":
        return False
    if not credentialing_ready(record):
        return False
    grace = _dt(record, "evidence_required_after_utc")
    if grace is None:
        return False
    return DB.clock <= grace


def family_eligible(account, procedure_family):
    """Step 6 — the family gate only bites from the activity floor upward."""
    if account is None:
        return True
    if service_line_tier_index(account) < ACTIVITY_TIER_FLOOR:
        return True
    families = set()
    for case in DB.procedure_cases.values():
        if case.get("hospital_account_id") != account.get("id"):
            continue
        if case.get("case_status") == "COMPLETED" and case.get("procedure_family"):
            families.add(case.get("procedure_family"))
    return procedure_family in families


def case_eligible(record, account, procedure_family=None):
    if not credential_valid(record):
        return False
    if procedure_family is None:
        return True
    return family_eligible(account, procedure_family)


def evidence_initial_status(expires):
    now = DB.clock
    if expires is not None and now < expires <= now + timedelta(days=EXPIRING_SOON_DAYS):
        return "EXPIRING_SOON"
    return "VALID"


def surge_operator_status(record):
    """The operator-capability rating derived from the credential and the
    cleared proctor requirement."""
    cleared = int((record or {}).get("proctored_cases_completed") or 0)
    if not credential_valid(record):
        return SURGEON_STATUS_LABELS[0]
    if cleared >= TRAINING_REQUIREMENT_UNITS:
        return SURGEON_STATUS_LABELS[2]
    return SURGEON_STATUS_LABELS[1]


# ---------------------------------------------------------------------------
# ServiceContract, incidents and penalty accounting
# ---------------------------------------------------------------------------

def service_tier_index(contract):
    """COMPREHENSIVE 3, STANDARD 2, LIMITED 1, PARTS_ONLY 0; -1 when the tier
    does not map into that closed set."""
    return TIER_INDEX_BY_COVERAGE.get((contract or {}).get("coverage_tier"), -1)


def contract_response_hours(contract):
    """The response-time commitment per coverage tier (PRD §2.8).

    PRD §2.8 pins the result verbatim — "The resulting commitment is 24 hours for
    `COMPREHENSIVE`, 12 for `STANDARD`, 18 for `LIMITED` and 24 for `PARTS_ONLY`"
    — and that enumeration is the single self-consistent statement of the rule.
    The prose formula surrounding it is internally contradictory: it names
    `COMPREHENSIVE` an index of 3 (so `48 − 12 × 3` is 12, never the 24 it
    asserts), yet it also says the unclamped `COMPREHENSIVE` branch is 36 and
    "the outer ceiling pulls the `COMPREHENSIVE` branch down from 36 hours to
    24," which requires an index of 1, not 3. No arithmetic satisfies all of that
    at once, so the enumerated table governs. `LIMITED` landing above `STANDARD`
    is the near-miss trap §2.8 names out loud.
    """
    return RESPONSE_HOURS_BY_COVERAGE.get((contract or {}).get("coverage_tier"))


def contract_end(contract):
    if contract is None:
        return None
    start = _dt(contract, "contract_start_utc")
    if start is None:
        return None
    months = int(contract.get("contract_months") or 0)
    return start + timedelta(days=INTERVAL_DAYS * months)


def contract_temporally_valid(contract, system):
    """The start instant falls on or after the site's installation instant and
    the end instant is strictly later than the start."""
    start = _dt(contract, "contract_start_utc")
    if start is None:
        return False
    end = contract_end(contract)
    if end is None or not end > start:
        return False
    installed = _dt(system, "installed_at_utc") if system is not None else None
    if installed is None:
        return True
    return start >= installed


def incident_severity(system, account):
    """CRITICAL when the system is in service-action-required; MAJOR when it is
    IN_SERVICE but the account's posture is not ACTIVE; MINOR otherwise."""
    if system is not None and system.get("service_status") == "SERVICE_ACTION_REQUIRED":
        return "CRITICAL"
    if system is not None and system.get("service_status") == "IN_SERVICE":
        if account_posture(account) != "ACTIVE":
            return "MAJOR"
    return "MINOR"


def incident_response_due(incident):
    stored = (incident or {}).get("response_due_at_utc")
    if stored:
        return stored
    started = _dt(incident, "incident_started_at")
    hours = incident.get("_commitment_hours")
    if started is None or hours is None:
        return None
    return to_iso(started + timedelta(hours=int(hours)))


def incident_breached(incident, instant=None):
    """The breach instant is exclusive: a resolution stamped exactly at
    response_due_at_utc is not a breach."""
    due = parse_iso8601(incident_response_due(incident))
    if due is None:
        return False
    if instant is None:
        for field in ("resolved_at_utc", "acknowledged_at_utc"):
            value = _dt(incident, field)
            if value is not None:
                instant = value
                break
    if instant is None:
        return False
    return instant > due


def incident_resolution_penalty(incident):
    """Decay function per PRD §2.9 / SCAFFOLD §1.3.

    t = service tier index + 1; the closed bands are 0 / 2 / 2t / 4t.
    """
    due = parse_iso8601(incident_response_due(incident))
    resolved = _dt(incident, "resolved_at_utc")
    if due is None or resolved is None:
        return 0
    tier = int(incident.get("_penalty_tier_index") or 0)
    t = tier + 1
    if resolved <= due:
        return 0
    if resolved <= due + timedelta(hours=GRACE_HOURS):
        return 2
    if resolved <= due + timedelta(hours=ESCALATION_HOURS):
        return 2 * t
    return 4 * t


def penalty_balance(account):
    """Opening balance after decay + resolved penalties, clamped to [0, 15]."""
    if account is None:
        return 0
    opening = max(0, int(account.get("_penalty_balance") or 0) - MONTHLY_DECAY_POINTS)
    total = opening
    for incident in DB.incidents.values():
        if incident.get("_account_id") != account.get("id"):
            continue
        total += incident_resolution_penalty(incident)
    return max(0, min(MAX_PENALTY_POINTS, total))


# ---------------------------------------------------------------------------
# Loaner and transfer windows
# ---------------------------------------------------------------------------

def loaner_buffered_end(start):
    return start + timedelta(days=LOANER_WINDOW_DAYS, hours=LOANER_BUFFER_HOURS)


def loaner_conflict(candidate_start, loaner_serial, dispatches, ignore_id=None):
    """Half-open buffered overlap on the same loaner unit; adjacency is
    permitted, a one-minute intrusion is not."""
    if candidate_start is None:
        return False
    cand_end = loaner_buffered_end(candidate_start)
    for dispatch in dispatches:
        if dispatch.get("id") == ignore_id:
            continue
        if dispatch.get("loaner_serial_number") != loaner_serial:
            continue
        if dispatch.get("reservation_status") not in ("PROGRAMMED", "ACTIVATED"):
            continue
        existing_start = _dt(dispatch, "dispatch_window_start_utc")
        if existing_start is None:
            continue
        existing_end = loaner_buffered_end(existing_start)
        if candidate_start < existing_end and cand_end > existing_start:
            return True
    return False


def transfer_conflict(candidate_start, candidate_end, destination_id, txns,
                      ignore_id=None):
    """Closed date range, day granularity, no merge grace (PRD §3.8).

    "Both endpoints of the transfer window are inclusive at day granularity, so
    the candidate window is the closed range from the start date through the end
    date inclusive," and a candidate is rejected when a non-reversed transaction
    on the same destination "has a closed window overlapping the candidate's".
    Two closed ranges overlap when neither starts after the other ends. "disregarding
    only gaps of 3 days or fewer" is the merge provision below, not a tolerance:
    a gap is accepted and merged, so it must not be rejected here.
    """
    if candidate_start is None or candidate_end is None:
        return False
    cs = candidate_start.date()
    ce = candidate_end.date()
    for txn in txns:
        if txn.get("id") == ignore_id:
            continue
        if txn.get("transaction_status") == "REVERSED":
            continue
        if txn.get("destination_account_id") != destination_id:
            continue
        es = _dt(txn, "transfer_window_start_utc")
        ee = _dt(txn, "transfer_window_end_utc")
        if es is None or ee is None:
            continue
        if cs <= ee.date() and ce >= es.date():
            return True
    return False


def transfer_merge_target(candidate_start, destination_id, txns, ignore_id=None):
    """The existing transaction a candidate is merged into (PRD §3.8).

    "a candidate whose start date falls within 3 days after an existing window's
    inclusive end date is merged into that window instead of being rejected, and
    the merged window then spans both."
    """
    if candidate_start is None:
        return None
    cs = candidate_start.date()
    grace = timedelta(days=TRANSFER_GRACE_DAYS)
    for txn in txns:
        if txn.get("id") == ignore_id:
            continue
        if txn.get("transaction_status") == "REVERSED":
            continue
        if txn.get("destination_account_id") != destination_id:
            continue
        ee = _dt(txn, "transfer_window_end_utc")
        if ee is None:
            continue
        if ee.date() < cs <= (ee + grace).date():
            return txn
    return None


def source_window_supply(source_id, txns):
    total = 0
    for txn in txns:
        if txn.get("transaction_status") == "REVERSED":
            continue
        if txn.get("source_account_id") != source_id:
            continue
        total += int(txn.get("procedure_units") or 0)
    return total


# ---------------------------------------------------------------------------
# IDN credit pool
# ---------------------------------------------------------------------------

def remaining_credit_units(ledger):
    if ledger is None:
        return 0
    return max(0, int(ledger.get("maximum_procedure_commitment") or 0)
               - int(ledger.get("consumed_procedure_units") or 0)
               - int(ledger.get("supplied_procedure_units") or 0))


def closing_consumption(account):
    if account is None:
        return 0
    consumed = sum(int(l.get("consumed_procedure_units") or 0)
                   for l in ledgers_of_account(account.get("id")))
    supplied = sum(int(l.get("supplied_procedure_units") or 0)
                   for l in ledgers_of_account(account.get("id")))
    code = account.get("idn_group_code")
    shared = 0
    for txn in DB.transfer_transactions.values():
        if txn.get("transaction_status") == "REVERSED":
            continue
        src = DB.hospital_accounts.get(txn.get("source_account_id"))
        dst = DB.hospital_accounts.get(txn.get("destination_account_id"))
        if (src and src.get("idn_group_code") == code) or (dst and dst.get("idn_group_code") == code):
            shared += int(txn.get("procedure_units") or 0)
    return consumed - supplied + shared


def pool_budget(account):
    """Caveat A: `placement_fee_cents == 0`, ignored while committed cases
    are above zero."""
    ledger = None
    for candidate in ledgers_of_account((account or {}).get("id")):
        ledger = candidate
        break
    caveat_a = False
    if ledger is not None:
        for agreement in agreements_of_account(account.get("id")):
            if (int(agreement.get("placement_fee_cents") or 0) == 0
                    and committed_cases(agreement) == 0):
                caveat_a = True
                break
    if caveat_a:
        return SURPLUS_POOL_BUDGET
    return int((ledger or {}).get("maximum_procedure_commitment") or 0)


def pool_left(account):
    """Unsigned: when negative the pool is over-consumed, never wrapped."""
    budget = pool_budget(account)
    consumed = sum(int(l.get("consumed_procedure_units") or 0)
                   for l in ledgers_of_account((account or {}).get("id")))
    return budget - consumed


def aggregate_utilisation(account):
    if account is None:
        return 0
    committed = sum(committed_cases(a) for a in agreements_of_account(account.get("id")))
    return committed + closing_consumption(account)


def pool_saturated(account):
    return aggregate_utilisation(account) >= MAX_POOL_UTILISATION_UNITS


# ---------------------------------------------------------------------------
# Expansion reviews: selection, allocation and status
# ---------------------------------------------------------------------------

def service_priority_of(system):
    contract = active_contract((system or {}).get("id"))
    if contract is None:
        contract = any_active_contract((system or {}).get("id"))
    index = service_tier_index(contract)
    return index if index >= 0 else -1


def select_eligible_system(account, exclude_system_id=None):
    """Highest service priority, ties broken by earliest created_at, never id."""
    candidates = [s for s in systems_of_account((account or {}).get("id"))
                  if expansion_eligible(s)]
    if exclude_system_id:
        candidates = [s for s in candidates if s.get("id") != exclude_system_id]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (-service_priority_of(s), s.get("created_at") or ""))
    return candidates[0]


def eligible_system_utilization(review):
    system = DB.robot_systems.get((review or {}).get("eligible_system_id"))
    if system is None:
        return 0
    cycle = current_cycle(system)
    return completed_case_count(cycle) if cycle else 0


def requires_prior_reporting_period(review):
    """True when the targeted agreement's reference cycle sits one reporting
    index behind the account's newest cycle."""
    account = DB.hospital_accounts.get((review or {}).get("hospital_account_id"))
    if account is None:
        return False
    newest = -1
    for system in systems_of_account(account.get("id")):
        for cycle in cycles_of_system(system.get("id")):
            newest = max(newest, int(cycle.get("reporting_period_index") or 0))
    agreement = DB.placement_agreements.get(review.get("placement_agreement_id"))
    if agreement is None:
        return False
    for cycle in cycles_of_agreement(agreement.get("id")):
        if int(cycle.get("reporting_period_index") or 0) == newest - 1:
            return True
    return False


def expansion_allocation(account, requested_case_capacity):
    """Binary support requests evaluated in the pinned order of PRD §3.7."""
    eligible = [s for s in systems_of_account((account or {}).get("id"))
                if expansion_eligible(s)]
    eligible_count = len(eligible)
    supported = 0
    for system in eligible:
        agreement = DB.placement_agreements.get(system.get("placement_agreement_id"))
        minimum = int((agreement or {}).get("minimum_procedures_per_cycle") or 0)
        if minimum <= EXPANSION_VOLUME_TARGET:
            supported += 1
    available = EXPANSION_VOLUME_TARGET * supported
    requested = int(requested_case_capacity or 0)
    allocated = min(requested, available)
    total_allocated = min(allocated, EXPANSION_VOLUME_TARGET * eligible_count)
    unallocated = max(0, EXPANSION_VOLUME_TARGET * (eligible_count - supported))
    return {
        "eligible_system_count": eligible_count,
        "supported_system_count": supported,
        "available_case_capacity": available,
        "allocate_case_capacity": allocated,
        "total_allocated_case_capacity": total_allocated,
        "unallocated_case_capacity": unallocated,
    }


def expansion_cap_ratio(allocation):
    """total allocated / (target × eligible count), floored at 0, 4 dp."""
    eligible_count = allocation["eligible_system_count"]
    if eligible_count <= 0:
        return Decimal("0.0000")
    denominator = Decimal(EXPANSION_VOLUME_TARGET * eligible_count)
    ratio = Decimal(allocation["total_allocated_case_capacity"]) / denominator
    ratio = max(Decimal("0"), ratio)
    return ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def expansion_status(account, requested_case_capacity=None):
    if requested_case_capacity is None:
        requested_case_capacity = _default_requested_capacity(account)
    allocation = expansion_allocation(account, requested_case_capacity)
    ratio = expansion_cap_ratio(allocation)
    if ratio < Decimal("1.0"):
        return "CAPACITY_DEFERRED"
    if allocation["unallocated_case_capacity"] == 0:
        return "EXPANSION_READY"
    return "CAPACITY_DEFERRED"


def _default_requested_capacity(account):
    """The account's newest pending support request, else the volume target."""
    capacity = None
    for review in DB.expansion_reviews.values():
        if review.get("hospital_account_id") != (account or {}).get("id"):
            continue
        if review.get("review_status") not in ("SUBMITTED", "APPROVED"):
            continue
        value = review.get("requested_case_capacity")
        if value is None:
            continue
        capacity = value if capacity is None else max(capacity, int(value))
    if capacity is None:
        return EXPANSION_VOLUME_TARGET
    return int(capacity)


# ---------------------------------------------------------------------------
# Shortfall, compliance tiers and escalation
# ---------------------------------------------------------------------------

def shortfall_procedures(agreement):
    minimum = int((agreement or {}).get("minimum_procedures_per_cycle") or 0)
    if minimum < 1:
        return 0
    return max(0, minimum - committed_cases(agreement))


def shortfall_fee(agreement):
    """USAGE_BASED with a commitment of at least 1 only; grace 2 is inclusive."""
    if agreement is None:
        return 0
    if agreement.get("arrangement_type") != "USAGE_BASED":
        return 0
    if int(agreement.get("minimum_procedures_per_cycle") or 0) < 1:
        return 0
    if agreement.get("is_shortfall_waived"):
        return 0
    short = shortfall_procedures(agreement)
    if short <= SHORTFALL_GRACE_PROCEDURES:
        return 0
    billable = short - SHORTFALL_GRACE_PROCEDURES
    fee = Decimal(int(agreement.get("placement_fee_cents") or 0))
    rate = Decimal(SHORTFALL_RATE_BASIS_POINTS)
    return round_half_up(Decimal(billable) * fee * rate / Decimal(10000))


def compliance_tier(agreement):
    streak = int((agreement or {}).get("_shortfall_streak") or 0)
    fee = Decimal(int((agreement or {}).get("placement_fee_cents") or 0))
    return round_half_up(Decimal(streak) * fee / Decimal(TIER_SCALE_DIVISOR))


def compliance_status(agreement):
    """The tier ladder of PRD §2.12; the warning band is closed at tier 10."""
    if agreement is None:
        return "MEETS_COMMITMENT"
    if agreement.get("is_shortfall_waived"):
        return "MEETS_COMMITMENT"
    if shortfall_procedures(agreement) == 0:
        return "MEETS_COMMITMENT"
    tier = compliance_tier(agreement)
    if tier <= 10:
        return "SHORTFALL_WARNING"
    if tier <= 25:
        return "SHORTFALL_CHARGEABLE"
    return "NON_COMPLIANT"


def escalation_tier(streak):
    """The largest t with REMAINDER(2**t, 7) != 1, examined with t ascending.

    Because 2**3 = 8 and 8 mod 7 = 1, the ladder stops at t = 2.
    """
    t = 0
    while t < 64 and pow(2, t + 1, ESCALATION_MODULUS) != 1:
        t += 1
    return t


def escalation_period_quota(tier):
    return {0: 0, 1: 1, 2: 2, 3: 4}.get(tier, 4)


def escalation_effective(agreement):
    """The escalation is effective when the quota is positive and the
    agreement's current cycle index is divisible by it."""
    tier = escalation_tier(int((agreement or {}).get("_shortfall_streak") or 0))
    quota = escalation_period_quota(tier)
    if quota <= 0:
        return False
    index = 0
    cycle = newest_cycle_of_agreement(agreement)
    if cycle is not None:
        index = int(cycle.get("reporting_period_index") or 0)
    return index % quota == 0


def newest_cycle_of_agreement(agreement):
    cycles = cycles_of_agreement((agreement or {}).get("id"))
    if not cycles:
        return None
    return max(cycles, key=lambda c: int(c.get("reporting_period_index") or 0))