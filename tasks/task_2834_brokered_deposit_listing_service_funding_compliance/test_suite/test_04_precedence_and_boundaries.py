"""Single-error precedence collisions and boundary arithmetic.

Two families of behaviour live here.  The first is the priority ordering of PRD
§2.8: a request that violates two rules at once is rejected with the
lower-numbered rule's error and nothing else is evaluated, and the PRD names
three booking collisions explicitly.  The second is the exact boundary
direction of the PRD's arithmetic tests -- the primary-purpose ratios of §3.3,
the inclusive maturity-ladder cap of §3.5 and the zero-denominator/empty-set
edge of §2.4 and §3.7.

Every test builds its own book from scratch through the PRD's own endpoints.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN, COMPLIANCE, DESK, TREASURY


# ─── Local composition helpers (test_helpers is read-only) ────────────────────

def _list_placements(**params) -> tuple:
    return validate_paginated(api_client.list_placements(ADMIN, params=params))


def _setup_open_program_with_active_neighbour(principal_cents: int,
                                             program_name: str) -> dict:
    """Bank plus an OPEN_FOR_PLACEMENT brokered program holding one ACTIVE
    tranche issued 2026-08-01 for 60 days, so it matures 2026-09-30.

    The bank keeps the WELL_CAPITALIZED default, so `rate_cap_regime` is
    `EXEMPT` and no ceiling applies to anything booked below (PRD §3.1).
    """
    env = fx.setup_open_program(program_overrides={"program_name": program_name})
    neighbour = fx.book_placement(
        env["program"]["id"], DESK,
        principal_cents=principal_cents,
        rate_bps=470,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    env["neighbour"] = fx.activate_placement(neighbour["id"], DESK)
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


def _setup_open_and_unattested_programs() -> dict:
    """The neighbour book above, plus a second program of the same bank and the
    same agreement carried only as far as CLASSIFIED, never attested."""
    env = _setup_open_program_with_active_neighbour(10_000_000_000, "Program X open")
    program_y = fx.open_program(
        env["institution"]["id"], DESK,
        broker_id=env["broker"]["id"],
        agreement_id=env["agreement"]["id"],
        program_name="Program Y unattested",
        funding_channel_claim="BROKERED",
    )
    fx.classify_program(program_y["id"], program_y["version"], COMPLIANCE)
    env["program_y"] = fx.read_program(program_y["id"])
    return env


class TestProgramNotOpenBeatsMaturityWindowConcentration:
    """One booking request violates the lifecycle rule and the ladder rule at
    once; the PRD names which of the two is reported."""

    def test_unattested_program_reports_program_not_open_not_ladder_aggregate(self):
        """PRD §2.8: "A placement booked against a program that is not open and
        that would also breach the maturity-window aggregate reports
        `ERR_PROGRAM_NOT_OPEN`, not `ERR_MATURITY_WINDOW_CONCENTRATION`."

        PRD §3.5: "The program must already have a governing determination,
        without which the booking is refused with `ERR_CLASSIFICATION_REQUIRED`,
        and it must be sitting in `OPEN_FOR_PLACEMENT`: a `CLASSIFIED` but
        un-attested program, a `SUSPENDED` program and a program under
        reclassification all refuse new money with `ERR_PROGRAM_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/program_not_open_beats_maturity_window_concentration
        """
        env = _setup_open_and_unattested_programs()
        assert env["program_y"]["state"] == "CLASSIFIED", (
            "program Y must sit in CLASSIFIED, i.e. determined but never attested, "
            f"got {env['program_y']['state']}"
        )
        assert env["institution"]["total_deposits_cents"] == 50_000_000_000, (
            "core 40,000,000,000 plus the ACTIVE brokered 10,000,000,000 makes "
            "total_deposits_cents 50,000,000,000, so the ladder cap is 17,500,000,000; "
            f"got {env['institution']['total_deposits_cents']}"
        )

        # 7,500,000,000 + the 10,000,000,000 neighbour maturing on the same day
        # reaches the 17,500,000,000 cap exactly, so both rules are violated.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program_y"]["id"],
                principal_cents=7_500_000_000,
                rate_bps=470,
                issue_date="2026-08-01",
                tenor_days=60,
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN.value)
        assert resp.json()["data"]["error_id"] != (
            ApiErrorId.ERR_MATURITY_WINDOW_CONCENTRATION.value
        ), (
            "the lower-numbered lifecycle rule must win even though the ladder "
            "aggregate 17,500,000,000 also reaches the cap exactly"
        )

        rows, meta = _list_placements(program_id=env["program_y"]["id"])
        assert meta["total_count"] == 0 and rows == [], (
            "a refused booking must persist no placement row under the program"
        )

    def test_attested_program_then_reports_maturity_window_concentration(self):
        """PRD §3.5: "The cap is an inclusive bound: an exposure that reaches the
        cap, not merely one that passes it, is refused with
        `ERR_MATURITY_WINDOW_CONCENTRATION`."

        PRD §2.8: "A placement booked against a program that is not open and that
        would also breach the maturity-window aggregate reports
        `ERR_PROGRAM_NOT_OPEN`, not `ERR_MATURITY_WINDOW_CONCENTRATION`."

        Design: Difficulty/priority_pair_validation_conflict/program_not_open_beats_maturity_window_concentration
        """
        env = _setup_open_and_unattested_programs()
        program_y = fx.attest_program(env["program_y"]["id"], DESK)
        assert program_y["state"] == "OPEN_FOR_PLACEMENT", (
            "attestation must move the program CLASSIFIED -> OPEN_FOR_PLACEMENT, "
            f"got {program_y['state']}"
        )

        # The identical body now clears the lifecycle rule and surfaces the
        # capacity rule that was masked before.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program_y"]["id"],
                principal_cents=7_500_000_000,
                rate_bps=470,
                issue_date="2026-08-01",
                tenor_days=60,
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_MATURITY_WINDOW_CONCENTRATION.value)

        rows, meta = _list_placements(program_id=env["program_y"]["id"])
        assert meta["total_count"] == 0 and rows == [], (
            "the replayed booking is refused too, so still no placement row exists"
        )


def _setup_capped_program_with_active_source() -> dict:
    """An ADEQUATELY_CAPITALIZED bank -- so `rate_cap_regime` is `CAPPED` -- with
    a 400 bps benchmark effective 2026-07-01, one open rollover-enabled program
    and one ACTIVE tranche that is therefore an ineligible rollover source."""
    env = fx.setup_open_program(
        institution_overrides={"capital_category": "ADEQUATELY_CAPITALIZED"},
        program_overrides={"program_name": "Rolling CD", "rollover_enabled": True},
    )
    source = fx.book_placement(
        env["program"]["id"], DESK,
        principal_cents=1_000_000_000,
        rate_bps=470,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    env["source"] = fx.activate_placement(source["id"], DESK)
    env["program"] = fx.read_program(env["program"]["id"])
    return env


class TestRateCapExceededBeatsRolloverSourceInvalid:
    """A booking that both over-prices and mis-references its predecessor."""

    def test_over_ceiling_rollover_reports_rate_cap_exceeded(self):
        """PRD §2.8: "A placement that both exceeds the rate ceiling and names an
        ineligible rollover source reports `ERR_RATE_CAP_EXCEEDED`, not
        `ERR_ROLLOVER_SOURCE_INVALID`."

        PRD §3.5: "Where the bank's `rate_cap_regime` is `CAPPED`, the tranche's
        `rate_bps` must not exceed the ceiling computed as of its own
        `issue_date`; equality passes and one basis point above is refused with
        `ERR_RATE_CAP_EXCEEDED`, while an unpublished benchmark for the tranche's
        bucket surfaces as `ERR_NO_RATE_CAP_PUBLISHED`."

        Design: Difficulty/priority_pair_validation_conflict/rate_cap_exceeded_beats_rollover_source_invalid
        """
        env = _setup_capped_program_with_active_source()
        assert env["program"]["effective_cap_bps"] == 475, (
            "the national leg is the published 400 bps plus 75, and no local "
            f"comparison is asserted, so the ceiling is 475 bps; got "
            f"{env['program']['effective_cap_bps']}"
        )
        assert env["source"]["funding_status"] == "ACTIVE", (
            "the named rollover source must be ACTIVE, never MATURED, "
            f"got {env['source']['funding_status']}"
        )

        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=1_000_000_000,
                rate_bps=500,
                issue_date="2026-08-01",
                tenor_days=60,
                rolled_from_placement_id=env["source"]["id"],
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_CAP_EXCEEDED.value)
        assert resp.json()["data"]["error_id"] != (
            ApiErrorId.ERR_ROLLOVER_SOURCE_INVALID.value
        ), (
            "the ceiling rule outranks the rollover-source rule, so the ACTIVE "
            "source must not be the reported failure"
        )

        rows, meta = _list_placements(rolled_from_placement_id=env["source"]["id"])
        assert meta["total_count"] == 0 and rows == [], (
            "no successor tranche may be persisted by a refused booking"
        )

    def test_priced_at_ceiling_then_reports_rollover_source_invalid(self):
        """PRD §3.5: "Where `rolled_from_placement_id` is supplied it must name a
        placement of the *same* program whose `funding_status` is `MATURED` and
        which has not already been rolled; an `ACTIVE`, `PENDING` or `CANCELLED`
        source, a source belonging to another program, or a source already
        consumed by an earlier successor, is refused with
        `ERR_ROLLOVER_SOURCE_INVALID`."

        PRD §2.8: "A placement that both exceeds the rate ceiling and names an
        ineligible rollover source reports `ERR_RATE_CAP_EXCEEDED`, not
        `ERR_ROLLOVER_SOURCE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/rate_cap_exceeded_beats_rollover_source_invalid
        """
        env = _setup_capped_program_with_active_source()

        # 470 bps sits under the 475 bps ceiling, so only the rollover reference
        # is still wrong.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=1_000_000_000,
                rate_bps=470,
                issue_date="2026-08-01",
                tenor_days=60,
                rolled_from_placement_id=env["source"]["id"],
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_ROLLOVER_SOURCE_INVALID.value)

        rows, meta = _list_placements(rolled_from_placement_id=env["source"]["id"])
        assert meta["total_count"] == 0 and rows == [], (
            "an ineligible source may never acquire a successor tranche"
        )
        source = fx.read_placement(env["source"]["id"])
        assert source["funding_status"] == "ACTIVE", (
            "the refused booking must leave the source tranche untouched, "
            f"got {source['funding_status']}"
        )


def _setup_open_reciprocal_program() -> dict:
    """A counterparty-less MONEY_MARKET program claiming `RECIPROCAL_NETWORK`,
    carried to OPEN_FOR_PLACEMENT.  The bank's `total_liabilities_cents` is
    50,000,000,000, so remaining reciprocal capacity is 12,500,000,000 and the
    governing determination comes out `RECIPROCAL_EXCLUDED` (PRD §3.4)."""
    return fx.setup_open_core_program(
        program_overrides={
            "program_name": "Reciprocal MMDA",
            "funding_channel_claim": "RECIPROCAL_NETWORK",
            "product_type": "MONEY_MARKET",
            "tenor_days": 0,
            "offered_rate_bps": 400,
            "early_withdrawal_penalty_days": 0,
            "titling_convention": "SINGLE_FIDUCIARY_ACCOUNT",
            "reciprocal_arrangement_cents": 1_000_000_000,
        },
        classification_overrides={"rationale_code": "RECIPROCAL_NETWORK_EXCLUSION"},
    )


class TestMaturityDateInvalidBeatsReciprocalCapExceeded:
    """Calendar coherence outranks reciprocal capacity on one booking."""

    def test_incoherent_tenor_reports_maturity_date_invalid(self):
        """PRD §2.8: "A placement whose calendar terms are incoherent and whose
        principal also exceeds the remaining reciprocal capacity reports
        `ERR_MATURITY_DATE_INVALID`, not `ERR_RECIPROCAL_CAP_EXCEEDED`."

        PRD §3.5: "A maturity product must carry a `tenor_days` strictly greater
        than zero with `maturity_date` exactly `tenor_days` after `issue_date`,
        and a `NON_MATURITY` product must carry a `tenor_days` of 0 with
        `maturity_date` equal to `issue_date`; either incoherence is refused with
        `ERR_MATURITY_DATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/maturity_date_invalid_beats_reciprocal_cap_exceeded
        """
        env = _setup_open_reciprocal_program()
        classification = env["classification"]
        asserts.assert_deposit_classification(classification)
        assert classification["determined_class"] == "RECIPROCAL_EXCLUDED", (
            "the reciprocal-exclusion branch runs first and 12,500,000,000 of "
            "capacity covers the 1,000,000,000 arrangement, so the class must be "
            f"RECIPROCAL_EXCLUDED, got {classification['determined_class']}"
        )
        assert classification["deposit_broker_prong"] == "NOT_APPLICABLE", (
            "the first four branches record deposit_broker_prong NOT_APPLICABLE, "
            f"got {classification['deposit_broker_prong']}"
        )
        assert classification["call_report_line"] == "RC_O_M_RECIPROCAL", (
            "RECIPROCAL_EXCLUDED maps onto RC_O_M_RECIPROCAL, "
            f"got {classification['call_report_line']}"
        )

        # tenor_days 60 on a NON_MATURITY product AND 13,000,000,000 against
        # 12,500,000,000 of remaining capacity: both rules are violated.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=13_000_000_000,
                rate_bps=400,
                issue_date="2026-08-01",
                tenor_days=60,
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_MATURITY_DATE_INVALID.value)
        assert resp.json()["data"]["error_id"] != (
            ApiErrorId.ERR_RECIPROCAL_CAP_EXCEEDED.value
        ), (
            "calendar coherence is the lower-numbered rule, so the capacity "
            "breach must stay unreported"
        )

    def test_coherent_tenor_then_reports_reciprocal_cap_exceeded(self):
        """PRD §3.5: "For a program whose governing determination came out as
        `RECIPROCAL_EXCLUDED`, the tranche's `principal_cents` must not exceed the
        bank's remaining reciprocal capacity — 25 percent of
        `total_liabilities_cents`, taking the integer part, less the bank's
        current `reciprocal_deposits_cents`, floored at zero — and a principal
        above that capacity is refused with `ERR_RECIPROCAL_CAP_EXCEEDED`."

        PRD §2.8: "A placement whose calendar terms are incoherent and whose
        principal also exceeds the remaining reciprocal capacity reports
        `ERR_MATURITY_DATE_INVALID`, not `ERR_RECIPROCAL_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/maturity_date_invalid_beats_reciprocal_cap_exceeded
        """
        env = _setup_open_reciprocal_program()

        # tenor_days 0 makes maturity_date equal issue_date, so only the capacity
        # gate is still violated.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=13_000_000_000,
                rate_bps=400,
                issue_date="2026-08-01",
                tenor_days=0,
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_RECIPROCAL_CAP_EXCEEDED.value)

        rows, meta = _list_placements(program_id=env["program"]["id"])
        assert meta["total_count"] == 0 and rows == [], (
            "neither refused booking may leave a placement row behind"
        )
        institution = fx.read_institution(env["institution"]["id"])
        assert institution["reciprocal_deposits_cents"] == 0, (
            "no tranche reached ACTIVE, so the reciprocal bucket must still be 0, "
            f"got {institution['reciprocal_deposits_cents']}"
        )


def _setup_bank_and_listing_service() -> dict:
    """One bank and one listing-service counterparty; the primary-purpose tests
    read the filing's own fields alone, so no agreement or program is needed."""
    env = fx.setup_bank(publish_benchmark=False)
    env["broker"] = fx.register_broker(
        legal_name="Boundary Sweep Advisors LLC",
        broker_type="LISTING_SERVICE",
        has_placement_discretion=False,
        fee_structure="PER_ACCOUNT_FEE",
        fee_flat_cents=1000,
    )
    return env


def _file_exception(env, **overrides) -> dict:
    resp = api_client.create_exception(
        f.exception_payload(env["broker"]["id"], env["institution"]["id"], **overrides),
        DESK,
    )
    return validate_success(resp, expected_status=201)


class TestPrimaryPurposeTestsOppositeBoundaryDirections:
    """The two arithmetic tests read their ratios with opposite boundary
    directions: strictly below 2500 bps versus at or above 7500 bps."""

    def test_twenty_five_percent_test_is_strictly_below_2500_bps(self):
        """PRD §3.3: "Under the twenty-five-percent basis, `test_outcome` is
        `QUALIFIED` only when `business_line_deposit_ratio_bps` is strictly below
        2500 basis points, which is 25 percent — a ratio of exactly 2500 fails."

        PRD §3.3: "`business_line_deposit_ratio_bps` is
        `deposits_placed_at_ifs_cents` multiplied by 10000 and then divided by
        `total_customer_assets_cents`, discarding any remainder."

        PRD §3.3: "It is also stamped with `reporting_due_date`, a calendar date
        set to the logical clock's date plus 90 days."

        Design: Difficulty/boundary_precision_check/primary_purpose_tests_opposite_boundary_directions
        """
        env = _setup_bank_and_listing_service()

        just_below = _file_exception(
            env,
            exception_basis="TWENTY_FIVE_PERCENT_TEST",
            designated_business_line="advisory cash sweep just under",
            total_customer_assets_cents=40_000_000_000,
            deposits_placed_at_ifs_cents=9_999_999_999,
        )
        asserts.assert_primary_purpose_exception(just_below)
        assert just_below["business_line_deposit_ratio_bps"] == 2499, (
            "9,999,999,999 * 10000 // 40,000,000,000 discards the remainder and "
            f"gives 2499 bps, got {just_below['business_line_deposit_ratio_bps']}"
        )
        assert just_below["test_outcome"] == "QUALIFIED", (
            "2499 bps is strictly below 2500 bps, so the notice qualifies, "
            f"got {just_below['test_outcome']}"
        )

        exactly_at = _file_exception(
            env,
            exception_basis="TWENTY_FIVE_PERCENT_TEST",
            designated_business_line="advisory cash sweep exactly at",
            total_customer_assets_cents=40_000_000_000,
            deposits_placed_at_ifs_cents=10_000_000_000,
        )
        asserts.assert_primary_purpose_exception(exactly_at)
        assert exactly_at["business_line_deposit_ratio_bps"] == 2500, (
            "10,000,000,000 * 10000 // 40,000,000,000 is exactly 2500 bps, "
            f"got {exactly_at['business_line_deposit_ratio_bps']}"
        )
        assert exactly_at["test_outcome"] == "NOT_QUALIFIED", (
            "a ratio of exactly 2500 bps fails the strictly-below test, "
            f"got {exactly_at['test_outcome']}"
        )

        for filing in (just_below, exactly_at):
            assert filing["status"] == "DRAFT", (
                f"a new filing lands in DRAFT, got {filing['status']}"
            )
            assert filing["reporting_due_date"] == "2026-10-30", (
                "the clock reads 2026-08-01, so the due date is 2026-10-30, "
                f"got {filing['reporting_due_date']}"
            )

    def test_enabling_transactions_test_is_at_or_above_7500_bps(self):
        """PRD §3.3: "Under the enabling-transactions basis, `test_outcome` is
        `QUALIFIED` when `enabling_transaction_ratio_bps` is at or above 7500
        basis points, which is 75 percent — a ratio of exactly 7500 qualifies."

        PRD §3.3: "Both ratios are computed at creation and recomputed on
        submission, from the filing's own fields alone — no program or placement
        data enters."

        Design: Difficulty/boundary_precision_check/primary_purpose_tests_opposite_boundary_directions
        """
        env = _setup_bank_and_listing_service()

        exactly_at = _file_exception(
            env,
            exception_basis="ENABLING_TRANSACTIONS_TEST",
            designated_business_line="payment enabling exactly at",
            total_customer_assets_cents=40_000_000_000,
            deposits_placed_at_ifs_cents=1_000_000_000,
            enabling_transaction_count=3,
            total_transaction_count=4,
        )
        asserts.assert_primary_purpose_exception(exactly_at)
        assert exactly_at["enabling_transaction_ratio_bps"] == 7500, (
            "3 * 10000 // 4 is exactly 7500 bps, "
            f"got {exactly_at['enabling_transaction_ratio_bps']}"
        )
        assert exactly_at["test_outcome"] == "QUALIFIED", (
            "a ratio of exactly 7500 bps qualifies under the at-or-above test, "
            f"got {exactly_at['test_outcome']}"
        )
        assert exactly_at["business_line_deposit_ratio_bps"] == 250, (
            "the ratio the declared basis does not read is still computed from the "
            "filing's own fields: 1,000,000,000 * 10000 // 40,000,000,000 == 250, "
            f"got {exactly_at['business_line_deposit_ratio_bps']}"
        )

        just_below = _file_exception(
            env,
            exception_basis="ENABLING_TRANSACTIONS_TEST",
            designated_business_line="payment enabling just under",
            total_customer_assets_cents=40_000_000_000,
            deposits_placed_at_ifs_cents=1_000_000_000,
            enabling_transaction_count=2999,
            total_transaction_count=4000,
        )
        asserts.assert_primary_purpose_exception(just_below)
        assert just_below["enabling_transaction_ratio_bps"] == 7497, (
            "2999 * 10000 // 4000 discards the remainder and gives 7497 bps, "
            f"got {just_below['enabling_transaction_ratio_bps']}"
        )
        assert just_below["test_outcome"] == "NOT_QUALIFIED", (
            "7497 bps sits below 7500 bps, so the notice does not qualify, "
            f"got {just_below['test_outcome']}"
        )


class TestMaturityWindowAggregateCapInclusiveBoundary:
    """The ladder cap is an inclusive lower-bound rejection measured in whole
    cents: reaching it is refused, one cent short of it is accepted."""

    def test_exposure_equal_to_the_cap_is_refused(self):
        """PRD §3.5: "The exposure is the candidate's own `principal_cents` plus
        the `principal_cents` of every neighbour, and the cap is 3500 basis points
        — 35 percent — of the bank's `total_deposits_cents`, taking the integer
        part."

        PRD §3.5: "The cap is an inclusive bound: an exposure that reaches the
        cap, not merely one that passes it, is refused with
        `ERR_MATURITY_WINDOW_CONCENTRATION`."

        Design: Difficulty/boundary_precision_check/maturity_window_aggregate_cap_inclusive_boundary
        """
        env = _setup_open_program_with_active_neighbour(
            10_000_000_000, "Inclusive Cap CD"
        )
        assert env["neighbour"]["maturity_date"] == "2026-09-30", (
            "2026-08-01 advanced by 60 calendar days is 2026-09-30, "
            f"got {env['neighbour']['maturity_date']}"
        )
        assert env["neighbour"]["tenor_bucket"] == "DAYS_31_90", (
            "a 60 day time deposit lands in DAYS_31_90, "
            f"got {env['neighbour']['tenor_bucket']}"
        )
        assert env["institution"]["total_deposits_cents"] == 50_000_000_000, (
            "the cap is 3500 bps of 50,000,000,000, which is 17,500,000,000; "
            f"total_deposits_cents was {env['institution']['total_deposits_cents']}"
        )

        # 7,500,000,000 + 10,000,000,000 == 17,500,000,000 == the cap exactly.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=7_500_000_000,
                rate_bps=470,
                issue_date="2026-08-01",
                tenor_days=60,
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_MATURITY_WINDOW_CONCENTRATION.value)

    def test_exposure_one_cent_below_the_cap_is_accepted(self):
        """PRD §3.5: "The cap is an inclusive bound: an exposure that reaches the
        cap, not merely one that passes it, is refused with
        `ERR_MATURITY_WINDOW_CONCENTRATION`."

        PRD §2.11: "Placements in `PENDING`, `MATURED`, `WITHDRAWN_EARLY`,
        `ROLLED_OVER` or `CANCELLED` contribute to none of them."

        Design: Difficulty/boundary_precision_check/maturity_window_aggregate_cap_inclusive_boundary
        """
        env = _setup_open_program_with_active_neighbour(
            10_000_000_000, "Inclusive Cap CD"
        )

        # 7,499,999,999 + 10,000,000,000 == 17,499,999,999, one cent short.
        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=7_499_999_999,
                rate_bps=470,
                issue_date="2026-08-01",
                tenor_days=60,
            ),
            DESK,
        )
        accepted = validate_success(resp, expected_status=201)
        asserts.assert_deposit_placement(accepted)
        assert accepted["principal_cents"] == 7_499_999_999, (
            "the accepted tranche keeps the principal it was booked with, "
            f"got {accepted['principal_cents']}"
        )
        assert accepted["funding_status"] == "PENDING", (
            f"a booked tranche starts in PENDING, got {accepted['funding_status']}"
        )
        assert accepted["maturity_date"] == "2026-09-30", (
            "the accepted tranche matures on the neighbour's own date, "
            f"got {accepted['maturity_date']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 10_000_000_000, (
            "a PENDING tranche enters no wholesale bucket, so the brokered bucket "
            f"still holds the ACTIVE neighbour alone; got "
            f"{institution['brokered_deposits_cents']}"
        )


def _setup_de_novo_bank() -> dict:
    """A freshly registered bank with a zero core baseline and no programs,
    placements or board limits at all.  `total_liabilities_cents` is 1 because the
    PRD requires it to be strictly greater than zero (§3.1)."""
    return fx.setup_bank(
        publish_benchmark=False,
        institution_overrides={
            "legal_name": "De Novo Bank NA",
            "core_deposits_cents": 0,
            "total_liabilities_cents": 1,
            "tier1_capital_cents": 0,
            "liquidity_buffer_cents": 0,
        },
    )


class TestAverageDailyRatioEmptySetAndZeroDenominator:
    """With an empty placement book and a zero deposit base every ratio is zero
    rather than an error, and the headroom answer is the unbounded sentinel."""

    def test_point_in_time_summary_of_an_empty_book_is_all_zero(self):
        """PRD §2.4: "Any division whose denominator is zero yields zero rather
        than an error. This matters in practice for a newly registered bank whose
        `total_deposits_cents` is zero and for an exception filing that declares no
        transaction counts."

        PRD §3.7: "If there is no `ACTIVE` limit on that metric, the answer is
        unbounded and reported as -1."

        PRD §3.7: "`basis` defaults to `POINT_IN_TIME`, under which the
        average-daily figures are all reported as 0."

        Design: Difficulty/boundary_precision_check/average_daily_ratio_empty_set_and_zero_denominator
        """
        env = _setup_de_novo_bank()
        institution_id = env["institution"]["id"]

        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution_id, TREASURY)
        )
        assert summary["wholesale_funding_ratio_bps"] == 0, (
            "total_deposits_cents is zero, so the point-in-time ratio is 0 and not "
            f"an error; got {summary['wholesale_funding_ratio_bps']}"
        )
        assert summary["brokered_headroom_cents"] == -1, (
            "no ACTIVE BROKERED_TO_TOTAL_DEPOSITS limit exists, so the headroom is "
            f"unbounded and reported as -1; got {summary['brokered_headroom_cents']}"
        )
        assert summary["avg_wholesale_cents"] == 0, (
            "under the default POINT_IN_TIME basis the average-daily figures are "
            f"all reported as 0; got {summary['avg_wholesale_cents']}"
        )
        assert summary["average_daily_ratio_bps"] == 0, (
            "under the default POINT_IN_TIME basis the average-daily figures are "
            f"all reported as 0; got {summary['average_daily_ratio_bps']}"
        )

        institution = fx.read_institution(institution_id)
        asserts.assert_institution(institution)
        assert institution["total_deposits_cents"] == 0, (
            "core_deposits_cents is 0 and no bucket has any money, so "
            f"total_deposits_cents is 0; got {institution['total_deposits_cents']}"
        )
        for field in (
            "brokered_deposits_cents",
            "listing_service_deposits_cents",
            "reciprocal_deposits_cents",
        ):
            assert institution[field] == 0, (
                f"a bank with no placements must report {field} as 0, "
                f"got {institution[field]}"
            )
        assert institution["single_broker_max_ratio_bps"] == 0, (
            "no counterparty has any exposure, so single_broker_max_ratio_bps is 0, "
            f"got {institution['single_broker_max_ratio_bps']}"
        )
        assert institution["breached_metric_count"] == 0, (
            "no ACTIVE limit exists, so no metric can be in breach, "
            f"got {institution['breached_metric_count']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            "with nothing in breach and nothing in warning the posture is OPEN, "
            f"got {institution['concentration_posture']}"
        )
        assert institution["rate_cap_regime"] == "EXEMPT", (
            "a WELL_CAPITALIZED bank is EXEMPT from the ceiling, "
            f"got {institution['rate_cap_regime']}"
        )

    def test_single_day_average_daily_period_counts_both_endpoints(self):
        """PRD §3.7: "Its `day_count` is the number of whole days between
        `period_start` and `period_end` plus one, so both endpoints are inclusive."

        PRD §3.7: "The daily sum adds, for every day in the period, the
        `principal_cents` of each occupying placement; `avg_wholesale_cents` is
        that total divided by `day_count`, discarding the remainder; and
        `average_daily_ratio_bps` is `avg_wholesale_cents` multiplied by 10000 and
        divided by `total_deposits_cents`, again discarding the remainder, and 0
        when `total_deposits_cents` is zero."

        Design: Difficulty/boundary_precision_check/average_daily_ratio_empty_set_and_zero_denominator
        """
        env = _setup_de_novo_bank()

        summary = validate_success(
            api_client.get_wholesale_funding_summary(
                env["institution"]["id"],
                TREASURY,
                params={
                    "basis": "AVERAGE_DAILY",
                    "period_start": "2026-08-01",
                    "period_end": "2026-08-01",
                },
            )
        )
        assert summary["day_count"] == 1, (
            "period_start equals period_end and both endpoints are inclusive, so "
            f"day_count is 1; got {summary['day_count']}"
        )
        assert summary["avg_wholesale_cents"] == 0, (
            "no placement has ever been funded, so the daily sum is 0 and the "
            f"average is 0; got {summary['avg_wholesale_cents']}"
        )
        assert summary["average_daily_ratio_bps"] == 0, (
            "total_deposits_cents is zero, so the average-daily ratio is 0 rather "
            f"than an error; got {summary['average_daily_ratio_bps']}"
        )
        assert summary["brokered_headroom_cents"] == -1, (
            "the headroom answer is unbounded under either basis while no ACTIVE "
            f"limit exists; got {summary['brokered_headroom_cents']}"
        )
