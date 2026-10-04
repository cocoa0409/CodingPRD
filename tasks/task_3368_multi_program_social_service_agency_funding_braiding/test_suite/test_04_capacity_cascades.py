"""Capacity cascades, cross-entity gating and the confidentiality variants."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, set_clock,
    create_client, create_funder, create_program, create_grant, open_assessment,
    open_screen, verify_screen, submit_assessment, route_assessment, determine_screen,
    find_enrollment, list_enrollments_for, setup_landscape, setup_capacity_pair,
    refresh_screen, ApiErrorId, INTAKE, PROGRAM, COMPLIANCE,
)


def test_zero_capacity_program_is_exhausted_before_any_enrollment():
    """PRD §3.4: "a program configured with `capacity_slots` of 0 is exhausted
    before any enrollment exists."
    PRD §3.4: "An attempt to consume a slot when `enrolled_slots` is already at
    or above `capacity_slots` is refused with `ERR_PROGRAM_CAPACITY_EXCEEDED`
    (HTTP 409), and that refusal guards both direct enrollment creation and
    eligible determinations."

    Design: Difficulty/boundary_precision_check/zero_capacity_program_is_exhausted_before_any_enrollment
    """
    set_clock("2026-09-02T00:00:00Z")
    landscape = setup_landscape(program={"name": "ZERO_PGM", "capacity_slots": 0},
                                grants=[{"grant_code": "G0"}])
    client = create_client()
    assessment = open_assessment(client["id"])
    screen = open_screen(assessment["id"], landscape["program"]["id"],
                         landscape["grant"]["id"])
    verify_screen(screen["id"])
    submit_assessment(assessment["id"])
    route_assessment(assessment["id"])

    resp = api_client.determine_eligibility_screen(screen["id"], {"determination": "ELIGIBLE"},
                                                   COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CAPACITY_EXCEEDED)

    after = refresh_screen(screen["id"])
    assert after["determination"] == "PENDING", (
        "the refusal is a validation rejection, not an INELIGIBLE determination"
    )
    assert after["denial_reason_code"] is None
    assert list_enrollments_for(client["id"]) == [], "no enrollment exists for the client"


def test_screen_determination_gated_by_parent_assessment_routing():
    """PRD §3.4: "A screen determined while the parent assessment is not
    `ROUTED` is refused with `ERR_INTAKE_NOT_ROUTED`; a screen opened or
    determined in violation of §2.7 is refused with
    `ERR_CONFIDENTIALITY_SCOPE_DENIED`; and one opened against an unattested
    program under a federal or state funder is refused with
    `ERR_NONDISCRIMINATION_VIOLATION`."
    PRD §2.10: "`ERR_INTAKE_NOT_ROUTED` (HTTP 409) fires when a determination is
    attempted on an eligibility screen whose parent assessment is not in
    `ROUTED` status."

    Design: Difficulty/cross_entity_state_dependency/screen_determination_gated_by_parent_assessment_routing
    """
    set_clock("2026-09-02T00:00:00Z")
    landscape = setup_landscape()
    client = create_client()
    assessment = open_assessment(client["id"])
    screen = open_screen(assessment["id"], landscape["program"]["id"],
                         landscape["grant"]["id"])
    verify_screen(screen["id"])
    submit_assessment(assessment["id"])

    resp = api_client.determine_eligibility_screen(screen["id"], {"determination": "ELIGIBLE"},
                                                   COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_ROUTED)

    parent = get_success_data(api_client.get_intake_assessment(assessment["id"], INTAKE))
    assert parent["status"] == "SUBMITTED", "the parent never reached ROUTED"
    after = refresh_screen(screen["id"])
    assert after["determination"] == "PENDING"
    assert after["verification_state"] == "VERIFIED"
    assert list_enrollments_for(client["id"]) == [], "the refused call creates no enrollment"


def test_eligibility_screen_parallel_determination_and_verification_dimensions():
    """PRD §3.4: "A screen carries two state dimensions that never touch each
    other."
    PRD §3.4: "The verification hop is an unusual transition because it does not
    change the determination dimension at all: a screen in `PENDING`
    determination stays in `PENDING` determination."
    PRD §3.4: "it sets `determination` to `ELIGIBLE` and creates an `Enrollment`
    in `PENDING` status carrying the assessment's client, the screen's
    `program_id` and the screen's `grant_id`. It then increments that program's
    `enrolled_slots` by one".

    Design: Difficulty/non_linear_state_machine/eligibility_screen_parallel_determination_and_verification_dimensions
    """
    set_clock("2026-09-02T00:00:00Z")
    landscape = setup_landscape()
    client = create_client()
    assessment = open_assessment(client["id"])
    screen = open_screen(assessment["id"], landscape["program"]["id"],
                         landscape["grant"]["id"])
    submit_assessment(assessment["id"])

    api_client.determine_eligibility_screen(screen["id"], {"determination": "ELIGIBLE"},
                                            COMPLIANCE)
    after_verify = refresh_screen(screen["id"])
    assert after_verify["verification_state"] == "VERIFIED"
    assert after_verify["determination"] == "PENDING", (
        "the verification hop does not move the determination dimension"
    )

    route_assessment(assessment["id"])
    api_client.determine_eligibility_screen(screen["id"], {"determination": "ELIGIBLE"},
                                            COMPLIANCE)
    after_determine = refresh_screen(screen["id"])
    assert after_determine["determination"] == "ELIGIBLE"
    assert after_determine["verification_state"] == "VERIFIED", (
        "the determination hop does not move the verification dimension"
    )

    enrollments = list_enrollments_for(client["id"])
    assert len(enrollments) == 1, "the eligible determination creates exactly one enrollment"
    assert enrollments[0]["status"] == "PENDING"
    assert enrollments[0]["program_id"] == landscape["program"]["id"]
    assert enrollments[0]["grant_id"] == landscape["grant"]["id"]

    listed = get_success_data(api_client.list_eligibility_screens(
        COMPLIANCE, {"program_id": landscape["program"]["id"]}))
    assert len(listed) == 1 and listed[0]["id"] == screen["id"]


def test_capacity_saturation_cascade_sweeps_sibling_pending_screens():
    """PRD §3.4: "It then increments that program's `enrolled_slots` by one, and
    — when that increment brings `enrolled_slots` up to `capacity_slots` — runs
    the capacity cascade, setting every screen for that program still sitting at
    `PENDING` determination to `INELIGIBLE` with a `denial_reason_code` of
    `PROGRAM_AT_CAPACITY`."
    PRD §3.4: "`available_slots` is `capacity_slots` minus `enrolled_slots`, and
    a program is exhausted when `available_slots` is at or below zero".

    Design: Difficulty/transitive_cascade/capacity_saturation_cascade_sweeps_sibling_pending_screens
    """
    set_clock("2026-09-02T00:00:00Z")
    landscape = setup_landscape(program={"capacity_slots": 1})
    client_one = create_client(full_name="Client One")
    walked = {"assessment": open_assessment(client_one["id"])}
    screen_one = open_screen(walked["assessment"]["id"], landscape["program"]["id"],
                             landscape["grant"]["id"])
    verify_screen(screen_one["id"])
    submit_assessment(walked["assessment"]["id"])
    route_assessment(walked["assessment"]["id"])

    client_two = create_client(full_name="Client Two", household_size=1)
    assessment_two = open_assessment(client_two["id"])
    screen_two = open_screen(assessment_two["id"], landscape["program"]["id"],
                             landscape["grant"]["id"], verified_income_cents=130000,
                             household_size_at_screen=1)
    submit_assessment(assessment_two["id"])

    determine_screen(screen_one["id"], "ELIGIBLE")

    swept = refresh_screen(screen_two["id"])
    assert swept["determination"] == "INELIGIBLE", "hop 3 sweeps the sibling pending screen"
    assert swept["denial_reason_code"] == "PROGRAM_AT_CAPACITY"

    enrollments = list_enrollments_for(client_one["id"])
    assert len(enrollments) == 1
    assert enrollments[0]["status"] == "PENDING"
    assert list_enrollments_for(client_two["id"]) == [], (
        "the swept screen never reached ELIGIBLE, so it created no enrollment"
    )


def test_confidentiality_safety_check_outranks_capacity_constraint_check():
    """PRD §2.10: "A stale-version refusal and a safety refusal each outrank a
    capacity refusal and each outrank a money refusal on the same request".
    PRD §2.7: "A `PROTECTED` client is permitted only when the target domain
    appears in the client's `consent_scope` and the logical clock has not passed
    `consent_expires_on`."

    Design: Difficulty/priority_pair_validation_conflict/confidentiality_safety_check_outranks_capacity_constraint_check
    """
    ctx = setup_capacity_pair(
        capacity_slots=1,
        first_activate=False,
        second_verify=True,
        second_route=True,
        second_submit=True,
        second_client_overrides={
            "confidentiality_tier": "PROTECTED",
            "consent_scope": ["HOUSING"],
            "consent_expires_on": "2026-10-31T00:00:00Z",
        },
        clock="2026-10-02T00:00:00Z",
        clock_after="2026-11-05T00:00:00Z",
    )

    resp = api_client.determine_eligibility_screen(
        ctx["screen_two"]["id"], {"determination": "ELIGIBLE"}, COMPLIANCE
    )
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_SCOPE_DENIED)

    after = refresh_screen(ctx["screen_two"]["id"])
    assert after["determination"] == "PENDING", "the refusal records no determination"
    assert after["verification_state"] == "VERIFIED"
    assert list_enrollments_for(ctx["client_two"]["id"]) == [], (
        "no enrollment is created for the refused client"
    )


def test_confidentiality_tier_first_write_refusal_vs_consent_first_read_projection():
    """PRD §2.7: "The `SEALED` branch is absolute in this variant: consent never
    overrides it, so a sealed client whose consent list covers the target domain
    is still refused."
    PRD §2.7: "A refusal carries `ERR_CONFIDENTIALITY_SCOPE_DENIED` with HTTP
    403, and it guards four operations: ... creating an enrollment directly".

    Design: Difficulty/dual_variant_calc/confidentiality_tier_first_write_refusal_vs_consent_first_read_projection
    """
    set_clock("2026-10-02T00:00:00Z")
    funder = create_funder(name="FED", funder_type="FEDERAL",
                           allow_faith_based_activity=False,
                           requires_time_and_effort_documentation=True,
                           max_admin_rate_pct=0.25, fiscal_year_start_month=10)
    program = create_program(name="HOUSING_PGM", capacity_slots=5)
    grant = create_grant(funder["id"], program["id"], grant_code="G1",
                         period_start="2026-01-01T00:00:00Z",
                         period_end="2027-09-30T00:00:00Z")
    client = create_client(full_name="Sealed Client", household_size=3,
                           immigration_status="LPR", confidentiality_tier="SEALED",
                           consent_scope=["HOUSING"],
                           consent_expires_on="2026-12-31T00:00:00Z")

    resp = api_client.create_enrollment(
        {"client_id": client["id"], "program_id": program["id"], "grant_id": grant["id"]},
        PROGRAM,
    )
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_SCOPE_DENIED)

    assert list_enrollments_for(client["id"]) == []
    assert get_success_data(api_client.list_eligibility_screens(
        COMPLIANCE, {"program_id": program["id"]})) == []
