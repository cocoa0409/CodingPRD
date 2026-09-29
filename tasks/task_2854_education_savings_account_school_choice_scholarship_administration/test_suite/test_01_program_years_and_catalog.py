"""Standing up an award year, publishing the expense catalogue and the logical clock."""

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    MISSING_ID,
    PA,
    ApiErrorId,
    assert_expense_category,
    assert_iso_millis,
    assert_program_year,
    create_application_payload,
    create_program_year_payload,
    create_program_year_payload_defaults_omitted,
    create_student,
    create_tuition_category_payload,
    make_guardian_headers,
    open_window,
    read_expense_category,
    read_program_year,
    set_clock,
    validate_error,
    validate_success,
)


class TestProgramYearCreation:
    """The record a programme-year creation mints and the defaults it applies."""

    def test_creation_echoes_every_declared_input_and_system_field(self, api):
        """PRD §3.1: "A new year is born in `DRAFT` with its ops-run epoch
        `current_quarter` at 0 and both seat counters at 0."

        PRD §2.4: "Every resource the API mints carries a server-generated `id`,
        formatted as a UUID with no type prefix of any kind, and a `created_at`
        timestamp expressed as an ISO 8601 UTC instant with exactly three
        fractional-second digits."

        Design: Corner/entities/program_year_creation_returns_every_declared_field
        """
        payload = create_program_year_payload()
        response = api.create_program_year(payload, PA)

        assert response.status_code == 201, (
            "creating a programme year brings a brand-new resource into existence "
            f"and responds with HTTP 201 Created, got {response.status_code}"
        )
        body = response.json()
        assert body["response_type"] == "object", (
            "a single created resource is reported with response_type object, "
            f"got {body['response_type']!r}"
        )
        assert isinstance(body["meta"]["api_request_id"], str), (
            "the envelope carries a server-generated api_request_id"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "the api_request_id starts with req_, got "
            f"{body['meta']['api_request_id']!r}"
        )

        year = validate_success(response, expected_status=201)
        assert_program_year(year)

        assert year["label"] == "2026-27", f"label should be echoed, got {year['label']!r}"
        assert year["residency_state"] == "TX", (
            f"residency_state should be echoed, got {year['residency_state']!r}"
        )
        assert year["total_seats"] == 2, (
            f"total_seats fixes capacity at creation, got {year['total_seats']}"
        )
        assert year["base_award_cents"] == 731500, (
            f"base_award_cents should be echoed, got {year['base_award_cents']}"
        )
        assert year["rollover_cap_pct"] == pytest.approx(0.25, abs=0.0001), (
            f"rollover_cap_pct is a fraction that keeps its precision, "
            f"got {year['rollover_cap_pct']}"
        )
        assert year["admin_fee_pct"] == pytest.approx(0.0175, abs=0.0001), (
            f"admin_fee_pct is a fraction that keeps its precision, "
            f"got {year['admin_fee_pct']}"
        )
        assert year["acceptance_deadline_days"] == 14, (
            f"acceptance_deadline_days should be echoed, "
            f"got {year['acceptance_deadline_days']}"
        )
        assert year["min_assessment_percentile"] == 40, (
            f"min_assessment_percentile should be echoed, "
            f"got {year['min_assessment_percentile']}"
        )
        assert year["min_portfolio_artifacts"] == 6, (
            f"min_portfolio_artifacts should be echoed, "
            f"got {year['min_portfolio_artifacts']}"
        )

        assert year["status"] == "DRAFT", (
            f"a new year is born in DRAFT, got {year['status']!r}"
        )
        assert year["current_quarter"] == 0, (
            f"the ops-run epoch starts at 0, got {year['current_quarter']}"
        )
        assert year["seats_committed"] == 0, (
            f"both seat counters read 0 on a freshly created year, "
            f"got seats_committed {year['seats_committed']}"
        )
        assert year["seats_available"] == 0, (
            f"both seat counters read 0 on a freshly created year, "
            f"got seats_available {year['seats_available']}"
        )
        assert year["version"] == 1, (
            f"version starts at 1 when the resource is created, got {year['version']}"
        )
        assert_iso_millis(year["created_at"], "program_year.created_at")
        assert_iso_millis(year["updated_at"], "program_year.updated_at")

    def test_omitted_optional_parameters_take_the_programme_defaults(self, api):
        """PRD §3.1: "`base_award_cents` is the per-pupil base entitlement before any
        income multiplier or category add-on and defaults to 731500 — that is, seven
        thousand three hundred and fifteen dollars — and must be at least 1."

        PRD §3.1: "`min_portfolio_artifacts` is the smallest accepted portfolio
        artefact count, inclusive, defaults to 6, and must be at least 1."

        Design: Corner/entities/program_year_defaults_applied_when_optional_inputs_omitted
        """
        payload = create_program_year_payload_defaults_omitted()
        for optional in (
            "base_award_cents",
            "rollover_cap_pct",
            "admin_fee_pct",
            "acceptance_deadline_days",
            "min_assessment_percentile",
            "min_portfolio_artifacts",
        ):
            assert optional not in payload, (
                f"the payload must omit {optional} so the server has to default it"
            )

        year = validate_success(api.create_program_year(payload, PA), expected_status=201)

        assert year["base_award_cents"] == 731500, (
            f"base_award_cents defaults to 731500, got {year['base_award_cents']}"
        )
        assert year["rollover_cap_pct"] == pytest.approx(0.25, abs=0.0001), (
            f"rollover_cap_pct defaults to 0.25, got {year['rollover_cap_pct']}"
        )
        assert year["admin_fee_pct"] == pytest.approx(0.0175, abs=0.0001), (
            f"admin_fee_pct defaults to 0.0175, got {year['admin_fee_pct']}"
        )
        assert year["acceptance_deadline_days"] == 14, (
            f"acceptance_deadline_days defaults to 14, "
            f"got {year['acceptance_deadline_days']}"
        )
        assert year["min_assessment_percentile"] == 40, (
            f"min_assessment_percentile defaults to 40, "
            f"got {year['min_assessment_percentile']}"
        )
        assert year["min_portfolio_artifacts"] == 6, (
            f"min_portfolio_artifacts defaults to 6, "
            f"got {year['min_portfolio_artifacts']}"
        )
        assert year["total_seats"] == 3, (
            f"total_seats is the supplied capacity, got {year['total_seats']}"
        )
        assert year["seats_committed"] == 0 and year["seats_available"] == 0, (
            "both seat counters read 0 on a freshly created year, got "
            f"committed {year['seats_committed']} / available {year['seats_available']}"
        )


class TestProgramYearLifecycle:
    """The DRAFT to WINDOW_OPEN publication step and the seat pool it publishes."""

    def test_open_window_advances_the_year_and_publishes_the_seat_pool(self, api):
        """PRD §3.1: "On success `seats_committed` is set to 0, `seats_available` is
        set to the full `total_seats`, and the year's `version` rises by 1."

        Design: Corner/state_machines/program_year_starts_in_draft_and_open_window_advances_it
        """
        created = validate_success(
            api.create_program_year(create_program_year_payload(), PA),
            expected_status=201,
        )
        assert created["status"] == "DRAFT", (
            f"a new year is born in DRAFT, got {created['status']!r}"
        )
        assert created["version"] == 1, (
            f"version starts at 1 when the resource is created, got {created['version']}"
        )

        opened = validate_success(api.open_window(created["id"], PA))

        assert opened["status"] == "WINDOW_OPEN", (
            "publishing the year for applications advances it DRAFT to WINDOW_OPEN, "
            f"got {opened['status']!r}"
        )
        assert opened["version"] == created["version"] + 1, (
            f"the year's version rises by 1 on the publication, got {opened['version']} "
            f"from {created['version']}"
        )
        assert opened["seats_committed"] == 0, (
            f"seats_committed is set to 0, got {opened['seats_committed']}"
        )
        assert opened["seats_available"] == created["total_seats"], (
            "seats_available is set to the full total_seats, got "
            f"{opened['seats_available']} against {created['total_seats']} seats"
        )
        assert opened["current_quarter"] == 0, (
            "no disbursement has yet been run for the year, so current_quarter is "
            f"still 0, got {opened['current_quarter']}"
        )


class TestExpenseCatalogue:
    """Publishing an allowable-expense catalogue entry and reading it back."""

    def test_catalogue_entry_round_trips_with_its_cap_and_three_booleans(self, api):
        """PRD §3.1: "Each catalogue entry carries a stable uppercase-snake `code` such
        as "TUITION" that must be unique across the catalogue, a display `name`, and a
        `per_year_cap_cents` ceiling of at least 1 cent that limits how much one account
        may commit to that category within one programme year."

        Design: Corner/endpoints/expense_category_create_and_read_round_trip
        """
        payload = create_tuition_category_payload(
            code="MATERIALS",
            name="Curriculum materials",
            per_year_cap_cents=300000,
            allowable=True,
            requires_preapproval=False,
            requires_service_period=False,
        )
        created = validate_success(
            api.create_expense_category(payload, PA), expected_status=201
        )
        assert_expense_category(created)

        assert created["code"] == "MATERIALS", (
            f"code should be echoed, got {created['code']!r}"
        )
        assert created["name"] == "Curriculum materials", (
            f"name should be echoed, got {created['name']!r}"
        )
        assert created["per_year_cap_cents"] == 300000, (
            "per_year_cap_cents is a whole-cent integer ceiling, got "
            f"{created['per_year_cap_cents']!r}"
        )
        assert created["allowable"] is True, (
            f"allowable should be echoed as true, got {created['allowable']!r}"
        )
        assert created["requires_preapproval"] is False, (
            f"requires_preapproval should be echoed as false, "
            f"got {created['requires_preapproval']!r}"
        )
        assert created["requires_service_period"] is False, (
            f"requires_service_period should be echoed as false, "
            f"got {created['requires_service_period']!r}"
        )

        reread = read_expense_category(created["id"])
        assert reread == created, (
            "reading the catalogue entry back returns exactly the record that was "
            f"published, got {reread!r} against {created!r}"
        )


class TestLogicalClock:
    """The logical programme clock every window and deadline reads."""

    def test_clock_setting_decides_whether_the_submission_window_is_open(self, api):
        """PRD §2.5: "Before any operator sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time. A `ProgramAdmin`
        may move it by supplying a `to_iso8601` instant; the response reports the new
        setting as `current_utc`"

        PRD §3.1: "Note that opening the window is necessary but not sufficient for a
        submission to be accepted: the logical clock must also stand at or after
        `window_open_at` and strictly before `window_close_at`."

        Design: Corner/endpoints/clock_endpoint_pins_the_logical_program_time
        """
        year = validate_success(
            api.create_program_year(create_program_year_payload(), PA),
            expected_status=201,
        )
        open_window(year["id"])
        student = create_student()
        guardian = make_guardian_headers(student["id"])

        early = validate_success(api.set_clock("2026-08-10T00:00:00Z", PA))
        assert early["current_utc"].startswith("2026-08-10T00:00:00"), (
            f"the response reports the new setting as current_utc, got {early!r}"
        )

        too_early = api.create_application(
            create_application_payload(year["id"], student["id"]), guardian
        )
        validate_error(too_early, ApiErrorId.APPLICATION_WINDOW_CLOSED.value, 409)
        assert read_program_year(year["id"])["status"] == "WINDOW_OPEN", (
            "the year itself is unaffected by a submission the clock refused"
        )

        set_clock("2026-09-01T00:00:00Z")
        inside = api.create_application(
            create_application_payload(year["id"], student["id"]), guardian
        )
        application = validate_success(inside, expected_status=201)
        assert application["status"] == "DRAFT", (
            "a newly created application sits in DRAFT once the clock stands inside "
            f"the window, got {application['status']!r}"
        )
        assert read_program_year(year["id"])["status"] == "WINDOW_OPEN", (
            "the year stays WINDOW_OPEN throughout"
        )

    def test_clock_starts_at_the_declared_epoch_before_any_operator_moves_it(self, api):
        """PRD §2.5: "Before any operator sets it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time."

        PRD §3.2: "On success the current logical instant is stamped into
        `submitted_at` — which later serves as the primary tie-break when the eligible
        pool is ranked"

        Design: Corner/endpoints/clock_endpoint_pins_the_logical_program_time
        """
        year = validate_success(
            api.create_program_year(
                create_program_year_payload(
                    window_open_at="2026-08-01T00:00:00Z",
                    window_close_at="2026-09-30T23:59:59Z",
                ),
                PA,
            ),
            expected_status=201,
        )
        open_window(year["id"])
        student = create_student()
        guardian = make_guardian_headers(student["id"])

        application = validate_success(
            api.create_application(
                create_application_payload(year["id"], student["id"]), guardian
            ),
            expected_status=201,
        )
        submitted = validate_success(api.submit_application(application["id"], guardian))

        assert submitted["submitted_at"].startswith("2026-08-01T00:00:00"), (
            "with no operator having moved the clock, the logical instant stamped "
            f"into submitted_at is the epoch 2026-08-01T00:00:00Z, got "
            f"{submitted['submitted_at']!r} against the epoch {CLOCK_EPOCH}"
        )


class TestNotFoundIdentifiers:
    """Each resource kind reports its own not-found code."""

    @pytest.mark.parametrize(
        "reader_name,expected_error",
        [
            ("get_program_year", ApiErrorId.PROGRAM_YEAR_NOT_FOUND),
            ("get_student", ApiErrorId.STUDENT_NOT_FOUND),
            ("get_application", ApiErrorId.APPLICATION_NOT_FOUND),
            ("get_account", ApiErrorId.ACCOUNT_NOT_FOUND),
            ("get_provider", ApiErrorId.PROVIDER_NOT_FOUND),
            ("get_expense_category", ApiErrorId.EXPENSE_CATEGORY_NOT_FOUND),
            ("get_purchase_request", ApiErrorId.PURCHASE_REQUEST_NOT_FOUND),
            ("get_misuse_case", ApiErrorId.MISUSE_CASE_NOT_FOUND),
            ("get_renewal_review", ApiErrorId.RENEWAL_REVIEW_NOT_FOUND),
            ("get_appeal", ApiErrorId.APPEAL_NOT_FOUND),
        ],
    )
    def test_each_resource_kind_has_its_own_not_found_code(
        self, api, reader_name, expected_error
    ):
        """PRD §2.8: "The programme year named by the path or by `program_year_id` or
        `next_program_year_id` exists — `ERR_PROGRAM_YEAR_NOT_FOUND`."

        PRD §2.8: "The appeal named by the path exists — `ERR_APPEAL_NOT_FOUND`, on
        appeal reads and appeal decisions."

        Design: Corner/entities/every_nonexistent_id_returns_its_own_not_found_error
        """
        reader = getattr(api, reader_name)
        response = reader(MISSING_ID, PA)

        body = validate_error(response, expected_error.value, 404)
        assert body["message"], (
            "the message provides a human-readable explanation of what went wrong"
        )
