"""The two elected-variant calculations: taproom excise basis and packaging loss basis."""

import pytest
from test_helpers import (
    ADMIN,
    BASIS_METERED_POUR,
    BASIS_WHOLE_KEG_REMOVAL,
    BATCH_CONDITIONING,
    BATCH_PACKAGED,
    CELLAR,
    CONTAINER_PINT_16OZ,
    DESTINATION_TAPROOM,
    KEG_SIZE_HALF_BBL,
    LOSS_BASIS_LAST_RUN_ABSORBS,
    LOSS_BASIS_PRO_RATA,
    PACKAGE_HALF_BBL_KEG,
    REPORT_DRAFT,
    TANK_DIRTY,
    TAPROOM,
    assert_bbl,
    assert_cents,
    excise_report_payload,
    pour_payload,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    complete_run,
    create_conditioning_batch,
    create_exempt_beer,
    create_completed_run,
    create_tank,
    create_tapped_keg,
    plan_run,
    set_clock,
)


def _tapped_keg_with_three_pints(api):
    """Brewery ACTIVE, one taproom keg tapped inside August, three 16 oz pints pulled."""
    set_clock(api, "2026-08-01T00:00:00Z")
    bootstrap_brewery(api)
    beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000)
    tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
    batch = create_conditioning_batch(
        api,
        beer["id"],
        tank["id"],
        actual_yield_bbl=16.000,
        batch_code="B-1001",
        planned_volume_bbl=16.00,
        brew_start_utc="2026-08-01T06:00:00Z",
        brew_end_utc="2026-08-08T06:00:00Z",
        loss_basis=LOSS_BASIS_PRO_RATA,
    )
    run = create_completed_run(
        api,
        batch["id"],
        package_type=PACKAGE_HALF_BBL_KEG,
        destination=DESTINATION_TAPROOM,
        units_planned=10,
        run_code="R-TAP-1",
    )
    set_clock(api, "2026-08-10T12:00:00Z")
    keg = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
    for _ in range(3):
        validate_success(
            api.create_taproom_pour(
                pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )
    set_clock(api, "2026-09-01T00:00:00Z")
    return {"beer": beer, "tank": tank, "batch": batch, "run": run, "keg": keg}


AUGUST = {
    "period_start_utc": "2026-08-01T00:00:00Z",
    "period_end_utc": "2026-09-01T00:00:00Z",
}


class TestTaproomBasisDivergence:
    def test_metered_pour_basis_taxes_only_the_forty_eight_ounces_actually_served(self, api):
        """Under METERED_POUR the return taxes 48 oz, which is 0.012 bbl.

        PRD §3.8: "Under a `taproom_basis` of `METERED_POUR`, the brewery is
        taxed only on what it actually served. `taproom_bbl` is the sum of
        `volume_oz` over every taproom pour whose `poured_at_utc` falls inside
        the window, regardless of `container_type` — a four-ounce sample counts
        for exactly its four ounces and a growler for its sixty-four — divided
        by the 3,968 fluid ounces in a barrel, rounded half up to three decimal
        places."

        Design: Difficulty/dual_variant_calc/taproom_basis_metered_pour_vs_whole_keg_removal_divergence
        """
        _tapped_keg_with_three_pints(api)

        report = validate_success(
            api.create_excise_report(
                excise_report_payload(taproom_basis=BASIS_METERED_POUR, **AUGUST), ADMIN
            ),
            201,
        )

        assert report["state"] == REPORT_DRAFT
        assert_bbl(report["taproom_bbl"], 0.012, "taproom_bbl")
        assert_bbl(report["distribution_bbl"], 0.000, "distribution_bbl")
        assert_bbl(report["total_taxable_bbl"], 0.012, "total_taxable_bbl")
        assert_cents(report["federal_tax_cents"], 4, "federal_tax_cents")
        assert_cents(report["state_tax_cents"], 7, "state_tax_cents")
        assert_cents(report["total_tax_due_cents"], 11, "total_tax_due_cents")

    def test_whole_keg_basis_taxes_the_entire_container_at_the_moment_it_was_tapped(self, api):
        """Under WHOLE_KEG_REMOVAL the same data yields 0.500 bbl, a 0.488 divergence.

        PRD §3.8: "The divergence is not marginal: a half-barrel keg tapped
        inside the window from which three sixteen-ounce pints were pulled
        yields forty-eight ounces divided by 3,968, which is 0.012 barrels on
        the metered basis, against the keg's full 0.500 barrels on the whole-keg
        basis — a gap of 0.488 barrels on identical data."

        Design: Difficulty/dual_variant_calc/taproom_basis_metered_pour_vs_whole_keg_removal_divergence
        """
        _tapped_keg_with_three_pints(api)

        metered = validate_success(
            api.create_excise_report(
                excise_report_payload(taproom_basis=BASIS_METERED_POUR, **AUGUST), ADMIN
            ),
            201,
        )
        whole_keg = validate_success(
            api.create_excise_report(
                excise_report_payload(taproom_basis=BASIS_WHOLE_KEG_REMOVAL, **AUGUST),
                ADMIN,
            ),
            201,
        )

        assert whole_keg["state"] == REPORT_DRAFT
        assert_bbl(whole_keg["taproom_bbl"], 0.500, "whole-keg taproom_bbl")
        assert_bbl(whole_keg["distribution_bbl"], 0.000, "distribution_bbl")
        assert_cents(whole_keg["federal_tax_cents"], 175, "federal_tax_cents")
        assert_cents(whole_keg["state_tax_cents"], 272, "state_tax_cents")
        assert_cents(whole_keg["total_tax_due_cents"], 447, "total_tax_due_cents")
        assert whole_keg["taproom_bbl"] - metered["taproom_bbl"] == pytest.approx(
            0.488, abs=0.0005
        )


def _batch_with_two_completed_and_one_planned_run(api, beer_id, tank_id, batch_code, loss_basis, prefix):
    """A 16.000 bbl batch with two certified 5.000 bbl runs and a third still PLANNED."""
    batch = create_conditioning_batch(
        api,
        beer_id,
        tank_id,
        actual_yield_bbl=16.000,
        batch_code=batch_code,
        planned_volume_bbl=16.00,
        brew_start_utc="2026-08-01T06:00:00Z",
        brew_end_utc="2026-08-08T06:00:00Z",
        loss_basis=loss_basis,
    )
    runs = []
    for index in (1, 2):
        run = plan_run(
            api,
            batch["id"],
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=10,
            run_code=f"{prefix}-{index}",
        )
        complete_run(api, run["id"], 10)
        runs.append(run)
    third = plan_run(
        api,
        batch["id"],
        package_type=PACKAGE_HALF_BBL_KEG,
        destination=DESTINATION_TAPROOM,
        units_planned=10,
        run_code=f"{prefix}-3",
    )
    runs.append(third)
    return batch, runs


class TestPackagingLossBasisDivergence:
    def test_pro_rata_rounds_each_share_independently_and_gives_the_remainder_to_one_run(self, api):
        """PRO_RATA over three equal runs yields 0.334 / 0.333 / 0.333.

        PRD §3.3: "Worked through: a batch with an `actual_yield_bbl` of 16.000
        packaged by three runs of 5.000 barrels each has a total loss of 1.000
        barrels; each raw share is one barrel times five barrels divided by
        fifteen barrels, which is 0.333 after independent rounding; the three
        rounded shares sum to 0.999; the 0.001 remainder goes to the
        earliest-created run because all three tie on `bbl_removed`; and the
        result is 0.334, 0.333, 0.333."

        Design: Difficulty/dual_variant_calc/packaging_loss_basis_pro_rata_vs_last_run_absorbs_divergence
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000)
        tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
        batch, runs = _batch_with_two_completed_and_one_planned_run(
            api, beer["id"], tank["id"], "B-PRO", LOSS_BASIS_PRO_RATA, "R-PRO"
        )
        assert validate_success(api.get_batch(batch["id"], CELLAR))["state"] == BATCH_CONDITIONING

        complete_run(api, runs[2]["id"], 10)

        closed = validate_success(api.get_batch(batch["id"], CELLAR))
        assert closed["state"] == BATCH_PACKAGED
        assert_bbl(closed["packaged_bbl"], 15.000, "packaged_bbl")
        assert_bbl(closed["remaining_bbl"], 1.000, "remaining_bbl")
        assert_bbl(closed["total_loss_bbl"], 1.000, "total_loss_bbl")

        shares = [
            validate_success(api.get_packaging_run(run["id"], CELLAR))["loss_share_bbl"]
            for run in runs
        ]
        assert_bbl(shares[0], 0.334, "earliest run loss_share_bbl")
        assert_bbl(shares[1], 0.333, "second run loss_share_bbl")
        assert_bbl(shares[2], 0.333, "third run loss_share_bbl")
        assert sum(shares) == pytest.approx(1.000, abs=0.0005)
        assert validate_success(api.get_tank(tank["id"], CELLAR))["status"] == TANK_DIRTY

    def test_last_run_absorbs_puts_the_whole_loss_on_the_final_run(self, api):
        """LAST_RUN_ABSORBS over the same shape yields 0.000 / 0.000 / 1.000.

        PRD §3.3: "Under a `loss_basis` of `LAST_RUN_ABSORBS`, every completed
        run except one is set to 0.000 and the **final run by `created_at`
        ascending** absorbs the entire total loss as its `loss_share_bbl`."

        Design: Difficulty/dual_variant_calc/packaging_loss_basis_pro_rata_vs_last_run_absorbs_divergence
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000)
        tank = create_tank(api, code="FV-02", capacity_bbl=30.00)
        batch, runs = _batch_with_two_completed_and_one_planned_run(
            api, beer["id"], tank["id"], "B-LRA", LOSS_BASIS_LAST_RUN_ABSORBS, "R-LRA"
        )

        complete_run(api, runs[2]["id"], 10)

        closed = validate_success(api.get_batch(batch["id"], CELLAR))
        assert closed["state"] == BATCH_PACKAGED
        assert_bbl(closed["total_loss_bbl"], 1.000, "total_loss_bbl")

        shares = [
            validate_success(api.get_packaging_run(run["id"], CELLAR))["loss_share_bbl"]
            for run in runs
        ]
        assert_bbl(shares[0], 0.000, "first run loss_share_bbl")
        assert_bbl(shares[1], 0.000, "second run loss_share_bbl")
        assert_bbl(shares[2], 1.000, "final run loss_share_bbl")
        assert sum(shares) == pytest.approx(1.000, abs=0.0005)
        assert validate_success(api.get_tank(tank["id"], CELLAR))["status"] == TANK_DIRTY
