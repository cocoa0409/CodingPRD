"""Variant-selecting calculations: the availability basis and the royalty basis.

Both families run the same inputs through two declared variants and pin the
divergence the variant choice produces.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import WindOpsApiClient
from test_helpers.assertions import assert_cents, assert_four_dp, assert_two_dp
from test_helpers.constants import (
    AGREEMENT_IN_SETTLEMENT,
    CURTAILMENT_RELEASED,
    ROYALTY_DEEMED_INCLUSIVE,
    ROYALTY_METERED_ONLY,
    SETTLEMENT_DRAFT,
)
from test_helpers.fixtures import (
    create_settlement,
    farm_version,
    read_farm,
    setup_availability_basis_divergence,
    setup_royalty_basis_divergence,
)
from test_helpers.test_users import make_commercial_headers

COMMERCIAL = make_commercial_headers()


# ===========================================================================
# Difficulty / dual_variant_calc
# ===========================================================================
def test_both_availability_figures_are_identical_under_either_basis(api: WindOpsApiClient):
    """PRD 3.9: "The two figures are computed from identical period data and, in general,
    they do not agree."

    Design: Difficulty/dual_variant_calc/availability_time_basis_vs_energy_basis_diverge_on_identical_period_data
    """
    world = setup_availability_basis_divergence(api)

    time_based = validate_success(api.settle_agreement(world["sa_time"]["id"], COMMERCIAL))
    energy_based = validate_success(api.settle_agreement(world["sa_energy"]["id"], COMMERCIAL))

    for settled in (time_based, energy_based):
        assert settled["state"] == AGREEMENT_IN_SETTLEMENT
        assert_four_dp(settled["time_based_availability_pct"], 98.3333, "time_based")
        assert_four_dp(settled["energy_based_availability_pct"], 83.3333, "energy_based")

    assert (
        time_based["time_based_availability_pct"]
        == energy_based["time_based_availability_pct"]
    ), "both agreements must compute the same time-based figure from the same period data"
    assert (
        time_based["energy_based_availability_pct"]
        == energy_based["energy_based_availability_pct"]
    ), "both agreements must compute the same energy-based figure from the same period data"


def test_availability_basis_selects_which_figure_the_assessment_reads(api: WindOpsApiClient):
    """PRD 3.9: "Under a `TIME_BASED` agreement the basis figure is
    `time_based_availability_pct`, which ignores telemetry entirely and depends only on counted
    downtime hours and the turbine count. Under an `ENERGY_BASED` agreement the basis figure is
    `energy_based_availability_pct`, which ignores downtime intervals entirely and depends only
    on metered against potential energy."

    Design: Difficulty/dual_variant_calc/availability_time_basis_vs_energy_basis_diverge_on_identical_period_data
    """
    world = setup_availability_basis_divergence(api)

    time_based = validate_success(api.settle_agreement(world["sa_time"]["id"], COMMERCIAL))
    energy_based = validate_success(api.settle_agreement(world["sa_energy"]["id"], COMMERCIAL))

    # 98.3333 clears the 97.0000 guarantee, so the time-based assessment is nil.
    assert_cents(time_based["assessed_lda_cents"], 0, "TIME_BASED assessed_lda_cents")
    # 83.3333 falls 13.6667 points short, charged at 500000 cents per point under a
    # 20000000 cent cap.
    assert_cents(
        energy_based["assessed_lda_cents"], 6833350, "ENERGY_BASED assessed_lda_cents"
    )
    assert time_based["assessed_lda_cents"] != energy_based["assessed_lda_cents"], (
        "the basis choice must change the assessment even on identical period data"
    )


def test_metered_only_royalty_ignores_the_released_compensable_curtailment(
    api: WindOpsApiClient,
):
    """PRD 3.9: "`deemed_kwh` depends on the basis and is where the two variants diverge: under
    `METERED_ONLY` it is forced to 0, so compensable grid curtailment earns the landowner nothing
    even though the operator was compensated for it, while under `DEEMED_INCLUSIVE` it is the sum,
    over every curtailment order on those turbines whose `state` is `RELEASED` and whose
    `compensable` is true, of that order's hours of overlap with the half-open settlement period
    multiplied by its `deemed_kwh_per_hour`."

    Design: Difficulty/dual_variant_calc/landowner_royalty_metered_only_vs_deemed_inclusive_diverge_on_same_curtailment
    """
    world = setup_royalty_basis_divergence(api)
    curtailment = world["curtailment"]
    assert curtailment["compensable"] is True, "a GRID curtailment is compensable"
    assert curtailment["state"] == CURTAILMENT_RELEASED
    assert_two_dp(curtailment["curtailed_hours"], 24, "curtailed_hours")

    metered = create_settlement(
        api,
        world["farm"]["id"],
        farm_version(api, world["farm"]["id"]),
        parcel_code="P-METERED",
        royalty_basis=ROYALTY_METERED_ONLY,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
        royalty_pct=4.0,
        minimum_payment_cents=200000,
        energy_price_cents_per_kwh=6,
        road_damage_assessment_cents=0,
    )

    assert metered["metered_kwh"] == 1000000
    assert metered["deemed_kwh"] == 0, "METERED_ONLY forces the deemed component to zero"
    assert_cents(metered["royalty_cents"], 240000, "royalty_cents")
    assert_cents(metered["payment_cents"], 240000, "payment_cents")
    assert metered["state"] == SETTLEMENT_DRAFT


def test_deemed_inclusive_royalty_scales_the_same_curtailment_into_the_payment(
    api: WindOpsApiClient,
):
    """PRD 3.9: "Because `deemed_kwh` is added to the base rather than substituted into it, a
    `DEEMED_INCLUSIVE` settlement produces a strictly larger royalty than a `METERED_ONLY`
    settlement for identical farm telemetry whenever any compensable curtailment falls in the
    period."

    Design: Difficulty/dual_variant_calc/landowner_royalty_metered_only_vs_deemed_inclusive_diverge_on_same_curtailment
    """
    world = setup_royalty_basis_divergence(api)
    farm_id = world["farm"]["id"]

    metered = create_settlement(
        api,
        farm_id,
        farm_version(api, farm_id),
        parcel_code="P-METERED",
        royalty_basis=ROYALTY_METERED_ONLY,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
        royalty_pct=4.0,
        minimum_payment_cents=200000,
        energy_price_cents_per_kwh=6,
        road_damage_assessment_cents=0,
    )
    deemed = create_settlement(
        api,
        farm_id,
        farm_version(api, farm_id),
        parcel_code="P-DEEMED",
        royalty_basis=ROYALTY_DEEMED_INCLUSIVE,
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-07-01T00:00:00Z",
        royalty_pct=4.0,
        minimum_payment_cents=200000,
        energy_price_cents_per_kwh=6,
        road_damage_assessment_cents=0,
    )

    assert deemed["metered_kwh"] == 1000000
    # PRD 3.9 clips "that order's span from `start_utc` to `end_utc`" against the
    # settlement period, so the released order contributes its whole 48-hour span
    # (2026-06-10 to 2026-06-12, entirely inside June) at 1800 deemed kWh per hour.
    assert deemed["deemed_kwh"] == 86400
    assert_cents(deemed["royalty_cents"], 260736, "royalty_cents")
    assert_cents(deemed["payment_cents"], 260736, "payment_cents")
    assert deemed["royalty_cents"] > metered["royalty_cents"], (
        "the deemed component must raise the royalty above the metered-only variant"
    )

    assert deemed["state"] == SETTLEMENT_DRAFT
    farm = read_farm(api, farm_id)
    assert_cents(farm["opex_accrued_cents"], 0, "a draft settlement posts nothing")
