"""Composite setup helpers.

These build the multi-step preconditions tests need without asserting anything
beyond "the setup step succeeded". They are organised in tiers:

  Tier 1  single-entity state progression (a pilot in a chosen status)
  Tier 2  entity hierarchies (a registered airframe under an owner, a zone)
  Tier 3  full lifecycle shortcuts (an approved authorization, a flown flight)
  Tier 4  accumulation and threshold targeting (risk score, eroded cover)
  Tier 5  finalisation and terminal states (a closed or withdrawn report)

Two conventions matter throughout. Optimistically concurrent writes always read
their parent row immediately beforehand, because the echoed version goes stale on
every mutation. And every helper that performs several hops is phased so that a
later hop never invalidates the precondition an earlier hop established.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .assertions import shift_days, shift_hours, shift_minutes
from .constants import CLOCK_STARTUP_UTC
from .test_users import (
    AIRSPACE_AUTHORITY,
    COMPLIANCE_OFFICER,
    INVESTIGATION_OFFICER,
    SAFETY_REVIEWER,
    WAIVER_APPROVER,
    make_pilot_headers,
)

FAR_FUTURE = "2029-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------


class Clock:
    """Tracks the logical clock inside a test.

    The clock starts at its startup value and is monotonic and forward-only, so
    every target handed to `set` must be strictly later than the present value.
    """

    def __init__(self, api, headers: Optional[Dict[str, str]] = None) -> None:
        self.api = api
        self.headers = headers or COMPLIANCE_OFFICER
        self.now = CLOCK_STARTUP_UTC

    def set(self, to_iso8601: str) -> str:
        data = get_success_data(self.api.set_clock(to_iso8601, headers=self.headers))
        self.now = data["current_utc"]
        return self.now

    def advance_days(self, days: int) -> str:
        return self.set(shift_days(self.now, days))

    def advance_minutes(self, minutes: int) -> str:
        return self.set(shift_minutes(self.now, minutes))

    def advance_hours(self, hours: int) -> str:
        return self.set(shift_hours(self.now, hours))


def set_clock(api, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Advance the clock and return the new `current_utc`."""
    data = get_success_data(api.set_clock(to_iso8601, headers=headers or COMPLIANCE_OFFICER))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# Tier 1 - pilot state progression
# ---------------------------------------------------------------------------


def create_pilot(api, operator_category: str = "RECREATIONAL", **overrides: Any) -> Dict[str, Any]:
    """A pilot in UNCERTIFIED with no certificate and no currency."""
    return get_success_data(
        api.create_pilot(f.pilot_payload(operator_category, **overrides), headers=COMPLIANCE_OFFICER),
        201,
    )


def read_pilot(api, pilot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_pilot(pilot_id, headers=headers or COMPLIANCE_OFFICER))


def pilot_version(api, pilot_id: str) -> int:
    """The pilot's current `version`, read immediately before an OCC write."""
    return read_pilot(api, pilot_id)["version"]


def schedule_and_pass_knowledge_test(
    api, pilot: Dict[str, Any], scheduled_at: Optional[str] = None
) -> Dict[str, Any]:
    """Book the exam the pilot's category permits and grade it at the pass mark."""
    category = pilot["operator_category"]
    test_code = "TRUST_RECREATIONAL" if category == "RECREATIONAL" else "PART107_COMMERCIAL"
    mark = 100 if category == "RECREATIONAL" else 70
    test = get_success_data(
        api.schedule_knowledge_test(
            pilot["id"],
            f.knowledge_test_payload(test_code, scheduled_at or CLOCK_STARTUP_UTC),
            headers=COMPLIANCE_OFFICER,
        ),
        201,
    )
    get_success_data(
        api.grade_knowledge_test(test["id"], f.grade_payload(mark), headers=COMPLIANCE_OFFICER)
    )
    return test


def create_certified_pilot(
    api,
    operator_category: str = "COMMERCIAL",
    scheduled_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A pilot in CERTIFIED, reached the only way the service allows: a passing grade.

    Note the currency consequence for a commercial operator: with no completed
    flight the recency anchor is the certificate's own `issued_at`, so currency
    runs out 90 days after issuance.
    """
    pilot = create_pilot(api, operator_category, **overrides)
    schedule_and_pass_knowledge_test(api, pilot, scheduled_at)
    return read_pilot(api, pilot["id"])


def create_suspended_pilot(
    api, operator_category: str = "COMMERCIAL", reason: str = "Manual enforcement action"
) -> Dict[str, Any]:
    pilot = create_certified_pilot(api, operator_category)
    get_success_data(
        api.suspend_pilot(pilot["id"], f.suspension_payload(reason), headers=COMPLIANCE_OFFICER)
    )
    return read_pilot(api, pilot["id"])


def create_revoked_pilot(api, operator_category: str = "COMMERCIAL") -> Dict[str, Any]:
    pilot = create_suspended_pilot(api, operator_category)
    get_success_data(
        api.revoke_pilot(pilot["id"], f.revocation_payload(), headers=COMPLIANCE_OFFICER)
    )
    return read_pilot(api, pilot["id"])


# ---------------------------------------------------------------------------
# Tier 2 - airframes, broadcast modules, zones and restrictions
# ---------------------------------------------------------------------------


def create_aircraft(
    api,
    owner_pilot_id: str,
    takeoff_weight_g: int = 1200,
    max_altitude_ft: int = 1500,
    **overrides: Any,
) -> Dict[str, Any]:
    """An airframe in PENDING_REGISTRATION, created by its own owner."""
    return get_success_data(
        api.create_aircraft(
            f.aircraft_payload(owner_pilot_id, takeoff_weight_g, max_altitude_ft, **overrides),
            headers=make_pilot_headers(owner_pilot_id),
        ),
        201,
    )


def create_verified_module(
    api,
    aircraft: Dict[str, Any],
    verified_until: str = FAR_FUTURE,
    **overrides: Any,
) -> Dict[str, Any]:
    """Attach a module and drive it UNVERIFIED -> VERIFICATION_PENDING -> VERIFIED."""
    owner_headers = make_pilot_headers(aircraft["owner_pilot_id"])
    module = get_success_data(
        api.create_remote_id_module(
            aircraft["id"], f.module_payload(**overrides), headers=owner_headers
        ),
        201,
    )
    get_success_data(
        api.submit_module_verification(
            module["id"], f.module_submission_payload(), headers=owner_headers
        )
    )
    return get_success_data(
        api.verify_remote_id_module(
            module["id"],
            f.module_verify_payload("VERIFIED", verified_until=verified_until),
            headers=COMPLIANCE_OFFICER,
        )
    )


def create_registered_aircraft(
    api,
    owner_pilot_id: str,
    takeoff_weight_g: int = 1200,
    max_altitude_ft: int = 1500,
    module_verified_until: str = FAR_FUTURE,
    **overrides: Any,
) -> Dict[str, Any]:
    """An airframe in REGISTERED, with a VERIFIED module first when one is required.

    The hops are phased deliberately: the module reaches VERIFIED before
    registration is attempted, because registration re-reads `remote_id_required`
    and refuses an airframe with no usable module.
    """
    aircraft = create_aircraft(
        api, owner_pilot_id, takeoff_weight_g, max_altitude_ft, **overrides
    )
    if aircraft["remote_id_required"]:
        create_verified_module(api, aircraft, verified_until=module_verified_until)
    return get_success_data(api.register_aircraft(aircraft["id"], headers=COMPLIANCE_OFFICER))


def create_grounded_aircraft(
    api, owner_pilot_id: str, reason: str = "Scheduled maintenance", **overrides: Any
) -> Dict[str, Any]:
    aircraft = create_registered_aircraft(api, owner_pilot_id, **overrides)
    return get_success_data(
        api.ground_aircraft(aircraft["id"], f.grounding_payload(reason), headers=COMPLIANCE_OFFICER)
    )


def create_zone(api, **overrides: Any) -> Dict[str, Any]:
    """An uncontrolled zone with `reserved_slot_count` 0 and `version` 1."""
    return get_success_data(
        api.create_zone(f.zone_payload(**overrides), headers=AIRSPACE_AUTHORITY), 201
    )


def create_controlled_zone(api, **overrides: Any) -> Dict[str, Any]:
    """A zone whose `requires_authorization` is true."""
    return get_success_data(
        api.create_zone(f.controlled_zone_payload(**overrides), headers=AIRSPACE_AUTHORITY), 201
    )


def read_zone(api, zone_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_zone(zone_id, headers=headers or AIRSPACE_AUTHORITY))


def zone_version(api, zone_id: str) -> int:
    """The zone's current `version`, read immediately before an OCC write."""
    return read_zone(api, zone_id)["version"]


def create_tfr(
    api,
    zone_id: str,
    effective_from: str,
    effective_until: str,
    max_permitted_altitude_ft: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A restriction in ACTIVE. Passing None for the altitude cap declares a total ban."""
    payload = f.tfr_payload(
        zone_id,
        effective_from,
        effective_until,
        **overrides,
    )
    if max_permitted_altitude_ft is not None:
        payload["max_permitted_altitude_ft"] = max_permitted_altitude_ft
    return get_success_data(api.create_tfr(payload, headers=AIRSPACE_AUTHORITY), 201)


# ---------------------------------------------------------------------------
# Tier 3 - lifecycle shortcuts
# ---------------------------------------------------------------------------


def create_requested_authorization(
    api,
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    window_start: str,
    window_end: str,
    requested_ceiling_ft: int = 400,
    waiver_id: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An authorization in REQUESTED. No slot is reserved at request time."""
    payload = f.authorization_payload(
        pilot_id,
        aircraft_id,
        zone_id,
        zone_version(api, zone_id),
        window_start,
        window_end,
        requested_ceiling_ft,
        **overrides,
    )
    if waiver_id is not None:
        payload["waiver_id"] = waiver_id
    return get_success_data(
        api.create_authorization(payload, headers=make_pilot_headers(pilot_id)), 201
    )


def create_approved_authorization(
    api,
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    window_start: str,
    window_end: str,
    requested_ceiling_ft: int = 400,
    waiver_id: Any = None,
    decider_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An authorization in APPROVED, holding one of the zone's concurrent slots."""
    authorization = create_requested_authorization(
        api,
        pilot_id,
        aircraft_id,
        zone_id,
        window_start,
        window_end,
        requested_ceiling_ft,
        waiver_id,
        **overrides,
    )
    return get_success_data(
        api.decide_authorization(
            authorization["id"],
            f.approve_authorization_payload(),
            headers=decider_headers or AIRSPACE_AUTHORITY,
        )
    )


def create_draft_waiver(
    api,
    pilot_id: str,
    aircraft_id: str,
    waiver_type: str = "OVER_PEOPLE",
    requested_ceiling_ft: int = 700,
    **overrides: Any,
) -> Dict[str, Any]:
    """A waiver application in DRAFT, echoing the pilot version read immediately before."""
    return get_success_data(
        api.create_waiver(
            f.waiver_payload(
                pilot_id,
                aircraft_id,
                pilot_version(api, pilot_id),
                waiver_type,
                requested_ceiling_ft,
                **overrides,
            ),
            headers=make_pilot_headers(pilot_id),
        ),
        201,
    )


def attach_safety_case(
    api,
    waiver: Dict[str, Any],
    ground_risk_class: int = 1,
    air_risk_class: str = "ARC_A",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_safety_case(
            waiver["id"],
            f.safety_case_payload(ground_risk_class, air_risk_class, **overrides),
            headers=make_pilot_headers(waiver["pilot_id"]),
        ),
        201,
    )


def create_under_review_waiver(
    api,
    pilot_id: str,
    aircraft_id: str,
    waiver_type: str = "OVER_PEOPLE",
    requested_ceiling_ft: int = 700,
    ground_risk_class: int = 1,
    air_risk_class: str = "ARC_A",
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A waiver in UNDER_REVIEW together with its safety case."""
    waiver = create_draft_waiver(
        api, pilot_id, aircraft_id, waiver_type, requested_ceiling_ft, **overrides
    )
    case = attach_safety_case(api, waiver, ground_risk_class, air_risk_class)
    pilot_headers = make_pilot_headers(pilot_id)
    get_success_data(api.submit_waiver(waiver["id"], headers=pilot_headers))
    waiver = get_success_data(api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER))
    return waiver, case


def create_cleared_waiver(
    api,
    pilot_id: str,
    aircraft_id: str,
    waiver_type: str = "OVER_PEOPLE",
    requested_ceiling_ft: int = 700,
    ground_risk_class: int = 1,
    air_risk_class: str = "ARC_A",
    reviewer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A waiver in CLEARED, with the reviewer's own id stamped on the safety case."""
    waiver, case = create_under_review_waiver(
        api,
        pilot_id,
        aircraft_id,
        waiver_type,
        requested_ceiling_ft,
        ground_risk_class,
        air_risk_class,
        **overrides,
    )
    waiver = get_success_data(
        api.clear_waiver_safety_case(
            waiver["id"],
            f.clear_safety_case_payload(),
            headers=reviewer_headers or SAFETY_REVIEWER,
        )
    )
    case = get_success_data(api.get_safety_case(case["id"], headers=SAFETY_REVIEWER))
    return waiver, case


def create_approved_waiver(
    api,
    pilot_id: str,
    aircraft_id: str,
    waiver_type: str = "OVER_PEOPLE",
    requested_ceiling_ft: int = 700,
    granted_ceiling_ft: Optional[int] = None,
    ground_risk_class: int = 1,
    air_risk_class: str = "ARC_A",
    approver_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A waiver in APPROVED with `valid_until` 180 days past the deciding instant.

    The clearing reviewer and the deciding approver are deliberately different
    principals, because the same human may not both clear and approve.
    """
    waiver, _case = create_cleared_waiver(
        api,
        pilot_id,
        aircraft_id,
        waiver_type,
        requested_ceiling_ft,
        ground_risk_class,
        air_risk_class,
        **overrides,
    )
    ceiling = requested_ceiling_ft if granted_ceiling_ft is None else granted_ceiling_ft
    return get_success_data(
        api.decide_waiver(
            waiver["id"],
            f.approve_waiver_payload(ceiling),
            headers=approver_headers or WAIVER_APPROVER,
        )
    )


def create_filed_policy(
    api,
    pilot_id: str,
    effective_from: str = CLOCK_STARTUP_UTC,
    effective_until: str = FAR_FUTURE,
    coverage_limit_cents: int = 5000000,
    deductible_cents: int = 100000,
    indemnification_clause_accepted: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """A policy in PENDING_VERIFICATION whose ledger figures are all still 0."""
    return get_success_data(
        api.create_policy(
            f.policy_payload(
                pilot_id,
                effective_from,
                effective_until,
                coverage_limit_cents,
                deductible_cents,
                indemnification_clause_accepted,
                **overrides,
            ),
            headers=make_pilot_headers(pilot_id),
        ),
        201,
    )


def create_active_policy(
    api,
    pilot_id: str,
    effective_from: str = CLOCK_STARTUP_UTC,
    effective_until: str = FAR_FUTURE,
    coverage_limit_cents: int = 5000000,
    deductible_cents: int = 100000,
    indemnification_clause_accepted: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """A policy in ACTIVE with its ledger opened at the full coverage limit."""
    policy = create_filed_policy(
        api,
        pilot_id,
        effective_from,
        effective_until,
        coverage_limit_cents,
        deductible_cents,
        indemnification_clause_accepted,
        **overrides,
    )
    return get_success_data(
        api.verify_policy(policy["id"], f.activate_policy_payload(), headers=COMPLIANCE_OFFICER)
    )


def read_policy(api, policy_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_policy(policy_id, headers=headers or COMPLIANCE_OFFICER))


def create_planned_flight(
    api,
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    planned_start: str,
    planned_end: str,
    operation_category: str = "RECREATIONAL",
    planned_max_altitude_ft: int = 400,
    authorization_id: Any = None,
    waiver_id: Any = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A flight in PLANNED with `investigation_status` NONE."""
    payload = f.flight_payload(
        pilot_id,
        aircraft_id,
        zone_id,
        planned_start,
        planned_end,
        operation_category,
        planned_max_altitude_ft,
        **overrides,
    )
    if authorization_id is not None:
        payload["authorization_id"] = authorization_id
    if waiver_id is not None:
        payload["waiver_id"] = waiver_id
    return get_success_data(
        api.create_flight(payload, headers=make_pilot_headers(pilot_id)), 201
    )


def clear_flight_for_launch(
    api, flight: Dict[str, Any], acknowledged_tfr_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Run the pre-flight sweep and return the appended check record.

    A FAILED result is returned as a recorded advisory with a 201, so callers that
    need PREFLIGHT_CLEARED must inspect the record rather than assume success.
    """
    return get_success_data(
        api.preflight_check(
            flight["id"],
            f.preflight_check_payload(acknowledged_tfr_ids),
            headers=make_pilot_headers(flight["pilot_id"]),
        ),
        201,
    )


def create_cleared_flight(
    api,
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    planned_start: str,
    planned_end: str,
    acknowledged_tfr_ids: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A flight in PREFLIGHT_CLEARED, reached through a PASSED check."""
    flight = create_planned_flight(
        api, pilot_id, aircraft_id, zone_id, planned_start, planned_end, **kwargs
    )
    check = clear_flight_for_launch(api, flight, acknowledged_tfr_ids)
    assert check["result"] == "PASSED", (
        f"setup expected a PASSED pre-flight check, got findings {check['blocking_findings']}"
    )
    return get_success_data(api.get_flight(flight["id"], headers=make_pilot_headers(pilot_id)))


def create_in_progress_flight(
    api,
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    planned_start: str,
    planned_end: str,
    acknowledged_tfr_ids: Optional[List[str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A flight in IN_PROGRESS with `actual_start` at the launching instant."""
    flight = create_cleared_flight(
        api,
        pilot_id,
        aircraft_id,
        zone_id,
        planned_start,
        planned_end,
        acknowledged_tfr_ids,
        **kwargs,
    )
    return get_success_data(
        api.launch_flight(flight["id"], headers=make_pilot_headers(pilot_id))
    )


def create_completed_flight(
    api,
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    planned_start: str,
    planned_end: str,
    duration_minutes: int = 45,
    max_altitude_reached_ft: int = 300,
    incident_occurred: bool = False,
    acknowledged_tfr_ids: Optional[List[str]] = None,
    actual_end: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A flight in COMPLETED, which moves the pilot's recency anchor forward."""
    flight = create_in_progress_flight(
        api,
        pilot_id,
        aircraft_id,
        zone_id,
        planned_start,
        planned_end,
        acknowledged_tfr_ids,
        **kwargs,
    )
    end = actual_end or shift_minutes(flight["actual_start"], duration_minutes)
    return get_success_data(
        api.complete_flight(
            flight["id"],
            f.completion_payload(end, max_altitude_reached_ft, incident_occurred),
            headers=make_pilot_headers(pilot_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# ---------------------------------------------------------------------------


def create_filed_report(
    api,
    flight: Dict[str, Any],
    occurred_at: str,
    injury_level: str = "NONE",
    reported_property_damage_cents: int = 400000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A report in FILED, which opens the flight's investigation dimension and
    takes the provisional reserve against the covering policy."""
    return get_success_data(
        api.create_accident_report(
            f.accident_report_payload(
                flight["id"], occurred_at, injury_level, reported_property_damage_cents, **overrides
            ),
            headers=make_pilot_headers(flight["pilot_id"]),
        ),
        201,
    )


def create_investigating_report(
    api,
    flight: Dict[str, Any],
    occurred_at: str,
    injury_level: str = "NONE",
    reported_property_damage_cents: int = 400000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A report in INVESTIGATING; the reserve is untouched by opening the investigation."""
    report = create_filed_report(
        api, flight, occurred_at, injury_level, reported_property_damage_cents, **overrides
    )
    return get_success_data(
        api.open_investigation(report["id"], headers=INVESTIGATION_OFFICER)
    )


def create_remediation_report(
    api,
    flight: Dict[str, Any],
    occurred_at: str,
    injury_level: str = "NONE",
    reported_property_damage_cents: int = 400000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A report in REMEDIATION_REQUIRED with `remediation_round` 1."""
    report = create_investigating_report(
        api, flight, occurred_at, injury_level, reported_property_damage_cents, **overrides
    )
    return get_success_data(
        api.require_remediation(
            report["id"], f.remediation_payload(), headers=INVESTIGATION_OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 - finalisation and terminal states
# ---------------------------------------------------------------------------


def close_report(
    api,
    report: Dict[str, Any],
    damage_line_items: List[Dict[str, Any]],
    probable_cause: str = "Loss of link during descent",
    closer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Close an INVESTIGATING report, replacing the reserve with the settlement."""
    return get_success_data(
        api.close_accident_report(
            report["id"],
            f.close_report_payload(damage_line_items, probable_cause),
            headers=closer_headers or INVESTIGATION_OFFICER,
        )
    )


def withdraw_report(
    api, report: Dict[str, Any], closer_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Withdraw a FILED or INVESTIGATING report, releasing the reserve in full."""
    return get_success_data(
        api.withdraw_accident_report(
            report["id"], headers=closer_headers or INVESTIGATION_OFFICER
        )
    )


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------


def setup_recreational_operation(
    api,
    takeoff_weight_g: int = 1200,
    max_altitude_ft: int = 1500,
    zone_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CERTIFIED recreational pilot, their REGISTERED airframe and an uncontrolled zone."""
    pilot = create_certified_pilot(api, "RECREATIONAL")
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=takeoff_weight_g, max_altitude_ft=max_altitude_ft
    )
    zone = create_zone(api, **(zone_overrides or {}))
    return {"pilot": pilot, "aircraft": aircraft, "zone": zone}


def setup_commercial_operation(
    api,
    takeoff_weight_g: int = 1200,
    max_altitude_ft: int = 1500,
    coverage_limit_cents: int = 5000000,
    deductible_cents: int = 100000,
    policy_effective_until: str = FAR_FUTURE,
    zone_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CERTIFIED commercial pilot with a REGISTERED airframe, a zone and ACTIVE cover."""
    pilot = create_certified_pilot(api, "COMMERCIAL")
    aircraft = create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=takeoff_weight_g, max_altitude_ft=max_altitude_ft
    )
    zone = create_zone(api, **(zone_overrides or {}))
    policy = create_active_policy(
        api,
        pilot["id"],
        effective_until=policy_effective_until,
        coverage_limit_cents=coverage_limit_cents,
        deductible_cents=deductible_cents,
    )
    return {"pilot": pilot, "aircraft": aircraft, "zone": zone, "policy": policy}
