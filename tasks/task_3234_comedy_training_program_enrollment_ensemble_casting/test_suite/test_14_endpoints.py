"""Corner queue: endpoints — clock action and cohort admission capacity."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_level, create_student, create_term_draft, create_instructor,
    reset_clock, grant_placement, create_cohort_program_payload,
    create_evaluated_audition,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]
CD = TEST_USERS["casting_director_headers"]


def test_clock_set_endpoint_advances_logical_time():
    """PRD §2.4: "The server boots with the logical clock pinned to
    `2026-09-01T00:00:00Z`. The only way to advance it is an admin-only test-driving
    capability that sets the clock to a supplied `current_utc` instant"

    Design: Corner/endpoints/clock_set_endpoint_advances_logical_time
    """
    reset_clock()
    data = validate_success(api_client.set_clock("2027-06-15T12:00:00Z", PD))
    assert data["current_utc"] == "2027-06-15T12:00:00Z"


def test_cohort_admit_over_capacity_rejected():
    """PRD §3.6: "Admission happens one student at a time: the ProgramDirector
    admits by naming an `audition_id`, and the admission validates that the
    student's `completed_level_codes` cover the cohort's `min_track_level_code` — a
    student short of the floor is refused with `ERR_MIN_TRACK_LEVEL_NOT_MET`
    (HTTP 422) — and that the cohort has room, an admission beyond `cohort_size`
    failing with `ERR_COHORT_OVER_CAPACITY` (HTTP 422). A successful admission moves
    the audition to `SELECTED` and raises `admitted_count` by 1."

    Design: Corner/endpoints/cohort_admit_over_capacity_rejected
    """
    reset_clock()
    create_level(code="L1", allows_placement_bypass=False)
    lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                        allows_placement_bypass=True)
    lvl3 = create_level(code="L3R", sequence_index=2, requires_level_code="L2",
                        allows_placement_bypass=True)
    term = create_term_draft()
    s1 = create_student()
    s2 = create_student()
    cohort = validate_success(api_client.create_cohort_program(
        create_cohort_program_payload(term["id"], cohort_size=1,
                                      min_track_level_code="L3R"), PD), 201)
    validate_success(api_client.begin_cohort_auditions(cohort["id"], PD))
    grant_placement(s1["id"], lvl3["id"])
    grant_placement(s2["id"], lvl3["id"])
    aud1 = create_evaluated_audition(s1["id"], "COHORT",
                                     cohort_program_id=cohort["id"],
                                     rubric_scores={"scene_work": 9, "characters": 9,
                                                    "musicality": 9, "game": 9})
    aud2 = create_evaluated_audition(s2["id"], "COHORT",
                                     cohort_program_id=cohort["id"],
                                     rubric_scores={"scene_work": 9, "characters": 9,
                                                    "musicality": 9, "game": 9})
    validate_success(api_client.admit_to_cohort(cohort["id"], aud1["id"], PD))
    resp = api_client.admit_to_cohort(cohort["id"], aud2["id"], PD)
    validate_error(resp, ApiErrorId.ERR_COHORT_OVER_CAPACITY, 422)
    cohort_now = validate_success(api_client.get_cohort_program(cohort["id"], PD))
    assert cohort_now["admitted_count"] == 1
