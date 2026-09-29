"""Breadth tests for the read side of the corner design index.

Covers single-resource retrieval, list pagination, the path- and body-borne
not-found codes, the assistance-enrollment reverse channel, and the API's
immediate-consistency commitment: every derived field is readable in the
response of the very call that caused it.

Design sections covered: Corner/entities and Corner/consistency_model.
"""
import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.test_users import COUNSELOR_ALPHA_USER_ID

UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000ff"
SECOND_UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000fe"


# ---------------------------------------------------------------------------
# Single-patient retrieval
# ---------------------------------------------------------------------------
def test_patient_retrieval_returns_the_stored_entity(api, registry_admin_headers):
    """The read hands back exactly what the create call persisted.

    PRD §3.3: "A patient's own record exposes both derived postures alongside
    the latest activity figures, and it is readable by any of the six staff
    roles as well as by the patient themselves under the ownership rule of
    §2.1."

    Design: Corner/entities/patient_retrieval_returns_the_stored_entity
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    created = validate_success(
        api.create_patient(
            factories.create_patient_payload(
                mrn="RH0001", diagnosis_code="RA_SEROPOSITIVE"
            ),
            registry_admin_headers,
        ),
        201,
    )

    read = validate_success(api.get_patient(created["id"], registry_admin_headers), 200)

    assertions.assert_patient(read)
    assert read["id"] == created["id"]
    assert read["version"] == created["version"]
    assert read["mrn"] == "RH0001"
    assert read["diagnosis_code"] == "RA_SEROPOSITIVE"
    assert read["full_name"] == created["full_name"]
    assert read["date_of_birth"] == created["date_of_birth"]
    assert read["registry_consent"] == created["registry_consent"]
    assertions.assert_instant_equals(read["created_at"], created["created_at"], "created_at")


def test_repeated_patient_reads_never_advance_version(api, registry_admin_headers):
    """A read is not a mutation, so the revision counter stands still.

    PRD §2.4: "The `version` counter is the substrate of the concurrency
    controls in §2.6, so its behaviour is exact rather than approximate: a
    resource's `version` advances only where this document says it advances."

    Design: Corner/entities/patient_retrieval_returns_the_stored_entity
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    created = validate_success(
        api.create_patient(factories.create_patient_payload(mrn="RH0001"), registry_admin_headers),
        201,
    )
    expected_version = created["version"]

    first = validate_success(api.get_patient(created["id"], registry_admin_headers), 200)
    second = validate_success(api.get_patient(created["id"], registry_admin_headers), 200)

    assert first["version"] == expected_version
    assert second["version"] == expected_version


# ---------------------------------------------------------------------------
# Visit list pagination
# ---------------------------------------------------------------------------
def test_visit_listing_paginates_with_limit_offset_and_total_count(api, practice):
    """`total_count` counts the filtered set, not the page window.

    PRD §2.3: "Four pagination fields appear in the `meta` object of every list
    response: `limit` and `offset` echo the effective values applied to the
    query, `total_count` reports how many rows match the filters before the
    page window is applied, and `has_more` is true when rows remain beyond the
    current page."

    Design: Corner/entities/visit_listing_paginates_with_limit_offset_and_total_count
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    # Three mutually disjoint 30-minute FOLLOW_UP slots, so the two-concurrent
    # visit clinician cap cannot fire.
    for hour in (14, 15, 16):
        fixtures.book_visit(
            practice, visit_datetime=instant(2026, 8, 3, hour, 0, 0), visit_type="FOLLOW_UP"
        )

    first_page, first_meta = assertions.validate_list(
        api.list_visits(
            practice.admin_headers,
            params={"patient_id": practice.patient_id, "limit": 2, "offset": 0},
        )
    )
    assertions.assert_pagination_meta(first_meta, 2, 0, 3, True)
    assert len(first_page) == 2
    assertions.assert_created_at_ascending(first_page)

    second_page, second_meta = assertions.validate_list(
        api.list_visits(
            practice.admin_headers,
            params={"patient_id": practice.patient_id, "limit": 2, "offset": 2},
        )
    )
    assertions.assert_pagination_meta(second_meta, 2, 2, 3, False)
    assert len(second_page) == 1

    paged_ids = [row["id"] for row in first_page + second_page]
    assert len(set(paged_ids)) == 3, "the two pages must partition the filtered set"


def test_visit_listing_applies_the_declared_default_limit(api, practice):
    """An unpaginated request echoes the declared default page window.

    PRD §2.3: "Every list endpoint accepts two optional query parameters.
    `limit` controls page size: it defaults to 10, its minimum accepted value is
    1 and its maximum accepted value is 100."

    Design: Corner/entities/visit_listing_paginates_with_limit_offset_and_total_count
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    for hour in (14, 15, 16):
        fixtures.book_visit(
            practice, visit_datetime=instant(2026, 8, 3, hour, 0, 0), visit_type="FOLLOW_UP"
        )

    rows, meta = assertions.validate_list(
        api.list_visits(
            practice.admin_headers,
            params={"patient_id": practice.patient_id, "status": "SCHEDULED"},
        )
    )
    assertions.assert_pagination_meta(meta, 10, 0, 3, False)
    assert len(rows) == 3
    assert all(row["status"] == "SCHEDULED" for row in rows)


# ---------------------------------------------------------------------------
# Path-borne and body-borne not-found codes
# ---------------------------------------------------------------------------
def test_patient_not_found_returns_patient_not_found(api, registry_admin_headers):
    """An id that was never minted is a 404 on the patient-scoped read.

    PRD §2.5: "Likewise a patient-scoped read against an unknown patient fails
    with `ERR_PATIENT_NOT_FOUND` (HTTP 404) irrespective of what the rest of the
    request contains."

    Design: Corner/entities/patient_not_found_returns_patient_not_found
    """
    fixtures.set_clock(CLOCK_DEFAULT, registry_admin_headers)

    response = api.get_patient(UNKNOWN_UUID, registry_admin_headers)
    error = validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert error["error_id"] == "ERR_PATIENT_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"]


@pytest.mark.parametrize(
    "broken_field",
    ["patient_id", "drug_id"],
)
def test_therapy_episode_create_with_unknown_reference_returns_reference_not_found(
    api, practice, broken_field
):
    """A body reference that resolves to nothing outranks the concurrency token.

    PRD §3.4: "Any of the four references that fails to resolve yields
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/therapy_episode_create_with_unknown_patient_returns_reference_not_found
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    patient_version = practice.patient_version
    payload = factories.create_therapy_episode_payload(
        practice.patient_id,
        practice.drug_id,
        practice.plan_id,
        patient_version,
        therapy_start_at=CLOCK_DEFAULT,
    )
    payload[broken_field] = (
        UNKNOWN_UUID if broken_field == "patient_id" else SECOND_UNKNOWN_UUID
    )

    error = validate_error(
        api.create_therapy_episode(payload, practice.rheum_headers),
        ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
        404,
    )
    assert error["error_id"] != "ERR_STALE_PATIENT_VERSION"

    _rows, meta = assertions.validate_list(
        api.list_therapy_episodes(
            practice.admin_headers, params={"patient_id": practice.patient_id}
        )
    )
    assert meta["total_count"] == 0, "the rejected create must persist no episode"

    patient = validate_success(api.get_patient(practice.patient_id, practice.admin_headers))
    assert patient["version"] == patient_version, "the rejection left the parent untouched"


def test_monitoring_lab_body_episode_id_not_found_returns_episode_not_found(api, reference):
    """The body-borne episode reference carries its own not-found code.

    PRD §2.10: "`ERR_EPISODE_NOT_FOUND` — an `episode_id` body field does not
    resolve. Applies to authorization creation, monitoring-lab filing,
    appointment scheduling and enrollment creation."

    Design: Corner/entities/monitoring_lab_body_episode_id_not_found_returns_episode_not_found
    """
    fixtures.set_clock(CLOCK_DEFAULT, reference.admin_headers)

    payload = factories.create_monitoring_lab_payload(
        UNKNOWN_UUID, panel_type="CMP", collected_at=instant(2026, 7, 25), alt_u_l=30.0
    )
    error = validate_error(
        api.create_monitoring_lab(payload, reference.nurse_headers),
        ApiErrorId.ERR_EPISODE_NOT_FOUND.value,
        404,
    )
    assert error["error_id"] != "ERR_REFERENCE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Assistance enrollment reverse channel
# ---------------------------------------------------------------------------
def test_assistance_enrollment_reverse_lookup_by_episode_returns_the_child_row(api, planned):
    """The episode-scoped read is the enrollment's sole reverse channel.

    PRD §3.8: "An enrollment read exposes the full three-way ledger, and an
    episode's enrollments are listed through the episode-scoped read that is
    their sole reverse channel, optionally filtered by `status`."

    Design: Corner/entities/assistance_enrollment_reverse_lookup_by_episode_returns_the_child_row
    """
    fixtures.set_clock(CLOCK_DEFAULT, planned.admin_headers)

    enrollment = fixtures.submit_enrollment(
        planned,
        program_type="MANUFACTURER_COPAY_CARD",
        annual_benefit_cents=500_000,
        coverage_start=CLOCK_DEFAULT,
    )

    rows, meta = assertions.validate_list(
        api.list_episode_assistance_enrollments(planned.episode_id, planned.counselor_headers)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    row = rows[0]
    assertions.assert_assistance_enrollment(row)
    assert row["id"] == enrollment["id"]
    assert row["episode_id"] == planned.episode_id

    assert row["status"] == "SUBMITTED"
    assertions.assert_money_ledger(row, used=0, reserved=0, remaining=500_000)
    assert row["annual_benefit_cents"] == 500_000

    # A copay card runs 365 days from coverage_start; renewal is due 30 days early.
    assertions.assert_instant_equals(row["coverage_start"], CLOCK_DEFAULT, "coverage_start")
    assertions.assert_instant_equals(
        row["coverage_end"], instant(2027, 8, 1), "coverage_end"
    )
    assertions.assert_instant_equals(
        row["reauth_due_at"], instant(2027, 7, 2), "reauth_due_at"
    )

    assert row["submitted_by_user_id"] == COUNSELOR_ALPHA_USER_ID
    assert row["attested_by_user_id"] is None
    assert row["attested_at"] is None
    assert row["termination_reason"] is None


def test_assistance_enrollment_reverse_lookup_status_filter_excludes_submitted(api, planned):
    """The optional status filter narrows the reverse channel, and the scalar read agrees.

    PRD §2.5: "Because links are body fields rather than path segments, the list
    endpoints double as the reverse-reachability channel: visits can be filtered
    by `patient_id`, `clinician_id` and `status`; therapy episodes by
    `patient_id`, `drug_id`, `payer_plan_id`, `prior_episode_id`,
    `therapy_state` and `funding_state`; authorizations by `episode_id`,
    `exception_attested_by_clinician_id` and `status`; infusion appointments by
    `episode_id`, `chair_id`, `reserved_authorization_id`,
    `reserved_enrollment_id` and `status`; an episode's monitoring labs by
    `panel_type`; an episode's assistance enrollments by `status`; and a
    patient's screening records by `screen_type`."

    Design: Corner/entities/assistance_enrollment_reverse_lookup_by_episode_returns_the_child_row
    """
    fixtures.set_clock(CLOCK_DEFAULT, planned.admin_headers)

    enrollment = fixtures.submit_enrollment(
        planned,
        program_type="MANUFACTURER_COPAY_CARD",
        annual_benefit_cents=500_000,
        coverage_start=CLOCK_DEFAULT,
    )

    filtered_rows, filtered_meta = assertions.validate_list(
        api.list_episode_assistance_enrollments(
            planned.episode_id, planned.counselor_headers, params={"status": "ACTIVE"}
        )
    )
    assert filtered_meta["total_count"] == 0, "the SUBMITTED row is excluded by the filter"
    assert filtered_rows == []

    scalar = validate_success(
        api.get_assistance_enrollment(enrollment["id"], planned.counselor_headers), 200
    )
    assert scalar["id"] == enrollment["id"]
    assert scalar["episode_id"] == planned.episode_id
    assert scalar["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Immediate consistency: derived fields are readable at once
# ---------------------------------------------------------------------------
def test_screening_write_body_and_the_very_next_read_agree_immediately(api, practice):
    """No sweep or refresh sits between the screening write and its derived posture.

    PRD §3.3: "Every filed screening record re-derives both of the patient's
    screening postures and increments the patient's `version` by one."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_request_that_caused_it
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    before = validate_success(api.get_patient(practice.patient_id, practice.admin_headers))
    assert before["tb_screen_status"] == "MISSING"
    assert before["hbv_screen_status"] == "INCOMPLETE"
    assert before["target_status"] == "UNASSESSED"
    version_before = before["version"]

    written = validate_success(
        api.create_screening_record(
            factories.create_screening_record_payload(
                practice.patient_id,
                "TB_IGRA",
                "NEGATIVE",
                collected_at=instant(2026, 7, 20),
                resulted_at=instant(2026, 7, 21),
            ),
            practice.nurse_headers,
        ),
        201,
    )
    # The write's own body already carries the identity stamp — no follow-up read.
    assert written["recorded_by_user_id"] == practice.nurse_id
    assert written["screen_type"] == "TB_IGRA"
    assert written["result"] == "NEGATIVE"

    after = validate_success(api.get_patient(practice.patient_id, practice.rheum_headers))
    assert after["tb_screen_status"] == "CLEARED", "the derived posture needs no sweep"
    assert after["hbv_screen_status"] == "INCOMPLETE", "only the written marker moved"
    assert after["version"] == version_before + 1

    rows, meta = assertions.validate_list(
        api.list_patient_screening_records(practice.patient_id, practice.rheum_headers)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == written["id"]
    assert rows[0]["screen_type"] == "TB_IGRA"


def test_visit_and_scoring_derivations_appear_in_their_own_responses(api, practice):
    """The slot end and the whole scoring projection are present without a re-read.

    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_request_that_caused_it
    """
    fixtures.set_clock(CLOCK_DEFAULT, practice.admin_headers)

    booked = validate_success(
        api.create_visit(
            factories.create_visit_payload(
                practice.patient_id,
                practice.rheumatologist_id,
                visit_datetime=instant(2026, 8, 1, 9, 0, 0),
                visit_type="NEW",
            ),
            practice.admin_headers,
        ),
        201,
    )
    # A NEW visit occupies a full hour, and the end instant is in the create body.
    assertions.assert_instant_equals(
        booked["visit_end_datetime"], instant(2026, 8, 1, 10, 0, 0), "visit_end_datetime"
    )
    assert booked["status"] == "SCHEDULED"
    assert booked.get("activity_score") is None
    assert booked.get("activity_category") is None

    validate_success(api.check_in_visit(booked["id"], practice.nurse_headers), 200)

    scored = validate_success(
        api.score_visit(
            booked["id"],
            factories.score_visit_cdai_payload(
                tender_joint_count=1,
                swollen_joint_count=1,
                patient_global_assessment=2.0,
                physician_global_assessment=2.0,
            ),
            practice.rheum_headers,
        ),
        200,
    )
    assertions.assert_two_decimal_places(scored["activity_score"], "activity_score")
    assert float(scored["activity_score"]) == 6.00
    assert scored["activity_category"] == "LOW"
    assert scored["status"] == "SCORED"
    assertions.assert_instant_equals(scored["scored_at"], CLOCK_DEFAULT, "scored_at")

    patient = validate_success(api.get_patient(practice.patient_id, practice.rheum_headers))
    assert float(patient["latest_activity_score"]) == 6.00
    assert patient["latest_activity_category"] == "LOW"
    assert patient["target_status"] == "AT_TARGET"
