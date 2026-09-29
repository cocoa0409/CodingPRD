"""Three-hop cascades: the notice suspension, and a keg coming back empty."""

from test_helpers import (
    ADMIN,
    CELLAR,
    CONTAINER_PINT_16OZ,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    KEG_EMPTY_DIRTY,
    KEG_SIZE_HALF_BBL,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_SUSPENDED,
    NOTICE_SUSPENDED,
    ORDER_REJECTED,
    PACKAGE_HALF_BBL_KEG,
    RECON_RECONCILED,
    REJECTION_NOTICE_SUSPENDED,
    RUN_COMPLETED,
    TAPROOM,
    assert_bbl,
    assert_oz,
    keg_return_payload,
    pour_payload,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_allocated_order,
    create_completed_run,
    create_conditioning_batch,
    create_distribution_ready_beer,
    create_exempt_beer,
    create_license,
    create_tank,
    create_tapped_keg,
    suspend_notice,
)

SUSPENSION_REASON = "TTB audit hold on brewer's notice BR-OR-4417"


def _allocated_self_distributed_order(api):
    """An ACTIVE licence, a certified 5.000 bbl distribution run, 3.00 bbl reserved."""
    bootstrap_brewery(api, home_state_code="OR", ttb_brewers_notice_number="BR-OR-4417")
    beer = create_distribution_ready_beer(
        api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
    )
    license_row = create_license(
        api,
        "ID",
        LICENSE_SELF_DISTRIBUTION,
        annual_barrel_cap=1000.00,
        franchise_state=False,
        effective_from_utc="2026-01-01T00:00:00Z",
        expires_at_utc="2027-01-01T00:00:00Z",
    )
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
    )
    run = create_completed_run(
        api,
        batch["id"],
        package_type=PACKAGE_HALF_BBL_KEG,
        destination=DESTINATION_DISTRIBUTION,
        units_planned=10,
        run_code="R-DIST-1",
    )
    order = create_allocated_order(
        api,
        beer["id"],
        license_row["id"],
        bbl_requested=3.00,
        ship_to_state_code="ID",
        distance_miles=120,
        requested_ship_utc="2026-08-15T15:00:00Z",
        order_code="SO-4001",
    )
    return beer, license_row, run, order


class TestNoticeSuspensionCascade:
    def test_hop_one_and_two_suspend_the_licence_and_reject_its_allocated_order(self, api):
        """One SUSPEND leaves the licence SUSPENDED and the order REJECTED/NOTICE_SUSPENDED.

        PRD §3.1: "First, every state licence whose `status` is `ACTIVE` moves to
        `SUSPENDED`. Second — caused by that licence change, not by the notice
        change — every distribution order citing a licence that just moved, and
        whose own `state` is `SUBMITTED` or `ALLOCATED`, moves to `REJECTED` with
        `rejection_reason` set to `NOTICE_SUSPENDED`."

        Design: Difficulty/transitive_cascade/notice_suspension_cascades_license_to_order_to_released_run_allocation
        """
        beer, license_row, _, order = _allocated_self_distributed_order(api)

        brewery = suspend_notice(api, reason=SUSPENSION_REASON)

        assert brewery["notice_status"] == NOTICE_SUSPENDED
        assert brewery["suspension_reason"] == SUSPENSION_REASON
        assert (
            validate_success(api.get_state_license(license_row["id"], ADMIN))["status"]
            == LICENSE_SUSPENDED
        )
        rejected = validate_success(api.get_distribution_order(order["id"], ADMIN))
        assert rejected["state"] == ORDER_REJECTED
        assert rejected["rejection_reason"] == REJECTION_NOTICE_SUSPENDED
        stored_beer = validate_success(api.get_beer(beer["id"], ADMIN))
        assert stored_beer["taproom_sellable"] is False
        assert stored_beer["distribution_sellable"] is False

    def test_hop_three_returns_the_reserved_barrels_to_the_run_it_drew_them_from(self, api):
        """The released reservation reappears as available_bbl three edges away.

        PRD §3.1: "Third — caused by those rejections — every order that had been
        in `ALLOCATED` releases each entry of its `allocation_lines`: the cited
        packaging run's `allocated_bbl` falls by that entry's barrel figure while
        its `available_bbl` rises by the same amount, and the order's own
        `allocation_lines` becomes an empty list with `allocated_bbl` returning
        to 0.000."

        Design: Difficulty/transitive_cascade/notice_suspension_cascades_license_to_order_to_released_run_allocation
        """
        _, license_row, run, order = _allocated_self_distributed_order(api)
        before = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_bbl(before["allocated_bbl"], 3.000, "allocated_bbl before the cascade")
        assert_bbl(before["available_bbl"], 2.000, "available_bbl before the cascade")

        suspend_notice(api, reason=SUSPENSION_REASON)

        released = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert_bbl(released["allocated_bbl"], 0.000, "allocated_bbl")
        assert_bbl(released["available_bbl"], 5.000, "available_bbl")
        assert_bbl(released["shipped_bbl"], 0.000, "shipped_bbl")
        assert_bbl(released["bbl_removed"], 5.000, "bbl_removed")
        rejected = validate_success(api.get_distribution_order(order["id"], ADMIN))
        assert_bbl(rejected["allocated_bbl"], 0.000, "order allocated_bbl")
        assert rejected["allocation_lines"] == []
        assert_bbl(
            validate_success(api.get_state_license(license_row["id"], ADMIN))[
                "barrels_shipped_ytd"
            ],
            0.000,
            "barrels_shipped_ytd",
        )


def _two_kegs_one_already_returned(api):
    """A taproom run with two filled kegs; KEG-0001 is back inside tolerance."""
    bootstrap_brewery(api)
    beer = create_exempt_beer(
        api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
    )
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
    )
    run = create_completed_run(
        api,
        batch["id"],
        package_type=PACKAGE_HALF_BBL_KEG,
        destination=DESTINATION_TAPROOM,
        units_planned=10,
        run_code="R-TAP-1",
    )
    first = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
    for _ in range(2):
        validate_success(
            api.create_taproom_pour(
                pour_payload(first["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )
    second = create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0002")
    for _ in range(4):
        validate_success(
            api.create_taproom_pour(
                pour_payload(second["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )
    # Both kegs are filled from the run before either comes back, so
    # kegs_outstanding_count only reaches zero on the SECOND return. §3.3 makes
    # RECONCILED terminal on that dimension, so returning KEG-0001 while it is
    # the run's only outstanding keg would reconcile the run one keg early.
    validate_success(api.move_keg_asset(first["id"], keg_return_payload(15.0), TAPROOM))
    return run, first, second


class TestKegReturnCascade:
    def test_the_tolerance_flags_one_sibling_keg_and_spares_the_other(self, api):
        """A 64 oz shortfall is flagged where a 32 oz shortfall on the same fill is not.

        PRD §3.4: "For a half-barrel keg filled with 1984.00 ounces the tolerance
        is 39.68 ounces, so a variance of exactly −39.68 ounces is **not**
        flagged while −39.69 ounces is."

        Design: Difficulty/transitive_cascade/keg_return_cascades_variance_to_outstanding_count_to_run_reconciliation
        """
        _, first, second = _two_kegs_one_already_returned(api)

        returned = validate_success(
            api.move_keg_asset(second["id"], keg_return_payload(14.5), TAPROOM)
        )

        assert returned["state"] == KEG_EMPTY_DIRTY
        assert_oz(returned["returned_volume_oz"], 1856.00, "returned_volume_oz")
        assert_oz(returned["depletion_variance_oz"], -64.00, "depletion_variance_oz")
        assert returned["shrinkage_flagged"] is True
        assert returned["cycle_count"] == 1
        sibling = validate_success(api.get_keg_asset(first["id"], CELLAR))
        assert_oz(sibling["depletion_variance_oz"], -32.00, "sibling variance")
        assert sibling["shrinkage_flagged"] is False

    def test_the_last_keg_back_reconciles_the_run_and_sums_both_variances(self, api):
        """kegs_outstanding_count reaching zero flips the run to RECONCILED at -96.00 oz.

        PRD §3.4: "The third hop follows from the second: when that count reaches
        zero and the run's `kegs_filled_count` is at least 1, the run's
        `reconciliation_state` moves `OPEN → RECONCILED` and its
        `keg_shrinkage_oz` is written as the sum of `depletion_variance_oz` over
        every keg asset still linked to the run — including the kegs whose own
        variance sat comfortably inside tolerance — rounded half up to two
        decimal places."

        Design: Difficulty/transitive_cascade/keg_return_cascades_variance_to_outstanding_count_to_run_reconciliation
        """
        run, _, second = _two_kegs_one_already_returned(api)
        assert (
            validate_success(api.get_packaging_run(run["id"], CELLAR))[
                "kegs_outstanding_count"
            ]
            == 1
        )

        validate_success(api.move_keg_asset(second["id"], keg_return_payload(14.5), TAPROOM))

        reconciled = validate_success(api.get_packaging_run(run["id"], CELLAR))
        assert reconciled["kegs_outstanding_count"] == 0
        assert reconciled["kegs_filled_count"] == 2
        assert reconciled["reconciliation_state"] == RECON_RECONCILED
        assert_oz(reconciled["keg_shrinkage_oz"], -96.00, "keg_shrinkage_oz")
        assert reconciled["state"] == RUN_COMPLETED
        assert_bbl(reconciled["bbl_removed"], 5.000, "bbl_removed")
