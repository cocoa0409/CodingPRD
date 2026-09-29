"""
The generic objections: one 404 per collection, one 401, one 400, and the 409s.

Nothing here is about business arithmetic. These tests check that the service keeps a
separate identifier for each thing that can be missing, refuses an unauthenticated write
before it looks at anything else, catches malformed payloads ahead of the business rule
they would otherwise trip, and gives each entity its own state objection.
"""

from test_helpers import (
    AHJ_HEADERS,
    REBATE_ADMIN_HEADERS,
    UTILITY_REVIEWER_HEADERS,
    WARRANTY_AGENT_HEADERS,
    AlertSeverity,
    AlertStatus,
    ApiErrorId,
    ApplicationStatus,
    ClaimStatus,
    EventStatus,
    PermitStatus,
    TestType,
    UserRole,
    WarrantyStatus,
    assert_program_ledger,
    assert_quantity,
    build_user_headers,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

# Twelve identifiers that resolve to nothing, one per collection, so that a service which
# answered every probe from the same lookup could not accidentally look right.
MISSING_INSTALLER = "11111111-1111-1111-1111-111111111111"
MISSING_SITE = "22222222-2222-2222-2222-222222222222"
MISSING_LOAD_CALCULATION = "33333333-3333-3333-3333-333333333333"
MISSING_PERMIT = "44444444-4444-4444-4444-444444444444"
MISSING_TEST = "55555555-5555-5555-5555-555555555555"
MISSING_APPLICATION = "66666666-6666-6666-6666-666666666666"
MISSING_ENROLLMENT = "77777777-7777-7777-7777-777777777777"
MISSING_EVENT = "88888888-8888-8888-8888-888888888888"
MISSING_PERFORMANCE = "99999999-9999-9999-9999-999999999999"
MISSING_PROGRAM = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MISSING_CLAIM = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
MISSING_ALERT = "cccccccc-cccc-cccc-cccc-cccccccccccc"

# A role header with no identity beside it, and an identity carrying a role the service
# has never heard of.
ROLE_WITHOUT_IDENTITY = {
    "X-User-Role": UserRole.CERTIFIED_INSTALLER,
    "Content-Type": "application/json",
}
UNDECLARED_ROLE = "StorageContractor"

FRESH_TEST_WINDOW = "2026-08-20T09:00:00Z"
EVENT_WINDOW_END = "2026-09-15T19:00:00Z"


class TestTheNotFoundCatalogue:
    """Twelve collections, twelve identifiers, twelve distinct objections."""

    def test_each_collection_answers_with_its_own_not_found(self, api):
        """No collection borrows another's 404, and none of them borrows a 403.

        Every probe is issued by a role that the endpoint table authorizes and that owns
        nothing, so no ownership rule can pre-empt the existence check, and every probe
        carries an identifier belonging to no record. Each of the twelve reads comes back
        with the objection minted for that entity type rather than with a shared one.

        PRD 2.4: "The first identifier that resolves to nothing decides the response, and each entity type raises its own 404: `ERR_INSTALLER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_LOAD_CALCULATION_NOT_FOUND`, `ERR_BATTERY_SYSTEM_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` and `ERR_PERFORMANCE_NOT_FOUND`."
        PRD 2.12: "Every referenced resource resolves, path parameters left to right and then body foreign keys in declaration order, each miss raising that entity's own 404."

        Design: Corner/errors/not_found_probes_across_every_remaining_root_collection
        """
        fixtures.certified_installer(api)

        probes = [
            (api.get_installer, MISSING_INSTALLER, WARRANTY_AGENT_HEADERS,
             ApiErrorId.ERR_INSTALLER_NOT_FOUND),
            (api.get_site, MISSING_SITE, AHJ_HEADERS,
             ApiErrorId.ERR_SITE_NOT_FOUND),
            (api.get_load_calculation, MISSING_LOAD_CALCULATION, AHJ_HEADERS,
             ApiErrorId.ERR_LOAD_CALCULATION_NOT_FOUND),
            (api.get_permit, MISSING_PERMIT, AHJ_HEADERS,
             ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (api.get_commissioning_test, MISSING_TEST, AHJ_HEADERS,
             ApiErrorId.ERR_TEST_NOT_FOUND),
            (api.get_application, MISSING_APPLICATION, UTILITY_REVIEWER_HEADERS,
             ApiErrorId.ERR_APPLICATION_NOT_FOUND),
            (api.get_enrollment, MISSING_ENROLLMENT, UTILITY_REVIEWER_HEADERS,
             ApiErrorId.ERR_ENROLLMENT_NOT_FOUND),
            (api.get_dispatch_event, MISSING_EVENT, UTILITY_REVIEWER_HEADERS,
             ApiErrorId.ERR_EVENT_NOT_FOUND),
            (api.get_performance, MISSING_PERFORMANCE, UTILITY_REVIEWER_HEADERS,
             ApiErrorId.ERR_PERFORMANCE_NOT_FOUND),
            (api.get_program, MISSING_PROGRAM, REBATE_ADMIN_HEADERS,
             ApiErrorId.ERR_PROGRAM_NOT_FOUND),
            (api.get_claim, MISSING_CLAIM, REBATE_ADMIN_HEADERS,
             ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api.get_alert, MISSING_ALERT, WARRANTY_AGENT_HEADERS,
             ApiErrorId.ERR_ALERT_NOT_FOUND),
        ]

        for read, unknown_id, headers, error_id in probes:
            validate_error(read(unknown_id, headers=headers), error_id, expected_status=404)


class TestAuthenticationBeforeEverythingElse:
    """A write that never gets as far as the role table or the site lookup."""

    def test_a_missing_identity_and_an_unknown_role_are_both_unauthenticated(self, api):
        """Neither probe is answered with a role objection or a not-found one.

        The first write sends a well-formed role and no identity at all; the second sends a
        real installer identity under a role name the service does not define. Both are
        refused at the identity gate, which runs before role authorization and before any
        identifier in the payload is resolved, so both come back as unauthenticated rather
        than as forbidden or as a missing site. Nothing was written either time.

        PRD 2.1: "Every request to every endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not one of the six role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.12: "Both identity headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/write_with_missing_x_user_id_header_returns_unauthenticated
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        payload = factories.whole_home_load_calculation_payload(project.site_id)

        validate_error(
            api.create_load_calculation(payload, headers=ROLE_WITHOUT_IDENTITY),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )
        validate_error(
            api.create_load_calculation(
                payload, headers=build_user_headers(project.installer_id, UNDECLARED_ROLE)
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        calculations, _ = validate_paginated(
            api.list_load_calculations(
                {"site_id": project.site_id}, headers=project.installer_headers
            )
        )
        assert calculations == [], "an unauthenticated write left a calculation behind"


class TestShapeBeforeBusinessRules:
    """Four malformations on four endpoints, all caught by the same 400."""

    def test_four_malformed_payloads_are_all_refused_as_invalid_requests(self, api):
        """A zero-length window, a short serial list, an unknown enum, an empty circuit list.

        Each probe would trip a business rule if it got that far: the test booking duplicates
        a type the bank already holds, the registration would decide warranty coverage, the
        alert would open against a bank in service, and the calculation would be sized. The
        shape check runs first, so all four are refused as malformed rather than as duplicate,
        late or unsized. Nothing moved: the bank's warranty is still unregistered, the bank
        still holds exactly its four bookings, and no alert exists against it.

        PRD 2.4: "A request that omits a required field, sends null where a value is required, supplies a value outside a declared enumeration, sends a negative quantity where only non-negative values are meaningful, supplies a window whose `window_end` is not strictly after its `window_start`, sends an empty essential-circuit list under essential-loads scoping, registers a serial-number list whose length differs from the bank's `unit_count`, or supplies a firmware string that is not three dot-separated integers, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD 2.12: "Required fields present and non-null, enumerations respected, quantities non-negative, windows strictly ordered, and the other shape rules of §2.4, else `ERR_INVALID_REQUEST`."
        PRD 3.6: "Once a bank is commissioned, the installer registers the manufacturer warranty by supplying the `coverage_years` term and the `serial_numbers` of the individual units, whose count must equal the bank's `unit_count`."
        PRD 3.8: "the `severity` of the condition (`INFO`, `WARNING` or `CRITICAL`, the last reserved for conditions that put the bank's dispatch participation in question)"

        Design: Corner/errors/shape_probes_across_write_endpoints_return_invalid_request
        """
        project = fixtures.commissioned_project(api)
        system_id = project.battery_system_id

        validate_error(
            api.create_commissioning_test(
                factories.commissioning_test_payload(
                    system_id,
                    TestType.BACKUP_TRANSITION,
                    FRESH_TEST_WINDOW,
                    FRESH_TEST_WINDOW,
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api.register_warranty(
                system_id,
                factories.warranty_registration_payload(unit_count=1),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api.create_alert(
                factories.alert_payload(system_id, severity="MEGA"),
                headers=WARRANTY_AGENT_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api.create_load_calculation(
                factories.load_calculation_payload(project.site_id, essential_circuits=[]),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        system = fixtures.read_system(api, project)
        assert system["warranty_status"] == WarrantyStatus.UNREGISTERED
        tests, meta = validate_paginated(
            api.list_commissioning_tests(
                {"battery_system_id": system_id}, headers=project.installer_headers
            )
        )
        assert meta["total_count"] == 4
        assert len(tests) == 4
        alerts, _ = validate_paginated(
            api.list_alerts({"battery_system_id": system_id}, headers=WARRANTY_AGENT_HEADERS)
        )
        assert alerts == [], "a malformed alert payload created an alert"


class TestTheTwoReviewWorkflowsKeepSeparateStateErrors:
    """The same verb on two entities that have both moved past it."""

    def test_resubmitting_a_finished_permit_and_application_names_each_entity(self, api):
        """Two refusals, two identifiers, and neither row moves.

        The project is finished: the permit has passed its field inspection and the utility
        has approved the bank for installation. Submission is declared out of the permit's
        draft and corrections states, and out of the application's draft and supplemental
        states, so neither call is available now — and each entity reports its own state
        objection rather than a shared one. Both rows stay exactly where the reviews left them.

        PRD 3.4: "Reviewing a permit that is not `SUBMITTED`, or submitting one that is neither `DRAFT` nor `CORRECTIONS_REQUIRED`, is rejected with `ERR_PERMIT_STATE_INVALID`."
        PRD 3.5: "Submitting the application moves it `DRAFT → SUBMITTED` and requires the bank to be at `DESIGN_LOCKED`, `INSTALLED` or `COMMISSIONED` — a bank still in `DESIGN_DRAFT` has nothing stable to review — and requires that the bank's `grid_status` is not already `DENIED`, since a utility denial is final for that bank."
        PRD 2.12: "The target resource is in a state from which the requested transition is declared, else the state error of the entity concerned — `ERR_LOAD_CALC_STATE_INVALID`, `ERR_SYSTEM_BUILD_STATE_INVALID`, `ERR_SYSTEM_GRID_STATE_INVALID`, `ERR_PERMIT_STATE_INVALID`, `ERR_APPLICATION_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_ALERT_STATE_INVALID`, `ERR_ENROLLMENT_STATE_INVALID`, `ERR_EVENT_STATE_INVALID` or `ERR_PERFORMANCE_STATE_INVALID`."

        Design: Corner/errors/submit_on_an_already_advanced_permit_and_application_returns_state_invalid
        """
        project = fixtures.commissioned_project(api)

        validate_error(
            api.submit_permit(project.permit_id, headers=project.installer_headers),
            ApiErrorId.ERR_PERMIT_STATE_INVALID,
            expected_status=409,
        )
        validate_error(
            api.submit_application(
                project.application_id, headers=project.installer_headers
            ),
            ApiErrorId.ERR_APPLICATION_STATE_INVALID,
            expected_status=409,
        )

        permit = get_success_data(
            api.get_permit(project.permit_id, headers=AHJ_HEADERS)
        )
        assert permit["status"] == PermitStatus.INSPECTION_PASSED
        application = get_success_data(
            api.get_application(project.application_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert application["status"] == ApplicationStatus.APPROVED_TO_INSTALL


class TestTheTerminalClaimState:
    """An action that is legal from the reserved state and gone once the claim is void."""

    def test_submitting_a_voided_claim_is_refused_and_re_releases_nothing(self, api):
        """The hold was released once, and the refused submission does not release it again.

        The installer reserved 423000 cents while the bank was installed and then withdrew
        the reservation, which returned the whole hold to the unencumbered bucket. The project
        was then finished — commissioned, granted permission to operate and warranty-registered
        — so every precondition submission asks about is satisfied and the only thing wrong is
        the claim's own terminal state. The refusal names the claim, the claim stays void, and
        the pool still shows the full budget unencumbered rather than a second release.

        PRD 3.7: "Voiding moves the claim `RESERVED → VOID`, takes a `reason` string which is stored in `clawback_reason` as the release audit note, and releases the claim's effective hold from `reserved_budget_cents` back to `remaining_budget_cents`."
        PRD 3.7: "**Adjudication.** A reserved claim is submitted for adjudication once the project is genuinely finished: the bank must be `COMMISSIONED`, its `grid_status` must be `PTO_GRANTED`, and its `warranty_status` must be `ACTIVE`."
        PRD 3.7: "Every transition of a claim from a state that does not declare it — submitting an approved claim, paying an unapproved one, clawing back one that was never paid — is rejected with `ERR_CLAIM_STATE_INVALID`."

        Design: Corner/errors/submitting_a_voided_claim_returns_claim_state_invalid
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        claim = fixtures.reserve_claim(api, project, program_id)
        validate_success(
            api.void_claim(
                claim["id"], factories.void_payload(), headers=project.installer_headers
            )
        )
        project = fixtures.schedule_four_tests(api, project)
        project = fixtures.record_four_results(api, project)
        project = fixtures.pass_inspection(api, project)
        project = fixtures.advance_clock(api, project, fixtures.COMMISSIONING_INSTANT)
        validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )
        project = fixtures.grant_pto(api, project)
        project = fixtures.register_warranty(api, project)

        validate_error(
            api.submit_claim(claim["id"], headers=project.installer_headers),
            ApiErrorId.ERR_CLAIM_STATE_INVALID,
            expected_status=409,
        )

        stored = fixtures.read_claim(api, project, claim["id"])
        assert stored["status"] == ClaimStatus.VOID
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=5000000, reserved=0, paid=0)


class TestThreeMoreEntitiesWithTheirOwnStateErrors:
    """A settled event, a reported participation and an unacknowledged alert."""

    def test_a_settled_event_a_reported_delivery_and_an_open_alert_each_object(self, api):
        """Three refusals, three identifiers, and the third is a skipped step rather than a repeat.

        The metered figure is reported once, which moves the participation out of the pending
        state the report is declared from; a second report while the event is still scheduled
        is therefore refused as a performance-state objection and does not overwrite the nine
        kilowatt-hours already on record. The event is then settled, and a second settlement is
        refused as an event-state objection because settlement is terminal. The alert is a
        different shape of mistake: it was never acknowledged, and filing is declared only out
        of the acknowledged state, so the attempt to skip triage is refused as an alert-state
        objection — the bank's warranty is active, so nothing else could be the cause. The
        alert stays open with no review round on it.

        PRD 3.9: "**Reporting delivery.** After the window has closed the reviewer reports metered `delivered_kwh` for a participation, which moves it `PENDING → REPORTED`. The event must still be `SCHEDULED` and the logical clock must have reached or passed the event's `window_end`; reporting for a participation that is not `PENDING` is rejected with `ERR_PERFORMANCE_STATE_INVALID`."
        PRD 3.9: "A settled event is terminal: neither a further participation nor a second settlement is possible, and both are rejected with `ERR_EVENT_STATE_INVALID`."
        PRD 3.8: "An acknowledged alert can become a warranty claim. Filing moves the alert `ACKNOWLEDGED → UNDER_REVIEW`, requires the bank's `warranty_status` to be `ACTIVE` — a bank whose warranty is `UNREGISTERED` or `VOID` is rejected with `ERR_WARRANTY_NOT_ACTIVE` — records the `claimed_component` named on the filing, may carry `resolution_notes` giving the reviewer context, and increments `claim_round_count` by one."
        PRD 3.8: "Acknowledging, filing or adjudicating from a status that does not declare the transition is rejected with `ERR_ALERT_STATE_INVALID`."

        Design: Corner/errors/settle_report_delivery_and_file_claim_from_dead_states_return_state_invalid
        """
        project = fixtures.enrolled_project(api)
        project = fixtures.register_warranty(api, project)
        alert = validate_success(
            api.create_alert(
                factories.alert_payload(
                    project.battery_system_id, severity=AlertSeverity.CRITICAL
                ),
                headers=WARRANTY_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        event = fixtures.create_event(api, project)
        fixtures.call_into_event(api, project)
        project = fixtures.advance_clock(api, project, EVENT_WINDOW_END)
        fixtures.report_delivery(api, project, 9.0)

        validate_error(
            api.report_delivery(
                project.performance_id,
                factories.delivery_payload(4.0),
                headers=UTILITY_REVIEWER_HEADERS,
            ),
            ApiErrorId.ERR_PERFORMANCE_STATE_INVALID,
            expected_status=409,
        )

        fixtures.settle_event(api, project)
        validate_error(
            api.settle_event(event["id"], headers=UTILITY_REVIEWER_HEADERS),
            ApiErrorId.ERR_EVENT_STATE_INVALID,
            expected_status=409,
        )

        validate_error(
            api.file_warranty_claim(
                alert["id"],
                factories.file_claim_payload(),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_ALERT_STATE_INVALID,
            expected_status=409,
        )

        settled_event = get_success_data(
            api.get_dispatch_event(event["id"], headers=UTILITY_REVIEWER_HEADERS)
        )
        assert settled_event["status"] == EventStatus.SETTLED
        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(performance, "delivered_kwh", 9.0)
        stored_alert = get_success_data(
            api.get_alert(alert["id"], headers=WARRANTY_AGENT_HEADERS)
        )
        assert stored_alert["status"] == AlertStatus.OPEN
        assert stored_alert["claim_round_count"] == 0
