"""Valuation snapshots, the two bases and taking a route to market (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    as_decimal,
    assert_cents,
    assert_multiple_1dp,
    assert_route_valuation,
)

BROKER = TEST_USERS["broker_headers"]


class TestListedBasisMembership:
    def test_listed_basis_drops_only_excluded_stops_and_keeps_unverified_ones(self, api):
        """With A3 excluded and A2 left UNVERIFIED, the unverified stop still contributes its
        claimed 15000, so the fall from 463500 to 351500 is caused by the exclusion alone — and
        the shorter membership raises the weighted age enough to move the multiple to 11.0.

        PRD §3.4: "`LISTED_BASIS` is the market-facing number the route is advertised on: its
        input set is every stop of the listing whose verification dimension is anything other
        than `EXCLUDED`, each contributing its `claimed_recurring_mrr_cents` as its recurring
        figure and its `avg_monthly_repair_cents` as its repair figure."
        PRD §3.4: "`valuation_cents` is the sum of those two already-rounded components".
        PRD §3.4: "Creating a snapshot marks every earlier snapshot of the *same* listing and the
        *same* basis as superseded by setting its `is_superseded` to true".

        Design: Corner/calculations/listed_basis_valuation_filters_out_excluded_accounts_only
        """
        ctx = fx.draft_route_with_three_stops(api)
        first = fx.create_valuation(api, ctx.listing["id"], "LISTED_BASIS")
        assert_cents(first["valuation_cents"], 463500, "three-stop listed valuation")

        fx.exclude_account(api, ctx.a3["id"])

        snapshot = validate_success(
            api.create_route_valuation(
                ctx.listing["id"],
                f.route_valuation_payload(
                    "LISTED_BASIS", fx.listing_version(api, ctx.listing["id"])
                ),
                BROKER,
            ),
            201,
        )
        assert_route_valuation(snapshot)
        assert_cents(snapshot["recurring_mrr_cents"], 31000, "recurring base")
        assert snapshot["account_count"] == 2
        assert snapshot["weighted_avg_account_age_months"] == 63
        assert_multiple_1dp(snapshot["base_multiple"], "10.0", "base multiple")
        assert_multiple_1dp(snapshot["age_adjustment"], "1.0", "age adjustment")
        assert_multiple_1dp(snapshot["effective_multiple"], "11.0", "effective multiple")
        assert_cents(snapshot["recurring_component_cents"], 341000, "recurring component")
        assert_cents(snapshot["repair_component_cents"], 10500, "repair component")
        assert_cents(snapshot["valuation_cents"], 351500, "valuation")
        assert snapshot["basis"] == "LISTED_BASIS"
        assert snapshot["is_superseded"] is False

        audited = validate_success(api.get_route_valuation(first["id"], BROKER))
        assert_cents(audited["valuation_cents"], 463500, "retained valuation")
        assert audited["is_superseded"] is True

    def test_supersession_runs_down_the_basis_chain_not_across_the_listing(self, api):
        """A second verified-basis snapshot supersedes only the first verified one and leaves the
        listed-basis row alone, so the three filter combinations return one, two and three rows
        over the very same listing.

        PRD §3.4: "Creating a snapshot marks every earlier snapshot of the *same* listing and the
        *same* basis as superseded by setting its `is_superseded` to true".
        PRD §4: "List valuation snapshots, filterable by `listing_id`, `basis` and
        `is_superseded`."

        Design: Corner/endpoints/valuation_list_filters_by_basis_and_supersession_together
        """
        ctx = fx.verified_route_with_deal(api)
        listing_id = ctx.listing["id"]
        v_old = ctx.verified_valuation
        assert_cents(v_old["valuation_cents"], 343725, "first verified valuation")

        v_new = fx.create_valuation(api, listing_id, "VERIFIED_BASIS")
        assert_cents(v_new["valuation_cents"], 343725, "second verified valuation")

        live_verified, meta = validate_paginated(
            api.list_route_valuations(
                BROKER,
                params={"listing_id": listing_id, "basis": "VERIFIED_BASIS",
                        "is_superseded": "false"},
            )
        )
        assert meta["total_count"] == 1
        assert len(live_verified) == 1
        assert live_verified[0]["id"] == v_new["id"]
        assert_cents(live_verified[0]["valuation_cents"], 343725, "live verified valuation")

        both_verified, meta = validate_paginated(
            api.list_route_valuations(
                BROKER, params={"listing_id": listing_id, "basis": "VERIFIED_BASIS"}
            )
        )
        assert meta["total_count"] == 2
        for row in both_verified:
            assert_cents(row["valuation_cents"], 343725, "verified valuation")

        listed_rows, meta = validate_paginated(
            api.list_route_valuations(
                BROKER, params={"listing_id": listing_id, "basis": "LISTED_BASIS"}
            )
        )
        assert meta["total_count"] == 1
        assert_cents(listed_rows[0]["valuation_cents"], 463500, "listed valuation")
        assert listed_rows[0]["is_superseded"] is False

        superseded, meta = validate_paginated(
            api.list_route_valuations(
                BROKER, params={"listing_id": listing_id, "is_superseded": "true"}
            )
        )
        assert meta["total_count"] == 1
        assert superseded[0]["id"] == v_old["id"]

        everything, meta = validate_paginated(
            api.list_route_valuations(BROKER, params={"listing_id": listing_id})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

    def test_a_stale_listing_version_blocks_a_valuation_the_route_has_outgrown(self, api):
        """A version captured before a fourth stop joined would have valued a three-stop
        roll-up, so the write is refused with a concurrency error rather than a state error —
        and the identical body lands once the version is re-read, this time valuing 53000.

        PRD §2.8: "If it does not equal that listing's current `version`, the creation is
        rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412) and nothing is written".
        PRD §2.8: "Because an accepted valuation itself increments `RouteListing.version`, a
        client creating two valuations in succession must re-read the listing between them."

        Design: Corner/complexity_layers/stale_expected_listing_version_after_a_fourth_account_is_added
        """
        ctx = fx.draft_route_with_three_stops(api)
        listing_id = ctx.listing["id"]
        first = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        assert_cents(first["valuation_cents"], 463500, "three-stop listed valuation")
        stale_version = fx.listing_version(api, listing_id)

        fourth = fx.add_account(
            api, listing_id, customer_ref="A4-CHANDLER", service_start_date="2021-06-01",
            route_day="THU", monthly_service_fee_cents=8000, avg_monthly_chemical_cents=2000,
            avg_monthly_repair_cents=1000, chemical_billing_method="INCLUDED",
            billing_frequency="MONTHLY",
        )
        assert_cents(fourth["claimed_recurring_mrr_cents"], 10000, "A4 claimed recurring")
        assert fourth["account_age_months"] == 62

        validate_error(
            api.create_route_valuation(
                listing_id, f.route_valuation_payload("LISTED_BASIS", stale_version), BROKER
            ),
            ApiErrorId.ERR_STALE_LISTING_VERSION,
            412,
        )

        listing = validate_success(api.get_route_listing(listing_id, BROKER))
        assert listing["version"] == stale_version + 1
        assert_cents(listing["claimed_recurring_mrr_cents"], 53000, "claimed recurring")
        assert_cents(listing["claimed_repair_mrr_cents"], 5000, "claimed repair")
        assert listing["claimed_account_count"] == 4

        fresh = validate_success(
            api.create_route_valuation(
                listing_id,
                f.route_valuation_payload("LISTED_BASIS", listing["version"]),
                BROKER,
            ),
            201,
        )
        assert_cents(fresh["recurring_mrr_cents"], 53000, "recurring base")
        assert fresh["account_count"] == 4
        assert fresh["weighted_avg_account_age_months"] == 52
        assert_multiple_1dp(fresh["base_multiple"], "10.0", "base multiple")
        assert_multiple_1dp(fresh["age_adjustment"], "0.5", "age adjustment")
        assert_multiple_1dp(fresh["effective_multiple"], "10.5", "effective multiple")
        assert_cents(fresh["recurring_component_cents"], 556500, "recurring component")
        assert_cents(fresh["repair_component_cents"], 15000, "repair component")
        assert_cents(fresh["valuation_cents"], 571500, "valuation")

        rows, meta = validate_paginated(
            api.list_route_valuations(
                BROKER, params={"listing_id": listing_id, "basis": "LISTED_BASIS"}
            )
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first["id"]]["is_superseded"] is True
        assert by_id[fresh["id"]]["is_superseded"] is False


class TestPublication:
    def test_a_ready_draft_listing_publishes_and_bumps_its_version_once(self, api):
        """A DRAFT listing that already satisfies both readiness preconditions moves to LISTED
        with its version advanced by exactly one, and the transition itself touches none of the
        roll-ups.

        PRD §3.4: "**Publication** takes a `DRAFT` listing to market and moves its status to
        `LISTED`, incrementing the listing's `version` by one."
        PRD §3.4: "the listing must have `claimed_account_count` of at least one, and it must have
        at least one `LISTED_BASIS` valuation whose `is_superseded` is false."

        Design: Corner/state_machines/publish_listing_valid_transition_draft_to_listed
        """
        ctx = fx.route_with_billing_history(api)
        listing_id = ctx.listing["id"]
        valuation = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        assert_cents(valuation["valuation_cents"], 463500, "listed valuation")
        pre_publish_v = fx.listing_version(api, listing_id)

        published = validate_success(api.publish_route_listing(listing_id, BROKER))
        assert published["status"] == "LISTED"
        assert published["version"] == pre_publish_v + 1
        assert_cents(published["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(published["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert published["claimed_account_count"] == 3
        assert published["withdrawal_reason_code"] is None

        assert validate_success(api.get_route_listing(listing_id, BROKER))["status"] == "LISTED"

    def test_each_publication_precondition_refuses_on_its_own(self, api):
        """One listing has neither stops nor a valuation and the other has a stop but no
        listed-basis snapshot, so both are refused — and only once the snapshot exists does the
        second one publish, proving neither precondition subsumes the other.

        PRD §3.4: "A listing with an empty account list, and a listing whose only listed-basis
        snapshot has since been superseded by a newer one, both answer
        `ERR_LISTING_NOT_PUBLISHABLE`."
        PRD §3.2: "The same window in a different region is always permitted."

        Design: Corner/state_machines/publish_without_accounts_or_listed_valuation_precondition_enforced
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        fx.seed_buyer(api)
        pub_a = fx.seed_listing(api, seller["id"], region_code="PHX-A")
        pub_b = fx.seed_listing(api, seller["id"], region_code="PHX-B")
        fx.add_account(
            api, pub_b["id"], customer_ref="B1-ONLY", service_start_date="2019-03-15",
            route_day="MON", monthly_service_fee_cents=20000, avg_monthly_chemical_cents=0,
            avg_monthly_repair_cents=0, chemical_billing_method="INCLUDED",
            billing_frequency="MONTHLY",
        )

        validate_error(
            api.publish_route_listing(pub_a["id"], BROKER),
            ApiErrorId.ERR_LISTING_NOT_PUBLISHABLE,
            422,
        )
        validate_error(
            api.publish_route_listing(pub_b["id"], BROKER),
            ApiErrorId.ERR_LISTING_NOT_PUBLISHABLE,
            422,
        )

        valuation = validate_success(
            api.create_route_valuation(
                pub_b["id"],
                f.route_valuation_payload("LISTED_BASIS", fx.listing_version(api, pub_b["id"])),
                BROKER,
            ),
            201,
        )
        assert_cents(valuation["valuation_cents"], 200000, "single-stop valuation")

        published = validate_success(api.publish_route_listing(pub_b["id"], BROKER))
        assert published["status"] == "LISTED"

        assert validate_success(api.get_route_listing(pub_a["id"], BROKER))["status"] == "DRAFT"

    def test_publishing_an_already_listed_route_a_second_time_is_refused(self, api):
        """Publication is not idempotent: the second identical publish answers an invalid listing
        transition and does not advance the version a retried publish could otherwise inflate.

        PRD §3.4: "Publication is available from `DRAFT` only, so publishing an already-`LISTED`
        route, a `CLOSED` one or a `WITHDRAWN` one answers `ERR_INVALID_LISTING_TRANSITION`."

        Design: Corner/state_machines/publishing_an_already_listed_listing_is_rejected_not_idempotent
        """
        ctx = fx.listed_route(api)
        listing_id = ctx.listing["id"]
        listed_v = fx.listing_version(api, listing_id)

        validate_error(
            api.publish_route_listing(listing_id, BROKER),
            ApiErrorId.ERR_INVALID_LISTING_TRANSITION,
            409,
        )

        unchanged = validate_success(api.get_route_listing(listing_id, BROKER))
        assert unchanged["status"] == "LISTED"
        assert unchanged["version"] == listed_v

    def test_the_licensing_regime_is_looked_up_at_publication_not_before(self, api):
        """An AZ route is opened, stocked and valued happily while only the NV regime exists;
        publication is where the missing profile bites, and seeding it makes the very same call
        succeed.

        PRD §3.4: "First the licensing regime must exist: there must be a `StateLicenseProfile`
        whose `state_code` matches the listing's `state_code` ... and its absence is
        `ERR_STATE_PROFILE_MISSING`."

        Design: Corner/errors/publishing_a_listing_whose_state_has_no_license_profile_rejected
        """
        fx.seed_nv_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"], region_code="PHX-SE")
        fx.add_account(
            api, listing["id"], customer_ref="SE1-AHWATUKEE",
            service_start_date="2019-03-15", route_day="MON",
            monthly_service_fee_cents=18000, avg_monthly_chemical_cents=0,
            avg_monthly_repair_cents=0, chemical_billing_method="INCLUDED",
            billing_frequency="MONTHLY",
        )
        fx.create_valuation(api, listing["id"], "LISTED_BASIS")

        validate_error(
            api.publish_route_listing(listing["id"], BROKER),
            ApiErrorId.ERR_STATE_PROFILE_MISSING,
            422,
        )

        blocked = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert blocked["status"] == "DRAFT"
        assert_cents(blocked["claimed_recurring_mrr_cents"], 18000, "claimed recurring")

        validate_success(
            api.create_state_license_profile(
                f.state_license_profile_payload(), TEST_USERS["platform_admin_headers"]
            ),
            201,
        )

        published = validate_success(api.publish_route_listing(listing["id"], BROKER))
        assert published["status"] == "LISTED"


ADMIN = TEST_USERS["platform_admin_headers"]


def all_three_verified(api):
    """The canonical AZ route with every stop run through verification and nothing excluded."""
    ctx = fx.route_with_billing_history(api)
    for key in ("a1", "a2", "a3"):
        ctx[key] = fx.verify_account(api, ctx[key]["id"])
    assert ctx.a1["verification_status"] == "VERIFIED"
    assert ctx.a2["verification_status"] == "VERIFIED"
    assert ctx.a3["verification_status"] == "DISPUTED"
    return ctx


def one_stop_valuation(api, seller, region_code, service_cents, chemical_cents,
                       service_start_date):
    """A fresh DRAFT listing holding one INCLUDED stop, snapshotted on the listed basis."""
    listing = fx.seed_listing(
        api, seller["id"], region_code=region_code,
        listed_mrr_cents=service_cents + chemical_cents, listed_account_count=1,
        asking_price_cents=(service_cents + chemical_cents) * 10,
    )
    fx.add_account(
        api, listing["id"], customer_ref=f"{region_code}-S1",
        service_start_date=service_start_date, monthly_service_fee_cents=service_cents,
        avg_monthly_chemical_cents=chemical_cents, avg_monthly_repair_cents=0,
        chemical_billing_method="INCLUDED",
    )
    return fx.create_valuation(api, listing["id"], "LISTED_BASIS")


class TestTheTwoBasesAreGenuinelyDifferentAnswers:
    def test_membership_and_amounts_both_move_so_age_and_multiple_move_with_them(self, api):
        """One route, one clock, two snapshots: the listed basis counts all three stops at the seller's
        own claims, the verified basis counts the two that survived verification at the bank's figures,
        and because the dropped stop is the youngest one the weighted age climbs from 50 to 64 months
        and drags the multiple from 10.5 to 11.0 on top of the smaller base.

        PRD §3.4: "`LISTED_BASIS` ... its input set is every stop of the listing whose verification
        dimension is anything other than `EXCLUDED`, each contributing its
        `claimed_recurring_mrr_cents` as its recurring figure and its `avg_monthly_repair_cents` as its
        repair figure ... `VERIFIED_BASIS` ... its input set is only those stops that are `VERIFIED`,
        each contributing its `verified_recurring_mrr_cents` and its `verified_repair_mrr_cents`."
        PRD §3.4: "Because the two bases differ in both the membership filter and the per-account
        amounts, the same listing yields two different total values, and frequently two different tier
        multiples and two different weighted ages as well."
        PRD §3.4: "`valuation_cents` is the sum of those two already-rounded components — each
        component is rounded independently first, and only then are they added."

        Design: Difficulty/dual_variant_calc/route_valuation_listed_versus_verified_basis
        """
        ctx = all_three_verified(api)
        listing_id = ctx.listing["id"]

        listed = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        verified = fx.create_valuation(api, listing_id, "VERIFIED_BASIS")
        assert_route_valuation(listed)
        assert_route_valuation(verified)

        assert listed["basis"] == "LISTED_BASIS"
        assert listed["account_count"] == 3
        assert_cents(listed["recurring_mrr_cents"], 43000, "listed recurring")
        assert_cents(listed["repair_mrr_cents"], 4000, "listed repair")
        assert listed["weighted_avg_account_age_months"] == 50
        assert_multiple_1dp(listed["base_multiple"], "10.0", "listed base multiple")
        assert_multiple_1dp(listed["age_adjustment"], "0.5", "listed age adjustment")
        assert_multiple_1dp(listed["effective_multiple"], "10.5", "listed effective multiple")
        assert_cents(listed["recurring_component_cents"], 451500, "listed recurring component")
        assert_cents(listed["repair_component_cents"], 12000, "listed repair component")
        assert_cents(listed["valuation_cents"], 463500, "listed valuation")

        assert verified["basis"] == "VERIFIED_BASIS"
        assert verified["account_count"] == 2
        assert_cents(verified["recurring_mrr_cents"], 30318, "verified recurring")
        assert_cents(verified["repair_mrr_cents"], 3409, "verified repair")
        assert verified["weighted_avg_account_age_months"] == 64
        assert_multiple_1dp(verified["base_multiple"], "10.0", "verified base multiple")
        assert_multiple_1dp(verified["age_adjustment"], "1.0", "verified age adjustment")
        assert_multiple_1dp(verified["effective_multiple"], "11.0", "verified effective multiple")
        assert_cents(verified["recurring_component_cents"], 333498, "verified recurring component")
        assert_cents(verified["repair_component_cents"], 10227, "verified repair component")
        assert_cents(verified["valuation_cents"], 343725, "verified valuation")

        assert listed["valuation_cents"] - verified["valuation_cents"] == 119775

    def test_supersession_is_scoped_per_basis_so_neither_variant_retires_the_other(self, api):
        """Both snapshots are live at once on the same listing, and a fresh listed-basis snapshot
        retires only its own predecessor: the verified-basis row is untouched by it, which is what lets
        the market number and the diligence number coexist.

        PRD §3.4: "Creating a snapshot marks every earlier snapshot of the *same* listing and the
        *same* basis as superseded by setting its `is_superseded` to true, and increments the listing's
        `version` by one — which is precisely why the next snapshot must carry a re-read
        `expected_listing_version`."
        PRD §3.4: "Each snapshot records `computed_from_clock_utc`, the logical clock reading that
        supplied the account ages it used, and carries `is_superseded`, which is false at creation."

        Design: Difficulty/dual_variant_calc/route_valuation_listed_versus_verified_basis
        """
        ctx = all_three_verified(api)
        listing_id = ctx.listing["id"]

        first_listed = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        verified = fx.create_valuation(api, listing_id, "VERIFIED_BASIS")
        assert first_listed["is_superseded"] is False
        assert verified["is_superseded"] is False

        second_listed = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        assert_cents(second_listed["valuation_cents"], 463500, "re-taken listed valuation")
        assert second_listed["is_superseded"] is False

        retired = validate_success(api.get_route_valuation(first_listed["id"], BROKER))
        assert retired["is_superseded"] is True
        survivor = validate_success(api.get_route_valuation(verified["id"], BROKER))
        assert survivor["is_superseded"] is False
        assert_cents(survivor["valuation_cents"], 343725, "verified valuation")

        live, meta = validate_paginated(
            api.list_route_valuations(
                BROKER, params={"listing_id": listing_id, "is_superseded": "false"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["basis"] for row in live} == {"LISTED_BASIS", "VERIFIED_BASIS"}


class TestTheMultipleIsANestedClampOverTwoIndependentTerms:
    def test_one_cent_across_the_lower_tier_boundary_costs_a_whole_turn(self, api):
        """Two routes of identical age differ by a single cent of recurring revenue, and that cent sits
        exactly on the lower tier boundary: the tier is inclusive at its floor, so 30000 earns ten
        times and 29999 earns nine, a 30009-cent swing with the age adjustment held at zero.

        PRD §3.4: "In the integer cents this API speaks, the two tier boundaries are 30,000 cents and
        100,000 cents, the first tier applying strictly below the lower boundary, the second applying
        from the lower boundary up to strictly below the higher one, and the third from the higher
        boundary upward."
        PRD §3.4: "From twenty-four through thirty-five months, nothing is added or taken away."
        PRD §3.4: "`recurring_component_cents` is the snapshot's `recurring_mrr_cents` multiplied by
        `effective_multiple`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/valuation_multiple_nested_min_max_over_tier_and_age
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)

        on_boundary = one_stop_valuation(api, seller, "PHX-T1", 20000, 10000, "2024-01-15")
        one_cent_below = one_stop_valuation(api, seller, "PHX-T2", 20000, 9999, "2024-01-15")

        assert_cents(on_boundary["recurring_mrr_cents"], 30000, "boundary recurring")
        assert on_boundary["weighted_avg_account_age_months"] == 30
        assert_multiple_1dp(on_boundary["base_multiple"], "10.0", "boundary base multiple")
        assert_multiple_1dp(on_boundary["age_adjustment"], "0.0", "boundary age adjustment")
        assert_multiple_1dp(on_boundary["effective_multiple"], "10.0", "boundary multiple")
        assert_cents(on_boundary["valuation_cents"], 300000, "boundary valuation")
        assert_cents(on_boundary["repair_component_cents"], 0, "boundary repair component")

        assert_cents(one_cent_below["recurring_mrr_cents"], 29999, "sub-boundary recurring")
        assert one_cent_below["weighted_avg_account_age_months"] == 30
        assert_multiple_1dp(one_cent_below["base_multiple"], "9.0", "sub-boundary base multiple")
        assert_multiple_1dp(one_cent_below["age_adjustment"], "0.0", "sub-boundary adjustment")
        assert_multiple_1dp(one_cent_below["effective_multiple"], "9.0", "sub-boundary multiple")
        assert_cents(one_cent_below["valuation_cents"], 269991, "sub-boundary valuation")
        assert_cents(one_cent_below["repair_component_cents"], 0, "sub-boundary repair component")

        assert on_boundary["valuation_cents"] - one_cent_below["valuation_cents"] == 30009

    def test_the_youngest_age_band_cancels_the_top_tier_exactly(self, api):
        """A route in the highest tier with the youngest customer base lands on the same effective
        multiple as a mid-tier route of settled age: the two terms are derived independently and then
        added, so a full turn of tier premium is cancelled by a full turn of age penalty.

        PRD §3.4: "A route at one thousand dollars a month or more is valued at eleven times."
        PRD §3.4: "A weighted average age of twenty-three months or less subtracts one full turn."
        PRD §3.4: "`effective_multiple` is the base multiple plus the age adjustment, clamped into the
        band from a floor of six point zero to a cap of twelve point zero — that is, the greater of the
        floor and the adjusted multiple, then the lesser of that result and the cap — and expressed to
        one decimal place."

        Design: Difficulty/combinatorial_formula/valuation_multiple_nested_min_max_over_tier_and_age
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)

        mid_tier_mature = one_stop_valuation(api, seller, "PHX-T1", 20000, 10000, "2024-01-15")
        top_tier_young = one_stop_valuation(api, seller, "PHX-T3", 60000, 40000, "2025-02-10")

        assert_cents(top_tier_young["recurring_mrr_cents"], 100000, "top tier recurring")
        assert top_tier_young["weighted_avg_account_age_months"] == 17
        assert_multiple_1dp(top_tier_young["base_multiple"], "11.0", "top tier base multiple")
        assert_multiple_1dp(top_tier_young["age_adjustment"], "-1.0", "top tier age adjustment")
        assert_multiple_1dp(top_tier_young["effective_multiple"], "10.0", "top tier multiple")
        assert_cents(top_tier_young["valuation_cents"], 1000000, "top tier valuation")
        assert_cents(top_tier_young["repair_component_cents"], 0, "top tier repair component")

        assert_multiple_1dp(mid_tier_mature["base_multiple"], "10.0", "mid tier base multiple")
        assert_multiple_1dp(mid_tier_mature["age_adjustment"], "0.0", "mid tier age adjustment")
        assert_multiple_1dp(mid_tier_mature["effective_multiple"], "10.0", "mid tier multiple")
        assert as_decimal(top_tier_young["effective_multiple"]) == as_decimal(
            mid_tier_mature["effective_multiple"]
        )
        assert top_tier_young["valuation_cents"] > mid_tier_mature["valuation_cents"]


def suspension_pair(api):
    """Two AZ sellers, each with a valuation-ready DRAFT route, the first of them suspended.

    The single stop of each route carries three trailing bank-verified months whose
    collections match its claimed figure exactly, so the stop verifies with zero variance
    and BOTH valuation bases select a non-empty input set. Suspension is then the only
    rule either route breaks, which is what lets the suspension error surface rather than
    the earlier empty-input check of PRD §2.9.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.seed_az_profile(api)
    lapsed = fx.seed_seller(api)
    active = fx.seed_seller(
        api, legal_name="Cactus Clear Pools Inc", license_number="AZ-PA-2002"
    )
    pair = {}
    for key, seller, region in (("lapsed", lapsed, "SUS-SUN"), ("active", active, "SUS-CACTUS")):
        listing = fx.seed_listing(
            api, seller["id"], region_code=region, listed_mrr_cents=20000,
            listed_account_count=1, asking_price_cents=200000,
        )
        stop = fx.add_account(
            api, listing["id"], customer_ref=f"{region}-S1", monthly_service_fee_cents=20000,
            avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0,
        )
        fx.add_billing_months(
            api, stop["id"], billed_service_cents=20000, billed_chemical_cents=0,
            billed_repair_cents=0, collected_cents=20000,
        )
        verified_stop = fx.verify_account(api, stop["id"])
        assert verified_stop["verification_status"] == "VERIFIED"
        fx.create_valuation(api, listing["id"], "LISTED_BASIS")
        pair[key] = {"seller": seller, "listing": listing}
    suspended = fx.suspend_seller(api, lapsed["id"])
    assert suspended["status"] == "SUSPENDED"
    return pair


class TestAnEmptyInputSetIsRefusedNotValuedAtZero:
    def test_excluding_the_only_stop_empties_both_bases_and_a_reinstate_refills_them(self, api):
        """The route still exists, still has a stop row and is still `DRAFT`, but every basis now has
        nothing to sum, so both requests are refused rather than answered with zero; neither refusal
        writes a snapshot or moves the listing's version, and undoing the exclusion restores the exact
        listed figure.

        PRD §3.4: "An empty input set is refused with `ERR_NO_VALUATION_INPUTS` rather than valued at
        zero — a verified-basis request on a listing with no verified stops, and a listed-basis request
        on a listing whose every stop has been excluded, both land there."
        PRD §3.2: "It is `EMPTY` when no stop of the listing is `VERIFIED`."
        PRD §3.6: "Because the claimed figures are a pure sum over included stops and the stop's own
        `claimed_recurring_mrr_cents` is untouched by exclusion, an exclude followed immediately by a
        reinstate returns the listing's claimed roll-up to precisely the cents it held before"

        Design: Difficulty/boundary_precision_check/empty_valuation_input_set_is_not_zero_valued_rejected
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(
            api, seller["id"], region_code="EMPTY-01", listed_mrr_cents=20000,
            listed_account_count=1, asking_price_cents=200000,
        )
        listing_id = listing["id"]
        account = fx.add_account(
            api, listing_id, customer_ref="EMPTY-01-S1", monthly_service_fee_cents=20000,
            avg_monthly_chemical_cents=0, avg_monthly_repair_cents=0,
        )
        excluded = fx.exclude_account(api, account["id"])
        assert excluded["verification_status"] == "EXCLUDED"

        emptied = validate_success(api.get_route_listing(listing_id, BROKER))
        assert emptied["status"] == "DRAFT"
        assert_cents(emptied["claimed_recurring_mrr_cents"], 0, "claimed recurring")
        assert emptied["claimed_account_count"] == 0
        assert_cents(emptied["verified_recurring_mrr_cents"], 0, "verified recurring")
        assert emptied["verified_account_count"] == 0
        assert emptied["verification_posture"] == "EMPTY"
        version_before = emptied["version"]

        for basis in ("LISTED_BASIS", "VERIFIED_BASIS"):
            validate_error(
                api.create_route_valuation(
                    listing_id, f.route_valuation_payload(basis, version_before), BROKER
                ),
                ApiErrorId.ERR_NO_VALUATION_INPUTS,
                422,
            )

        rows, meta = validate_paginated(
            api.list_route_valuations(BROKER, params={"listing_id": listing_id})
        )
        assert meta["total_count"] == 0
        assert rows == []
        untouched = validate_success(api.get_route_listing(listing_id, BROKER))
        assert untouched["version"] == version_before

        reinstated = validate_success(api.reinstate_service_account(account["id"], BROKER))
        assert reinstated["verification_status"] == "UNVERIFIED"
        assert_cents(reinstated["claimed_recurring_mrr_cents"], 20000, "claimed recurring")

        refilled = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        assert refilled["account_count"] == 1
        assert_cents(refilled["recurring_mrr_cents"], 20000, "listed recurring")
        assert refilled["weighted_avg_account_age_months"] == 88
        assert_multiple_1dp(refilled["effective_multiple"], "10.0", "effective multiple")
        assert_cents(refilled["valuation_cents"], 200000, "listed valuation")

    def test_the_verified_basis_alone_is_empty_while_the_listed_basis_values_the_same_route(self, api):
        """Three fully-billed stops make the listed basis worth 463500, yet the verified basis has no
        members at all and is refused; verifying a single stop is enough to make the very same request
        succeed, so it was emptiness and not the route that caused the refusal.

        PRD §3.4: "`VERIFIED_BASIS` is the diligence number that gates closing and later prices the
        clawback: its input set is only those stops that are `VERIFIED`, each contributing its
        `verified_recurring_mrr_cents` and its `verified_repair_mrr_cents`."
        PRD §3.4: "An empty input set is refused with `ERR_NO_VALUATION_INPUTS` rather than valued at
        zero — a verified-basis request on a listing with no verified stops ... land there."
        PRD §3.4: "`repair_component_cents` is the snapshot's `repair_mrr_cents` multiplied by a flat
        repair multiple of three point zero, rounded half up to whole cents"

        Design: Difficulty/boundary_precision_check/empty_valuation_input_set_is_not_zero_valued_rejected
        """
        ctx = fx.route_with_billing_history(api)
        listing_id = ctx.listing["id"]

        before = validate_success(api.get_route_listing(listing_id, BROKER))
        assert before["verification_posture"] == "EMPTY"
        assert before["claimed_account_count"] == 3

        validate_error(
            api.create_route_valuation(
                listing_id,
                f.route_valuation_payload("VERIFIED_BASIS", before["version"]),
                BROKER,
            ),
            ApiErrorId.ERR_NO_VALUATION_INPUTS,
            422,
        )

        listed = fx.create_valuation(api, listing_id, "LISTED_BASIS")
        assert listed["account_count"] == 3
        assert_cents(listed["valuation_cents"], 463500, "listed valuation")

        fx.verify_account(api, ctx.a1["id"])
        verified = fx.create_valuation(api, listing_id, "VERIFIED_BASIS")
        assert verified["account_count"] == 1
        assert_cents(verified["recurring_mrr_cents"], 16000, "verified recurring")
        assert_cents(verified["repair_mrr_cents"], 1500, "verified repair")
        assert verified["weighted_avg_account_age_months"] == 88
        assert_multiple_1dp(verified["effective_multiple"], "10.0", "effective multiple")
        assert_cents(verified["recurring_component_cents"], 160000, "recurring component")
        assert_cents(verified["repair_component_cents"], 4500, "repair component")
        assert_cents(verified["valuation_cents"], 164500, "verified valuation")


class TestASuspendedSellerFreezesItsOwnRoutesOnly:
    def test_publication_is_refused_for_the_suspended_seller_and_granted_for_the_active_one(self, api):
        """Both routes are `DRAFT`, both have a live listed-basis snapshot and a stop to sell, and both
        sit under the same AZ regime with no exclusivity conflict; the only difference is the owner's
        status, and the refused route is left exactly as it was.

        PRD §3.4: "Next the seller must be `ACTIVE`, or the answer is `ERR_SELLER_SUSPENDED`."
        PRD §3.4: "Last comes readiness: the listing must have `claimed_account_count` of at least one,
        and it must have at least one `LISTED_BASIS` valuation whose `is_superseded` is false."
        PRD §3.4: "**Publication** takes a `DRAFT` listing to market and moves its status to `LISTED`,
        incrementing the listing's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_and_valuation_blocked_by_suspended_seller
        """
        pair = suspension_pair(api)
        frozen_id = pair["lapsed"]["listing"]["id"]
        version_before = fx.listing_version(api, frozen_id)

        validate_error(
            api.publish_route_listing(frozen_id, BROKER),
            ApiErrorId.ERR_SELLER_SUSPENDED,
            422,
        )

        still_draft = validate_success(api.get_route_listing(frozen_id, BROKER))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["version"] == version_before
        assert_cents(still_draft["claimed_recurring_mrr_cents"], 20000, "claimed recurring")
        assert still_draft["claimed_account_count"] == 1

        active_id = pair["active"]["listing"]["id"]
        active_version = fx.listing_version(api, active_id)
        published = validate_success(api.publish_route_listing(active_id, BROKER))
        assert published["status"] == "LISTED"
        assert published["version"] == active_version + 1

    def test_snapshotting_is_refused_for_the_suspended_seller_and_granted_for_the_active_one(self, api):
        """The suspension reaches a second endpoint on a second entity family: no snapshot may be taken
        on the frozen route even though it is still `DRAFT` and its stop is untouched, while the
        identical request against the active seller's route is accepted and valued.

        PRD §3.4: "they may not be taken at all while the listing's seller is suspended, which answers
        `ERR_SELLER_SUSPENDED`."
        PRD §3.1: "The platform operator may suspend a seller, which sets `status` to `SUSPENDED` and
        stores the supplied `suspension_reason_code`. Suspension is deliberately indirect in its
        consequences: nothing about the seller's listings changes, yet four listing-scoped operations
        stop working the moment the flag flips — publishing a listing, creating a valuation snapshot on
        it, accepting an offer on it, and recording a customer introduction under it."
        PRD §3.4: "A route billing less than three hundred dollars a month in recurring revenue is
        valued at nine times that monthly figure."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_and_valuation_blocked_by_suspended_seller
        """
        pair = suspension_pair(api)
        frozen_id = pair["lapsed"]["listing"]["id"]
        version_before = fx.listing_version(api, frozen_id)

        validate_error(
            api.create_route_valuation(
                frozen_id, f.route_valuation_payload("LISTED_BASIS", version_before), BROKER
            ),
            ApiErrorId.ERR_SELLER_SUSPENDED,
            422,
        )
        validate_error(
            api.create_route_valuation(
                frozen_id, f.route_valuation_payload("VERIFIED_BASIS", version_before), BROKER
            ),
            ApiErrorId.ERR_SELLER_SUSPENDED,
            422,
        )

        unchanged = validate_success(api.get_route_listing(frozen_id, BROKER))
        assert unchanged["version"] == version_before
        assert unchanged["status"] == "DRAFT"
        owner = validate_success(api.get_seller(pair["lapsed"]["seller"]["id"], BROKER))
        assert owner["status"] == "SUSPENDED"
        assert owner["suspension_reason_code"] == "LICENSE_LAPSED"

        allowed = fx.create_valuation(api, pair["active"]["listing"]["id"], "LISTED_BASIS")
        assert allowed["basis"] == "LISTED_BASIS"
        assert allowed["is_superseded"] is False
        assert_cents(allowed["recurring_mrr_cents"], 20000, "listed recurring")
        assert_multiple_1dp(allowed["base_multiple"], "9.0", "base multiple")
        assert_multiple_1dp(allowed["effective_multiple"], "10.0", "effective multiple")
        assert_cents(allowed["valuation_cents"], 200000, "listed valuation")
