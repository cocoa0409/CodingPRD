"""Retiring a garment and recovering what is left of it on a resale channel.

Retirement is the door out of the rentable fleet, and it is guarded by whatever
the garment is still committed to — a live booking or an unsettled damage claim.
Once a unit is `RETIRED` a planner may put it in a shop window, and the price is
built by a seven-step pass whose evaluation order is pinned precisely because it
looks circular: the fee percentage is keyed on a tier derived from the price, and
the floor correction then moves the price without moving the tier.  These tests
pin both ends of the tier table, the single corrective pass, the thirty-day
window boundary, the supersede lineage, the sale discount floor, and the fact
that a sale re-prices on what the garment actually fetched.
"""

from __future__ import annotations

from typing import Optional

from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_SUPERSEDE_TARGET,
    ERR_LISTING_ALREADY_ACTIVE,
    ERR_LISTING_WINDOW_OPEN,
    ERR_SALE_PRICE_BELOW_FLOOR,
    ERR_STALE_UNIT_VERSION,
    ERR_UNIT_HAS_ACTIVE_COMMITMENT,
    ERR_UNIT_NOT_RETIRED,
)
from test_helpers.assertions import (
    assert_error,
    assert_fields,
    assert_instant,
    assert_list,
    assert_money,
    assert_null,
    assert_ok,
    assert_unit_position,
)
from test_helpers.fixtures import (
    Scenario,
    inspected_turn,
    standard_catalog,
)

JsonDict = dict

# Every listing in this module is created on 2026-08-03, so the thirty-day
# selling window closes on 2026-09-02.
LISTING_CLOCK = K.CLOCK_AUG_03
WINDOW_DAY_29_CLOCK = K.CLOCK_SEP_01_0000
WINDOW_DAY_30_CLOCK = K.CLOCK_SEP_02_0000


def _retired_unit(
    scenario: Scenario,
    condition_grade: str = K.GRADE_A,
    reason: str = K.RETIREMENT_PLANNED_REFRESH,
    clock: str = LISTING_CLOCK,
):
    """A never-rented garment of the 48000-cent gown style, withdrawn from the floor."""
    scenario.set_clock(clock)
    style = scenario.create_style()
    unit = scenario.add_unit(
        style["id"], K.UNIT_GOWN_001, condition_grade=condition_grade
    )
    assert_unit_position(
        unit,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
        condition_grade=condition_grade,
    )
    retired = scenario.retire_unit(unit["id"], reason)
    assert_unit_position(retired, availability_state=K.AVAIL_RETIRED)
    return style, retired


def _fresh_version(scenario: Scenario, unit_id: str) -> int:
    """Re-read the unit so the optimistic-concurrency token is current."""
    return scenario.read_unit(unit_id)["version"]


def _listed(
    scenario: Scenario,
    unit_id: str,
    channel: str = K.CHANNEL_OUTLET,
    supersedes_listing_id: Optional[str] = None,
) -> JsonDict:
    """Put a retired garment in a shop window with a freshly read version token."""
    return scenario.create_listing(
        unit_id, _fresh_version(scenario, unit_id), channel, supersedes_listing_id
    )


def _expire(scenario: Scenario, listing_id: str) -> JsonDict:
    return assert_ok(scenario.client.expire_resale_listing(listing_id, scenario.planner))


def _reprice(scenario: Scenario, listing_id: str) -> JsonDict:
    return assert_ok(scenario.client.reprice_resale_listing(listing_id, scenario.planner))


def _sell(scenario: Scenario, listing_id: str, sale_price_cents: int):
    """A raw sale attempt, so a test can inspect a refusal itself."""
    return scenario.client.sell_resale_listing(
        listing_id, F.sale_payload(sale_price_cents), scenario.planner
    )


def _listings_for_unit(scenario: Scenario, unit_id: str, total_count: int):
    rows, _meta = assert_list(
        scenario.client.list_resale_listings(
            scenario.planner, {"rental_unit_id": unit_id}
        ),
        total_count=total_count,
    )
    return rows


def test_a_grade_a_gown_lists_at_the_high_tier_outlet_fee(scenario: Scenario) -> None:
    """21600 lands in the HIGH tier, so the OUTLET fee is 0.12 and not the MID 0.08.

    PRD §3.8: "Step 1 computes `base_price_cents` as the style's `retail_price_cents`, multiplied by the resale rate for the unit's current `condition_grade` — 0.45 for grade `A`, 0.32 for `B`, 0.20 for `C` and 0.08 for `D` — multiplied by one minus 0.15 times the listing's `markdown_step`, rounded half up."
    PRD §3.8: "Step 3 reads the fee percentage for the listing's `channel` at that frozen tier: for `OUTLET` it is 0.05 at `LOW`, 0.08 at `MID` and 0.12 at `HIGH`; for `PARTNER_RESALE` it is 0.15 at `LOW`, 0.18 at `MID` and 0.22 at `HIGH`."
    PRD §3.8: "Step 7 then restates the money on the final price with the frozen percentage: `channel_fee_cents` becomes `list_price_cents` multiplied by the fee percentage, rounded half up, and `net_recovery_cents` is `list_price_cents` minus that fee minus the handling cost."

    Design: Corner/calculations/calc_resale_first_listing_uses_the_high_tier_fee
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_A)

    listing = _listed(scenario, unit["id"], K.CHANNEL_OUTLET)
    assert_fields(listing, state=K.LISTING_LISTED, channel=K.CHANNEL_OUTLET, markdown_step=0)
    assert_instant(listing["listed_at"], LISTING_CLOCK, "listed_at")

    # 48000 x 0.45 = 21600, at or above the 20000 MID ceiling, so the tier is HIGH.
    assert_money(
        listing,
        base_price_cents=21600,
        list_price_cents=21600,
        channel_fee_cents=2592,
        net_recovery_cents=18608,
    )
    assert_fields(listing, floor_adjusted=False)
    # 21600 x 0.12 = 2592, and 21600 - 2592 - 400 handling = 18608.
    assert listing["base_price_cents"] >= K.RESALE_TIER_MID_CEILING_CENTS
    assert (
        listing["net_recovery_cents"]
        == listing["list_price_cents"]
        - listing["channel_fee_cents"]
        - K.CHANNEL_HANDLING_CENTS[K.CHANNEL_OUTLET]
    )

    assert_unit_position(
        scenario.read_unit(unit["id"]), availability_state=K.AVAIL_RETIRED
    )


def test_a_reprice_that_breaks_the_floor_is_restated_at_the_minimum_recovery(
    scenario: Scenario,
) -> None:
    """One corrective pass lifts the price and pins the net at exactly 2000 cents.

    PRD §3.8: "When `markdown_step` is strictly below the cap of 3, `markdown_step` is incremented by 1, the listing moves `EXPIRED → LISTED`, `listed_at` is re-stamped at the current clock, and `base_price_cents`, `list_price_cents`, `channel_fee_cents`, `net_recovery_cents` and `floor_adjusted` are all recomputed at the new markdown step — this is the bounded markdown cycle `LISTED → EXPIRED → LISTED`."
    PRD §3.8: "When the provisional net is below the minimum net recovery of 2,000 cents, `list_price_cents` is set to 2,000 plus the channel's handling cost, divided by one minus the fee percentage, rounded half up, and `floor_adjusted` is set to true."
    PRD §3.8: "Step 7 then restates the money on the final price with the frozen percentage: `channel_fee_cents` becomes `list_price_cents` multiplied by the fee percentage, rounded half up, and `net_recovery_cents` is `list_price_cents` minus that fee minus the handling cost."

    Design: Corner/calculations/calc_resale_reprice_floor_correction_pins_net_recovery_at_the_minimum
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_D)

    # 48000 x 0.08 = 3840, below the 5000 LOW ceiling, so PARTNER_RESALE is 0.15.
    first = _listed(scenario, unit["id"], K.CHANNEL_PARTNER_RESALE)
    assert_money(
        first,
        base_price_cents=3840,
        list_price_cents=3840,
        channel_fee_cents=576,
        net_recovery_cents=2364,
    )
    assert_fields(first, markdown_step=0, floor_adjusted=False)

    scenario.set_clock(K.CLOCK_SEP_05_0900)
    assert_fields(_expire(scenario, first["id"]), state=K.LISTING_EXPIRED)

    marked_down = _reprice(scenario, first["id"])
    assert_fields(marked_down, state=K.LISTING_LISTED, markdown_step=1, floor_adjusted=True)
    assert_instant(marked_down["listed_at"], K.CLOCK_SEP_05_0900, "listed_at")
    # Step 1: 48000 x 0.08 x 0.85 = 3264, whose provisional net of
    # 3264 - 490 - 900 = 1874 is under the 2000 minimum.  Step 6 restates the
    # price as (2000 + 900) / 0.85 = 3412 at the still-frozen LOW percentage.
    assert_money(
        marked_down,
        base_price_cents=3264,
        list_price_cents=3412,
        channel_fee_cents=512,
        net_recovery_cents=K.MIN_NET_RECOVERY_CENTS,
    )
    # Step 7 restates the fee on the corrected price, so it is 512 and not the
    # 490 that 0.15 of the uncorrected 3264 would have left behind.
    assert marked_down["channel_fee_cents"] != 490
    assert (
        marked_down["net_recovery_cents"]
        == marked_down["list_price_cents"]
        - marked_down["channel_fee_cents"]
        - K.CHANNEL_HANDLING_CENTS[K.CHANNEL_PARTNER_RESALE]
    )


def test_a_stale_unit_version_is_refused_before_the_fresh_token_lists(
    scenario: Scenario,
) -> None:
    """Retirement bumps the very version the listing request has to quote.

    PRD §3.8: "Retirement sets `availability_state` to `RETIRED`, stamps `retired_at` with the current logical clock, records the supplied reason and increments the unit's `version`."
    PRD §3.8: "And, as §2.6 sets out, the supplied `expected_rental_unit_version` must still equal the unit's stored `version`, otherwise `ERR_STALE_UNIT_VERSION` (412)."

    Design: Corner/complexity_layers/layer_stale_unit_version_on_a_resale_listing_is_rejected_then_the_fresh_token_wins
    """
    scenario.set_clock(LISTING_CLOCK)
    style = scenario.create_style()
    unit = scenario.add_unit(style["id"], K.UNIT_GOWN_001, condition_grade=K.GRADE_A)
    stale_version = unit["version"]

    retired = scenario.retire_unit(unit["id"], K.RETIREMENT_PLANNED_REFRESH)
    assert_fields(retired, version=stale_version + 1)

    refused = scenario.client.create_resale_listing(
        F.resale_listing_payload(unit["id"], stale_version, K.CHANNEL_OUTLET),
        scenario.planner,
    )
    assert_error(refused, ERR_STALE_UNIT_VERSION)
    # The refusal is total: no listing row was brought into existence.
    _listings_for_unit(scenario, unit["id"], total_count=0)

    # The identical body with the current token is accepted.
    accepted = scenario.create_listing(
        unit["id"], retired["version"], K.CHANNEL_OUTLET
    )
    assert_fields(accepted, state=K.LISTING_LISTED, markdown_step=0, floor_adjusted=False)
    assert_money(
        accepted,
        base_price_cents=21600,
        list_price_cents=21600,
        channel_fee_cents=2592,
        net_recovery_cents=18608,
    )
    assert_unit_position(
        scenario.read_unit(unit["id"]), availability_state=K.AVAIL_RETIRED
    )


def test_a_superseding_listing_records_its_predecessor_and_inherits_the_ladder(
    scenario: Scenario,
) -> None:
    """The lineage is a chain: the child points back, the parent points nowhere.

    PRD §3.8: "At rank 34, when `supersedes_listing_id` is supplied it must reference a listing on the same `rental_unit_id` whose `state` is `EXPIRED`, otherwise `ERR_INVALID_SUPERSEDE_TARGET` (422) — a supersede chain may only extend from a listing that genuinely ran out its window on the same garment."
    PRD §3.8: "The listing's `markdown_step` is inherited as the superseded listing's `markdown_step` plus 1, or is 0 for a first listing, which is how the markdown ladder survives across superseding listings."

    Design: Corner/entities/entity_resale_listing_self_reference_records_the_supersede_lineage
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_A)
    parent = _listed(scenario, unit["id"], K.CHANNEL_OUTLET)
    assert_fields(parent, markdown_step=0)
    assert_null(parent, "supersedes_listing_id")

    scenario.set_clock(K.CLOCK_SEP_05_0900)
    assert_fields(_expire(scenario, parent["id"]), state=K.LISTING_EXPIRED)

    child = _listed(
        scenario,
        unit["id"],
        K.CHANNEL_PARTNER_RESALE,
        supersedes_listing_id=parent["id"],
    )
    assert_fields(
        child,
        state=K.LISTING_LISTED,
        markdown_step=1,
        supersedes_listing_id=parent["id"],
        channel=K.CHANNEL_PARTNER_RESALE,
    )

    # The lineage is readable from the parent's side through the filter.
    rows, _meta = assert_list(
        scenario.client.list_resale_listings(
            scenario.planner, {"supersedes_listing_id": parent["id"]}
        ),
        total_count=1,
    )
    assert rows[0]["id"] == child["id"]

    # And the parent itself is unchanged: no back-pointer, still expired.
    reread = scenario.read_listing(parent["id"])
    assert_fields(reread, state=K.LISTING_EXPIRED, markdown_step=0)
    assert_null(reread, "supersedes_listing_id")


def test_an_open_damage_claim_blocks_retirement_until_it_is_charged(
    scenario: Scenario,
) -> None:
    """The reservation is already RETURNED, so the only live commitment is the claim.

    PRD §3.8: "At rank 45, no reservation whose `allocated_unit_id` is this unit may be in `MATCHED`, `SHIPPED`, `IN_POSSESSION` or `RETURN_INITIATED`, and no damage claim on this unit may be in `OPEN`, `ASSESSED` or `DISPUTED`; otherwise the request is refused with `ERR_UNIT_HAS_ACTIVE_COMMITMENT` (409)."
    PRD §3.8: "Retirement sets `availability_state` to `RETIRED`, stamps `retired_at` with the current logical clock, records the supplied reason and increments the unit's `version`."
    PRD §3.8: "The second branch, `PROCESSING → RETIRED`, is the condemned and lost case: a garment in reconditioning is withdrawn mid-pipeline. Its cascade drives any reverse-logistics job on the unit that sits in `RECEIVED`, `INSPECTED`, `PROCESSING`, `READY_FOR_PHOTO`, `PHOTOGRAPHED` or `CONDEMNED_HOLD` to `CONDEMNED_HOLD`, and it then recomputes the style's `active_unit_count`, `required_depth_units`, `depth_gap_units` and `replenishment_flag`."

    Design: Corner/validations/validation_retirement_is_blocked_by_an_open_claim_then_allowed_once_charged
    """
    catalog = standard_catalog(scenario)
    turn = inspected_turn(
        scenario,
        catalog,
        K.WINDOW_AUG_05_09,
        K.SOIL_LIGHT,
        K.DAMAGE_MODERATE,
        K.GRADE_B,
    )
    # The garment is back in the warehouse: the reservation is harmless and the
    # job is mid-pipeline, so rank 45 has only the claim left to object to.
    assert_fields(turn.claim, state=K.CLAIM_OPEN)
    assert_fields(turn.job, state=K.JOB_PROCESSING)

    refused = scenario.client.retire_rental_unit(
        turn.unit_id,
        F.retirement_payload(K.RETIREMENT_CONDEMNED_DAMAGE),
        scenario.planner,
    )
    assert_error(refused, ERR_UNIT_HAS_ACTIVE_COMMITMENT)

    blocked = scenario.read_unit(turn.unit_id)
    assert_unit_position(blocked, availability_state=K.AVAIL_PROCESSING)
    assert_null(blocked, "retired_at")
    assert_null(blocked, "retirement_reason")

    # Charging the claim moves it out of the {OPEN, ASSESSED, DISPUTED} set.
    scenario.assess(turn.claim_id)
    assert_fields(scenario.charge(turn.claim_id), state=K.CLAIM_CHARGED)

    retired = scenario.retire_unit(turn.unit_id, K.RETIREMENT_CONDEMNED_DAMAGE)
    assert_unit_position(retired, availability_state=K.AVAIL_RETIRED)
    assert_fields(
        retired,
        retirement_reason=K.RETIREMENT_CONDEMNED_DAMAGE,
        version=blocked["version"] + 1,
    )
    assert_instant(retired["retired_at"], K.CLOCK_AUG_10_0900, "retired_at")

    # The in-flight job is dragged into the condemned sink by the same request.
    assert_fields(
        scenario.read_job(catalog.inspector, turn.job_id), state=K.JOB_CONDEMNED_HOLD
    )


def test_a_sale_one_cent_under_the_discount_floor_is_refused(
    scenario: Scenario,
) -> None:
    """19440 is exactly ninety percent of 21600, so 19439 is a cent too generous.

    PRD §3.8: "At rank 55 that price must be greater than or equal to the listing's `list_price_cents` multiplied by one minus 0.10, rounded half up, otherwise `ERR_SALE_PRICE_BELOW_FLOOR` (422): a planner may discount at the point of sale by up to ten percent of the list price and no further."
    PRD §3.8: "The listing moves `LISTED → SOLD`, `sold_at` is stamped at the current logical clock, and `sale_price_cents` is recorded."
    PRD §3.8: "Hop two moves the unit `RETIRED → SOLD`, which is terminal on the availability dimension and increments the unit's `version`."

    Design: Corner/validations/validation_sale_below_the_discount_floor_is_refused_then_the_floor_price_sells
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_A)
    listing = _listed(scenario, unit["id"], K.CHANNEL_OUTLET)
    assert_money(listing, list_price_cents=21600)
    version_before_sale = _fresh_version(scenario, unit["id"])

    refused = _sell(scenario, listing["id"], 19439)
    assert_error(refused, ERR_SALE_PRICE_BELOW_FLOOR)

    held = scenario.read_listing(listing["id"])
    assert_fields(held, state=K.LISTING_LISTED, markdown_step=0)
    assert_null(held, "sold_at")
    assert_null(held, "sale_price_cents")

    sold = assert_ok(_sell(scenario, listing["id"], 19440))
    assert_fields(sold, state=K.LISTING_SOLD, markdown_step=0)
    assert_money(sold, sale_price_cents=19440, list_price_cents=21600)
    assert_instant(sold["sold_at"], LISTING_CLOCK, "sold_at")

    unit_after = scenario.read_unit(unit["id"])
    assert_unit_position(unit_after, availability_state=K.AVAIL_SOLD)
    assert_fields(unit_after, version=version_before_sale + 1)


def test_an_unexpired_supersede_target_outranks_the_active_listing_rule(
    scenario: Scenario,
) -> None:
    """One body breaks ranks 34 and 35 at once, and rank 34 is the one reported.

    PRD §3.8: "At rank 34, when `supersedes_listing_id` is supplied it must reference a listing on the same `rental_unit_id` whose `state` is `EXPIRED`, otherwise `ERR_INVALID_SUPERSEDE_TARGET` (422) — a supersede chain may only extend from a listing that genuinely ran out its window on the same garment."
    PRD §3.8: "At rank 35, no other listing on this unit may be in `DRAFT` or `LISTED`, otherwise `ERR_LISTING_ALREADY_ACTIVE` (409): one live shop window per garment."

    Design: Corner/validations/validation_supersede_target_must_be_expired_and_outranks_the_active_listing_rule
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_A)
    active = _listed(scenario, unit["id"], K.CHANNEL_OUTLET)
    assert_fields(active, state=K.LISTING_LISTED, channel=K.CHANNEL_OUTLET)
    fresh_version = _fresh_version(scenario, unit["id"])

    # Naming the live listing as the predecessor breaks rank 34 (it is LISTED,
    # not EXPIRED) and rank 35 (it is active); the lower rank must answer.
    with_target = scenario.client.create_resale_listing(
        F.resale_listing_payload(
            unit["id"], fresh_version, K.CHANNEL_PARTNER_RESALE, active["id"]
        ),
        scenario.planner,
    )
    assert_error(with_target, ERR_INVALID_SUPERSEDE_TARGET)

    # The identical body without the predecessor leaves only rank 35 broken,
    # which proves the ordering rather than a fixed preference for 422.
    without_target = scenario.client.create_resale_listing(
        F.resale_listing_payload(unit["id"], fresh_version, K.CHANNEL_PARTNER_RESALE),
        scenario.planner,
    )
    assert_error(without_target, ERR_LISTING_ALREADY_ACTIVE)

    survivors = _listings_for_unit(scenario, unit["id"], total_count=1)
    assert_fields(
        survivors[0],
        id=active["id"],
        state=K.LISTING_LISTED,
        channel=K.CHANNEL_OUTLET,
    )


def test_expiry_on_the_twenty_ninth_day_is_refused_as_still_open(
    scenario: Scenario,
) -> None:
    """A listing stamped 2026-08-03 is one day short of its window on 2026-09-01.

    PRD §3.8: "At rank 44 the current logical clock's calendar date must be greater than or equal to the calendar date of `listed_at` plus 30 days, otherwise `ERR_LISTING_WINDOW_OPEN` (409); the boundary is inclusive, so expiry is permitted on exactly the thirtieth day after listing and refused on the twenty-ninth."

    Design: Difficulty/boundary_precision_check/listing_expiration_allowed_exactly_at_window_edge
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_D)
    listing = _listed(scenario, unit["id"], K.CHANNEL_OUTLET)
    assert_instant(listing["listed_at"], LISTING_CLOCK, "listed_at")

    # 2026-08-03 plus 30 days is 2026-09-02, so day 29 is one short.
    scenario.set_clock(WINDOW_DAY_29_CLOCK)
    refused = scenario.client.expire_resale_listing(listing["id"], scenario.planner)
    assert_error(refused, ERR_LISTING_WINDOW_OPEN)

    still_listed = scenario.read_listing(listing["id"])
    assert_fields(
        still_listed,
        state=K.LISTING_LISTED,
        markdown_step=listing["markdown_step"],
    )
    assert_money(still_listed, list_price_cents=listing["list_price_cents"])
    assert_instant(still_listed["listed_at"], LISTING_CLOCK, "listed_at")


def test_expiry_on_the_thirtieth_day_is_allowed_and_does_not_reprice(
    scenario: Scenario,
) -> None:
    """The inclusive edge opens exactly on 2026-09-02, and expiry moves only the state.

    PRD §3.8: "At rank 44 the current logical clock's calendar date must be greater than or equal to the calendar date of `listed_at` plus 30 days, otherwise `ERR_LISTING_WINDOW_OPEN` (409); the boundary is inclusive, so expiry is permitted on exactly the thirtieth day after listing and refused on the twenty-ninth."
    PRD §3.8: "A planner expires a `LISTED` listing, moving it `LISTED → EXPIRED`."
    PRD §3.8: "When `markdown_step` is strictly below the cap of 3, `markdown_step` is incremented by 1, the listing moves `EXPIRED → LISTED`, `listed_at` is re-stamped at the current clock, and `base_price_cents`, `list_price_cents`, `channel_fee_cents`, `net_recovery_cents` and `floor_adjusted` are all recomputed at the new markdown step — this is the bounded markdown cycle `LISTED → EXPIRED → LISTED`."

    Design: Difficulty/boundary_precision_check/listing_expiration_allowed_exactly_at_window_edge
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_D)
    listing = _listed(scenario, unit["id"], K.CHANNEL_OUTLET)

    scenario.set_clock(WINDOW_DAY_30_CLOCK)
    expired = _expire(scenario, listing["id"])
    assert_fields(expired, state=K.LISTING_EXPIRED)

    # The markdown ladder and the money belong to the reprice request, not to
    # expiry, so every priced field is byte-for-byte what listing produced.
    priced = (
        "markdown_step",
        "base_price_cents",
        "list_price_cents",
        "channel_fee_cents",
        "net_recovery_cents",
        "floor_adjusted",
    )
    assert {field: expired[field] for field in priced} == {
        field: listing[field] for field in priced
    }
    assert_instant(expired["listed_at"], LISTING_CLOCK, "listed_at")

    # Expiry is a listing event: the garment stays where retirement left it.
    assert_unit_position(
        scenario.read_unit(unit["id"]), availability_state=K.AVAIL_RETIRED
    )


def test_a_partner_listing_freezes_the_high_tier_percentage_at_creation(
    scenario: Scenario,
) -> None:
    """Tier HIGH is read once off the Step-1 price and becomes the listing's own rate.

    PRD §3.8: "Step 2 derives the channel tier from that Step-1 price and **freezes** it: the tier is `LOW` when `base_price_cents` is below 5,000 cents, `MID` when it is below 20,000 cents, and `HIGH` otherwise."
    PRD §3.8: "Step 3 reads the fee percentage for the listing's `channel` at that frozen tier: for `OUTLET` it is 0.05 at `LOW`, 0.08 at `MID` and 0.12 at `HIGH`; for `PARTNER_RESALE` it is 0.15 at `LOW`, 0.18 at `MID` and 0.22 at `HIGH`."
    PRD §3.8: "Step 7 then restates the money on the final price with the frozen percentage: `channel_fee_cents` becomes `list_price_cents` multiplied by the fee percentage, rounded half up, and `net_recovery_cents` is `list_price_cents` minus that fee minus the handling cost."

    Design: Difficulty/combinatorial_formula/resale_sale_reuses_fee_pct_frozen_at_listing_tier
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_A)

    listing = _listed(scenario, unit["id"], K.CHANNEL_PARTNER_RESALE)
    assert_fields(listing, state=K.LISTING_LISTED, markdown_step=0)
    # 48000 x 0.45 = 21600, which is not below the 20000 MID ceiling, so the
    # frozen tier is HIGH and PARTNER_RESALE charges 0.22 for the listing's life.
    assert listing["base_price_cents"] >= K.RESALE_TIER_MID_CEILING_CENTS
    assert_money(
        listing,
        base_price_cents=21600,
        list_price_cents=21600,
        channel_fee_cents=4752,
        net_recovery_cents=15948,
    )
    # 21600 x 0.22 = 4752, and 21600 - 4752 - 900 handling = 15948, so the
    # MID rate of 0.18 (3888) never touches this listing.
    assert listing["channel_fee_cents"] != 3888


def test_a_sale_restates_the_fee_at_the_frozen_percentage_not_the_sale_tier(
    scenario: Scenario,
) -> None:
    """19440 would re-derive as MID, but the listing's HIGH 0.22 is what applies.

    PRD §3.8: "The listing moves `LISTED → SOLD`, `sold_at` is stamped at the current logical clock, and `sale_price_cents` is recorded."
    PRD §3.8: "Steps 4 through 7 of the pricing arithmetic are then re-run with the list price replaced by `sale_price_cents` and the fee percentage still frozen at its listing-time value, so `channel_fee_cents` and `net_recovery_cents` restate on what the garment actually fetched; `base_price_cents` is left untouched as the historical record of what the markdown ladder asked for."
    PRD §3.8: "The unit's `realized_revenue_cents` is deliberately **not** touched by a sale: end-of-life money reaches unit economics through the sold listing's `net_recovery_cents`, and adding it to rental revenue as well would count it twice."

    Design: Difficulty/combinatorial_formula/resale_sale_reuses_fee_pct_frozen_at_listing_tier
    """
    _style, unit = _retired_unit(scenario, condition_grade=K.GRADE_A)
    listing = _listed(scenario, unit["id"], K.CHANNEL_PARTNER_RESALE)

    sold = assert_ok(_sell(scenario, listing["id"], 19440))
    assert_fields(sold, state=K.LISTING_SOLD)
    assert_instant(sold["sold_at"], LISTING_CLOCK, "sold_at")
    # 19440 x 0.22 = 4276.8, half up to 4277, and 19440 - 4277 - 900 = 14263.
    assert_money(
        sold,
        sale_price_cents=19440,
        base_price_cents=21600,
        channel_fee_cents=4277,
        net_recovery_cents=14263,
    )
    # Re-deriving the tier from 19440 would read MID at 0.18 and produce 3499
    # and 15041, which is 778 cents of fee the frozen rate does not forgive.
    assert sold["channel_fee_cents"] != 3499
    assert sold["net_recovery_cents"] != 15041

    # End-of-life money is reported by the listing alone.
    assert_money(scenario.read_unit(unit["id"]), realized_revenue_cents=0)


def test_a_listing_on_a_rentable_garment_is_refused_on_the_unit_state(
    scenario: Scenario,
) -> None:
    """The body is complete and correctly versioned; only the unit is wrong.

    PRD §3.8: "At rank 46, the unit's `availability_state` must be `RETIRED`, otherwise `ERR_UNIT_NOT_RETIRED` (409)."
    PRD §3.8: "And, as §2.6 sets out, the supplied `expected_rental_unit_version` must still equal the unit's stored `version`, otherwise `ERR_STALE_UNIT_VERSION` (412)."

    Design: Difficulty/cross_entity_state_dependency/resale_listing_requires_unit_in_retired_state
    """
    scenario.set_clock(LISTING_CLOCK)
    style = scenario.create_style()
    unit = scenario.add_unit(style["id"], K.UNIT_GOWN_001, condition_grade=K.GRADE_D)
    assert_unit_position(
        unit,
        availability_state=K.AVAIL_IN_STOCK,
        condition_state=K.COND_FLOOR_READY,
    )

    refused = scenario.client.create_resale_listing(
        F.resale_listing_payload(unit["id"], unit["version"], K.CHANNEL_OUTLET),
        scenario.planner,
    )
    # The token was read from the creation response itself, so the optimistic
    # concurrency check passes and the only surviving objection is the state.
    payload = assert_error(refused, ERR_UNIT_NOT_RETIRED)
    assert payload["error_id"] != ERR_STALE_UNIT_VERSION

    _listings_for_unit(scenario, unit["id"], total_count=0)
    assert_unit_position(
        scenario.read_unit(unit["id"]), availability_state=K.AVAIL_IN_STOCK
    )


def test_the_same_listing_body_is_accepted_once_the_unit_is_retired(
    scenario: Scenario,
) -> None:
    """Retirement bumps the version, so the retried body differs only in its token.

    PRD §3.8: "Retirement sets `availability_state` to `RETIRED`, stamps `retired_at` with the current logical clock, records the supplied reason and increments the unit's `version`."
    PRD §3.8: "The listing is created in `DRAFT` and advances `DRAFT → LISTED` inside the same request, stamping `listed_at` and incrementing the unit's `version`; a listing is therefore never observable in `DRAFT`."
    PRD §3.8: "Step 1 computes `base_price_cents` as the style's `retail_price_cents`, multiplied by the resale rate for the unit's current `condition_grade` — 0.45 for grade `A`, 0.32 for `B`, 0.20 for `C` and 0.08 for `D` — multiplied by one minus 0.15 times the listing's `markdown_step`, rounded half up."

    Design: Difficulty/cross_entity_state_dependency/resale_listing_requires_unit_in_retired_state
    """
    scenario.set_clock(LISTING_CLOCK)
    style = scenario.create_style()
    unit = scenario.add_unit(style["id"], K.UNIT_GOWN_001, condition_grade=K.GRADE_D)

    retired = scenario.retire_unit(unit["id"], K.RETIREMENT_PLANNED_REFRESH)
    assert_unit_position(retired, availability_state=K.AVAIL_RETIRED)
    assert_fields(
        retired,
        retirement_reason=K.RETIREMENT_PLANNED_REFRESH,
        version=unit["version"] + 1,
    )
    assert_instant(retired["retired_at"], LISTING_CLOCK, "retired_at")

    listing = scenario.create_listing(
        unit["id"], retired["version"], K.CHANNEL_OUTLET
    )
    assert_fields(listing, state=K.LISTING_LISTED, markdown_step=0)
    assert_instant(listing["listed_at"], LISTING_CLOCK, "listed_at")
    assert_null(listing, "supersedes_listing_id")
    # 48000 x 0.08 for grade D, at markdown step 0, is 3840.
    assert_money(listing, base_price_cents=3840)
    # The successful listing moved the unit's version on again.
    assert_fields(scenario.read_unit(unit["id"]), version=retired["version"] + 1)
