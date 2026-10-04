"""Duty rotation: the SAFETY_WATCH credential gate, half-open overlap
semantics, the inclusive fatigue cap, fatigue accrual/reset, and the pinned
priority of the overlap rule over the fatigue cap."""
from test_helpers import (
    ApiErrorId,
    get_volunteer,
    list_deployment_shifts,
    run_ops_epoch,
    set_clock,
    setup_fatigued_volunteer,
    setup_on_site_deployment,
    validate_error,
    validate_success,
)

FATIGUE_36_SHIFTS = [
    ("2026-09-10T08:00:00Z", "2026-09-10T20:00:00Z"),
    ("2026-09-11T08:00:00Z", "2026-09-11T20:00:00Z"),
    ("2026-09-12T08:00:00Z", "2026-09-12T20:00:00Z"),
]


def test_safety_watch_requires_medical_or_structural_cert(api, operations_lead_headers):
    """PRD §3.5: "The credential gate applies to `SAFETY_WATCH` shifts: the deployment's volunteer must hold a `VERIFIED` `MEDICAL` or `STRUCTURAL` certification, else `ERR_CERT_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/validations/safety_watch_shift_requires_medical_or_structural
    """
    bundle = setup_on_site_deployment()  # volunteer holds VERIFIED CHAINSAW only
    operation_id = bundle["operation"]["id"]
    deployment_id = bundle["deployment"]["id"]
    resp = api.create_duty_shift(
        operation_id,
        {
            "deployment_id": deployment_id,
            "kind": "SAFETY_WATCH",
            "starts_at": "2026-09-10T08:00:00Z",
            "ends_at": "2026-09-10T12:00:00Z",
        },
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_VERIFIED)
    resp = api.create_duty_shift(
        operation_id,
        {
            "deployment_id": deployment_id,
            "kind": "OPERATIONS",
            "starts_at": "2026-09-10T08:00:00Z",
            "ends_at": "2026-09-10T12:00:00Z",
        },
        operations_lead_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_adjacent_shift_touching_boundary_admitted(api, operations_lead_headers):
    """PRD §3.5: "The overlap rule treats every shift as a half-open interval — the start is inclusive, the end exclusive — and rejects the new shift with `ERR_SHIFT_OVERLAP` (HTTP 409) when another `SCHEDULED` or `COMPLETED` shift of the same deployment starts before the new shift ends and ends after the new shift starts; two shifts that merely touch, one ending exactly when the other begins, are admissible."

    Design: Difficulty/resource_temporal_overlap/duty_shift_half_open_adjacency
    """
    bundle = setup_on_site_deployment()
    operation_id = bundle["operation"]["id"]
    deployment_id = bundle["deployment"]["id"]
    shift_a = validate_success(
        api.create_duty_shift(
            operation_id,
            {
                "deployment_id": deployment_id,
                "kind": "OPERATIONS",
                "starts_at": "2026-09-10T08:00:00Z",
                "ends_at": "2026-09-10T12:00:00Z",
            },
            operations_lead_headers,
        ),
        201,
    )
    assert shift_a["status"] == "SCHEDULED"
    # Adjacent: starts exactly when shift A ends -> admissible under half-open semantics.
    shift_b = validate_success(
        api.create_duty_shift(
            operation_id,
            {
                "deployment_id": deployment_id,
                "kind": "LOGISTICS",
                "starts_at": "2026-09-10T12:00:00Z",
                "ends_at": "2026-09-10T16:00:00Z",
            },
            operations_lead_headers,
        ),
        201,
    )
    assert shift_b["status"] == "SCHEDULED"


def test_straddling_shift_rejected_and_nothing_persisted(api, operations_lead_headers):
    """PRD §3.5: "rejects the new shift with `ERR_SHIFT_OVERLAP` (HTTP 409) when another `SCHEDULED` or `COMPLETED` shift of the same deployment starts before the new shift ends and ends after the new shift starts; two shifts that merely touch, one ending exactly when the other begins, are admissible."

    Design: Difficulty/resource_temporal_overlap/duty_shift_half_open_adjacency
    """
    bundle = setup_on_site_deployment()
    operation_id = bundle["operation"]["id"]
    deployment_id = bundle["deployment"]["id"]
    validate_success(
        api.create_duty_shift(
            operation_id,
            {
                "deployment_id": deployment_id,
                "kind": "OPERATIONS",
                "starts_at": "2026-09-10T08:00:00Z",
                "ends_at": "2026-09-10T12:00:00Z",
            },
            operations_lead_headers,
        ),
        201,
    )
    validate_success(
        api.create_duty_shift(
            operation_id,
            {
                "deployment_id": deployment_id,
                "kind": "LOGISTICS",
                "starts_at": "2026-09-10T12:00:00Z",
                "ends_at": "2026-09-10T16:00:00Z",
            },
            operations_lead_headers,
        ),
        201,
    )
    # Straddles the interior of the first shift (10:00 ends before 11:00 start is false;
    # 11:00 < 12:00 and 13:00 > 08:00 -> overlap).
    resp = api.create_duty_shift(
        operation_id,
        {
            "deployment_id": deployment_id,
            "kind": "OPERATIONS",
            "starts_at": "2026-09-10T11:00:00Z",
            "ends_at": "2026-09-10T13:00:00Z",
        },
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
    shifts = list_deployment_shifts(deployment_id)
    assert len(shifts) == 2


def test_fatigue_cap_admits_exactly_forty_hours(api, operations_lead_headers):
    """PRD §3.5: "The fatigue cap rejects with `ERR_FATIGUE_LIMIT_EXCEEDED` (HTTP 422) when the new shift's hours, added to the volunteer's current `fatigue_hours`, would exceed 40 (`MAX_FATIGUE_HOURS`); landing exactly on 40 is admissible."

    Design: Corner/cross_cutting_layers/fatigue_exact_cap_admitted
    """
    bundle = setup_fatigued_volunteer(
        shift_specs=FATIGUE_36_SHIFTS, ops_clock="2026-09-12T21:00:00Z",
    )
    assert bundle["volunteer"]["fatigue_hours"] == 36
    # 36 + 4 == 40 exactly -> admitted.
    resp = api.create_duty_shift(
        bundle["operation"]["id"],
        {
            "deployment_id": bundle["deployment"]["id"],
            "kind": "LOGISTICS",
            "starts_at": "2026-09-13T08:00:00Z",
            "ends_at": "2026-09-13T12:00:00Z",
        },
        operations_lead_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    volunteer = get_volunteer(bundle["volunteer"]["id"])
    assert volunteer["fatigue_hours"] == 36


def test_fatigue_resets_after_full_rest_window(api):
    """PRD §2.9: "a volunteer who has had no on-duty shift for at least 24 hours — `REST_RESET_HOURS` — has `fatigue_hours` reset to 0 at the next ops run, provided no shift is currently in progress"
    PRD §3.5: "Only after all of the epoch's completions are booked does the reset rule run, per volunteer: if at least 24 hours have passed since the end of the volunteer's most recently completed shift, and no `SCHEDULED` shift currently contains `current_utc`, the volunteer's `fatigue_hours` returns to 0."

    Design: Corner/calculations/fatigue_reset_after_rest_window
    """
    bundle = setup_fatigued_volunteer(
        cert_kinds=("CHAINSAW", "STRUCTURAL"),
        volunteer_overrides={
            "full_name": "Bo Karr", "email": "bo@x.org", "skills": ["CHAINSAW", "STRUCTURAL"],
        },
    )
    volunteer = bundle["volunteer"]
    assert volunteer["fatigue_hours"] == 10
    assert volunteer["readiness_score"] == 45
    # 49 hours after the last shift end (2026-09-10T18:00:00Z), nothing in window.
    set_clock("2026-09-12T19:00:00Z")
    run_ops_epoch()
    volunteer = get_volunteer(volunteer["id"])
    assert volunteer["fatigue_hours"] == 0
    assert volunteer["readiness_score"] == 65


def test_overlap_error_precedes_fatigue_error(api, operations_lead_headers):
    """PRD §2.6: "When a single request violates several rules, exactly one error is returned, chosen by a fixed validation priority — lower priority numbers win." with business rules ordered "then temporal rules (availability containment, rest buffer, shift overlap), then capacity and coverage constraints (fatigue cap, capability coverage, hazard alignment, offer ceiling, duplicate enrollment)" — shift overlap ahead of the fatigue cap.

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fatigue_on_shift_conflict
    """
    bundle = setup_fatigued_volunteer(
        shift_specs=FATIGUE_36_SHIFTS, ops_clock="2026-09-12T21:00:00Z",
    )
    assert bundle["volunteer"]["fatigue_hours"] == 36
    # Overlaps the COMPLETED 2026-09-10 08:00-20:00 shift AND 36 + 8 = 44 > 40.
    resp = api.create_duty_shift(
        bundle["operation"]["id"],
        {
            "deployment_id": bundle["deployment"]["id"],
            "kind": "OPERATIONS",
            "starts_at": "2026-09-10T10:00:00Z",
            "ends_at": "2026-09-10T18:00:00Z",
        },
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_rejected_shift_leaves_fatigue_and_shift_count_unchanged(api, operations_lead_headers):
    """PRD §3.5: "Every completed duty shift adds its duration in hours to the volunteer's `fatigue_hours`" (accrual happens at completion, not at scheduling, so a rejected scheduling changes nothing).

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fatigue_on_shift_conflict
    """
    bundle = setup_fatigued_volunteer(
        shift_specs=FATIGUE_36_SHIFTS, ops_clock="2026-09-12T21:00:00Z",
    )
    resp = api.create_duty_shift(
        bundle["operation"]["id"],
        {
            "deployment_id": bundle["deployment"]["id"],
            "kind": "OPERATIONS",
            "starts_at": "2026-09-10T10:00:00Z",
            "ends_at": "2026-09-10T18:00:00Z",
        },
        operations_lead_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
    volunteer = get_volunteer(bundle["volunteer"]["id"])
    assert volunteer["fatigue_hours"] == 36
    shifts = list_deployment_shifts(bundle["deployment"]["id"])
    assert len(shifts) == 3
