"""Entity surface: creation echoes, declared defaults, reads, listings and references."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    COMPLAINANT_HEADERS,
    RECORDS_CUSTODIAN_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_append_only_common_fields,
    assert_created_equals_updated,
    assert_envelope_meta,
    assert_instant,
    assert_list_page,
    assert_mutable_common_fields,
    assert_single_read_omits_pagination,
    assert_two_dp,
    make_ia_commander_headers,
    make_supervisor_headers,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"
UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_OFFICER_ID = "00000000-0000-0000-0000-0000000000fe"
UNKNOWN_UNIT_ID = "00000000-0000-0000-0000-0000000000fd"
STANDING_COMMANDER_ID = "00000000-0000-0000-0000-00000000000a"


def test_officer_creation_echoes_every_declared_field(api):
    """The first write of the domain's root entity returns all of it, stamped from the clock.

    PRD: Creating a sworn officer record requires the officer's `unit_id`, `badge_number`, `full_name`, `rank`, `assignment_type`, `annual_salary_cents`, `demographic_code` and `hire_date`, the last of which is an ISO 8601 UTC date of hire.
    PRD: A newly created officer starts with every derived field at its zero point: `employment_status` is `ACTIVE`, `eis_score` is 0.00, `eis_alert_level` is `NONE`, `open_case_load` is 0, `open_alert_count` is 0, `imposed_suspension_days_total` is 0, `intervention_escalation_count` is 0, `credibility_disclosure_active` is false, and `suspension_end_date` is null.
    PRD: `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `created_at` is stamped when the row is first written and never changes, `updated_at` is refreshed on every accepted mutation of that row, and `version` is an integer that begins at 1 and increments by exactly 1 on every accepted mutation.
    Design: Corner/entities/officer_creation_returns_201_with_every_declared_field
    """
    fixtures.set_clock(api, BASE_CLOCK)
    patrol_unit = fixtures.create_unit(api, intake_enabled=True)

    response = api.create_officer(
        factories.officer_payload(
            patrol_unit["id"],
            badge_number="PN-777",
            full_name="Officer Ruiz",
            rank="OFFICER",
            assignment_type="PATROL",
            annual_salary_cents=8800000,
            demographic_code="DG_D",
            hire_date="2021-06-14T00:00:00Z",
            is_investigator=False,
            certification_level=1,
            max_case_load=4,
        ),
        SYSTEM_ADMIN_HEADERS,
    )

    officer = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)
    assert_single_read_omits_pagination(body)

    assert officer["unit_id"] == patrol_unit["id"]
    assert officer["badge_number"] == "PN-777"
    assert officer["full_name"] == "Officer Ruiz"
    assert officer["rank"] == "OFFICER"
    assert officer["assignment_type"] == "PATROL"
    assert officer["annual_salary_cents"] == 8800000
    assert officer["demographic_code"] == "DG_D"
    assert officer["is_investigator"] is False
    assert officer["certification_level"] == 1
    assert officer["max_case_load"] == 4
    assert officer["employment_status"] == "ACTIVE"

    assert_mutable_common_fields(officer, "officer")
    assert_created_equals_updated(officer, "officer")
    assert_instant(officer["created_at"], BASE_CLOCK, "officer.created_at")
    assert_instant(officer["updated_at"], BASE_CLOCK, "officer.updated_at")


def test_omitted_optional_inputs_fall_back_to_declared_defaults(api):
    """Four entities each supply only their required inputs, and none of the defaults is null.

    PRD: A sixth field, `intake_enabled`, defaults to true when omitted and is the switch that takes a unit out of the routing pool: a unit whose `intake_enabled` is false is never an eligible routing target, even for a complaint that names it.
    PRD: Hearing rooms are seeded the same way, with a `facility_code`, a `room_name`, a `concurrent_capacity` of at least 1 and a `recording_enabled` flag that defaults to true and records whether the room supports a recorded interview.
    PRD: Three further fields are optional and carry defaults: `is_investigator` defaults to false, `certification_level` defaults to 0, and `max_case_load` defaults to 5.
    PRD: `complainant_demographic_code` is optional and stores `UNKNOWN` when omitted, which matters later because `UNKNOWN` forms its own reporting group rather than being excluded.
    PRD: Anonymous intake is the exception: the sequence is still assigned, but `intake_reference_code` stays null, and an anonymous complainant consequently holds no credential with which to withdraw.
    PRD: A `Supervisor` or a `SystemAdmin` records a risk-relevant event against an officer, supplying the `event_type`, an optional `severity_code` that defaults to `NA`, the `occurred_at` instant and an optional `source_reference` naming the source report.
    PRD: On acceptance the system derives `base_weight` from the event type's base weight in the scoring table below, and derives `weekday_index` from `occurred_at`: an integer from 0 to 6 where 0 is Monday, computed in UTC.
    PRD: The first is the base weight of its `event_type`: 3 for `USE_OF_FORCE`, 2 for `PURSUIT`, 1 for `SICK_LEAVE_DAY`, 1 for `COMPLAINT_INTAKE` and 4 for `COMPLAINT_SUSTAINED` — a sustained complaint weighs more than any single incident.
    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    fixtures.set_clock(api, BASE_CLOCK)
    ia_unit = fixtures.create_unit(
        api,
        name="Internal Affairs",
        unit_role="INTERNAL_AFFAIRS",
        command_code="IA",
        peer_group_code="PG_IA",
        sworn_headcount=12,
    )
    room = fixtures.create_hearing_room(api, concurrent_capacity=2)
    bell = fixtures.create_officer(
        api, ia_unit["id"], badge_number="IA-900", full_name="Officer Bell"
    )

    assert ia_unit["intake_enabled"] is True
    assert room["recording_enabled"] is True
    assert bell["is_investigator"] is False
    assert bell["certification_level"] == 0
    assert bell["max_case_load"] == 5

    complaint = validate_success(
        api.create_complaint(
            factories.anonymous_complaint_payload(
                ia_unit["id"],
                narrative="Rude language on a traffic stop.",
                incident_datetime="2026-07-20T18:00:00Z",
            ),
            COMPLAINANT_HEADERS,
        ),
        201,
    )

    assert complaint["complainant_demographic_code"] == "UNKNOWN"
    assert complaint["alleged_injury"] is False
    assert complaint["intake_reference_code"] is None

    event = validate_success(
        api.create_activity_event(
            bell["id"],
            factories.activity_event_payload(
                event_type="PURSUIT", occurred_at="2026-07-25T12:00:00Z"
            ),
            make_supervisor_headers(bell["id"]),
        ),
        201,
    )

    assert event["severity_code"] == "NA"
    assert_two_dp(event["base_weight"], 2.0, label="base_weight")
    assert event["system_generated"] is False


def test_complaint_retrieval_returns_the_stored_intake_row(api, world):
    """A second internal-affairs unit appears after intake, and the read still reports the first routing.

    PRD: `received_at` is stamped from the logical clock at intake and becomes the anchor for the statutory investigation window.
    PRD: Otherwise it is `CLASS_II` when at least one reported type is `NEGLECT_OF_DUTY` or `PURSUIT_VIOLATION`.
    PRD: Otherwise, when the unit identified by `subject_unit_id` has `intake_enabled` true, the target is that same `subject_unit_id`.
    PRD: `intake_reference_code` is that sequence rendered as the four literal characters `CMP-` followed by the sequence zero-padded to six digits — sequence 123 yields `CMP-000123`.
    Design: Corner/entities/complaint_retrieval_returns_the_stored_intake_row
    """
    filed = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Reports not filed for four shifts.",
        incident_datetime="2026-07-15T20:00:00Z",
        complainant_demographic_code="DG_A",
    )
    fixtures.create_unit(
        api,
        name="Internal Affairs Annex",
        unit_role="INTERNAL_AFFAIRS",
        command_code="IAA",
        peer_group_code="PG_IA",
        sworn_headcount=4,
        intake_enabled=True,
    )

    response = api.get_complaint(filed["id"], RECORDS_CUSTODIAN_HEADERS)
    complaint = validate_success(response, 200)
    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)
    assert_single_read_omits_pagination(body)

    assert complaint["id"] == filed["id"]
    assert complaint["narrative"] == "Reports not filed for four shifts."
    assert complaint["intake_channel"] == "SUPERVISOR"
    assert_instant(complaint["incident_datetime"], "2026-07-15T20:00:00Z")
    assert_instant(complaint["received_at"], BASE_CLOCK)
    assert complaint["classification"] == "CLASS_II"
    assert complaint["priority"] == 2
    assert complaint["assigned_unit_id"] == world["patrol_unit_id"]
    assert complaint["screening_required"] is False
    assert complaint["status"] == "CLASSIFIED"
    assert complaint["intake_reference_code"] == "CMP-000001"
    assert complaint["allegation_count"] == 0
    assert complaint["version"] == 1


def test_complaint_listing_returns_the_pagination_envelope(api, world):
    """Five rows against a default page of ten, then a two-row page and its trailing remainder.

    PRD: Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` controls the starting position: it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is a schema failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).
    PRD: List responses populate all four pagination fields in `meta`: `limit` and `offset` echo the effective values actually applied, `total_count` reports the number of records matching the filters before the page window is applied, and `has_more` is true when records remain beyond the current window. Single-resource reads and mutations omit those four fields.
    PRD: Unless a specific list endpoint states otherwise, results are ordered by `created_at` ascending.
    Design: Corner/entities/complaint_listing_returns_the_pagination_envelope
    """
    filed = [
        fixtures.file_supervisor_complaint(
            api,
            world,
            narrative=f"Complaint {label}.",
            incident_datetime=f"2026-07-1{index}T20:00:00Z",
        )["id"]
        for index, label in enumerate(("one", "two", "three", "four", "five"), start=1)
    ]

    response = api.list_complaints(RECORDS_CUSTODIAN_HEADERS)
    assert response.status_code == 200
    assert response.json()["response_type"] == "array"
    everything, meta = fixtures.rows(response)
    assert_list_page(meta, limit=10, offset=0, total=5, has_more=False)
    assert [row["id"] for row in everything] == filed

    first_page, first_meta = fixtures.rows(
        api.list_complaints(RECORDS_CUSTODIAN_HEADERS, {"limit": 2, "offset": 0})
    )
    assert_list_page(first_meta, limit=2, offset=0, total=5, has_more=True)
    assert [row["id"] for row in first_page] == filed[:2]

    last_page, last_meta = fixtures.rows(
        api.list_complaints(RECORDS_CUSTODIAN_HEADERS, {"limit": 2, "offset": 4})
    )
    assert_list_page(last_meta, limit=2, offset=4, total=5, has_more=False)
    assert [row["id"] for row in last_page] == filed[4:]

    assert not {row["id"] for row in first_page} & {row["id"] for row in last_page}


def test_unknown_complaint_id_returns_not_found_on_a_read_and_on_an_action(api):
    """The existence ladder answers first, so the purge route never reports a state error.

    PRD: A request naming a complaint that does not exist fails with `ERR_COMPLAINT_NOT_FOUND` (HTTP 404) whatever else is wrong with the body; the same principle yields `ERR_OFFICER_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_ALLEGATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_DISCIPLINE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REINSTATEMENT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND` and `ERR_ROOM_NOT_FOUND` for their respective resources, each with HTTP 404.
    PRD: A complaints path segment must resolve to a `Complaint` on the single-complaint read, allegation creation, classification, investigation opening, withdrawal and purge; an officers path segment must resolve to an `Officer` on the single-officer read, the activity-event list, the EIS profile read, activity-event creation and the employment-status write; an investigations path segment must resolve to an `Investigation` on the single-investigation read, assignment, tolling, interview-session creation, findings and close; an allegations path segment must resolve to an `Allegation` on the single-allegation read and the disposition write; an interview-sessions path segment must resolve to an `InterviewSession` on the single-session read, hold and postpone; a disciplines path segment must resolve to a `Discipline` on the single-discipline read, impose and appeal filing; an appeals path segment must resolve to an `Appeal` on the single-appeal read, the reinstatement list, hear and decide; a reinstatements path segment must resolve to a `Reinstatement` on finalize; an eis-alerts path segment must resolve to an `EarlyInterventionAlert` on the single-alert read, dismiss and plan creation; an intervention-plans path segment must resolve to an `InterventionPlan` on the single-plan read, the check-in list, activate and close; a check-ins path segment must resolve to a `MonitoringCheckIn` on complete; and a credibility-disclosures path segment must resolve to a `CredibilityDisclosure` on the single-disclosure read and release.
    PRD: The `message` provides a human-readable explanation of what went wrong.
    Design: Corner/entities/unknown_complaint_id_returns_not_found
    """
    fixtures.set_clock(api, BASE_CLOCK)

    read = api.get_complaint(UNKNOWN_ID, make_ia_commander_headers(STANDING_COMMANDER_ID))
    read_error = validate_error(read, "ERR_COMPLAINT_NOT_FOUND", 404)
    read_body = read.json()
    assert read_body["response_type"] == "error"
    assert_envelope_meta(read_body)
    assert isinstance(read_error["message"], str) and read_error["message"]

    purge = api.purge_complaint(
        UNKNOWN_ID, {"purge_reason": "probe"}, RECORDS_CUSTODIAN_HEADERS
    )
    purge_error = validate_error(purge, "ERR_COMPLAINT_NOT_FOUND", 404)
    purge_body = purge.json()
    assert purge_body["response_type"] == "error"
    assert_envelope_meta(purge_body)
    assert isinstance(purge_error["message"], str) and purge_error["message"]


def test_complaint_intake_missing_required_fields_is_rejected(api):
    """Two intakes, each short one required input, and neither leaves a row behind.

    PRD: **Schema** — on every endpoint, the body parses, every field the endpoint requires is present, and every supplied value matches its declared type, its enum domain and its numeric range.
    PRD: A `Complainant`, a `Supervisor` or an `IACommander` submits the `intake_channel`, the free-text `narrative`, the `incident_datetime` at which the alleged conduct occurred, the `alleged_injury` flag, a non-empty `reported_allegation_types` array and the `subject_unit_id` the complaint concerns.
    Design: Corner/entities/complaint_intake_missing_required_narrative_is_rejected
    """
    fixtures.set_clock(api, BASE_CLOCK)
    fixtures.create_internal_affairs_unit(api)
    patrol_unit = fixtures.create_unit(api, intake_enabled=True)

    without_narrative = factories.public_complaint_payload(
        patrol_unit["id"], complainant_name="Dana Ruiz", complainant_contact="dana@example.org"
    )
    without_narrative.pop("narrative")
    validate_error(
        api.create_complaint(without_narrative, COMPLAINANT_HEADERS), "ERR_INVALID_REQUEST", 400
    )

    without_types = factories.public_complaint_payload(
        patrol_unit["id"],
        narrative="No allegation types supplied.",
        complainant_name="Dana Ruiz",
        complainant_contact="dana@example.org",
    )
    without_types.pop("reported_allegation_types")
    validate_error(
        api.create_complaint(without_types, COMPLAINANT_HEADERS), "ERR_INVALID_REQUEST", 400
    )

    stored, meta = fixtures.rows(api.list_complaints(RECORDS_CUSTODIAN_HEADERS))
    assert meta["total_count"] == 0
    assert stored == []


def test_complaint_classification_is_computed_and_the_supplied_values_are_ignored(api, world):
    """A body claiming CLASS_III priority 3 against the subject unit is overruled on all three.

    PRD: The complaint is `CLASS_I` when `alleged_injury` is true, or when at least one member of `reported_allegation_types` is `EXCESSIVE_FORCE`, `UNLAWFUL_SEARCH` or `UNTRUTHFULNESS`.
    PRD: Because injury is tested first, a complaint reporting only `NEGLECT_OF_DUTY` but alleging injury classifies `CLASS_I`, not `CLASS_II`: injury outranks the moderate band.
    PRD: `priority` is derived mechanically from `classification`: 1 for `CLASS_I`, 2 for `CLASS_II` and 3 for `CLASS_III`, where 1 is the most urgent.
    PRD: When `classification` is `CLASS_I`, or when `screening_required` is true, the target is the unit whose `unit_role` is `INTERNAL_AFFAIRS` with the earliest `created_at` — the subject unit never investigates a Class I complaint about itself.
    PRD: `screening_required` is true when, and only when, `classification` is `CLASS_III` **and** `intake_channel` is `ANONYMOUS`.
    PRD: The same 365-day figure is stored forward as `statute_expires_at`, which is `incident_datetime` plus 365 whole days — the deadline for filing about this incident, entirely separate from the investigation's own due date.
    Design: Corner/entities/complaint_classification_is_computed_and_the_extra_field_is_ignored
    """
    injured = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Takedown caused a wrist fracture.",
        incident_datetime="2026-07-15T20:00:00Z",
        alleged_injury=True,
        reported_allegation_types=["NEGLECT_OF_DUTY"],
        complainant_demographic_code="DG_A",
        classification="CLASS_III",
        priority=3,
        assigned_unit_id=world["patrol_unit_id"],
    )

    assert injured["classification"] == "CLASS_I"
    assert injured["priority"] == 1
    assert injured["assigned_unit_id"] == world["ia_unit_id"]
    assert injured["screening_required"] is False
    assert_instant(injured["statute_expires_at"], "2027-07-15T20:00:00Z")
    assert injured["status"] == "CLASSIFIED"

    stored = fixtures.read_complaint(api, injured["id"], world["cmdr_headers"])
    assert stored["classification"] == "CLASS_I"
    assert stored["priority"] == 1
    assert stored["assigned_unit_id"] == world["ia_unit_id"]


def test_intake_sequence_and_reference_code_are_minted_from_the_store(api, world):
    """Both bodies claim sequence 99, and the store hands out 1 and then 2.

    PRD: The identifier never carries a type prefix, and clients never supply it — an `id` present in a request body is ignored.
    PRD: `intake_sequence` is a monotonic counter: each accepted intake takes the previous maximum plus 1, and the very first accepted intake takes 1.
    PRD: `intake_reference_code` is that sequence rendered as the four literal characters `CMP-` followed by the sequence zero-padded to six digits — sequence 123 yields `CMP-000123`.
    PRD: `received_at` is stamped from the logical clock at intake and becomes the anchor for the statutory investigation window.
    Design: Corner/entities/intake_sequence_and_reference_code_are_minted_with_ignored_input
    """
    first = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="First intake of the store.",
        incident_datetime="2026-07-15T20:00:00Z",
        id="11111111-1111-1111-1111-111111111111",
        intake_sequence=99,
        intake_reference_code="CMP-000999",
        status="CLOSED",
        received_at="2020-01-01T00:00:00Z",
    )

    assert first["intake_sequence"] == 1
    assert first["intake_reference_code"] == "CMP-000001"
    assert_instant(first["received_at"], BASE_CLOCK)
    assert first["status"] == "CLASSIFIED"
    assert first["id"] != "11111111-1111-1111-1111-111111111111"

    second = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Second intake of the store.",
        incident_datetime="2026-07-16T20:00:00Z",
        intake_sequence=99,
    )

    assert second["intake_sequence"] == 2
    assert second["intake_reference_code"] == "CMP-000002"


def test_officer_enum_range_and_empty_array_constraints_are_all_rejected(api):
    """An unlisted rank, a certification level of four and an empty type list all fail the same tier.

    PRD: **Schema** — on every endpoint, the body parses, every field the endpoint requires is present, and every supplied value matches its declared type, its enum domain and its numeric range. The declared ranges are: `certification_level` from 0 through 3, `priority` from 1 through 3, `aggravator_count` and `mitigator_count` each from 0 through 5, `required_checkin_count` from 2 through 6, `duration_days` exactly one of 30, 60 or 90, `sworn_headcount` at least 1, `concurrent_capacity` at least 1, `max_case_load` at least 0, `annual_salary_cents` at least 0, `limit` from 1 through 100 and `offset` at least 0. Failure: `ERR_INVALID_REQUEST` (400).
    PRD: A `Complainant`, a `Supervisor` or an `IACommander` submits the `intake_channel`, the free-text `narrative`, the `incident_datetime` at which the alleged conduct occurred, the `alleged_injury` flag, a non-empty `reported_allegation_types` array and the `subject_unit_id` the complaint concerns.
    Design: Corner/entities/officer_invalid_enum_rank_and_out_of_range_certification_are_rejected
    """
    fixtures.set_clock(api, BASE_CLOCK)
    fixtures.create_internal_affairs_unit(api)
    patrol_unit = fixtures.create_unit(api, intake_enabled=True)

    bad_rank = api.create_officer(
        factories.officer_payload(
            patrol_unit["id"],
            badge_number="PN-801",
            full_name="Officer Rank Probe",
            rank="COLONEL",
        ),
        SYSTEM_ADMIN_HEADERS,
    )
    validate_error(bad_rank, "ERR_INVALID_REQUEST", 400)

    bad_certification = api.create_officer(
        factories.officer_payload(
            patrol_unit["id"],
            badge_number="PN-802",
            full_name="Officer Cert Probe",
            certification_level=4,
        ),
        SYSTEM_ADMIN_HEADERS,
    )
    validate_error(bad_certification, "ERR_INVALID_REQUEST", 400)

    empty_types = api.create_complaint(
        factories.public_complaint_payload(
            patrol_unit["id"],
            narrative="Empty allegation list.",
            reported_allegation_types=[],
            complainant_name="Dana Ruiz",
            complainant_contact="dana@example.org",
        ),
        COMPLAINANT_HEADERS,
    )
    validate_error(empty_types, "ERR_INVALID_REQUEST", 400)

    officers, officer_meta = fixtures.rows(api.list_officers(SYSTEM_ADMIN_HEADERS))
    assert officer_meta["total_count"] == 0
    assert officers == []
    complaints, complaint_meta = fixtures.rows(api.list_complaints(RECORDS_CUSTODIAN_HEADERS))
    assert complaint_meta["total_count"] == 0
    assert complaints == []


def test_an_activity_event_is_append_only_with_no_version_and_no_update_path(api):
    """The event carries neither counter, and the only write route it has is the append.

    PRD: Three record types are append-only history and therefore carry only `id` and `created_at` — for a `Unit`, a `HearingRoom` and an `OfficerActivityEvent` both `updated_at` and `version` are absent from the resource entirely.
    PRD: Events are immutable once written: they carry only an `id` and a `created_at`, and there is no update path.
    PRD: On acceptance the system derives `base_weight` from the event type's base weight in the scoring table below, and derives `weekday_index` from `occurred_at`: an integer from 0 to 6 where 0 is Monday, computed in UTC.
    PRD: `system_generated` is false for supervisor-recorded events and true only for the `COMPLAINT_SUSTAINED` events that the sustained-disposition cascade appends.
    PRD: An officer's events are listed in `occurred_at` ascending order with an optional `event_type` filter.
    Design: Corner/entities/activity_event_is_immutable_with_no_version_and_no_write_back_route
    """
    fixtures.set_clock(api, BASE_CLOCK)
    patrol_unit = fixtures.create_unit(api, intake_enabled=True)
    bell = fixtures.create_officer(
        api, patrol_unit["id"], badge_number="PN-041", full_name="Officer Bell"
    )

    response = api.create_activity_event(
        bell["id"],
        factories.activity_event_payload(
            event_type="USE_OF_FORCE",
            occurred_at="2026-07-15T20:00:00Z",
            severity_code="LEVEL_2",
            source_reference="UOF-2026-0142",
        ),
        make_supervisor_headers(bell["id"]),
    )

    event = validate_success(response, 201)
    assert event["officer_id"] == bell["id"]
    assert event["source_reference"] == "UOF-2026-0142"
    assert event["severity_code"] == "LEVEL_2"
    assert event["weekday_index"] == 2
    assert event["system_generated"] is False
    assert_append_only_common_fields(event, "activity event")

    listed, meta = fixtures.rows(
        api.list_activity_events(bell["id"], SYSTEM_ADMIN_HEADERS, {"event_type": "USE_OF_FORCE"})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [event["id"]]
    assert_append_only_common_fields(listed[0], "listed activity event")
    assert listed[0]["weekday_index"] == 2


def test_allegation_parent_and_body_references_must_each_resolve(api, world):
    """Three broken references give three different 404s, and only the clean call moves the counter.

    PRD: Path parameters are resolved strictly left to right, and the leftmost unresolvable segment decides the error.
    PRD: **Body-reference existence** — every foreign key inside the body resolves. `reporting_supervisor_officer_id` on intake, `subject_officer_id` on allegation creation and on interview-session creation, `investigator_officer_id` on assignment, and `supervisor_officer_id` on plan creation must each resolve to an `Officer`, failing with `ERR_OFFICER_NOT_FOUND` (404); `subject_unit_id` on intake and `unit_id` on officer creation must resolve to a `Unit`, failing with `ERR_UNIT_NOT_FOUND` (404); and `hearing_room_id` on interview-session creation and on postponement must resolve to a `HearingRoom`, failing with `ERR_ROOM_NOT_FOUND` (404).
    PRD: Each accepted allegation raises the complaint's `allegation_count` by 1 and starts life with `disposition` `PENDING`, `evidence_weight_for` and `evidence_weight_against` both 0, `support_pct` 0.00, `redacted` false, and `policy_compliant`, `disposed_at` and `prior_sustained_count_at_disposition` all unset.
    Design: Corner/entities/allegation_parent_and_body_references_must_resolve_or_return_not_found
    """
    complaint = fixtures.file_supervisor_complaint(
        api, world, narrative="Reports not filed for four shifts."
    )

    bad_parent = api.create_allegation(
        UNKNOWN_ID,
        factories.allegation_payload(
            world["subj_id"], narrative="Parent probe.", offense_class="C"
        ),
        world["cmdr_headers"],
    )
    validate_error(bad_parent, "ERR_COMPLAINT_NOT_FOUND", 404)

    bad_officer = api.create_allegation(
        complaint["id"],
        factories.allegation_payload(
            UNKNOWN_OFFICER_ID, narrative="Body officer probe.", offense_class="C"
        ),
        world["cmdr_headers"],
    )
    validate_error(bad_officer, "ERR_OFFICER_NOT_FOUND", 404)

    bad_unit = api.create_complaint(
        factories.supervisor_complaint_payload(
            UNKNOWN_UNIT_ID, world["sup_id"], narrative="Body unit probe."
        ),
        world["sup_headers"],
    )
    validate_error(bad_unit, "ERR_UNIT_NOT_FOUND", 404)

    created = validate_success(
        api.create_allegation(
            complaint["id"],
            factories.allegation_payload(
                world["subj_id"],
                narrative="Reports for four shifts were never filed.",
                offense_class="C",
            ),
            world["cmdr_headers"],
        ),
        201,
    )

    assert created["complaint_id"] == complaint["id"]
    assert created["subject_officer_id"] == world["subj_id"]
    assert created["disposition"] == "PENDING"
    assert created["evidence_weight_for"] == 0
    assert created["evidence_weight_against"] == 0
    assert_two_dp(created["support_pct"], 0.00, label="support_pct")
    assert created["redacted"] is False

    parent = fixtures.read_complaint(api, complaint["id"], world["cmdr_headers"])
    assert parent["allegation_count"] == 1


def test_one_officer_can_investigate_one_file_while_being_the_subject_of_another(api, world):
    """Ahn carries file A and is accused on file B, and only the self-loop is forbidden.

    PRD: A nominated officer who is a subject of the complaint, who shares a `unit_id` with any subject officer, or who is the acting commander is refused with `ERR_INVESTIGATOR_CONFLICT`.
    PRD: Allegations are listed with optional `complaint_id`, `subject_officer_id`, `disposition` and `allegation_type` filters, and a single allegation read returns its evidence weights and disposition.
    Design: Corner/entities/one_officer_spans_the_investigator_and_subject_roles_across_two_files
    """
    west_unit = fixtures.create_unit(
        api,
        name="Patrol West",
        command_code="PW",
        peer_group_code="PG_WEST",
        sworn_headcount=40,
        intake_enabled=True,
    )
    croft = fixtures.create_investigator(
        api,
        west_unit["id"],
        badge_number="PW-102",
        full_name="Investigator Croft",
        certification_level=3,
        max_case_load=3,
    )

    file_a = fixtures.file_supervisor_complaint(
        api, world, narrative="Reports not filed for four shifts."
    )
    allegation_a = fixtures.attach_allegation(
        api, world, file_a["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    investigation_a = fixtures.open_investigation(api, world, file_a["id"])
    fixtures.assign_investigation(
        api, world, investigation_a["id"], investigation_a["version"], world["inv_a_id"]
    )

    file_b = fixtures.file_supervisor_complaint(
        api,
        world,
        narrative="Investigator delayed his own casework.",
        incident_datetime="2026-07-18T20:00:00Z",
        subject_unit_id=world["ia_unit_id"],
    )
    allegation_b = fixtures.attach_allegation(
        api,
        world,
        file_b["id"],
        subject_officer_id=world["inv_a_id"],
        allegation_type="NEGLECT_OF_DUTY",
        offense_class="C",
        narrative="Case file sat untouched for six weeks.",
    )
    investigation_b = fixtures.open_investigation(api, world, file_b["id"])

    self_loop = api.assign_investigation(
        investigation_b["id"],
        factories.assignment_payload(investigation_b["version"], world["inv_a_id"]),
        world["cmdr_headers"],
    )
    validate_error(self_loop, "ERR_INVESTIGATOR_CONFLICT", 422)
    untouched = fixtures.read_investigation(api, investigation_b["id"], world["cmdr_headers"])
    assert untouched["status"] == "UNASSIGNED"
    assert untouched["assignment_count"] == 0
    assert untouched["version"] == investigation_b["version"]

    assigned = fixtures.assign_investigation(
        api, world, investigation_b["id"], investigation_b["version"], croft["id"]
    )
    assert assigned["assigned_investigator_officer_id"] == croft["id"]

    assert fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"])["open_case_load"] == 1
    assert fixtures.read_officer(api, croft["id"], world["cmdr_headers"])["open_case_load"] == 1

    carried, carried_meta = fixtures.rows(
        api.list_investigations(
            world["cmdr_headers"], {"assigned_investigator_officer_id": world["inv_a_id"]}
        )
    )
    assert carried_meta["total_count"] == 1
    assert [row["id"] for row in carried] == [investigation_a["id"]]

    accused, accused_meta = fixtures.rows(
        api.list_allegations(world["cmdr_headers"], {"subject_officer_id": world["inv_a_id"]})
    )
    assert accused_meta["total_count"] == 1
    assert [row["id"] for row in accused] == [allegation_b["id"]]

    against_subject, subject_meta = fixtures.rows(
        api.list_allegations(world["cmdr_headers"], {"subject_officer_id": world["subj_id"]})
    )
    assert subject_meta["total_count"] == 1
    assert [row["id"] for row in against_subject] == [allegation_a["id"]]
