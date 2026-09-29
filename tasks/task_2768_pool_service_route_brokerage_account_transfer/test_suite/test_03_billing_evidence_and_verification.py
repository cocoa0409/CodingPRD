"""Billing evidence, the trailing verification window and exclusion barriers (PRD §3.3, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_ratio_4dp,
)

BROKER = TEST_USERS["broker_headers"]


class TestBillingRecordLedgerShape:
    def test_a_billing_row_is_an_immutable_ledger_entry_with_derived_money(self, api):
        """The one append-only entity that carries computed money exposes `id` and `created_at`
        and nothing else of the lifecycle triple, and its three derived columns are the
        PASS_THROUGH split: the billed chemical never enters the recurring figure.

        PRD §2.4: "A `BillingHistoryRecord` and an `AttritionEvent` each carry only `id` and
        `created_at`: **both `updated_at` and `version` are absent from these two resource
        types**, they are never modified after insertion, and no endpoint exists to amend them."
        PRD §3.3: "`recurring_collected_cents` is the month's recurring invoice —
        `billed_service_cents`, plus `billed_chemical_cents` only when the owning account's
        `chemical_billing_method` is `INCLUDED` — multiplied by that month's `collection_rate`
        and rounded half up to whole cents."

        Design: Corner/entities/billing_history_record_is_immutable_no_version_field
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])
        account = fx.add_account(api, listing["id"], **fx.CANONICAL_A2)
        assert_cents(account["claimed_recurring_mrr_cents"], 15000, "A2 claimed recurring")

        row = validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(
                    account["id"], "2026-06", **fx.CANONICAL_A2_BILLING
                ),
                BROKER,
            ),
            201,
        )
        assert_ratio_4dp(row["collection_rate"], "0.9545", "collection rate")
        assert_cents(row["recurring_collected_cents"], 14318, "recurring collected")
        assert_cents(row["repair_collected_cents"], 1909, "repair collected")

        assert "id" in row and is_valid_uuid(row["id"])
        assert "created_at" in row and is_iso8601_timestamp(row["created_at"])
        assert "version" not in row
        assert "updated_at" not in row

        reread = validate_success(api.get_billing_history_record(row["id"], BROKER))
        assert reread == row

    def test_the_uniqueness_key_is_account_month_and_source_together(self, api):
        """The same month is legal twice as long as the source differs: an identical
        BANK_VERIFIED row is a 409 while a SELLER_UPLOAD row for that same month is a 201, and
        the money fields are no part of the key.

        PRD §3.3: "The combination of `account_id`, `period_month` and `source` must be unique: a
        `BANK_VERIFIED` trace and a `SELLER_UPLOAD` export for the same account and month coexist
        happily, but two `BANK_VERIFIED` rows for the same account and month do not, and the
        second answers `ERR_DUPLICATE_BILLING_PERIOD`."

        Design: Corner/validations/duplicate_account_month_source_billing_row_rejected
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])
        a1 = fx.add_account(api, listing["id"], **fx.CANONICAL_A1)
        a2 = fx.add_account(api, listing["id"], **fx.CANONICAL_A2)

        validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(a1["id"], "2026-06", **fx.CANONICAL_A1_BILLING),
                BROKER,
            ),
            201,
        )

        validate_error(
            api.create_billing_history_record(
                f.billing_history_record_payload(a1["id"], "2026-06", **fx.CANONICAL_A1_BILLING),
                BROKER,
            ),
            ApiErrorId.ERR_DUPLICATE_BILLING_PERIOD,
            409,
        )
        validate_error(
            api.create_billing_history_record(
                f.billing_history_record_payload(
                    a1["id"], "2026-06", billed_service_cents=12000,
                    billed_chemical_cents=4000, billed_repair_cents=1500, collected_cents=17000,
                ),
                BROKER,
            ),
            ApiErrorId.ERR_DUPLICATE_BILLING_PERIOD,
            409,
        )

        validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(
                    a1["id"], "2026-06", source="SELLER_UPLOAD", **fx.CANONICAL_A1_BILLING
                ),
                BROKER,
            ),
            201,
        )

        other_account = validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(a2["id"], "2026-06", **fx.CANONICAL_A2_BILLING),
                BROKER,
            ),
            201,
        )
        assert_ratio_4dp(other_account["collection_rate"], "0.9545", "collection rate")

        rows, meta = validate_paginated(
            api.list_billing_history_records(
                BROKER, params={"account_id": a1["id"], "period_month": "2026-06"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["source"] for row in rows} == {"BANK_VERIFIED", "SELLER_UPLOAD"}

    def test_a_month_is_filable_only_once_the_clock_has_left_it(self, api):
        """The gate is on month labels, not dates: the clock's own month is refused even on its
        last instant, and 2026-08 becomes filable the moment the clock reaches September.

        PRD §3.3: "A record may not be filed for a month that has not finished — `period_month`
        must be strictly earlier than the logical clock's own month, so the current month is
        refused with `ERR_TEMPORAL_WINDOW_VIOLATION` while the month immediately preceding it is
        accepted."

        Design: Corner/validations/billing_month_not_strictly_before_the_clock_month_rejected
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])
        a1 = fx.add_account(api, listing["id"], **fx.CANONICAL_A1)

        def row(period_month):
            return f.billing_history_record_payload(
                a1["id"], period_month, **fx.CANONICAL_A1_BILLING
            )

        validate_error(
            api.create_billing_history_record(row("2026-08"), BROKER),
            ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION,
            422,
        )
        validate_error(
            api.create_billing_history_record(row("2026-09"), BROKER),
            ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION,
            422,
        )
        validate_success(api.create_billing_history_record(row("2026-07"), BROKER), 201)

        fx.set_clock(api, "2026-08-31T23:59:59Z")
        validate_error(
            api.create_billing_history_record(row("2026-08"), BROKER),
            ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION,
            422,
        )

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        validate_success(api.create_billing_history_record(row("2026-08"), BROKER), 201)


class TestVerificationEvidenceWindow:
    def test_only_in_window_bank_verified_months_count_towards_the_three(self, api):
        """An account holding four rows — two in-window bank traces, one in-window seller export
        and one bank trace from before the window — still covers only two of the three required
        months, and verification is refused until the third trace lands.

        PRD §3.3: "The evidence window is the three most recent *complete* calendar months,
        meaning the three month labels immediately preceding the logical clock's own month, taken
        in ascending order. With the clock reading `2026-08-01T00:00:00Z`, the window is May, June
        and July of 2026."
        PRD §3.3: "If the window is not covered by three distinct months of bank-verified
        evidence, verification is refused with `ERR_INSUFFICIENT_BILLING_HISTORY` and nothing is
        written."

        Design: Corner/validations/verify_without_three_in_window_bank_verified_months_violation_to_error
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"], listed_account_count=1)
        a1 = fx.add_account(api, listing["id"], **fx.CANONICAL_A1)

        fx.add_billing_months(api, a1["id"], months=("2026-05", "2026-06"),
                              **fx.CANONICAL_A1_BILLING)
        fx.add_billing_months(api, a1["id"], months=("2026-07",), source="SELLER_UPLOAD",
                              **fx.CANONICAL_A1_BILLING)
        fx.add_billing_months(api, a1["id"], months=("2026-04",), **fx.CANONICAL_A1_BILLING)

        validate_error(
            api.verify_service_account(a1["id"], BROKER),
            ApiErrorId.ERR_INSUFFICIENT_BILLING_HISTORY,
            422,
        )

        refused = validate_success(api.get_service_account(a1["id"], BROKER))
        assert refused["verification_status"] == "UNVERIFIED"
        assert refused["verified_recurring_mrr_cents"] is None

        validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(a1["id"], "2026-07", **fx.CANONICAL_A1_BILLING),
                BROKER,
            ),
            201,
        )

        verified = validate_success(api.verify_service_account(a1["id"], BROKER))
        assert verified["verification_status"] == "VERIFIED"
        assert_cents(verified["verified_recurring_mrr_cents"], 16000, "verified recurring")
        assert_cents(verified["verified_repair_mrr_cents"], 1500, "verified repair")
        assert_ratio_4dp(verified["verification_variance"], "0.0000", "verification variance")

        parent = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(parent["verified_recurring_mrr_cents"], 16000, "listing verified recurring")
        assert parent["verified_account_count"] == 1
        assert parent["verification_posture"] == "COMPLETE"


class TestExclusionBarrierAndItsInverse:
    def test_an_excluded_stop_takes_no_further_evidence_and_reinstating_restores_it_exactly(
        self, api
    ):
        """Exclusion is a write barrier as well as a roll-up change: verification and a fresh
        billing row are both refused while the stop is out, reinstating puts back exactly the
        12000 it removed, and the same verification then runs and lands on DISPUTED.

        PRD §3.3: "Verification is also refused outright on a stop that has been excluded, with
        `ERR_ACCOUNT_EXCLUDED`."
        PRD §3.3: "And an account already dropped from the list accepts no new evidence,
        answering `ERR_ACCOUNT_EXCLUDED`."
        PRD §3.6: "The `exclusion_reason_code` is cleared to null, and so are
        `verified_recurring_mrr_cents`, `verified_repair_mrr_cents` and `verification_variance`".
        PRD §2.10: "Excluding an account removes exactly that account's contribution and
        reinstating it restores exactly the same contribution".

        Design: Corner/validations/excluded_account_refuses_verification_and_billing_writes
        """
        ctx = fx.route_with_billing_history(api)
        a3_id = ctx.a3["id"]
        fx.exclude_account(api, a3_id)

        validate_error(
            api.verify_service_account(a3_id, BROKER), ApiErrorId.ERR_ACCOUNT_EXCLUDED, 409
        )
        validate_error(
            api.create_billing_history_record(
                f.billing_history_record_payload(a3_id, "2026-04", **fx.CANONICAL_A3_BILLING),
                BROKER,
            ),
            ApiErrorId.ERR_ACCOUNT_EXCLUDED,
            409,
        )

        while_excluded = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert_cents(while_excluded["claimed_recurring_mrr_cents"], 31000, "claimed recurring")
        assert_cents(while_excluded["claimed_repair_mrr_cents"], 3500, "claimed repair")
        assert while_excluded["claimed_account_count"] == 2

        reinstated = validate_success(api.reinstate_service_account(a3_id, BROKER))
        assert reinstated["verification_status"] == "UNVERIFIED"
        assert reinstated["exclusion_reason_code"] is None
        assert reinstated["verified_recurring_mrr_cents"] is None
        assert reinstated["verification_variance"] is None

        restored = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert_cents(restored["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(restored["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert restored["claimed_account_count"] == 3

        disputed = validate_success(api.verify_service_account(a3_id, BROKER))
        assert disputed["verification_status"] == "DISPUTED"
        assert_cents(disputed["verified_recurring_mrr_cents"], 10000, "verified recurring")
        assert_ratio_4dp(disputed["verification_variance"], "0.1667", "verification variance")

    def test_exclude_and_reinstate_each_refuse_the_side_they_already_sit_on(self, api):
        """The two operations have disjoint source sets, so reinstating a live stop and excluding
        an already-excluded one are both invalid account transitions — and the round trip is
        loss-free on the claimed roll-up.

        PRD §3.6: "A stop may be excluded from `UNVERIFIED`, `VERIFIED` or `DISPUTED`; from any
        other value the answer is `ERR_INVALID_ACCOUNT_TRANSITION`."
        PRD §3.6: "Reinstating a stop moves it from `EXCLUDED` back to `UNVERIFIED`".
        PRD §3.6: "an exclude followed immediately by a reinstate returns the listing's claimed
        roll-up to precisely the cents it held before".

        Design: Corner/errors/reinstating_a_live_account_and_double_excluding_rejected
        """
        ctx = fx.draft_route_with_three_stops(api)
        a1_id = ctx.a1["id"]
        assert ctx.a1["verification_status"] == "UNVERIFIED"

        validate_error(
            api.reinstate_service_account(a1_id, BROKER),
            ApiErrorId.ERR_INVALID_ACCOUNT_TRANSITION,
            409,
        )

        excluded = validate_success(
            api.exclude_service_account(a1_id, f.exclude_account_payload(), BROKER)
        )
        assert excluded["verification_status"] == "EXCLUDED"
        assert excluded["exclusion_reason_code"] == "DISPUTED_HISTORY"

        validate_error(
            api.exclude_service_account(a1_id, f.exclude_account_payload(), BROKER),
            ApiErrorId.ERR_INVALID_ACCOUNT_TRANSITION,
            409,
        )

        reinstated = validate_success(api.reinstate_service_account(a1_id, BROKER))
        assert reinstated["verification_status"] == "UNVERIFIED"
        assert reinstated["exclusion_reason_code"] is None

        validate_error(
            api.reinstate_service_account(a1_id, BROKER),
            ApiErrorId.ERR_INVALID_ACCOUNT_TRANSITION,
            409,
        )

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert_cents(listing["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(listing["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert listing["claimed_account_count"] == 3


MIXED_MONTHS = (
    {"billed_service_cents": 10000, "billed_chemical_cents": 3000,
     "billed_repair_cents": 2000, "collected_cents": 13500},
    {"billed_service_cents": 10000, "billed_chemical_cents": 1000,
     "billed_repair_cents": 5000, "collected_cents": 14400},
    {"billed_service_cents": 10000, "billed_chemical_cents": 5000,
     "billed_repair_cents": 1000, "collected_cents": 12800},
)


class TestTheRoundingHappensPerMonthBeforeAnyAveraging:
    def test_the_pinned_order_lands_on_11200_where_a_blended_rate_would_say_11258(self, api):
        """Three months with deliberately different mixes and rates make the two orderings disagree:
        rounding each month at its own rate and averaging afterwards gives 11200, while summing the
        billed amounts, averaging them and applying one blended rate of 0.8660 gives 11258. The pinned
        order also decides the outcome's paperwork — the stop is disputed and still carries its numbers.

        PRD §3.3: "**The rounding happens per month, before any averaging.**"
        PRD §3.3: "**Only then** are the three already-rounded monthly figures averaged:
        `verified_recurring_mrr_cents` is the sum of the three monthly recurring figures divided by
        three and rounded half up to a whole cent, and `verified_repair_mrr_cents` is the sum of the
        three monthly repair figures divided by three and rounded half up to a whole cent. Summing raw
        billed amounts first, averaging them, and applying a single blended collection rate at the end
        is explicitly *not* how this works."
        PRD §3.3: "the absolute difference between `verified_recurring_mrr_cents` and the account's
        `claimed_recurring_mrr_cents`, divided by `claimed_recurring_mrr_cents`, to four decimal places
        rounded half up."

        Design: Difficulty/combinatorial_formula/verification_rounds_each_month_before_averaging
        """
        ctx = fx.month_varying_route(api, MIXED_MONTHS)
        assert_cents(ctx.account["claimed_recurring_mrr_cents"], 13000, "claimed recurring")

        verified = fx.verify_account(api, ctx.account["id"])
        assert_cents(verified["verified_recurring_mrr_cents"], 11200, "verified recurring")
        assert verified["verified_recurring_mrr_cents"] != 11258
        assert_cents(verified["verified_repair_mrr_cents"], 2367, "verified repair")
        assert_ratio_4dp(verified["verification_variance"], "0.1385", "verification variance")
        assert verified["verification_status"] == "DISPUTED"

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert_cents(listing["verified_recurring_mrr_cents"], 0, "listing verified recurring")
        assert listing["verified_account_count"] == 0
        assert listing["verification_posture"] == "INCOMPLETE"

    def test_the_monthly_columns_the_average_reads_are_the_frozen_ones_on_the_rows(self, api):
        """The same three months on a pass-through stop, where the recurring invoice is the service fee
        alone: each immutable row already carries the rate and the rounded cents the average will read,
        their mean is 8667, and the blended alternative would have said 8660 — a seven-cent gap that
        exists only because the rounding is per month.

        PRD §3.3: "`recurring_collected_cents` is the month's recurring invoice —
        `billed_service_cents`, plus `billed_chemical_cents` only when the owning account's
        `chemical_billing_method` is `INCLUDED` — multiplied by that month's `collection_rate` and
        rounded half up to whole cents. `repair_collected_cents` is `billed_repair_cents` multiplied by
        the same rate, again rounded half up to whole cents."
        PRD §3.3: "Each record derives three columns at write time, and because these rows are
        immutable they are never recomputed afterwards. `collection_rate` is `collected_cents` divided
        by the total of the three billed amounts, taken to four decimal places rounded half up"
        PRD §3.3: "each month's recurring collected cents is that month's recurring invoice — service
        plus chemical when the account folds chemicals in, service alone when it passes them through —
        multiplied by that month's own rate and rounded half up to a whole cent"

        Design: Difficulty/combinatorial_formula/verification_rounds_each_month_before_averaging
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(
            api, seller["id"], region_code="ROUND-PASS", listed_mrr_cents=10000,
            listed_account_count=1, asking_price_cents=100000,
        )
        account = fx.add_account(
            api, listing["id"], customer_ref="ROUND-PASS-S1", monthly_service_fee_cents=10000,
            avg_monthly_chemical_cents=3000, avg_monthly_repair_cents=2000,
            chemical_billing_method="PASS_THROUGH",
        )
        assert_cents(account["claimed_recurring_mrr_cents"], 10000, "claimed recurring")

        rows = []
        for month, amounts in zip(("2026-05", "2026-06", "2026-07"), MIXED_MONTHS):
            rows.append(
                validate_success(
                    api.create_billing_history_record(
                        f.billing_history_record_payload(account["id"], month, **amounts), BROKER
                    ),
                    201,
                )
            )

        expected_rates = ("0.9000", "0.9000", "0.8000")
        expected_recurring = (9000, 9000, 8000)
        expected_repair = (1800, 4500, 800)
        for row, rate, recurring, repair in zip(
            rows, expected_rates, expected_recurring, expected_repair
        ):
            assert_ratio_4dp(row["collection_rate"], rate, f"{row['period_month']} collection rate")
            assert_cents(
                row["recurring_collected_cents"], recurring,
                f"{row['period_month']} recurring collected",
            )
            assert_cents(
                row["repair_collected_cents"], repair, f"{row['period_month']} repair collected"
            )
        assert sum(row["recurring_collected_cents"] for row in rows) == 26000
        assert sum(row["repair_collected_cents"] for row in rows) == 7100

        verified = fx.verify_account(api, account["id"])
        assert_cents(verified["verified_recurring_mrr_cents"], 8667, "verified recurring")
        assert verified["verified_recurring_mrr_cents"] != 8660
        assert_cents(verified["verified_repair_mrr_cents"], 2367, "verified repair")
        assert_ratio_4dp(verified["verification_variance"], "0.1333", "verification variance")
        assert verified["verification_status"] == "DISPUTED"

        frozen, meta = validate_paginated(
            api.list_billing_history_records(BROKER, params={"account_id": account["id"]})
        )
        assert meta["total_count"] == 3
        for row in frozen:
            assert row["recurring_collected_cents"] in expected_recurring


class TestTheVarianceToleranceIsInclusiveToFourDecimals:
    def test_five_percent_exactly_verifies_and_the_next_step_out_disputes(self, api):
        """Two stops on one route claim the same 20000 and are read over the same three months; only
        the collected cash differs, by one hundred cents a month, and that moves the variance from
        exactly the tolerance to just past it — one stop joins the verified set and the other does not.

        PRD §3.3: "The outcome follows from the variance against a tolerance of five percent, and the
        comparison is inclusive: a variance of five percent to four decimal places passes. A stop whose
        variance is at or below the tolerance lands in `VERIFIED`; a stop whose variance is above it
        lands in `DISPUTED`."
        PRD §3.2: "`verified_recurring_mrr_cents` and `verified_repair_mrr_cents` are the sums of the
        corresponding per-account verified figures over the narrower set of stops that are actually
        `VERIFIED`, each account's figure already being a whole number of cents; `verified_account_count`
        counts that narrower set."
        PRD §3.2: "It is `INCOMPLETE` when at least one stop is `UNVERIFIED` or `DISPUTED`."

        Design: Difficulty/boundary_precision_check/verification_variance_tolerance_inclusive_boundary
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(
            api, seller["id"], region_code="BND-01", listed_mrr_cents=40000,
            listed_account_count=2, asking_price_cents=400000,
        )
        stops = {}
        for ref, collected in (("BND-ON", 19000), ("BND-OFF", 18900)):
            account = fx.add_account(
                api, listing["id"], customer_ref=ref, monthly_service_fee_cents=20000,
                avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0,
            )
            assert_cents(account["claimed_recurring_mrr_cents"], 20000, f"{ref} claimed recurring")
            fx.add_billing_months(
                api, account["id"], billed_service_cents=20000, billed_chemical_cents=0,
                billed_repair_cents=0, collected_cents=collected,
            )
            stops[ref] = fx.verify_account(api, account["id"])

        on_boundary = stops["BND-ON"]
        assert_cents(on_boundary["verified_recurring_mrr_cents"], 19000, "on-boundary verified")
        assert_ratio_4dp(on_boundary["verification_variance"], "0.0500", "on-boundary variance")
        assert on_boundary["verification_status"] == "VERIFIED"
        assert_cents(on_boundary["verified_repair_mrr_cents"], 0, "on-boundary verified repair")

        past_boundary = stops["BND-OFF"]
        assert_cents(past_boundary["verified_recurring_mrr_cents"], 18900, "past-boundary verified")
        assert_ratio_4dp(past_boundary["verification_variance"], "0.0550", "past-boundary variance")
        assert past_boundary["verification_status"] == "DISPUTED"
        assert_cents(past_boundary["verified_repair_mrr_cents"], 0, "past-boundary verified repair")

        rolled_up = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(rolled_up["verified_recurring_mrr_cents"], 19000, "listing verified recurring")
        assert rolled_up["verified_account_count"] == 1
        assert rolled_up["verification_posture"] == "INCOMPLETE"
        assert rolled_up["claimed_account_count"] == 2

    def test_one_stop_crosses_the_same_boundary_and_is_demoted_out_of_the_verified_set(self, api):
        """The stop verifies at exactly the tolerance, then the clock rolls the window forward onto a
        weaker month; the re-run averages 18967 instead of 19000, which is 0.0517 of the claim, and the
        demotion edge takes the stop and the listing's verified sums back out.

        PRD §3.3: "`VERIFIED → DISPUTED` is the demotion edge: a re-run over the current window that
        now yields a variance above the tolerance takes the stop back out of the verified set."
        PRD §3.3: "The evidence window is the three most recent *complete* calendar months, meaning
        the three month labels immediately preceding the logical clock's own month, taken in ascending
        order."
        PRD §3.3: "on the two that land in `DISPUTED` the listing's posture is recomputed to
        `INCOMPLETE`, and on the demotion edge the stop leaves the verified set so the listing's
        verified sums shrink accordingly."

        Design: Difficulty/boundary_precision_check/verification_variance_tolerance_inclusive_boundary
        """
        ctx = fx.collection_ratio_route(
            api, billed_service_cents=20000, collected_cents=19000, region_code="BND-WALK"
        )
        account_id = ctx.account["id"]

        first_pass = fx.verify_account(api, account_id)
        assert_cents(first_pass["verified_recurring_mrr_cents"], 19000, "verified recurring")
        assert_ratio_4dp(first_pass["verification_variance"], "0.0500", "verification variance")
        assert first_pass["verification_status"] == "VERIFIED"

        promoted = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert_cents(promoted["verified_recurring_mrr_cents"], 19000, "listing verified recurring")
        assert promoted["verified_account_count"] == 1

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        august = validate_success(
            api.create_billing_history_record(
                f.billing_history_record_payload(
                    account_id, "2026-08", billed_service_cents=20000, billed_chemical_cents=0,
                    billed_repair_cents=0, collected_cents=18900,
                ),
                BROKER,
            ),
            201,
        )
        assert_ratio_4dp(august["collection_rate"], "0.9450", "August collection rate")
        assert_cents(august["recurring_collected_cents"], 18900, "August recurring collected")

        demoted = fx.verify_account(api, account_id)
        assert_cents(demoted["verified_recurring_mrr_cents"], 18967, "verified recurring")
        assert_ratio_4dp(demoted["verification_variance"], "0.0517", "verification variance")
        assert demoted["verification_status"] == "DISPUTED"
        assert_cents(demoted["verified_repair_mrr_cents"], 0, "verified repair")

        shrunk = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert_cents(shrunk["verified_recurring_mrr_cents"], 0, "listing verified recurring")
        assert shrunk["verified_account_count"] == 0
        assert shrunk["verification_posture"] == "INCOMPLETE"
