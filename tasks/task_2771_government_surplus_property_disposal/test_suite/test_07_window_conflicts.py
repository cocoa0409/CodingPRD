"""Two window-conflict geometries at auction lot creation.

The venue capacity rule and the asset relist cooldown are checked one after the
other against the same `opens_at`, but they disagree about the boundary instant.
The venue rule is half-open, so a lot opening at the exact instant another closes
does not intersect it; the cooldown rule is closed and carries a mandatory
twenty-four hour buffer, so the very adjacency the venue rule permits is a
violation there. These tests pin the boundary in both directions and check the
hosting venue's roll-up counter after every accepted write.
"""

import pytest

from test_helpers import (
    OFFICER_USER_ID,
    ApiErrorId,
    assert_auction_lot,
    assert_sale_venue,
    assert_surplus_asset,
    create_auction_lot_payload,
    make_disposal_officer_headers,
    read_asset,
    read_venue,
    register_venue,
    setup_assessed_assets,
    setup_closed_no_sale_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER_HEADERS = make_disposal_officer_headers(OFFICER_USER_ID)

# A 2024 furniture pallet appraised C6 / functional with no repair estimate is
# worth 12540 cents, below the de-minimis screening threshold, so every asset in
# these scenarios is listable straight out of ASSESSED.
FURNITURE_FMV_CENTS = 12540
FURNITURE_RESERVE_CENTS = 7524


def _four_pallets_and_a_two_lot_venue():
    """One accepted turn-in holding four separately listable pallets, plus a venue
    that admits two concurrent lots."""
    scenario = setup_assessed_assets(
        [
            {"kind": "furniture", "overrides": {"description": f"File cabinets, pallet {n}"}}
            for n in range(1, 5)
        ]
    )
    scenario["venue"] = register_venue(
        name="Austin Surplus Yard", venue_code="AUS-01", concurrent_lot_capacity=2
    )
    return scenario


class TestVenueAggregateCapacityOverHalfOpenWindows:
    """Capacity is an aggregate count of intersecting live windows at one venue,
    and the intersection test is strict at both ends."""

    def _fill_the_venue_to_capacity(self, api, scenario):
        """Two overlapping lots, which is exactly the venue's capacity."""
        venue = scenario["venue"]
        assert venue["concurrent_lot_capacity"] == 2
        assert venue["active_lot_count"] == 0, (
            f"a brand-new venue hosts no live lot, got {venue['active_lot_count']}"
        )

        first = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    scenario["assets"][0]["id"],
                    venue["id"],
                    opens_at="2026-09-01T00:00:00Z",
                    closes_at="2026-09-05T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert first["lot_number"] == "AUS-01-0001", (
            f"the first lot at this venue is position one, got {first['lot_number']}"
        )
        assert read_venue(venue["id"])["active_lot_count"] == 1, (
            "the venue counts one DRAFT lot after the first accepted write"
        )

        second = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    scenario["assets"][1]["id"],
                    venue["id"],
                    opens_at="2026-09-03T00:00:00Z",
                    closes_at="2026-09-07T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert second["lot_number"] == "AUS-01-0002", (
            f"the second lot at this venue is position two, got {second['lot_number']}"
        )
        assert read_venue(venue["id"])["active_lot_count"] == 2, (
            "the venue counts two DRAFT lots, which is its full capacity"
        )
        return first, second

    def test_third_lot_intersecting_both_live_windows_is_refused(self, api):
        """PRD §3.6: "The first is a **venue capacity** rule over half-open windows.
        Consider the lots at the same venue whose `status` is `DRAFT` or `OPEN`; two
        windows are treated as intersecting when the new lot's `opens_at` falls strictly
        before the other's `closes_at` and the other's `opens_at` falls strictly before the
        new lot's `closes_at`. Windows that merely touch — a new lot opening at the exact
        instant another closes — do not intersect. If the number of intersecting lots is
        greater than or equal to the venue's `concurrent_lot_capacity`, the creation is
        refused with `ERR_VENUE_CAPACITY_CONFLICT`."
        PRD §3.6: "Creation also recomputes the hosting venue's `active_lot_count`, which
        counts that venue's lots in `DRAFT` or `OPEN`, and increments the asset's
        `version` by 1."

        Design: Difficulty/resource_temporal_overlap/rto_venue_aggregate_capacity_half_open_adjacency_allowed
        """
        scenario = _four_pallets_and_a_two_lot_venue()
        venue = scenario["venue"]
        self._fill_the_venue_to_capacity(api, scenario)

        third_asset = scenario["assets"][2]
        asset_version_before = read_asset(third_asset["id"])["version"]

        resp = api.create_auction_lot(
            create_auction_lot_payload(
                third_asset["id"],
                venue["id"],
                opens_at="2026-09-04T00:00:00Z",
                closes_at="2026-09-06T00:00:00Z",
            ),
            OFFICER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_CONFLICT)

        after = read_venue(venue["id"])
        assert_sale_venue(after)
        assert after["active_lot_count"] == 2, (
            "the refused create writes nothing, so the roll-up still counts two live "
            f"lots; got {after['active_lot_count']}"
        )
        rejected_asset = read_asset(third_asset["id"])
        assert_surplus_asset(rejected_asset)
        assert rejected_asset["disposition_status"] == "ASSESSED", (
            "the third pallet was never listed; got "
            f"{rejected_asset['disposition_status']}"
        )
        assert rejected_asset["version"] == asset_version_before, (
            "no hop of the refused create may touch the asset"
        )
        _, meta = validate_paginated(
            api.list_auction_lots(OFFICER_HEADERS, params={"venue_id": venue["id"]})
        )
        assert meta["total_count"] == 2, (
            f"only the two accepted lots exist at this venue; got {meta['total_count']}"
        )

    def test_one_second_before_the_boundary_still_intersects_and_is_refused(self, api):
        """PRD §3.6: "The first is a **venue capacity** rule over half-open windows.
        Consider the lots at the same venue whose `status` is `DRAFT` or `OPEN`; two
        windows are treated as intersecting when the new lot's `opens_at` falls strictly
        before the other's `closes_at` and the other's `opens_at` falls strictly before the
        new lot's `closes_at`. Windows that merely touch — a new lot opening at the exact
        instant another closes — do not intersect. If the number of intersecting lots is
        greater than or equal to the venue's `concurrent_lot_capacity`, the creation is
        refused with `ERR_VENUE_CAPACITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/rto_venue_aggregate_capacity_half_open_adjacency_allowed
        """
        scenario = _four_pallets_and_a_two_lot_venue()
        venue = scenario["venue"]
        self._fill_the_venue_to_capacity(api, scenario)

        # One second inside the first lot's window still counts it as intersecting,
        # which together with the second lot reaches the capacity of two.
        resp = api.create_auction_lot(
            create_auction_lot_payload(
                scenario["assets"][2]["id"],
                venue["id"],
                opens_at="2026-09-04T23:59:59Z",
                closes_at="2026-09-08T00:00:00Z",
            ),
            OFFICER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_CONFLICT)
        assert read_venue(venue["id"])["active_lot_count"] == 2, (
            "the refused create leaves the roll-up at two"
        )

    @pytest.mark.parametrize(
        ("opens_at", "closes_at", "touched"),
        [
            ("2026-09-05T00:00:00Z", "2026-09-08T00:00:00Z", "the first lot's closes_at"),
            ("2026-09-07T00:00:00Z", "2026-09-10T00:00:00Z", "the second lot's closes_at"),
        ],
    )
    def test_lot_opening_at_the_instant_another_closes_is_admitted(
        self, api, opens_at, closes_at, touched
    ):
        """PRD §3.6: "The first is a **venue capacity** rule over half-open windows.
        Consider the lots at the same venue whose `status` is `DRAFT` or `OPEN`; two
        windows are treated as intersecting when the new lot's `opens_at` falls strictly
        before the other's `closes_at` and the other's `opens_at` falls strictly before the
        new lot's `closes_at`. Windows that merely touch — a new lot opening at the exact
        instant another closes — do not intersect. If the number of intersecting lots is
        greater than or equal to the venue's `concurrent_lot_capacity`, the creation is
        refused with `ERR_VENUE_CAPACITY_CONFLICT`."
        PRD §3.6: "Every lot gets a human-readable `lot_number` assembled as the venue's
        `venue_code`, a hyphen, and the lot's one-based position among all lots at that
        venue ordered by `created_at` ascending, with the position zero-padded to four
        digits — the third lot ever created at a venue coded `NORTHYARD` is therefore
        `NORTHYARD-0003`."
        PRD §3.6: "Creation also recomputes the hosting venue's `active_lot_count`, which
        counts that venue's lots in `DRAFT` or `OPEN`, and increments the asset's
        `version` by 1."

        Design: Difficulty/resource_temporal_overlap/rto_venue_aggregate_capacity_half_open_adjacency_allowed
        """
        scenario = _four_pallets_and_a_two_lot_venue()
        venue = scenario["venue"]
        self._fill_the_venue_to_capacity(api, scenario)

        third_asset = scenario["assets"][2]
        asset_version_before = read_asset(third_asset["id"])["version"]

        lot = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    third_asset["id"], venue["id"],
                    opens_at=opens_at, closes_at=closes_at,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert_auction_lot(lot)
        assert lot["status"] == "DRAFT", (
            f"a window that merely touches {touched} is admitted, got {lot['status']}"
        )
        assert lot["opens_at"].startswith(opens_at[:19]), (
            f"the lot must store the requested opens_at, got {lot['opens_at']}"
        )
        assert lot["lot_number"] == "AUS-01-0003", (
            "this is the third lot ever created at AUS-01, and the earlier refusals "
            f"consumed no position; got {lot['lot_number']}"
        )
        assert lot["reserve_price_cents"] == FURNITURE_RESERVE_CENTS, (
            f"the computed reserve is 7524 cents, got {lot['reserve_price_cents']}"
        )

        after = read_venue(venue["id"])
        assert after["active_lot_count"] == 3, (
            "the roll-up counts every DRAFT or OPEN lot at the venue regardless of "
            f"whether their windows overlap; got {after['active_lot_count']}"
        )
        listed = read_asset(third_asset["id"])
        assert listed["disposition_status"] == "LISTED", (
            f"the accepted lot lists its asset, got {listed['disposition_status']}"
        )
        assert listed["version"] == asset_version_before + 1, (
            "lot creation increments the asset's version by exactly 1"
        )


class TestAssetRelistCooldownOverClosedWindows:
    """The cooldown is a closed interval with a twenty-four hour buffer, so the
    boundary instant is admissible but everything before it — including the bare
    adjacency the venue rule allows — is not."""

    def _unsold_lot(self):
        """A furniture pallet whose first lot closed unsold, leaving the asset
        `AUCTION_ELIGIBLE` and the clock at that lot's `closes_at`."""
        scenario = setup_closed_no_sale_lot(
            kind="furniture",
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-09-05T00:00:00Z",
            venue_overrides={
                "name": "Austin Surplus Yard",
                "venue_code": "AUS-01",
                "concurrent_lot_capacity": 2,
            },
        )
        assert scenario["lot"]["status"] == "CLOSED_NO_SALE", (
            f"the first lot must close unsold, got {scenario['lot']['status']}"
        )
        assert scenario["asset"]["disposition_status"] == "AUCTION_ELIGIBLE", (
            "an unsold lot returns its asset to AUCTION_ELIGIBLE; got "
            f"{scenario['asset']['disposition_status']}"
        )
        assert read_venue(scenario["venue"]["id"])["active_lot_count"] == 0, (
            "a CLOSED_NO_SALE lot is neither DRAFT nor OPEN, so it leaves the roll-up"
        )
        return scenario

    @pytest.mark.parametrize(
        "opens_at",
        [
            # Bare adjacency, which the venue capacity rule would have permitted.
            pytest.param("2026-09-05T00:00:00Z", id="bare_adjacency"),
            # One second short of the twenty-four hour buffer.
            pytest.param("2026-09-05T23:59:59Z", id="one_second_early"),
        ],
    )
    def test_relist_before_the_cooldown_boundary_is_refused(self, api, opens_at):
        """PRD §3.6: "The second is an **asset cooldown** rule over closed windows with a
        mandatory buffer, and its capacity is always one rather than a configured number.
        Consider every lot ever created for the same asset whose `status` is `DRAFT`,
        `OPEN`, `CLOSED_MET`, `CLOSED_NO_SALE` or `SETTLED` — that is, every lot except the
        cancelled ones. The new lot's `opens_at` must be at or after the latest of those
        lots' `closes_at` plus a twenty-four hour relist cooldown. Equality passes: opening
        exactly one day after the previous close is fine, one second earlier is not, and
        adjacency that the venue rule permits is forbidden here. A violation is refused
        with `ERR_ASSET_WINDOW_CONFLICT`."
        PRD §3.7: "**When the candidate set is empty** — no bids at all, or every bid below
        reserve — the lot closes at `CLOSED_NO_SALE`. `closed_by_user_id` and `closed_at`
        are still stamped, no invoice is created, and the asset moves `disposition_status`
        `LISTED` → `AUCTION_ELIGIBLE` so it can be listed again once the relist cooldown
        has elapsed."

        Design: Difficulty/resource_temporal_overlap/rto_asset_relist_cooldown_closed_interval_adjacency_forbidden
        """
        scenario = self._unsold_lot()
        asset = scenario["asset"]
        venue = scenario["venue"]
        asset_version_before = asset["version"]

        resp = api.create_auction_lot(
            create_auction_lot_payload(
                asset["id"], venue["id"],
                opens_at=opens_at, closes_at="2026-09-10T00:00:00Z",
            ),
            OFFICER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_WINDOW_CONFLICT)

        after_asset = read_asset(asset["id"])
        assert after_asset["disposition_status"] == "AUCTION_ELIGIBLE", (
            "the refused relist leaves the asset AUCTION_ELIGIBLE; got "
            f"{after_asset['disposition_status']}"
        )
        assert after_asset["version"] == asset_version_before, (
            "the refused create applies none of its hops, so the asset's version stays "
            f"at {asset_version_before}; got {after_asset['version']}"
        )
        assert read_venue(venue["id"])["active_lot_count"] == 0, (
            "no lot was created, so the venue still hosts no live lot"
        )
        _, meta = validate_paginated(
            api.list_auction_lots(OFFICER_HEADERS, params={"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the original unsold lot exists for this asset; got {meta['total_count']}"
        )

    def test_relist_exactly_one_day_after_the_previous_close_is_admitted(self, api):
        """PRD §3.6: "The second is an **asset cooldown** rule over closed windows with a
        mandatory buffer, and its capacity is always one rather than a configured number.
        Consider every lot ever created for the same asset whose `status` is `DRAFT`,
        `OPEN`, `CLOSED_MET`, `CLOSED_NO_SALE` or `SETTLED` — that is, every lot except the
        cancelled ones. The new lot's `opens_at` must be at or after the latest of those
        lots' `closes_at` plus a twenty-four hour relist cooldown. Equality passes: opening
        exactly one day after the previous close is fine, one second earlier is not, and
        adjacency that the venue rule permits is forbidden here. A violation is refused
        with `ERR_ASSET_WINDOW_CONFLICT`."
        PRD §3.6: "Every lot gets a human-readable `lot_number` assembled as the venue's
        `venue_code`, a hyphen, and the lot's one-based position among all lots at that
        venue ordered by `created_at` ascending, with the position zero-padded to four
        digits — the third lot ever created at a venue coded `NORTHYARD` is therefore
        `NORTHYARD-0003`."
        PRD §3.6: "Creation also recomputes the hosting venue's `active_lot_count`, which
        counts that venue's lots in `DRAFT` or `OPEN`, and increments the asset's
        `version` by 1."

        Design: Difficulty/resource_temporal_overlap/rto_asset_relist_cooldown_closed_interval_adjacency_forbidden
        """
        scenario = self._unsold_lot()
        asset = scenario["asset"]
        venue = scenario["venue"]
        asset_version_before = asset["version"]

        validate_error(
            api.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"], venue["id"],
                    opens_at="2026-09-05T23:59:59Z",
                    closes_at="2026-09-10T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_ASSET_WINDOW_CONFLICT,
        )

        relist = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"], venue["id"],
                    opens_at="2026-09-06T00:00:00Z",
                    closes_at="2026-09-10T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert_auction_lot(relist)
        assert relist["status"] == "DRAFT", (
            "the boundary instant is admissible because the cooldown window is closed "
            f"on the equality; got {relist['status']}"
        )
        assert relist["opens_at"].startswith("2026-09-06T00:00:00"), (
            "the relist opens exactly twenty-four hours after the previous close; got "
            f"{relist['opens_at']}"
        )
        assert relist["lot_number"] == "AUS-01-0002", (
            "this is the second lot ever created at AUS-01 and the refused attempt "
            f"consumed no position; got {relist['lot_number']}"
        )
        assert relist["reserve_price_cents"] == FURNITURE_RESERVE_CENTS, (
            "the reserve is recomputed from the unchanged valuation of 12540 cents; got "
            f"{relist['reserve_price_cents']}"
        )
        assert relist["high_bid_cents"] == 0, (
            "the relist carries no bidding history from the unsold lot"
        )
        assert relist["bid_count"] == 0

        after_venue = read_venue(venue["id"])
        assert after_venue["active_lot_count"] == 1, (
            "the accepted relist is the venue's only DRAFT or OPEN lot; got "
            f"{after_venue['active_lot_count']}"
        )
        relisted_asset = read_asset(asset["id"])
        assert relisted_asset["disposition_status"] == "LISTED", (
            "the accepted relist moves the asset AUCTION_ELIGIBLE to LISTED; got "
            f"{relisted_asset['disposition_status']}"
        )
        assert relisted_asset["fair_market_value_cents"] == FURNITURE_FMV_CENTS, (
            "relisting does not revalue the property"
        )
        assert relisted_asset["version"] == asset_version_before + 1, (
            "only the accepted create increments the asset's version, and by exactly 1"
        )

    def test_a_lot_at_a_different_venue_is_still_bound_by_the_asset_cooldown(self, api):
        """PRD §3.6: "The second is an **asset cooldown** rule over closed windows with a
        mandatory buffer, and its capacity is always one rather than a configured number.
        Consider every lot ever created for the same asset whose `status` is `DRAFT`,
        `OPEN`, `CLOSED_MET`, `CLOSED_NO_SALE` or `SETTLED` — that is, every lot except the
        cancelled ones. The new lot's `opens_at` must be at or after the latest of those
        lots' `closes_at` plus a twenty-four hour relist cooldown. Equality passes: opening
        exactly one day after the previous close is fine, one second earlier is not, and
        adjacency that the venue rule permits is forbidden here. A violation is refused
        with `ERR_ASSET_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/rto_asset_relist_cooldown_closed_interval_adjacency_forbidden
        """
        scenario = self._unsold_lot()
        asset = scenario["asset"]
        other_venue = register_venue(
            name="Round Rock Surplus Annex",
            venue_code="AUS-02",
            concurrent_lot_capacity=4,
        )

        # The cooldown looks at every lot ever created for the same asset, without
        # regard to which venue hosted it, so an empty second venue is no escape.
        validate_error(
            api.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"], other_venue["id"],
                    opens_at="2026-09-05T00:00:00Z",
                    closes_at="2026-09-10T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_ASSET_WINDOW_CONFLICT,
        )
        assert read_venue(other_venue["id"])["active_lot_count"] == 0, (
            "the second venue hosts nothing after the refusal"
        )

        relist = validate_success(
            api.create_auction_lot(
                create_auction_lot_payload(
                    asset["id"], other_venue["id"],
                    opens_at="2026-09-06T00:00:00Z",
                    closes_at="2026-09-10T00:00:00Z",
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert relist["venue_id"] == other_venue["id"]
        assert relist["lot_number"] == "AUS-02-0001", (
            "lot positions are counted per venue, so the first lot at AUS-02 is "
            f"position one; got {relist['lot_number']}"
        )
        assert read_venue(other_venue["id"])["active_lot_count"] == 1, (
            "the accepted relist is the second venue's only live lot"
        )
        assert read_venue(scenario["venue"]["id"])["active_lot_count"] == 0, (
            "the original venue's roll-up counts only its own lots, and its unsold lot "
            "is neither DRAFT nor OPEN"
        )
