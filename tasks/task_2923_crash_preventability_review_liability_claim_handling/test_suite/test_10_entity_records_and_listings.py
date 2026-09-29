"""Record shapes, declared defaults and reverse-reachable listings.

The probes here stay on the record layer of the contract: what a freshly
created row carries, what a read re-serialises, how a collection paginates and
filters, and which not-found code each addressable collection owns.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_array_envelope,
    assert_cents,
    assert_common_fields,
    assert_declared_fields,
    assert_error_envelope,
    assert_id_set,
    assert_instants_equal,
    assert_multiplier,
    assert_object_envelope,
    assert_page,
    assert_rate,
    assert_score_2dp,
    assert_timestamp_shape,
)
from test_helpers.constants import (
    ABSENT_UUIDS,
    BALLOT_DISPOSITION_ABSTAIN,
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIM_HANDLING_NEGOTIATION,
    CLAIM_HANDLING_SETUP,
    CLAIMANT_TYPE_PROPERTY,
    CLOCK_EPOCH,
    DEFAULT_LIMIT,
    DEMAND_STATE_DEMANDED,
    EVIDENCE_POSTURE_PARTIAL,
    EVIDENCE_TELEMATICS,
    MAX_LIMIT,
    PRESERVATION_PRESERVED,
    PREVENTABILITY_REPORTED,
    REPORTING_STATUS_NOT_REQUIRED,
    REPORTING_STATUS_PENDING_FILING,
    RESERVE_STATUS_PROVISIONAL,
    REVIEW_STATE_DELIBERATION,
    RISK_TIER_STANDARD,
    ROUTE_CLASS_LOCAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    STAFFING_POSTURE_OK,
    TOW_REASON_CONVENIENCE,
    TOW_REASON_DISABLING_DAMAGE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    AUDITOR,
    CLAIMS_ADJUSTER,
    COMMITTEE_ONE,
    DISPATCHER,
    SAFETY_ADMIN,
    build_claim,
    build_crash,
    build_driver,
    build_preserved_evidence,
    build_review_case,
    build_statement,
    build_terminal,
    open_deliberation,
)
from test_helpers.types import (
    CLAIM_FIELDS,
    COMMITTEE_VOTE_FIELDS,
    CRASH_FIELDS,
    DEMAND_FIELDS,
    DRIVER_STATEMENT_FIELDS,
    TERMINAL_FIELDS,
)

MODERATE_RESERVE_BASE_CENTS = 2_500_000


def _decimal(value) -> Decimal:
    """Read a declared decimal back without inviting binary float noise."""
    return Decimal(str(value))


class TestTerminalRegistrationRecord:
    """A freshly registered terminal publishes its whole declared shape."""

    def test_registration_returns_every_declared_field_at_its_empty_value(
        self, api: ApiClient
    ):
        """The six computed counters read as an empty fleet, not as nulls.

        PRD: "A freshly registered terminal reports zero for every counter and
        an `OK` `staffing_posture`."

        Design: Corner/entities/terminal_creation_returns_all_declared_fields_with_defaults
        """
        response = api.create_terminal(
            factories.terminal_payload(
                name="Springfield Terminal",
                terminal_code="SPR01",
                region_code="OH",
                annual_miles_millions=4.0,
            ),
            SAFETY_ADMIN,
        )

        created = validate_success(response, 201)
        assert_object_envelope(response.json())
        assert_common_fields(created, expected_version=1)
        assert_declared_fields(created, TERMINAL_FIELDS)

        assert created["name"] == "Springfield Terminal"
        assert created["terminal_code"] == "SPR01"
        assert created["region_code"] == "OH"
        assert _decimal(created["annual_miles_millions"]) == Decimal("4.0")

        assert created["active_driver_count"] == 0
        assert created["suspended_driver_count"] == 0
        assert created["staffing_posture"] == STAFFING_POSTURE_OK
        assert created["preventable_crash_count"] == 0
        assert_rate(created["crash_rate_per_million_miles"], 0.000)
        assert created["risk_tier"] == RISK_TIER_STANDARD
        assert created["late_filing_count"] == 0

        assert_timestamp_shape(created["created_at"], "created_at")
        assert_timestamp_shape(created["updated_at"], "updated_at")
        assert_instants_equal(created["updated_at"], created["created_at"], "updated_at")


def _recordable_moderate_crash(api: ApiClient) -> dict:
    """A towed-away moderate crash on a two-million-mile terminal."""
    terminal = build_terminal(
        api,
        name="Tiffin Terminal",
        terminal_code="TIF01",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-2001",
        full_name="Ida Vaszary",
        cdl_number="OH-CDL-2001",
        hire_date="2012-04-09",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T16:45:00Z",
        notified_at="2026-07-29T17:10:00Z",
        location_text="SR-18 at Township Rd 96",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=True,
        tow_reason=TOW_REASON_DISABLING_DAMAGE,
    )
    return {"terminal": terminal, "driver": driver, "crash": crash}


class TestCrashRetrievalRecord:
    """A single-crash read re-serialises the frozen fields it was born with."""

    def test_the_read_returns_the_stored_intake_and_the_frozen_recordability(
        self, api: ApiClient
    ):
        """Recordability was decided once, and the read hands it back unchanged.

        PRD: "Recordability is decided once, at intake, and then frozen. ... A
        tow contributes `DISABLING_TOW` only when `tow_away` is true *and*
        `tow_reason` is `DISABLING_DAMAGE`"

        Design: Corner/entities/crash_retrieval_returns_stored_and_derived_fields
        """
        context = _recordable_moderate_crash(api)

        response = api.get_crash(context["crash"]["id"], AUDITOR)
        crash = validate_success(response)
        assert_object_envelope(response.json())
        assert_declared_fields(crash, CRASH_FIELDS)

        assert_instants_equal(crash["occurred_at"], "2026-07-29T16:45:00Z", "occurred_at")
        assert crash["location_text"] == "SR-18 at Township Rd 96"
        assert crash["severity"] == SEVERITY_MODERATE
        assert crash["route_class"] == ROUTE_CLASS_REGIONAL
        assert crash["tow_away"] is True
        assert crash["tow_reason"] == TOW_REASON_DISABLING_DAMAGE
        assert crash["injury_transported_count"] == 0
        assert crash["fatality_count"] == 0
        assert crash["hazmat_release"] is False
        assert crash["mechanical_factor"] is False
        assert crash["third_party_at_fault"] is False

        assert crash["dot_recordable"] is True
        assert crash["recordability_codes"] == ["DISABLING_TOW"]
        assert_instants_equal(crash["report_due_at"], "2026-08-01T16:45:00Z", "report_due_at")
        assert crash["reporting_status"] == REPORTING_STATUS_PENDING_FILING

    def test_the_kept_notification_instant_is_the_clock_not_the_supplied_value(
        self, api: ApiClient
    ):
        """Intake mints its own notification instant, and the read is not a write.

        PRD: "the `notified_at` the crash keeps is the logical-clock instant at
        which intake was processed."

        Design: Corner/entities/crash_retrieval_returns_stored_and_derived_fields
        """
        context = _recordable_moderate_crash(api)

        crash = validate_success(api.get_crash(context["crash"]["id"], AUDITOR))

        assert_instants_equal(crash["notified_at"], CLOCK_EPOCH, "notified_at")
        assert crash["terminal_id"] == context["terminal"]["id"]
        assert crash["driver_id"] == context["driver"]["id"]
        assert crash["preventability_status"] == PREVENTABILITY_REPORTED
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_PARTIAL
        assert crash["appeals_exhausted"] is False
        assert crash["version"] == 1
        assert crash["filing_reference"] is None
        assert crash["filed_at"] is None


UPPER_SANDUSKY_CRASHES = (
    ("2026-07-25T08:00:00Z", "2026-07-25T08:15:00Z", "US-30 MM 60", SEVERITY_MODERATE,
     ROUTE_CLASS_REGIONAL),
    ("2026-07-26T08:00:00Z", "2026-07-26T08:15:00Z", "US-30 MM 62", SEVERITY_MODERATE,
     ROUTE_CLASS_REGIONAL),
    ("2026-07-27T08:00:00Z", "2026-07-27T08:15:00Z", "Dock 4", SEVERITY_MINOR,
     ROUTE_CLASS_LOCAL),
)


def _three_crashes_on_one_driver(api: ApiClient) -> dict:
    """Two regional moderate crashes and one local minor crash."""
    terminal = build_terminal(
        api,
        name="Upper Sandusky Terminal",
        terminal_code="UPS01",
        region_code="OH",
        annual_miles_millions=3.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-2101",
        full_name="Jonas Ferreira",
        cdl_number="OH-CDL-2101",
        hire_date="2013-01-15",
    )
    crashes = []
    for occurred_at, notified_at, location_text, severity, route_class in UPPER_SANDUSKY_CRASHES:
        crashes.append(
            build_crash(
                api,
                driver["id"],
                terminal["id"],
                occurred_at=occurred_at,
                notified_at=notified_at,
                location_text=location_text,
                severity=severity,
                route_class=route_class,
            )
        )
    return {"terminal": terminal, "driver": driver, "crashes": crashes}


class TestCrashCollectionPaging:
    """Three rows, a two-row window and a filter that runs before the window."""

    def test_two_windows_partition_the_three_rows_without_repeating_one(
        self, api: ApiClient
    ):
        """total_count counts the matches, has_more reports what is left over.

        PRD: "`total_count` is the number of rows matching the request's filters
        before the page window is applied, and `has_more` is true exactly when
        rows matching the filters remain beyond the current window."

        Design: Corner/entities/crashes_listing_paginates_with_total_count_and_has_more
        """
        context = _three_crashes_on_one_driver(api)
        expected_ids = [crash["id"] for crash in context["crashes"]]

        first_response = api.list_crashes(AUDITOR, {"limit": 2, "offset": 0})
        first_page, first_meta = validate_paginated(first_response)
        assert_array_envelope(first_response.json())
        assert len(first_page) == 2
        assert_page(first_meta, total_count=3, has_more=True, limit=2, offset=0)

        second_page, second_meta = validate_paginated(
            api.list_crashes(AUDITOR, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert_page(second_meta, total_count=3, has_more=False, limit=2, offset=2)

        assert_id_set(list(first_page) + list(second_page), expected_ids)

    def test_the_severity_filter_narrows_the_count_before_the_page_is_cut(
        self, api: ApiClient
    ):
        """One row matches, and an unpaged read publishes the declared default.

        PRD: "`limit` controls page size: it defaults to 10"

        Design: Corner/entities/crashes_listing_paginates_with_total_count_and_has_more
        """
        context = _three_crashes_on_one_driver(api)
        minor_crash = context["crashes"][2]

        filtered, filtered_meta = validate_paginated(
            api.list_crashes(AUDITOR, {"severity": SEVERITY_MINOR})
        )
        assert len(filtered) == 1
        assert filtered[0]["id"] == minor_crash["id"]
        assert_page(filtered_meta, total_count=1, has_more=False, limit=DEFAULT_LIMIT, offset=0)

        unpaged, unpaged_meta = validate_paginated(api.list_crashes(AUDITOR))
        assert len(unpaged) == 3
        assert_page(unpaged_meta, total_count=3, has_more=False, limit=DEFAULT_LIMIT, offset=0)


class TestEveryAddressableCollectionOwnsItsNotFoundCode:
    """Ten single-resource reads, ten distinct entity-scoped 404 codes."""

    def test_each_absent_uuid_earns_the_code_of_the_collection_addressed(
        self, api: ApiClient
    ):
        """A well-formed absent identifier never collapses to a shared code.

        PRD: "Every entity type has its own not-found error, and it is used both
        for an unresolvable `{id}` in the path and for an unresolvable identifier
        supplied in a request body: `ERR_TERMINAL_NOT_FOUND`,
        `ERR_DRIVER_NOT_FOUND`, `ERR_CRASH_NOT_FOUND`,
        `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_REVIEW_CASE_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_POLICY_LAYER_NOT_FOUND`,
        `ERR_DEMAND_NOT_FOUND`, `ERR_DISCIPLINARY_ACTION_NOT_FOUND` and
        `ERR_SUBROGATION_DEMAND_NOT_FOUND`, each answering HTTP 404."

        Design: Corner/entities/not_found_uuid_on_every_addressable_collection_returns_entity_scoped_error
        """
        probes = (
            (api.get_terminal, ABSENT_UUIDS[0], ApiErrorId.TERMINAL_NOT_FOUND),
            (api.get_driver, ABSENT_UUIDS[1], ApiErrorId.DRIVER_NOT_FOUND),
            (api.get_crash, ABSENT_UUIDS[2], ApiErrorId.CRASH_NOT_FOUND),
            (api.get_evidence_item, ABSENT_UUIDS[3], ApiErrorId.EVIDENCE_ITEM_NOT_FOUND),
            (api.get_review_case, ABSENT_UUIDS[4], ApiErrorId.REVIEW_CASE_NOT_FOUND),
            (api.get_claim, ABSENT_UUIDS[5], ApiErrorId.CLAIM_NOT_FOUND),
            (api.get_policy_layer, ABSENT_UUIDS[6], ApiErrorId.POLICY_LAYER_NOT_FOUND),
            (api.get_demand, ABSENT_UUIDS[7], ApiErrorId.DEMAND_NOT_FOUND),
            (
                api.get_disciplinary_action,
                ABSENT_UUIDS[8],
                ApiErrorId.DISCIPLINARY_ACTION_NOT_FOUND,
            ),
            (
                api.get_subrogation_demand,
                ABSENT_UUIDS[9],
                ApiErrorId.SUBROGATION_DEMAND_NOT_FOUND,
            ),
        )

        for read, absent_id, expected in probes:
            response = read(absent_id, AUDITOR)
            assert response.status_code == 404, (
                f"{expected.value} should answer HTTP 404, got {response.status_code}"
            )
            error = assert_error_envelope(response.json())
            assert error["error_id"] == expected.value, (
                f"expected {expected.value}, got {error['error_id']}"
            )
            assert "id" not in error, "an error payload carries no entity data"
            assert "version" not in error, "an error payload carries no entity data"


class TestDriverCreationRequiredInputs:
    """The refusal of an incomplete payload leaves nothing at all behind."""

    def test_omitting_the_licence_number_is_refused_and_persists_nothing(
        self, api: ApiClient
    ):
        """A missing required input is a request-shape failure with no side effect.

        PRD: "The body parses as JSON, contains no unknown fields, contains every
        required input, and every present value matches its declared type, enum
        domain and range constraint ... Any violation is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/driver_creation_missing_required_cdl_number_returns_invalid_request
        """
        terminal = build_terminal(
            api,
            name="Van Wert Terminal",
            terminal_code="VAN01",
            region_code="OH",
            annual_miles_millions=1.5,
        )

        refused = api.create_driver(
            factories.driver_payload(
                terminal["id"],
                employee_code="D-2201",
                full_name="Kaya Lindqvist",
                hire_date="2016-08-22",
                cdl_number=factories.DROP,
            ),
            SAFETY_ADMIN,
        )
        validate_error(refused, ApiErrorId.INVALID_REQUEST.value, 400)

        empty, empty_meta = validate_paginated(
            api.list_drivers(SAFETY_ADMIN, {"terminal_id": terminal["id"]})
        )
        assert empty == []
        assert_page(empty_meta, total_count=0, has_more=False)

        accepted = validate_success(
            api.create_driver(
                factories.driver_payload(
                    terminal["id"],
                    employee_code="D-2201",
                    full_name="Kaya Lindqvist",
                    cdl_number="OH-CDL-2201",
                    hire_date="2016-08-22",
                ),
                SAFETY_ADMIN,
            ),
            201,
        )
        assert_common_fields(accepted, expected_version=1)
        assert accepted["employee_code"] == "D-2201"

        after = validate_success(api.get_terminal(terminal["id"], SAFETY_ADMIN))
        assert after["active_driver_count"] == 1


def _claim_awaiting_its_first_demand(api: ApiClient) -> dict:
    """A moderate crash with a claim opened on it and no demand yet."""
    terminal = build_terminal(
        api,
        name="Wapakoneta Terminal",
        terminal_code="WAP01",
        region_code="OH",
        annual_miles_millions=2.5,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-2301",
        full_name="Lars Wembley",
        cdl_number="OH-CDL-2301",
        hire_date="2010-11-30",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T13:00:00Z",
        notified_at="2026-07-29T13:20:00Z",
        location_text="SR-501 at Bellefontaine St",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
    )
    claim = build_claim(api, crash["id"], claimant_notice_date="2026-07-30")
    return {"terminal": terminal, "driver": driver, "crash": crash, "claim": claim}


class TestDemandCreationDefaults:
    """The declared defaults of a demand, observed on a claim that did move."""

    def test_the_claim_opens_on_its_two_declared_initial_states(self, api: ApiClient):
        """Handling and reserve each start where the contract says they start.

        PRD: "A claim opens with `handling_status` of `SETUP` and
        `reserve_status` of `PROVISIONAL` ... At setup the provisional variant
        runs and its result is frozen into `provisional_reserve_cents`, which is
        never recomputed again, and the same figure seeds
        `outstanding_reserve_cents`."

        Design: Corner/entities/demand_creation_applies_declared_defaults
        """
        context = _claim_awaiting_its_first_demand(api)
        claim = context["claim"]

        assert claim["adjuster_note"] is None
        assert claim["handling_status"] == CLAIM_HANDLING_SETUP
        assert claim["reserve_status"] == RESERVE_STATUS_PROVISIONAL
        assert_cents(
            claim["provisional_reserve_cents"],
            MODERATE_RESERVE_BASE_CENTS,
            "provisional_reserve_cents",
        )
        assert_cents(
            claim["outstanding_reserve_cents"],
            MODERATE_RESERVE_BASE_CENTS,
            "outstanding_reserve_cents",
        )
        assert claim["revised_reserve_cents"] is None

    def test_a_new_demand_takes_its_declared_defaults_and_null_settlement_fields(
        self, api: ApiClient
    ):
        """Five inputs in, and every other field comes from the contract.

        PRD: "The demand is created in `DEMANDED` state with `next_round_index`
        at 1, `rescission_count` at 0, a null `settlement_reference` and nulls in
        `settled_amount_cents`, `alae_cents`, `settlement_total_cents` and
        `settled_at`; its derived `round_count` is the number of negotiation
        rounds recorded against it and reads 0 until the first offer. ... the
        first demand moves the claim `SETUP → NEGOTIATION`"

        Design: Corner/entities/demand_creation_applies_declared_defaults
        """
        context = _claim_awaiting_its_first_demand(api)
        claim_id = context["claim"]["id"]

        response = api.create_demand(
            claim_id,
            factories.demand_payload(
                claimant_name="Auglaize Mutual Insurance",
                claimant_type=CLAIMANT_TYPE_PROPERTY,
                demand_amount_cents=750_000,
                represented_by_counsel=False,
                demand_received_at="2026-07-31T10:00:00Z",
            ),
            CLAIMS_ADJUSTER,
        )
        demand = validate_success(response, 201)
        assert_object_envelope(response.json())
        assert_common_fields(demand, expected_version=1)
        assert_declared_fields(demand, DEMAND_FIELDS)

        assert demand["status"] == DEMAND_STATE_DEMANDED
        assert demand["next_round_index"] == 1
        assert demand["round_count"] == 0
        assert demand["rescission_count"] == 0
        assert demand["settled_amount_cents"] is None
        assert demand["alae_cents"] is None
        assert demand["settlement_total_cents"] is None
        assert demand["settled_at"] is None
        assert demand["settlement_reference"] is None

        moved = validate_success(api.get_claim(claim_id, CLAIMS_ADJUSTER))
        assert moved["handling_status"] == CLAIM_HANDLING_NEGOTIATION


def _terminal_and_driver_for_intake_probes(
    api: ApiClient,
    name: str,
    terminal_code: str,
    annual_miles_millions,
    employee_code: str,
    full_name: str,
    cdl_number: str,
    hire_date: str,
) -> dict:
    """One terminal and one driver, so every intake foreign key resolves."""
    terminal = build_terminal(
        api,
        name=name,
        terminal_code=terminal_code,
        region_code="OH",
        annual_miles_millions=annual_miles_millions,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code=employee_code,
        full_name=full_name,
        cdl_number=cdl_number,
        hire_date=hire_date,
    )
    return {"terminal": terminal, "driver": driver}


class TestComputedRecordabilityIsNotAClientInput:
    """The client cannot assert recordability, and the server disagrees with it."""

    def test_supplying_the_computed_flag_is_refused_and_the_server_derives_the_opposite(
        self, api: ApiClient
    ):
        """A convenience tow fires no code, whatever the request claimed.

        PRD: "A tow contributes `DISABLING_TOW` only when `tow_away` is true
        *and* `tow_reason` is `DISABLING_DAMAGE` — a unit towed for convenience
        is not a trigger ... `dot_recordable` is true when at least one code
        fired, and `recordability_codes` is an empty list when it is false."

        Design: Corner/entities/crash_computed_recordability_field_in_request_body_rejected
        """
        context = _terminal_and_driver_for_intake_probes(
            api,
            name="Xenia Terminal",
            terminal_code="XEN01",
            annual_miles_millions=2.0,
            employee_code="D-2401",
            full_name="Mira Osgood",
            cdl_number="OH-CDL-2401",
            hire_date="2017-05-05",
        )
        intake = dict(
            occurred_at="2026-07-31T07:00:00Z",
            notified_at="2026-07-31T07:05:00Z",
            location_text="Yard lane 3",
            severity=SEVERITY_MINOR,
            route_class=ROUTE_CLASS_LOCAL,
            tow_away=True,
            tow_reason=TOW_REASON_CONVENIENCE,
        )

        refused = api.create_crash(
            factories.crash_payload(
                context["driver"]["id"],
                context["terminal"]["id"],
                dot_recordable=True,
                **intake,
            ),
            DISPATCHER,
        )
        validate_error(refused, ApiErrorId.INVALID_REQUEST.value, 400)

        accepted = validate_success(
            api.create_crash(
                factories.crash_payload(
                    context["driver"]["id"], context["terminal"]["id"], **intake
                ),
                DISPATCHER,
            ),
            201,
        )
        assert accepted["dot_recordable"] is False
        assert accepted["recordability_codes"] == []
        assert accepted["report_due_at"] is None
        assert accepted["reporting_status"] == REPORTING_STATUS_NOT_REQUIRED

        rows, meta = validate_paginated(api.list_crashes(DISPATCHER))
        assert len(rows) == 1
        assert_page(meta, total_count=1, has_more=False)


class TestClaimCreationMintsItsSystemFields:
    """Everything a later action would set is left at its unset value."""

    def test_the_new_claim_carries_minted_identity_and_no_downstream_state(
        self, api: ApiClient
    ):
        """A claim on an unreviewed, partly documented crash scores 5 plus 5.

        PRD: "`litigation_risk_score` starts from the crash's preventability: 30
        points when the crash has been found `PREVENTABLE`, 10 while it is still
        `UNDER_REVIEW`, 5 while it is merely `REPORTED`, and nothing at all once
        it has been found `NON_PREVENTABLE`. The crash's evidence posture adds 25
        points when the record is `COMPROMISED`, 5 when it is `PARTIAL` and
        nothing when it is `COMPLETE`."

        Design: Corner/entities/claim_creation_mints_system_fields_and_common_fields
        """
        context = _terminal_and_driver_for_intake_probes(
            api,
            name="Yellow Springs Terminal",
            terminal_code="YSP01",
            annual_miles_millions=1.0,
            employee_code="D-2501",
            full_name="Nils Abernathy",
            cdl_number="OH-CDL-2501",
            hire_date="2009-02-02",
        )
        crash = build_crash(
            api,
            context["driver"]["id"],
            context["terminal"]["id"],
            occurred_at="2026-07-30T15:00:00Z",
            notified_at="2026-07-30T15:30:00Z",
            location_text="US-68 at Corry St",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_LOCAL,
        )

        response = api.create_claim(
            factories.claim_payload(
                crash["id"],
                claimant_notice_date="2026-07-31",
                adjuster_note="notice by letter",
            ),
            CLAIMS_ADJUSTER,
        )
        claim = validate_success(response, 201)
        assert_object_envelope(response.json())
        assert_common_fields(claim, expected_version=1)
        assert_declared_fields(claim, CLAIM_FIELDS)
        assert_instants_equal(claim["updated_at"], claim["created_at"], "updated_at")

        assert claim["litigation_risk_score"] == 10
        assert_multiplier(claim["litigation_risk_multiplier"], 1.00)
        assert claim["counsel_required"] is False
        assert claim["counsel_assigned"] is False
        assert claim["counsel_assigned_at"] is None
        assert claim["counsel_firm_name"] is None
        assert claim["litigation_flag"] is False
        assert claim["closed_at"] is None

    def test_every_money_bucket_starts_empty_while_the_exposure_is_the_reserve(
        self, api: ApiClient
    ):
        """Nothing paid, nothing released, and both totals equal the reserve.

        PRD: "`claim_exposure_cents` is defined as the sum of
        `outstanding_reserve_cents`, `indemnity_paid_cents`, `alae_paid_cents`
        and `reserve_released_cents` ... `total_incurred_cents`, which is
        `indemnity_paid_cents` plus `alae_paid_cents` plus
        `outstanding_reserve_cents` minus `subrogation_recovered_cents`"

        Design: Corner/entities/claim_creation_mints_system_fields_and_common_fields
        """
        context = _terminal_and_driver_for_intake_probes(
            api,
            name="Yellow Springs Terminal",
            terminal_code="YSP01",
            annual_miles_millions=1.0,
            employee_code="D-2501",
            full_name="Nils Abernathy",
            cdl_number="OH-CDL-2501",
            hire_date="2009-02-02",
        )
        crash = build_crash(
            api,
            context["driver"]["id"],
            context["terminal"]["id"],
            occurred_at="2026-07-30T15:00:00Z",
            notified_at="2026-07-30T15:30:00Z",
            location_text="US-68 at Corry St",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_LOCAL,
        )
        claim = build_claim(
            api,
            crash["id"],
            claimant_notice_date="2026-07-31",
            adjuster_note="notice by letter",
        )

        for field in (
            "indemnity_paid_cents",
            "alae_paid_cents",
            "reserve_released_cents",
            "subrogation_recovered_cents",
            "sir_eroded_cents",
            "insured_paid_cents",
        ):
            assert_cents(claim[field], 0, field)
        assert claim["layer_allocations"] == []
        assert_cents(
            claim["claim_exposure_cents"], MODERATE_RESERVE_BASE_CENTS, "claim_exposure_cents"
        )
        assert_cents(
            claim["total_incurred_cents"], MODERATE_RESERVE_BASE_CENTS, "total_incurred_cents"
        )


ADA_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-29T08:00:00Z",
    "window_end_at": "2026-07-29T10:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}

FIRST_BALLOT_SCORE = 1.00
SECOND_BALLOT_SCORE = 3.00


def _case_with_one_ballot_from_one_member(api: ApiClient) -> dict:
    """A deliberating case carrying a single non-preventable ballot."""
    terminal = build_terminal(
        api,
        name="Ada Terminal",
        terminal_code="ADA01",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-2701",
        full_name="Piotr Nowicki",
        cdl_number="OH-CDL-2701",
        hire_date="2014-06-06",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T09:00:00Z",
        notified_at="2026-07-29T09:10:00Z",
        location_text="SR-235 at Main St",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        mechanical_factor=False,
    )
    build_preserved_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-2701",
        **ADA_EVIDENCE_WINDOW,
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I scraped the mirror on a parked trailer.",
        conditions_note=None,
    )
    case = build_review_case(
        api, crash["id"], committee_name="Ada Safety Review Committee"
    )
    opened = open_deliberation(api, case["id"])
    after_first = validate_success(
        api.cast_vote(
            case["id"],
            factories.vote_payload(
                opened["version"],
                vote=BALLOT_DISPOSITION_NON_PREVENTABLE,
                scores=factories.uniform_criterion_scores(1),
                comment="first impression",
            ),
            COMMITTEE_ONE,
        ),
        201,
    )
    return {"crash": crash, "review_case": case, "after_first_ballot": after_first}


def _ballot_by_sequence(rows) -> dict:
    return {row["sequence_number"]: row for row in rows}


class TestCommitteeBallotsAreAppendOnly:
    """A member who changes his mind appends; the earlier row is not touched."""

    def test_the_second_ballot_appends_and_the_first_is_marked_superseded(
        self, api: ApiClient
    ):
        """Both ballots survive, and neither carries a version to update.

        PRD: "A ballot is never edited — a member who changes his mind casts a
        fresh ballot and the earlier one is marked `superseded`."

        Design: Corner/entities/committee_vote_is_append_only_with_no_version_field
        """
        context = _case_with_one_ballot_from_one_member(api)
        case_id = context["review_case"]["id"]

        validate_success(
            api.cast_vote(
                case_id,
                factories.vote_payload(
                    context["after_first_ballot"]["version"],
                    vote=BALLOT_DISPOSITION_PREVENTABLE,
                    scores=factories.uniform_criterion_scores(3),
                    comment="revised after reviewing the camera",
                ),
                COMMITTEE_ONE,
            ),
            201,
        )

        rows, meta = validate_paginated(api.list_votes(case_id, AUDITOR))
        assert_page(meta, total_count=2, has_more=False)
        assert len(rows) == 2
        ballots = _ballot_by_sequence(rows)
        assert set(ballots) == {1, 2}

        first = ballots[1]
        assert first["vote"] == BALLOT_DISPOSITION_NON_PREVENTABLE
        assert_score_2dp(
            first["weighted_member_score"], FIRST_BALLOT_SCORE, "weighted_member_score"
        )
        assert first["comment"] == "first impression"
        assert first["superseded"] is True

        second = ballots[2]
        assert second["vote"] == BALLOT_DISPOSITION_PREVENTABLE
        assert_score_2dp(
            second["weighted_member_score"], SECOND_BALLOT_SCORE, "weighted_member_score"
        )
        assert second["comment"] == "revised after reviewing the camera"
        assert second["superseded"] is False

        for row in rows:
            assert_append_only_fields(row)
            assert_declared_fields(row, COMMITTEE_VOTE_FIELDS)
            assert row["review_case_id"] == case_id

    def test_only_the_parent_carries_the_version_and_the_live_ballot_count(
        self, api: ApiClient
    ):
        """The case's counters move; the ledger rows have none to move.

        PRD: "The case's `next_vote_sequence` and `version` each increase by 1,
        and the response body is the updated review case rather than the ballot"

        Design: Corner/entities/committee_vote_is_append_only_with_no_version_field
        """
        context = _case_with_one_ballot_from_one_member(api)
        case_id = context["review_case"]["id"]
        before = context["after_first_ballot"]

        after = validate_success(
            api.cast_vote(
                case_id,
                factories.vote_payload(
                    before["version"],
                    vote=BALLOT_DISPOSITION_PREVENTABLE,
                    scores=factories.uniform_criterion_scores(3),
                    comment="revised after reviewing the camera",
                ),
                COMMITTEE_ONE,
            ),
            201,
        )

        assert after["version"] == before["version"] + 1
        assert after["next_vote_sequence"] == 3
        assert after["active_vote_count"] == 1
        assert after["abstain_count"] == 0

        live, live_meta = validate_paginated(
            api.list_votes(case_id, AUDITOR, {"superseded": "false"})
        )
        assert_page(live_meta, total_count=1, has_more=False)
        assert len(live) == 1
        assert live[0]["sequence_number"] == 2
        assert live[0]["vote"] == BALLOT_DISPOSITION_PREVENTABLE


class TestDomainAndPaginationBounds:
    """Three shapes of the same refusal: an enum, a count and a page size."""

    def test_an_out_of_domain_enum_and_a_negative_count_are_both_refused(
        self, api: ApiClient
    ):
        """Neither the severity domain nor the non-negativity rule bends.

        PRD: "The classification fields are `severity`, one of `MINOR`,
        `MODERATE`, `SEVERE` or `CATASTROPHIC` ... `injury_transported_count`,
        the number of people taken from the scene for immediate medical
        attention, which may not be negative"

        Design: Corner/entities/crash_out_of_domain_enum_and_pagination_bounds_returns_invalid_request
        """
        context = _terminal_and_driver_for_intake_probes(
            api,
            name="Zanesville Terminal",
            terminal_code="ZAN01",
            annual_miles_millions=5.0,
            employee_code="D-2601",
            full_name="Orla Pemberton",
            cdl_number="OH-CDL-2601",
            hire_date="2015-10-10",
        )
        intake = dict(
            occurred_at="2026-07-30T20:00:00Z",
            notified_at="2026-07-30T20:10:00Z",
            location_text="I-70 MM 152",
            route_class="LINEHAUL",
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
        )

        out_of_domain = api.create_crash(
            factories.crash_payload(
                context["driver"]["id"],
                context["terminal"]["id"],
                severity="CATASTROPHIC_PLUS",
                **intake,
            ),
            DISPATCHER,
        )
        validate_error(out_of_domain, ApiErrorId.INVALID_REQUEST.value, 400)

        negative_count = api.create_crash(
            factories.crash_payload(
                context["driver"]["id"],
                context["terminal"]["id"],
                severity=SEVERITY_MODERATE,
                injury_transported_count=-1,
                **intake,
            ),
            DISPATCHER,
        )
        validate_error(negative_count, ApiErrorId.INVALID_REQUEST.value, 400)

        rows, meta = validate_paginated(api.list_crashes(AUDITOR))
        assert rows == []
        assert_page(meta, total_count=0, has_more=False)

    def test_the_page_window_is_refused_outside_its_bounds_and_never_clamped(
        self, api: ApiClient
    ):
        """One past the maximum fails while the maximum itself succeeds.

        PRD: "A `limit` outside the range 1 through 100 inclusive, or a negative
        `offset`, is a request-shape violation and is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."

        Design: Corner/entities/crash_out_of_domain_enum_and_pagination_bounds_returns_invalid_request
        """
        validate_error(
            api.list_crashes(AUDITOR, {"limit": MAX_LIMIT + 1}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.list_crashes(AUDITOR, {"offset": -1}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        rows, meta = validate_paginated(api.list_crashes(AUDITOR, {"limit": MAX_LIMIT}))
        assert rows == []
        assert_page(meta, total_count=0, has_more=False, limit=MAX_LIMIT, offset=0)


class TestSubResourceCreatesResolveTheirParentFirst:
    """An absent parent is reported as the parent's own not-found code."""

    def test_the_absent_crash_is_reported_whether_it_is_a_path_or_a_body_reference(
        self, api: ApiClient
    ):
        """Two different creates against the same absent crash, one code.

        PRD: "Requesting the evidence items of a crash identifier that does not
        resolve is `ERR_CRASH_NOT_FOUND` ... The parent is always resolved before
        anything about the child — including the child's own shape or state — is
        considered."

        Design: Corner/entities/driver_statement_on_unknown_crash_parent_returns_not_found
        """
        _terminal_and_driver_for_intake_probes(
            api,
            name="Bucyrus Terminal",
            terminal_code="BUC01",
            annual_miles_millions=2.0,
            employee_code="D-2801",
            full_name="Quinn Ardsley",
            cdl_number="OH-CDL-2801",
            hire_date="2018-03-14",
        )
        absent_crash_id = ABSENT_UUIDS[20]

        validate_error(
            api.create_evidence_item(
                absent_crash_id,
                factories.evidence_payload(
                    kind=EVIDENCE_TELEMATICS,
                    source_device_id="ECM-2801",
                    window_start_at="2026-07-30T10:00:00Z",
                    window_end_at="2026-07-30T12:00:00Z",
                    retention_deadline_at="2026-10-31T00:00:00Z",
                ),
                DISPATCHER,
            ),
            ApiErrorId.CRASH_NOT_FOUND.value,
            404,
        )

        validate_error(
            api.create_claim(
                factories.claim_payload(
                    absent_crash_id, claimant_notice_date="2026-07-31"
                ),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.CRASH_NOT_FOUND.value,
            404,
        )

        evidence_rows, evidence_meta = validate_paginated(api.list_evidence_items(AUDITOR))
        assert evidence_rows == []
        assert_page(evidence_meta, total_count=0)

        claim_rows, claim_meta = validate_paginated(api.list_claims(AUDITOR))
        assert claim_rows == []
        assert_page(claim_meta, total_count=0)


class TestBodyForeignKeysAreCheckedInDeclarationOrder:
    """Two absent references, and the declared order picks which one is named."""

    def test_the_driver_reference_is_named_before_the_terminal_reference(
        self, api: ApiClient
    ):
        """Both keys are absent, yet only the first declared one is reported.

        PRD: "Every foreign key supplied in the request body resolves to an
        existing row, checked in the declaration order of the owning entity's
        fields — otherwise the entity-specific not-found code at HTTP 404." The
        notification "identifies the driver operating the unit through
        `driver_id` and the terminal through `terminal_id`, both of which must
        resolve".

        Design: Corner/entities/crash_foreign_keys_validated_in_field_declaration_order
        """
        context = _terminal_and_driver_for_intake_probes(
            api,
            name="Celina Terminal",
            terminal_code="CEL01",
            annual_miles_millions=2.0,
            employee_code="D-2901",
            full_name="Rhys Calloway",
            cdl_number="OH-CDL-2901",
            hire_date="2013-09-09",
        )
        intake = dict(
            occurred_at="2026-07-30T11:00:00Z",
            notified_at="2026-07-30T11:10:00Z",
            location_text="SR-29 at Havemann Rd",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_REGIONAL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
        )

        both_absent = api.create_crash(
            factories.crash_payload(ABSENT_UUIDS[30], ABSENT_UUIDS[31], **intake),
            DISPATCHER,
        )
        both_absent_error = assert_error_envelope(both_absent.json())
        assert both_absent.status_code == 404
        assert both_absent_error["error_id"] == ApiErrorId.DRIVER_NOT_FOUND.value
        assert both_absent_error["error_id"] != ApiErrorId.TERMINAL_NOT_FOUND.value

        terminal_absent = api.create_crash(
            factories.crash_payload(
                context["driver"]["id"], ABSENT_UUIDS[31], **intake
            ),
            DISPATCHER,
        )
        validate_error(terminal_absent, ApiErrorId.TERMINAL_NOT_FOUND.value, 404)

        rows, meta = validate_paginated(api.list_crashes(AUDITOR))
        assert rows == []
        assert_page(meta, total_count=0)

    def test_the_intake_succeeds_once_both_references_resolve(self, api: ApiClient):
        """The same payload that was refused twice is accepted unchanged.

        PRD: "Every entity type has its own not-found error, and it is used both
        for an unresolvable `{id}` in the path and for an unresolvable identifier
        supplied in a request body"

        Design: Corner/entities/crash_foreign_keys_validated_in_field_declaration_order
        """
        context = _terminal_and_driver_for_intake_probes(
            api,
            name="Celina Terminal",
            terminal_code="CEL01",
            annual_miles_millions=2.0,
            employee_code="D-2901",
            full_name="Rhys Calloway",
            cdl_number="OH-CDL-2901",
            hire_date="2013-09-09",
        )
        intake = dict(
            occurred_at="2026-07-30T11:00:00Z",
            notified_at="2026-07-30T11:10:00Z",
            location_text="SR-29 at Havemann Rd",
            severity=SEVERITY_MODERATE,
            route_class=ROUTE_CLASS_REGIONAL,
            tow_away=False,
            tow_reason=TOW_REASON_NONE,
        )
        validate_error(
            api.create_crash(
                factories.crash_payload(ABSENT_UUIDS[30], ABSENT_UUIDS[31], **intake),
                DISPATCHER,
            ),
            ApiErrorId.DRIVER_NOT_FOUND.value,
            404,
        )

        created = validate_success(
            api.create_crash(
                factories.crash_payload(
                    context["driver"]["id"], context["terminal"]["id"], **intake
                ),
                DISPATCHER,
            ),
            201,
        )

        assert created["driver_id"] == context["driver"]["id"]
        assert created["terminal_id"] == context["terminal"]["id"]
        assert_common_fields(created, expected_version=1)

        rows, meta = validate_paginated(api.list_crashes(AUDITOR))
        assert len(rows) == 1
        assert_page(meta, total_count=1, has_more=False)
        assert rows[0]["id"] == created["id"]


REVERSE_EVIDENCE_WINDOW = {
    "window_start_at": "2026-07-30T11:00:00Z",
    "window_end_at": "2026-07-30T13:00:00Z",
    "retention_deadline_at": "2026-10-31T00:00:00Z",
}


def _two_terminals_one_of_them_busy(api: ApiClient) -> dict:
    """Terminal A carries a whole crash file; terminal B carries only a driver."""
    terminal_a = build_terminal(
        api,
        name="Defiance Terminal",
        terminal_code="DEF01",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    terminal_b = build_terminal(
        api,
        name="Elyria Terminal",
        terminal_code="ELY01",
        region_code="OH",
        annual_miles_millions=2.0,
    )
    driver_a = build_driver(
        api,
        terminal_a["id"],
        employee_code="D-3001",
        full_name="Sana Whitlock",
        cdl_number="OH-CDL-3001",
        hire_date="2012-12-12",
    )
    driver_b = build_driver(
        api,
        terminal_b["id"],
        employee_code="D-3101",
        full_name="Tomas Belrose",
        cdl_number="OH-CDL-3101",
        hire_date="2012-12-12",
    )
    crash = build_crash(
        api,
        driver_a["id"],
        terminal_a["id"],
        occurred_at="2026-07-30T12:00:00Z",
        notified_at="2026-07-30T12:15:00Z",
        location_text="US-24 at Independence Dam",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    evidence = build_preserved_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-3001",
        **REVERSE_EVIDENCE_WINDOW,
    )
    statement = build_statement(
        api,
        crash["id"],
        driver_a["id"],
        narrative="Low-speed contact with a fixed object.",
        attested=True,
        conditions_note=None,
    )
    case = build_review_case(
        api, crash["id"], committee_name="Defiance Safety Review Committee"
    )
    opened = open_deliberation(api, case["id"])
    validate_success(
        api.cast_vote(
            case["id"],
            factories.vote_payload(
                opened["version"],
                vote=BALLOT_DISPOSITION_ABSTAIN,
                comment="recusing, I dispatched this load",
            ),
            COMMITTEE_ONE,
        ),
        201,
    )
    return {
        "terminal_a": terminal_a,
        "terminal_b": terminal_b,
        "driver_a": driver_a,
        "driver_b": driver_b,
        "crash": crash,
        "evidence": evidence,
        "statement": statement,
        "review_case": case,
    }


class TestChildrenAreReachableBackwardsFromTheirParent:
    """Every declared foreign key is navigable from the parent identifier."""

    def test_the_filtered_top_level_lists_return_only_the_named_parents_children(
        self, api: ApiClient
    ):
        """Terminal A's driver is found, and terminal B's driver has no crashes.

        PRD: "Lists drivers. Filters: `terminal_id`, `status`, `tenure_band`,
        `required_action_tier`." — "Crashes may be listed with `driver_id`,
        `terminal_id`, `preventability_status`, `reporting_status`, `route_class`
        and `severity` filters" — "Lists review cases. Filters: `crash_id`,
        `appeal_evidence_item_id`, `status`, `determination`."

        Design: Corner/entities/child_rows_are_reverse_reachable_from_every_parent_id
        """
        context = _two_terminals_one_of_them_busy(api)

        drivers_of_a, drivers_meta = validate_paginated(
            api.list_drivers(AUDITOR, {"terminal_id": context["terminal_a"]["id"]})
        )
        assert_page(drivers_meta, total_count=1, has_more=False)
        assert_id_set(drivers_of_a, [context["driver_a"]["id"]])
        assert drivers_of_a[0]["terminal_id"] == context["terminal_a"]["id"]

        crashes_of_b, crashes_meta = validate_paginated(
            api.list_crashes(AUDITOR, {"driver_id": context["driver_b"]["id"]})
        )
        assert crashes_of_b == []
        assert_page(crashes_meta, total_count=0, has_more=False)

        cases_of_crash, cases_meta = validate_paginated(
            api.list_review_cases(AUDITOR, {"crash_id": context["crash"]["id"]})
        )
        assert_page(cases_meta, total_count=1, has_more=False)
        assert_id_set(cases_of_crash, [context["review_case"]["id"]])
        assert cases_of_crash[0]["crash_id"] == context["crash"]["id"]
        assert cases_of_crash[0]["status"] == REVIEW_STATE_DELIBERATION

    def test_each_sub_resource_collection_returns_its_own_parents_rows(
        self, api: ApiClient
    ):
        """Evidence, statements and ballots each read back under their parent.

        PRD: "Lists the evidence items requested against the crash." — "Lists the
        driver statements recorded against the crash." — "Lists the ballots cast
        on the review case, including superseded and cascade-created ballots."

        Design: Corner/entities/child_rows_are_reverse_reachable_from_every_parent_id
        """
        context = _two_terminals_one_of_them_busy(api)
        crash_id = context["crash"]["id"]

        evidence_response = api.list_crash_evidence_items(crash_id, AUDITOR)
        assert_array_envelope(evidence_response.json())
        evidence_rows, evidence_meta = validate_paginated(evidence_response)
        assert_page(evidence_meta, total_count=1, has_more=False)
        assert_id_set(evidence_rows, [context["evidence"]["id"]])
        assert evidence_rows[0]["crash_id"] == crash_id
        assert evidence_rows[0]["preservation_state"] == PRESERVATION_PRESERVED

        statement_rows, statement_meta = validate_paginated(
            api.list_driver_statements(crash_id, AUDITOR)
        )
        assert_page(statement_meta, total_count=1, has_more=False)
        assert_id_set(statement_rows, [context["statement"]["id"]])
        assert_declared_fields(statement_rows[0], DRIVER_STATEMENT_FIELDS)
        assert_append_only_fields(statement_rows[0])
        assert statement_rows[0]["crash_id"] == crash_id
        assert statement_rows[0]["submitted_by_driver_id"] == context["driver_a"]["id"]
        assert statement_rows[0]["attested"] is True

        ballot_rows, ballot_meta = validate_paginated(
            api.list_votes(context["review_case"]["id"], AUDITOR)
        )
        assert_page(ballot_meta, total_count=1, has_more=False)
        assert ballot_rows[0]["review_case_id"] == context["review_case"]["id"]
        assert ballot_rows[0]["vote"] == BALLOT_DISPOSITION_ABSTAIN
        assert ballot_rows[0]["criterion_scores"] is None
        assert ballot_rows[0]["weighted_member_score"] is None
