"""
Error-code breadth: eleven 404s that must each name their own table, the single
duplicate-identifier code standing over two tables, the discharged-patient block
on a fresh order, the two temporal codes that guard one watch from opposite ends,
the incident-review pair of codes, the discontinuation-review prerequisite, the
one-live-feed-per-order rule, and the handoff state code reached from both of the
endpoints that can raise it.
"""

from test_helpers import (
    HTTP_CONFLICT,
    HTTP_CREATED,
    HTTP_NOT_FOUND,
    HTTP_UNPROCESSABLE,
    ObservationApiClient,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_fields,
    assert_row_count,
    exactly_one,
    final_segment_rows,
    rows_where,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    DOC_HANDOFF_DRAFTED,
    DOC_HANDOFF_SIGNED,
    DOC_PENDING,
    ENTRY_KIND_PROVISIONAL,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_COST_ENTRY_NOT_FOUND,
    ERR_DUPLICATE_ACTIVE_FEED,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_FEED_NOT_FOUND,
    ERR_HANDOFF_NOT_FOUND,
    ERR_INVALID_HANDOFF_STATE,
    ERR_INVALID_SHIFT_WINDOW,
    ERR_ORDER_NOT_FOUND,
    ERR_OUTSIDE_SHIFT_WINDOW,
    ERR_PATIENT_DISCHARGED,
    ERR_PATIENT_NOT_FOUND,
    ERR_REASSESSMENT_NOT_FOUND,
    ERR_REASSESSMENT_REQUIRED_BEFORE_REVIEW,
    ERR_REVIEW_FINDINGS_REQUIRED,
    ERR_SAFETY_EVENT_NOT_FOUND,
    ERR_STAFF_NOT_FOUND,
    ERR_STAFF_SUSPENDED,
    ERR_STATION_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    EVENT_CLOSED,
    EVENT_INCIDENT_REVIEW,
    FEED_ACTIVE,
    FEED_RELEASED,
    HANDOFF_DRAFTED,
    HANDOFF_SIGNED,
    INTERVENTION_BED_ALARM,
    INTERVENTION_VERBAL_REDIRECTION,
    KIND_FALL_WITH_INJURY,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    ORDER_ACTIVE,
    ORDER_DISCONTINUATION_REVIEW,
    ORDER_DISCONTINUED,
    PATIENT_ADMITTED,
    PATIENT_DISCHARGED,
    POOL_INTERNAL_FLOAT,
    RECOMMENDATION_DISCONTINUE,
    RELEASE_OBSERVER_RELEASE,
    RESOLUTION_CONTINUE_OBSERVATION,
    RISK_ELOPEMENT,
    RISK_FALL,
    STAFF_AVAILABLE,
    STAFF_ON_ASSIGNMENT,
    STAFF_SUSPENDED,
    STATION_ACTIVE_MONITORING,
    STATION_IDLE,
    SUSPENSION_INCIDENT_REVIEW_OPENED,
    UNIT_OPEN,
    VARIANT_ROLLING_EVENT_WEIGHTED,
    WATCH_ON_WATCH,
    WATCH_SCHEDULED,
)
from test_helpers.factories import (
    assignment_payload,
    close_event_payload,
    discontinuation_review_payload,
    feed_payload,
    handoff_payload,
    order_payload,
    patient_payload,
    reassessment_payload,
    unit_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    assignment_handoffs,
    make_assignment,
    make_feed,
    make_handoff,
    make_order,
    make_patient,
    make_safety_event,
    make_staff,
    make_station,
    make_unit,
    order_assignments,
    order_feeds,
    patient_orders,
    read_assignment,
    read_event,
    read_feed,
    read_handoff,
    read_order,
    read_patient,
    read_staff,
    read_station,
    read_unit,
    start_watch_at,
    unit_cost_entries,
    unit_head,
)
from test_helpers.test_users import (
    COORDINATOR,
    MANAGER,
    OFFICER_1,
    OFFICER_2,
    OFFICER_ONE,
    OFFICER_TWO,
    PROVIDER_1,
    PROVIDER_ONE,
    make_remote_observer_headers,
    make_sitter_headers,
)

CERT_VALID = "2027-01-01T00:00:00Z"


class TestNotFoundCodePerEntity:
    """Eleven entity tables sharing one 404 shape but not one 404 code."""

    def test_each_single_resource_read_names_its_own_entity_in_the_404(
        self, api: ObservationApiClient
    ) -> None:
        """
        On an empty database every one of the eleven single-resource reads resolves its
        path id against its own table and reports that table's own code, so no generic
        not-found code and no neighbouring entity's code may stand in for another's.

        PRD 2.5: "The first path segment whose identifier names no existing row terminates
        the request with the 404 belonging to that segment's entity type:
        `ERR_UNIT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_FEED_NOT_FOUND`, `ERR_HANDOFF_NOT_FOUND`, `ERR_SAFETY_EVENT_NOT_FOUND`,
        `ERR_REASSESSMENT_NOT_FOUND`, or `ERR_COST_ENTRY_NOT_FOUND`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."
        PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."
        PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/every_not_found_code_is_reachable_from_its_own_read
        """
        probes = (
            (api.get_unit, "11111111-1111-4111-8111-111111111111", ERR_UNIT_NOT_FOUND),
            (api.get_patient, "22222222-2222-4222-8222-222222222222", ERR_PATIENT_NOT_FOUND),
            (api.get_staff, "33333333-3333-4333-8333-333333333333", ERR_STAFF_NOT_FOUND),
            (api.get_order, "44444444-4444-4444-8444-444444444444", ERR_ORDER_NOT_FOUND),
            (
                api.get_assignment,
                "55555555-5555-4555-8555-555555555555",
                ERR_ASSIGNMENT_NOT_FOUND,
            ),
            (api.get_station, "66666666-6666-4666-8666-666666666666", ERR_STATION_NOT_FOUND),
            (api.get_feed, "77777777-7777-4777-8777-777777777777", ERR_FEED_NOT_FOUND),
            (api.get_handoff, "88888888-8888-4888-8888-888888888888", ERR_HANDOFF_NOT_FOUND),
            (
                api.get_safety_event,
                "99999999-9999-4999-8999-999999999999",
                ERR_SAFETY_EVENT_NOT_FOUND,
            ),
            (
                api.get_reassessment,
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                ERR_REASSESSMENT_NOT_FOUND,
            ),
            (
                api.get_cost_entry,
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                ERR_COST_ENTRY_NOT_FOUND,
            ),
        )
        for read, probe_id, expected_error_id in probes:
            response = read(probe_id, MANAGER)
            error = validate_error(response, expected_error_id, HTTP_NOT_FOUND)
            assert error["error_id"] == expected_error_id, (
                f"reading {probe_id} must report {expected_error_id}"
            )
            body = response.json()
            assert body["response_type"] == "error", (
                f"the rejection of {probe_id} must declare response_type error"
            )
            assert_envelope_meta(body)
            assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
                "an error envelope's meta carries only the two request identifiers, "
                f"got {sorted(body['meta'])}"
            )

        reported = [
            validate_error(read(probe_id, MANAGER), expected_error_id, HTTP_NOT_FOUND)[
                "error_id"
            ]
            for read, probe_id, expected_error_id in probes
        ]
        assert len(set(reported)) == len(probes), (
            f"the eleven reads must report eleven distinct codes, got {reported}"
        )


class TestDuplicateIdentifierAcrossTwoTables:
    """One conflict code guarding two different uniqueness scopes."""

    def test_a_repeated_unit_code_and_a_globally_repeated_mrn_are_both_conflicts(
        self, api: ObservationApiClient
    ) -> None:
        """
        The duplicate-identifier code fires for a second unit taking a live `unit_code`
        and for a second patient taking a live `mrn`, and the medical record number is
        unique across all patients rather than within one unit, so re-using it in a
        different unit is refused too — and none of the three losing writes leaves a row
        behind.

        PRD 3.1: "A `unit_code` already taken by another unit is rejected with
        `ERR_DUPLICATE_IDENTIFIER`."
        PRD 3.1: "Patients are admitted to a unit by the same `NurseManager`, who supplies
        the `unit_id` of the occupied unit, an `mrn` medical record number of 4 to 24
        characters that must be unique across all patients, a `full_name` of 1 to 120
        characters, and `age_years` as a whole number from 0 through 120 inclusive — a
        figure that later feeds the risk-score age adjustment."
        PRD 3.1: "An `mrn` already in use is rejected with `ERR_DUPLICATE_IDENTIFIER`."
        PRD 3.1: "A freshly registered unit opens in posture `OPEN` with `restriction_reason`
        null, an `observed_cost_to_date_cents` ledger head of 0, and an `open_order_count`
        of 0."
        PRD 3.1: "An admitted patient's `status` is `ADMITTED` and `discharged_at` is null."
        PRD 2.6: "Uniqueness of the unit code and the patient medical record number —
        `ERR_DUPLICATE_IDENTIFIER`."

        Design: Corner/errors/duplicate_unit_code_and_duplicate_mrn_are_distinct_conflicts
        """
        keeper = make_unit(
            api,
            unit_code="UNIT-C38",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtyeight",
        )
        neighbour = make_unit(
            api,
            unit_code="UNIT-C39",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Thirtynine",
        )
        first_patient = make_patient(
            api,
            keeper["id"],
            mrn="MRN-C3801",
            full_name="Duplicate Probe Patient",
            age_years=60,
        )

        validate_error(
            api.create_unit(
                unit_payload(
                    unit_code="UNIT-C38",
                    name="Impostor Unit",
                    observation_cost_budget_cents=100000,
                    video_monitoring_enabled=True,
                ),
                MANAGER,
            ),
            ERR_DUPLICATE_IDENTIFIER,
            HTTP_CONFLICT,
        )
        validate_error(
            api.create_patient(
                patient_payload(
                    keeper["id"],
                    mrn="MRN-C3801",
                    full_name="Impostor Patient Same Unit",
                    age_years=71,
                ),
                MANAGER,
            ),
            ERR_DUPLICATE_IDENTIFIER,
            HTTP_CONFLICT,
        )
        validate_error(
            api.create_patient(
                patient_payload(
                    neighbour["id"],
                    mrn="MRN-C3801",
                    full_name="Impostor Patient Other Unit",
                    age_years=71,
                ),
                MANAGER,
            ),
            ERR_DUPLICATE_IDENTIFIER,
            HTTP_CONFLICT,
        )

        unit_rows, unit_meta = validate_paginated(api.list_units(MANAGER))
        assert_row_count(unit_rows, 2, "units after the rejected registration")
        assert unit_meta["total_count"] == 2, (
            f"the impostor unit must not be counted, got {unit_meta['total_count']}"
        )
        assert_fields(
            exactly_one(unit_rows, id=keeper["id"]),
            label="UNIT-C38 after the rejected registration",
            unit_code="UNIT-C38",
            name="Corner Unit Thirtyeight",
            observation_cost_budget_cents=250000,
            video_monitoring_enabled=False,
            status=UNIT_OPEN,
            restriction_reason=None,
            observed_cost_to_date_cents=0,
            open_order_count=0,
        )

        keeper_rows, keeper_meta = validate_paginated(
            api.list_unit_patients(keeper["id"], MANAGER)
        )
        assert_row_count(keeper_rows, 1, "patients on UNIT-C38")
        assert keeper_meta["total_count"] == 1, "no impostor patient may be counted"
        assert_fields(
            exactly_one(keeper_rows, id=first_patient["id"]),
            label="the surviving patient",
            mrn="MRN-C3801",
            full_name="Duplicate Probe Patient",
            age_years=60,
            status=PATIENT_ADMITTED,
            discharged_at=None,
        )
        neighbour_rows, neighbour_meta = validate_paginated(
            api.list_unit_patients(neighbour["id"], MANAGER)
        )
        assert_row_count(neighbour_rows, 0, "patients on UNIT-C39")
        assert neighbour_meta["total_count"] == 0, (
            "the cross-unit mrn re-use must have admitted nobody"
        )


class TestDischargedPatientRefusesNewOrders:
    """The patient-scoped member of the state gate, reachable only from a fresh order."""

    def test_no_further_observation_order_can_be_written_against_a_discharged_patient(
        self, api: ObservationApiClient
    ) -> None:
        """
        Discharge terminates the episode the patient already had, so the only way left to
        reach the discharged-patient conflict is a brand-new order write — which is refused
        without admitting an order row, leaving the unit's derived open-order count and its
        version exactly where the discharge left them.

        PRD 3.2: "The patient must still be `ADMITTED`; writing an order against a
        discharged patient is rejected with `ERR_PATIENT_DISCHARGED`."
        PRD 3.9: "Discharging a patient advances that patient `ADMITTED → DISCHARGED` and
        stamps `discharged_at` from the logical clock; discharging a patient who is already
        `DISCHARGED` is rejected with `ERR_PATIENT_DISCHARGED`."
        PRD 3.9: "In the first hop, because the patient has left `ADMITTED`, every
        non-terminal observation order belonging to that patient — that is, every order in
        `ACTIVE`, `REASSESSMENT_DUE`, `ESCALATED` or `DISCONTINUATION_REVIEW` — transitions
        to `DISCONTINUED` with `discontinued_at` stamped, processed in ascending
        `created_at`."
        PRD 3.1: "The `open_order_count` field is a derived figure — the number of
        observation orders written for patients who occupy this unit whose own status is
        `ACTIVE`, `REASSESSMENT_DUE`, `ESCALATED` or `DISCONTINUATION_REVIEW` — and it is
        recomputed whenever a new order is written for one of the unit's patients, which is
        itself a mutation of the unit and therefore advances the unit's `version` by 1."
        PRD 2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the
        server must not fall back to real time before the first clock call arrives."

        Design: Corner/errors/a_discharged_patient_accepts_no_further_observation_order
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C40",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Forty",
        )
        patient = make_patient(
            api,
            unit["id"],
            mrn="MRN-C4001",
            full_name="Discharged Patient",
            age_years=60,
        )
        first_order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions before discharge",
        )
        validate_success(api.discharge_patient(patient["id"], MANAGER))
        unit_version_after_discharge = read_unit(api, unit["id"])["version"]

        validate_error(
            api.create_order(
                order_payload(
                    patient["id"],
                    PROVIDER_ONE,
                    risk_categories=[RISK_FALL, RISK_ELOPEMENT],
                    required_modality=MODALITY_ONE_TO_ONE_SITTER,
                    clinical_rationale="Attempt to reopen observation after discharge",
                ),
                PROVIDER_1,
            ),
            ERR_PATIENT_DISCHARGED,
            HTTP_CONFLICT,
        )

        assert_fields(
            read_patient(api, patient["id"]),
            label="the discharged patient",
            status=PATIENT_DISCHARGED,
            discharged_at=CLOCK_START,
        )
        assert_fields(
            read_order(api, first_order["id"]),
            label="the order swept up by the discharge",
            status=ORDER_DISCONTINUED,
        )
        orders = patient_orders(api, patient["id"])
        assert_row_count(orders, 1, "orders on the discharged patient")
        exactly_one(orders, id=first_order["id"])
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit after the rejected order write",
            open_order_count=0,
            version=unit_version_after_discharge,
        )


class TestShiftWindowVersusStartWindow:
    """Two temporal codes guarding one watch from opposite ends."""

    def test_the_declared_window_and_the_moment_of_arrival_carry_different_codes(
        self, api: ObservationApiClient
    ) -> None:
        """
        A window one minute over twelve hours and a zero-length window are both rejected as
        an unsound declared window, while the eight-hour window between them is scheduled;
        then the same watch refuses a sitter who arrives sixteen minutes early, admits one
        arriving exactly on the fifteen-minute grace, and refuses a second sitter standing
        exactly on `shift_end_at` because that bound is strict.

        PRD 3.4: "Separately, the window itself must be sane: `shift_end_at` must be
        strictly later than `shift_start_at`, and the window may span at most 720 whole
        minutes — twelve hours — with any violation rejected as `ERR_INVALID_SHIFT_WINDOW`."
        PRD 3.4: "The new assignment lands with `watch_status` at `SCHEDULED` and
        `documentation_status` at `PENDING`, with `scheduled_minutes` derived as the whole
        minutes between `shift_start_at` and `shift_end_at`, and with `final_cost_cents`,
        `current_segment_started_at`, `break_started_at`, `completion_reason` and
        `voided_at` all null and `watch_segment_count` and `watched_minutes` both 0."
        PRD 3.4: "It bills the entire scheduled window at the observer's base rate scaled by
        their pool: the observer's `hourly_rate_cents` is multiplied by `scheduled_minutes`
        divided by 60, and that product is multiplied by the pool multiplier — 1.00 for
        `INTERNAL_FLOAT`, 1.45 for `AGENCY`, and 0.00 for `VOLUNTEER`, whose labor is
        donated and therefore free."
        PRD 3.4: "The order's `version`, the unit's `version` and the observer's `version`
        each advance by 1."
        PRD 3.5: "The clock must be inside the permitted start window: at or after
        `shift_start_at` less the 15-minute early-start grace, and strictly before
        `shift_end_at`."
        PRD 3.5: "Arriving 20 minutes early, or arriving at or after the shift's own end
        instant, is rejected with `ERR_OUTSIDE_SHIFT_WINDOW`."
        PRD 3.5: "Starting the watch stamps `current_segment_started_at` with the logical
        clock, opening the first billable segment, and moves the observer `AVAILABLE →
        ON_ASSIGNMENT`; both rows advance their `version` by 1."

        Design: Corner/errors/shift_window_sanity_and_the_start_watch_grace_are_separate_codes
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C41",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortyone",
        )
        patient = make_patient(
            api,
            unit["id"],
            mrn="MRN-C4101",
            full_name="Window Probe Patient",
            age_years=60,
        )
        first_sitter = make_staff(
            api,
            unit["id"],
            full_name="Window Sitter One",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        second_sitter = make_staff(
            api,
            unit["id"],
            full_name="Window Sitter Two",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions, afternoon watch",
        )
        version_before_scheduling = order["version"]

        validate_error(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    first_sitter["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T20:01:00Z",
                    version_before_scheduling,
                ),
                COORDINATOR,
            ),
            ERR_INVALID_SHIFT_WINDOW,
            HTTP_UNPROCESSABLE,
        )
        validate_error(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    first_sitter["id"],
                    "2026-08-01T12:00:00Z",
                    "2026-08-01T12:00:00Z",
                    version_before_scheduling,
                ),
                COORDINATOR,
            ),
            ERR_INVALID_SHIFT_WINDOW,
            HTTP_UNPROCESSABLE,
        )

        first_watch = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    first_sitter["id"],
                    "2026-08-01T12:00:00Z",
                    "2026-08-01T20:00:00Z",
                    version_before_scheduling,
                ),
                COORDINATOR,
            ),
            HTTP_CREATED,
        )
        assert_fields(
            first_watch,
            label="the eight-hour watch",
            watch_status=WATCH_SCHEDULED,
            documentation_status=DOC_PENDING,
            scheduled_minutes=480,
            provisional_cost_cents=16000,
            final_cost_cents=None,
            current_segment_started_at=None,
            break_started_at=None,
            completion_reason=None,
            voided_at=None,
            watch_segment_count=0,
            watched_minutes=0,
        )
        version_after_scheduling = read_order(api, order["id"])["version"]
        assert version_after_scheduling == version_before_scheduling + 1, (
            "only the accepted schedule may advance the order, got "
            f"{version_after_scheduling} from {version_before_scheduling}"
        )

        second_watch = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    second_sitter["id"],
                    "2026-08-01T12:00:00Z",
                    "2026-08-01T20:00:00Z",
                    version_after_scheduling,
                ),
                COORDINATOR,
            ),
            HTTP_CREATED,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit carrying two provisional charges",
            observed_cost_to_date_cents=32000,
            status=UNIT_OPEN,
        )

        advance_clock(api, "2026-08-01T11:44:00Z")
        validate_error(
            api.start_watch(first_watch["id"], make_sitter_headers(first_sitter["id"])),
            ERR_OUTSIDE_SHIFT_WINDOW,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_assignment(api, first_watch["id"]),
            label="the watch a sitter reached for sixteen minutes early",
            watch_status=WATCH_SCHEDULED,
            current_segment_started_at=None,
        )
        assert_fields(
            read_staff(api, first_sitter["id"]),
            label="the sitter who arrived sixteen minutes early",
            status=STAFF_AVAILABLE,
        )

        advance_clock(api, "2026-08-01T11:45:00Z")
        started = validate_success(
            api.start_watch(first_watch["id"], make_sitter_headers(first_sitter["id"]))
        )
        assert_fields(
            started,
            label="the watch begun exactly on the grace boundary",
            watch_status=WATCH_ON_WATCH,
            current_segment_started_at="2026-08-01T11:45:00.000Z",
        )
        assert_fields(
            read_staff(api, first_sitter["id"]),
            label="the sitter who arrived exactly on the grace boundary",
            status=STAFF_ON_ASSIGNMENT,
        )

        advance_clock(api, "2026-08-01T20:00:00Z")
        validate_error(
            api.start_watch(second_watch["id"], make_sitter_headers(second_sitter["id"])),
            ERR_OUTSIDE_SHIFT_WINDOW,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_assignment(api, second_watch["id"]),
            label="the watch reached for exactly on its own end instant",
            watch_status=WATCH_SCHEDULED,
            current_segment_started_at=None,
        )
        assert_fields(
            read_staff(api, second_sitter["id"]),
            label="the sitter who arrived exactly on shift_end_at",
            status=STAFF_AVAILABLE,
        )

        entries = unit_cost_entries(api, unit["id"])
        assert_row_count(entries, 2, "ledger rows after two schedules and one start")
        assert_row_count(
            rows_where(entries, entry_kind=ENTRY_KIND_PROVISIONAL),
            2,
            "provisional rows",
        )
        assert_row_count(final_segment_rows(entries), 0, "final-segment rows")


class TestIncidentReviewSuspensionAndFindings:
    """The two codes that hang off the incident-review branch and nowhere else."""

    def test_the_review_suspends_the_sitter_and_refuses_a_close_without_findings(
        self, api: ObservationApiClient
    ) -> None:
        """
        Opening an incident review on an event that named a watch suspends the observer who
        was keeping it, and that suspension blocks a second watch on another order without
        writing anything; closing the same event needs findings, and the close that finally
        lands leaves the observer suspended because only recertification reinstates them.

        PRD 3.8: "A `SafetyOfficer` opens an incident review on a `FALL_WITH_INJURY` or
        `SELF_HARM_ATTEMPT` event instead, advancing `REPORTED → INCIDENT_REVIEW` and
        recording their own identity in `review_opened_by_user_id`."
        PRD 3.8: "Finally, and strictly **after** all four cascade hops, if the event named
        an `assignment_id` then the observer who was keeping that watch transitions to
        `SUSPENDED` with `suspension_reason` `INCIDENT_REVIEW_OPENED`."
        PRD 3.8: "Alongside the cascade the order's `elopement_risk_score` is recomputed
        under the rolling event-weighted reading, and `reassessment_interval_hours` is
        recomputed from the new score with `next_reassessment_due_at` reset to
        `last_reassessed_at` advanced by that interval — note that `last_reassessed_at`
        itself is not moved, because opening a review is not a reassessment."
        PRD 3.3: "It contributes 1.0 point for each safety event on the order whose
        `event_kind` is `ELOPEMENT_ATTEMPT` or `AGGRESSION` and whose `occurred_at` falls at
        or after the instant 24 hours before the current logical clock — the boundary is
        inclusive, so an attempt exactly 24 hours old still counts — plus 2.0 points for
        each safety event on the order whose `event_kind` is `FALL_WITH_INJURY` or
        `SELF_HARM_ATTEMPT`, counted over all time with no window at all."
        PRD 3.3: "Events are counted regardless of their own workflow `status`: an event
        that has already reached `CLOSED` still contributes its points."
        PRD 3.2: "The second derived figure is `reassessment_interval_hours`, which converts
        the score into a mandated reassessment cadence over four tiers, each boundary
        inclusive: a score of 8.0 or higher demands reassessment every 4 hours; a score
        below 8.0 but 6.0 or higher demands every 8 hours; a score below 6.0 but 3.0 or
        higher demands every 12 hours; and anything below 3.0 falls to the default of every
        24 hours."
        PRD 3.4: "The observer must not be `SUSPENDED`, or the request fails with
        `ERR_STAFF_SUSPENDED`."
        PRD 3.8: "On the incident-review branch `review_findings` is mandatory and must be
        non-empty, and its absence is rejected with `ERR_REVIEW_FINDINGS_REQUIRED`; on the
        escalation-response branch it is not required and is not recorded."
        PRD 3.8: "Closure stores the `resolution`, records the closer in `closed_by_user_id`,
        and stores `review_findings` on the incident-review branch only."
        PRD 3.1: "This operation carries a second, decisive effect: it is the **only** path
        out of `SUSPENDED`."

        Design: Corner/errors/incident_review_suspends_the_sitter_and_demands_findings_at_close
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C42",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortytwo",
        )
        watched_patient = make_patient(
            api, unit["id"], mrn="MRN-C4201", full_name="Incident Patient", age_years=60
        )
        other_patient = make_patient(
            api, unit["id"], mrn="MRN-C4202", full_name="Second Order Patient", age_years=60
        )
        sitter = make_staff(
            api,
            unit["id"],
            full_name="Incident Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        watched_order = make_order(
            api,
            watched_patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions, one-to-one",
        )
        other_order = make_order(
            api,
            other_patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Second order awaiting a sitter",
        )
        watch = make_assignment(
            api,
            watched_order["id"],
            sitter["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
            expected_order_version=watched_order["version"],
        )
        start_watch_at(api, watch["id"], sitter["id"], "2026-08-01T08:00:00Z")
        advance_clock(api, "2026-08-01T09:00:00Z")
        event = make_safety_event(
            api,
            watched_order["id"],
            KIND_FALL_WITH_INJURY,
            sitter["id"],
            narrative="Unwitnessed fall from bed with a scalp laceration",
            assignment_id=watch["id"],
        )
        opened = validate_success(api.open_incident_review(event["id"], OFFICER_1))
        assert_fields(
            opened,
            label="the event under incident review",
            status=EVENT_INCIDENT_REVIEW,
            review_opened_by_user_id=OFFICER_ONE,
            review_findings=None,
            closed_by_user_id=None,
            resolution=None,
        )
        assert_fields(
            read_staff(api, sitter["id"]),
            label="the sitter whose watch the event named",
            status=STAFF_SUSPENDED,
            suspension_reason=SUSPENSION_INCIDENT_REVIEW_OPENED,
        )
        assert_fields(
            read_order(api, watched_order["id"]),
            label="the order carrying an all-time fall with injury",
            status=ORDER_ACTIVE,
            elopement_risk_score=3.5,
            reassessment_interval_hours=12,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            last_reassessed_at=CLOCK_START,
            next_reassessment_due_at="2026-08-01T12:00:00.000Z",
        )

        validate_error(
            api.create_assignment(
                assignment_payload(
                    other_order["id"],
                    sitter["id"],
                    "2026-08-02T08:00:00Z",
                    "2026-08-02T16:00:00Z",
                    other_order["version"],
                ),
                COORDINATOR,
            ),
            ERR_STAFF_SUSPENDED,
            HTTP_UNPROCESSABLE,
        )
        assert_row_count(
            order_assignments(api, other_order["id"]),
            0,
            "watches on the second order",
        )
        assert_fields(
            read_order(api, other_order["id"]),
            label="the second order after the refused schedule",
            version=other_order["version"],
        )
        assert unit_head(api, unit["id"]) == 16000, (
            "the refused schedule must not bill the unit"
        )

        validate_error(
            api.close_safety_event(
                event["id"],
                close_event_payload(RESOLUTION_CONTINUE_OBSERVATION),
                OFFICER_2,
            ),
            ERR_REVIEW_FINDINGS_REQUIRED,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_event(api, event["id"]),
            label="the event after the findings-free close attempt",
            status=EVENT_INCIDENT_REVIEW,
            resolution=None,
            closed_by_user_id=None,
            review_findings=None,
        )

        closed = validate_success(
            api.close_safety_event(
                event["id"],
                close_event_payload(
                    RESOLUTION_CONTINUE_OBSERVATION,
                    review_findings="Bed alarm was disabled; sitter re-education ordered",
                ),
                OFFICER_2,
            )
        )
        assert_fields(
            closed,
            label="the closed incident review",
            status=EVENT_CLOSED,
            resolution=RESOLUTION_CONTINUE_OBSERVATION,
            closed_by_user_id=OFFICER_TWO,
            review_opened_by_user_id=OFFICER_ONE,
            review_findings="Bed alarm was disabled; sitter re-education ordered",
        )
        assert_fields(
            read_staff(api, sitter["id"]),
            label="the sitter after the close",
            status=STAFF_SUSPENDED,
            suspension_reason=SUSPENSION_INCIDENT_REVIEW_OPENED,
        )
        assert_fields(
            read_order(api, watched_order["id"]),
            label="the order after the close",
            status=ORDER_ACTIVE,
            elopement_risk_score=3.5,
            reassessment_interval_hours=12,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
        )
        assert_fields(
            read_assignment(api, watch["id"]),
            label="the watch that was in force",
            watch_status=WATCH_ON_WATCH,
            watch_segment_count=0,
            watched_minutes=0,
        )
        watch_entries = assignment_cost_entries(api, watch["id"])
        assert_row_count(watch_entries, 1, "ledger rows on the open watch")
        assert_row_count(final_segment_rows(watch_entries), 0, "final-segment rows")


class TestDiscontinuationReviewPrerequisite:
    """The review gate is a reassessment count, not the age of the order."""

    def test_the_review_needs_one_reassessment_and_is_then_immune_to_the_sweep(
        self, api: ObservationApiClient
    ) -> None:
        """
        A brand-new order cannot be walked straight into discontinuation: the review is
        refused while `reassessment_count` is 0 and the order is left untouched, the very
        same call succeeds once a single reassessment is on the record, and the order it
        produces then survives a clock advance well past due plus grace.

        PRD 3.9: "The order must already have been reassessed at least once — its
        `reassessment_count` must be 1 or greater — because a discontinuation judgement on
        an order that has never been revisited is a judgement on stale information; an order
        with a `reassessment_count` of 0 is rejected with
        `ERR_REASSESSMENT_REQUIRED_BEFORE_REVIEW`."
        PRD 3.9: "Opening the review advances `ACTIVE → DISCONTINUATION_REVIEW`, stores the
        submitted recommendation in `discontinuation_recommendation`, records the opening
        provider in `discontinuation_review_opened_by_user_id`, and advances the order's
        `version` by 1."
        PRD 3.9: "While the order sits in `DISCONTINUATION_REVIEW` it is immune to the clock
        reassessment sweep, so a review can be deliberated across clock advances without the
        order lapsing underneath it."
        PRD 3.3: "That record carries the `order_id` it belongs to, the acting provider's
        identity in `performed_by_user_id`, the `risk_categories_after` as submitted, the
        order's `elopement_risk_score` immediately before the reassessment in `score_before`,
        the score immediately after it in `score_after`, the resulting cadence in
        `interval_hours_after`, and the logical-clock instant of the reassessment in
        `reassessed_at`."
        PRD 3.3: "On the order itself, `risk_categories` is replaced by the submitted
        `risk_categories_after`, the score is recomputed under the rolling event-weighted
        reading described next with `risk_score_variant` set to `ROLLING_EVENT_WEIGHTED`,
        `reassessment_interval_hours` is recomputed from the new score, `last_reassessed_at`
        is stamped with the current logical clock, `next_reassessment_due_at` is set to that
        same instant advanced by the freshly computed interval, `reassessment_count` is
        increased by 1, and the order's `version` advances by 1."
        PRD 3.3: "Only orders in `ACTIVE` or `REASSESSMENT_DUE` are candidates — an order
        sitting in `ESCALATED` or `DISCONTINUATION_REVIEW` is immune to the sweep entirely,
        which is what makes an open discontinuation review safe from lapsing while it is
        being decided."
        PRD 3.3: "The clock response reports the instant now in force as `current_utc`,
        together with `orders_marked_reassessment_due` and `orders_lapsed` as counts of what
        the sweep did."
        PRD 3.2: "It is built by summing a weight for each risk category the order carries —
        a `FALL` criterion contributes 1.5 points, an `ELOPEMENT` criterion contributes 2.5
        points, and a `SELF_HARM` criterion contributes 3.0 points — then adding an age
        adjustment of 1.0 point when the patient's `age_years` is 75 or greater (a patient of
        exactly 75 receives the adjustment; a patient of 74 does not) and 0.0 points
        otherwise, then adding an event component described below."
        PRD 3.2: "The second derived figure is `reassessment_interval_hours`, which converts
        the score into a mandated reassessment cadence over four tiers, each boundary
        inclusive: a score of 8.0 or higher demands reassessment every 4 hours; a score below
        8.0 but 6.0 or higher demands every 8 hours; a score below 6.0 but 3.0 or higher
        demands every 12 hours; and anything below 3.0 falls to the default of every 24
        hours."

        Design: Corner/errors/discontinuation_review_needs_one_reassessment_on_the_record
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C43",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortythree",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C4301", full_name="Review Gate Patient", age_years=60
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Fall precautions pending review",
        )

        validate_error(
            api.open_discontinuation_review(
                order["id"],
                discontinuation_review_payload(RECOMMENDATION_DISCONTINUE),
                PROVIDER_1,
            ),
            ERR_REASSESSMENT_REQUIRED_BEFORE_REVIEW,
            HTTP_UNPROCESSABLE,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the never-reassessed order after the refused review",
            status=ORDER_ACTIVE,
            version=order["version"],
            reassessment_count=0,
            discontinuation_recommendation=None,
            discontinuation_review_opened_by_user_id=None,
        )

        record = validate_success(
            api.create_reassessment(
                order["id"], reassessment_payload([RISK_FALL]), PROVIDER_1
            ),
            HTTP_CREATED,
        )
        assert_fields(
            record,
            label="the first reassessment record",
            order_id=order["id"],
            performed_by_user_id=PROVIDER_ONE,
            risk_categories_after=[RISK_FALL],
            score_before=1.5,
            score_after=1.5,
            interval_hours_after=24,
            reassessed_at=CLOCK_START,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the order after its first reassessment",
            status=ORDER_ACTIVE,
            reassessment_count=1,
            elopement_risk_score=1.5,
            reassessment_interval_hours=24,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            last_reassessed_at=CLOCK_START,
            next_reassessment_due_at="2026-08-02T00:00:00.000Z",
        )

        review = validate_success(
            api.open_discontinuation_review(
                order["id"],
                discontinuation_review_payload(RECOMMENDATION_DISCONTINUE),
                PROVIDER_1,
            )
        )
        assert_fields(
            review,
            label="the opened discontinuation review",
            status=ORDER_DISCONTINUATION_REVIEW,
            discontinuation_recommendation=RECOMMENDATION_DISCONTINUE,
            discontinuation_review_opened_by_user_id=PROVIDER_ONE,
        )

        sweep = advance_clock(api, "2026-08-03T00:00:00Z")
        assert_fields(
            sweep,
            label="the sweep over an order under review",
            current_utc="2026-08-03T00:00:00.000Z",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the order after the sweep it is immune to",
            status=ORDER_DISCONTINUATION_REVIEW,
            next_reassessment_due_at="2026-08-02T00:00:00.000Z",
            lapsed_at=None,
        )


class TestOneLiveFeedPerOrder:
    """The duplicate-feed rule is scoped to the order, not to the console."""

    def test_a_second_console_is_refused_until_the_first_feed_is_released(
        self, api: ObservationApiClient
    ) -> None:
        """
        An empty console with spare span still cannot take a second live feed for an order
        that already has one, so the conflict is the duplicate-feed code and not the span
        limit; releasing the first feed frees the order and makes the identical admission
        legal, leaving one released and one active feed on the episode.

        PRD 3.7: "An order may carry at most one feed in `status` `ACTIVE` at a time, and a
        second concurrent feed on the same order is rejected with
        `ERR_DUPLICATE_ACTIVE_FEED`."
        PRD 3.7: "The feed is admitted when that total is less than or equal to the
        pre-candidate limit; the comparison is inclusive, so filling the console exactly to
        its limit is permitted."
        PRD 3.7: "Each feed freezes an `acuity_weight` at the moment it is admitted, computed
        from the risk categories of the order it serves: a `FALL` criterion contributes 1.0,
        an `ELOPEMENT` criterion contributes 2.0, and a `SELF_HARM` criterion contributes
        3.0, with the sum rounded half up to one decimal place."
        PRD 3.7: "From that weight a penalty is derived over inclusive thresholds: a weight
        of 6.0 or higher costs 2 slots, a weight below 6.0 but 4.0 or higher costs 1 slot,
        and anything below 4.0 costs nothing."
        PRD 3.7: "An admitted feed opens in `status` `ACTIVE` with `release_reason` and
        `released_at` null."
        PRD 3.7: "On the first admitted feed the console transitions `IDLE →
        ACTIVE_MONITORING` and its observer moves `AVAILABLE → ON_ASSIGNMENT`; an observer
        who is already `ON_ASSIGNMENT` simply stays there."
        PRD 3.7: "The observer releases a feed from the console when the patient no longer
        needs it, advancing `ACTIVE → RELEASED` with `release_reason` set to
        `OBSERVER_RELEASE` and `released_at` stamped from the logical clock."
        PRD 3.7: "The console recomputes `active_feed_count`, `active_acuity_weight` and
        `effective_span_limit`; when `active_feed_count` reaches 0 the console transitions
        `ACTIVE_MONITORING → IDLE`, with `active_acuity_weight` back at 0.0 and
        `effective_span_limit` back at the full `declared_max_span`, and its observer moves
        `ON_ASSIGNMENT → AVAILABLE`."

        Design: Corner/errors/an_order_may_hold_only_one_active_feed_across_all_consoles
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C44",
            budget_cents=250000,
            video_monitoring_enabled=True,
            name="Corner Unit Fortyfour",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C4401", full_name="Duplicate Feed Patient", age_years=60
        )
        observer = make_staff(
            api,
            unit["id"],
            full_name="Duplicate Feed Observer",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2200,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_VIDEO_MONITORING,
            clinical_rationale="Fall risk on continuous video observation",
        )
        first_console = make_station(
            api, observer["id"], station_label="CONSOLE-D44A", declared_max_span=3
        )
        second_console = make_station(
            api, observer["id"], station_label="CONSOLE-D44B", declared_max_span=2
        )
        first_feed = make_feed(
            api,
            first_console["id"],
            order["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
            observer["id"],
        )
        candidate = feed_payload(
            second_console["id"],
            order["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        observer_headers = make_remote_observer_headers(observer["id"])

        validate_error(
            api.create_feed(candidate, observer_headers),
            ERR_DUPLICATE_ACTIVE_FEED,
            HTTP_CONFLICT,
        )
        assert_fields(
            read_station(api, second_console["id"]),
            label="the empty second console after the refused admission",
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
            status=STATION_IDLE,
            version=second_console["version"],
        )

        released = validate_success(api.release_feed(first_feed["id"], observer_headers))
        assert_fields(
            released,
            label="the released feed",
            status=FEED_RELEASED,
            release_reason=RELEASE_OBSERVER_RELEASE,
            released_at=CLOCK_START,
        )
        assert_fields(
            read_station(api, first_console["id"]),
            label="the first console after the release",
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=3,
            status=STATION_IDLE,
        )
        assert_fields(
            read_staff(api, observer["id"]),
            label="the observer whose consoles are both idle",
            status=STAFF_AVAILABLE,
        )

        second_feed = validate_success(
            api.create_feed(candidate, observer_headers), HTTP_CREATED
        )
        assert_fields(
            second_feed,
            label="the feed admitted after the release",
            station_id=second_console["id"],
            order_id=order["id"],
            status=FEED_ACTIVE,
            acuity_weight=1.0,
            release_reason=None,
            released_at=None,
        )
        assert_fields(
            read_station(api, second_console["id"]),
            label="the second console now carrying the feed",
            active_feed_count=1,
            active_acuity_weight=1.0,
            effective_span_limit=2,
            status=STATION_ACTIVE_MONITORING,
        )
        assert_fields(
            read_staff(api, observer["id"]),
            label="the observer back on a live console",
            status=STAFF_ON_ASSIGNMENT,
        )
        feeds = order_feeds(api, order["id"])
        assert_row_count(feeds, 2, "feeds on the episode")
        exactly_one(feeds, id=first_feed["id"], status=FEED_RELEASED)
        exactly_one(feeds, id=second_feed["id"], status=FEED_ACTIVE)
        assert_fields(
            read_feed(api, first_feed["id"]),
            label="the first feed re-read",
            status=FEED_RELEASED,
            release_reason=RELEASE_OBSERVER_RELEASE,
        )


class TestHandoffStateIsSingleUse:
    """One conflict code reached from the draft endpoint and from the countersign endpoint."""

    def test_neither_the_draft_nor_the_countersignature_can_be_replayed(
        self, api: ObservationApiClient
    ) -> None:
        """
        A second draft against an outgoing watch whose documentation has already left
        `PENDING` is refused and creates no second record, the incoming sitter's
        countersignature carries the record to `SIGNED`, and replaying that countersignature
        is refused with the same code while the signature fields and the record's version
        stand still — and the paperwork never touches the watch dimension or the ledger.

        PRD 3.6: "The outgoing assignment's `documentation_status` must be `PENDING`; a
        second draft against an assignment already in `HANDOFF_DRAFTED` or `HANDOFF_SIGNED`
        is rejected with `ERR_INVALID_HANDOFF_STATE`."
        PRD 3.6: "The outgoing assignment's `watch_status` must be `ON_WATCH` or `ON_BREAK` —
        one cannot hand off a watch that has not started or has already ended."
        PRD 3.6: "A successful draft creates a handoff record whose `documentation_state` is
        `DRAFTED`, with `countersigned_by_staff_id` and `countersigned_at` both null, and
        moves the outgoing assignment `PENDING → HANDOFF_DRAFTED` while leaving its
        `watch_status` completely untouched; the assignment's `version` advances by 1."
        PRD 3.6: "The handoff record's `documentation_state` must still be `DRAFTED`;
        countersigning one already `SIGNED` is rejected with `ERR_INVALID_HANDOFF_STATE`."
        PRD 3.6: "Countersigning advances the record `DRAFTED → SIGNED`, records the
        countersigner in `countersigned_by_staff_id` and the moment in `countersigned_at`,
        and moves the outgoing assignment `HANDOFF_DRAFTED → HANDOFF_SIGNED` while again
        leaving its `watch_status` untouched."
        PRD 3.5: "Drafting or signing paperwork never moves the watch dimension, and starting
        or ending a break never moves the documentation dimension."
        PRD 3.4: "It bills the entire scheduled window at the observer's base rate scaled by
        their pool: the observer's `hourly_rate_cents` is multiplied by `scheduled_minutes`
        divided by 60, and that product is multiplied by the pool multiplier — 1.00 for
        `INTERNAL_FLOAT`, 1.45 for `AGENCY`, and 0.00 for `VOLUNTEER`, whose labor is donated
        and therefore free."

        Design: Corner/errors/handoff_documentation_cannot_be_drafted_twice_or_signed_twice
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C45",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortyfive",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C4501", full_name="Handoff State Patient", age_years=60
        )
        outgoing_sitter = make_staff(
            api,
            unit["id"],
            full_name="State Sitter Out",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        incoming_sitter = make_staff(
            api,
            unit["id"],
            full_name="State Sitter In",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            risk_categories=[RISK_FALL],
            clinical_rationale="Two-shift fall watch",
        )
        outgoing = make_assignment(
            api,
            order["id"],
            outgoing_sitter["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
            expected_order_version=order["version"],
        )
        incoming = make_assignment(
            api,
            order["id"],
            incoming_sitter["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-02T00:00:00Z",
            expected_order_version=read_order(api, order["id"])["version"],
        )
        start_watch_at(api, outgoing["id"], outgoing_sitter["id"], "2026-08-01T08:00:00Z")
        record = make_handoff(
            api,
            outgoing["id"],
            incoming["id"],
            outgoing_sitter["id"],
            behavior_summary="Restless but redirectable",
            interventions_used=[INTERVENTION_VERBAL_REDIRECTION, INTERVENTION_BED_ALARM],
        )
        assert_fields(
            record,
            label="the drafted handoff",
            outgoing_assignment_id=outgoing["id"],
            incoming_assignment_id=incoming["id"],
            documentation_state=HANDOFF_DRAFTED,
            behavior_summary="Restless but redirectable",
            interventions_used=[INTERVENTION_VERBAL_REDIRECTION, INTERVENTION_BED_ALARM],
            countersigned_by_staff_id=None,
            countersigned_at=None,
        )
        assert_fields(
            read_assignment(api, outgoing["id"]),
            label="the outgoing watch after the draft",
            documentation_status=DOC_HANDOFF_DRAFTED,
            watch_status=WATCH_ON_WATCH,
        )

        validate_error(
            api.create_handoff(
                handoff_payload(
                    outgoing["id"],
                    incoming["id"],
                    behavior_summary="Second draft attempt",
                    interventions_used=[INTERVENTION_VERBAL_REDIRECTION],
                ),
                make_sitter_headers(outgoing_sitter["id"]),
            ),
            ERR_INVALID_HANDOFF_STATE,
            HTTP_CONFLICT,
        )
        records = assignment_handoffs(api, outgoing["id"])
        assert_row_count(records, 1, "handoff records on the outgoing watch")
        assert_fields(
            exactly_one(records, id=record["id"]),
            label="the only handoff record",
            documentation_state=HANDOFF_DRAFTED,
        )

        signed = validate_success(
            api.countersign_handoff(record["id"], make_sitter_headers(incoming_sitter["id"]))
        )
        assert_fields(
            signed,
            label="the countersigned handoff",
            documentation_state=HANDOFF_SIGNED,
            countersigned_by_staff_id=incoming_sitter["id"],
            countersigned_at="2026-08-01T08:00:00.000Z",
        )
        assert_fields(
            read_assignment(api, outgoing["id"]),
            label="the outgoing watch after the countersignature",
            documentation_status=DOC_HANDOFF_SIGNED,
            watch_status=WATCH_ON_WATCH,
        )

        validate_error(
            api.countersign_handoff(record["id"], make_sitter_headers(incoming_sitter["id"])),
            ERR_INVALID_HANDOFF_STATE,
            HTTP_CONFLICT,
        )
        assert_fields(
            read_handoff(api, record["id"]),
            label="the handoff after the replayed countersignature",
            documentation_state=HANDOFF_SIGNED,
            countersigned_by_staff_id=incoming_sitter["id"],
            countersigned_at="2026-08-01T08:00:00.000Z",
            version=signed["version"],
        )
        assert unit_head(api, unit["id"]) == 32000, (
            "documentation must never touch the unit ledger head"
        )
