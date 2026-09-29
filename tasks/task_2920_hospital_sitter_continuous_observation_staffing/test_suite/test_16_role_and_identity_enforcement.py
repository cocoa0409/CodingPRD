"""
Role and identity enforcement: the partitioned write surface probed once for every
role that does not own the write, the two entity-backed roles confined to their own
`Staff` row, the empty identity header refused ahead of path resolution, and the
three segregation-of-duties seams — the provider who may not sign off on their own
order, the officer who may not close their own review, and the sitter who may not
countersign their own handoff.
"""

from test_helpers import (
    HTTP_CREATED,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_UNAUTHORIZED,
    ObservationApiClient,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_envelope_meta,
    assert_fields,
    assert_row_count,
    rows_where,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COMPETENCY_BASIC,
    COST_POSTED,
    DECISION_APPROVE,
    DOC_HANDOFF_DRAFTED,
    DOC_PENDING,
    ENTRY_KIND_PROVISIONAL,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STAFF_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    EVENT_CLOSED,
    EVENT_INCIDENT_REVIEW,
    FEED_ACTIVE,
    HANDOFF_DRAFTED,
    INTERVENTION_BED_ALARM,
    INTERVENTION_VERBAL_REDIRECTION,
    KIND_AGGRESSION,
    KIND_ELOPEMENT_ATTEMPT,
    KIND_FALL_WITH_INJURY,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    ORDER_ACTIVE,
    ORDER_DISCONTINUATION_REVIEW,
    ORDER_DISCONTINUED,
    POOL_AGENCY,
    POOL_INTERNAL_FLOAT,
    RECOMMENDATION_CONTINUE,
    RECOMMENDATION_DISCONTINUE,
    RESOLUTION_CONTINUE_OBSERVATION,
    RESOLUTION_STAFF_RETRAINING_REQUIRED,
    RISK_ELOPEMENT,
    RISK_FALL,
    ROLE_ATTENDING_PROVIDER,
    ROLE_SITTER,
    STAFF_AVAILABLE,
    STAFF_ON_ASSIGNMENT,
    STAFF_SUSPENDED,
    STATION_ACTIVE_MONITORING,
    STATION_IDLE,
    SUSPENSION_INCIDENT_REVIEW_OPENED,
    UNIT_OPEN,
    WATCH_ON_WATCH,
    WATCH_SCHEDULED,
)
from test_helpers.factories import (
    assignment_payload,
    clock_payload,
    close_event_payload,
    cost_close_payload,
    discontinuation_decision_payload,
    discontinuation_review_payload,
    escalate_response_payload,
    feed_payload,
    handoff_payload,
    order_payload,
    patient_payload,
    safety_event_payload,
    staff_payload,
    unit_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    make_assignment,
    make_handoff,
    make_order,
    make_patient,
    make_reassessment,
    make_safety_event,
    make_staff,
    make_station,
    make_unit,
    order_assignments,
    order_safety_events,
    read_assignment,
    read_event,
    read_feed,
    read_handoff,
    read_order,
    read_staff,
    read_station,
    read_unit,
    start_watch_at,
    unit_cost_entries,
)
from test_helpers.test_users import (
    ADMIN,
    COORDINATOR,
    MANAGER,
    MANAGER_ONE,
    OFFICER_1,
    OFFICER_2,
    OFFICER_ONE,
    OFFICER_TWO,
    PROVIDER_1,
    PROVIDER_2,
    PROVIDER_ONE,
    blank_user_id_headers,
    make_remote_observer_headers,
    make_sitter_headers,
)

CERT_VALID = "2027-01-01T00:00:00Z"


class TestExclusiveWriteSurface:
    """The write surface partitioned by professional function, probed role by role."""

    def test_twelve_well_formed_writes_are_each_refused_at_the_role_gate(
        self, api: ObservationApiClient
    ) -> None:
        """
        Twelve legal bodies, each sent under a role that does not hold that write, are
        all refused with `ERR_ROLE_NOT_PERMITTED` — including the inverse case, where the
        `SystemAdmin` who may exercise every other write is still refused a safety-event
        report. Four probes name path or body identifiers that exist nowhere, and the
        role gate answers ahead of them rather than surfacing a 404 or a shape error, so
        after all twelve refusals the database holds exactly what setup wrote and the
        logical clock has not moved off its startup instant.

        PRD 2.1: "A value of `X-User-Role` that is not one of those seven, or that is one
        of the seven but is not authorized for the endpoint being called, is rejected with
        `ERR_ROLE_NOT_PERMITTED`."
        PRD 2.1: "The seven roles divide the write surface by professional function."
        PRD 2.1: "An `AttendingProvider` writes observation orders, performs risk
        reassessments, opens the discontinuation review and renders the discontinuation
        decision."
        PRD 2.1: "A `NurseManager` registers nursing units, admits and discharges patients,
        and voids scheduled watches."
        PRD 2.1: "A `StaffingCoordinator` registers observation staff, records completed
        competency training, schedules watches, opens monitoring consoles, and closes the
        unit cost period."
        PRD 2.1: "A `Sitter` keeps a one-to-one watch, takes break relief, drafts and
        countersigns handoff documentation, and reports safety events."
        PRD 2.1: "A `RemoteObserver` admits and releases video feeds on a console, takes a
        console offline, and reports events seen on camera."
        PRD 2.1: "A `SafetyOfficer` records the escalation response, opens the incident
        review, and closes an event with a disposition."
        PRD 2.1: "A `SystemAdmin` drives the logical clock and may exercise every other
        write in the system **except** reporting a safety event, which is reserved to
        `Sitter` and `RemoteObserver` because the report must be attributable to a real
        observer."
        PRD 2.6: "They form a single ordered ladder, and the server evaluates them in
        ascending order and returns the **first** failure it reaches, so a request that
        violates several rules always surfaces the earliest one."
        PRD 2.6: "Role recognition and role authorization for the target endpoint —
        `ERR_ROLE_NOT_PERMITTED`."
        PRD 2.6: "Existence of path-segment resources, left to right — the corresponding
        404."
        PRD 2.6: "Existence of body foreign-key references, in the endpoint's declared field
        order — the corresponding 404."
        PRD 2.4: "A `SystemAdmin` moves the clock by supplying a `current_utc` instant; the
        new value must be greater than or equal to the current logical clock, and an attempt
        to rewind the clock is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/rbac/every_exclusive_write_rejects_the_roles_that_do_not_own_it
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C46",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortysix",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C4601", full_name="Rbac Patient", age_years=60
        )
        sitter = make_staff(
            api,
            unit["id"],
            full_name="Rbac Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Rbac probe order",
        )

        absent_assignment = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        absent_successor = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        absent_station = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        absent_event = "ffffffff-ffff-4fff-8fff-ffffffffffff"

        probes = (
            (
                "an observation order written by the NurseManager",
                lambda: api.create_order(
                    order_payload(
                        patient["id"],
                        MANAGER_ONE,
                        risk_categories=[RISK_FALL],
                        required_modality=MODALITY_ONE_TO_ONE_SITTER,
                        clinical_rationale="Nurse manager attempting to write an order",
                    ),
                    MANAGER,
                ),
            ),
            (
                "a nursing unit registered by the AttendingProvider",
                lambda: api.create_unit(
                    unit_payload(
                        unit_code="UNIT-C46X",
                        name="Provider Unit",
                        observation_cost_budget_cents=100000,
                        video_monitoring_enabled=False,
                    ),
                    PROVIDER_1,
                ),
            ),
            (
                "a patient admitted by the StaffingCoordinator",
                lambda: api.create_patient(
                    patient_payload(
                        unit["id"],
                        mrn="MRN-C4602",
                        full_name="Coordinator Admit",
                        age_years=60,
                    ),
                    COORDINATOR,
                ),
            ),
            (
                "an observer registered by the NurseManager",
                lambda: api.create_staff(
                    staff_payload(
                        unit["id"],
                        full_name="Manager Hire",
                        source_pool=POOL_AGENCY,
                        hourly_rate_cents=2500,
                        competency_level=COMPETENCY_BASIC,
                        deescalation_cert_expires_on=CERT_VALID,
                    ),
                    MANAGER,
                ),
            ),
            (
                "a watch scheduled by the NurseManager",
                lambda: api.create_assignment(
                    assignment_payload(
                        order["id"],
                        sitter["id"],
                        "2026-08-01T08:00:00Z",
                        "2026-08-01T16:00:00Z",
                        order["version"],
                    ),
                    MANAGER,
                ),
            ),
            (
                "a watch started by the StaffingCoordinator",
                lambda: api.start_watch(absent_assignment, COORDINATOR),
            ),
            (
                "handoff documentation drafted by the RemoteObserver",
                lambda: api.create_handoff(
                    handoff_payload(
                        absent_assignment,
                        absent_successor,
                        behavior_summary="Observer attempting sitter documentation",
                        interventions_used=[INTERVENTION_VERBAL_REDIRECTION],
                    ),
                    make_remote_observer_headers(sitter["id"]),
                ),
            ),
            (
                "a video feed admitted by the Sitter",
                lambda: api.create_feed(
                    feed_payload(
                        absent_station,
                        order["id"],
                        "2026-08-01T08:00:00Z",
                        "2026-08-01T16:00:00Z",
                    ),
                    make_sitter_headers(sitter["id"]),
                ),
            ),
            (
                "a safety event closed by the NurseManager",
                lambda: api.close_safety_event(
                    absent_event,
                    close_event_payload(RESOLUTION_CONTINUE_OBSERVATION),
                    MANAGER,
                ),
            ),
            (
                "the unit cost period closed by the NurseManager",
                lambda: api.cost_close(
                    unit["id"], cost_close_payload(CLOCK_START), MANAGER
                ),
            ),
            (
                "the logical clock driven by the AttendingProvider",
                lambda: api.set_clock(clock_payload("2026-08-01T06:00:00Z"), PROVIDER_1),
            ),
            (
                "a safety event reported by the SystemAdmin",
                lambda: api.create_safety_event(
                    safety_event_payload(
                        order["id"],
                        KIND_AGGRESSION,
                        narrative="SystemAdmin attempting to report an event",
                    ),
                    ADMIN,
                ),
            ),
        )
        assert len(probes) == 12, "one probe per forbidden write"

        for label, call in probes:
            refusal = validate_error(call(), ERR_ROLE_NOT_PERMITTED, HTTP_FORBIDDEN)
            assert refusal["error_id"] == ERR_ROLE_NOT_PERMITTED, label

        units, units_meta = validate_paginated(api.list_units(ADMIN))
        assert_row_count(units, 1, "units after the twelve refusals")
        assert units_meta["total_count"] == 1, "no unit was created by a provider"
        patients, patients_meta = validate_paginated(
            api.list_unit_patients(unit["id"], ADMIN)
        )
        assert_row_count(patients, 1, "patients on the probed unit")
        assert patients_meta["total_count"] == 1, "no patient was admitted by a coordinator"
        staff_rows, staff_meta = validate_paginated(api.list_unit_staff(unit["id"], ADMIN))
        assert_row_count(staff_rows, 1, "staff on the probed unit")
        assert staff_meta["total_count"] == 1, "no observer was registered by a manager"
        assert_row_count(
            order_assignments(api, order["id"]), 0, "watches on the probed order"
        )
        assert_row_count(
            order_safety_events(api, order["id"]), 0, "safety events on the probed order"
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the probed order",
            status=ORDER_ACTIVE,
            version=order["version"],
        )

        # The clock only ever moves forward, so a set to the startup instant that is
        # accepted proves the refused advance to 06:00 never landed.
        sweep = advance_clock(api, CLOCK_START)
        assert_fields(
            sweep,
            label="the clock after the refused clock write",
            current_utc=CLOCK_START,
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )


class TestEntityBackedOwnership:
    """`Sitter` and `RemoteObserver` identities measured against two different owners."""

    def test_a_wrong_owner_an_unknown_identity_and_the_rightful_owner_all_diverge(
        self, api: ObservationApiClient
    ) -> None:
        """
        The ownership comparison is per resource: a watch is owned through the
        assignment's `staff_id` and a feed through the console's `observer_staff_id`. A
        real but wrong `Staff` id is refused with `ERR_NOT_RESOURCE_OWNER` on both, an
        `X-User-ID` naming no `Staff` row at all is a 404 instead, and each rightful
        owner's byte-identical call then succeeds and moves both the operated resource
        and the observer's duty posture.

        PRD 2.1: "When `X-User-Role` is `Sitter`, `X-User-ID` is the `id` of the acting
        `Staff` row."
        PRD 2.1: "Ownership checks on any resource that references a `Staff` compare the
        resource's own staff reference to `X-User-ID`: for the watch operations (starting a
        watch, starting and ending break relief, completing a watch) the comparison is
        against the assignment's `staff_id`; for drafting a handoff it is against the
        outgoing assignment's `staff_id`; for countersigning a handoff it is against the
        incoming assignment's `staff_id`."
        PRD 2.1: "When `X-User-Role` is `RemoteObserver`, `X-User-ID` is likewise the `id`
        of the acting `Staff` row, and ownership checks compare it to the
        `observer_staff_id` of the `MonitoringStation` being operated (directly for console
        and feed-admission operations, and through the feed's `station_id` when a feed is
        released)."
        PRD 2.1: "A mismatch between an entity-backed caller's `X-User-ID` and the owning
        `Staff` reference is rejected with `ERR_NOT_RESOURCE_OWNER`."
        PRD 2.1: "An `X-User-ID` presented by a `Sitter` or `RemoteObserver` that names no
        `Staff` row at all is rejected with `ERR_STAFF_NOT_FOUND`."
        PRD 2.6: "Ownership for the entity-backed roles — `ERR_NOT_RESOURCE_OWNER`."
        PRD 3.5: "And the caller must be the assignment's own observer."
        PRD 3.5: "Starting the watch stamps `current_segment_started_at` with the logical
        clock, opening the first billable segment, and moves the observer `AVAILABLE →
        ON_ASSIGNMENT`; both rows advance their `version` by 1."
        PRD 3.7: "The caller must be the console's own observer."
        PRD 3.7: "Each feed freezes an `acuity_weight` at the moment it is admitted,
        computed from the risk categories of the order it serves: a `FALL` criterion
        contributes 1.0, an `ELOPEMENT` criterion contributes 2.0, and a `SELF_HARM`
        criterion contributes 3.0, with the sum rounded half up to one decimal place."
        PRD 3.7: "An admitted feed opens in `status` `ACTIVE` with `release_reason` and
        `released_at` null."
        PRD 3.7: "On the first admitted feed the console transitions `IDLE →
        ACTIVE_MONITORING` and its observer moves `AVAILABLE → ON_ASSIGNMENT`; an observer
        who is already `ON_ASSIGNMENT` simply stays there."

        Design: Corner/rbac/entity_backed_callers_are_confined_to_their_own_staff_row
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C47",
            budget_cents=250000,
            video_monitoring_enabled=True,
            name="Corner Unit Fortyseven",
        )
        bedside_patient = make_patient(
            api, unit["id"], mrn="MRN-C4701", full_name="Owner Patient One", age_years=60
        )
        video_patient = make_patient(
            api, unit["id"], mrn="MRN-C4702", full_name="Owner Patient Two", age_years=60
        )
        sitter_a = make_staff(
            api,
            unit["id"],
            full_name="Owner Sitter A",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        sitter_b = make_staff(
            api,
            unit["id"],
            full_name="Owner Sitter B",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        observer_one = make_staff(
            api,
            unit["id"],
            full_name="Owner Observer One",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2200,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        observer_two = make_staff(
            api,
            unit["id"],
            full_name="Owner Observer Two",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2200,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        bedside_order = make_order(
            api,
            bedside_patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="One-to-one fall watch",
        )
        video_order = make_order(
            api,
            video_patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_VIDEO_MONITORING,
            clinical_rationale="Video observation for fall risk",
        )
        watch = make_assignment(
            api,
            bedside_order["id"],
            sitter_a["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        console = make_station(
            api,
            observer_one["id"],
            station_label="CONSOLE-C47",
            declared_max_span=2,
        )
        advance_clock(api, "2026-08-01T08:00:00Z")

        # Probe 1: a real sitter who is not this watch's sitter.
        validate_error(
            api.start_watch(watch["id"], make_sitter_headers(sitter_b["id"])),
            ERR_NOT_RESOURCE_OWNER,
            HTTP_FORBIDDEN,
        )
        assert_fields(
            read_assignment(api, watch["id"]),
            label="the watch after the wrong sitter tried it",
            watch_status=WATCH_SCHEDULED,
            current_segment_started_at=None,
            version=watch["version"],
        )
        assert_fields(
            read_staff(api, sitter_b["id"]),
            label="the sitter who does not hold the watch",
            status=STAFF_AVAILABLE,
        )

        # Probe 2: an identity that names no Staff row at all.
        validate_error(
            api.start_watch(
                watch["id"],
                make_sitter_headers("aaaa1111-aaaa-4aaa-8aaa-aaaa11112222"),
            ),
            ERR_STAFF_NOT_FOUND,
            HTTP_NOT_FOUND,
        )
        assert_fields(
            read_assignment(api, watch["id"]),
            label="the watch after the unknown identity tried it",
            watch_status=WATCH_SCHEDULED,
            version=watch["version"],
        )

        # Probe 3: the rightful sitter, identical call.
        started = validate_success(
            api.start_watch(watch["id"], make_sitter_headers(sitter_a["id"]))
        )
        assert_fields(
            started,
            label="the watch started by its own sitter",
            watch_status=WATCH_ON_WATCH,
            current_segment_started_at="2026-08-01T08:00:00.000Z",
        )
        assert_fields(
            read_staff(api, sitter_a["id"]),
            label="the sitter who holds the watch",
            status=STAFF_ON_ASSIGNMENT,
        )

        # Probe 4: a real observer who does not staff this console.
        validate_error(
            api.create_feed(
                feed_payload(
                    console["id"],
                    video_order["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                ),
                make_remote_observer_headers(observer_two["id"]),
            ),
            ERR_NOT_RESOURCE_OWNER,
            HTTP_FORBIDDEN,
        )
        assert_fields(
            read_station(api, console["id"]),
            label="the console after the wrong observer tried it",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
            version=console["version"],
        )
        assert_fields(
            read_staff(api, observer_two["id"]),
            label="the observer who staffs no console",
            status=STAFF_AVAILABLE,
        )

        # Probe 5: the console's own observer, identical body.
        feed = validate_success(
            api.create_feed(
                feed_payload(
                    console["id"],
                    video_order["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                ),
                make_remote_observer_headers(observer_one["id"]),
            ),
            HTTP_CREATED,
        )
        assert_fields(
            feed,
            label="the feed admitted by the console's own observer",
            status=FEED_ACTIVE,
            acuity_weight=1.0,
            release_reason=None,
            released_at=None,
        )
        assert_fields(
            read_feed(api, feed["id"]),
            label="the re-read feed",
            status=FEED_ACTIVE,
            acuity_weight=1.0,
        )
        assert_fields(
            read_station(api, console["id"]),
            label="the console carrying its first feed",
            status=STATION_ACTIVE_MONITORING,
            active_feed_count=1,
            active_acuity_weight=1.0,
            effective_span_limit=2,
        )
        assert_fields(
            read_staff(api, observer_one["id"]),
            label="the console's own observer",
            status=STAFF_ON_ASSIGNMENT,
        )


class TestEmptyIdentityHeader:
    """The outermost rung: an empty `X-User-ID` answered before anything is resolved."""

    def test_an_empty_identity_header_is_refused_before_the_path_is_resolved(
        self, api: ObservationApiClient
    ) -> None:
        """
        Against an empty database, two writes whose path identifiers name nothing — one on
        an entity-backed role, one on an opaque role — are both refused with
        `ERR_UNAUTHENTICATED`, so neither the 404 for the missing path segment nor the
        404 for a `Staff` row that does not exist ever surfaces, and both refusals are
        still shaped like every other error in the API.

        PRD 2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
        user, and `X-User-Role`, declaring the capacity in which they act."
        PRD 2.1: "Both headers must be present and non-empty; a header supplied as an empty
        string counts as absent, and either condition is rejected with `ERR_UNAUTHENTICATED`."
        PRD 2.6: "Header presence — `ERR_UNAUTHENTICATED`."
        PRD 2.6: "Existence of path-segment resources, left to right — the corresponding
        404."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
        specific error."
        PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/rbac/an_empty_identity_header_is_refused_before_the_path_is_resolved
        """
        probes = (
            (
                "a sitter starting a watch that does not exist",
                api.start_watch(
                    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    blank_user_id_headers(ROLE_SITTER),
                ),
            ),
            (
                "a provider opening a review on an order that does not exist",
                api.open_discontinuation_review(
                    "44444444-4444-4444-8444-444444444444",
                    discontinuation_review_payload(RECOMMENDATION_CONTINUE),
                    blank_user_id_headers(ROLE_ATTENDING_PROVIDER),
                ),
            ),
        )
        for label, response in probes:
            refusal = validate_error(response, ERR_UNAUTHENTICATED, HTTP_UNAUTHORIZED)
            assert refusal["error_id"] == ERR_UNAUTHENTICATED, label
            body = response.json()
            assert body["response_type"] == "error", label
            assert_envelope_meta(body)
            assert set(body["meta"]) == {
                "api_request_id",
                "api_request_timestamp",
            }, label


class TestProviderSegregationOfDuties:
    """Two provider identities to end an order: one recommends, another decides."""

    def test_the_ordering_provider_may_not_render_the_discontinuation_decision(
        self, api: ObservationApiClient
    ) -> None:
        """
        The provider who wrote the order may legally reassess it and open its
        discontinuation review, but the decision compares the deciding `X-User-ID` against
        `ordering_provider_user_id` and refuses the match with `ERR_SEGREGATION_OF_DUTIES`,
        leaving the order parked in `DISCONTINUATION_REVIEW` so that a second provider can
        complete the identical call and terminate it.

        PRD 2.1: "The `AttendingProvider` who renders a discontinuation decision must
        present an `X-User-ID` different from the order's `ordering_provider_user_id`, so
        two distinct provider identities are always required to terminate an order through
        review."
        PRD 2.6: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.9: "Opening the review advances `ACTIVE → DISCONTINUATION_REVIEW`, stores the
        submitted recommendation in `discontinuation_recommendation`, records the opening
        provider in `discontinuation_review_opened_by_user_id`, and advances the order's
        `version` by 1."
        PRD 3.9: "A second `AttendingProvider` then renders the decision, submitting a
        `decision` of `APPROVE` or `REJECT` and, optionally, a free-text `rationale`."
        PRD 3.9: "The order must be in `DISCONTINUATION_REVIEW`, and in both branches the
        deciding `X-User-ID` must differ from the order's `ordering_provider_user_id` — the
        provider who wrote the order may never be the one who signs off on ending it, and an
        attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.9: "Clearing that gate advances the order `DISCONTINUATION_REVIEW →
        DISCONTINUED` and stamps `discontinued_at` from the logical clock, then cascades over
        everything the order was consuming."
        PRD 3.1: "The `open_order_count` field is a derived figure — the number of
        observation orders written for patients who occupy this unit whose own status is
        `ACTIVE`, `REASSESSMENT_DUE`, `ESCALATED` or `DISCONTINUATION_REVIEW` — and it is
        recomputed whenever a new order is written for one of the unit's patients, which is
        itself a mutation of the unit and therefore advances the unit's `version` by 1."

        Design: Corner/rbac/the_ordering_provider_may_not_render_the_discontinuation_decision
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C48",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortyeight",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C4801", full_name="Sod Patient", age_years=60
        )
        order = make_order(
            api,
            patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Fall precautions, likely short-lived",
        )
        make_reassessment(api, order["id"], [RISK_FALL], provider_headers=PROVIDER_1)
        opened = validate_success(
            api.open_discontinuation_review(
                order["id"],
                discontinuation_review_payload(RECOMMENDATION_DISCONTINUE),
                PROVIDER_1,
            )
        )
        assert_fields(
            opened,
            label="the review opened by the ordering provider",
            status=ORDER_DISCONTINUATION_REVIEW,
            discontinuation_review_opened_by_user_id=PROVIDER_ONE,
            discontinuation_recommendation=RECOMMENDATION_DISCONTINUE,
            discontinued_at=None,
        )
        version_in_review = opened["version"]

        validate_error(
            api.decide_discontinuation(
                order["id"],
                discontinuation_decision_payload(
                    DECISION_APPROVE,
                    rationale="Ordering provider attempting to close their own order",
                ),
                PROVIDER_1,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            HTTP_FORBIDDEN,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the order after its own provider tried to decide",
            status=ORDER_DISCONTINUATION_REVIEW,
            discontinued_at=None,
            version=version_in_review,
        )

        decided = validate_success(
            api.decide_discontinuation(
                order["id"],
                discontinuation_decision_payload(
                    DECISION_APPROVE, rationale="Second provider concurs, risk resolved"
                ),
                PROVIDER_2,
            )
        )
        assert_fields(
            decided,
            label="the order decided by a second provider",
            status=ORDER_DISCONTINUED,
            discontinued_at=CLOCK_START,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit once the order is terminated",
            open_order_count=0,
            observed_cost_to_date_cents=0,
            status=UNIT_OPEN,
        )


class TestOfficerSegregationOfDuties:
    """The closer-versus-opener comparison, which only one of the two branches arms."""

    def test_an_incident_review_may_not_be_closed_by_the_officer_who_opened_it(
        self, api: ObservationApiClient
    ) -> None:
        """
        One officer opens an incident review on a bedside fall and records the escalation
        response on a separate elopement attempt, and the same officer identity is then
        refused the first closure and granted the second: the comparison is against
        `review_opened_by_user_id`, which only the incident-review branch ever populates.
        A second officer completes the refused closure, and the escalated order comes back
        to `ACTIVE` with the score and cadence the rolling reading gives it.

        PRD 2.1: "The `SafetyOfficer` who closes a safety event must present an `X-User-ID`
        different from that event's `review_opened_by_user_id`; on the escalation-response
        branch that field is null and the check therefore passes vacuously."
        PRD 2.6: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.8: "An `ELOPEMENT_ATTEMPT` or an `AGGRESSION` report drives the order `ACTIVE →
        ESCALATED`, or `REASSESSMENT_DUE → ESCALATED` when the order was already overdue;
        either way the order's `version` advances by 1."
        PRD 3.8: "This branch is deliberately inert: `review_opened_by_user_id` stays null —
        which is what makes the segregation-of-duties check at close time vacuous on this
        branch — and no field of the order, of any feed, of any console or of any observer is
        mutated."
        PRD 3.8: "A `SafetyOfficer` opens an incident review on a `FALL_WITH_INJURY` or
        `SELF_HARM_ATTEMPT` event instead, advancing `REPORTED → INCIDENT_REVIEW` and
        recording their own identity in `review_opened_by_user_id`."
        PRD 3.8: "First, the order's `required_modality` is forced to `ONE_TO_ONE_SITTER` — a
        no-op when it is already that."
        PRD 3.8: "Finally, and strictly **after** all four cascade hops, if the event named an
        `assignment_id` then the observer who was keeping that watch transitions to
        `SUSPENDED` with `suspension_reason` `INCIDENT_REVIEW_OPENED`."
        PRD 3.8: "The closer's `X-User-ID` must differ from `review_opened_by_user_id`, so an
        incident review always takes two distinct officers; on the escalation-response branch
        that field is null and the comparison passes with nothing to compare."
        PRD 3.8: "Closure stores the `resolution`, records the closer in `closed_by_user_id`,
        and stores `review_findings` on the incident-review branch only."
        PRD 3.8: "If the owning order is `ESCALATED` and no other safety event on that order
        remains in any status other than `CLOSED`, the order transitions `ESCALATED → ACTIVE`
        — the last open event is what un-escalates the order, so an order with two open events
        stays escalated until the second one closes."
        PRD 3.8: "The order's `elopement_risk_score` is recomputed under the rolling
        event-weighted reading, and `reassessment_interval_hours` and `next_reassessment_due_at`
        follow from it, with `next_reassessment_due_at` set to `last_reassessed_at` advanced by
        the new interval; a close never moves `last_reassessed_at`, so closing an event cannot
        postpone an overdue reassessment."
        PRD 3.2: "It is built by summing a weight for each risk category the order carries — a
        `FALL` criterion contributes 1.5 points, an `ELOPEMENT` criterion contributes 2.5
        points, and a `SELF_HARM` criterion contributes 3.0 points — then adding an age
        adjustment of 1.0 point when the patient's `age_years` is 75 or greater (a patient of
        exactly 75 receives the adjustment; a patient of 74 does not) and 0.0 points otherwise,
        then adding an event component described below."
        PRD 3.3: "It contributes 1.0 point for each safety event on the order whose
        `event_kind` is `ELOPEMENT_ATTEMPT` or `AGGRESSION` and whose `occurred_at` falls at or
        after the instant 24 hours before the current logical clock — the boundary is
        inclusive, so an attempt exactly 24 hours old still counts — plus 2.0 points for each
        safety event on the order whose `event_kind` is `FALL_WITH_INJURY` or
        `SELF_HARM_ATTEMPT`, counted over all time with no window at all."
        PRD 3.2: "The second derived figure is `reassessment_interval_hours`, which converts
        the score into a mandated reassessment cadence over four tiers, each boundary
        inclusive: a score of 8.0 or higher demands reassessment every 4 hours; a score below
        8.0 but 6.0 or higher demands every 8 hours; a score below 6.0 but 3.0 or higher
        demands every 12 hours; and anything below 3.0 falls to the default of every 24 hours."

        Design: Corner/rbac/an_incident_review_may_not_be_closed_by_the_officer_who_opened_it
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C49",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fortynine",
        )
        patient_a = make_patient(
            api, unit["id"], mrn="MRN-C4901", full_name="Officer Patient A", age_years=60
        )
        patient_b = make_patient(
            api, unit["id"], mrn="MRN-C4902", full_name="Officer Patient B", age_years=60
        )
        sitter_a = make_staff(
            api,
            unit["id"],
            full_name="Officer Sitter A",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        sitter_b = make_staff(
            api,
            unit["id"],
            full_name="Officer Sitter B",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order_a = make_order(
            api,
            patient_a["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Fall precautions under one-to-one watch",
        )
        order_b = make_order(
            api,
            patient_b["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_ELOPEMENT],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Elopement risk, awaiting a sitter",
        )
        watch = make_assignment(
            api,
            order_a["id"],
            sitter_a["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        start_watch_at(api, watch["id"], sitter_a["id"], "2026-08-01T08:00:00Z")
        advance_clock(api, "2026-08-01T09:00:00Z")

        bedside_event = make_safety_event(
            api,
            order_a["id"],
            KIND_FALL_WITH_INJURY,
            sitter_a["id"],
            narrative="Fall from chair with a wrist fracture",
            assignment_id=watch["id"],
        )
        reviewed = validate_success(
            api.open_incident_review(bedside_event["id"], OFFICER_1)
        )
        assert_fields(
            reviewed,
            label="the event under incident review",
            status=EVENT_INCIDENT_REVIEW,
            review_opened_by_user_id=OFFICER_ONE,
            resolution=None,
            closed_by_user_id=None,
            review_findings=None,
        )

        camera_event = make_safety_event(
            api,
            order_b["id"],
            KIND_ELOPEMENT_ATTEMPT,
            sitter_b["id"],
            narrative="Found at the stairwell door",
        )
        escalated = validate_success(
            api.escalate_response(
                camera_event["id"],
                escalate_response_payload(["VERBAL_REDIRECTION", "SECURITY_NOTIFIED"]),
                OFFICER_1,
            )
        )
        assert_fields(
            escalated,
            label="the escalation-response event",
            review_opened_by_user_id=None,
            response_actions=["VERBAL_REDIRECTION", "SECURITY_NOTIFIED"],
        )

        # Probe 1: the officer who opened the review may not close it.
        validate_error(
            api.close_safety_event(
                bedside_event["id"],
                close_event_payload(
                    RESOLUTION_STAFF_RETRAINING_REQUIRED,
                    review_findings="Bed alarm not enabled at shift start",
                ),
                OFFICER_1,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            HTTP_FORBIDDEN,
        )
        assert_fields(
            read_event(api, bedside_event["id"]),
            label="the reviewed event after its own opener tried to close it",
            status=EVENT_INCIDENT_REVIEW,
            resolution=None,
            closed_by_user_id=None,
            review_findings=None,
            version=reviewed["version"],
        )

        # Probe 2: a second officer closes the identical call.
        closed = validate_success(
            api.close_safety_event(
                bedside_event["id"],
                close_event_payload(
                    RESOLUTION_STAFF_RETRAINING_REQUIRED,
                    review_findings="Bed alarm not enabled at shift start",
                ),
                OFFICER_2,
            )
        )
        assert_fields(
            closed,
            label="the reviewed event closed by a second officer",
            status=EVENT_CLOSED,
            closed_by_user_id=OFFICER_TWO,
            review_opened_by_user_id=OFFICER_ONE,
            resolution=RESOLUTION_STAFF_RETRAINING_REQUIRED,
            review_findings="Bed alarm not enabled at shift start",
        )

        # Probe 3: the same officer closes the escalation-response event vacuously.
        vacuous = validate_success(
            api.close_safety_event(
                camera_event["id"],
                close_event_payload(RESOLUTION_CONTINUE_OBSERVATION),
                OFFICER_1,
            )
        )
        assert_fields(
            vacuous,
            label="the escalation-response event closed by its own responder",
            status=EVENT_CLOSED,
            closed_by_user_id=OFFICER_ONE,
            review_opened_by_user_id=None,
            resolution=RESOLUTION_CONTINUE_OBSERVATION,
            review_findings=None,
        )

        assert_fields(
            read_order(api, order_b["id"]),
            label="the order un-escalated by its last open event closing",
            status=ORDER_ACTIVE,
            elopement_risk_score=3.5,
            reassessment_interval_hours=12,
        )
        assert_fields(
            read_order(api, order_a["id"]),
            label="the order carrying an all-time fall with injury",
            elopement_risk_score=3.5,
            reassessment_interval_hours=12,
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
        )
        assert_fields(
            read_staff(api, sitter_a["id"]),
            label="the sitter whose watch the reviewed event named",
            status=STAFF_SUSPENDED,
            suspension_reason=SUSPENSION_INCIDENT_REVIEW_OPENED,
        )
        assert_fields(
            read_staff(api, sitter_b["id"]),
            label="the sitter who merely reported an event",
            status=STAFF_AVAILABLE,
            suspension_reason=None,
        )


class TestHandoffSegregationOfDuties:
    """The countersignature's two stacked gates, reached in the only order that shows both."""

    def test_a_sitter_holding_both_watches_cannot_countersign_their_own_handoff(
        self, api: ObservationApiClient
    ) -> None:
        """
        One sitter holds two consecutive watches on the same order, exactly the mandatory
        480 minutes apart, and drafts the handoff from the first into the second. Because
        that sitter is the incoming assignment's own staff the ownership gate passes and the
        segregation gate refuses them; a third sitter who owns neither side is refused by the
        ownership gate instead, which pins the order of the two checks. Neither refusal moves
        the record, the outgoing watch's paperwork or the unit's ledger head, which still
        holds one provisional charge for each of the three scheduled watches.

        PRD 2.1: "A mismatch between an entity-backed caller's `X-User-ID` and the owning
        `Staff` reference is rejected with `ERR_NOT_RESOURCE_OWNER`."
        PRD 2.1: "The `Sitter` who countersigns a handoff must be a different `Staff` from the
        outgoing assignment's `staff_id`."
        PRD 2.6: "Ownership for the entity-backed roles — `ERR_NOT_RESOURCE_OWNER`."
        PRD 2.6: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`."
        PRD 3.4: "The rest-buffer comparison is inclusive in the observer's favour: a gap of
        exactly 480 minutes passes."
        PRD 3.4: "It bills the entire scheduled window at the observer's base rate scaled by
        their pool: the observer's `hourly_rate_cents` is multiplied by `scheduled_minutes`
        divided by 60, and that product is multiplied by the pool multiplier — 1.00 for
        `INTERNAL_FLOAT`, 1.45 for `AGENCY`, and 0.00 for `VOLUNTEER`, whose labor is donated
        and therefore free."
        PRD 3.6: "The outgoing assignment's `watch_status` must be `ON_WATCH` or `ON_BREAK` —
        one cannot hand off a watch that has not started or has already ended."
        PRD 3.6: "A successful draft creates a handoff record whose `documentation_state` is
        `DRAFTED`, with `countersigned_by_staff_id` and `countersigned_at` both null, and moves
        the outgoing assignment `PENDING → HANDOFF_DRAFTED` while leaving its `watch_status`
        completely untouched; the assignment's `version` advances by 1."
        PRD 3.6: "Countersignature closes the loop and is performed by the **incoming**
        sitter."
        PRD 3.6: "The caller's `X-User-ID` must equal the incoming assignment's `staff_id`, and
        — this is the documentation leg of segregation of duties — the incoming assignment's
        observer must be a different `Staff` from the outgoing assignment's observer, so a
        sitter can never sign off on their own report; a violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD 2.10: "A unit's `observed_cost_to_date_cents` is the sum of `amount_cents` across
        every `CostEntry` whose `unit_id` is that unit and whose `status` is `POSTED`."

        Design: Corner/rbac/a_sitter_holding_both_watches_cannot_countersign_their_own_handoff
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C50",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fifty",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C5001", full_name="Self Sign Patient", age_years=60
        )
        double_shift = make_staff(
            api,
            unit["id"],
            full_name="Double Shift Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        third_shift = make_staff(
            api,
            unit["id"],
            full_name="Third Shift Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Continuous fall watch across three shifts",
        )
        outgoing = make_assignment(
            api,
            order["id"],
            double_shift["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        incoming = make_assignment(
            api,
            order["id"],
            double_shift["id"],
            "2026-08-02T00:00:00Z",
            "2026-08-02T08:00:00Z",
        )
        make_assignment(
            api,
            order["id"],
            third_shift["id"],
            "2026-08-02T08:00:00Z",
            "2026-08-02T16:00:00Z",
        )
        start_watch_at(api, outgoing["id"], double_shift["id"], "2026-08-01T08:00:00Z")

        handoff = make_handoff(
            api,
            outgoing["id"],
            incoming["id"],
            double_shift["id"],
            behavior_summary="Slept most of the shift",
            interventions_used=[INTERVENTION_BED_ALARM],
        )
        assert_fields(
            handoff,
            label="the drafted handoff",
            documentation_state=HANDOFF_DRAFTED,
            countersigned_by_staff_id=None,
            countersigned_at=None,
        )

        # Probe 1: the sitter who owns both sides passes ownership and fails segregation.
        validate_error(
            api.countersign_handoff(
                handoff["id"], make_sitter_headers(double_shift["id"])
            ),
            ERR_SEGREGATION_OF_DUTIES,
            HTTP_FORBIDDEN,
        )

        # Probe 2: a sitter who owns neither side never reaches the segregation check.
        validate_error(
            api.countersign_handoff(
                handoff["id"], make_sitter_headers(third_shift["id"])
            ),
            ERR_NOT_RESOURCE_OWNER,
            HTTP_FORBIDDEN,
        )

        assert_fields(
            read_handoff(api, handoff["id"]),
            label="the handoff after both refusals",
            documentation_state=HANDOFF_DRAFTED,
            countersigned_by_staff_id=None,
            countersigned_at=None,
            version=handoff["version"],
        )
        assert_fields(
            read_assignment(api, outgoing["id"]),
            label="the outgoing watch after both refusals",
            documentation_status=DOC_HANDOFF_DRAFTED,
            watch_status=WATCH_ON_WATCH,
        )
        assert_fields(
            read_assignment(api, incoming["id"]),
            label="the incoming watch after both refusals",
            documentation_status=DOC_PENDING,
            watch_status=WATCH_SCHEDULED,
        )

        entries = unit_cost_entries(api, unit["id"])
        assert_row_count(entries, 3, "ledger rows for three scheduled watches")
        provisionals = rows_where(
            entries, entry_kind=ENTRY_KIND_PROVISIONAL, status=COST_POSTED
        )
        assert_row_count(provisionals, 3, "posted provisional rows")
        for row in provisionals:
            assert row["amount_cents"] == 16000, "eight hours at 2000 cents an hour"
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit holding three provisional charges",
            observed_cost_to_date_cents=48000,
            status=UNIT_OPEN,
            restriction_reason=None,
        )
