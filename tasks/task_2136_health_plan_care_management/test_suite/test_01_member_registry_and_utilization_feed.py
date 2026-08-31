"""Member registration, the utilization feed and the logical clock."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, UNKNOWN_UUID, UTILIZATION_ANALYST,
    assert_member, assert_transition_event, create_member, create_member_payload,
    create_transition_event_payload, is_iso8601_timestamp, is_valid_uuid,
    make_care_manager_headers, next_external_member_id, record_event,
    setup_program_and_managers, stratify, validate_error, validate_paginated,
    validate_success,
)


def test_member_registration_returns_declared_fields_with_null_risk_snapshots(api):
    """PRD §3.1: "A newly registered member has no stratification history, so all
    four of `latest_concurrent_score`, `latest_concurrent_tier`,
    `latest_prospective_score` and `latest_prospective_tier` start out null."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/member_creation_returns_declared_fields_with_null_risk_snapshots
    """
    payload = create_member_payload(
        external_member_id="MBR-3101", full_name="Ada Stone",
        birth_date="1970-01-01", state_code="CA", chronic_condition_count=2,
        social_data_consent_status="GRANTED",
    )
    response = api.create_member(payload, PROGRAM_ADMIN)
    data = validate_success(response, 201)

    assert_member(data)
    assert data["external_member_id"] == "MBR-3101"
    assert data["state_code"] == "CA"
    assert data["chronic_condition_count"] == 2
    assert data.get("latest_concurrent_score") is None
    assert data.get("latest_concurrent_tier") is None
    assert data.get("latest_prospective_score") is None
    assert data.get("latest_prospective_tier") is None
    assert data["version"] == 1

    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_member_retrieval_returns_the_stored_record(api):
    """PRD §4: "Read one member including the latest tier for each stratification
    variant." PRD §2.4: "`version`, an integer that starts at 1 on creation and
    increases by exactly one on every mutation of that record."

    Design: Corner/entities/member_retrieval_returns_stored_entity
    """
    member = create_member(
        external_member_id="MBR-3102", full_name="Bo Frey",
        birth_date="1969-02-02", state_code="NY", chronic_condition_count=1,
    )
    care_manager = setup_program_and_managers(with_reviewer=False)["care_manager"]

    data = validate_success(
        api.get_member(member["id"], make_care_manager_headers(care_manager["id"]))
    )
    assert data["id"] == member["id"]
    assert data["full_name"] == "Bo Frey"
    assert data["version"] == 1


def test_member_listing_honours_limit_and_offset(api):
    """PRD §2.3: "List responses populate four pagination fields inside `meta`:
    `limit` and `offset` echo the effective values used for the page,
    `total_count` reports the number of records matching the filter before the
    page window is applied, and `has_more` is true exactly when records remain
    beyond the current window."

    Design: Corner/entities/member_listing_paginates_with_limit_and_offset
    """
    for index, name in enumerate(("One", "Two", "Three"), start=1):
        create_member(
            external_member_id=f"MBR-320{index}", full_name=name,
            birth_date=f"196{index}-01-01", state_code="CA",
        )

    response = api.list_members(UTILIZATION_ANALYST, params={"limit": 2, "offset": 1})
    data, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(data) == 2, f"Expected 2 rows in the page window, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 1
    assert meta["has_more"] is False


def test_member_read_with_unknown_id_returns_member_not_found(api):
    """PRD §2.6: "The service reports the not-found code named for the failing
    segment: `ERR_MEMBER_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
    `ERR_CARE_MANAGER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_CARE_PLAN_NOT_FOUND`, `ERR_GOAL_NOT_FOUND`, `ERR_INTERVENTION_NOT_FOUND`,
    `ERR_TOUCH_NOT_FOUND`, `ERR_SOCIAL_NEED_NOT_FOUND`,
    `ERR_COMMUNITY_RESOURCE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND` or
    `ERR_TRANSITION_EVENT_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/member_get_unknown_id_returns_member_not_found
    """
    response = api.get_member(UNKNOWN_UUID, PROGRAM_ADMIN)
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_member_registration_without_state_code_is_rejected(api):
    """PRD §2.6: "on every write endpoint, each required input field is present,
    each enum-valued field holds a declared member of its enumeration, each
    integer or number field is of the correct type and satisfies its declared
    range constraint, and any instant-valued field such as `scheduled_end_at` or
    `service_end_at` parses as an ISO 8601 instant. Otherwise
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "Plan operations register one by supplying the plan's own
    `external_member_id` — the health-plan member number, which must be non-empty
    and unique across all members — together with the member's `full_name`, their
    `birth_date` as an ISO 8601 calendar date in year-month-day form, and their
    `state_code`, exactly two uppercase letters naming the US state of residence."

    Design: Corner/entities/member_create_missing_state_code_returns_invalid_request
    """
    response = api.create_member(
        {"external_member_id": "MBR-3301", "full_name": "No State",
         "birth_date": "1970-01-01"},
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400

    _, meta = validate_paginated(api.list_members(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, "the rejected registration must persist nothing"


def test_member_registration_applies_declared_optional_defaults(api):
    """PRD §3.1: "Two further attributes may be supplied at registration and
    default sensibly when they are not: `chronic_condition_count`, an integer no
    smaller than zero counting the member's active chronic conditions, which
    defaults to 0; and `social_data_consent_status`, which is either `GRANTED` or
    `REVOKED` and defaults to `GRANTED`."

    Design: Corner/entities/member_create_without_optional_fields_applies_declared_defaults
    """
    response = api.create_member(
        {"external_member_id": "MBR-3401", "full_name": "Default Dee",
         "birth_date": "1980-03-03", "state_code": "CA"},
        PROGRAM_ADMIN,
    )
    data = validate_success(response, 201)
    assert data["chronic_condition_count"] == 0
    assert data["social_data_consent_status"] == "GRANTED"


def test_member_identity_fields_are_server_minted(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id` — a UUID
    with no type prefix of any kind — and a `created_at` timestamp recorded as an
    ISO 8601 UTC instant with three fractional-second digits."
    PRD §2.4: "`version`, an integer that starts at 1 on creation and increases by
    exactly one on every mutation of that record."

    Design: Corner/entities/member_system_fields_are_server_minted_untyped_uuids
    """
    data = validate_success(
        api.create_member(
            create_member_payload(
                external_member_id="MBR-3501", full_name="Uid Probe",
                birth_date="1975-04-04",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert is_valid_uuid(data["id"]), (
        f"id must be a bare 8-4-4-4-12 UUID with no prefix, got {data['id']!r}"
    )
    assert len(data["id"]) == 36
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["version"] == 1


def test_discharge_naming_unknown_index_admission_is_not_found(api):
    """PRD §3.1: "A discharge may also point back at the admission it closes
    through `index_admission_event_id`, a reference to the earlier event record;
    for any event type other than `DISCHARGE` that reference is null."
    PRD §2.6: "Transition event creation resolves `member_id`, then
    `index_admission_event_id`."

    Design: Corner/entities/discharge_referencing_unknown_index_admission_returns_transition_event_not_found
    """
    member = create_member(external_member_id="MBR-3801", full_name="Ref Probe",
                           birth_date="1959-05-05")
    response = api.create_transition_event(
        {"member_id": member["id"], "event_type": "DISCHARGE",
         "occurred_at": "2026-08-01T00:00:00Z", "facility_name": "Bay General",
         "adjudication_status": "CLOSED", "discharge_disposition": "HOME",
         "index_admission_event_id": UNKNOWN_UUID},
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_TRANSITION_EVENT_NOT_FOUND.value)
    assert response.status_code == 404

    _, meta = validate_paginated(
        api.list_transition_events(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 0


def test_transition_event_listing_filters_by_index_admission(api):
    """PRD §4: "List utilization events, optionally by member, by type, or by the
    index admission a discharge closes."
    PRD §3.7: "Recording a utilization event whose `event_type` is `DISCHARGE`
    fires a cascade on every enrollment of that member whose `enrollment_status`
    is `ACTIVE`."

    Design: Corner/endpoints/transition_event_list_filters_by_index_admission_event_id
    """
    member = create_member(external_member_id="MBR-8201", full_name="Link Lia",
                           birth_date="1970-01-01")
    admission = record_event(
        member["id"], event_type="INPATIENT_ADMISSION",
        occurred_at="2026-07-28T00:00:00Z", episode_cost_cents=700000,
        adjudication_status="CLOSED",
    )
    discharge_response = api.create_transition_event(
        create_transition_event_payload(
            member["id"], event_type="DISCHARGE",
            occurred_at="2026-08-01T00:00:00Z", episode_cost_cents=0,
            adjudication_status="CLOSED", discharge_disposition="SNF",
            index_admission_event_id=admission["id"],
        ),
        PROGRAM_ADMIN,
    )
    discharge = validate_success(discharge_response, 201)
    assert_transition_event(discharge)
    assert discharge["toc_triggered_enrollment_count"] == 0, (
        "a member with no ACTIVE enrollment escalates nothing"
    )

    record_event(member["id"], event_type="ED_VISIT",
                 occurred_at="2026-07-10T00:00:00Z", episode_cost_cents=120000,
                 adjudication_status="CLOSED")

    rows, meta = validate_paginated(
        api.list_transition_events(
            PROGRAM_ADMIN, params={"index_admission_event_id": admission["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == discharge["id"]

    _, all_meta = validate_paginated(
        api.list_transition_events(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert all_meta["total_count"] == 3


def test_logical_clock_starts_at_the_declared_startup_instant(api):
    """PRD §2.5: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."
    PRD §3.2: "an `as_of_date` stamped as the calendar date of the logical clock
    at computation time"
    PRD §3.4: "Activation stamps `activated_at` with the logical-clock instant and
    then does five things in the member's file."

    Design: Corner/endpoints/logical_clock_defaults_to_declared_startup_instant
    """
    from test_helpers import create_program, create_care_manager, enroll

    program = create_program(name="Clock Default Program", min_risk_tier="LOW")
    care_manager = create_care_manager(full_name="Rita Nolan")
    member = create_member(external_member_id="MBR-8401", full_name="Clock Cleo",
                           birth_date="1970-01-01")
    stratification = stratify(member["id"], "CONCURRENT")
    assert stratification["as_of_date"] == "2026-08-01"

    enrollment = enroll(member["id"], program["id"], care_manager["id"])
    activated = validate_success(api.activate_enrollment(enrollment["id"], PROGRAM_ADMIN))

    assert activated["activated_at"] == "2026-08-01T00:00:00.000Z"
    assert activated["next_touch_due_at"] == "2026-08-31T00:00:00.000Z", (
        "a STANDARD cadence projects 30 days from activated_at"
    )

    clock = validate_success(api.set_clock("2026-09-01T00:00:00Z", PROGRAM_ADMIN))
    assert clock["current_utc"] == "2026-09-01T00:00:00.000Z"
