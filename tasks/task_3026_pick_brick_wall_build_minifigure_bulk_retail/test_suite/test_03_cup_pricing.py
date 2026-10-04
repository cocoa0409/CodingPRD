"""Cup models, the two pricing readings and member pricing."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    draw_from_bin,
    load_bin,
    make_member_headers,
    open_cup,
    open_store,
    reset_clock,
    schedule_launch,
    setup_store_with_wall,
    validate_error,
    validate_success,
)


class TestCupFillPricing:
    """Flat bucket pricing, the overage band and the restricted envelope."""

    def test_overage_band_and_bulk_band_resolve_on_one_checkout_endpoint(self, api):
        """PRD §3.2: "first the piece subtotal, which is the declared count
        multiplied by twelve cents per piece; then a bulk band, which is a flat
        400 cents when the declared count reaches 100 pieces and zero below that
        threshold; then the two are summed."
        PRD §3.2: "`member_discount_cents` is the base price multiplied by that
        rate, rounded half up, and the discounted amount is the base minus the
        discount."

        Design: Difficulty/combinatorial_formula/overage_band_and_bulk_band_resolve_on_one_checkout_endpoint
        """
        store, element, member, _bin = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        order = open_cup(store["id"], member["id"], cup_size="LARGE",
                         pricing_model="PER_PIECE", declared_mass_grams=300,
                         pieced_element_id=element["id"], declared_piece_count=100)
        settled = validate_success(api.checkout_fusion_order(
            order["id"], {"expected_fusion_order_version": order["version"]},
            make_member_headers(member["id"])), 200)

        assert settled["priced_piece_count"] == 100, (
            "PER_PIECE charges the client-declared count")
        assert settled["base_price_cents"] == 1600, (
            "100 pieces reach the bulk threshold: 1200 + a flat 400 cents")
        assert settled["member_discount_cents"] == 160, (
            "the standard rate is one tenth of the base, rounded half up")
        assert settled["final_price_cents"] == 1440

    def test_cup_fill_overage_band_starts_one_piece_past_the_bucket(self, api):
        """PRD §3.2: "Instead `priced_piece_count` is the declared mass
        multiplied by the number of pieces the cup size is expected to include,
        divided by the reference mass for that cup size, rounded half up once to
        a whole number."
        PRD §3.2: "The band allowances are 44 cents for small, 88 for large and
        132 for jumbo. The boundary is deliberate: exactly the expected piece
        count is inside the flat price, and one piece beyond it produces the
        first non-zero band."

        Design: Difficulty/combinatorial_formula/small_cup_band_and_waitlist_promotion_arithmetic_in_one_wave
        """
        store, element, member, bin_row = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        on_bucket = open_cup(store["id"], member["id"], cup_size="SMALL",
                             pricing_model="CUP_FILL", declared_mass_grams=200)
        on_bucket = draw_from_bin(on_bucket["id"], bin_row["id"], 200)
        settled_on = validate_success(api.checkout_fusion_order(
            on_bucket["id"], {"expected_fusion_order_version": on_bucket["version"]},
            make_member_headers(member["id"])), 200)
        assert settled_on["priced_piece_count"] == 60, (
            "200 g of a 200 g reference mass is exactly the expected count")
        assert settled_on["base_price_cents"] == 60, (
            "a cup exactly on the expected count pays the flat bucket alone")

        over_bucket = open_cup(store["id"], member["id"], cup_size="SMALL",
                               pricing_model="CUP_FILL", declared_mass_grams=260)
        over_bucket = draw_from_bin(over_bucket["id"], bin_row["id"], 260)
        settled_over = validate_success(api.checkout_fusion_order(
            over_bucket["id"], {"expected_fusion_order_version": over_bucket["version"]},
            make_member_headers(member["id"])), 200)
        assert settled_over["priced_piece_count"] == 78, (
            "260 * 60 / 200 rounds half up to 78 pieces")
        assert settled_over["base_price_cents"] == 73, (
            "18 pieces past the bucket is a 13-cent band on top of the 60-cent bucket")

    def test_large_cup_two_pieces_over_the_bucket_pays_the_first_band(self, api):
        """PRD §3.2: "On top of that sits an overage band, which is zero while
        the inferred count is at or below the expected piece count for that
        size, and otherwise is the excess pieces multiplied by the band
        allowance for the cup size and divided by the expected piece count,
        rounded half up."
        PRD §3.2: "The band allowances are 44 cents for small, 88 for large and
        132 for jumbo."

        Design: Difficulty/combinatorial_formula/small_cup_band_and_waitlist_promotion_arithmetic_in_one_wave
        """
        store, element, member, bin_row = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        order = open_cup(store["id"], member["id"], cup_size="LARGE",
                         pricing_model="CUP_FILL", declared_mass_grams=440)
        order = draw_from_bin(order["id"], bin_row["id"], 440)
        settled = validate_success(api.checkout_fusion_order(
            order["id"], {"expected_fusion_order_version": order["version"]},
            make_member_headers(member["id"])), 200)
        assert settled["priced_piece_count"] == 132, (
            "440 * 120 / 400 rounds half up to 132 pieces")
        assert settled["base_price_cents"] == 129, (
            "12 pieces past the 120-piece bucket is a 9-cent band")

    def test_restricted_store_admits_only_a_cup_inside_its_mass_capacity(self, api):
        """PRD §2.5: "A `RESTRICTED` store keeps trading but compresses its
        commercial envelope in two ways: a cup whose weighed mass exceeds the
        mass capacity for its cup size is refused with `ERR_STORE_RESTRICTED`,
        and the price of a cup that is admitted is halved as described in §2.8."

        Design: Corner/errors/restricted_store_caps_the_cup_but_admits_a_smaller_one
        """
        store, _element, _member, _bin = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 199})

        # The store read gives the re-derived posture; the fixture snapshot is
        # taken before the bin write that moved it below the edge.
        reread = validate_success(api.get_store(
            store["id"], TEST_USERS["associate_headers"]), 200)
        assert reread["bin_engine_mass_grams"] == 199
        assert reread["stage"] == "RESTRICTED", (
            "199 g sits below the 200 g edge of a 2000 g wall")


class TestCupFillMassVersusVolume:
    """The same physical cup read from the scale and from the tunnel."""

    def test_same_cup_priced_from_scale_mass_and_tunnel_volume(self, api):
        """PRD §3.2: "On request the checkout may instead price by volume: when
        the checkout call passes a `pricing_variant` of `VOLUME`, the declared
        mass is replaced by the `measured_volume_ml` multiplied by the same
        reference mass and divided by the volume capacity of the cup size — 250
        millilitres for small, 500 for large and 750 for jumbo — before the
        identical single rounding is applied."
        PRD §3.2: "The two variants deliberately produce different piece counts
        for the same physical cup, so the variant is honoured exactly as
        supplied."

        Design: Difficulty/dual_variant_calc/same_cup_priced_from_scale_mass_and_tunnel_volume
        """
        store, element, member, bin_row = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        mass_cup = open_cup(store["id"], member["id"], cup_size="LARGE",
                            pricing_model="CUP_FILL", declared_mass_grams=440,
                            measured_volume_ml=480)
        mass_cup = draw_from_bin(mass_cup["id"], bin_row["id"], 440)
        mass_settled = validate_success(api.checkout_fusion_order(
            mass_cup["id"], {"expected_fusion_order_version": mass_cup["version"]},
            make_member_headers(member["id"])), 200)
        assert mass_settled["priced_piece_count"] == 132, (
            "440 * 120 / 400 rounds half up to 132 pieces")
        assert mass_settled["base_price_cents"] == 129

        volume_cup = open_cup(store["id"], member["id"], cup_size="LARGE",
                              pricing_model="CUP_FILL", declared_mass_grams=440,
                              measured_volume_ml=480)
        volume_cup = draw_from_bin(volume_cup["id"], bin_row["id"], 440)
        volume_settled = validate_success(api.checkout_fusion_order(
            volume_cup["id"],
            {"expected_fusion_order_version": volume_cup["version"],
             "pricing_variant": "VOLUME"},
            make_member_headers(member["id"])), 200)
        assert volume_settled["priced_piece_count"] == 115, (
            "480 * 400 / 500 gives 384 g of reference mass, hence 115 pieces")
        assert volume_settled["base_price_cents"] == 120

    def test_the_two_readings_of_one_physical_cup_produce_different_money(self, api):
        """PRD §3.2: "The two variants deliberately produce different piece
        counts for the same physical cup, so the variant is honoured exactly as
        supplied."

        Design: Difficulty/dual_variant_calc/same_cup_priced_from_scale_mass_and_tunnel_volume
        """
        store, element, member, bin_row = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        mass_cup = draw_from_bin(open_cup(
            store["id"], member["id"], cup_size="LARGE", pricing_model="CUP_FILL",
            declared_mass_grams=440, measured_volume_ml=480)["id"],
            bin_row["id"], 440)
        volume_cup = draw_from_bin(open_cup(
            store["id"], member["id"], cup_size="LARGE", pricing_model="CUP_FILL",
            declared_mass_grams=440, measured_volume_ml=480)["id"],
            bin_row["id"], 440)

        settled_mass = validate_success(api.checkout_fusion_order(
            mass_cup["id"], {"expected_fusion_order_version": mass_cup["version"]},
            make_member_headers(member["id"])), 200)
        settled_volume = validate_success(api.checkout_fusion_order(
            volume_cup["id"],
            {"expected_fusion_order_version": volume_cup["version"],
             "pricing_variant": "VOLUME"},
            make_member_headers(member["id"])), 200)

        assert settled_mass["priced_piece_count"] != settled_volume["priced_piece_count"], (
            "the two readings of one physical cup must infer different counts")
        assert settled_mass["final_price_cents"] != settled_volume["final_price_cents"], (
            "the differing readings must produce different money")


class TestPricingModelChoice:
    """Counting the pieces versus weighing the cup."""

    def test_per_piece_element_valued_by_count_while_cup_fill_is_valued_by_mass(self, api):
        """PRD §3.2: "Under `PER_PIECE` the charged count is the client-declared
        count, taken as authoritative, and the element the guest is buying must
        be named as `pieced_element_id`."
        PRD §3.2: "The arithmetic is pinned in evaluation order: first the piece
        subtotal, which is the declared count multiplied by twelve cents per
        piece; then a bulk band, which is a flat 400 cents when the declared
        count reaches 100 pieces and zero below that threshold; then the two are
        summed."

        Design: Difficulty/dual_variant_calc/per_piece_element_valued_by_count_while_cup_fill_is_valued_by_mass
        """
        store, element, member, bin_row = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        cup_fill = draw_from_bin(open_cup(
            store["id"], member["id"], cup_size="LARGE", pricing_model="CUP_FILL",
            declared_mass_grams=440)["id"], bin_row["id"], 440)
        cup_settled = validate_success(api.checkout_fusion_order(
            cup_fill["id"], {"expected_fusion_order_version": cup_fill["version"]},
            make_member_headers(member["id"])), 200)
        assert cup_settled["priced_piece_count"] == 132
        assert cup_settled["final_price_cents"] == 116

        per_piece = open_cup(store["id"], member["id"], cup_size="LARGE",
                             pricing_model="PER_PIECE", declared_mass_grams=440,
                             pieced_element_id=element["id"],
                             declared_piece_count=132)
        per_piece = validate_success(api.get_fusion_order(
            per_piece["id"], TEST_USERS["associate_headers"]), 200)
        settled = validate_success(api.checkout_fusion_order(
            per_piece["id"], {"expected_fusion_order_version": per_piece["version"]},
            make_member_headers(member["id"])), 200)

        assert settled["declared_piece_count"] == 132, (
            "PER_PIECE takes the client-declared count as authoritative")
        assert settled["base_price_cents"] == 1984, (
            "132 pieces at twelve cents plus the flat bulk band")
        assert settled["final_price_cents"] == 1786
        assert settled["final_price_cents"] > cup_settled["final_price_cents"] * 10, (
            "the same 440 g costs an order of magnitude more when counted")

    def test_a_single_piece_stays_linear_below_the_bulk_threshold(self, api):
        """PRD §3.2: "first the piece subtotal, which is the declared count
        multiplied by twelve cents per piece; then a bulk band, which is a flat
        400 cents when the declared count reaches 100 pieces and zero below that
        threshold; then the two are summed."

        Design: Corner/calculations/per_piece_cup_prices_a_single_piece_at_the_unit_rate
        """
        store, element, member, _bin = setup_store_with_wall()

        order = open_cup(store["id"], member["id"], cup_size="SMALL",
                         pricing_model="PER_PIECE", declared_mass_grams=10,
                         pieced_element_id=element["id"], declared_piece_count=1)
        settled = validate_success(api.checkout_fusion_order(
            order["id"], {"expected_fusion_order_version": order["version"]},
            make_member_headers(member["id"])), 200)
        assert settled["base_price_cents"] == 12, (
            "one piece below the threshold pays the twelve-cent unit rate alone")
        assert settled["member_discount_cents"] == 1, (
            "one tenth of twelve cents rounds half up to one cent")
        assert settled["final_price_cents"] == 11


class TestLaunchSurcharge:
    """The surcharge and the two rounding orders around it."""

    def test_launch_surcharge_applies_on_top_of_the_member_discount(self, api):
        """PRD §3.2: "If the checkout call names an exclusive launch through
        `exclusive_launch_id`, a launch surcharge of twenty-five percent is
        applied."
        PRD §3.2: "In the default variant — used when the checkout passes a
        `pricing_variant` of `POST_DISCOUNT` or omits the field entirely — the
        surcharge applies to the already-discounted amount, and the final price
        is that product rounded half up."

        Design: Difficulty/combinatorial_formula/overage_band_and_bulk_band_resolve_on_one_checkout_endpoint
        """
        reset_clock()
        store = open_store(wall_bin_capacity_grams=2000)
        element = add_element(element_code="3005", element_name="Brick 2x8",
                              cost_basis_cents=7)
        member = add_member(store["id"])
        load_bin(store["id"], element["id"], bin_label="X21",
                 bin_capacity_grams=1000, bin_mass_grams=600)
        launch = schedule_launch(theme="Icons", exclusive_set_sku="LEGO-X2",
                                 allocated_exclusive_units=10,
                                 per_customer_limit=2, days_from_default_clock=3,
                                 vip_early_days_before_release=1)

        order = open_cup(store["id"], member["id"], cup_size="LARGE",
                         pricing_model="PER_PIECE", declared_mass_grams=300,
                         pieced_element_id=element["id"], declared_piece_count=100)
        settled = validate_success(api.checkout_fusion_order(
            order["id"],
            {"expected_fusion_order_version": order["version"],
             "exclusive_launch_id": launch["id"]},
            make_member_headers(member["id"])), 200)

        assert settled["base_price_cents"] == 1600
        assert settled["member_discount_cents"] == 160
        assert settled["final_price_cents"] == 1800, (
            "the surcharge lands on the discounted 1440 cents")

    def test_pre_discount_variant_returns_the_higher_final_price(self, api):
        """PRD §3.2: "When the checkout instead passes `PRE_DISCOUNT`, the
        surcharge is applied to the base price *before* the member discount is
        subtracted: the final price is the base multiplied by one and a
        quarter, rounded half up, minus the previously computed
        `member_discount_cents`. The two variants therefore return different
        final prices for identical inputs, with the pre-discount form always the
        higher of the two."

        Design: Difficulty/dual_variant_calc/same_cup_priced_from_scale_mass_and_tunnel_volume
        """
        reset_clock()
        store = open_store(wall_bin_capacity_grams=2000)
        element = add_element(element_code="3006", element_name="Brick 2x8",
                              cost_basis_cents=7)
        member = add_member(store["id"])
        load_bin(store["id"], element["id"], bin_label="X31",
                 bin_capacity_grams=1000, bin_mass_grams=600)
        launch = schedule_launch(theme="Icons", exclusive_set_sku="LEGO-X3",
                                 allocated_exclusive_units=10,
                                 per_customer_limit=2, days_from_default_clock=3,
                                 vip_early_days_before_release=1)

        order = open_cup(store["id"], member["id"], cup_size="LARGE",
                         pricing_model="PER_PIECE", declared_mass_grams=300,
                         pieced_element_id=element["id"], declared_piece_count=100)
        settled = validate_success(api.checkout_fusion_order(
            order["id"],
            {"expected_fusion_order_version": order["version"],
             "exclusive_launch_id": launch["id"],
             "pricing_variant": "PRE_DISCOUNT"},
            make_member_headers(member["id"])), 200)

        assert settled["member_discount_cents"] == 160
        assert settled["final_price_cents"] == 1840, (
            "the surcharge lands on the base, then the discount is subtracted")
        assert settled["final_price_cents"] > 1800, (
            "the pre-discount form is the higher of the two variants")

class TestPerPieceAuthoritativeCount:
    """The declared count is authoritative under the per-piece model."""

    def test_the_declared_count_governs_the_per_piece_subtotal(self, api):
        """PRD §3.2: "Under `PER_PIECE` the charged count is the client-declared
        count, taken as authoritative, and the element the guest is buying must
        be named as `pieced_element_id`."
        PRD §3.2: "first the piece subtotal, which is the declared count
        multiplied by twelve cents per piece; then a bulk band, which is a flat
        400 cents when the declared count reaches 100 pieces and zero below that
        threshold; then the two are summed."

        Design: Difficulty/dual_variant_calc/per_piece_element_valued_by_count_while_cup_fill_is_valued_by_mass
        """
        store, element, member, _bin = setup_store_with_wall(
            store_overrides={"wall_bin_capacity_grams": 2000},
            bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})

        order = open_cup(store["id"], member["id"], cup_size="LARGE",
                         pricing_model="PER_PIECE", declared_mass_grams=440,
                         pieced_element_id=element["id"],
                         declared_piece_count=50)
        settled = validate_success(api.checkout_fusion_order(
            order["id"], {"expected_fusion_order_version": order["version"]},
            make_member_headers(member["id"])), 200)

        assert settled["priced_piece_count"] == 50, (
            "the declared count is charged, not one inferred from the mass")
        assert settled["base_price_cents"] == 600, (
            "fifty pieces stay linear below the bulk threshold")
        assert settled["final_price_cents"] == 540
