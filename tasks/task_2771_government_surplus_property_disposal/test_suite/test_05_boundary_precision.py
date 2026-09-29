"""Boundary precision: the exact threshold, one step below and one step above.

Several of the PRD's thresholds are normative rather than incidental — a reserve
of exactly five thousand dollars does require a deposit, an advance at exactly
`tier_deadline_at` is permitted while one second earlier is not, and disposal on
the federal use period's end date is permitted while one day earlier is not.
Each test here drives the same call on both sides of one such threshold and at
the threshold itself.
"""

from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    assert_auction_lot,
    assert_screening_cycle,
    assert_screening_request,
    assert_surplus_asset,
    advance_tier,
    create_screening_cycle_payload,
    create_screening_request_payload,
    make_agency_officer_headers,
    make_disposal_officer_headers,
    open_screening_cycle,
    read_asset,
    read_cycle,
    read_request,
    read_venue,
    register_local_government,
    register_venue,
    create_lot,
    file_screening_request,
    set_clock,
    setup_assessed_asset,
    setup_assessed_assets,
    setup_listed_lot,
    validate_error,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse one of the PRD's ISO 8601 UTC instants for exact comparison."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── The deposit threshold at a reserve of exactly 500000 ─────────────────

_LOT_WINDOW = {"opens_at": "2026-09-01T00:00:00Z", "closes_at": "2026-09-05T00:00:00Z"}


def _two_auction_eligible_furniture_assets() -> dict:
    """Two FURNITURE assets whose acquisition costs straddle the reserve that
    lands exactly on the deposit threshold, both carried through the whole
    screening ladder so each is listable outright.

    A cost of 833333 and a cost of 833332 are one cent apart, are both above the
    de-minimis screening threshold, and at a C1 condition with no repair estimate
    and less than a year of age they carry straight through to fair market value.
    """
    scenario = setup_assessed_assets(
        [
            {
                "kind": "furniture",
                "overrides": {
                    "description": "Executive conference table, twenty foot",
                    "acquisition_cost_cents": 833333,
                    "acquisition_date": "2026-01-10",
                },
                "assessment": {
                    "condition_code": "C1",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-31",
                },
            },
            {
                "kind": "furniture",
                "overrides": {
                    "description": "Executive credenza run, twenty foot",
                    "acquisition_cost_cents": 833332,
                    "acquisition_date": "2026-01-10",
                },
                "assessment": {
                    "condition_code": "C1",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-07-31",
                },
            },
        ]
    )
    for asset in scenario["assets"]:
        cycle = open_screening_cycle(
            asset["id"], opens_at="2026-08-01T00:00:00Z", tier_window_days=3
        )
        advance_tier(cycle["id"], 4)
    scenario["assets"] = [read_asset(a["id"]) for a in scenario["assets"]]
    return scenario


class TestAuctionDepositThreshold:
    """A reserve of exactly 500000 requires a 50000-cent deposit; 499999 requires
    none."""

    def test_computed_reserve_straddling_the_threshold_sets_the_deposit(self, api):
        """PRD §3.6: "By default the reserve is derived from the asset's stored valuation: take sixty hundredths of `fair_market_value_cents`, round that product half up to whole cents, and use the larger of that figure and twenty-five dollars."
        PRD §3.6: "The lot's `required_deposit_cents` is evaluated exactly once, at lot creation, against whichever `reserve_price_cents` was stored — computed or overridden alike."
        PRD §3.6: "A reserve below five thousand dollars requires no deposit at all and `required_deposit_cents` is 0."
        PRD §3.6: "A reserve of five thousand dollars **or more** requires a deposit of ten hundredths of the reserve, rounded half up to whole cents, but never less than five hundred dollars."
        PRD §3.6: "The comparison is inclusive on the requiring side: a reserve of exactly five thousand dollars does require a deposit."
        PRD §3.3: "Multiply `acquisition_cost_cents` by the condition factor, the age factor and the functional factor, and round that single product half up to whole cents."
        PRD §3.6: "Every lot gets a human-readable `lot_number` assembled as the venue's `venue_code`, a hyphen, and the lot's one-based position among all lots at that venue ordered by `created_at` ascending, with the position zero-padded to four digits — the third lot ever created at a venue coded `NORTHYARD` is therefore `NORTHYARD-0003`."
        PRD §3.6: "Creation also recomputes the hosting venue's `active_lot_count`, which counts that venue's lots in `DRAFT` or `OPEN`, and increments the asset's `version` by 1."
        PRD §3.6: "An asset in `AUCTION_ELIGIBLE` — one that walked the whole screening ladder to exhaustion, or that came back from an unsold lot or a debarred buyer — is listable outright, moving `AUCTION_ELIGIBLE` → `LISTED`."

        Design: Difficulty/boundary_precision_check/bpc_deposit_threshold_at_exactly_500000_reserve
        """
        scenario = _two_auction_eligible_furniture_assets()
        asset_high, asset_low = scenario["assets"]

        assert asset_high["fair_market_value_cents"] == 833333, (
            "an unworn C1 asset under a year old keeps its acquisition cost, got "
            f"{asset_high['fair_market_value_cents']}"
        )
        assert asset_low["fair_market_value_cents"] == 833332, (
            f"expected 833332, got {asset_low['fair_market_value_cents']}"
        )
        for asset in (asset_high, asset_low):
            assert asset["disposition_status"] == "AUCTION_ELIGIBLE", (
                "an exhausted screening ladder leaves the asset listable, got "
                f"{asset['disposition_status']}"
            )

        venue = register_venue()
        lot_high = create_lot(asset_high["id"], venue["id"], **_LOT_WINDOW)
        lot_low = create_lot(asset_low["id"], venue["id"], **_LOT_WINDOW)

        assert_auction_lot(lot_high)
        assert_auction_lot(lot_low)

        assert lot_high["reserve_price_cents"] == 500000, (
            "sixty hundredths of 833333 is 499999.8, which rounds half up to "
            f"500000; got {lot_high['reserve_price_cents']}"
        )
        assert lot_high["reserve_source"] == "COMPUTED", (
            f"no reserve was supplied, got {lot_high['reserve_source']}"
        )
        assert lot_high["required_deposit_cents"] == 50000, (
            "a reserve of exactly five thousand dollars does require a deposit, "
            "and ten hundredths of 500000 is 50000, which is exactly the five "
            f"hundred dollar floor; got {lot_high['required_deposit_cents']}"
        )

        assert lot_low["reserve_price_cents"] == 499999, (
            "sixty hundredths of 833332 is 499999.2, which rounds half up to "
            f"499999; got {lot_low['reserve_price_cents']}"
        )
        assert lot_low["reserve_source"] == "COMPUTED", (
            f"no reserve was supplied, got {lot_low['reserve_source']}"
        )
        assert lot_low["required_deposit_cents"] == 0, (
            "one cent below the threshold requires no deposit at all, got "
            f"{lot_low['required_deposit_cents']}"
        )

        assert lot_high["lot_number"] == "AUS-01-0001", (
            f"the first lot at this venue, got {lot_high['lot_number']}"
        )
        assert lot_low["lot_number"] == "AUS-01-0002", (
            f"the second lot at this venue, got {lot_low['lot_number']}"
        )
        assert read_venue(venue["id"])["active_lot_count"] == 2, (
            "both DRAFT lots count towards the venue's active lot count"
        )
        for asset in (asset_high, asset_low):
            relisted = read_asset(asset["id"])
            assert_surplus_asset(relisted)
            assert relisted["disposition_status"] == "LISTED", (
                f"listing moves the asset to LISTED, got {relisted['disposition_status']}"
            )
            assert relisted["version"] == asset["version"] + 1, (
                "listing increments the asset's version by exactly 1, from "
                f"{asset['version']}; got {relisted['version']}"
            )

    @pytest.mark.parametrize(
        "reserve_cents, expected_deposit_cents, note",
        [
            (499999, 0, "one cent below the threshold"),
            (500000, 50000, "exactly on the threshold"),
            (500001, 50000, "one cent above the threshold"),
        ],
    )
    def test_overridden_reserve_at_the_deposit_threshold(
        self, api, reserve_cents, expected_deposit_cents, note
    ):
        """PRD §3.6: "The lot's `required_deposit_cents` is evaluated exactly once, at lot creation, against whichever `reserve_price_cents` was stored — computed or overridden alike."
        PRD §3.6: "A reserve below five thousand dollars requires no deposit at all and `required_deposit_cents` is 0."
        PRD §3.6: "A reserve of five thousand dollars **or more** requires a deposit of ten hundredths of the reserve, rounded half up to whole cents, but never less than five hundred dollars."
        PRD §3.6: "The comparison is inclusive on the requiring side: a reserve of exactly five thousand dollars does require a deposit."
        PRD §3.6: "Where the `DisposalOfficer` supplies a `reserve_price_cents` in the request, that value is stored verbatim without any formula being applied, and the lot records `reserve_source` as `OFFICER_OVERRIDE`; where the officer supplies nothing, the computed figure is stored and `reserve_source` is `COMPUTED`."

        Design: Difficulty/boundary_precision_check/bpc_deposit_threshold_at_exactly_500000_reserve
        """
        scenario = setup_listed_lot(
            lot_overrides={"reserve_price_cents": reserve_cents}
        )
        lot = scenario["lot"]

        assert lot["reserve_price_cents"] == reserve_cents, (
            f"the officer's figure is stored verbatim ({note}), got "
            f"{lot['reserve_price_cents']}"
        )
        assert lot["reserve_source"] == "OFFICER_OVERRIDE", (
            f"an overridden reserve records its source, got {lot['reserve_source']}"
        )
        assert lot["required_deposit_cents"] == expected_deposit_cents, (
            f"a reserve of {reserve_cents} ({note}) requires "
            f"{expected_deposit_cents}, got {lot['required_deposit_cents']}"
        )


# ─── The tier window closing instant ──────────────────────────────────────


def _open_cycle_with_a_local_government_waiting() -> dict:
    """A freshly opened cycle whose every tier window is five whole days long,
    plus a registered local government ready to file into the second tier."""
    scenario = setup_assessed_asset(kind="vehicle")
    recipient = register_local_government()
    cycle = open_screening_cycle(
        scenario["asset"]["id"],
        opens_at="2026-08-01T00:00:00Z",
        tier_window_days=5,
    )
    scenario["recipient"] = recipient
    scenario["cycle"] = cycle
    return scenario


class TestScreeningTierAdvanceBoundary:
    """`tier_deadline_at` is five whole days after the epoch, so the same advance
    is refused at 2026-08-05T23:59:59Z and permitted at 2026-08-06T00:00:00Z."""

    def test_advance_with_zero_open_requests_inside_the_window(self, api):
        """PRD §3.4: "A new cycle is `OPEN`, its `current_tier` is `STATE_AGENCY`, its `tier_opened_at` equals the supplied `opens_at`, its `tier_advance_count` is 0, its `open_request_count` is 0, and `awarded_by_user_id` and `awarded_at` are null."
        PRD §3.4: "Its `tier_deadline_at` is derived as the `tier_opened_at` plus `tier_window_days` whole days, where a day is an exact multiple of twenty-four hours."
        PRD §3.4: "An advance is permitted only when the cycle's `open_request_count` is zero — nobody in this tier wants the property — or when the logical clock has reached or passed `tier_deadline_at`, meaning the window has closed regardless of interest."
        PRD §3.4: "From `STATE_AGENCY`, `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`, the advance keeps the cycle in `OPEN` and moves `current_tier` exactly one step along the fixed order `STATE_AGENCY` → `LOCAL_GOVERNMENT` → `ELIGIBLE_NONPROFIT` → `PUBLIC_SALE`; `tier_opened_at` is reset to the logical clock, `tier_deadline_at` is recomputed from that new opening instant plus the same `tier_window_days`, `tier_advance_count` increases by 1, and the cycle's `version` increments by 1."

        Design: Difficulty/boundary_precision_check/bpc_advance_tier_with_zero_open_requests_inside_window
        """
        scenario = _open_cycle_with_a_local_government_waiting()
        cycle = scenario["cycle"]

        assert_screening_cycle(cycle)
        assert cycle["current_tier"] == "STATE_AGENCY", (
            f"a new cycle starts at STATE_AGENCY, got {cycle['current_tier']}"
        )
        assert cycle["open_request_count"] == 0, (
            f"a new cycle holds no requests, got {cycle['open_request_count']}"
        )
        assert _instant(cycle["tier_opened_at"]) == _instant("2026-08-01T00:00:00Z"), (
            f"tier_opened_at equals the supplied opens_at, got {cycle['tier_opened_at']}"
        )
        assert _instant(cycle["tier_deadline_at"]) == _instant("2026-08-06T00:00:00Z"), (
            "five whole days of exactly twenty-four hours after "
            f"2026-08-01T00:00:00Z is 2026-08-06T00:00:00Z, got "
            f"{cycle['tier_deadline_at']}"
        )

        response = api.advance_screening_tier(
            cycle["id"], make_disposal_officer_headers()
        )
        advanced = validate_success(response, 200)
        assert advanced["current_tier"] == "LOCAL_GOVERNMENT", (
            "with no open requests the advance is permitted well inside the "
            f"window; got {advanced['current_tier']}"
        )
        assert advanced["status"] == "OPEN", (
            f"the advance keeps the cycle OPEN, got {advanced['status']}"
        )
        assert advanced["tier_advance_count"] == 1, (
            f"tier_advance_count increases by 1, got {advanced['tier_advance_count']}"
        )
        assert _instant(advanced["tier_opened_at"]) == _instant("2026-08-01T00:00:00Z"), (
            "tier_opened_at is reset to the logical clock, which has not moved; "
            f"got {advanced['tier_opened_at']}"
        )
        assert _instant(advanced["tier_deadline_at"]) == _instant(
            "2026-08-06T00:00:00Z"
        ), (
            "the deadline is recomputed from the new opening instant plus the same "
            f"five days; got {advanced['tier_deadline_at']}"
        )
        assert advanced["version"] == cycle["version"] + 1, (
            "the advance increments the cycle's version by exactly 1, from "
            f"{cycle['version']}; got {advanced['version']}"
        )

    def test_advance_one_second_before_the_deadline_with_an_open_request(self, api):
        """PRD §3.4: "An advance is permitted only when the cycle's `open_request_count` is zero — nobody in this tier wants the property — or when the logical clock has reached or passed `tier_deadline_at`, meaning the window has closed regardless of interest."
        PRD §3.4: "An advance attempted while the tier still holds open requests inside its window is refused with `ERR_TIER_WINDOW_OPEN`."
        PRD §3.4: "Filing also recomputes the cycle's `open_request_count`, which is the number of requests on that cycle whose `status` is `SUBMITTED` or `INFO_REQUESTED`."
        PRD §2.9: "Those secondary effects are part of the operation's contract, not best-effort housekeeping: an operation either applies all of its hops or, if a validation fails, applies none of them."

        Design: Difficulty/boundary_precision_check/bpc_advance_tier_with_zero_open_requests_inside_window
        """
        scenario = _open_cycle_with_a_local_government_waiting()
        cycle = advance_tier(scenario["cycle"]["id"], 1)
        recipient = scenario["recipient"]

        request = file_screening_request(cycle["id"], recipient["id"])
        assert_screening_request(request)
        assert request["status"] == "SUBMITTED", (
            f"a filed request lands SUBMITTED, got {request['status']}"
        )
        assert request["tier_at_submission"] == "LOCAL_GOVERNMENT", (
            "the request freezes the tier the cycle stood on, got "
            f"{request['tier_at_submission']}"
        )

        before = read_cycle(cycle["id"])
        assert before["open_request_count"] == 1, (
            "filing recomputes the count of SUBMITTED and INFO_REQUESTED "
            f"requests; got {before['open_request_count']}"
        )

        set_clock("2026-08-05T23:59:59Z")
        response = api.advance_screening_tier(
            cycle["id"], make_disposal_officer_headers()
        )
        validate_error(response, ApiErrorId.ERR_TIER_WINDOW_OPEN)

        after = read_cycle(cycle["id"])
        assert after["current_tier"] == "LOCAL_GOVERNMENT", (
            "one second before the deadline the window is still open, so the "
            f"refused advance moves nothing; got {after['current_tier']}"
        )
        assert after["tier_advance_count"] == before["tier_advance_count"], (
            "a refused advance applies none of its hops, so tier_advance_count "
            f"stays at {before['tier_advance_count']}; got "
            f"{after['tier_advance_count']}"
        )
        assert after["version"] == before["version"], (
            f"the refusal leaves the cycle's version at {before['version']}, got "
            f"{after['version']}"
        )
        assert _instant(after["tier_opened_at"]) == _instant(
            before["tier_opened_at"]
        ), "the refusal does not reset tier_opened_at"

    def test_advance_at_exactly_the_deadline_instant_is_permitted(self, api):
        """PRD §3.4: "An advance is permitted only when the cycle's `open_request_count` is zero — nobody in this tier wants the property — or when the logical clock has reached or passed `tier_deadline_at`, meaning the window has closed regardless of interest."
        PRD §3.4: "From `STATE_AGENCY`, `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`, the advance keeps the cycle in `OPEN` and moves `current_tier` exactly one step along the fixed order `STATE_AGENCY` → `LOCAL_GOVERNMENT` → `ELIGIBLE_NONPROFIT` → `PUBLIC_SALE`; `tier_opened_at` is reset to the logical clock, `tier_deadline_at` is recomputed from that new opening instant plus the same `tier_window_days`, `tier_advance_count` increases by 1, and the cycle's `version` increments by 1."
        PRD §3.4: "A filed request lands in `status` `SUBMITTED` with `information_request_note`, `denial_reason` all null and `resubmission_count` at 0, and it freezes `tier_at_submission` as a copy of the cycle's `current_tier` at that instant — one of `STATE_AGENCY`, `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`."

        Design: Difficulty/boundary_precision_check/bpc_advance_tier_with_zero_open_requests_inside_window
        """
        scenario = _open_cycle_with_a_local_government_waiting()
        cycle = advance_tier(scenario["cycle"]["id"], 1)
        request = file_screening_request(cycle["id"], scenario["recipient"]["id"])

        set_clock("2026-08-05T23:59:59Z")
        validate_error(
            api.advance_screening_tier(cycle["id"], make_disposal_officer_headers()),
            ApiErrorId.ERR_TIER_WINDOW_OPEN,
        )

        set_clock("2026-08-06T00:00:00Z")
        advanced = validate_success(
            api.advance_screening_tier(cycle["id"], make_disposal_officer_headers()),
            200,
        )
        assert advanced["current_tier"] == "ELIGIBLE_NONPROFIT", (
            "at exactly the deadline instant the window has closed regardless of "
            f"interest, so the advance is permitted; got {advanced['current_tier']}"
        )
        assert advanced["status"] == "OPEN", (
            f"the advance keeps the cycle OPEN, got {advanced['status']}"
        )
        assert advanced["tier_advance_count"] == 2, (
            f"this is the cycle's second advance, got {advanced['tier_advance_count']}"
        )
        assert _instant(advanced["tier_opened_at"]) == _instant(
            "2026-08-06T00:00:00Z"
        ), (
            "tier_opened_at is reset to the logical clock, got "
            f"{advanced['tier_opened_at']}"
        )
        assert _instant(advanced["tier_deadline_at"]) == _instant(
            "2026-08-11T00:00:00Z"
        ), (
            "the deadline is recomputed as the new opening instant plus the same "
            f"five whole days; got {advanced['tier_deadline_at']}"
        )

        carried = read_request(request["id"])
        assert carried["status"] == "SUBMITTED", (
            "advancing past a tier does not resolve the request it left behind, "
            f"got {carried['status']}"
        )
        assert carried["tier_at_submission"] == "LOCAL_GOVERNMENT", (
            "the frozen tier is never rewritten, got "
            f"{carried['tier_at_submission']}"
        )
        assert read_cycle(cycle["id"])["open_request_count"] == 1, (
            "the request is still SUBMITTED, so it still counts as open"
        )

    def test_request_from_the_tier_the_cycle_has_left_is_refused(self, api):
        """PRD §3.4: "Three checks follow existence resolution, in this order: the requesting organisation must not be `SUSPENDED`, or the filing is refused with `ERR_AGENCY_SUSPENDED`; the organisation's `agency_type` must equal the cycle's `current_tier`, or the filing is refused with `ERR_TIER_PRIORITY_VIOLATION` — this is what makes the ladder a ladder, and it also means a cycle sitting at `PUBLIC_SALE` admits no screening request at all, since no organisation's type is `PUBLIC_SALE`; and the logical clock must fall inside the closed interval running from `tier_opened_at` through `tier_deadline_at`, both endpoints included, or the filing is refused with `ERR_TIER_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/bpc_advance_tier_with_zero_open_requests_inside_window
        """
        scenario = _open_cycle_with_a_local_government_waiting()
        cycle = advance_tier(scenario["cycle"]["id"], 1)
        recipient = scenario["recipient"]
        file_screening_request(cycle["id"], recipient["id"])

        set_clock("2026-08-06T00:00:00Z")
        validate_success(
            api.advance_screening_tier(cycle["id"], make_disposal_officer_headers()),
            200,
        )

        response = api.create_screening_request(
            create_screening_request_payload(cycle["id"], recipient["id"]),
            make_agency_officer_headers(recipient["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TIER_PRIORITY_VIOLATION)

        assert read_cycle(cycle["id"])["open_request_count"] == 1, (
            "the refused filing adds nothing to the cycle's open request count"
        )


# ─── The federal use period's inclusive end date ──────────────────────────


def _two_federally_sourced_assets() -> dict:
    """Two federally sourced assets appraised with the clock at 2026-08-14.

    The IT_EQUIPMENT item's twelve-month use period from 2025-08-15 ends on
    2026-08-15, one day into the future. The VEHICLE's eighteen-month period from
    2024-12-31 clamps to 2026-06-30, which is already past.
    """
    scenario = setup_assessed_assets(
        [
            {
                "kind": "it_equipment",
                "overrides": {
                    "description": "Federally donated switch stack",
                    "federal_source": True,
                    "federal_use_period_start_on": "2025-08-15",
                },
                "assessment": {
                    "condition_code": "C2",
                    "functional": True,
                    "repair_cost_estimate_cents": 0,
                    "assessed_on": "2026-08-14",
                },
            },
            {
                "kind": "vehicle",
                "overrides": {
                    "description": "Federally donated crew cab pickup",
                    "federal_source": True,
                    "federal_use_period_start_on": "2024-12-31",
                    "vin": "1FT7W2BT9KEB77777",
                    "odometer_reading": 156780,
                    "title_number": "TX-77777",
                },
                "assessment": {
                    "condition_code": "C4",
                    "functional": True,
                    "repair_cost_estimate_cents": 185000,
                    "assessed_on": "2026-08-14",
                },
            },
        ],
        clock="2026-08-14T00:00:00Z",
    )
    return scenario


class TestFederalUsePeriodEndDateInclusive:
    """The use-period gate opens on the end date itself, so the same cycle
    creation is refused on 2026-08-14 and accepted on 2026-08-15."""

    def test_use_period_end_dates_are_derived_with_month_clamping(self, api):
        """PRD §3.3: "Its `federal_use_period_end_on` is computed at creation by adding a category-dependent number of calendar months to `federal_use_period_start_on`: eighteen months for a `VEHICLE`, a `HEAVY_EQUIPMENT` item or a `RESTRICTED_MILITARY` article, and twelve months for `IT_EQUIPMENT` or `FURNITURE`."
        PRD §3.3: "The month arithmetic keeps the day-of-month and clamps to the last day of the target month where that day does not exist, as described in §2.4."
        PRD §2.4: "Calendar-month arithmetic, used only for federal use periods, adds a number of months to the start date's month while keeping the day-of-month, and clamps to the last day of the target month when that day-of-month does not exist there — so a use period starting on 31 August and running twelve months ends on 31 August, while one starting on 31 August and running eighteen months ends on 28 February in a common year and 29 February in a leap year."

        Design: Difficulty/boundary_precision_check/bpc_federal_use_period_end_date_inclusive
        """
        scenario = _two_federally_sourced_assets()
        asset_it, asset_vehicle = scenario["assets"]

        assert asset_it["federal_source"] is True, (
            "the use-period gate only applies to federally sourced property"
        )
        assert asset_it["federal_use_period_end_on"] == "2026-08-15", (
            "twelve months added to 2025-08-15 keeps the day-of-month, got "
            f"{asset_it['federal_use_period_end_on']}"
        )
        assert asset_vehicle["federal_use_period_end_on"] == "2026-06-30", (
            "eighteen months added to 2024-12-31 lands in June, which has no "
            f"thirty-first, so it clamps; got {asset_vehicle['federal_use_period_end_on']}"
        )

        assert asset_it["fair_market_value_cents"] == 985946, (
            "the use-period fields do not enter the valuation, got "
            f"{asset_it['fair_market_value_cents']}"
        )
        assert asset_vehicle["fair_market_value_cents"] == 297620, (
            f"expected 297620, got {asset_vehicle['fair_market_value_cents']}"
        )
        for asset in (asset_it, asset_vehicle):
            assert_surplus_asset(asset)
            assert asset["disposition_status"] == "ASSESSED", (
                f"both assets are appraised, got {asset['disposition_status']}"
            )
            assert asset["version"] == 2, (
                "one assessment increments the asset's version once from 1, and "
                f"acceptance changes no asset field; got {asset['version']}"
            )

    def test_screening_one_day_before_the_use_period_end_is_refused(self, api):
        """PRD §3.3: "An asset may be pushed into tier screening or listed for auction only when it is not federally sourced, or when the logical clock's current date has reached or passed its `federal_use_period_end_on`."
        PRD §3.3: "Disposal **on** the end date itself is permitted; one day earlier is not, and is refused with `ERR_FEDERAL_USE_PERIOD_ACTIVE`."
        PRD §3.4: "Note the precedence: the disposability complaint precedes the use-period complaint, which in turn precedes the malformed-window complaint."
        PRD §2.9: "Those secondary effects are part of the operation's contract, not best-effort housekeeping: an operation either applies all of its hops or, if a validation fails, applies none of them."

        Design: Difficulty/boundary_precision_check/bpc_federal_use_period_end_date_inclusive
        """
        scenario = _two_federally_sourced_assets()
        asset_it = scenario["assets"][0]

        response = api.create_screening_cycle(
            create_screening_cycle_payload(
                asset_it["id"],
                opens_at="2026-08-14T00:00:00Z",
                tier_window_days=5,
            ),
            make_disposal_officer_headers(),
        )
        validate_error(response, ApiErrorId.ERR_FEDERAL_USE_PERIOD_ACTIVE)

        after = read_asset(asset_it["id"])
        assert after["disposition_status"] == "ASSESSED", (
            "one day before the end date the asset is still federally committed, "
            f"so nothing moves; got {after['disposition_status']}"
        )
        assert after["version"] == 2, (
            "the refused opening applies none of its hops, so the asset's version "
            f"stays at 2; got {after['version']}"
        )

    def test_screening_on_the_use_period_end_date_is_permitted(self, api):
        """PRD §3.3: "Disposal **on** the end date itself is permitted; one day earlier is not, and is refused with `ERR_FEDERAL_USE_PERIOD_ACTIVE`."
        PRD §3.4: "A new cycle is `OPEN`, its `current_tier` is `STATE_AGENCY`, its `tier_opened_at` equals the supplied `opens_at`, its `tier_advance_count` is 0, its `open_request_count` is 0, and `awarded_by_user_id` and `awarded_at` are null."
        PRD §3.4: "Its `tier_deadline_at` is derived as the `tier_opened_at` plus `tier_window_days` whole days, where a day is an exact multiple of twenty-four hours."
        PRD §3.4: "Opening the cycle also moves the asset from `ASSESSED` to `SCREENING` and increments the asset's `version` by 1."

        Design: Difficulty/boundary_precision_check/bpc_federal_use_period_end_date_inclusive
        """
        scenario = _two_federally_sourced_assets()
        asset_it = scenario["assets"][0]

        validate_error(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    asset_it["id"],
                    opens_at="2026-08-14T00:00:00Z",
                    tier_window_days=5,
                ),
                make_disposal_officer_headers(),
            ),
            ApiErrorId.ERR_FEDERAL_USE_PERIOD_ACTIVE,
        )

        set_clock("2026-08-15T00:00:00Z")
        cycle = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    asset_it["id"],
                    opens_at="2026-08-15T00:00:00Z",
                    tier_window_days=5,
                ),
                make_disposal_officer_headers(),
            ),
            201,
        )
        assert_screening_cycle(cycle)
        assert cycle["status"] == "OPEN", (
            f"a new cycle is OPEN, got {cycle['status']}"
        )
        assert cycle["current_tier"] == "STATE_AGENCY", (
            f"a new cycle starts at the first tier, got {cycle['current_tier']}"
        )
        assert _instant(cycle["tier_opened_at"]) == _instant("2026-08-15T00:00:00Z"), (
            f"tier_opened_at equals the supplied opens_at, got {cycle['tier_opened_at']}"
        )
        assert _instant(cycle["tier_deadline_at"]) == _instant(
            "2026-08-20T00:00:00Z"
        ), (
            "five whole days after 2026-08-15T00:00:00Z is 2026-08-20T00:00:00Z, "
            f"got {cycle['tier_deadline_at']}"
        )

        after = read_asset(asset_it["id"])
        assert after["disposition_status"] == "SCREENING", (
            "the very same call that was refused one day earlier now moves the "
            f"asset into screening; got {after['disposition_status']}"
        )
        assert after["version"] == 3, (
            "opening the cycle increments the asset's version by 1 from 2, got "
            f"{after['version']}"
        )
        assert after["federal_use_period_end_on"] == "2026-08-15", (
            "the gate reads the end date without rewriting it, got "
            f"{after['federal_use_period_end_on']}"
        )

    def test_screening_after_the_use_period_has_ended_is_permitted(self, api):
        """PRD §3.3: "An asset may be pushed into tier screening or listed for auction only when it is not federally sourced, or when the logical clock's current date has reached or passed its `federal_use_period_end_on`."
        PRD §3.4: "Opening the cycle also moves the asset from `ASSESSED` to `SCREENING` and increments the asset's `version` by 1."

        Design: Difficulty/boundary_precision_check/bpc_federal_use_period_end_date_inclusive
        """
        scenario = _two_federally_sourced_assets()
        asset_vehicle = scenario["assets"][1]

        cycle = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    asset_vehicle["id"],
                    opens_at="2026-08-14T00:00:00Z",
                    tier_window_days=5,
                ),
                make_disposal_officer_headers(),
            ),
            201,
        )
        assert cycle["status"] == "OPEN", (
            "the clock has passed this asset's clamped end date of 2026-06-30, so "
            f"the gate is open; got {cycle['status']}"
        )

        after = read_asset(asset_vehicle["id"])
        assert after["disposition_status"] == "SCREENING", (
            f"the asset enters screening, got {after['disposition_status']}"
        )
        assert after["version"] == 3, (
            f"the asset's version increments by 1 from 2, got {after['version']}"
        )
