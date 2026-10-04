"""Instant pricing: the spot/contract split, lane geometry, mileage floor, rounding."""
import pytest

from test_helpers import (
    api_client as api,
    create_facility,
    iso3,
    list_load_quotes,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    newest_quote,
    post_load,
    setup_board,
    setup_lock_window_scenario,
    setup_spot_vs_contract_scenario,
)


class TestSpotVersusContract:
    """The two pricing modes must not be conflated."""

    def test_spot_and_contract_loads_post_at_different_locked_prices(self):
        """PRD section 3.3: "Under spot pricing the implied per-mile rate is the
        market level multiplied by the `lane_index`, by the timing-band multiple,
        by the weight-adjustment multiple, and by the commodity multiple, all at
        full precision."
        PRD section 3.3: "Contract pricing is flat and does not scale. When the
        load's `pricing_mode` is `CONTRACT` and it names a valid
        `lane_contract_id`, the load's `base_rate_cents` is the referenced
        contract's `committed_rate_cents`, again subject to the same
        50,000-cent floor."

        Design: Difficulty/dual_variant_calc/quote_price_spot_vs_contract_on_identical_lane
        """
        board = setup_spot_vs_contract_scenario()
        spot = post_load(board["shipper_id"], board["spot_load"]["id"])
        contract = post_load(board["shipper_id"], board["contract_load"]["id"])

        assert spot["posted_rate_cents"] == 372240, (
            f"spot posted rate should be 372240, got {spot['posted_rate_cents']}")
        assert spot["booked_rate_cents"] == 372240
        assert contract["posted_rate_cents"] == 215000, (
            f"contract posted rate should be the flat 215000, got {contract['posted_rate_cents']}")
        assert contract["booked_rate_cents"] == 215000
        assert spot["posted_rate_cents"] != contract["posted_rate_cents"]
        assert spot["lane_key"] == "TX>CA" and contract["lane_key"] == "TX>CA"
        assert spot["status"] == "POSTED" and contract["status"] == "POSTED"

    def test_spot_quote_derives_its_floor_and_per_mile_figure(self):
        """PRD section 3.3: "Whichever variant ran, the quote's `min_rate_cents` is
        struck from the base rate: the base multiplied by eighty-five hundredths,
        rounded half up to the nearest cent."
        PRD section 3.2: "it exposes the derived figure `quoted_cents_per_mile` so
        a carrier can compare lanes at a glance: that is the quote's
        `base_rate_cents` divided by its `effective_miles`, carried to four
        decimal places."

        Design: Difficulty/dual_variant_calc/quote_price_spot_vs_contract_on_identical_lane
        """
        board = setup_spot_vs_contract_scenario()
        post_load(board["shipper_id"], board["spot_load"]["id"])
        post_load(board["shipper_id"], board["contract_load"]["id"])

        spot_quotes = list_load_quotes(board["shipper_id"], board["spot_load"]["id"])
        assert len(spot_quotes) == 1
        spot_quote = spot_quotes[0]
        assert spot_quote["quote_kind"] == "INITIAL"
        assert spot_quote["base_rate_cents"] == 372240
        assert spot_quote["quoted_cents_per_mile"] == pytest.approx(310.2, abs=0.001)
        assert spot_quote["min_rate_cents"] == 316404

        contract_quotes = list_load_quotes(board["shipper_id"], board["contract_load"]["id"])
        assert len(contract_quotes) == 1
        contract_quote = contract_quotes[0]
        assert contract_quote["effective_miles"] == 1200.0
        assert contract_quote["base_rate_cents"] == 215000
        assert contract_quote["min_rate_cents"] == 182750

    def test_late_booking_pays_the_live_surcharged_price_not_the_locked_one(self):
        """PRD section 3.7: "If that age is at most sixty minutes, the booking is
        in its locked window: the `agreed_rate_cents` is exactly the quote price,
        and a reprice that lands afterwards cannot retroactively change this
        booking's number."
        PRD section 3.7: "If the age is strictly more than sixty minutes, the lock
        has lapsed and the price is re-derived live from the load's current
        `market_band` — the band in force at the booking instant, not the band the
        quote was struck at."

        Design: Difficulty/dual_variant_calc/booking_price_locked_within_window_vs_live_surcharged_after
        """
        board = setup_lock_window_scenario()
        live_booking = api.create_booking(
            {
                "load_id": board["live_load"]["id"],
                "carrier_id": board["carrier_id"],
                "rate_quote_id": board["live_quote"]["id"],
                "equipment_id": board["equipment"][1]["id"],
                "expected_load_version": board["live_load"]["version"],
            },
            make_carrier_headers(board["carrier_id"]),
        )
        assert live_booking.status_code == 201, (
            f"expected 201 from the late booking, got {live_booking.status_code} {live_booking.text}")
        live_data = live_booking.json()["data"]

        assert board["locked_booking"]["agreed_rate_cents"] == 106297, (
            "a booking inside the lock window books at exactly the quote price")
        # The live base re-derives from the load's unchanged BALANCED band, so
        # the surplus is exactly the five percent late-booking surcharge.
        assert live_data["agreed_rate_cents"] == 111612, (
            "a booking past the lock window books at the live surcharged price")
        assert live_data["agreed_rate_cents"] != board["locked_booking"]["agreed_rate_cents"]

    def test_locked_booking_ignores_a_reprice_that_lands_afterwards(self):
        """PRD section 3.7: "If that age is at most sixty minutes, the booking is
        in its locked window: the `agreed_rate_cents` is exactly the quote price,
        and a reprice that lands afterwards cannot retroactively change this
        booking's number."
        PRD section 3.7: "Crucially, the load's `posted_rate_cents` is never
        touched: it is the immutable record of the quote struck when the load was
        first posted, and after a single reprice the two figures diverge."

        Design: Difficulty/dual_variant_calc/booking_price_locked_within_window_vs_live_surcharged_after
        """
        board = setup_lock_window_scenario()
        assert board["locked_booking"]["booked_at"] == iso3("2026-10-05T01:00:00Z")
        assert board["locked_booking"]["agreed_rate_cents"] == 106297

        locked_quote = api.get_rate_quote(
            board["locked_quote"]["id"], make_shipper_headers(board["shipper_id"]))
        assert locked_quote.status_code == 200
        quote_data = locked_quote.json()["data"]
        assert quote_data["base_rate_cents"] == 106297
        assert quote_data["repriced_rate_cents"] is None

        # Repricing the still-posted sibling load must not move the locked booking.
        repriced = api.reprice_load(board["live_load"]["id"], "TIGHT",
                                    make_platform_admin_headers())
        assert repriced.status_code == 200
        rebooked = api.get_booking(board["locked_booking"]["id"],
                                   make_carrier_headers(board["carrier_id"]))
        assert rebooked.json()["data"]["agreed_rate_cents"] == 106297


class TestLaneGeometry:
    """lane_index is a pure function of the two state codes."""

    def test_lane_index_differs_between_txca_and_txga(self):
        """PRD section 3.3: "A Texas-to-California lane, `TX>CA`, produces a raw
        total of 48 and a `lane_index` of 1.2000.  The index is a pure function of
        the two state codes; no identifier, entity, or timestamp participates in
        it."

        Design: Corner/calculations/lane_index_is_a_pure_function_of_the_two_state_codes
        """
        board = setup_board(units=1)
        ga_facility = create_facility("GA")
        ca_load, ca_quote = _post(board, board["destination_facility_id"])
        ga_load, ga_quote = _post(board, ga_facility["id"])

        assert ca_load["lane_key"] == "TX>CA"
        assert ga_load["lane_key"] == "TX>GA"
        assert ca_load["posted_rate_cents"] == 279180, (
            f"TX>CA 900-mile lane should price at 279180, got {ca_load['posted_rate_cents']}")
        assert ga_load["posted_rate_cents"] == 325710, (
            f"TX>GA 900-mile lane should price at 325710, got {ga_load['posted_rate_cents']}")
        assert ga_load["posted_rate_cents"] != ca_load["posted_rate_cents"]

    def test_lane_key_filter_selects_only_the_matching_lane(self):
        """PRD section 3.2: "Both facilities must exist and the destination must be
        a different state in practice if the lane is to be distinct."

        Design: Corner/calculations/lane_index_is_a_pure_function_of_the_two_state_codes
        """
        board = setup_board(units=1)
        ga_facility = create_facility("GA")
        _post(board, board["destination_facility_id"])
        _post(board, ga_facility["id"])

        tx_ca = api.list_loads(make_shipper_headers(board["shipper_id"]),
                               {"lane_key": "TX>CA"})
        assert tx_ca.status_code == 200
        assert len(tx_ca.json()["data"]) == 1
        assert tx_ca.json()["data"][0]["lane_key"] == "TX>CA"

    def test_short_haul_is_priced_over_the_fifty_mile_floor(self):
        """PRD section 3.3: "Mileage enters through `effective_miles`, which is the
        load's `distance_miles`, except that any figure below 50 miles is raised to
        50.  Short hauls therefore price as if they were fifty miles long."

        Design: Corner/calculations/minimum_mileage_floor_raises_a_short_haul_to_fifty_effective_miles
        """
        board = setup_board(units=1)
        load = _post(board, board["destination_facility_id"], distance_miles=30)[0]
        quote = newest_quote(board["shipper_id"], load["id"])

        assert quote["effective_miles"] == 50.0
        assert quote["effective_miles"] != 30.0
        # 50 effective miles at the BALANCED dry-van implied rate prices at
        # 15,510 cents, below the 50,000-cent floor, so the floor is the base.
        assert quote["base_rate_cents"] == 50000
        assert load["posted_rate_cents"] == 50000
        assert quote["min_rate_cents"] == 42500

    def test_money_is_rounded_once_to_the_cent_on_a_reefer_haul(self):
        """PRD section 2.4: "Internal arithmetic is performed on the full-precision
        intermediate values and only the final stored figure is rounded."

        Design: Corner/calculations/rounded_money_is_exact_to_the_cent_on_a_395_mile_reefer_haul
        """
        board = setup_board(units=1, equipment_type="REEFER",
                            carrier_overrides={"equipment_types": ["REEFER"]})
        load = _post(board, board["destination_facility_id"], equipment_type="REEFER",
                     commodity="TEMPERATURE_CONTROLLED", weight_lbs=45000,
                     distance_miles=395)[0]
        quotes = list_load_quotes(board["shipper_id"], load["id"])

        assert load["posted_rate_cents"] == 176016, (
            f"the 395-mile reefer haul should price at exactly 176016, got {load['posted_rate_cents']}")
        assert load["posted_rate_cents"] != 176015
        assert len(quotes) == 1
        assert quotes[0]["base_rate_cents"] == 176016
        assert quotes[0]["quoted_cents_per_mile"] == pytest.approx(445.61, abs=0.01)
        assert quotes[0]["effective_miles"] == 395.0


def _post(board, destination_facility_id, **overrides):
    kwargs = dict(distance_miles=900)
    kwargs.update(overrides)
    load = api.create_load(
        {
            "shipper_id": board["shipper_id"],
            "origin_facility_id": board["origin_facility_id"],
            "destination_facility_id": destination_facility_id,
            "pricing_mode": "SPOT",
            "equipment_type": overrides.get("equipment_type", "DRY_VAN"),
            "commodity": overrides.get("commodity", "GENERAL"),
            "weight_lbs": overrides.get("weight_lbs", 40000),
            "declared_cargo_value_cents": 5000000,
            "distance_miles": kwargs["distance_miles"],
            "pickup_window_start": overrides.get("pickup_window_start", "2026-10-05T08:00:00Z"),
            "pickup_window_end": "2026-10-05T12:00:00Z",
            "delivery_deadline": "2026-10-07T18:00:00Z",
            "market_band": "BALANCED",
        },
        make_shipper_headers(board["shipper_id"]),
    )
    assert load.status_code == 201, f"setup failed: {load.status_code} {load.text}"
    load_id = load.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"]))
    assert posted.status_code == 200, f"setup failed: {posted.status_code} {posted.text}"
    return posted.json()["data"], newest_quote(board["shipper_id"], load_id)