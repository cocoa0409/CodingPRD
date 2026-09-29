"""Arithmetic corners: recoupment tiers, tier tables, scoped counting and thresholds.

Each figure here is derived from the contract's own formula, spelled out in the
comment beside the assertion so an off-by-one in a tier boundary or a rounding
direction is visible without re-deriving the number.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    DEV_ACTIVE_DEVELOPMENT,
    GUILD_TIER_HIGH,
    GUILD_TIER_LOW,
    NEG_STUDIO_COUNTER,
    OFFER_SIDE_STUDIO,
    PITCH_SUBMITTED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    STEP_REVISION,
    TIER_PREMIER,
    TIER_PROBATION,
    TURNAROUND_EXERCISED,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    platform_admin_headers,
    studio_partner_headers,
)

REVISION_STEP = [f.step_spec(STEP_REVISION, 2000000)]
BEN_OKAFOR = {
    "full_name": "Ben Okafor",
    "guild_minimum_tier": GUILD_TIER_HIGH,
    "quote_per_step_cents": 2000000,
}
SALT_FLATS = {
    "title": "Salt Flats",
    "logline": "A land-speed team races the drought that is erasing their track.",
    "packaging_elements": [],
    "underlying_ip_key": "IP-SALT-FLATS",
}


def test_a_three_month_turnaround_adds_pro_rated_interest_and_the_middle_handling_tier(api):
    """A 37375000 write-off carried three months prices out at 38965937.

    PRD 3.9: "multiply `writeoff_cents` by 900 and by `months_elapsed`, then divide
    by 120,000 ... 750,000 cents when it is above 10,000,000 but at or below
    50,000,000 ... take the smaller of two figures".

    Design: Corner/calculations/turnaround_recoupment_compounds_interest_and_adds_the_middle_handling_tier
    """
    ctx = fx.turnaround_offered(api, "wrapped")
    fx.set_clock(api, "2026-12-26T00:00:00Z")

    successor = validate_success(
        api.exercise_turnaround(
            ctx.project_id,
            f.turnaround_exercise_payload(),
            business_affairs_headers(),
        ),
        201,
    )
    assert successor["dev_status"] == DEV_ACTIVE_DEVELOPMENT
    assert successor["predecessor_project_id"] == ctx.project_id

    predecessor = validate_success(
        api.get_project(ctx.project_id, business_affairs_headers())
    )
    assert predecessor["turnaround_status"] == TURNAROUND_EXERCISED
    a.assert_cents(predecessor["writeoff_cents"], 37375000, "writeoff_cents")
    # 37375000 * 900 * 3 / 120000 discards its remainder at 840937, the handling fee
    # for a write-off above 10000000 is 750000, and 135 percent of the write-off
    # would be 50456250, so the sum is the smaller figure.
    a.assert_cents(
        predecessor["recoupment_paid_cents"], 38965937, "recoupment_paid_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(
        slate, committed=33000000, writeoff=37375000, recouped=38965937
    )


def test_the_same_stored_cap_is_clamped_for_probation_and_lifted_for_premier(api):
    """One stored cap of 5 becomes an effective 1 on probation and an effective 7 at premier.

    PRD 3.1: "An agency on `PROBATION` is cut to a single submission per season
    regardless of what its baseline says - the probation ceiling is 1. An agency at
    `PREMIER` gets its `annual_submission_cap` plus a premier bonus of 2 further
    submissions."

    Design: Corner/calculations/premier_bonus_and_probation_clamp_override_the_same_stored_annual_cap
    """
    probation = fx.create_agency(
        api, {"relationship_tier": TIER_PROBATION, "annual_submission_cap": 5}
    )

    premier = validate_success(
        api.create_agency(
            f.rival_agency_payload(
                {
                    "agency_code": "MER",
                    "relationship_tier": TIER_PREMIER,
                    "annual_submission_cap": 5,
                }
            ),
            platform_admin_headers(),
        ),
        201,
    )
    assert premier["annual_submission_cap"] == 5
    assert premier["effective_submission_cap"] == 7, "5 plus the premier bonus of 2"
    assert premier["submissions_used_count"] == 0

    clamped = validate_success(
        api.get_agency(probation["id"], business_affairs_headers())
    )
    assert clamped["annual_submission_cap"] == 5, "the stored baseline is kept as filed"
    assert clamped["effective_submission_cap"] == 1, "probation discards it entirely"


def test_the_single_probation_slot_is_counted_once_per_season_year(api):
    """A 2027 pitch does not consume any part of the 2028 allotment.

    PRD 3.1: "`submissions_used_count`, which counts the agency's own pitches whose
    `status` is `SUBMITTED`, `COVERED` or `ADVANCED` and whose slate has the same
    `season_year` as the slate named in the request currently being evaluated - so
    an agency's allotment is per season, not global".

    Design: Corner/calculations/submissions_used_count_is_scoped_to_the_season_year_of_the_requested_slate
    """
    ctx = build_scenario(api, "pitch", agency={"relationship_tier": TIER_PROBATION})

    slate_2028 = validate_success(
        api.create_slate(f.cable_slate_payload(), platform_admin_headers()), 201
    )
    assert slate_2028["season_year"] == 2028

    second = validate_success(
        api.create_pitch(
            f.pitch_payload(ctx.agency_id, slate_2028["id"], dict(SALT_FLATS)),
            agency_rep_headers(ctx.agency_id),
        ),
        201,
    )
    assert second["slate_id"] == slate_2028["id"]
    assert second["status"] == PITCH_SUBMITTED

    rows, meta = validate_paginated(
        api.list_pitches(
            business_affairs_headers(),
            {"agency_id": ctx.agency_id, "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 2, "both pitches survive, so the cap is per season and not lifetime"
    a.assert_pagination_meta(meta, total_count=2)


def test_the_guild_tier_factor_scales_the_floor_before_the_fee_comparison(api):
    """One 2000000 REVISION fee floors at 2500000 for a LOW writer and 3125000 for a HIGH one.

    PRD 3.4: "That base is scaled by the writer's tier factor in basis points, which
    is 10000 for a `LOW` `guild_minimum_tier` and 12500 for `HIGH` ... A step's
    `effective_fee_cents` is then the greater of the submitted `fee_cents` and that
    scaled guild floor."

    Design: Corner/calculations/guild_floor_tier_table_lifts_the_high_tier_step_further_than_the_low_tier_step
    """
    ctx = build_scenario(
        api,
        "project",
        writer={"guild_minimum_tier": GUILD_TIER_LOW, "quote_per_step_cents": 2000000},
    )
    low_deal = fx.execute_script_deal(
        api, ctx.project_id, ctx.writer_id, steps=list(REVISION_STEP)
    )
    high_writer = fx.add_second_writer(api, ctx, dict(BEN_OKAFOR))

    high_deal = validate_success(
        api.create_script_deal(
            f.script_deal_payload(
                ctx.project_id, high_writer, steps=list(REVISION_STEP)
            ),
            business_affairs_headers(),
        ),
        201,
    )
    # The REVISION base of 2500000 times 12500 bps is 3125000, which beats the fee.
    a.assert_cents(
        high_deal["guaranteed_commitment_cents"], 3125000, "guaranteed_commitment_cents"
    )
    a.assert_cents(
        high_deal["full_option_exposure_cents"], 3125000, "full_option_exposure_cents"
    )

    low = validate_success(api.get_script_deal(low_deal["id"], business_affairs_headers()))
    # The same base times 10000 bps is 2500000, which also beats the 2000000 fee.
    a.assert_cents(
        low["guaranteed_commitment_cents"], 2500000, "guaranteed_commitment_cents"
    )

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    a.assert_cents(
        project["cumulative_dev_cost_cents"], 5625000, "cumulative_dev_cost_cents"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=5625000, available=394375000)


def test_the_posture_flips_to_restricted_at_exactly_six_thousand_basis_points(api):
    """Eleven reserved episodes of twenty is 5500 bps; a counter to twelve lands on 6000.

    PRD 2.8: "at 6000 or above the slate is `RESTRICTED`, and below it the slate is
    `OPEN`. The boundary is inclusive on the restricted side, so a slate whose
    committed and reserved episodes come to exactly sixty percent of capacity is
    `RESTRICTED`."

    Design: Corner/calculations/slate_posture_flips_to_restricted_at_exactly_six_thousand_bps_of_utilisation
    """
    ctx = build_scenario(api, "negotiation", negotiation={"episode_count": 11})

    before = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    # 11 * 10000 / 20 is 5500, which is below the threshold.
    a.assert_slate_episode_ledger(
        before, committed=0, reserved=11, available=9, posture=POSTURE_OPEN
    )

    countered = validate_success(
        api.table_round(
            ctx.negotiation_id,
            f.round_payload(12, 29000000, 1800, 60, 40),
            studio_partner_headers(),
        )
    )
    assert countered["status"] == NEG_STUDIO_COUNTER
    assert countered["round_number"] == 2
    assert countered["last_offer_side"] == OFFER_SIDE_STUDIO
    assert countered["episode_count"] == 12
    a.assert_cents(
        countered["total_license_commitment_cents"],
        348000000,
        "total_license_commitment_cents",
    )

    after = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    # 12 * 10000 / 20 is exactly 6000, and the comparison is inclusive.
    a.assert_slate_episode_ledger(
        after, committed=0, reserved=12, available=8, posture=POSTURE_RESTRICTED
    )
