"""Route listings, their roll-ups and the customer stop list (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    make_buyer_headers,
    make_escrow_agent_headers,
    make_platform_admin_headers,
    make_seller_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_listing_claimed_mrr_conservation,
    assert_route_listing,
    assert_service_account,
)

BROKER = TEST_USERS["broker_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
UNKNOWN_LISTING_ID = "11111111-1111-4111-8111-111111111111"


class TestListingBirthAndRollups:
    def test_fresh_listing_defaults_every_rollup_to_zero(self, api):
        """A listing opens in DRAFT with all seven roll-ups at zero while the seller-declared
        figures it was opened with are stored untouched.

        PRD §3.2: "A listing is opened by the brokerage in `DRAFT` against a named `seller_id`".
        PRD §3.2: "All seven start at zero on a fresh listing."
        PRD §3.2: "A fresh listing therefore starts at `EMPTY`".
        PRD §2.4: "`version` is an integer that starts at 1".

        Design: Corner/entities/create_route_listing_defaults_status_and_rollups
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)

        created = validate_success(
            api.create_route_listing(f.route_listing_payload(seller["id"]), BROKER), 201
        )
        assert_route_listing(created)

        assert created["status"] == "DRAFT"
        assert_cents(created["claimed_recurring_mrr_cents"], 0, "claimed recurring")
        assert_cents(created["claimed_repair_mrr_cents"], 0, "claimed repair")
        assert created["claimed_account_count"] == 0
        assert_cents(created["verified_recurring_mrr_cents"], 0, "verified recurring")
        assert_cents(created["verified_repair_mrr_cents"], 0, "verified repair")
        assert created["verified_account_count"] == 0
        assert created["verification_posture"] == "EMPTY"
        assert created["introductions_completed_count"] == 0
        assert created["withdrawal_reason_code"] is None
        assert created["version"] == 1

        # The seller-declared inputs live alongside the zeroed roll-ups.
        assert_cents(created["listed_mrr_cents"], 43000, "listed mrr")
        assert created["listed_account_count"] == 3
        assert_cents(created["asking_price_cents"], 460000, "asking price")

    def test_listing_read_returns_claimed_and_verified_rollups_side_by_side(self, api):
        """Both roll-up families are readable at once: claimed 43000/4000/3 over the three
        stops and verified 30318/3409/2 over the two that resolved to VERIFIED, with the
        posture still INCOMPLETE because A3 landed in DISPUTED.

        PRD §3.2: "`verified_recurring_mrr_cents` and `verified_repair_mrr_cents` are the sums
        of the corresponding per-account verified figures over the narrower set of stops that
        are actually `VERIFIED`".
        PRD §3.2: "It is `INCOMPLETE` when at least one stop is `UNVERIFIED` or `DISPUTED`."

        Design: Corner/entities/get_route_listing_returns_stored_rollups
        """
        ctx = fx.route_with_billing_history(api)
        a1 = fx.verify_account(api, ctx.a1["id"])
        a2 = fx.verify_account(api, ctx.a2["id"])
        a3 = fx.verify_account(api, ctx.a3["id"])
        assert a1["verification_status"] == "VERIFIED"
        assert a2["verification_status"] == "VERIFIED"
        assert a3["verification_status"] == "DISPUTED"

        listing = validate_success(api.get_route_listing(ctx.listing["id"], BROKER))
        assert listing["status"] == "DRAFT"
        assert_cents(listing["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(listing["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert listing["claimed_account_count"] == 3
        assert_cents(listing["verified_recurring_mrr_cents"], 30318, "verified recurring")
        assert_cents(listing["verified_repair_mrr_cents"], 3409, "verified repair")
        assert listing["verified_account_count"] == 2
        assert listing["verification_posture"] == "INCOMPLETE"
        assert listing["introductions_completed_count"] == 0
        assert listing["withdrawal_reason_code"] is None

        # The seller's own declarations are never overwritten by the roll-ups.
        assert_cents(listing["asking_price_cents"], 460000, "asking price")
        assert_cents(listing["listed_mrr_cents"], 43000, "listed mrr")
        assert listing["listed_account_count"] == 3

        accounts, _ = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": ctx.listing["id"]})
        )
        assert_listing_claimed_mrr_conservation(listing, accounts)


class TestStopCollectionPaging:
    def test_three_stops_walk_in_two_pages_with_a_stable_total_count(self, api):
        """The same three-row set is paged two-then-one: total_count stays 3 across both pages
        while has_more flips true then false, and the unfiltered page returns all three at the
        declared default limit of 10.

        PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted".
        PRD §2.3: "the `meta` block of a list response carries `total_count` — the number of
        records matching the filters before pagination is applied — and `has_more`, which is
        true exactly when records remain beyond the current page."

        Design: Corner/entities/list_service_accounts_paginates_with_total_count_and_has_more
        """
        ctx = fx.draft_route_with_three_stops(api)
        listing_id = ctx.listing["id"]

        first, meta_one = validate_paginated(
            api.list_service_accounts(
                BROKER, params={"listing_id": listing_id, "limit": 2, "offset": 0}
            )
        )
        assert len(first) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        second, meta_two = validate_paginated(
            api.list_service_accounts(
                BROKER, params={"listing_id": listing_id, "limit": 2, "offset": 2}
            )
        )
        assert len(second) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2

        third, meta_three = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": listing_id})
        )
        assert len(third) == 3
        assert meta_three["total_count"] == 3
        assert meta_three["has_more"] is False
        assert meta_three["limit"] == 10
        assert meta_three["offset"] == 0

        walked = [row["id"] for row in first] + [row["id"] for row in second]
        assert len(set(walked)) == 3
        assert set(walked) == {ctx.a1["id"], ctx.a2["id"], ctx.a3["id"]}

    def test_pagination_bounds_are_rejected_not_silently_clamped(self, api):
        """limit 0, limit 101 and offset -1 are all 400s, while limit 100 — the inclusive
        maximum — and an offset one past the last row both succeed.

        PRD §2.3: "it defaults to 10 when omitted, may not be smaller than 1, and may not be
        larger than 100."
        PRD §2.3: "`limit=0`, `limit=101`, `offset=-1` and any non-numeric value are all
        rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/validations/pagination_limit_and_offset_out_of_range_rejected
        """
        ctx = fx.draft_route_with_three_stops(api)
        listing_id = ctx.listing["id"]

        validate_error(
            api.list_service_accounts(BROKER, params={"listing_id": listing_id, "limit": 0}),
            ApiErrorId.ERR_VALIDATION,
            400,
        )
        validate_error(
            api.list_service_accounts(BROKER, params={"listing_id": listing_id, "limit": 101}),
            ApiErrorId.ERR_VALIDATION,
            400,
        )
        validate_error(
            api.list_service_accounts(BROKER, params={"listing_id": listing_id, "offset": -1}),
            ApiErrorId.ERR_VALIDATION,
            400,
        )

        rows, meta = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": listing_id, "limit": 100})
        )
        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 100

        past_end, meta_end = validate_paginated(
            api.list_service_accounts(
                BROKER, params={"listing_id": listing_id, "limit": 2, "offset": 3}
            )
        )
        assert past_end == []
        assert meta_end["total_count"] == 3
        assert meta_end["has_more"] is False


class TestStopCreationSurface:
    def test_dropping_a_required_stop_field_is_refused_and_persists_nothing(self, api):
        """A missing `_cents` amount and a missing enum that decides a downstream formula branch
        are both request-shape failures, and neither rejected write leaves a row behind.

        PRD §2.9: "`ERR_VALIDATION` — request-body shape: a required field is missing".
        PRD §3.2: "A stop records the seller's own `customer_ref` for the pool, between 1 and 60
        characters and unique within its listing ... the recurring `monthly_service_fee_cents`
        invoice of at least one cent, the `avg_monthly_chemical_cents` and
        `avg_monthly_repair_cents` averages of at least zero, a `chemical_billing_method` of
        `INCLUDED` or `PASS_THROUGH`, and a `billing_frequency` of `MONTHLY` or `QUARTERLY`."

        Design: Corner/entities/create_service_account_missing_required_field_rejected
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])

        no_fee = f.service_account_payload(listing["id"])
        no_fee.pop("monthly_service_fee_cents")
        validate_error(
            api.create_service_account(no_fee, BROKER), ApiErrorId.ERR_VALIDATION, 400
        )

        no_method = f.service_account_payload(listing["id"], customer_ref="A9-NO-METHOD")
        no_method.pop("chemical_billing_method")
        validate_error(
            api.create_service_account(no_method, BROKER), ApiErrorId.ERR_VALIDATION, 400
        )

        rows, meta = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": listing["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        parent = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(parent["claimed_recurring_mrr_cents"], 0, "claimed recurring")
        assert parent["claimed_account_count"] == 0
        assert parent["verification_posture"] == "EMPTY"

    def test_stop_derived_columns_are_recomputed_and_client_values_discarded(self, api):
        """A stop that tries to dictate its own claimed recurring billing and age is stored with
        the server's own figures: 16000 from the fee plus the INCLUDED chemical, and 88 months
        from the service start date against the logical clock.

        PRD §3.2: "Two derived numbers are computed on every stop and are never accepted from
        the client."
        PRD §3.2: "The claimed recurring figure is the normalised service component plus the
        chemical component."
        PRD §3.2: "The second derived number is `account_age_months`, the whole months elapsed
        from `service_start_date` to the logical clock."
        PRD §3.2: "A new stop begins with its verification dimension at `UNVERIFIED` and its
        transfer dimension at `PENDING`."

        Design: Corner/entities/create_service_account_computed_claimed_mrr_input_ignored
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])

        stop = validate_success(
            api.create_service_account(
                f.service_account_payload(
                    listing["id"],
                    claimed_recurring_mrr_cents=999999,
                    account_age_months=3,
                    verification_status="VERIFIED",
                ),
                BROKER,
            ),
            201,
        )
        assert_service_account(stop)
        assert_cents(stop["claimed_recurring_mrr_cents"], 16000, "claimed recurring")
        assert stop["account_age_months"] == 88
        assert stop["verification_status"] == "UNVERIFIED"
        assert stop["transfer_status"] == "PENDING"
        for null_field in (
            "verified_recurring_mrr_cents",
            "verified_repair_mrr_cents",
            "verification_variance",
            "current_mrr_cents",
            "deal_id",
            "replaced_account_id",
            "introduction_sequence_no",
            "introduced_on",
            "exclusion_reason_code",
        ):
            assert stop[null_field] is None, f"{null_field} should be null on a fresh stop"

        parent = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(parent["claimed_recurring_mrr_cents"], 16000, "claimed recurring")
        assert_cents(parent["claimed_repair_mrr_cents"], 1500, "claimed repair")

    def test_a_stop_whose_parent_listing_does_not_exist_is_refused(self, api):
        """The parent is carried in the body, so a well-formed stop naming a listing id that
        resolves to nothing answers the listing's own 404 — and the identical body against the
        real listing lands and is reachable through the filtered collection.

        PRD §2.9: "`ERR_LISTING_NOT_FOUND` — a route listing identifier in the path or body
        resolves to nothing."
        PRD §4: "a listing's customer stops are reached through the `/service-accounts`
        collection filtered by `listing_id`, not through a path beneath the listing."

        Design: Corner/entities/service_account_requires_existing_listing_parent
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])

        validate_error(
            api.create_service_account(
                f.service_account_payload(UNKNOWN_LISTING_ID), BROKER
            ),
            ApiErrorId.ERR_LISTING_NOT_FOUND,
            404,
        )

        stop = validate_success(
            api.create_service_account(f.service_account_payload(listing["id"]), BROKER), 201
        )
        assert stop["listing_id"] == listing["id"]
        assert_cents(stop["claimed_recurring_mrr_cents"], 16000, "claimed recurring")

        rows, meta = validate_paginated(
            api.list_service_accounts(BROKER, params={"listing_id": listing["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == stop["id"]

        parent = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert parent["claimed_account_count"] == 1

    def test_quarterly_service_fee_is_divided_before_the_chemical_is_added(self, api):
        """Two stops carrying byte-identical money differ only in billing_frequency, so the
        QUARTERLY divisor alone produces 18333 against 49000 — and because the division rounds
        before the chemical joins, the quarterly answer is 15333 + 3000 rather than 16333.

        PRD §3.2: "for a `QUARTERLY` account the same figure covers three months of service and
        is therefore divided by three and rounded half up to whole cents before anything else
        happens."
        PRD §3.2: "`avg_monthly_repair_cents` never enters the recurring base at all under any
        billing method".

        Design: Corner/calculations/account_claimed_recurring_mrr_normalises_quarterly_billing
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"], region_code="PHX-QTR")
        money = dict(
            service_start_date="2019-03-15",
            monthly_service_fee_cents=46000,
            avg_monthly_chemical_cents=3000,
            avg_monthly_repair_cents=900,
            chemical_billing_method="INCLUDED",
        )

        quarterly = validate_success(
            api.create_service_account(
                f.service_account_payload(
                    listing["id"], customer_ref="Q1-QUARTERLY", route_day="MON",
                    billing_frequency="QUARTERLY", **money,
                ),
                BROKER,
            ),
            201,
        )
        assert_cents(quarterly["claimed_recurring_mrr_cents"], 18333, "quarterly claimed")
        assert quarterly["claimed_recurring_mrr_cents"] != 16333

        monthly = validate_success(
            api.create_service_account(
                f.service_account_payload(
                    listing["id"], customer_ref="Q2-MONTHLY", route_day="TUE",
                    billing_frequency="MONTHLY", **money,
                ),
                BROKER,
            ),
            201,
        )
        assert_cents(monthly["claimed_recurring_mrr_cents"], 49000, "monthly claimed")

        parent = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(parent["claimed_recurring_mrr_cents"], 67333, "listing claimed recurring")
        assert_cents(parent["claimed_repair_mrr_cents"], 1800, "listing claimed repair")
        assert parent["claimed_account_count"] == 2


class TestListingAmendment:
    def test_patch_touches_only_the_named_field_and_is_state_gated(self, api):
        """A body carrying only `asking_price_cents` leaves the declared revenue, the account
        count and the exclusivity window exactly as they were while still bumping the version —
        and the same body is refused once the listing has been withdrawn.

        PRD §4: "Amend a draft listing's `asking_price_cents`, `listed_mrr_cents`,
        `listed_account_count`, `exclusive_start_date` or `exclusive_end_date`; omitted fields
        are left as they are."
        PRD §2.4: "`version` is an integer that starts at 1 and increases by exactly 1 on every
        mutation of that record".
        PRD §3.2: "an amendment attempted on an `UNDER_CONTRACT`, `CLOSED` or `WITHDRAWN`
        listing is refused with `ERR_INVALID_LISTING_TRANSITION`."

        Design: Corner/endpoints/patch_listing_updates_only_the_named_fields_and_bumps_the_version
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        listing = fx.seed_listing(api, seller["id"])
        assert listing["version"] == 1

        patched = validate_success(
            api.update_route_listing(listing["id"], {"asking_price_cents": 480000}, BROKER)
        )
        assert_cents(patched["asking_price_cents"], 480000, "asking price")
        assert_cents(patched["listed_mrr_cents"], 43000, "listed mrr")
        assert patched["listed_account_count"] == 3
        assert patched["exclusive_start_date"] == "2026-08-01"
        assert patched["exclusive_end_date"] == "2026-11-01"
        assert patched["status"] == "DRAFT"
        assert patched["version"] == 2

        reread = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(reread["asking_price_cents"], 480000, "asking price")
        assert reread["version"] == 2

        withdrawn = validate_success(
            api.withdraw_route_listing(listing["id"], f.withdraw_listing_payload(), BROKER)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["version"] == 3

        validate_error(
            api.update_route_listing(listing["id"], {"asking_price_cents": 500000}, BROKER),
            ApiErrorId.ERR_INVALID_LISTING_TRANSITION,
            409,
        )

        final = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(final["asking_price_cents"], 480000, "asking price")
        assert final["version"] == 3


class TestListingSurfaceAccessControl:
    def test_the_listing_write_surface_belongs_to_the_broker_alone(self, api):
        """Every other role — including PlatformAdmin, the strongest role elsewhere — is refused
        on the four broker-owned listing writes, and the role gate answers before existence, so
        a Buyer patching an unknown id gets 403 rather than 404.

        PRD §2.1: "If the role is recognised but is not one of the roles authorised for the
        endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403); this too precedes
        existence, so a `Buyer` probing an unknown listing identifier receives 403 rather
        than 404."
        PRD §2.1: "There is no hierarchical override anywhere in this API."
        PRD §4: "The `Authorized Role(s)` column is exhaustive: a role absent from it is refused
        with `ERR_UNAUTHORIZED`".

        Design: Corner/rbac/broker_exclusive_listing_writes_are_unauthorized_for_every_other_role
        """
        fx.seed_az_profile(api)
        seller = fx.seed_seller(api)
        buyer = fx.seed_buyer(api)
        listing = fx.seed_listing(api, seller["id"])
        seller_headers = make_seller_headers(seller["id"])
        buyer_headers = make_buyer_headers(buyer["id"])

        validate_error(
            api.create_route_listing(f.route_listing_payload(seller["id"]), seller_headers),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.update_route_listing(
                listing["id"], {"asking_price_cents": 480000}, buyer_headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.update_route_listing(
                UNKNOWN_LISTING_ID, {"asking_price_cents": 480000}, buyer_headers
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_service_account(
                f.service_account_payload(listing["id"]), make_escrow_agent_headers("escrow-x")
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )
        validate_error(
            api.publish_route_listing(listing["id"], make_platform_admin_headers()),
            ApiErrorId.ERR_UNAUTHORIZED,
            403,
        )

        validate_success(
            api.create_service_account(f.service_account_payload(listing["id"]), BROKER), 201
        )

        as_buyer = validate_success(api.get_route_listing(listing["id"], buyer_headers))
        assert_cents(as_buyer["asking_price_cents"], 460000, "asking price")
        assert as_buyer["status"] == "DRAFT"
        assert as_buyer["claimed_account_count"] == 1

    def test_a_missing_or_unrecognised_role_is_401_on_reads_and_writes_alike(self, api):
        """The role check runs first and treats an absent header and an unrecognised role name
        identically — 401, never the 403 reserved for a known role — and it guards reads too.

        PRD §2.1: "If `X-User-Role` is absent, empty, or holds any string other than the five
        recognised role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.1: "Every request to this API — reads included — must carry two headers."

        Design: Corner/validations/listing_write_without_a_known_role_header_unauthenticated
        """
        seller = fx.seed_seller(api)
        body = f.route_listing_payload(seller["id"])

        validate_error(
            api.create_route_listing(body, headers_without_role()),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.create_route_listing(body, headers_with_unknown_role()),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.list_route_listings(headers_with_unknown_role()),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        rows, meta = validate_paginated(api.list_route_listings(BROKER))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_seller_may_only_withdraw_the_listing_it_owns(self, api):
        """The Seller role is entity-backed, so the same withdrawal request is 403 for a second,
        equally valid ACTIVE seller and 200 for the owner — ownership outranks the fact that the
        listing is perfectly withdrawable.

        PRD §2.1: "When a `Seller` or `Buyer` addresses a resource that some other party owns,
        the rejection is `ERR_ACTOR_NOT_OWNER` (HTTP 403), and it fires even on endpoints where
        that role is otherwise authorised".
        PRD §3.2: "Either the brokerage or the owning seller may withdraw a listing from the
        market, supplying a `withdrawal_reason_code`".

        Design: Corner/validations/seller_acting_on_a_listing_it_does_not_own_is_forbidden
        """
        fx.seed_az_profile(api)
        owner = fx.seed_seller(api)
        stranger = fx.second_seller(api)
        listing = fx.seed_listing(api, owner["id"])
        body = f.withdraw_listing_payload(withdrawal_reason_code="SELLER_RETIRED")

        validate_error(
            api.withdraw_route_listing(listing["id"], body, make_seller_headers(stranger["id"])),
            ApiErrorId.ERR_ACTOR_NOT_OWNER,
            403,
        )

        untouched = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert untouched["status"] == "DRAFT"
        assert untouched["withdrawal_reason_code"] is None

        withdrawn = validate_success(
            api.withdraw_route_listing(listing["id"], body, make_seller_headers(owner["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason_code"] == "SELLER_RETIRED"


def az_seller(api):
    """Clock, AZ regime and one ACTIVE seller — the shared prelude of the stop-level tests."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.seed_az_profile(api)
    return fx.seed_seller(api)


class TestTheChemicalBillingMethodIsAWholeBranchOfTheClaimedBase:
    def test_identical_inputs_diverge_by_the_chemical_component_alone(self, api):
        """Two stops are created with byte-identical service, chemical and repair figures and the same
        start date; only `chemical_billing_method` differs, and the claimed base differs by exactly the
        chemical figure while repair stays outside the base under both branches.

        PRD §3.2: "Its chemical component is `avg_monthly_chemical_cents` when
        `chemical_billing_method` is `INCLUDED`, and zero when it is `PASS_THROUGH`, because
        pass-through chemicals are billed at cost and never earn a multiple. The claimed recurring
        figure is the normalised service component plus the chemical component."
        PRD §3.2: "`avg_monthly_repair_cents` never enters the recurring base at all under any billing
        method — repair revenue is valued separately, at its own multiple, later."
        PRD §3.2: "`claimed_recurring_mrr_cents` on the listing is the sum of
        `claimed_recurring_mrr_cents` over the stops whose verification dimension is anything other
        than `EXCLUDED`; `claimed_repair_mrr_cents` is the sum of `avg_monthly_repair_cents` over the
        same set; and `claimed_account_count` is how many stops that set holds."

        Design: Difficulty/dual_variant_calc/account_claimed_mrr_included_versus_pass_through_chemical
        """
        seller = az_seller(api)
        listing = fx.seed_listing(api, seller["id"], region_code="PHX-NE")
        empty = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(empty["claimed_recurring_mrr_cents"], 0, "claimed recurring")
        assert empty["claimed_account_count"] == 0

        shared = dict(
            service_start_date="2019-03-15", route_day="TUE", monthly_service_fee_cents=12000,
            avg_monthly_chemical_cents=4000, avg_monthly_repair_cents=1500,
            billing_frequency="MONTHLY",
        )
        included = fx.add_account(
            api, listing["id"], customer_ref="S-INCLUDED",
            chemical_billing_method="INCLUDED", **shared
        )
        passed_through = fx.add_account(
            api, listing["id"], customer_ref="S-PASS-THROUGH",
            chemical_billing_method="PASS_THROUGH", **shared
        )
        assert_service_account(included)
        assert_service_account(passed_through)

        assert_cents(included["claimed_recurring_mrr_cents"], 16000, "INCLUDED claimed recurring")
        assert_cents(
            passed_through["claimed_recurring_mrr_cents"], 12000, "PASS_THROUGH claimed recurring"
        )
        assert (
            included["claimed_recurring_mrr_cents"]
            - passed_through["claimed_recurring_mrr_cents"] == 4000
        )
        assert_cents(included["avg_monthly_repair_cents"], 1500, "INCLUDED repair average")
        assert_cents(passed_through["avg_monthly_repair_cents"], 1500, "PASS_THROUGH repair average")
        assert included["account_age_months"] == 88
        assert passed_through["account_age_months"] == 88

        rolled_up = validate_success(api.get_route_listing(listing["id"], BROKER))
        assert_cents(rolled_up["claimed_recurring_mrr_cents"], 28000, "listing claimed recurring")
        assert_cents(rolled_up["claimed_repair_mrr_cents"], 3000, "listing claimed repair")
        assert rolled_up["claimed_account_count"] == 2
        assert_listing_claimed_mrr_conservation(rolled_up, [included, passed_through])

    def test_the_branch_reaches_the_price_because_only_the_base_earns_the_multiple(self, api):
        """Two single-stop routes hold the same raw money and are valued at the same instant on the
        same tier and age band; the pass-through route is worth 40000 cents less, which is the chemical
        figure at the recurring multiple, while both routes carry the same repair component.

        PRD §3.2: "Its chemical component is `avg_monthly_chemical_cents` when
        `chemical_billing_method` is `INCLUDED`, and zero when it is `PASS_THROUGH`, because
        pass-through chemicals are billed at cost and never earn a multiple."
        PRD §3.4: "its input set is every stop of the listing whose verification dimension is anything
        other than `EXCLUDED`, each contributing its `claimed_recurring_mrr_cents` as its recurring
        figure and its `avg_monthly_repair_cents` as its repair figure."
        PRD §3.4: "`repair_component_cents` is the snapshot's `repair_mrr_cents` multiplied by a flat
        repair multiple of three point zero, rounded half up to whole cents"

        Design: Difficulty/dual_variant_calc/account_claimed_mrr_included_versus_pass_through_chemical
        """
        seller = az_seller(api)
        shared = dict(
            service_start_date="2019-03-15", route_day="TUE", monthly_service_fee_cents=12000,
            avg_monthly_chemical_cents=4000, avg_monthly_repair_cents=1500,
            billing_frequency="MONTHLY",
        )
        snapshots = {}
        for method, region in (("INCLUDED", "CHEM-INCL"), ("PASS_THROUGH", "CHEM-PASS")):
            listing = fx.seed_listing(
                api, seller["id"], region_code=region, listed_mrr_cents=16000,
                listed_account_count=1, asking_price_cents=160000,
            )
            fx.add_account(
                api, listing["id"], customer_ref=f"{region}-S1",
                chemical_billing_method=method, **shared
            )
            snapshots[method] = fx.create_valuation(api, listing["id"], "LISTED_BASIS")

        included = snapshots["INCLUDED"]
        passed_through = snapshots["PASS_THROUGH"]

        assert_cents(included["recurring_mrr_cents"], 16000, "INCLUDED recurring base")
        assert_cents(included["repair_mrr_cents"], 1500, "INCLUDED repair base")
        assert included["weighted_avg_account_age_months"] == 88
        assert_cents(included["recurring_component_cents"], 160000, "INCLUDED recurring component")
        assert_cents(included["repair_component_cents"], 4500, "INCLUDED repair component")
        assert_cents(included["valuation_cents"], 164500, "INCLUDED valuation")

        assert_cents(passed_through["recurring_mrr_cents"], 12000, "PASS_THROUGH recurring base")
        assert_cents(passed_through["repair_mrr_cents"], 1500, "PASS_THROUGH repair base")
        assert passed_through["weighted_avg_account_age_months"] == 88
        assert_cents(
            passed_through["recurring_component_cents"], 120000, "PASS_THROUGH recurring component"
        )
        assert_cents(
            passed_through["repair_component_cents"], 4500, "PASS_THROUGH repair component"
        )
        assert_cents(passed_through["valuation_cents"], 124500, "PASS_THROUGH valuation")

        assert included["valuation_cents"] - passed_through["valuation_cents"] == 40000
        assert included["repair_component_cents"] == passed_through["repair_component_cents"]


class TestExclusivityIsAHalfOpenIntervalOnSellerAndRegion:
    def test_a_window_may_start_on_the_day_the_incumbent_ends_but_not_a_day_earlier(self, api):
        """Adjacency is accepted because the incumbent's end date is outside its own window, and moving
        the same three-month window one day earlier makes it overlap by exactly that day and be
        refused; the refusal writes no row and leaves both surviving listings in `DRAFT`.

        PRD §3.2: "A listing's `[exclusive_start_date, exclusive_end_date)` interval may not overlap
        the interval of any other listing for the same `seller_id` and `region_code` that is not
        `WITHDRAWN`; a collision is `ERR_LISTING_EXCLUSIVITY_OVERLAP`. Because the interval is
        half-open, a new window beginning on exactly the date an existing window ends is permitted."
        PRD §3.2: "`exclusive_start_date` is the first date inside that window and
        `exclusive_end_date` is its exclusive end"

        Design: Difficulty/resource_temporal_overlap/listing_exclusivity_half_open_adjacency_allowed
        """
        seller = az_seller(api)
        base = fx.seed_listing(
            api, seller["id"], region_code="EXC-01",
            exclusive_start_date="2026-08-01", exclusive_end_date="2026-11-01",
        )
        assert base["exclusive_end_date"] == "2026-11-01"

        adjacent = validate_success(
            api.create_route_listing(
                f.route_listing_payload(
                    seller["id"], region_code="EXC-01",
                    exclusive_start_date="2026-11-01", exclusive_end_date="2027-02-01",
                ),
                BROKER,
            ),
            201,
        )
        assert_route_listing(adjacent)
        assert adjacent["exclusive_start_date"] == "2026-11-01"
        assert adjacent["exclusive_end_date"] == "2027-02-01"

        validate_error(
            api.create_route_listing(
                f.route_listing_payload(
                    seller["id"], region_code="EXC-01",
                    exclusive_start_date="2026-10-31", exclusive_end_date="2027-01-31",
                ),
                BROKER,
            ),
            ApiErrorId.ERR_LISTING_EXCLUSIVITY_OVERLAP,
            409,
        )

        rows, meta = validate_paginated(
            api.list_route_listings(
                BROKER, params={"seller_id": seller["id"], "region_code": "EXC-01"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {base["id"], adjacent["id"]}
        assert all(row["status"] == "DRAFT" for row in rows)

    def test_the_same_refused_window_is_free_one_region_over(self, api):
        """The window that collided in `EXC-01` is accepted in `EXC-02` under the same seller and the
        same regime, so the conflict was a property of the region pair and not of the dates; the second
        region's listing is a full first-class `DRAFT` row.

        PRD §3.2: "**Exclusivity is scoped to the pair of seller and region.**"
        PRD §3.2: "The same window in a different region is always permitted."
        PRD §3.2: "A listing is opened by the brokerage in `DRAFT` against a named `seller_id`".

        Design: Difficulty/resource_temporal_overlap/listing_exclusivity_half_open_adjacency_allowed
        """
        seller = az_seller(api)
        base = fx.seed_listing(
            api, seller["id"], region_code="EXC-01",
            exclusive_start_date="2026-08-01", exclusive_end_date="2026-11-01",
        )

        colliding = dict(
            exclusive_start_date="2026-10-31", exclusive_end_date="2027-01-31"
        )
        validate_error(
            api.create_route_listing(
                f.route_listing_payload(seller["id"], region_code="EXC-01", **colliding), BROKER
            ),
            ApiErrorId.ERR_LISTING_EXCLUSIVITY_OVERLAP,
            409,
        )

        elsewhere = validate_success(
            api.create_route_listing(
                f.route_listing_payload(seller["id"], region_code="EXC-02", **colliding), BROKER
            ),
            201,
        )
        assert elsewhere["region_code"] == "EXC-02"
        assert elsewhere["exclusive_start_date"] == "2026-10-31"
        assert elsewhere["exclusive_end_date"] == "2027-01-31"
        assert elsewhere["status"] == "DRAFT"
        assert elsewhere["seller_id"] == seller["id"]

        first_region, meta = validate_paginated(
            api.list_route_listings(
                BROKER, params={"seller_id": seller["id"], "region_code": "EXC-01"}
            )
        )
        assert meta["total_count"] == 1
        assert first_region[0]["id"] == base["id"]
        assert first_region[0]["status"] == "DRAFT"


class TestReinstateCompensatesExcludeOnTheClaimedDimension:
    def test_the_round_trip_restores_the_claimed_roll_up_to_the_exact_cent(self, api):
        """Excluding the middle stop drops the roll-up by precisely that stop's own claimed figures and
        reinstating it puts them back exactly, with the stop's own claimed number never having moved;
        both legs are real writes, so the listing's version has advanced by two while its values have
        not moved at all.

        PRD §3.6: "Because the claimed figures are a pure sum over included stops and the stop's own
        `claimed_recurring_mrr_cents` is untouched by exclusion, an exclude followed immediately by a
        reinstate returns the listing's claimed roll-up to precisely the cents it held before — the
        pair is exactly compensating on the claimed dimension"
        PRD §3.6: "Reinstating a stop moves it from `EXCLUDED` back to `UNVERIFIED` ... The
        `exclusion_reason_code` is cleared to null, and so are `verified_recurring_mrr_cents`,
        `verified_repair_mrr_cents` and `verification_variance`"
        PRD §3.6: "The listing's `claimed_recurring_mrr_cents`, `claimed_repair_mrr_cents`,
        `claimed_account_count` and `verification_posture` are recomputed and its `version` increments."

        Design: Difficulty/compensating_invariant/reinstate_account_restores_listing_claimed_rollup_exactly
        """
        ctx = fx.draft_route_with_three_stops(api)
        listing_id = ctx.listing["id"]

        before = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(before["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(before["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert before["claimed_account_count"] == 3
        assert before["verification_posture"] == "EMPTY"
        version_before = before["version"]

        excluded = fx.exclude_account(
            api, ctx.a2["id"], exclusion_reason_code="CUSTOMER_ALREADY_CANCELLED"
        )
        assert excluded["verification_status"] == "EXCLUDED"
        assert excluded["exclusion_reason_code"] == "CUSTOMER_ALREADY_CANCELLED"
        assert_cents(excluded["claimed_recurring_mrr_cents"], 15000, "A2 claimed recurring")

        shrunk = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(shrunk["claimed_recurring_mrr_cents"], 28000, "claimed recurring")
        assert_cents(shrunk["claimed_repair_mrr_cents"], 2000, "claimed repair")
        assert shrunk["claimed_account_count"] == 2

        reinstated = validate_success(api.reinstate_service_account(ctx.a2["id"], BROKER))
        assert reinstated["verification_status"] == "UNVERIFIED"
        assert reinstated["exclusion_reason_code"] is None
        assert reinstated["verified_recurring_mrr_cents"] is None
        assert reinstated["verified_repair_mrr_cents"] is None
        assert reinstated["verification_variance"] is None
        assert_cents(reinstated["claimed_recurring_mrr_cents"], 15000, "A2 claimed recurring")

        after = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(after["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(after["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert after["claimed_account_count"] == 3
        assert after["verification_posture"] == "EMPTY"
        assert_cents(after["verified_recurring_mrr_cents"], 0, "verified recurring")
        assert after["version"] == version_before + 2
        assert_listing_claimed_mrr_conservation(after, [ctx.a1, reinstated, ctx.a3])

    def test_the_verified_dimension_is_not_compensated_by_the_same_round_trip(self, api):
        """The identical round trip on a stop that had been verified restores the claimed roll-up to
        the cent and deliberately leaves the verified side short: the stop comes back as `UNVERIFIED`,
        the listing's verified figures still exclude it, and the snapshot the exclusion superseded is
        not resurrected.

        PRD §3.6: "Reinstating a stop moves it from `EXCLUDED` back to `UNVERIFIED` — never straight
        back to `VERIFIED`, because the evidence must be re-examined."
        PRD §3.6: "the pair is exactly compensating on the claimed dimension, while on the verified
        dimension the reinstatement leaves the route short until the stop is verified again.
        Reinstating does not resurrect a superseded valuation"
        PRD §3.2: "It is `INCOMPLETE` when at least one stop is `UNVERIFIED` or `DISPUTED`."

        Design: Difficulty/compensating_invariant/reinstate_account_restores_listing_claimed_rollup_exactly
        """
        ctx = fx.route_with_billing_history(api)
        listing_id = ctx.listing["id"]
        fx.verify_account(api, ctx.a1["id"])
        fx.verify_account(api, ctx.a2["id"])
        original = fx.create_valuation(api, listing_id, "VERIFIED_BASIS")
        assert_cents(original["valuation_cents"], 343725, "verified valuation")

        before = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(before["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(before["verified_recurring_mrr_cents"], 30318, "verified recurring")
        assert before["verified_account_count"] == 2

        fx.exclude_account(api, ctx.a2["id"], exclusion_reason_code="CUSTOMER_ALREADY_CANCELLED")
        shrunk = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(shrunk["claimed_recurring_mrr_cents"], 28000, "claimed recurring")
        assert_cents(shrunk["verified_recurring_mrr_cents"], 16000, "verified recurring")
        assert shrunk["verified_account_count"] == 1

        reinstated = validate_success(api.reinstate_service_account(ctx.a2["id"], BROKER))
        assert reinstated["verification_status"] == "UNVERIFIED"
        assert reinstated["verified_recurring_mrr_cents"] is None

        after = validate_success(api.get_route_listing(listing_id, BROKER))
        assert_cents(after["claimed_recurring_mrr_cents"], 43000, "claimed recurring")
        assert_cents(after["claimed_repair_mrr_cents"], 4000, "claimed repair")
        assert after["claimed_account_count"] == 3
        assert_cents(after["verified_recurring_mrr_cents"], 16000, "verified recurring")
        assert_cents(after["verified_repair_mrr_cents"], 1500, "verified repair")
        assert after["verified_account_count"] == 1
        assert after["verification_posture"] == "INCOMPLETE"

        stale = validate_success(api.get_route_valuation(original["id"], BROKER))
        assert stale["is_superseded"] is True
        live, meta = validate_paginated(
            api.list_route_valuations(
                BROKER,
                params={
                    "listing_id": listing_id,
                    "basis": "VERIFIED_BASIS",
                    "is_superseded": "false",
                },
            )
        )
        assert meta["total_count"] == 1
        assert_cents(live[0]["valuation_cents"], 164500, "post-exclusion verified valuation")
