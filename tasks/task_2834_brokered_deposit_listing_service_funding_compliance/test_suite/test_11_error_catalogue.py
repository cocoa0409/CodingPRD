"""Error-catalogue behaviour of the Brokered Deposit Funding Compliance API.

Each test drives one refusal that the PRD states in prose, then checks that the
refused call left the book untouched.  Every test builds its own state from an
empty database.
"""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_INSTANT,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, COMPLIANCE, DESK, EXAMINER, TREASURY


# ─── Section: identity headers are inspected before anything else ──────────────

class TestUnauthenticatedHeaders:
    """A missing or unrecognised identity header is refused before any lookup."""

    def test_a_request_with_no_identity_headers_is_refused(self):
        """Every request, without exception, carries two headers: `X-User-ID`
        identifying the acting operator and `X-User-Role` declaring the capacity in
        which that operator acts. If either header is absent, or if `X-User-Role` is not
        one of the six role names the system recognises, the request is refused with
        `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about it is inspected.

        Design: Corner/errors/corner_missing_or_undeclared_headers_return_unauthenticated
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        institution = fx.register_institution(legal_name="Header Bank NA")

        response = api_client._request(
            "GET", f"/institutions/{institution['id']}", headers=None
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    @pytest.mark.parametrize("headers", [
        {"X-User-ID": "op_admin"},
        {"X-User-Role": "SystemAdmin"},
        {"X-User-ID": "op_x", "X-User-Role": "Auditor"},
        {"X-User-ID": "op_x", "X-User-Role": "systemadmin"},
    ])
    def test_a_half_present_or_undeclared_role_header_is_refused(self, headers):
        """If either header is absent, or if `X-User-Role` is not one of the six role
        names the system recognises, the request is refused with `ERR_UNAUTHENTICATED`
        (HTTP 401) before anything else about it is inspected.

        PRD §2.1: The six roles are `SystemAdmin`, `FundingDeskOfficer`,
        `ComplianceReviewer`, `TreasuryController`, `Examiner` and
        `BrokerRepresentative`.

        Design: Corner/errors/corner_missing_or_undeclared_headers_return_unauthenticated
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        institution = fx.register_institution(legal_name="Header Bank NA")

        response = api_client._request(
            "GET", f"/institutions/{institution['id']}", headers=headers
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_identity_outranks_existence_so_an_unknown_id_still_returns_401(self):
        """1. Identity: `X-User-ID` and `X-User-Role` present and the role recognised —
        `ERR_UNAUTHENTICATED`. All endpoints.

        PRD §2.8: Every request is evaluated against the rules below in ascending
        priority order and, on the first rule it violates, is rejected with that rule's
        error and nothing else is evaluated.

        Design: Corner/errors/corner_missing_or_undeclared_headers_return_unauthenticated
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)

        response = api_client._request(
            "GET", f"/institutions/{NON_EXISTENT_UUID}", headers=None
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Section: each addressable resource has its own typed 404 ──────────────────

class TestTypedNotFoundCodes:
    """An unknown identifier resolves to the code belonging to that resource."""

    @pytest.mark.parametrize("path,error_id", [
        (f"/broker-agreements/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value),
        (f"/primary-purpose-exceptions/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_EXCEPTION_NOT_FOUND.value),
        (f"/deposit-programs/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_PROGRAM_NOT_FOUND.value),
        (f"/deposit-classifications/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_CLASSIFICATION_NOT_FOUND.value),
        (f"/deposit-placements/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_PLACEMENT_NOT_FOUND.value),
        (f"/contingency-plans/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_PLAN_NOT_FOUND.value),
        (f"/call-report-filings/{NON_EXISTENT_UUID}",
         ApiErrorId.ERR_FILING_NOT_FOUND.value),
    ])
    def test_each_unknown_resource_returns_its_own_typed_404(self, path, error_id):
        """Foreign keys travelling in a body or query string are resolved with the same
        not-found codes as their addressed counterparts: an unknown bank reference
        yields `ERR_INSTITUTION_NOT_FOUND`, an unknown counterparty
        `ERR_BROKER_NOT_FOUND`, an unknown agreement `ERR_AGREEMENT_NOT_FOUND`, an
        unknown exception filing `ERR_EXCEPTION_NOT_FOUND`, an unknown program
        `ERR_PROGRAM_NOT_FOUND`, an unknown classification
        `ERR_CLASSIFICATION_NOT_FOUND`, an unknown placement `ERR_PLACEMENT_NOT_FOUND`,
        an unknown contingency plan `ERR_PLAN_NOT_FOUND` and an unknown call report
        filing `ERR_FILING_NOT_FOUND`. All nine are HTTP 404.

        Design: Corner/errors/corner_remaining_typed_not_found_codes
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)

        response = api_client._request("GET", path, headers=ADMIN)
        validate_error(response, error_id)

    def test_an_unknown_bank_reference_in_a_program_body_yields_the_bank_code(self):
        """Foreign keys travelling in a body or query string are resolved with the same
        not-found codes as their addressed counterparts: an unknown bank reference yields
        `ERR_INSTITUTION_NOT_FOUND`, an unknown counterparty `ERR_BROKER_NOT_FOUND`, an
        unknown agreement `ERR_AGREEMENT_NOT_FOUND`, an unknown exception filing
        `ERR_EXCEPTION_NOT_FOUND`, an unknown program `ERR_PROGRAM_NOT_FOUND`, an unknown
        classification `ERR_CLASSIFICATION_NOT_FOUND`, an unknown placement
        `ERR_PLACEMENT_NOT_FOUND`, an unknown contingency plan `ERR_PLAN_NOT_FOUND` and
        an unknown call report filing `ERR_FILING_NOT_FOUND`. All nine are HTTP 404.

        PRD §2.8 rule 4: Bank existence — `ERR_INSTITUTION_NOT_FOUND`. The bank read,
        the capital-category change, balance adjustments, the wholesale funding summary,
        and both the create and list forms of concentration limits, contingency plans and
        call report filings; also the `institution_id` body field of an exception filing
        and of a program create.

        Design: Corner/errors/corner_remaining_typed_not_found_codes
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)

        response = api_client.create_program(
            f.program_payload(NON_EXISTENT_UUID, program_name="Orphan Program"), DESK
        )
        validate_error(response, ApiErrorId.ERR_INSTITUTION_NOT_FOUND.value)

    def test_an_unknown_counterparty_reference_in_a_program_body_yields_the_broker_code(self):
        """5. Counterparty existence — `ERR_BROKER_NOT_FOUND`. The counterparty read,
        both forms of the agreements collection under a counterparty, an exception filing
        create, and a program create carrying `broker_id`.

        PRD §2.8: Every request is evaluated against the rules below in ascending
        priority order and, on the first rule it violates, is rejected with that rule's
        error and nothing else is evaluated.

        Design: Corner/errors/corner_remaining_typed_not_found_codes
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Typed 404 Bank NA"})

        response = api_client.create_program(
            f.program_payload(
                env["institution"]["id"],
                program_name="Orphan Counterparty Program",
                funding_channel_claim="BROKERED",
                broker_id=NON_EXISTENT_UUID,
                agreement_id=NON_EXISTENT_UUID,
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_BROKER_NOT_FOUND.value)


# ─── Section: malformed write payloads ─────────────────────────────────────────

class TestMalformedWritePayloads:
    """Shape is checked on every write before any business rule runs."""

    @pytest.mark.parametrize("drop,overrides", [
        ("legal_name", {}),
        (None, {"capital_category": "SUPER_CAPITALIZED"}),
        (None, {"core_deposits_cents": -1}),
        (None, {"tier1_capital_cents": -100}),
    ])
    def test_shape_violations_on_a_bank_create_are_invalid_requests(self, drop, overrides):
        """3. Request shape: every input field that has no declared default is present,
        every enum-typed field carries a declared member, integer fields are integers,
        `_cents` and `_bps` fields are not negative, diligence sub-scores lie within 0 to
        100 inclusive, calendar-date fields are formatted as year-month-day and instant
        fields are ISO 8601 UTC — `ERR_INVALID_REQUEST`. All write endpoints.

        Design: Corner/errors/corner_malformed_write_payloads_return_invalid_request
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)

        payload = f.institution_payload(legal_name="Malformed Bank NA", **overrides)
        if drop is not None:
            payload.pop(drop)

        response = api_client.create_institution(payload, ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        listed, meta = validate_paginated(api_client.list_institutions(ADMIN))
        assert meta["total_count"] == 0, (
            "a refused create must persist nothing, got total_count "
            f"{meta['total_count']}"
        )
        assert listed == []

    @pytest.mark.parametrize("score", [101, -1, 200])
    def test_a_diligence_subscore_outside_zero_to_one_hundred_is_an_invalid_request(self, score):
        """3. Request shape: every input field that has no declared default is present,
        every enum-typed field carries a declared member, integer fields are integers,
        `_cents` and `_bps` fields are not negative, diligence sub-scores lie within 0 to
        100 inclusive, calendar-date fields are formatted as year-month-day and instant
        fields are ISO 8601 UTC — `ERR_INVALID_REQUEST`. All write endpoints.

        PRD §3.2: four diligence sub-scores each within 0 to 100 inclusive

        Design: Corner/errors/corner_malformed_write_payloads_return_invalid_request
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        broker = fx.register_broker(legal_name="Malformed Brokers LLC")

        response = api_client.create_agreement(
            broker["id"], f.agreement_payload(aml_program_score=score), DESK
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        listed, meta = validate_paginated(
            api_client.list_broker_agreements(broker["id"], DESK)
        )
        assert meta["total_count"] == 0, (
            f"a refused filing must persist nothing, got total_count {meta['total_count']}"
        )

    def test_an_action_literal_outside_the_endpoints_row_is_an_invalid_request(self):
        """Every action endpoint takes a required `action` field naming which transition
        to perform, drawn from the literals listed in its row below, and an action that is
        not one of those literals is an invalid request.

        Design: Corner/errors/corner_malformed_write_payloads_return_invalid_request
        """
        env = fx.setup_classified_program(
            program_overrides={"program_name": "Action Literal Program"}
        )

        response = api_client.program_state_action(
            env["program"]["id"], {"action": "FROBNICATE"}, DESK
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        assert fx.read_program(env["program"]["id"])["state"] == "CLASSIFIED", (
            "a refused action leaves the program where it was"
        )

    @pytest.mark.parametrize("report_period", ["2026Q5", "2026Q0", "26Q3", "2026-Q3", "Q32026"])
    def test_a_malformed_report_period_label_is_an_invalid_request(self, report_period):
        """A filing is opened for one reporting period, identified by a `report_period`
        label of four digits followed by the letter Q and a quarter number 1 through 4 —
        `2026Q3` is well formed, and anything else is refused as an invalid request.

        Design: Corner/errors/corner_malformed_write_payloads_return_invalid_request
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Period Bank NA"})

        response = api_client.create_call_report_filing(
            env["institution"]["id"],
            f.call_report_filing_payload(report_period=report_period),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        _, meta = validate_paginated(
            api_client.list_call_report_filings(env["institution"]["id"], DESK)
        )
        assert meta["total_count"] == 0, (
            f"a refused filing must persist nothing, got total_count {meta['total_count']}"
        )


# ─── Section: uniqueness is scoped to the parent, not to the whole table ───────

class TestUniquenessScopes:
    """Each duplicate key is rejected only inside the scope the PRD gives it."""

    def test_agreement_ref_is_unique_within_one_counterparty_only(self):
        """A filing supplies the counterparty-assigned `agreement_ref`, which must be
        unique within that one counterparty — a repeat is refused with
        `ERR_DUPLICATE_KEY`

        Design: Corner/errors/corner_uniqueness_scopes_are_per_parent_not_global
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        first_broker = fx.register_broker(legal_name="Scope Brokers One LLC")
        second_broker = fx.register_broker(legal_name="Scope Brokers Two LLC")

        validate_success(
            api_client.create_agreement(
                first_broker["id"], f.agreement_payload(agreement_ref="AGR-SHARED"), DESK
            ),
            expected_status=201,
        )
        validate_success(
            api_client.create_agreement(
                second_broker["id"], f.agreement_payload(agreement_ref="AGR-SHARED"), DESK
            ),
            expected_status=201,
        )

        response = api_client.create_agreement(
            first_broker["id"], f.agreement_payload(agreement_ref="AGR-SHARED"), DESK
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)

        _, meta = validate_paginated(
            api_client.list_broker_agreements(first_broker["id"], DESK)
        )
        assert meta["total_count"] == 1, (
            "the refused repeat added nothing to the first counterparty, got "
            f"total_count {meta['total_count']}"
        )

    def test_report_period_is_unique_within_one_bank_only(self):
        """The `report_period` is unique within one bank, so a second filing for a period
        that already has one is refused with `ERR_DUPLICATE_KEY`; the same label at a
        different bank is fine.

        Design: Corner/errors/corner_uniqueness_scopes_are_per_parent_not_global
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        first_bank = fx.register_institution(legal_name="Scope Bank One NA")
        second_bank = fx.register_institution(legal_name="Scope Bank Two NA")

        validate_success(
            api_client.create_call_report_filing(
                first_bank["id"], f.call_report_filing_payload(report_period="2026Q2"), DESK
            ),
            expected_status=201,
        )
        validate_success(
            api_client.create_call_report_filing(
                second_bank["id"], f.call_report_filing_payload(report_period="2026Q2"), DESK
            ),
            expected_status=201,
        )

        response = api_client.create_call_report_filing(
            first_bank["id"], f.call_report_filing_payload(report_period="2026Q2"), DESK
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)

        _, meta = validate_paginated(
            api_client.list_call_report_filings(first_bank["id"], DESK)
        )
        assert meta["total_count"] == 1, (
            "the refused repeat added nothing at the first bank, got total_count "
            f"{meta['total_count']}"
        )

    def test_benchmark_uniqueness_is_the_pair_of_bucket_and_effective_date(self):
        """A publication governs the half-open interval that begins on its own
        `effective_date` and ends the day the next publication for the same bucket becomes
        effective, and the pair of `tenor_bucket` and `effective_date` must be unique
        across all publications — a duplicate is refused with `ERR_DUPLICATE_KEY`.

        Design: Corner/errors/corner_uniqueness_scopes_are_per_parent_not_global
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)

        validate_success(
            api_client.publish_national_rate_cap(
                f.national_rate_cap_payload(
                    tenor_bucket="DAYS_1_30",
                    published_national_rate_bps=400,
                    effective_date="2026-07-01",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.publish_national_rate_cap(
                f.national_rate_cap_payload(
                    tenor_bucket="DAYS_31_90",
                    published_national_rate_bps=420,
                    effective_date="2026-07-01",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.publish_national_rate_cap(
                f.national_rate_cap_payload(
                    tenor_bucket="DAYS_1_30",
                    published_national_rate_bps=410,
                    effective_date="2026-07-15",
                ),
                ADMIN,
            ),
            expected_status=201,
        )

        response = api_client.publish_national_rate_cap(
            f.national_rate_cap_payload(
                tenor_bucket="DAYS_1_30",
                published_national_rate_bps=999,
                effective_date="2026-07-01",
            ),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_KEY.value)

        _, meta = validate_paginated(api_client.list_national_rate_caps(ADMIN))
        assert meta["total_count"] == 3, (
            "only the three distinct pairs were published, got total_count "
            f"{meta['total_count']}"
        )


# ─── Section: a CAPPED bank with no governing publication for the bucket ───────

def _capped_bank_with_a_gap_in_the_benchmark_table() -> dict:
    """A CAPPED bank; only the DAYS_1_30 bucket has a publication in force at the
    logical clock's date, while the DAYS_31_90 publication is still in the future."""
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    fx.publish_rate_cap(
        tenor_bucket="DAYS_1_30",
        published_national_rate_bps=400,
        effective_date="2026-07-01",
    )
    fx.publish_rate_cap(
        tenor_bucket="DAYS_31_90",
        published_national_rate_bps=420,
        effective_date="2026-09-01",
    )
    institution = fx.register_institution(
        legal_name="Gap Bank NA", capital_category="ADEQUATELY_CAPITALIZED"
    )
    return {"institution": institution}


class TestMissingBenchmarkPublication:
    """An empty candidate pool is a missing input, never a ceiling of zero."""

    def test_a_bucket_with_no_publication_in_force_refuses_the_program(self):
        """If the candidate pool is empty while the bank's regime is `CAPPED`, the request
        fails with `ERR_NO_RATE_CAP_PUBLISHED` — an unpublished benchmark is a missing
        input, not a ceiling of zero.

        PRD §3.1: Only publications for the subject's own `tenor_bucket` are candidates,
        and only those whose `effective_date` falls on or before the applicable as-of
        date; among those, the one with the latest `effective_date` wins, and if two share
        that date the one created most recently wins.

        Design: Corner/errors/corner_capped_institution_without_published_benchmark_returns_404
        """
        env = _capped_bank_with_a_gap_in_the_benchmark_table()
        assert fx.read_institution(env["institution"]["id"])["rate_cap_regime"] == "CAPPED", (
            "every category other than WELL_CAPITALIZED is CAPPED"
        )

        response = api_client.create_program(
            f.program_payload(
                env["institution"]["id"],
                program_name="60D Gap Program",
                tenor_days=60,
                offered_rate_bps=470,
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_NO_RATE_CAP_PUBLISHED.value)

        _, meta = validate_paginated(api_client.list_programs(DESK))
        assert meta["total_count"] == 0, (
            "a refused program create persists nothing, got total_count "
            f"{meta['total_count']}"
        )

    def test_a_bucket_with_a_publication_in_force_derives_the_national_leg_ceiling(self):
        """Once a publication has been selected, the ceiling is built in a pinned order.
        The national leg is the publication's `published_national_rate_bps` plus 75 basis
        points. If the program asserts no local comparison — that is, its
        `local_prevailing_rate_bps` is null — the combined figure is the national leg
        alone.

        PRD §3.4: A tenor of exactly 30 days therefore lands in the first maturity bucket
        and a tenor of exactly 31 days in the second.

        Design: Corner/errors/corner_capped_institution_without_published_benchmark_returns_404
        """
        env = _capped_bank_with_a_gap_in_the_benchmark_table()

        program = validate_success(
            api_client.create_program(
                f.program_payload(
                    env["institution"]["id"],
                    program_name="30D Covered Program",
                    tenor_days=30,
                    offered_rate_bps=470,
                ),
                DESK,
            ),
            expected_status=201,
        )
        assert program["tenor_bucket"] == "DAYS_1_30", (
            f"a 30-day tenor lands in DAYS_1_30, got {program['tenor_bucket']}"
        )
        assert program["effective_cap_bps"] == 475, (
            "400 published plus 75 basis points with no local comparison, got "
            f"{program['effective_cap_bps']}"
        )


# ─── Section: the reciprocal exclusion capacity ────────────────────────────────

def _reciprocal_program_with_capacity_of_seven_and_a_half_billion() -> dict:
    """Bank whose reciprocal capacity is 7,500,000,000 cents, with an open
    RECIPROCAL_EXCLUDED program contracted for 7,000,000,000 of it."""
    env = fx.setup_bank(
        institution_overrides={
            "legal_name": "Reciprocal Bank NA",
            "core_deposits_cents": 30_000_000_000,
            "total_liabilities_cents": 30_000_000_000,
        }
    )
    env.update(
        fx.setup_approved_agreement(
            broker_overrides={
                "legal_name": "Reciprocal Network LLC",
                "broker_type": "DEPOSIT_PLACEMENT_NETWORK",
                "has_placement_discretion": False,
                "fee_structure": "PER_ACCOUNT_FEE",
                "fee_flat_cents": 500,
            },
            agreement_overrides={"fee_structure": "PER_ACCOUNT_FEE", "fee_flat_cents": 500},
        )
    )
    env["program"] = fx.open_program(
        env["institution"]["id"], DESK,
        broker_id=env["broker"]["id"],
        agreement_id=env["agreement"]["id"],
        program_name="Reciprocal CD Program",
        funding_channel_claim="RECIPROCAL_NETWORK",
        reciprocal_arrangement_cents=7_000_000_000,
        tenor_days=60,
        offered_rate_bps=300,
    )
    env["classification"] = fx.classify_program(
        env["program"]["id"], env["program"]["version"], COMPLIANCE
    )
    env["program"] = fx.attest_program(env["program"]["id"], DESK)
    return env


class TestReciprocalCapacityExhausted:
    """Reciprocal money is admitted only up to the bank's remaining capacity."""

    def test_a_tranche_inside_the_remaining_capacity_is_booked_and_funded(self):
        """First, reciprocal exclusion: when the program's `funding_channel_claim` is
        `RECIPROCAL_NETWORK` and the bank's remaining reciprocal capacity is at least the
        program's `reciprocal_arrangement_cents`, the `determined_class` is
        `RECIPROCAL_EXCLUDED`.

        PRD §2.11: `reciprocal_deposits_cents` are each the sum of `principal_cents` over
        that bank's placements whose `funding_status` is exactly `ACTIVE` and whose
        `classified_as` matches the bucket

        PRD §2.11: `total_deposits_cents` is `core_deposits_cents` plus those three
        buckets.

        Design: Corner/errors/corner_reciprocal_capacity_exhausted_rejected
        """
        env = _reciprocal_program_with_capacity_of_seven_and_a_half_billion()
        assert env["classification"]["determined_class"] == "RECIPROCAL_EXCLUDED", (
            "capacity of 7500000000 covers a contracted 7000000000, got "
            f"{env['classification']['determined_class']}"
        )
        assert env["classification"]["call_report_line"] == "RC_O_M_RECIPROCAL", (
            "RECIPROCAL_EXCLUDED maps to RC_O_M_RECIPROCAL, got "
            f"{env['classification']['call_report_line']}"
        )

        placement = fx.book_placement(
            env["program"]["id"], DESK, principal_cents=7_000_000_000,
            rate_bps=300, issue_date="2026-08-01", tenor_days=60,
        )
        activated = fx.activate_placement(placement["id"], DESK)
        assert activated["classified_as"] == "RECIPROCAL_EXCLUDED", (
            "the tranche inherits the determined class, got "
            f"{activated['classified_as']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["reciprocal_deposits_cents"] == 7_000_000_000, (
            "the live tranche fills the reciprocal bucket, got "
            f"{institution['reciprocal_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 37_000_000_000, (
            "total deposits are core plus the three wholesale buckets, got "
            f"{institution['total_deposits_cents']}"
        )

    def test_a_tranche_above_the_remaining_capacity_is_refused(self):
        """For a program whose governing determination came out as
        `RECIPROCAL_EXCLUDED`, the tranche's `principal_cents` must not exceed the bank's
        remaining reciprocal capacity — 25 percent of `total_liabilities_cents`, taking
        the integer part, less the bank's current `reciprocal_deposits_cents`, floored at
        zero — and a principal above that capacity is refused with
        `ERR_RECIPROCAL_CAP_EXCEEDED`.

        Design: Corner/errors/corner_reciprocal_capacity_exhausted_rejected
        """
        env = _reciprocal_program_with_capacity_of_seven_and_a_half_billion()
        first = fx.book_placement(
            env["program"]["id"], DESK, principal_cents=7_000_000_000,
            rate_bps=300, issue_date="2026-08-01", tenor_days=60,
        )
        fx.activate_placement(first["id"], DESK)

        response = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"], principal_cents=1_000_000_000,
                rate_bps=300, issue_date="2026-08-01", tenor_days=60,
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_RECIPROCAL_CAP_EXCEEDED.value)

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["reciprocal_deposits_cents"] == 7_000_000_000, (
            "the refused booking moved no money, got "
            f"{institution['reciprocal_deposits_cents']}"
        )
        _, meta = validate_paginated(
            api_client.list_placements(DESK, params={"program_id": env["program"]["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the first tranche exists, got total_count {meta['total_count']}"
        )

    def test_a_tranche_exactly_at_the_remaining_capacity_is_admitted(self):
        """For a program whose governing determination came out as
        `RECIPROCAL_EXCLUDED`, the tranche's `principal_cents` must not exceed the bank's
        remaining reciprocal capacity — 25 percent of `total_liabilities_cents`, taking
        the integer part, less the bank's current `reciprocal_deposits_cents`, floored at
        zero — and a principal above that capacity is refused with
        `ERR_RECIPROCAL_CAP_EXCEEDED`.

        Design: Corner/errors/corner_reciprocal_capacity_exhausted_rejected
        """
        env = _reciprocal_program_with_capacity_of_seven_and_a_half_billion()
        first = fx.book_placement(
            env["program"]["id"], DESK, principal_cents=7_000_000_000,
            rate_bps=300, issue_date="2026-08-01", tenor_days=60,
        )
        fx.activate_placement(first["id"], DESK)

        exact = validate_success(
            api_client.create_placement(
                f.placement_payload(
                    env["program"]["id"], principal_cents=500_000_000,
                    rate_bps=300, issue_date="2026-08-01", tenor_days=60,
                ),
                DESK,
            ),
            expected_status=201,
        )
        assert exact["funding_status"] == "PENDING", (
            "a principal equal to the remaining capacity does not exceed it, so the "
            f"booking stands; got {exact['funding_status']}"
        )


# ─── Section: the DRAFT submission window ──────────────────────────────────────

def _draft_notice_due_on_the_thirtieth_of_october() -> dict:
    """A DRAFT notice filed at the default clock, so its deadline is 2026-10-30."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Window Bank NA"})
    env["broker"] = fx.register_broker(legal_name="Window Brokers LLC")
    env["exception"] = fx.file_exception(
        env["broker"]["id"], env["institution"]["id"], DESK,
        total_customer_assets_cents=40_000_000_000,
        deposits_placed_at_ifs_cents=4_000_000_000,
    )
    return env


class TestFilingWindowClosed:
    """The deadline is inclusive on the day and closed the day after."""

    def test_a_submission_on_the_due_date_itself_is_accepted_and_rebases_the_deadline(self):
        """While the filing is in `DRAFT` it is the deadline by which submission must
        happen: a submission on the due date itself is accepted, a submission after it is
        refused with `ERR_FILING_WINDOW_CLOSED`.

        PRD §3.3: It is also stamped with `reporting_due_date`, a calendar date set to the
        logical clock's date plus 90 days.

        PRD §3.3: Once the filing reaches `ACKNOWLEDGED` or `GRANTED` the same field is
        re-based to the logical clock's date plus 90 days again and becomes the next
        periodic reporting deadline.

        Design: Corner/errors/corner_notice_submitted_after_reporting_due_date_rejected
        """
        env = _draft_notice_due_on_the_thirtieth_of_october()
        assert env["exception"]["reporting_due_date"] == "2026-10-30", (
            "2026-08-01 plus 90 days is 2026-10-30, got "
            f"{env['exception']['reporting_due_date']}"
        )

        fx.set_clock("2026-10-30T00:00:00Z")
        acknowledged = validate_success(
            api_client.exception_filing_action(
                env["exception"]["id"], {"action": "SUBMIT"}, DESK
            )
        )
        assert acknowledged["status"] == "ACKNOWLEDGED", (
            "the due date itself is inside the window, got "
            f"{acknowledged['status']}"
        )
        assert acknowledged["reporting_due_date"] == "2027-01-28", (
            "2026-10-30 plus 90 days is 2027-01-28, got "
            f"{acknowledged['reporting_due_date']}"
        )

    def test_a_submission_one_day_after_the_due_date_is_refused(self):
        """While the filing is in `DRAFT` it is the deadline by which submission must
        happen: a submission on the due date itself is accepted, a submission after it is
        refused with `ERR_FILING_WINDOW_CLOSED`.

        Design: Corner/errors/corner_notice_submitted_after_reporting_due_date_rejected
        """
        env = _draft_notice_due_on_the_thirtieth_of_october()

        fx.set_clock("2026-10-31T00:00:00Z")
        response = api_client.exception_filing_action(
            env["exception"]["id"], {"action": "SUBMIT"}, DESK
        )
        validate_error(response, ApiErrorId.ERR_FILING_WINDOW_CLOSED.value)

        unchanged = fx.read_exception(env["exception"]["id"])
        assert unchanged["status"] == "DRAFT", (
            f"a refused submission leaves the filing in DRAFT, got {unchanged['status']}"
        )
        assert unchanged["reporting_due_date"] == "2026-10-30", (
            "a refused submission does not re-base the deadline, got "
            f"{unchanged['reporting_due_date']}"
        )


# ─── Section: threshold and trigger ordering ───────────────────────────────────

class TestThresholdOrdering:
    """Board thresholds and plan triggers must be strictly increasing and bounded."""

    @pytest.mark.parametrize("warning_threshold_bps,breach_threshold_bps", [
        (3000, 2000),
        (2000, 2000),
        (9000, 10001),
        (10001, 10002),
    ])
    def test_limit_thresholds_that_are_not_strictly_increasing_are_refused(
        self, warning_threshold_bps, breach_threshold_bps
    ):
        """Both live in the range 0 to 10000 basis points inclusive, and
        `warning_threshold_bps` must be strictly below `breach_threshold_bps`; thresholds
        that are not strictly increasing, or a threshold above 10000, are refused with
        `ERR_THRESHOLD_ORDER_INVALID`.

        Design: Corner/errors/corner_threshold_ordering_violations_rejected
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Threshold Bank NA"})

        response = api_client.create_concentration_limit(
            env["institution"]["id"],
            f.concentration_limit_payload(
                metric="BROKERED_TO_TOTAL_DEPOSITS",
                warning_threshold_bps=warning_threshold_bps,
                breach_threshold_bps=breach_threshold_bps,
            ),
            TREASURY,
        )
        validate_error(response, ApiErrorId.ERR_THRESHOLD_ORDER_INVALID.value)

        _, meta = validate_paginated(
            api_client.list_concentration_limits(env["institution"]["id"], TREASURY)
        )
        assert meta["total_count"] == 0, (
            f"a refused limit persists nothing, got total_count {meta['total_count']}"
        )

    def test_thresholds_one_basis_point_apart_and_at_the_ceiling_are_accepted(self):
        """Both live in the range 0 to 10000 basis points inclusive, and
        `warning_threshold_bps` must be strictly below `breach_threshold_bps`; thresholds
        that are not strictly increasing, or a threshold above 10000, are refused with
        `ERR_THRESHOLD_ORDER_INVALID`.

        PRD §3.7: Each `ACTIVE` limit then takes that value into its own
        `current_value_bps` and sets `breach_state` to `BREACH` when the value is at or
        above its `breach_threshold_bps`, to `WARNING` when the value is at or above its
        `warning_threshold_bps` but below the breach level, and to `WITHIN` otherwise.

        Design: Corner/errors/corner_threshold_ordering_violations_rejected
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Threshold Bank NA"})

        limit = validate_success(
            api_client.create_concentration_limit(
                env["institution"]["id"],
                f.concentration_limit_payload(
                    metric="BROKERED_TO_TOTAL_DEPOSITS",
                    warning_threshold_bps=9999,
                    breach_threshold_bps=10000,
                ),
                TREASURY,
            ),
            expected_status=201,
        )
        assert limit["status"] == "ACTIVE", (
            f"a strictly increasing pair at the ceiling stands, got {limit['status']}"
        )
        assert limit["current_value_bps"] == 0, (
            "an empty book leaves the metric at zero, got "
            f"{limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WITHIN", (
            f"zero is below both thresholds, got {limit['breach_state']}"
        )

    @pytest.mark.parametrize("stage_one,stage_two,stage_three", [
        (500, 500, 4000),
        (2000, 1000, 4000),
        (500, 2000, 2000),
        (500, 2000, 10001),
    ])
    def test_plan_triggers_that_are_not_strictly_increasing_are_refused(
        self, stage_one, stage_two, stage_three
    ):
        """The plan also declares three escalation triggers, `stage_1_trigger_bps`,
        `stage_2_trigger_bps` and `stage_3_trigger_bps`, which must be strictly increasing
        and none above 10000 — otherwise `ERR_THRESHOLD_ORDER_INVALID` — and the three
        playbook action codes `stage_1_action_code`, `stage_2_action_code` and
        `stage_3_action_code` that name what the treasury does at each level.

        Design: Corner/errors/corner_threshold_ordering_violations_rejected
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Trigger Bank NA"})

        response = api_client.create_contingency_plan(
            env["institution"]["id"],
            f.contingency_plan_payload(
                plan_version_label="CFP-ORDER",
                stage_1_trigger_bps=stage_one,
                stage_2_trigger_bps=stage_two,
                stage_3_trigger_bps=stage_three,
            ),
            TREASURY,
        )
        validate_error(response, ApiErrorId.ERR_THRESHOLD_ORDER_INVALID.value)

        _, meta = validate_paginated(
            api_client.list_contingency_plans(env["institution"]["id"], TREASURY)
        )
        assert meta["total_count"] == 0, (
            f"a refused plan persists nothing, got total_count {meta['total_count']}"
        )

    def test_triggers_one_basis_point_apart_and_at_the_ceiling_are_accepted(self):
        """The plan also declares three escalation triggers, `stage_1_trigger_bps`,
        `stage_2_trigger_bps` and `stage_3_trigger_bps`, which must be strictly increasing
        and none above 10000 — otherwise `ERR_THRESHOLD_ORDER_INVALID` — and the three
        playbook action codes `stage_1_action_code`, `stage_2_action_code` and
        `stage_3_action_code` that name what the treasury does at each level.

        PRD §3.7: A new plan lands in `DRAFT` with `activation_stage` of `NONE`,
        `required_buffer_cents` and `buffer_shortfall_cents` at 0, `prepared_by_user_id`
        stamped from the drafting controller and `approved_by_user_id` null.

        Design: Corner/errors/corner_threshold_ordering_violations_rejected
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Trigger Bank NA"})

        plan = validate_success(
            api_client.create_contingency_plan(
                env["institution"]["id"],
                f.contingency_plan_payload(
                    plan_version_label="CFP-EDGE",
                    stage_1_trigger_bps=500,
                    stage_2_trigger_bps=501,
                    stage_3_trigger_bps=10000,
                ),
                TREASURY,
            ),
            expected_status=201,
        )
        assert plan["status"] == "DRAFT", (
            f"a new plan lands in DRAFT, got {plan['status']}"
        )
        assert plan["activation_stage"] == "NONE", (
            f"a new plan carries activation_stage NONE, got {plan['activation_stage']}"
        )
        assert plan["required_buffer_cents"] == 0
        assert plan["buffer_shortfall_cents"] == 0
        assert plan["approved_by_user_id"] is None


# ─── Section: unclassified and already-governed programs ───────────────────────

class TestClassificationGates:
    """A program must be determined before it funds, and only once per cycle."""

    def test_booking_against_a_program_with_no_determination_is_refused(self):
        """The program must already have a governing determination, without which the
        booking is refused with `ERR_CLASSIFICATION_REQUIRED`, and it must be sitting in
        `OPEN_FOR_PLACEMENT`: a `CLASSIFIED` but un-attested program, a `SUSPENDED` program
        and a program under reclassification all refuse new money with
        `ERR_PROGRAM_NOT_OPEN`.

        PRD §2.8 rule 20: The program has a governing determination:
        `governing_classification_id` must be non-null before the program can be attested
        or funded — `ERR_CLASSIFICATION_REQUIRED`. Program state actions with the attest
        action, and placement create.

        Design: Corner/errors/corner_unclassified_and_already_governed_programs_rejected
        """
        env = fx.setup_brokered_program(
            program_overrides={"program_name": "Undetermined Program"}
        )
        assert env["program"]["state"] == "PENDING_CLASSIFICATION"
        assert env["program"]["governing_classification_id"] is None

        response = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"], principal_cents=1_000_000_000,
                rate_bps=470, issue_date="2026-08-01", tenor_days=60,
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_CLASSIFICATION_REQUIRED.value)

        _, meta = validate_paginated(api_client.list_placements(DESK))
        assert meta["total_count"] == 0, (
            f"a refused booking persists nothing, got total_count {meta['total_count']}"
        )

    def test_a_second_determination_against_an_open_program_is_not_classifiable(self):
        """It is admitted only while the program's `state` is `PENDING_CLASSIFICATION` or
        `RECLASSIFICATION_PENDING`; from any other state the request is refused with
        `ERR_PROGRAM_NOT_CLASSIFIABLE`.

        PRD §2.8 rule 19: The program is classifiable, meaning its `state` is
        `PENDING_CLASSIFICATION` or `RECLASSIFICATION_PENDING` —
        `ERR_PROGRAM_NOT_CLASSIFIABLE`. Classification create.

        Design: Corner/errors/corner_unclassified_and_already_governed_programs_rejected
        """
        env = fx.setup_open_program(
            program_overrides={"program_name": "Already Governed Program"}
        )
        live = fx.read_program(env["program"]["id"])
        assert live["state"] == "OPEN_FOR_PLACEMENT"

        response = api_client.create_classification(
            f.classification_payload(live["id"], live["version"]), COMPLIANCE
        )
        validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_CLASSIFIABLE.value)

        after = fx.read_program(env["program"]["id"])
        assert after["governing_classification_id"] == env["classification"]["id"], (
            "the original determination still governs the program"
        )
        assert after["version"] == live["version"], (
            "a refused determination does not advance the program version"
        )
        _, meta = validate_paginated(api_client.list_classifications(COMPLIANCE))
        assert meta["total_count"] == 1, (
            f"only the first determination exists, got total_count {meta['total_count']}"
        )


# ─── Section: a frozen bank takes no new wholesale money ───────────────────────

def _frozen_bank_with_a_breached_brokered_limit() -> dict:
    """Bank whose brokered-to-deposits ratio is 476 basis points against a board
    breach threshold of 400, so its posture evaluates to FROZEN."""
    env = fx.setup_active_placement(
        institution_overrides={
            "legal_name": "Frozen Bank NA",
            "core_deposits_cents": 20_000_000_000,
            "total_liabilities_cents": 30_000_000_000,
        },
        placement_overrides={
            "principal_cents": 1_000_000_000,
            "rate_bps": 470,
            "issue_date": "2026-08-01",
            "tenor_days": 60,
        },
    )
    env["limit"] = fx.create_concentration_limit(
        env["institution"]["id"], TREASURY,
        metric="BROKERED_TO_TOTAL_DEPOSITS",
        warning_threshold_bps=200,
        breach_threshold_bps=400,
    )
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


class TestFrozenInstitutionRefusesNewMoney:
    """A bank already in breach refuses a booking outright."""

    def test_a_new_limit_below_the_live_ratio_freezes_the_bank_immediately(self):
        """Each `ACTIVE` limit then takes that value into its own `current_value_bps` and
        sets `breach_state` to `BREACH` when the value is at or above its
        `breach_threshold_bps`, to `WARNING` when the value is at or above its
        `warning_threshold_bps` but below the breach level, and to `WITHIN` otherwise.

        PRD §3.7: The `concentration_posture` is `FROZEN` when at least one `ACTIVE` limit
        is in breach, `RESTRICTED` when none is in breach but at least one is in warning,
        and `OPEN` otherwise.

        PRD §3.7: The brokered-to-deposits value is `brokered_deposits_cents` multiplied by
        10000 and divided by `total_deposits_cents`, discarding the remainder.

        Design: Corner/errors/corner_frozen_institution_refuses_new_wholesale_placement
        """
        env = _frozen_bank_with_a_breached_brokered_limit()

        assert env["limit"]["current_value_bps"] == 476, (
            "1000000000 * 10000 / 21000000000 with the remainder discarded is 476, got "
            f"{env['limit']['current_value_bps']}"
        )
        assert env["limit"]["breach_state"] == "BREACH", (
            f"476 is at or above the breach level of 400, got {env['limit']['breach_state']}"
        )
        assert env["institution"]["concentration_posture"] == "FROZEN", (
            "one breached ACTIVE limit freezes the bank, got "
            f"{env['institution']['concentration_posture']}"
        )
        assert env["institution"]["breached_metric_count"] == 1, (
            f"exactly one limit is in breach, got {env['institution']['breached_metric_count']}"
        )

    def test_a_frozen_bank_refuses_the_booking_outright(self):
        """A bank whose `concentration_posture` is `FROZEN` accepts no new money at all,
        which is `ERR_CONCENTRATION_FROZEN`.

        PRD §3.7: A `FROZEN` bank opens no new programs and funds no new deposits, and the
        freeze lifts only when every `ACTIVE` limit has returned to `WITHIN` or `WARNING`.

        Design: Corner/errors/corner_frozen_institution_refuses_new_wholesale_placement
        """
        env = _frozen_bank_with_a_breached_brokered_limit()

        response = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"], principal_cents=500_000_000,
                rate_bps=470, issue_date="2026-08-01", tenor_days=60,
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_CONCENTRATION_FROZEN.value)

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 1_000_000_000, (
            "the refused booking moved no money, got "
            f"{institution['brokered_deposits_cents']}"
        )
        _, meta = validate_paginated(api_client.list_placements(DESK))
        assert meta["total_count"] == 1, (
            f"only the original tranche exists, got total_count {meta['total_count']}"
        )

    def test_a_frozen_bank_also_refuses_a_new_program(self):
        """A program cannot be opened at all while the bank's `concentration_posture` is
        `FROZEN`, which is reported as `ERR_CONCENTRATION_FROZEN`.

        Design: Corner/errors/corner_frozen_institution_refuses_new_wholesale_placement
        """
        env = _frozen_bank_with_a_breached_brokered_limit()

        response = api_client.create_program(
            f.program_payload(
                env["institution"]["id"], program_name="Blocked Core Program"
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_CONCENTRATION_FROZEN.value)

        _, meta = validate_paginated(api_client.list_programs(DESK))
        assert meta["total_count"] == 1, (
            f"only the original program exists, got total_count {meta['total_count']}"
        )


# ─── Section: the counterparty file gates ──────────────────────────────────────

class TestAgreementGates:
    """A DRAFT file cannot underwrite funding, and weak diligence cannot approve."""

    def test_a_draft_agreement_cannot_underwrite_a_new_program(self):
        """Where a counterparty is named, both the agreement's `status` and the
        counterparty's `diligence_status` must be `APPROVED` or `CONDITIONAL`; a `DRAFT`,
        `SUSPENDED`, `REJECTED` or `TERMINATED` file cannot underwrite new funding and the
        attempt is refused with `ERR_AGREEMENT_NOT_APPROVED`.

        Design: Corner/errors/corner_agreement_gates_reject_unapproved_and_insufficient_diligence
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Gate Bank NA"})
        broker = fx.register_broker(legal_name="Gate Brokers LLC")
        agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-DRAFT")
        assert agreement["status"] == "DRAFT", (
            f"a new agreement lands in DRAFT, got {agreement['status']}"
        )

        response = api_client.create_program(
            f.program_payload(
                env["institution"]["id"],
                program_name="Unbacked Brokered Program",
                funding_channel_claim="BROKERED",
                broker_id=broker["id"],
                agreement_id=agreement["id"],
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_APPROVED.value)

        _, meta = validate_paginated(api_client.list_programs(DESK))
        assert meta["total_count"] == 0, (
            f"a refused program create persists nothing, got total_count {meta['total_count']}"
        )

    def test_a_composite_below_sixty_cannot_be_approved_but_can_be_rejected(self):
        """An agreement whose composite score is below 60, or whose `aml_program_score` is
        below 60, cannot be approved at all and is refused with
        `ERR_DILIGENCE_SCORE_INSUFFICIENT`; the anti-money-laundering floor bites
        independently of the composite, so a composite of 78 sitting on an
        anti-money-laundering sub-score of 55 is still refused.

        PRD §3.2: The composite `diligence_score` is a weighted blend of the four
        sub-scores: thirty-five parts of `aml_program_score`, thirty parts of
        `financial_condition_score`, twenty parts of `insurance_coverage_score` and fifteen
        parts of `recordkeeping_score`, summed as an exact rational and divided by one
        hundred, with that single final quotient rounded half up to a whole point in the 0
        to 100 range.

        Design: Corner/errors/corner_agreement_gates_reject_unapproved_and_insufficient_diligence
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        broker = fx.register_broker(legal_name="Weak Brokers LLC")
        agreement = fx.draft_agreement(
            broker["id"], DESK,
            agreement_ref="AGR-WEAK",
            aml_program_score=40,
            financial_condition_score=50,
            insurance_coverage_score=50,
            recordkeeping_score=50,
        )
        under_diligence = fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
        assert under_diligence["diligence_score"] == 47, (
            "4650 divided by 100 rounded half up is 47, got "
            f"{under_diligence['diligence_score']}"
        )

        response = api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
        )
        validate_error(response, ApiErrorId.ERR_DILIGENCE_SCORE_INSUFFICIENT.value)

        assert fx.read_agreement(agreement["id"])["status"] == "UNDER_DILIGENCE", (
            "the refused approval leaves the agreement under diligence"
        )
        assert fx.read_broker(broker["id"])["approved_agreement_count"] == 0, (
            "no agreement was approved"
        )

        rejected = fx.diligence_action(agreement["id"], "REJECT", COMPLIANCE)
        assert rejected["status"] == "REJECTED", (
            f"such an agreement can only be rejected, got {rejected['status']}"
        )
        assert fx.read_broker(broker["id"])["diligence_status"] == "REJECTED", (
            "rejection sets the counterparty's diligence_status to REJECTED"
        )

    def test_the_aml_floor_bites_independently_of_a_passing_composite(self):
        """An agreement whose composite score is below 60, or whose `aml_program_score` is
        below 60, cannot be approved at all and is refused with
        `ERR_DILIGENCE_SCORE_INSUFFICIENT`; the anti-money-laundering floor bites
        independently of the composite, so a composite of 78 sitting on an
        anti-money-laundering sub-score of 55 is still refused.

        Design: Corner/errors/corner_agreement_gates_reject_unapproved_and_insufficient_diligence
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        broker = fx.register_broker(legal_name="AML Floor Brokers LLC")
        agreement = fx.draft_agreement(
            broker["id"], DESK,
            agreement_ref="AGR-AML",
            aml_program_score=55,
            financial_condition_score=90,
            insurance_coverage_score=90,
            recordkeeping_score=90,
        )
        under_diligence = fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
        assert under_diligence["diligence_score"] == 78, (
            "7775 divided by 100 rounded half up is 78, got "
            f"{under_diligence['diligence_score']}"
        )

        response = api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
        )
        validate_error(response, ApiErrorId.ERR_DILIGENCE_SCORE_INSUFFICIENT.value)

        assert fx.read_agreement(agreement["id"])["status"] == "UNDER_DILIGENCE", (
            "a composite of 78 does not rescue an anti-money-laundering score of 55"
        )


# ─── Section: unqualified notices and unreliable reliance ──────────────────────

class TestNoticeQualificationAndReliance:
    """A failed test cannot self-execute, and a DRAFT filing cannot be leaned on."""

    def test_a_ratio_of_exactly_2500_fails_and_the_notice_cannot_self_execute(self):
        """Under the twenty-five-percent basis, `test_outcome` is `QUALIFIED` only when
        `business_line_deposit_ratio_bps` is strictly below 2500 basis points, which is 25
        percent — a ratio of exactly 2500 fails.

        PRD §3.3: It may only do so when the arithmetic qualified — a notice whose
        `test_outcome` is `NOT_QUALIFIED` is refused with
        `ERR_PRIMARY_PURPOSE_TEST_NOT_MET`, and because no supervisory review path exists
        for a notice, the filer's only remedy is to withdraw it and re-file on the
        other-application basis.

        PRD §3.3: `business_line_deposit_ratio_bps` is `deposits_placed_at_ifs_cents`
        multiplied by 10000 and then divided by `total_customer_assets_cents`, discarding
        any remainder.

        Design: Corner/errors/corner_notice_not_qualified_and_draft_exception_reliance_rejected
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Boundary Bank NA"})
        broker = fx.register_broker(legal_name="Boundary Brokers LLC")

        filing = fx.file_exception(
            broker["id"], env["institution"]["id"], DESK,
            exception_basis="TWENTY_FIVE_PERCENT_TEST",
            total_customer_assets_cents=40_000_000_000,
            deposits_placed_at_ifs_cents=10_000_000_000,
        )
        assert filing["filing_type"] == "NOTICE", (
            "the twenty-five-percent basis is a NOTICE filing, got "
            f"{filing['filing_type']}"
        )
        assert filing["business_line_deposit_ratio_bps"] == 2500, (
            "10000000000 * 10000 / 40000000000 is exactly 2500, got "
            f"{filing['business_line_deposit_ratio_bps']}"
        )
        assert filing["test_outcome"] == "NOT_QUALIFIED", (
            f"a ratio of exactly 2500 fails, got {filing['test_outcome']}"
        )

        response = api_client.exception_filing_action(
            filing["id"], {"action": "SUBMIT"}, DESK
        )
        validate_error(response, ApiErrorId.ERR_PRIMARY_PURPOSE_TEST_NOT_MET.value)

        unchanged = fx.read_exception(filing["id"])
        assert unchanged["status"] == "DRAFT", (
            f"the refused submission leaves the notice in DRAFT, got {unchanged['status']}"
        )

    def test_a_determination_cannot_lean_on_a_draft_filing(self):
        """Where an exception is named, that filing's `status` must be `ACKNOWLEDGED` or
        `GRANTED` — a `DRAFT`, `UNDER_REVIEW`, `INFO_REQUESTED`, `DENIED`, `WITHDRAWN` or
        `REVOKED` filing cannot be relied upon and the attempt is refused with
        `ERR_EXCEPTION_NOT_RELIABLE`

        Design: Corner/errors/corner_notice_not_qualified_and_draft_exception_reliance_rejected
        """
        env = fx.setup_brokered_program(
            program_overrides={"program_name": "Reliance Program"}
        )
        draft_filing = fx.file_exception(
            env["broker"]["id"], env["institution"]["id"], DESK,
            exception_basis="TWENTY_FIVE_PERCENT_TEST",
            total_customer_assets_cents=40_000_000_000,
            deposits_placed_at_ifs_cents=4_000_000_000,
        )
        assert draft_filing["status"] == "DRAFT"
        assert draft_filing["test_outcome"] == "QUALIFIED", (
            "a ratio of 1000 basis points qualifies, so only the status blocks reliance"
        )

        response = api_client.create_classification(
            f.classification_payload(
                env["program"]["id"], env["program"]["version"],
                relied_exception_id=draft_filing["id"],
            ),
            COMPLIANCE,
        )
        validate_error(response, ApiErrorId.ERR_EXCEPTION_NOT_RELIABLE.value)

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "PENDING_CLASSIFICATION", (
            f"the program is still unclassified, got {program['state']}"
        )
        assert fx.read_exception(draft_filing["id"])["reliant_program_count"] == 0, (
            "the refused determination created no reliance"
        )


# ─── Section: booking calendars, rollover sources and funding transitions ──────

class TestPlacementCalendarSourceAndState:
    """The three refusals a tranche can earn from its own terms and its own state."""

    def test_a_non_maturity_program_refuses_a_tranche_carrying_a_tenor(self):
        """A maturity product must carry a `tenor_days` strictly greater than zero with
        `maturity_date` exactly `tenor_days` after `issue_date`, and a `NON_MATURITY`
        product must carry a `tenor_days` of 0 with `maturity_date` equal to `issue_date`;
        either incoherence is refused with `ERR_MATURITY_DATE_INVALID`.

        PRD §3.4: a program whose `product_type` is `MONEY_MARKET`, `SAVINGS` or `NOW` is
        `NON_MATURITY` regardless of tenor

        Design: Corner/errors/corner_placement_calendar_source_and_state_errors
        """
        env = fx.setup_open_program(program_overrides={
            "program_name": "Money Market Sweep Program",
            "product_type": "MONEY_MARKET",
            "tenor_days": 0,
            "offered_rate_bps": 200,
            "early_withdrawal_penalty_days": 0,
        })
        assert env["program"]["tenor_bucket"] == "NON_MATURITY", (
            f"a money market program is NON_MATURITY, got {env['program']['tenor_bucket']}"
        )
        assert env["institution"]["rate_cap_regime"] == "EXEMPT", (
            "a well capitalised bank is EXEMPT, so no ceiling gate can pre-empt the calendar"
        )

        response = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"], rate_bps=200, tenor_days=30
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_MATURITY_DATE_INVALID.value)

        _, meta = validate_paginated(api_client.list_placements(DESK))
        assert meta["total_count"] == 0, (
            f"the refused booking persisted nothing, got total_count {meta['total_count']}"
        )

        accepted = validate_success(
            api_client.create_placement(
                f.placement_payload(env["program"]["id"], rate_bps=200, tenor_days=0),
                DESK,
            ),
            expected_status=201,
        )
        assert accepted["maturity_date"] == accepted["issue_date"], (
            "a zero tenor matures on its issue date, got "
            f"{accepted['maturity_date']} against {accepted['issue_date']}"
        )
        assert accepted["tenor_bucket"] == "NON_MATURITY", (
            f"the tranche inherits NON_MATURITY, got {accepted['tenor_bucket']}"
        )

    def test_an_active_predecessor_is_not_an_eligible_rollover_source(self):
        """Where `rolled_from_placement_id` is supplied it must name a placement of the
        *same* program whose `funding_status` is `MATURED` and which has not already been
        rolled; an `ACTIVE`, `PENDING` or `CANCELLED` source, a source belonging to another
        program, or a source already consumed by an earlier successor, is refused with
        `ERR_ROLLOVER_SOURCE_INVALID`.

        Design: Corner/errors/corner_placement_calendar_source_and_state_errors
        """
        env = fx.setup_active_placement(
            program_overrides={"program_name": "Rollover Source Program"},
            placement_overrides={"principal_cents": 1_000_000_000},
        )
        assert env["placement"]["funding_status"] == "ACTIVE"

        response = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=500_000_000,
                rolled_from_placement_id=env["placement"]["id"],
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_ROLLOVER_SOURCE_INVALID.value)

        _, meta = validate_paginated(api_client.list_placements(DESK))
        assert meta["total_count"] == 1, (
            "only the predecessor exists, got total_count "
            f"{meta['total_count']}"
        )

    def test_a_second_activation_of_a_live_tranche_is_refused(self):
        """Any funding action that is not a declared transition out of the tranche's
        current `funding_status` — a second activation, or an early withdrawal of an
        already-matured tranche — is refused with `ERR_PLACEMENT_STATE_INVALID`.

        PRD §3.5: It moves the tranche `PENDING → ACTIVE` and requires three things beyond
        the transition itself

        Design: Corner/errors/corner_placement_calendar_source_and_state_errors
        """
        env = fx.setup_active_placement(
            placement_overrides={"principal_cents": 1_000_000_000},
        )

        response = api_client.funding_action(
            env["placement"]["id"], f.funding_action_payload("ACTIVATE"), DESK
        )
        validate_error(response, ApiErrorId.ERR_PLACEMENT_STATE_INVALID.value)

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 1_000_000_000, (
            "the refused second activation did not double the money, got "
            f"{institution['brokered_deposits_cents']}"
        )
        program = fx.read_program(env["program"]["id"])
        assert program["outstanding_principal_cents"] == 1_000_000_000, (
            "the program's outstanding principal was counted once, got "
            f"{program['outstanding_principal_cents']}"
        )

    def test_an_early_withdrawal_of_a_pending_tranche_is_refused(self):
        """It moves the tranche `ACTIVE → WITHDRAWN_EARLY` and requires a
        `withdrawal_date` that is present and strictly before `maturity_date`; the field is
        required for this action and ignored for the others.

        PRD §3.5: Any funding action that is not a declared transition out of the tranche's
        current `funding_status` — a second activation, or an early withdrawal of an
        already-matured tranche — is refused with `ERR_PLACEMENT_STATE_INVALID`.

        Design: Corner/errors/corner_placement_calendar_source_and_state_errors
        """
        env = fx.setup_booked_placement(
            placement_overrides={"principal_cents": 1_000_000_000},
        )
        assert env["placement"]["funding_status"] == "PENDING"
        assert env["placement"]["maturity_date"] == "2026-09-30", (
            "the default tranche runs 60 days from 2026-08-01, got "
            f"{env['placement']['maturity_date']}"
        )

        response = api_client.funding_action(
            env["placement"]["id"],
            f.funding_action_payload("EARLY_WITHDRAW", withdrawal_date="2026-08-15"),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_PLACEMENT_STATE_INVALID.value)

        placement = fx.read_placement(env["placement"]["id"])
        assert placement["funding_status"] == "PENDING", (
            f"the tranche is untouched, got {placement['funding_status']}"
        )
        assert placement["settlement_date"] is None, (
            "settlement_date stays null while the tranche is PENDING, got "
            f"{placement['settlement_date']}"
        )


# ─── Section: the remaining lifecycle refusals and a stale determination ───────

class TestRemainingStateInvalidCodesAndStaleClassification:
    """Each lifecycle owns its own state code, and a version bump stales a determination."""

    def test_activating_a_draft_plan_is_refused(self):
        """Any lifecycle action that is not a declared transition out of the plan's current
        `status` is refused with `ERR_PLAN_STATE_INVALID`, and every lifecycle action
        accepts an optional `note`.

        PRD §3.7: Activation moves the plan `APPROVED → ACTIVATED` and is where the
        arithmetic happens.

        Design: Corner/errors/corner_remaining_state_invalid_codes_and_stale_classification
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Ladder State Bank NA"})
        plan = fx.draft_contingency_plan(env["institution"]["id"], TREASURY)
        assert plan["status"] == "DRAFT", f"a new plan is DRAFT, got {plan['status']}"

        response = api_client.plan_lifecycle_action(
            plan["id"], {"action": "ACTIVATE"}, TREASURY
        )
        validate_error(response, ApiErrorId.ERR_PLAN_STATE_INVALID.value)

        unchanged = fx.read_plan(plan["id"])
        assert unchanged["status"] == "DRAFT", (
            f"the refused activation left the plan in DRAFT, got {unchanged['status']}"
        )
        assert unchanged["activation_stage"] == "NONE", (
            "`activation_stage` is `NONE` for any plan whose `status` is anything other "
            f"than `ACTIVATED`, got {unchanged['activation_stage']}"
        )
        assert unchanged["required_buffer_cents"] == 0, (
            f"no buffer was sized, got {unchanged['required_buffer_cents']}"
        )

    def test_attesting_a_draft_filing_is_refused(self):
        """Any workflow action that is not a declared transition out of the filing's
        current `status` is refused with `ERR_FILING_STATE_INVALID`.

        PRD §3.9: Attesting moves it `PREPARED → ATTESTED` and stamps
        `attested_by_user_id`, and it is the segregation-of-duties gate: the attesting
        identifier must differ from `prepared_by_user_id`.

        Design: Corner/errors/corner_remaining_state_invalid_codes_and_stale_classification
        """
        env = fx.setup_bank(institution_overrides={"legal_name": "Ladder State Bank NA"})
        filing = fx.create_call_report_filing(env["institution"]["id"], DESK)
        assert filing["status"] == "DRAFT", f"a new filing is DRAFT, got {filing['status']}"

        response = api_client.filing_workflow_action(
            filing["id"], {"action": "ATTEST"}, COMPLIANCE
        )
        validate_error(response, ApiErrorId.ERR_FILING_STATE_INVALID.value)

        unchanged = fx.read_filing(filing["id"])
        assert unchanged["status"] == "DRAFT", (
            f"the refused attestation left the filing in DRAFT, got {unchanged['status']}"
        )
        assert unchanged["attested_by_user_id"] is None, (
            "nothing was stamped, got "
            f"{unchanged['attested_by_user_id']}"
        )

    def test_attesting_an_unclassified_program_reports_the_state_code(self):
        """Any state action that is not a declared transition out of the program's current
        `state`, including any action at all against a `CLOSED` program, is refused with
        `ERR_PROGRAM_STATE_INVALID`.

        PRD §3.4: Attestation by a funding-desk officer moves the program `CLASSIFIED →
        OPEN_FOR_PLACEMENT` and stamps `attested_by_user_id` with the acting identifier.

        PRD §2.8 rule 18: Program lifecycle admissibility — `ERR_PROGRAM_STATE_INVALID`.
        Program state actions.

        PRD §2.8: Every request is evaluated against the rules below in ascending priority
        order and, on the first rule it violates, is rejected with that rule's error and
        nothing else is evaluated.

        Design: Corner/errors/corner_remaining_state_invalid_codes_and_stale_classification
        """
        env = fx.setup_brokered_program(
            program_overrides={"program_name": "Unattested Brokered Program"}
        )
        assert env["program"]["state"] == "PENDING_CLASSIFICATION"

        response = api_client.program_state_action(
            env["program"]["id"], {"action": "ATTEST_CLASSIFICATION"}, DESK
        )
        validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID.value)

        unchanged = fx.read_program(env["program"]["id"])
        assert unchanged["state"] == "PENDING_CLASSIFICATION", (
            f"the program did not open, got {unchanged['state']}"
        )
        assert unchanged["attested_by_user_id"] is None, (
            f"nothing was stamped, got {unchanged['attested_by_user_id']}"
        )

    def test_a_capital_downgrade_makes_the_standing_determination_stale(self):
        """The governing determination must also still be current: the determination's
        `program_version_at_determination` must equal the program's live `version` at the
        instant of booking, and when it does not — which happens precisely when a
        supervisory capital re-categorisation has bumped every program's version since the
        determination was made — the booking is refused with `ERR_CLASSIFICATION_STALE`
        until the program is re-classified.

        PRD §3.1: Every one of the bank's programs whose `state` is not `CLOSED` has its
        `effective_cap_bps` recomputed and its `version` incremented by exactly 1, processed
        in `created_at` ascending order; because a program's version moved, each program's
        standing determination is now stale for the purpose of booking new deposits, which
        is what §3.5 reports as `ERR_CLASSIFICATION_STALE` until the program is
        re-classified.

        PRD §3.1: The national leg is the publication's `published_national_rate_bps` plus
        75 basis points.

        Design: Corner/errors/corner_remaining_state_invalid_codes_and_stale_classification
        """
        env = fx.setup_open_program(
            program_overrides={"program_name": "Stale Determination Program"}
        )
        assert env["program"]["tenor_bucket"] == "DAYS_31_90", (
            "the default 60 day tenor lands in the second maturity bucket, got "
            f"{env['program']['tenor_bucket']}"
        )
        version_before = fx.read_program(env["program"]["id"])["version"]

        institution = fx.change_capital_category(
            env["institution"]["id"], "ADEQUATELY_CAPITALIZED"
        )
        assert institution["rate_cap_regime"] == "CAPPED", (
            f"a downgrade caps the bank, got {institution['rate_cap_regime']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["version"] == version_before + 1, (
            "the cascade bumps the program version by exactly 1, got "
            f"{program['version']} from {version_before}"
        )
        assert program["effective_cap_bps"] == 475, (
            "400 basis points published plus 75 is 475, got "
            f"{program['effective_cap_bps']}"
        )

        response = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"], principal_cents=1_000_000_000, rate_bps=470
            ),
            DESK,
        )
        validate_error(response, ApiErrorId.ERR_CLASSIFICATION_STALE.value)

        _, meta = validate_paginated(api_client.list_placements(DESK))
        assert meta["total_count"] == 0, (
            f"no tranche was booked, got total_count {meta['total_count']}"
        )
        assert fx.read_institution(env["institution"]["id"])["brokered_deposits_cents"] == 0, (
            "no money moved onto the balance sheet"
        )
