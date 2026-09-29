"""Input-validation tests for the funding book.

Each test builds its own world from an empty database and then drives one
request that the PRD's own prose either admits or refuses, checking the single
`error_id` the PRD names for that condition and checking that a refused request
left no trace behind.
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
from test_helpers.test_users import ADMIN, DESK, TREASURY

# Balance baselines shared by the banks these tests register.
_BANK = {
    "core_deposits_cents": 30_000_000_000,
    "total_liabilities_cents": 45_000_000_000,
    "tier1_capital_cents": 4_000_000_000,
    "liquidity_buffer_cents": 900_000_000,
}


class TestUniquenessKeys:
    """PRD §3.1 unique certificate numbers and PRD §3.7 limit supersession."""

    def test_duplicate_cert_id_is_refused_while_a_repeated_metric_supersedes(self):
        """A platform operator registers an insured depository institution with its chartered `legal_name` and its deposit-insurance certificate number `cert_id`, which must be non-empty and unique across every bank on the platform — a collision is refused with `ERR_DUPLICATE_KEY`.

        The metric is deliberately not a uniqueness key. Creating a limit for a metric that already has an `ACTIVE` row supersedes that row: the prior limit moves to `status` of `RETIRED` with its `current_value_bps` reset to 0 and its `breach_state` reset to `WITHIN`, while the new row becomes the governing `ACTIVE` limit and is evaluated against current balances immediately.

        Design: Corner/validations/corner_duplicate_cert_id_rejected
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        institution = fx.register_institution(legal_name="Unique Bank NA",
                                              cert_id="CERT-9050", **_BANK)
        first_limit = fx.create_concentration_limit(
            institution["id"], TREASURY, metric="BROKERED_TO_TOTAL_DEPOSITS",
            warning_threshold_bps=1000, breach_threshold_bps=2000,
        )

        collision = api_client.create_institution(
            f.institution_payload(
                legal_name="Copycat Bank NA", cert_id="CERT-9050",
                core_deposits_cents=1_000_000_000,
                total_liabilities_cents=2_000_000_000,
                tier1_capital_cents=200_000_000,
                liquidity_buffer_cents=50_000_000,
            ),
            ADMIN,
        )
        validate_error(collision, ApiErrorId.ERR_DUPLICATE_KEY.value)

        banks, banks_meta = validate_paginated(api_client.list_institutions(ADMIN))
        assert banks_meta["total_count"] == 1, (
            "the refused registration must leave no second bank behind, got "
            f"total_count {banks_meta['total_count']}"
        )
        assert [row["cert_id"] for row in banks] == ["CERT-9050"], (
            f"only the original holder of CERT-9050 exists, got {[r['cert_id'] for r in banks]}"
        )

        second_limit = validate_success(
            api_client.create_concentration_limit(
                institution["id"],
                f.concentration_limit_payload(
                    metric="BROKERED_TO_TOTAL_DEPOSITS",
                    warning_threshold_bps=1500, breach_threshold_bps=2500,
                ),
                TREASURY,
            ),
            expected_status=201,
        )
        asserts.assert_concentration_limit(second_limit)
        assert second_limit["status"] == "ACTIVE", (
            "the new row becomes the governing ACTIVE limit, got "
            f"{second_limit['status']}"
        )
        assert second_limit["breach_threshold_bps"] == 2500, (
            f"the new thresholds govern, got {second_limit['breach_threshold_bps']}"
        )
        assert second_limit["breach_state"] == "WITHIN", (
            "with no brokered money the metric is 0 and so below both thresholds, got "
            f"{second_limit['breach_state']}"
        )

        limits, _ = validate_paginated(
            api_client.list_concentration_limits(institution["id"], TREASURY)
        )
        superseded = next(row for row in limits if row["id"] == first_limit["id"])
        assert superseded["status"] == "RETIRED", (
            f"the prior limit is retired rather than rejected, got {superseded['status']}"
        )
        assert superseded["current_value_bps"] == 0, (
            "a retired row keeps a current_value_bps of 0, got "
            f"{superseded['current_value_bps']}"
        )
        assert superseded["breach_state"] == "WITHIN", (
            f"a retired row keeps a breach_state of WITHIN, got {superseded['breach_state']}"
        )

        active, active_meta = validate_paginated(
            api_client.list_concentration_limits(
                institution["id"], TREASURY, params={"status": "ACTIVE"}
            )
        )
        assert active_meta["total_count"] == 1, (
            "exactly one row governs the metric at a time, got total_count "
            f"{active_meta['total_count']}"
        )
        assert active[0]["id"] == second_limit["id"], (
            f"the surviving ACTIVE row is the new one, got {active[0]['id']!r}"
        )


class TestMaturityWindowAggregate:
    """PRD §3.5 the ±15-day ladder window and its inclusive rejection bound."""

    def test_exposure_one_cent_below_the_inclusive_cap_is_admitted(self):
        """The exposure is the candidate's own `principal_cents` plus the `principal_cents` of every neighbour, and the cap is 3500 basis points — 35 percent — of the bank's `total_deposits_cents`, taking the integer part. The cap is an inclusive bound: an exposure that reaches the cap, not merely one that passes it, is refused with `ERR_MATURITY_WINDOW_CONCENTRATION`. This is a buffered aggregate rule rather than an exclusive-occupancy rule — each neighbour on its own is perfectly admissible, and only the aggregate breaches.

        Neighbours are the bank's other placements whose `funding_status` is `PENDING` or `ACTIVE`, whose effective class is `BROKERED` or `LISTING_SERVICE_NON_BROKERED`, and whose own `maturity_date` falls inside that window

        The placement also inherits `classified_as` from the class determined by the program's governing determination; that inherited value is what the concentration and balance rules read once the money is live.

        Design: Corner/validations/corner_maturity_window_exposure_one_cent_under_cap_passes
        """
        env = fx.setup_active_placement(
            institution_overrides={
                "legal_name": "Edge Bank NA",
                "core_deposits_cents": 10_000_000_000,
                "total_liabilities_cents": 20_000_000_000,
                "tier1_capital_cents": 2_000_000_000,
                "liquidity_buffer_cents": 500_000_000,
            },
            broker_overrides={"legal_name": "Edge Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
            program_overrides={"program_name": "Edge Brokered CD"},
            placement_overrides={"principal_cents": 1_000_000_000, "rate_bps": 470,
                                 "issue_date": "2026-08-01", "tenor_days": 60},
        )
        institution_id = env["institution"]["id"]
        neighbour = fx.read_placement(env["placement"]["id"])
        assert neighbour["maturity_date"] == "2026-09-30", (
            f"the neighbour matures 60 days after issue, got {neighbour['maturity_date']!r}"
        )
        assert fx.read_institution(institution_id)["total_deposits_cents"] == 11_000_000_000, (
            "10000000000 of core plus the 1000000000 ACTIVE brokered tranche gives the "
            "denominator the cap is taken from"
        )

        # cap == 11_000_000_000 * 3500 // 10000 == 3_850_000_000; the candidate takes
        # the exposure to 3_849_999_999, exactly one cent below the inclusive bound.
        candidate = validate_success(
            api_client.create_placement(
                f.placement_payload(
                    env["program"]["id"], principal_cents=2_849_999_999, rate_bps=470,
                    issue_date="2026-08-01", tenor_days=60,
                ),
                DESK,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_placement(candidate)
        assert candidate["funding_status"] == "PENDING", (
            f"a newly booked tranche lands in PENDING, got {candidate['funding_status']}"
        )
        assert candidate["maturity_date"] == "2026-09-30", (
            "the candidate shares the neighbour's maturity date and so sits inside the "
            f"window, got {candidate['maturity_date']!r}"
        )
        assert candidate["tenor_bucket"] == "DAYS_31_90", (
            f"a 60-day tranche falls in DAYS_31_90, got {candidate['tenor_bucket']}"
        )
        assert candidate["classified_as"] == "BROKERED", (
            "the tranche inherits the class of the programme's governing determination, "
            f"got {candidate['classified_as']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 1_000_000_000, (
            "a PENDING tranche is not yet on the balance sheet, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 11_000_000_000, (
            f"total_deposits_cents is unchanged by a booking, got {institution['total_deposits_cents']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            f"no limits are configured, so the posture stays OPEN, got {institution['concentration_posture']}"
        )


class TestAgreementBelongsToCounterparty:
    """PRD §3.4 the agreement must belong to the programme's own counterparty."""

    def test_borrowed_agreement_flips_the_identical_payload_from_created_to_refused(self):
        """Where `broker_id` is present, `agreement_id` is required and must name an agreement belonging to that same counterparty — an agreement borrowed from another counterparty, or an `agreement_id` supplied for a program with no counterparty at all, is refused with `ERR_AGREEMENT_BROKER_MISMATCH`.

        A new program lands in `PENDING_CLASSIFICATION` with `governing_classification_id` null, `outstanding_principal_cents` at 0, `prepared_by_user_id` stamped from the opening officer's identifier and `attested_by_user_id` null.

        Design: Corner/validations/corner_agreement_of_another_broker_rejected
        """
        env = fx.setup_bank(institution_overrides=dict(_BANK,
                                                       legal_name="Mismatch Bank NA"))
        institution_id = env["institution"]["id"]
        first = fx.setup_approved_agreement(
            broker_overrides={"legal_name": "Mismatch Brokers One LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
        )
        second = fx.setup_approved_agreement(
            broker_overrides={"legal_name": "Mismatch Brokers Two LLC",
                              "fee_flat_cents": 20_000},
            agreement_overrides={"fee_flat_cents": 20_000},
        )
        assert first["agreement"]["status"] == "APPROVED", (
            "the borrowed agreement is APPROVED, so a refusal cannot be about approval"
        )

        matched = validate_success(
            api_client.create_program(
                f.program_payload(
                    institution_id, broker_id=first["broker"]["id"],
                    agreement_id=first["agreement"]["id"],
                    program_name="Matched Program",
                    funding_channel_claim="BROKERED",
                ),
                DESK,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_program(matched)
        assert matched["state"] == "PENDING_CLASSIFICATION", (
            f"a new programme lands in PENDING_CLASSIFICATION, got {matched['state']}"
        )
        assert matched["agreement_id"] == first["agreement"]["id"], (
            "the programme keeps the agreement of its own counterparty, got "
            f"{matched['agreement_id']!r}"
        )
        assert matched["governing_classification_id"] is None, (
            f"no determination exists yet, got {matched['governing_classification_id']!r}"
        )

        borrowed = api_client.create_program(
            f.program_payload(
                institution_id, broker_id=second["broker"]["id"],
                agreement_id=first["agreement"]["id"],
                program_name="Borrowed Agreement Program",
                funding_channel_claim="BROKERED",
            ),
            DESK,
        )
        validate_error(borrowed, ApiErrorId.ERR_AGREEMENT_BROKER_MISMATCH.value)

        programs, meta = validate_paginated(
            api_client.list_programs(DESK, params={"institution_id": institution_id})
        )
        assert meta["total_count"] == 1, (
            "the refused request must leave no programme row behind, got total_count "
            f"{meta['total_count']}"
        )
        assert programs[0]["id"] == matched["id"], (
            f"the surviving programme is the matched one, got {programs[0]['id']!r}"
        )


class TestIssueDateLowerBounds:
    """PRD §3.5 a deposit may not be back-dated before its own paperwork."""

    def test_issue_date_before_the_agreement_effective_date_is_refused(self):
        """Deposits also cannot be back-dated before the paperwork that permits them: `issue_date` must fall on or after the underwriting agreement's `effective_date` and on or after the logical clock's date, and an earlier date is refused with `ERR_ISSUE_BEFORE_AGREEMENT`.

        From those inputs the system derives `maturity_date` as `issue_date` advanced by `tenor_days` calendar days

        Design: Corner/validations/corner_issue_date_before_agreement_effective_date_rejected
        """
        env = fx.setup_open_program(
            clock="2026-08-10T00:00:00Z",
            institution_overrides=dict(_BANK, legal_name="Backdate Bank NA"),
            broker_overrides={"legal_name": "Backdate Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000,
                                 "effective_date": "2026-08-15"},
            program_overrides={"program_name": "Backdate Brokered CD"},
        )
        program_id = env["program"]["id"]

        backdated = api_client.create_placement(
            f.placement_payload(program_id, principal_cents=1_000_000_000,
                                rate_bps=470, issue_date="2026-08-10", tenor_days=60),
            DESK,
        )
        validate_error(backdated, ApiErrorId.ERR_ISSUE_BEFORE_AGREEMENT.value)

        placements, meta = validate_paginated(
            api_client.list_placements(DESK, params={"program_id": program_id})
        )
        assert meta["total_count"] == 0, (
            "2026-08-10 is the clock's own date but still precedes the agreement's "
            f"effective_date, so no tranche may exist, got total_count {meta['total_count']}"
        )
        assert placements == [], (
            f"the refused booking must leave no row behind, got {placements}"
        )
        assert fx.read_institution(env["institution"]["id"])["brokered_deposits_cents"] == 0, (
            "no money moved on the refused booking"
        )

        fx.set_clock("2026-08-15T00:00:00Z")
        admitted = validate_success(
            api_client.create_placement(
                f.placement_payload(program_id, principal_cents=1_000_000_000,
                                    rate_bps=470, issue_date="2026-08-15",
                                    tenor_days=60),
                DESK,
            ),
            expected_status=201,
        )
        assert admitted["issue_date"] == "2026-08-15", (
            "an issue_date exactly equal to both lower bounds is admissible, got "
            f"{admitted['issue_date']!r}"
        )
        assert admitted["maturity_date"] == "2026-10-14", (
            "2026-08-15 advanced by 60 calendar days is 2026-10-14, got "
            f"{admitted['maturity_date']!r}"
        )
        assert admitted["tenor_bucket"] == "DAYS_31_90", (
            f"a 60-day tranche falls in DAYS_31_90, got {admitted['tenor_bucket']}"
        )


class TestForwardLookingConcentrationGate:
    """PRD §3.5 activation gate read against the PRD §3.7 posture arithmetic."""

    def test_only_the_aggregate_of_two_admissible_activations_trips_the_gate(self):
        """and, looking forward rather than backward, the value the matching concentration metric would take *after* this activation must stay strictly below that limit's `breach_threshold_bps`. That forward-looking gate is refused with `ERR_CONCENTRATION_BREACH`, and it is distinct from the frozen check — the frozen check refuses a bank that is already in breach, while this one refuses the single activation that would do the freezing.

        The brokered-to-deposits value is `brokered_deposits_cents` multiplied by 10000 and divided by `total_deposits_cents`, discarding the remainder.

        Each `ACTIVE` limit then takes that value into its own `current_value_bps` and sets `breach_state` to `BREACH` when the value is at or above its `breach_threshold_bps`, to `WARNING` when the value is at or above its `warning_threshold_bps` but below the breach level, and to `WITHIN` otherwise. Both comparisons are inclusive lower bounds, so a value exactly equal to `breach_threshold_bps` is a breach, not a warning.

        Design: Corner/validations/corner_aggregate_activation_breaches_limit_each_leg_admissible
        """
        env = fx.setup_bank(institution_overrides={
            "legal_name": "Aggregate Bank NA",
            "core_deposits_cents": 100_000_000_000,
            "total_liabilities_cents": 150_000_000_000,
            "tier1_capital_cents": 12_000_000_000,
            "liquidity_buffer_cents": 3_000_000_000,
        })
        institution_id = env["institution"]["id"]
        limit = fx.create_concentration_limit(
            institution_id, TREASURY, metric="BROKERED_TO_TOTAL_DEPOSITS",
            warning_threshold_bps=500, breach_threshold_bps=900,
        )
        env = fx.setup_brokered_program(
            env,
            broker_overrides={"legal_name": "Aggregate Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
            program_overrides={"program_name": "Aggregate Brokered CD"},
        )
        env = fx.setup_open_program(env)
        program_id = env["program"]["id"]

        first = fx.book_placement(program_id, DESK, principal_cents=5_000_000_000,
                                  rate_bps=470, issue_date="2026-08-01", tenor_days=60)
        second = fx.book_placement(program_id, DESK, principal_cents=5_000_000_000,
                                   rate_bps=470, issue_date="2026-08-01", tenor_days=61)
        fx.activate_placement(first["id"], DESK)

        def read_limit():
            rows, _ = validate_paginated(
                api_client.list_concentration_limits(institution_id, TREASURY)
            )
            return next(row for row in rows if row["id"] == limit["id"])

        # 5_000_000_000 * 10000 // 105_000_000_000 == 476
        after_first = read_limit()
        assert after_first["current_value_bps"] == 476, (
            "the first leg alone is 476 bps, the floor of 5000000000 * 10000 / "
            f"105000000000, got {after_first['current_value_bps']}"
        )
        assert after_first["breach_state"] == "WITHIN", (
            "476 sits below the 500 bps warning level, got "
            f"{after_first['breach_state']}"
        )
        assert fx.read_institution(institution_id)["concentration_posture"] == "OPEN", (
            "no ACTIVE limit is in warning or breach, so the bank stays OPEN — which "
            "is why the second refusal cannot be the frozen check"
        )

        refused = api_client.funding_action(
            second["id"], f.funding_action_payload("ACTIVATE"), DESK
        )
        validate_error(refused, ApiErrorId.ERR_CONCENTRATION_BREACH.value)

        # 10_000_000_000 * 10000 // 110_000_000_000 == 909, at or above the 900 bound.
        stuck = fx.read_placement(second["id"])
        assert stuck["funding_status"] == "PENDING", (
            "the refused activation leaves the tranche PENDING, got "
            f"{stuck['funding_status']}"
        )
        assert stuck["fee_accrual_cents"] == 0, (
            "a tranche that never entered ACTIVE accrues no fee, got "
            f"{stuck['fee_accrual_cents']}"
        )
        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 5_000_000_000, (
            "only the first leg is on the balance sheet, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 105_000_000_000, (
            f"total_deposits_cents is unchanged, got {institution['total_deposits_cents']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            "the refusal prevented the freeze rather than following it, got "
            f"{institution['concentration_posture']}"
        )
        assert read_limit()["current_value_bps"] == 476, (
            "the limit's own value is untouched by the refused activation, got "
            f"{read_limit()['current_value_bps']}"
        )


class TestPassThroughInsuranceCoherence:
    """PRD §3.4 pass-through coverage is only coherent with subaccount titling."""

    def test_the_same_titling_flips_from_admitted_to_refused_when_the_claim_is_made(self):
        """Pass-through coverage is only coherent with subaccount titling and a real counterparty, so claiming it requires `titling_convention` to be `FBO_SUBACCOUNTS` and `broker_id` to be non-null; a program titled `DIRECT_TITLED` or `SINGLE_FIDUCIARY_ACCOUNT`, or one with no counterparty, cannot claim it.

        Either violation is refused with `ERR_PASS_THROUGH_TITLING_INVALID`.

        Design: Corner/validations/corner_pass_through_claim_requires_fbo_subaccount_titling
        """
        env = fx.setup_bank(institution_overrides=dict(_BANK,
                                                       legal_name="PassThrough Bank NA"))
        institution_id = env["institution"]["id"]
        file = fx.setup_approved_agreement(
            broker_overrides={"legal_name": "PassThrough Brokers LLC",
                              "fee_flat_cents": 10_000},
            agreement_overrides={"fee_flat_cents": 10_000},
        )
        base = {
            "broker_id": file["broker"]["id"],
            "agreement_id": file["agreement"]["id"],
            "funding_channel_claim": "BROKERED",
        }

        dormant = validate_success(
            api_client.create_program(
                f.program_payload(institution_id, program_name="Direct Titled No Claim",
                                  titling_convention="DIRECT_TITLED",
                                  pass_through_insurance=False, **base),
                DESK,
            ),
            expected_status=201,
        )
        assert dormant["titling_convention"] == "DIRECT_TITLED", (
            "the rule is dormant while pass_through_insurance is false, got "
            f"{dormant['titling_convention']}"
        )
        assert dormant["pass_through_insurance"] is False, (
            f"no claim was made, got {dormant['pass_through_insurance']!r}"
        )

        claimed = api_client.create_program(
            f.program_payload(institution_id, program_name="Direct Titled With Claim",
                              titling_convention="DIRECT_TITLED",
                              pass_through_insurance=True, **base),
            DESK,
        )
        validate_error(claimed, ApiErrorId.ERR_PASS_THROUGH_TITLING_INVALID.value)

        coherent = validate_success(
            api_client.create_program(
                f.program_payload(institution_id, program_name="FBO Titled With Claim",
                                  titling_convention="FBO_SUBACCOUNTS",
                                  pass_through_insurance=True, **base),
                DESK,
            ),
            expected_status=201,
        )
        assert coherent["pass_through_insurance"] is True, (
            "FBO_SUBACCOUNTS titling with a named counterparty satisfies the "
            f"mechanics, got {coherent['pass_through_insurance']!r}"
        )
        assert coherent["titling_convention"] == "FBO_SUBACCOUNTS", (
            f"the coherent titling is recorded, got {coherent['titling_convention']}"
        )

        programs, meta = validate_paginated(
            api_client.list_programs(DESK, params={"institution_id": institution_id})
        )
        assert meta["total_count"] == 2, (
            "the refused request left no row, so only the two admitted programmes "
            f"exist, got total_count {meta['total_count']}"
        )
        assert {row["id"] for row in programs} == {dormant["id"], coherent["id"]}, (
            f"the surviving programmes are the two admitted ones, got {[r['id'] for r in programs]}"
        )


class TestExceptionInputCoherence:
    """PRD §3.3 the coherence gate runs before either ratio is computed."""

    def test_incoherent_inputs_are_refused_before_any_ratio_is_computed(self):
        """The declared basis must be supported by its own inputs: a twenty-five-percent filing requires `total_customer_assets_cents` strictly above zero with `deposits_placed_at_ifs_cents` no larger than it, and an enabling-transactions filing requires `total_transaction_count` strictly above zero with `enabling_transaction_count` no larger than it. A zero denominator or a numerator larger than its denominator is refused with `ERR_EXCEPTION_INPUTS_INCOHERENT`.

        `business_line_deposit_ratio_bps` is `deposits_placed_at_ifs_cents` multiplied by 10000 and then divided by `total_customer_assets_cents`, discarding any remainder.

        Under the twenty-five-percent basis, `test_outcome` is `QUALIFIED` only when `business_line_deposit_ratio_bps` is strictly below 2500 basis points, which is 25 percent — a ratio of exactly 2500 fails.

        the twenty-five-percent basis and the enabling-transactions basis are both `NOTICE` filings

        At creation the filing lands in `DRAFT` with `info_request_round_count` and `reliant_program_count` both at 0

        It is also stamped with `reporting_due_date`, a calendar date set to the logical clock's date plus 90 days.

        Design: Corner/validations/corner_exception_input_coherence_runs_before_the_ratio_test
        """
        fx.set_clock("2026-08-01T00:00:00Z")
        institution = fx.register_institution(legal_name="Coherence Bank NA", **_BANK)
        broker = fx.register_broker(legal_name="Coherence Brokers LLC",
                                   fee_flat_cents=10_000)

        zero_denominator = api_client.create_exception(
            f.exception_payload(broker["id"], institution["id"],
                                designated_business_line="zero denominator",
                                total_customer_assets_cents=0,
                                deposits_placed_at_ifs_cents=0),
            DESK,
        )
        validate_error(zero_denominator,
                       ApiErrorId.ERR_EXCEPTION_INPUTS_INCOHERENT.value)

        numerator_too_large = api_client.create_exception(
            f.exception_payload(broker["id"], institution["id"],
                                designated_business_line="over-100 percent ratio",
                                total_customer_assets_cents=1_000_000_000,
                                deposits_placed_at_ifs_cents=1_500_000_000),
            DESK,
        )
        validate_error(numerator_too_large,
                       ApiErrorId.ERR_EXCEPTION_INPUTS_INCOHERENT.value)

        enabling_count_too_large = api_client.create_exception(
            f.exception_payload(broker["id"], institution["id"],
                                exception_basis="ENABLING_TRANSACTIONS_TEST",
                                designated_business_line="count exceeds total",
                                total_transaction_count=100,
                                enabling_transaction_count=101),
            DESK,
        )
        validate_error(enabling_count_too_large,
                       ApiErrorId.ERR_EXCEPTION_INPUTS_INCOHERENT.value)

        filings, meta = validate_paginated(api_client.list_exceptions(DESK))
        assert meta["total_count"] == 0, (
            "none of the three incoherent filings may exist, got total_count "
            f"{meta['total_count']}"
        )
        assert filings == [], (
            f"the dependent ratio never ran, so no row was stamped, got {filings}"
        )

        coherent = validate_success(
            api_client.create_exception(
                f.exception_payload(broker["id"], institution["id"],
                                    designated_business_line="coherent inputs",
                                    total_customer_assets_cents=40_000_000_000,
                                    deposits_placed_at_ifs_cents=4_000_000_000),
                DESK,
            ),
            expected_status=201,
        )
        asserts.assert_primary_purpose_exception(coherent)
        assert coherent["status"] == "DRAFT", (
            f"a new filing lands in DRAFT, got {coherent['status']}"
        )
        # 4_000_000_000 * 10000 // 40_000_000_000 == 1000
        assert coherent["business_line_deposit_ratio_bps"] == 1000, (
            "the ratio is the floor of 4000000000 * 10000 / 40000000000, got "
            f"{coherent['business_line_deposit_ratio_bps']}"
        )
        assert coherent["test_outcome"] == "QUALIFIED", (
            "1000 bps is strictly below the 2500 bps ceiling, got "
            f"{coherent['test_outcome']}"
        )
        assert coherent["filing_type"] == "NOTICE", (
            "the twenty-five-percent basis derives a NOTICE filing, got "
            f"{coherent['filing_type']}"
        )
        assert coherent["reliant_program_count"] == 0, (
            f"no determination leans on it yet, got {coherent['reliant_program_count']}"
        )
        assert coherent["info_request_round_count"] == 0, (
            f"no review round has run, got {coherent['info_request_round_count']}"
        )
        assert coherent["reporting_due_date"] == "2026-10-30", (
            "the clock's date of 2026-08-01 plus 90 days is 2026-10-30, got "
            f"{coherent['reporting_due_date']!r}"
        )
