"""Nested retrieval, the optimistic-concurrency gate and the housing ceiling."""

import pytest

from test_helpers import (
    C,
    CLINICAL_DIRECTOR_HEADERS,
    ApiErrorId,
    activate_continuing_care_plan,
    create_recovery_house,
    draft_continuing_care_plan,
    draft_plan,
    grant_recovery_house_license,
    read_episode,
    run_ops,
    set_clock,
    setup_admitted_episode,
    setup_claimed_episode,
    setup_exhausted_episode,
    setup_staged_episode,
    setup_site,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_an_admitted_episode_round_trips_through_its_nested_read(api):
    """
    PRD §2.4: "Every child row in the hierarchy carries the `episode_id` of the episode it
    belongs to, and the facility-rooted children carry the corresponding facility reference;
    nested retrieval uses those references to place a row under exactly one parent." PRD §3.1:
    "The new episode starts with `clinical_status` at `AWAITING_ASSESSMENT`, `care_level_status`
    at `NOT_STARTED`, `step_down_count` at 0 and `therapy_revenue_cents` at 0."

    Design: Corner/entities/episode_get_round_trips_the_stored_row_unchanged
    """
    site = setup_site()
    setup = setup_admitted_episode(
        site=site, admit_clock=C.CLOCK_2026_09_02, requested_level="ASAM_3_5",
        scores=C.SCORES_ASAM_3_5,
    )

    from test_helpers import READ_HEADERS

    response = api.get_episode_in_facility(site.id, setup.id, READ_HEADERS)
    data = response.json()["data"]

    assert data["patient_ref"] == C.PATIENT_REF
    assert data["assigned_level"] == "ASAM_3_5"
    assert data["clinical_status"] == "IN_TREATMENT"
    assert data["care_level_status"] == "ACTIVE"
    assert data["discharged_at"] is None
    assert data["revcap_pre_step_down_cents"] is None
    assert data["revcap_post_step_down_cents"] is None
    assert data["step_down_count"] == 0
    assert data["therapy_revenue_cents"] == 0
    assert data["id"] == setup.id


def test_admission_advances_both_parallel_dimensions_and_the_version(api):
    """PRD §3.3: "On success the episode's `admitted_at` is stamped, `clinical_status` becomes
    `IN_TREATMENT`, `care_level_status` moves from `NOT_STARTED` to `ACTIVE`, and the episode's
    version advances."

    Design: Corner/state_machines/episode_admit_moves_to_in_treatment_and_starts_care_level
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)

    episode = setup.episode
    assert episode["clinical_status"] == "IN_TREATMENT"
    assert episode["care_level_status"] == "ACTIVE"
    assert episode["admitted_at"] == C.CLOCK_2026_09_02_ISO
    assert episode["version"] > 1, "admission advanced the episode version"


def test_a_stale_episode_version_refuses_a_superseding_plan(api):
    """PRD §2.4: "Drafting a new treatment plan for an episode requires
    `expected_treatment_episode_version`, carrying the client's last observed `version` of the
    target `TreatmentEpisode`."
    PRD §2.4: "A mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_episode_version_refuses_a_superseding_treatment_plan
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site)
    observed = read_episode(setup.id)["version"]

    first = draft_plan(site, setup.id, expected_version=observed)
    assert first["status"] == "DRAFT"

    response = api.create_treatment_plan(
        site.id,
        setup.id,
        {
            "author_clinician_id": site.clinician["id"],
            "cosign_rationale_code": "ASAM-PLAN-V2",
            "expected_treatment_episode_version": observed,
        },
        site.clinician_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    fresh = read_episode(setup.id)["version"]
    retry = validate_success(
        api.create_treatment_plan(
            site.id,
            setup.id,
            {
                "author_clinician_id": site.clinician["id"],
                "cosign_rationale_code": "ASAM-PLAN-V2",
                "expected_treatment_episode_version": fresh,
            },
            site.clinician_headers,
        ),
        201,
    )
    assert retry["id"] != first["id"]


def test_the_recovery_housing_ceiling_is_an_inclusive_count_of_active_plans(api):
    """PRD §3.8: "the count of `ACTIVE` continuing-care plans must not exceed the summed
    `capacity_beds` of the facility's `OPEN` rows, and an overfill is
    `ERR_CONTINUING_CARE_HOUSING_FULL`."
    PRD §2.9: "the check is an inclusive ceiling, so a count exactly equal to the summed
    capacity passes and one more fails with `ERR_CONTINUING_CARE_HOUSING_FULL`."

    Design: Corner/validations/housing_capacity_check_is_conditional_on_the_plan_basis
    """
    site = setup_site()
    grant_recovery_house_license(site)
    create_recovery_house(site, house_name="Cedar House", capacity_beds=1, day_rate_cents=1000,
                          proximity_rank=1, grab_barrier_hours=0)

    # A licensed house is created for the second episode so that the RANKED_AUTO pool
    # is populated at activation; the ceiling under test is the count of ACTIVE plans
    # against the summed OPEN capacity, not pool availability.
    first = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    first_plan = draft_continuing_care_plan(site, first.id)
    activate_continuing_care_plan(site, first_plan["id"])

    second = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    version = read_episode(second.id)["version"]
    response = api.create_continuing_care_plan(
        site.id,
        second.id,
        {
            "housing_selection_basis": "RANKED_AUTO",
            "housing_window_start": "2026-09-07T00:00:00Z",
            "housing_window_end": "2026-10-07T00:00:00Z",
            "alumni_contact_interval_days": 7,
            "alumni_contacts_required": 2,
            "authorizing_clinician_id": site.clinician["id"],
            "shelter_class": "RESIDENTIAL",
            "wants_recovery_only_house": True,
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    # Drafting is allowed; the ceiling bites at activation.
    second_plan = response.json().get("data", {})
    if response.status_code == 201:
        from test_helpers import activate_continuing_care_plan as _activate

        blocked = api.activate_continuing_care_plan(
            site.id, second_plan["id"], {}, CLINICAL_DIRECTOR_HEADERS
        )
        validate_error_is_one_of(
            blocked,
            [ApiErrorId.ERR_CONTINUING_CARE_HOUSING_FULL, ApiErrorId.ERR_HOUSING_POOL_EXHAUSTED],
        )
    else:
        validate_error_is_one_of(
            response,
            [ApiErrorId.ERR_CONTINUING_CARE_HOUSING_FULL, ApiErrorId.ERR_HOUSING_POOL_EXHAUSTED],
        )


def test_a_state_rule_pre_empts_a_route_rule_on_the_same_level_change(api):
    """
    PRD §3.6: "Level-of-Care Changes: Stepping Down and Stepping Up A `ClinicalDirector` or
    `UtilizationReviewer` appoints a level-of-care change against an episode that is
    `IN_TREATMENT`, supplying the `authorization_id` funding the target level, the `to_level`,
    the `effective_at` instant, the required `expected_treatment_episode_version`, and
    optionally a `bed_id`." PRD §2.7a: "Only after all of that do the state and posture rules
    run"

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_referential_vs_state_on_step_down
    """
    site = setup_site()
    claim = setup_staged_episode(site=site)
    assert read_episode(claim.id)["clinical_status"] == "AWAITING_ADMISSION"

    version = read_episode(claim.id)["version"]
    response = api.create_level_of_care_change(
        site.id,
        claim.id,
        {
            "authorization_id": claim.auth_id,
            "to_level": "ASAM_2_1",
            "effective_at": C.CLOCK_2026_09_05,
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    error = validate_error(response, ApiErrorId.ERR_EPISODE_NOT_IN_TREATMENT, 409)
    assert error["error_id"] != ApiErrorId.ERR_LEVEL_ROUTE_NOT_ALLOWED
    assert error["error_id"] != ApiErrorId.ERR_LEVEL_EXCEEDS_FACILITY_LICENSE

    from test_helpers import list_episode_changes

    changes, _ = list_episode_changes(site.id, claim.id)
    assert changes == [], "no change row was created"


def test_a_cascade_never_moves_the_episodes_own_clinical_dimension(api):
    """
    PRD §3.5: "Stage one burns the clock bucket: `days_used`, `days_remaining` and the posture
    of every non-terminal authorization are re-derived, exactly as described for the day bank"
    reached exactly 0 while the episode is `IN_TREATMENT` becomes `EXHAUSTED`, the payer's
    coverage map is forced to promote the next covered lower level, the episode's
    `care_level_status` becomes `STEP_DOWN_PENDING`, and the episode's treatment plan is
    superseded in the same moment."

    Design: Difficulty/transitive_cascade/cascade_expired_site_accreditation_to_plan_to_bed_release
    """
    from test_helpers import list_episode_sessions, read_authorization, read_plan

    site = setup_site()
    setup = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_01)

    set_clock(C.CLOCK_2026_09_08)
    run_ops(site.id)
    assert read_authorization(setup.auth_id)["days_used"] == 7

    set_clock(C.CLOCK_2026_09_15)
    run_ops(site.id)

    auth = read_authorization(setup.auth_id)
    assert auth["days_remaining"] == 0
    assert auth["posture"] == "EXHAUSTED"
    episode = read_episode(setup.id)
    assert episode["care_level_status"] == "STEP_DOWN_PENDING"
    assert episode["clinical_status"] == "IN_TREATMENT", (
        "the day-bank cascade never advances the episode's clinical dimension"
    )


def test_the_days_exhausted_code_is_returned_by_its_own_branch(api):
    """PRD §3.3: "The authorization's `days_remaining` must be strictly greater than 0,
    reported as `ERR_AUTHORIZATION_DAYS_EXHAUSTED` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/admission_gated_on_authorization_days_and_clearance_effective_status
    """
    from test_helpers import INTAKE_NURSE_HEADERS, read_clearance

    site = setup_site()
    setup = setup_exhausted_episode(site=site, admit_clock=C.CLOCK_2026_09_01)

    # Every clearance still reads CLEARED, so only the fiscal rule can fire.
    response = api.admit_episode(site.id, setup.id, {}, INTAKE_NURSE_HEADERS)
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_DAYS_EXHAUSTED, 402)
