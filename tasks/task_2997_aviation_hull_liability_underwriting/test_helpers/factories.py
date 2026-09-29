"""Request payload builders.

Each builder returns a complete, valid payload for one endpoint and accepts
keyword overrides.  Overrides are applied by updating the assembled dictionary,
so no key is ever supplied twice.  Money is always an integer number of cents
expressed as a JSON number, and every timestamp is a full ISO-8601 instant.
"""

import itertools

from .constants import (
    ACQUISITION_REPORTING_DAYS_DEFAULT,
)
from .types import (
    AcquisitionSource,
    AircraftClass,
    CooperationStatus,
    CoverageDecision,
    DeclarationDecision,
    EndorsementType,
    LicenseType,
    LossType,
    OperatorType,
    PerilsScope,
    PolicyType,
    SalvageAction,
    SettlementBasis,
    TerritorialLimit,
    TerritoryCode,
    UseClass,
    WarrantyFinding,
)

# ----------------------------------------------------------------------
# Canonical instants used throughout the suite.
#
# The clock is parked inside the policy term wherever a test exercises
# behaviour that depends on the current instant.
# ----------------------------------------------------------------------
CLOCK_BEFORE_INCEPTION = "2026-08-15T00:00:00Z"
CLOCK_MID_TERM = "2026-09-15T00:00:00Z"
CLOCK_LATE_TERM = "2026-11-01T00:00:00Z"
CLOCK_AFTER_LOSS = "2026-10-15T00:00:00Z"
CLOCK_AFTER_EXPIRY = "2027-09-02T00:00:00Z"

POLICY_EFFECTIVE_FROM = "2026-09-01T00:00:00Z"
POLICY_EFFECTIVE_TO = "2027-09-01T00:00:00Z"
POLICY_TERM_DAYS = 365

_mark_counter = itertools.count(1)


def unique_registration_mark(prefix: str = "N9") -> str:
    """A registration mark that no other airframe in this test has used."""
    return f"{prefix}{next(_mark_counter):04d}"


def _build(base: dict, overrides: dict) -> dict:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# The logical clock
# ----------------------------------------------------------------------
def clock_payload(current_utc: str = CLOCK_BEFORE_INCEPTION, **overrides) -> dict:
    return _build({"current_utc": current_utc}, overrides)


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------
def operator_payload(**overrides) -> dict:
    """A flight school, which is the operator type most of the suite uses."""
    return _build(
        {
            "legal_name": "Northwind Flight Academy",
            "operator_type": OperatorType.FLIGHT_SCHOOL,
            "home_base_icao": "KBFI",
        },
        overrides,
    )


def air_carrier_operator_payload(**overrides) -> dict:
    """An air carrier, for which the certificate number is mandatory."""
    return _build(
        {
            "legal_name": "Cascade Regional Airways",
            "operator_type": OperatorType.AIR_CARRIER,
            "home_base_icao": "KSEA",
            "aoc_number": "AOC-4471",
        },
        overrides,
    )


def private_owner_operator_payload(**overrides) -> dict:
    return _build(
        {
            "legal_name": "Harbour Point Holdings",
            "operator_type": OperatorType.PRIVATE_OWNER,
            "home_base_icao": "KPAE",
        },
        overrides,
    )


def flying_club_operator_payload(**overrides) -> dict:
    return _build(
        {
            "legal_name": "Puget Sound Flying Club",
            "operator_type": OperatorType.FLYING_CLUB,
            "home_base_icao": "KRNT",
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Airframes
# ----------------------------------------------------------------------
def aircraft_payload(**overrides) -> dict:
    """A 2016 twin, whose depreciation is visible at the default clock year."""
    return _build(
        {
            "registration_mark": "N511NW",
            "aircraft_class": AircraftClass.MULTI_PISTON,
            "manufacture_year": 2016,
            "hull_new_value_cents": 66000000,
            "seat_count": 6,
            "max_takeoff_weight_kg": 2495,
        },
        overrides,
    )


def single_piston_aircraft_payload(registration_mark: str = "N512NW", **overrides) -> dict:
    """A 2020 single, the standard trainer of the fleet."""
    return _build(
        {
            "registration_mark": registration_mark,
            "aircraft_class": AircraftClass.SINGLE_PISTON,
            "manufacture_year": 2020,
            "hull_new_value_cents": 40000000,
            "seat_count": 4,
            "max_takeoff_weight_kg": 1300,
        },
        overrides,
    )


def turboprop_aircraft_payload(registration_mark: str = "N521NW", **overrides) -> dict:
    """A 2022 turboprop, used for the automatically acquired hulls."""
    return _build(
        {
            "registration_mark": registration_mark,
            "aircraft_class": AircraftClass.TURBOPROP,
            "manufacture_year": 2022,
            "hull_new_value_cents": 50000000,
            "seat_count": 8,
            "max_takeoff_weight_kg": 4200,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Pilots
# ----------------------------------------------------------------------
def pilot_payload(**overrides) -> dict:
    """A commercial pilot who scores into the third rating band on logged hours."""
    return _build(
        {
            "pilot_name": "Dana Reyes",
            "license_type": LicenseType.CPL,
            "total_logged_hours": 1200,
            "hours_on_type": 80,
            "last_training_completed_at": "2026-06-01T00:00:00Z",
            "medical_expires_at": "2027-06-30T00:00:00Z",
            "instrument_rated": False,
        },
        overrides,
    )


def senior_pilot_payload(**overrides) -> dict:
    """An airline transport pilot who scores into the first rating band."""
    return _build(
        {
            "pilot_name": "Morgan Vale",
            "license_type": LicenseType.ATPL,
            "total_logged_hours": 3000,
            "hours_on_type": 300,
            "last_training_completed_at": "2026-07-01T00:00:00Z",
            "medical_expires_at": "2028-01-31T00:00:00Z",
            "instrument_rated": True,
        },
        overrides,
    )


def student_pilot_payload(**overrides) -> dict:
    """A student pilot who falls short of every warranty minimum."""
    return _build(
        {
            "pilot_name": "Alex Iverson",
            "license_type": LicenseType.STUDENT,
            "total_logged_hours": 60,
            "hours_on_type": 5,
            "last_training_completed_at": "2026-07-15T00:00:00Z",
            "medical_expires_at": "2027-12-31T00:00:00Z",
            "instrument_rated": False,
        },
        overrides,
    )


def hours_verification_payload(
    verified_total_hours: int = 600, verified_hours_on_type: int = 50, **overrides
) -> dict:
    return _build(
        {
            "verified_total_hours": verified_total_hours,
            "verified_hours_on_type": verified_hours_on_type,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Policies
# ----------------------------------------------------------------------
def policy_payload(operator_id: str, **overrides) -> dict:
    """A worldwide fleet policy running a full 365-day term from 1 September."""
    return _build(
        {
            "operator_id": operator_id,
            "policy_type": PolicyType.FLEET,
            "effective_from": POLICY_EFFECTIVE_FROM,
            "effective_to": POLICY_EFFECTIVE_TO,
            "territorial_limit_code": TerritorialLimit.WORLDWIDE,
            "base_hull_rate_ppm": 18000,
            "hull_deductible_ppm": 15000,
            "liability_limit_cents": 500000000,
            "hull_aggregate_limit_cents": 900000000,
            "permitted_use_classes": [
                UseClass.PRIVATE,
                UseClass.BUSINESS,
                UseClass.INSTRUCTIONAL,
            ],
            "automatic_acquisition_enabled": False,
            "acquisition_reporting_days": ACQUISITION_REPORTING_DAYS_DEFAULT,
            "war_risk_required": False,
        },
        overrides,
    )


def single_aircraft_policy_payload(operator_id: str, **overrides) -> dict:
    """A single-airframe policy, which never earns the fleet size credit."""
    return _build(
        policy_payload(
            operator_id,
            policy_type=PolicyType.SINGLE_AIRCRAFT,
            permitted_use_classes=[UseClass.PRIVATE, UseClass.BUSINESS],
        ),
        overrides,
    )


def minimal_policy_payload(operator_id: str, **overrides) -> dict:
    """A policy carrying only the mandatory inputs, so defaults are observable."""
    return _build(
        {
            "operator_id": operator_id,
            "policy_type": PolicyType.SINGLE_AIRCRAFT,
            "effective_from": POLICY_EFFECTIVE_FROM,
            "effective_to": POLICY_EFFECTIVE_TO,
            "territorial_limit_code": TerritorialLimit.DOMESTIC,
            "base_hull_rate_ppm": 18000,
            "hull_deductible_ppm": 15000,
            "liability_limit_cents": 500000000,
            "hull_aggregate_limit_cents": 900000000,
        },
        overrides,
    )


# ----------------------------------------------------------------------
# Aircraft schedules
# ----------------------------------------------------------------------
def schedule_payload(
    policy_id: str, aircraft_id: str, named_pilot_id: str, **overrides
) -> dict:
    """An instructional hull scheduled for the whole policy term."""
    return _build(
        {
            "policy_id": policy_id,
            "aircraft_id": aircraft_id,
            "named_pilot_id": named_pilot_id,
            "use_class": UseClass.INSTRUCTIONAL,
            "agreed_value_cents": 45000000,
            "effective_from": POLICY_EFFECTIVE_FROM,
            "effective_to": POLICY_EFFECTIVE_TO,
            "acquisition_source": AcquisitionSource.SCHEDULED,
        },
        overrides,
    )


def private_schedule_payload(
    policy_id: str, aircraft_id: str, named_pilot_id: str, **overrides
) -> dict:
    """A private-use hull at the standard thirty million agreed value."""
    return _build(
        schedule_payload(
            policy_id,
            aircraft_id,
            named_pilot_id,
            use_class=UseClass.PRIVATE,
            agreed_value_cents=30000000,
        ),
        overrides,
    )


def value_revision_payload(
    new_agreed_value_cents: int, expected_schedule_version: int, **overrides
) -> dict:
    return _build(
        {
            "new_agreed_value_cents": new_agreed_value_cents,
            "expected_schedule_version": expected_schedule_version,
        },
        overrides,
    )


def warranty_finding_payload(finding: str, **overrides) -> dict:
    payload = {"finding": finding}
    if finding == WarrantyFinding.BREACH:
        payload["breach_reason"] = (
            "Logbook audit could not evidence the warranted hours on type"
        )
    return _build(payload, overrides)


# ----------------------------------------------------------------------
# Endorsements
# ----------------------------------------------------------------------
def endorsement_payload(
    policy_id: str,
    endorsement_type: str,
    effective_date: str = CLOCK_LATE_TERM,
    **overrides,
) -> dict:
    """The three fields every endorsement submission carries."""
    return _build(
        {
            "policy_id": policy_id,
            "endorsement_type": endorsement_type,
            "effective_date": effective_date,
        },
        overrides,
    )


def add_aircraft_endorsement_payload(
    policy_id: str,
    aircraft_id: str,
    named_pilot_id: str,
    effective_date: str = CLOCK_LATE_TERM,
    **overrides,
) -> dict:
    return _build(
        endorsement_payload(
            policy_id,
            EndorsementType.ADD_AIRCRAFT,
            effective_date,
            aircraft_id=aircraft_id,
            named_pilot_id=named_pilot_id,
            new_agreed_value_cents=30000000,
            new_use_class=UseClass.PRIVATE,
        ),
        overrides,
    )


def remove_aircraft_endorsement_payload(
    policy_id: str, target_schedule_id: str, effective_date: str = CLOCK_LATE_TERM, **overrides
) -> dict:
    return _build(
        endorsement_payload(
            policy_id,
            EndorsementType.REMOVE_AIRCRAFT,
            effective_date,
            target_schedule_id=target_schedule_id,
        ),
        overrides,
    )


def value_revision_endorsement_payload(
    policy_id: str,
    target_schedule_id: str,
    new_agreed_value_cents: int = 50000000,
    effective_date: str = CLOCK_LATE_TERM,
    **overrides,
) -> dict:
    return _build(
        endorsement_payload(
            policy_id,
            EndorsementType.VALUE_REVISION,
            effective_date,
            target_schedule_id=target_schedule_id,
            new_agreed_value_cents=new_agreed_value_cents,
        ),
        overrides,
    )


def use_class_change_endorsement_payload(
    policy_id: str,
    target_schedule_id: str,
    new_use_class: str = UseClass.BUSINESS,
    effective_date: str = CLOCK_LATE_TERM,
    **overrides,
) -> dict:
    return _build(
        endorsement_payload(
            policy_id,
            EndorsementType.USE_CLASS_CHANGE,
            effective_date,
            target_schedule_id=target_schedule_id,
            new_use_class=new_use_class,
        ),
        overrides,
    )


def territory_extension_endorsement_payload(
    policy_id: str,
    territory_code: str = TerritoryCode.CONTINENTAL,
    effective_date: str = CLOCK_LATE_TERM,
    **overrides,
) -> dict:
    return _build(
        endorsement_payload(
            policy_id,
            EndorsementType.TERRITORY_EXTENSION,
            effective_date,
            territory_code=territory_code,
        ),
        overrides,
    )


def exposure_endorsement_payload(
    policy_id: str,
    endorsement_type: str,
    exposure_member_count: int = 40,
    per_seat_limit_cents: int = 25000000,
    effective_date: str = CLOCK_LATE_TERM,
    **overrides,
) -> dict:
    return _build(
        endorsement_payload(
            policy_id,
            endorsement_type,
            effective_date,
            exposure_member_count=exposure_member_count,
            per_seat_limit_cents=per_seat_limit_cents,
        ),
        overrides,
    )


def referral_payload(
    referral_reason: str = "Risk survey outstanding", **overrides
) -> dict:
    return _build({"referral_reason": referral_reason}, overrides)


def void_payload(void_reason: str = "Broker withdrew the request", **overrides) -> dict:
    return _build({"void_reason": void_reason}, overrides)


# ----------------------------------------------------------------------
# War, hijacking and terrorism
# ----------------------------------------------------------------------
def war_market_payload(**overrides) -> dict:
    """A market writing the widest peril scope on a ten million dollar line.

    ``perils_offered`` is a single ordered scope, not a list: a market writing
    ``WAR_HIJACK_TERRORISM`` implicitly accepts the two narrower scopes.
    """
    return _build(
        {
            "market_name": "Lime Street War Syndicate 4412",
            "aggregate_line_cents": 1000000000,
            "perils_offered": PerilsScope.WAR_HIJACK_TERRORISM,
        },
        overrides,
    )


def war_placement_payload(
    policy_id: str,
    market_id: str,
    expected_policy_version: int,
    **overrides,
) -> dict:
    """A hijack-scope placement covering the first half of the policy term."""
    return _build(
        {
            "policy_id": policy_id,
            "market_id": market_id,
            "war_hull_line_cents": 600000000,
            "perils_scope": PerilsScope.WAR_HIJACK,
            "coverage_from": POLICY_EFFECTIVE_FROM,
            "coverage_to": "2027-03-01T00:00:00Z",
            "expected_policy_version": expected_policy_version,
        },
        overrides,
    )


def cancellation_payload(
    cancellation_reason: str = "Slip re-broked to another syndicate", **overrides
) -> dict:
    return _build({"cancellation_reason": cancellation_reason}, overrides)


# ----------------------------------------------------------------------
# Claims
# ----------------------------------------------------------------------
def claim_payload(policy_id: str, schedule_id: str, **overrides) -> dict:
    """A hull damage notification dated a few days after inception."""
    return _build(
        {
            "policy_id": policy_id,
            "schedule_id": schedule_id,
            "loss_date": "2026-09-05T00:00:00Z",
            "loss_type": LossType.HULL_DAMAGE,
            "loss_description": "Heavy landing, structural inspection ordered",
        },
        overrides,
    )


def investigation_payload(
    cooperation_status: str = CooperationStatus.COOPERATING,
    investigator_reference: str = "AAIB-2026-0301",
    **overrides,
) -> dict:
    return _build(
        {
            "cooperation_status": cooperation_status,
            "investigator_reference": investigator_reference,
        },
        overrides,
    )


def damage_assessment_payload(
    claim_id: str,
    repair_cost_estimate_cents: int = 20000000,
    assessed_at: str = "2026-09-10T00:00:00Z",
    **overrides,
) -> dict:
    return _build(
        {
            "claim_id": claim_id,
            "repair_cost_estimate_cents": repair_cost_estimate_cents,
            "assessor_reference": "SURV-4405",
            "assessed_at": assessed_at,
        },
        overrides,
    )


def coverage_decision_payload(
    decision: str = CoverageDecision.COVERED,
    reserve_cents: int = 20000000,
    **overrides,
) -> dict:
    payload = {"decision": decision}
    if decision == CoverageDecision.COVERED:
        payload["reserve_cents"] = reserve_cents
    else:
        payload["denial_reason"] = "Loss falls outside the scheduled use class"
    return _build(payload, overrides)


def salvage_disposition_payload(salvage_action: str, **overrides) -> dict:
    payload = {"salvage_action": salvage_action}
    if salvage_action == SalvageAction.SELL:
        payload["salvage_proceeds_cents"] = 3000000
    return _build(payload, overrides)


def settlement_payload(
    settlement_basis: str = SettlementBasis.AGREED_VALUE, **overrides
) -> dict:
    return _build({"settlement_basis": settlement_basis}, overrides)


# ----------------------------------------------------------------------
# Fleet declarations
# ----------------------------------------------------------------------
def fleet_declaration_payload(
    policy_id: str,
    period_from: str = POLICY_EFFECTIVE_FROM,
    period_to: str = "2026-09-30T00:00:00Z",
    **overrides,
) -> dict:
    return _build(
        {
            "policy_id": policy_id,
            "period_from": period_from,
            "period_to": period_to,
        },
        overrides,
    )


def declaration_acceptance_payload(
    decision: str = DeclarationDecision.ACCEPT, **overrides
) -> dict:
    payload = {"decision": decision}
    if decision == DeclarationDecision.REJECT:
        payload["rejection_reason"] = "Late notification of the acquisition"
    return _build(payload, overrides)
