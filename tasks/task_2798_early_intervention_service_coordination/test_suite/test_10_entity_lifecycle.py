"""
The shape of a freshly written row and of the row read back: computed fields
derived at creation, declared defaults applied to omitted inputs, the closed
input surface that refuses caller-supplied system fields, entity-scoped
existence failures, and the one register that carries no version at all.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    EVALUATOR_HEADERS,
    FISCAL_HEADERS,
    INTAKE_HEADERS,
    NON_EXISTENT_UUID,
    add_service_line,
    assert_append_only_row,
    assert_caseload_summary,
    assert_case_weight,
    assert_common_fields,
    assert_unit_pool,
    build_active_services,
    create_child,
    create_provider,
    create_referral,
    factories,
    is_iso8601_timestamp,
    make_service_coordinator_headers,
    read_caseload_summary,
    read_child,
    read_provider,
    read_service_line,
    record_consent,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

INTAKE_INSTANT = "2026-03-02T09:00:00Z"
RECEIVED_DATE = "2026-03-02"


def _at_intake(api):
    """Park the logical clock on the day the front-door narrative starts."""
    set_clock(api, INTAKE_INSTANT)


class TestChildRegistration:
    """The root entity: five inputs in, two derived fields out."""

    def test_creation_derives_the_third_birthday_and_starts_the_counter(self, api):
        """
        Registering a child echoes every supplied field, derives the third
        birthday three calendar years on, and opens the referral counter at zero.

        PRD 3.1: "From the birth date the server derives `third_birthday_date`:
        the same month and day three calendar years later, except that a child
        born on 29 February takes 28 February as the anniversary."

        Design: Corner/entities/child_creation_returns_computed_third_birthday_and_zero_referrals
        """
        _at_intake(api)

        child = validate_success(
            api.create_child(
                factories.child_payload(
                    first_name="Ada",
                    last_name="Nolan",
                    date_of_birth="2024-06-15",
                    county_code="CNT_A",
                    primary_language="EN",
                ),
                INTAKE_HEADERS,
            ),
            201,
        )

        assert child["first_name"] == "Ada"
        assert child["last_name"] == "Nolan"
        assert child["date_of_birth"] == "2024-06-15"
        assert child["county_code"] == "CNT_A"
        assert child["primary_language"] == "EN"
        assert child["third_birthday_date"] == "2027-06-15"
        assert child["active_referral_count"] == 0
        assert_common_fields(child, expected_version=1)
        assert is_iso8601_timestamp(child["created_at"])
        assert is_iso8601_timestamp(child["updated_at"])

    def test_retrieval_returns_the_stored_row_without_bumping_the_version(self, api):
        """
        Reading the child back yields the same row, computed date included, and
        leaves the concurrency counter where creation left it.

        PRD 2.4: "`version` is an integer that starts at 1 when the row is created
        and increments by exactly 1 on every mutation of that row — including
        mutations that arrive as the secondary effect of a write aimed at a
        different resource."

        Design: Corner/entities/child_retrieval_returns_the_stored_row_unchanged
        """
        _at_intake(api)
        created = validate_success(
            api.create_child(factories.child_payload(), INTAKE_HEADERS), 201
        )

        stored = validate_success(api.get_child(created["id"], INTAKE_HEADERS), 200)

        assert stored["id"] == created["id"]
        assert stored["last_name"] == "Nolan"
        assert stored["date_of_birth"] == "2024-06-15"
        assert stored["third_birthday_date"] == "2027-06-15"
        assert stored["active_referral_count"] == 0
        assert stored["version"] == 1

    def test_leap_day_birth_takes_the_28_february_anniversary(self, api):
        """
        A child born on 29 February has no third-birthday anniversary to land on,
        so the date falls back to 28 February rather than rolling into March,
        while a child born the following day keeps 1 March.

        PRD 3.1: "From the birth date the server derives `third_birthday_date`:
        the same month and day three calendar years later, except that a child
        born on 29 February takes 28 February as the anniversary."

        Design: Corner/entities/child_third_birthday_leap_day_anniversary_falls_on_feb_28
        """
        _at_intake(api)

        leap_born = validate_success(
            api.create_child(
                factories.child_payload(
                    first_name="Rue", last_name="Okafor", date_of_birth="2024-02-29"
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert leap_born["third_birthday_date"] == "2027-02-28"

        day_after = validate_success(
            api.create_child(
                factories.child_payload(
                    first_name="Milo", last_name="Okafor", date_of_birth="2024-03-01"
                ),
                INTAKE_HEADERS,
            ),
            201,
        )
        assert day_after["third_birthday_date"] == "2027-03-01"


class TestCaseOpening:
    """Declared defaults and the statutory deadline computed at intake."""

    def test_creation_applies_defaults_and_computes_the_statutory_deadline(self, api):
        """
        An intake that omits its one optional flag takes the declared default,
        every field awaiting a later act begins null, every derived counter begins
        at zero, and the 45-day deadline is fixed on the received date.

        PRD 3.1: "On creation the server computes `statutory_deadline_date` as that
        date plus 45 calendar days, sets `status` to `INTAKE`, sets
        `eligibility_status` to `PENDING`, sets `initial_timeline_status` to
        `IN_PROGRESS`, and recomputes the child's `active_referral_count`."

        Design: Corner/entities/referral_creation_applies_declared_defaults_and_statutory_deadline
        """
        _at_intake(api)
        child_id = create_child(api)

        referral = validate_success(
            api.create_referral(
                factories.referral_payload(
                    child_id,
                    primary_referral_source="PHYSICIAN",
                    referral_received_date=RECEIVED_DATE,
                    county_code="CNT_A",
                    presenting_concern=(
                        "Expressive language delay noted at the 20-month "
                        "well-child visit"
                    ),
                ),
                INTAKE_HEADERS,
            ),
            201,
        )

        assert referral["interpreter_required"] is False
        assert referral["status"] == "INTAKE"
        assert referral["eligibility_status"] == "PENDING"
        assert referral["initial_timeline_status"] == "IN_PROGRESS"
        assert referral["statutory_deadline_date"] == "2026-04-16"
        assert referral["coordinator_id"] is None
        assert referral["assignment_date"] is None
        assert_case_weight(referral["case_weight_points"], 0)
        assert referral["excluded_delay_days"] == 0
        assert referral["gross_elapsed_days"] == 0
        assert referral["net_elapsed_days"] == 0
        assert referral["monthly_contact_status"] == "NOT_APPLICABLE"
        assert referral["service_gap_flag"] is False
        assert referral["version"] == 1

        # The parent counter was recomputed inside the same request.
        assert read_child(api, child_id)["active_referral_count"] == 1


class TestCoordinatorRegistration:
    """The only entity whose status is an input carrying a default."""

    def test_creation_defaults_to_active_with_zero_aggregates(self, api):
        """
        A coordinator registered without a status is ACTIVE, and all three
        caseload aggregates start at zero — utilization included, rather than
        being divided out against the ceiling.

        PRD 3.2: "A freshly registered coordinator has `weighted_caseload_points`,
        `active_case_count` and `utilization_ratio` all at zero."

        Design: Corner/entities/coordinator_creation_defaults_to_active_with_zero_aggregates
        """
        _at_intake(api)

        coordinator = validate_success(
            api.create_coordinator(
                factories.coordinator_payload(
                    full_name="Dana Reyes",
                    county_code="CNT_A",
                    language_codes=["EN"],
                    max_weighted_caseload_points=12.00,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert coordinator["status"] == "ACTIVE"
        assert_case_weight(coordinator["max_weighted_caseload_points"], 12.00)
        assert_case_weight(coordinator["weighted_caseload_points"], 0)
        assert coordinator["active_case_count"] == 0
        assert coordinator["utilization_ratio"] == pytest.approx(0, abs=0.00005)

        assert_caseload_summary(
            read_caseload_summary(api, coordinator["id"]),
            coordinator_id=coordinator["id"],
            active_case_count=0,
            weighted_caseload_points=0,
            max_weighted_caseload_points=12.00,
            utilization_ratio=0,
            caseload_posture="OPEN",
            headroom_points=12.00,
        )


class TestCaseListing:
    """The list envelope: paging metadata and a conjunctive filter."""

    def test_paging_walks_the_collection_and_the_child_filter_narrows_it(self, api):
        """
        Three open cases page two at a time with a stable total and a has_more
        flag that falls on the last page, and the child filter cuts the same
        collection down to the single case belonging to that child.

        PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of rows
        matching the filters before pagination is applied and `has_more` is true
        when rows remain beyond the current page."

        Design: Corner/entities/referral_listing_paginates_and_filters_by_child
        """
        _at_intake(api)
        referral_ids = []
        second_child_id = None
        for first_name, last_name, dob, source, concern in (
            ("Ada", "Nolan", "2024-06-15", "PHYSICIAN", "Expressive language delay"),
            ("Ben", "Oyelaran", "2024-07-01", "HOSPITAL", "NICU graduate follow-up"),
            (
                "Cai",
                "Petrov",
                "2024-08-12",
                "PARENT",
                "Parent concern about motor milestones",
            ),
        ):
            child_id = create_child(
                api, first_name=first_name, last_name=last_name, date_of_birth=dob
            )
            if last_name == "Oyelaran":
                second_child_id = child_id
            referral_ids.append(
                create_referral(
                    api,
                    child_id,
                    primary_referral_source=source,
                    referral_received_date=RECEIVED_DATE,
                    presenting_concern=concern,
                )
            )

        first_page, first_meta = validate_paginated(
            api.list_referrals(ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_referrals(ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        walked = [row["id"] for row in first_page] + [row["id"] for row in second_page]
        assert len(set(walked)) == 3
        assert set(walked) == set(referral_ids)

        filtered, filtered_meta = validate_paginated(
            api.list_referrals(ADMIN_HEADERS, {"child_id": second_child_id})
        )
        assert len(filtered) == 1
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == referral_ids[1]

    def test_out_of_range_paging_parameters_are_their_own_rejection(self, api):
        """
        A zero page size and a negative offset are both refused by the pagination
        guard rather than by the body validator, and neither rejected read
        disturbs the collection.

        PRD 2.3: "A `limit` or `offset` that is not an integer, or that falls
        outside the accepted range for the parameter, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400); for the purposes of this check the
        service accepts `limit` values from 1 through 200 and `offset` values of 0
        or greater as syntactically valid integers, while the effective page size
        ceiling remains 100."

        Design: Corner/entities/referral_listing_with_zero_limit_returns_400
        """
        _at_intake(api)
        child_id = create_child(api)
        referral_id = create_referral(api, child_id)

        validate_error(
            api.list_referrals(ADMIN_HEADERS, {"limit": 0, "offset": 0}),
            ApiErrorId.INVALID_PAGINATION.value,
            400,
        )
        validate_error(
            api.list_referrals(ADMIN_HEADERS, {"limit": 1, "offset": -1}),
            ApiErrorId.INVALID_PAGINATION.value,
            400,
        )

        rows, meta = validate_paginated(api.list_referrals(ADMIN_HEADERS))
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [referral_id]
        assert rows[0]["version"] == 1


# ─── Existence, resolved per entity type ──────────────────────────────

NOT_FOUND_PROBES = (
    (
        "child",
        ApiErrorId.CHILD_NOT_FOUND.value,
        lambda api: api.get_child(NON_EXISTENT_UUID, INTAKE_HEADERS),
    ),
    (
        "referral",
        ApiErrorId.REFERRAL_NOT_FOUND.value,
        lambda api: api.get_referral(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "coordinator",
        ApiErrorId.COORDINATOR_NOT_FOUND.value,
        lambda api: api.get_coordinator(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "assessment",
        ApiErrorId.ASSESSMENT_NOT_FOUND.value,
        lambda api: api.complete_assessment(
            NON_EXISTENT_UUID,
            factories.complete_assessment_payload(RECEIVED_DATE),
            EVALUATOR_HEADERS,
        ),
    ),
    (
        "ifsp",
        ApiErrorId.IFSP_NOT_FOUND.value,
        lambda api: api.get_ifsp(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "ifsp_service",
        ApiErrorId.IFSP_SERVICE_NOT_FOUND.value,
        lambda api: api.get_ifsp_service(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "provider",
        ApiErrorId.PROVIDER_NOT_FOUND.value,
        lambda api: api.get_provider(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "authorization",
        ApiErrorId.AUTHORIZATION_NOT_FOUND.value,
        lambda api: api.get_authorization(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "visit",
        ApiErrorId.VISIT_NOT_FOUND.value,
        lambda api: api.get_visit(NON_EXISTENT_UUID, ADMIN_HEADERS),
    ),
    (
        "cost_share",
        ApiErrorId.COST_SHARE_NOT_FOUND.value,
        lambda api: api.get_cost_share(NON_EXISTENT_UUID, FISCAL_HEADERS),
    ),
    (
        "transition_plan",
        ApiErrorId.TRANSITION_PLAN_NOT_FOUND.value,
        lambda api: api.notify_lea(
            NON_EXISTENT_UUID,
            factories.notify_lea_payload(
                notification_date=RECEIVED_DATE, lea_code="LEA_NORTH"
            ),
            make_service_coordinator_headers(NON_EXISTENT_UUID),
        ),
    ),
)


class TestUnknownIdentifiers:
    """Eleven entity types, eleven distinct 404 identifiers."""

    @pytest.mark.parametrize(
        "expected_error, probe",
        [
            pytest.param(error, probe, id=name)
            for name, error, probe in NOT_FOUND_PROBES
        ],
    )
    def test_unknown_identifier_reports_the_entity_scoped_not_found(
        self, api, expected_error, probe
    ):
        """
        A syntactically valid identifier that was never issued fails against the
        entity it was meant to name, never a single collapsed generic code, and it
        fails there before any later rule the same request would also break.

        PRD 2.8: "Existence of referenced rows, resolved **left to right along the
        URL path first and then across body foreign keys in declaration order**."

        PRD 2.8: "A `child_id` in path or body must resolve to a `Child` or the
        request fails with `ERR_CHILD_NOT_FOUND` (404) — this applies to `GET
        /ei/children/{childId}` and `POST /ei/referrals`."

        Design: Corner/entities/unknown_identifiers_return_entity_scoped_not_found
        """
        _at_intake(api)

        error = validate_error(probe(api), expected_error, 404)
        assert error["message"]


# ─── The closed input surface ─────────────────────────────────────────

class TestRejectedBodies:
    """Presence, domain and closure, all reported at the shape rung."""

    def test_omitted_mandatory_field_is_refused_and_writes_nothing(self, api):
        """
        A field the contract lists as an input without a default is mandatory, so
        an intake missing the family name and a registration missing the caseload
        ceiling are both refused with nothing written behind them.

        PRD 3.1: "An `IntakeSpecialist` registers a child record carrying the
        child's `first_name`, `last_name`, `date_of_birth`, the `county_code` of
        residence, and the family's `primary_language` as an uppercase code such
        as `EN` or `ES`."

        Design: Corner/entities/child_creation_missing_required_field_returns_400
        """
        _at_intake(api)

        validate_error(
            api.create_child(
                {
                    "first_name": "Ada",
                    "date_of_birth": "2024-06-15",
                    "county_code": "CNT_A",
                    "primary_language": "EN",
                },
                INTAKE_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api.create_coordinator(
                {
                    "full_name": "Dana Reyes",
                    "county_code": "CNT_A",
                    "language_codes": ["EN"],
                },
                ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        # No partial row was written by either rejected call.
        validate_error(
            api.get_child(NON_EXISTENT_UUID, INTAKE_HEADERS),
            ApiErrorId.CHILD_NOT_FOUND.value,
            404,
        )

    def test_enum_token_outside_its_domain_is_refused(self, api):
        """
        A referral source that is not one of the eight federally reported tokens
        is refused at the shape rung, before the child counter can move.

        PRD 3.1: "A referral is opened with the `child_id` of the registered
        child, the `primary_referral_source` that federal reporting requires — one
        of `PHYSICIAN`, `HOSPITAL`, `PARENT`, `CHILD_CARE`, `SOCIAL_SERVICES`,
        `PUBLIC_HEALTH`, `EARLY_HEAD_START` or `OTHER` — the
        `referral_received_date` on which the program actually received the
        referral, the serving `county_code` for the case, and a narrative
        `presenting_concern` explaining why the child was referred."

        Design: Corner/entities/referral_invalid_enum_and_out_of_range_values_rejected
        """
        _at_intake(api)
        child_id = create_child(api)

        validate_error(
            api.create_referral(
                factories.referral_payload(
                    child_id, primary_referral_source="FRIEND_OF_FAMILY"
                ),
                INTAKE_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        assert read_child(api, child_id)["active_referral_count"] == 0

    def test_numeric_value_below_its_declared_floor_is_refused(self, api):
        """
        A caseload ceiling under the declared minimum is refused at the same rung
        as a bad enum, because range is part of shape.

        PRD 3.2: "A `ProgramAdmin` registers each service coordinator with a
        `full_name`, the `county_code` they serve, the `language_codes` they can
        serve families in directly (a non-empty array of uppercase tokens), and
        `max_weighted_caseload_points` — the state caseload standard expressed as
        a ceiling in weighted points, between 1.00 and 40.00 inclusive with two
        decimals."

        Design: Corner/entities/referral_invalid_enum_and_out_of_range_values_rejected
        """
        _at_intake(api)

        validate_error(
            api.create_coordinator(
                factories.coordinator_payload(max_weighted_caseload_points=0.5),
                ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_computed_and_system_fields_may_not_be_seeded_by_the_caller(self, api):
        """
        The input surface is closed: a caller can neither pre-fill a derived date
        nor hand the case a lifecycle status, because an unrecognised body key is
        rejected outright rather than quietly dropped.

        PRD 2.8: "Payload shape — `ERR_INVALID_REQUEST` (400): the body parses,
        contains every required input field, contains no unknown field, and every
        value matches its declared type, enum domain and numeric range. Applies to
        every endpoint."

        Design: Corner/entities/computed_and_system_fields_supplied_by_the_caller_are_rejected
        """
        _at_intake(api)
        child_id = create_child(api)

        validate_error(
            api.create_child(
                factories.child_payload(
                    first_name="Ben",
                    last_name="Oyelaran",
                    date_of_birth="2024-07-01",
                    third_birthday_date="2030-01-01",
                ),
                INTAKE_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api.create_referral(
                factories.referral_payload(child_id, status="ACTIVE_SERVICES"),
                INTAKE_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        assert read_child(api, child_id)["active_referral_count"] == 0


# ─── Foreign keys resolved on the body, not on the URL ─────────────────

class TestBodyForeignKeys:
    """Peer collections joined by explicit keys must still resolve."""

    def test_assessment_against_an_unknown_case_is_refused_on_existence(self, api):
        """
        An assessment naming a case that does not exist fails on the case, not on
        the domain-completeness rule the same body also breaks, and no assessment
        row is left behind.

        PRD 2.8: "A `referralId` in the path or a `referral_id` in the body must
        resolve to a `Referral` or the request fails with `ERR_REFERRAL_NOT_FOUND`
        (404) — this applies to every endpoint under `/ei/referrals/{referralId}/`
        plus `POST /ei/assessments`, `POST /ei/ifsps` and `POST /ei/cost-shares`."

        Design: Corner/entities/assessment_requires_an_existing_parent_referral
        """
        _at_intake(api)

        validate_error(
            api.create_assessment(
                factories.assessment_payload(
                    NON_EXISTENT_UUID,
                    assessment_type="INITIAL_EVALUATION",
                    scheduled_date="2026-03-10",
                    domains_assessed=[
                        "PHYSICAL",
                        "COGNITIVE",
                        "COMMUNICATION",
                        "SOCIAL_EMOTIONAL",
                    ],
                ),
                EVALUATOR_HEADERS,
            ),
            ApiErrorId.REFERRAL_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(
            api.list_assessments(ADMIN_HEADERS, {"referral_id": NON_EXISTENT_UUID})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_service_line_against_an_unknown_plan_is_refused_on_existence(self, api):
        """
        A service line naming a plan that does not exist is refused rather than
        written as an orphan, and the collection stays empty.

        PRD 2.8: "An `ifspId` in the path, an `ifsp_id` in the body, and a
        `supersedes_ifsp_id` when supplied must each resolve to an `IFSP` or the
        request fails with `ERR_IFSP_NOT_FOUND` (404) — applying to `GET
        /ei/ifsps/{ifspId}`, `POST /ei/ifsps/{ifspId}/consent`, `POST
        /ei/ifsp-services` and `POST /ei/transition-plans`."

        Design: Corner/entities/ifsp_service_create_with_unknown_plan_returns_404
        """
        _at_intake(api)

        validate_error(
            api.create_ifsp_service(
                factories.ifsp_service_payload(NON_EXISTENT_UUID),
                ADMIN_HEADERS,
            ),
            ApiErrorId.IFSP_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(
            api.list_ifsp_services(ADMIN_HEADERS, {"ifsp_id": NON_EXISTENT_UUID})
        )
        assert rows == []
        assert meta["total_count"] == 0


# ─── The one append-only register ─────────────────────────────────────

class TestContactRegister:
    """The single entity that carries no version and no updated_at."""

    def test_contact_entry_is_written_once_and_carries_no_version(self, api):
        """
        A logged contact carries an identifier and a creation stamp and nothing
        else from the audit set, takes its case from the path, and reads back
        exactly as written.

        PRD 2.4: "A `ContactLog` therefore carries only `id` and `created_at` — it
        has **no** `updated_at` field and **no** `version` field, and neither
        should appear in its representation."

        Design: Corner/entities/contact_log_is_append_only_with_no_version_field
        """
        case = build_active_services(api)

        entry = validate_success(
            api.create_contact_log(
                case.referral_id,
                factories.contact_log_payload(
                    contact_date="2026-03-20",
                    contact_method="HOME_VISIT",
                    contact_type="MONTHLY_CHECK_IN",
                    summary="Reviewed speech goals with the family in the home",
                ),
                case.coordinator_headers,
            ),
            201,
        )

        assert_append_only_row(entry)
        assert entry["referral_id"] == case.referral_id
        assert entry["contact_month"] == "2026-03"
        assert entry["qualifies_for_monthly_requirement"] is True

        stored = validate_success(
            api.get_contact_log(entry["id"], ADMIN_HEADERS), 200
        )
        assert stored == entry
        assert_append_only_row(stored)


# ─── The many-to-many funding junction ────────────────────────────────

SECOND_LINE = {
    "service_type": "DEVELOPMENTAL_INSTRUCTION",
    "setting_code": "HOME",
    "frequency_per_month": 2,
    "units_per_session": 2,
    "unit_rate_cents": 5500,
    "planned_units_total": 40,
}
FIRST_WINDOW = {"start_date": "2026-03-21", "end_date": "2026-04-30"}
SECOND_WINDOW = {"start_date": "2026-05-01", "end_date": "2026-05-31"}


def _build_two_line_plan_funded_by_two_providers(api):
    """Two consented lines, two credentialed providers, three authorizations:
    line 1 funded twice over disjoint windows, provider 1 funding both lines."""
    case = build_active_services(api)
    second_line_id = add_service_line(api, case.ifsp_id, **SECOND_LINE)
    case.line_ids.append(second_line_id)
    # The added line reopens the consent cycle, which must be closed before any
    # authorization may be written.
    record_consent(api, case.ifsp_id, case.child_id, consent_signed_date="2026-03-20")

    both_types_id = create_provider(
        api,
        agency_name="Riverbend Therapy",
        qualified_service_types=["SPEECH_THERAPY", "DEVELOPMENTAL_INSTRUCTION"],
        credential_expiry_date="2027-06-30",
    )
    speech_only_id = create_provider(
        api,
        agency_name="Lakeside Early Learning",
        qualified_service_types=["SPEECH_THERAPY"],
        credential_expiry_date="2027-06-30",
    )
    case.provider_ids.extend([both_types_id, speech_only_id])

    authorizations = [
        validate_success(
            api.create_authorization(
                factories.authorization_payload(
                    line_id, provider_id, authorized_units=units, **window
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        for line_id, provider_id, units, window in (
            (case.line_id, both_types_id, 24, FIRST_WINDOW),
            (case.line_id, speech_only_id, 12, SECOND_WINDOW),
            (second_line_id, both_types_id, 10, FIRST_WINDOW),
        )
    ]
    case.authorization_ids.extend(row["id"] for row in authorizations)
    return case, second_line_id, both_types_id, speech_only_id, authorizations


class TestFundingJunction:
    """One line funded by two providers, one provider funding two lines."""

    def test_each_line_keeps_its_own_pool_and_its_own_pinned_rate(self, api):
        """
        Three authorizations across two lines draw only on the pool of the line
        each one names, and each carries the rate of that line rather than
        anything belonging to the provider.

        PRD 3.6: "A line's `units_committed` is the sum of `authorized_units` over
        its authorizations in `ACTIVE`, `EXHAUSTED` or `SUSPENDED`, plus, for each
        authorization in `REVOKED`, that authorization's `authorized_units` minus
        its `units_released`, plus the same quantity for each authorization in
        `EXPIRED`."

        Design: Corner/entities/provider_authorization_junction_links_many_lines_to_many_providers
        """
        (
            case,
            second_line_id,
            _both_types_id,
            _speech_only_id,
            authorizations,
        ) = _build_two_line_plan_funded_by_two_providers(api)

        assert [row["status"] for row in authorizations] == ["ACTIVE"] * 3
        assert authorizations[0]["unit_rate_cents"] == 6_500
        assert authorizations[2]["unit_rate_cents"] == 5_500

        assert_unit_pool(
            read_service_line(api, case.line_id),
            units_committed=36,
            units_pool_remaining=60,
            planned_units_total=96,
        )
        assert_unit_pool(
            read_service_line(api, second_line_id),
            units_committed=10,
            units_pool_remaining=30,
            planned_units_total=40,
        )

        # The May window is admitted only because it starts the day after the
        # April window ends.
        assert authorizations[1]["start_date"] == "2026-05-01"
        assert authorizations[0]["end_date"] == "2026-04-30"

    def test_the_junction_lists_slice_by_line_and_by_provider(self, api):
        """
        The same three rows read as two by line and two by provider, and each
        provider's live authorization count reports its own share.

        PRD 2.3: "Authorization listing filters on `ifsp_service_id`,
        `provider_id` and `status`."

        Design: Corner/entities/provider_authorization_junction_links_many_lines_to_many_providers
        """
        (
            case,
            _second_line_id,
            both_types_id,
            speech_only_id,
            authorizations,
        ) = _build_two_line_plan_funded_by_two_providers(api)

        by_line, line_meta = validate_paginated(
            api.list_authorizations(ADMIN_HEADERS, {"ifsp_service_id": case.line_id})
        )
        assert line_meta["total_count"] == 2
        assert {row["id"] for row in by_line} == {
            authorizations[0]["id"],
            authorizations[1]["id"],
        }

        by_provider, provider_meta = validate_paginated(
            api.list_authorizations(ADMIN_HEADERS, {"provider_id": both_types_id})
        )
        assert provider_meta["total_count"] == 2
        assert {row["id"] for row in by_provider} == {
            authorizations[0]["id"],
            authorizations[2]["id"],
        }

        assert read_provider(api, both_types_id)["active_authorization_count"] == 2
        assert read_provider(api, speech_only_id)["active_authorization_count"] == 1
