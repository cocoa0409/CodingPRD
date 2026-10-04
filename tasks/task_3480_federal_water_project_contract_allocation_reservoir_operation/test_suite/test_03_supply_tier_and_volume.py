"""Declared-supply arithmetic, shortage-tier boundaries, and release volume.

Covers the flood-holdback conditional on the publish month, the strict
0.75 / 0.50 tier boundaries, latest-observation selection for the forecast,
per-release round-half-up volume conversion, and the ACTIVE-only input set
of the publish - PRD §2.6, §3.2 and §3.3.
"""

from test_helpers import (
    assert_instant,
    factories,
    fixtures,
)


def test_supply_minmax_flood_holdback(api):
    """Identical observations declare 7,500 when published in a flood month
    (January: holdback 2,000 applies) and 9,500 when published in April
    (holdback branch off) - the 2,000 delta is the FLOOD_MONTHS conditional.

    PRD §3.3: "When the logical-clock calendar month at publish is November,
    December, January, February, or March, a flood-control holdback equal to
    `flood_control_max_storage_af` multiplied by one tenth, rounded half up
    to whole acre-feet, is applied; in all other months the holdback is zero.
    The `declared_supply_af` is usable storage plus the adjusted forecast
    minus the holdback, floored at zero."

    Design: Difficulty/combinatorial_formula/supply_minmax_flood_holdback
    """
    # Small reservoir: usable = 10,500 - 5,000 = 5,500; snowpack 80 with
    # runoff 5,000 adjusts to round(5,000*80/100) = 4,000.
    world = fixtures.setup_announced_year(api)
    first = world["announcement"]
    assert first["declared_supply_af"] == 7_500, (
        "January publish: 5,500 + 4,000 - holdback round(20,000*0.10)=2,000"
    )

    april = fixtures.publish_revision(api, world, clock="2027-04-01T00:00:00Z")
    assert april["declared_supply_af"] == 9_500, (
        "April publish of identical observations: 5,500 + 4,000 - 0"
    )
    assert april["declared_supply_af"] - first["declared_supply_af"] == 2_000, (
        "the whole delta is the flood-month holdback branch"
    )

    superseded = fixtures.find_announcement(api, world["year"]["id"], first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert april["status"] == "PUBLISHED"


def test_tier_boundary_ratio_exact_075(api):
    """Declared 7,500 against total maximum 10,000 is exactly ratio 0.75 and
    classifies NONE; one acre-foot lower (7,499) classifies TIER_1 - the
    boundary is strict less-than.

    PRD §3.3: "Otherwise the ratio of `declared_supply_af` to the total
    maximum is compared in exact arithmetic, without float rounding: strictly
    below 0.50 classifies `TIER_2`; otherwise strictly below 0.75 classifies
    `TIER_1`; otherwise `NONE`. The boundaries are strict — a ratio of
    exactly 0.50 classifies `TIER_1`, and exactly 0.75 classifies `NONE`."

    Design: Difficulty/boundary_precision_check/tier_boundary_ratio_exact_075
    """
    world = fixtures.setup_announced_year(api)
    first = world["announcement"]
    assert first["declared_supply_af"] == 7_500
    assert first["shortage_tier"] == "NONE", "ratio exactly 0.75 must not trip TIER_1"

    revision = fixtures.publish_revision(api, world, runoff=4_999)
    # round(4,999*80/100) = 3,999 -> declared 5,500 + 3,999 - 2,000 = 7,499.
    assert revision["declared_supply_af"] == 7_499
    assert revision["shortage_tier"] == "TIER_1", "0.7499 is strictly below 0.75"

    assert world["line_sr"]["allocated_af"] == 6_000
    assert world["line_jr"]["allocated_af"] == 1_499, (
        "waterfall on 7,499: senior takes 6,000, junior gets the 1,499 remainder"
    )


def test_supply_uses_latest_observation_by_observed_on(api):
    """The later-observed runoff forecast governs regardless of posting
    order: 3,000 observed 2027-01-20 supersedes 5,000 observed 2027-01-10,
    so the declared supply is 5,900, not 7,500.

    PRD §3.2: "When several observations of the same type exist for a year,
    the one with the latest `observed_on` governs any forecast calculation,
    with ties broken toward the later `created_at`."

    Design: Corner/calculations/supply_uses_latest_observation_by_observed_on
    """
    world = fixtures.setup_open_year(api)
    fixtures.post_observation(
        api,
        world["year"]["id"],
        factories.runoff_forecast_payload(3_000, "2027-01-20T00:00:00Z"),
    )

    announcement = fixtures.publish_new_announcement(api, world)

    # usable 5,500 + round(3,000*80/100) - 2,000.
    assert announcement["declared_supply_af"] == 5_900
    assert announcement["declared_supply_af"] != 7_500, (
        "the stale earlier-observed 5,000 forecast must be excluded"
    )


def test_volume_conversion_applies_half_up_precision(api):
    """A 7 cfs x 3 day release is 41.6535 af and rounds half up to exactly
    42 af at creation; scheduled_end is start plus 3 days, exclusive.

    PRD §3.5: "The order's `scheduled_end` is derived as `scheduled_start`
    plus `duration_days` days and acts as the exclusive end of a half-open
    window, and its `volume_af` is derived once, at creation, as
    `release_cfs` multiplied by `duration_days` multiplied by 1.9835, rounded
    half up to whole acre-feet; this per-release rounding is never re-derived
    from other releases."

    Design: Corner/calculations/volume_conversion_applies_half_up_precision
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)

    release = fixtures.create_release(
        api,
        world["reservoir"]["id"],
        purpose="ENVIRONMENTAL",
        release_cfs=7,
        duration_days=3,
        scheduled_start="2027-02-01T00:00:00Z",
    )

    assert release["volume_af"] == 42, "round_half_up(7 * 3 * 1.9835) = round_half_up(41.6535)"
    assert_instant(release["scheduled_end"], "2027-02-04T00:00:00Z", "release.scheduled_end")
    assert release["status"] == "SCHEDULED"


def test_suspended_contract_skipped_by_next_publish(api):
    """The publish input set is ACTIVE contracts only: a contract suspended
    before the first publish gets no allocation line, and the tier ratio is
    computed against the reduced total maximum (7,500 / 6,000 -> NONE).

    PRD §3.3: "The total maximum is the sum of `max_annual_quantity_af` over
    all `ACTIVE` contracts"
    PRD §3.3: "One allocation line is created per `ACTIVE` contract, each
    tied back to its announcement through `announcement_id` and to its
    contract through `contract_id`."

    Design: Corner/state_machines/suspended_contract_skipped_by_next_publish
    """
    world = fixtures.setup_open_year(api)
    fixtures.suspend_contract(api, world["contract_jr"]["id"])

    # Create and publish by hand: the suspended junior contract must simply
    # receive no line, so the world's per-contract line refresh cannot run.
    year = fixtures.refresh_year(api, world)
    draft = fixtures.create_announcement(api, year["id"], year["version"])
    announcement = fixtures.publish_announcement(api, draft["id"])

    lines, meta = fixtures.rows(
        api.list_allocation_lines(
            fixtures.READ_HEADERS, {"announcement_id": announcement["id"], "limit": 100}
        )
    )
    assert len(lines) == 1, f"only the ACTIVE senior contract gets a line, got {len(lines)}"
    assert lines[0]["contract_id"] == world["contract_sr"]["id"]
    assert lines[0]["allocated_af"] == 6_000, "waterfall: min(6,000, 7,500)"

    assert announcement["declared_supply_af"] == 7_500
    assert announcement["shortage_tier"] == "NONE", (
        "total maximum is 6,000 once C-200 is SUSPENDED: 7,500/6,000 >= 0.75"
    )
