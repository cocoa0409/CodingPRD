"""ASAM assessment filing and the two readings of the placement rule."""

from test_helpers import (
    C,
    ApiErrorId,
    complete_assessment,
    is_iso8601_timestamp,
    make_clinician_headers,
    open_episode,
    read_assessment,
    read_episode,
    setup_site,
    start_assessment,
    validate_error,
)


def test_dimension_scores_omitted_is_refused_as_a_missing_required_field(api, intake_nurse_headers):
    """PRD §3.1: "Assessment begins when an `AdmissionsIntakeNurse` or `Clinician` files an
    assessment against an episode that is still `AWAITING_ASSESSMENT`, supplying the
    `assessor_clinician_id` and a `dimension_scores` payload."
    PRD §2.7: "A request that omits a required field, carries a field the operation does not
    declare, or supplies a value of the wrong type is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/assessment_create_missing_dimension_scores_returns_invalid_request
    """
    site = setup_site()
    episode = open_episode(site)

    response = api.create_assessment(
        site.id,
        episode["id"],
        {"assessor_clinician_id": site.clinician["id"]},
        intake_nurse_headers,
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_DIMENSION_SCORES, (
        "an omitted dimension_scores is a required-field failure, not a malformed-object failure"
    )


def test_dimension_sum_reading_places_a_low_total_at_asam_2_1(api):
    """PRD §3.1: "Under the `DIMENSION_SUM` reading, the recommended level is read straight
    off `total_score` by descending bands."
    PRD §3.1: "A total of 18 or more, below 28, places them at `ASAM_2_1`."
    PRD §3.1: "the episode's `assigned_level` takes the recommended level, and the episode
    moves from `UNDER_ASSESSMENT` to `AWAITING_AUTHORIZATION`."

    Design: Difficulty/dual_variant_calc/asam_placement_total_vs_single_dimension_floor
    """
    site = setup_site()
    episode = open_episode(site)

    scores = {
        "withdrawal_risk": 0,
        "biomedical_conditions": 0,
        "emotional_behavioral": 4,
        "readiness_to_change": 1,
        "relapse_potential": 3,
        "recovery_environment": 0,
    }
    assessment = start_assessment(site, episode["id"], scores=scores)
    complete_assessment(site, assessment["id"])

    stored = read_assessment(site.id, episode["id"], assessment["id"])
    assert stored["total_score"] == 18, (
        "weights 3*0 + 2*0 + 2*4 + 1*1 + 3*3 + 1*0 give 18, exactly the 2_1 threshold"
    )
    assert stored["placement_basis"] == "DIMENSION_SUM"
    assert stored["recommended_level"] == "ASAM_2_1"

    episode_after = read_episode(episode["id"])
    assert episode_after["assigned_level"] == "ASAM_2_1"
    assert episode_after["clinical_status"] == "AWAITING_AUTHORIZATION"


def test_highest_dimension_floor_reading_raises_the_same_scores_one_level(api):
    """PRD §3.1: "Under the `HIGHEST_DIMENSION_FLOOR` reading, a floor is derived from the
    single worst dimension and the final placement is the higher-ranked of that floor and the
    level the weighted total would have earned."
    PRD §3.1: "The floor is `ASAM_3_1` when `relapse_potential` equals 3, or when
    `biomedical_conditions` equals 4."

    Design: Difficulty/dual_variant_calc/asam_placement_total_vs_single_dimension_floor
    """
    site = setup_site()
    episode = open_episode(site)

    scores = {
        "withdrawal_risk": 0,
        "biomedical_conditions": 0,
        "emotional_behavioral": 4,
        "readiness_to_change": 0,
        "relapse_potential": 3,
        "recovery_environment": 0,
    }
    assessment = start_assessment(
        site, episode["id"], scores=scores, placement_basis="HIGHEST_DIMENSION_FLOOR"
    )
    completed = complete_assessment(site, assessment["id"])

    assert completed["placement_basis"] == "HIGHEST_DIMENSION_FLOOR"
    assert completed["recommended_level"] == "ASAM_3_1", (
        f"relapse_potential 3 floors the placement at ASAM_3_1, got {completed['recommended_level']}"
    )
    assert read_episode(episode["id"])["assigned_level"] == "ASAM_3_1"


def test_recovery_environment_weight_is_one_so_it_cannot_reach_the_2_1_band(api):
    """PRD §3.1: "`recovery_environment` a weight of 1."
    PRD §3.1: "Any total below 18 places them at `ASAM_1_0`."

    Design: Corner/calculations/asam_placement_ignores_low_weight_dimensions_at_the_2_1_threshold
    """
    site = setup_site()
    episode = open_episode(site)

    scores = {
        "withdrawal_risk": 0,
        "biomedical_conditions": 0,
        "emotional_behavioral": 0,
        "readiness_to_change": 0,
        "relapse_potential": 0,
        "recovery_environment": 4,
    }
    assessment = start_assessment(site, episode["id"], scores=scores)
    completed = complete_assessment(site, assessment["id"])

    assert completed["total_score"] == 4
    assert completed["recommended_level"] == "ASAM_1_0"


def test_completing_the_assessment_writes_its_fields_and_the_episode_placement(api):
    """
    PRD §3.1: "On success, `total_score` and `recommended_level` are written, the assessment's
    status becomes `COMPLETED` and `assessed_at` is stamped, the episode's `assigned_level`
    takes the recommended level, and the episode moves from `UNDER_ASSESSMENT` to
    `AWAITING_AUTHORIZATION`." PRD §3.1: "The weighted total is shared by both readings and is
    computed from the six dimensions with fixed integer weights: `withdrawal_risk` carries a
    weight of 3"

    Design: Corner/state_machines/episode_assess_then_complete_applies_assigned_level_and_thresholds
    """
    site = setup_site()
    episode = open_episode(site)
    assessment = start_assessment(site, episode["id"], scores=C.SCORES_ASAM_3_5)

    completed = complete_assessment(site, assessment["id"])

    assert completed["total_score"] == 40
    assert completed["recommended_level"] == "ASAM_3_5"
    assert completed["status"] == "COMPLETED"
    assert is_iso8601_timestamp(completed["assessed_at"])

    refreshed = read_episode(episode["id"])
    assert refreshed["assigned_level"] == "ASAM_3_5"
    assert refreshed["clinical_status"] == "AWAITING_AUTHORIZATION"


def test_starting_a_second_assessment_supersedes_the_sibling_in_flight_row(api):
    """PRD §3.1: "Starting a second assessment while one is already in flight supersedes the
    earlier row: the pre-existing `IN_PROGRESS` assessment's status becomes `SUPERSEDED` and
    the episode's own dimension does not move."

    Design: Corner/state_machines/episode_assess_then_complete_applies_assigned_level_and_thresholds
    """
    site = setup_site()
    episode = open_episode(site)
    first = start_assessment(site, episode["id"], scores=C.SCORES_ASAM_3_5)

    start_assessment(site, episode["id"], scores=C.SCORES_ASAM_3_5)

    superseded = read_assessment(site.id, episode["id"], first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert read_episode(episode["id"])["clinical_status"] == "UNDER_ASSESSMENT"


def test_a_clinician_with_no_usable_credential_cannot_complete_an_assessment(api):
    """PRD §3.1: "The assessor named by `assessor_clinician_id` must hold a `credential_tier`
    at or above the facility's `state_min_credential_tier`, and must hold a
    `ClinicianFacilityCredential` for that facility whose `is_usable` flag is true."
    PRD §3.1: "A failure of either is `ERR_ASSESSOR_CREDENTIAL_INSUFFICIENT`."

    Design: Corner/entities/body_foreign_keys_are_validated_left_to_right_against_the_facility
    """
    site = setup_site()
    outsider = setup_site().clinician  # credentialed at a different site, not this one
    episode = open_episode(site)
    assessment = start_assessment(site, episode["id"], scores=C.SCORES_ASAM_3_5)

    response = api.complete_assessment(
        site.id, assessment["id"], {}, make_clinician_headers(outsider["id"])
    )

    validate_error(response, ApiErrorId.ERR_ASSESSOR_CREDENTIAL_INSUFFICIENT)


def test_the_placement_cycle_can_be_walked_a_second_time(api):
    """PRD §3.1: "The floor reading is reachable in normal operation. An assessment is
    created under the default reading, completed — which places the episode — and then
    cancelled, returning the episode to `AWAITING_ASSESSMENT` with the original
    `dimension_scores` intact; it is then re-created with the same scores and a
    `placement_basis` of `HIGHEST_DIMENSION_FLOOR`."
    PRD §3.1: "Both assessment rows are then readable side by side, one recording each reading."

    Design: Difficulty/non_linear_state_machine/episode_clinical_status_reassessment_cycle
    """
    from test_helpers import cancel_assessment, CLINICAL_DIRECTOR_HEADERS

    site = setup_site()
    episode = open_episode(site)
    scores = {
        "withdrawal_risk": 0,
        "biomedical_conditions": 0,
        "emotional_behavioral": 4,
        "readiness_to_change": 0,
        "relapse_potential": 3,
        "recovery_environment": 0,
    }

    first = start_assessment(site, episode["id"], scores=scores)
    complete_assessment(site, first["id"])
    cancel_assessment(site, first["id"], headers=CLINICAL_DIRECTOR_HEADERS)

    assert read_assessment(site.id, episode["id"], first["id"])["status"] == "CANCELLED"
    assert read_episode(episode["id"])["clinical_status"] == "AWAITING_ASSESSMENT"

    second = start_assessment(
        site, episode["id"], scores=scores, placement_basis="HIGHEST_DIMENSION_FLOOR"
    )
    completed = complete_assessment(site, second["id"])
    assert completed["recommended_level"] == "ASAM_3_1", (
        "the second pass re-places the episode at AWAITING_AUTHORIZATION under the floor reading"
    )
    assert read_episode(episode["id"])["clinical_status"] == "AWAITING_AUTHORIZATION"
