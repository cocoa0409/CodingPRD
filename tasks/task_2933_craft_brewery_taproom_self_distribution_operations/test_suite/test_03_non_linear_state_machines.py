"""Parallel beer approval dimensions, and the keg's cyclic lifecycle."""

from test_helpers import (
    ADMIN,
    CELLAR,
    CHANNEL_TAPROOM,
    COMPLIANCE,
    CONTAINER_PINT_16OZ,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DESTINATION_TAPROOM,
    FILING_FORMULA,
    FILING_LABEL,
    KEG_FILLED,
    KEG_SIZE_HALF_BBL,
    LABEL_COLA_APPROVED,
    PACKAGE_HALF_BBL_KEG,
    RECON_OPEN,
    RECON_RECONCILED,
    REG_DRAFT,
    REGULATOR,
    TAPROOM,
    assert_instant_equals,
    assert_oz,
    filing_decision_payload,
    keg_clean_payload,
    keg_fill_payload,
    keg_movement_payload,
    keg_return_payload,
    pour_payload,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    complete_run,
    create_conditioning_batch,
    create_draft_beer,
    create_exempt_beer,
    create_tank,
    plan_run,
)


class TestBeerDimensionsAdvanceIndependently:
    def _label_approved_formula_rejected(self, api):
        bootstrap_brewery(api)
        beer = create_draft_beer(
            api,
            name="Barrel Reserve Tripel",
            style="Belgian Tripel",
            abv_pct=9.4,
            price_per_bbl_cents=58000,
            requires_formula=True,
        )
        validate_success(
            api.create_beer_filing(
                beer["id"],
                {
                    "filing_type": FILING_FORMULA,
                    "ingredient_list": "pilsner malt, candi sugar, coriander, brettanomyces",
                },
                COMPLIANCE,
            )
        )
        validate_success(
            api.create_beer_filing(
                beer["id"],
                {
                    "filing_type": FILING_LABEL,
                    "label_fields": {
                        "brand_name": "Barrel Reserve Tripel",
                        "abv_statement": "9.4% ALC/VOL",
                        "net_contents": "750 ML",
                        "health_warning": (
                            "GOVERNMENT WARNING: ACCORDING TO THE SURGEON GENERAL"
                        ),
                    },
                },
                COMPLIANCE,
            )
        )
        validate_success(
            api.decide_beer_filing(
                beer["id"],
                FILING_LABEL,
                filing_decision_payload(DECISION_APPROVED, cola_id="COLA-24-1188"),
                REGULATOR,
            )
        )
        return beer, validate_success(
            api.decide_beer_filing(
                beer["id"],
                FILING_FORMULA,
                filing_decision_payload(
                    DECISION_REJECTED,
                    note="brettanomyces requires a formula amendment",
                ),
                REGULATOR,
            )
        )

    def test_a_formula_rejection_leaves_an_approved_label_and_its_cola_id_intact(self, api):
        """The beer ends in DRAFT on one dimension and COLA_APPROVED on the other.

        PRD §3.1: "Those two dimensions — `registration_state` over the values
        `DRAFT`, `FORMULA_PENDING`, `FORMULA_APPROVED` and `FORMULA_EXEMPT`, and
        `label_state` over `NO_LABEL`, `COLA_PENDING`, `COLA_APPROVED` and
        `COLA_REVOKED` — live on the same beer row and advance
        **independently**. Advancing one never touches the other."

        Design: Difficulty/non_linear_state_machine/beer_registration_and_label_dimensions_advance_independently
        """
        beer, _ = self._label_approved_formula_rejected(api)

        stored = validate_success(api.get_beer(beer["id"], ADMIN))
        assert stored["registration_state"] == REG_DRAFT
        assert stored["label_state"] == LABEL_COLA_APPROVED
        assert stored["cola_id"] == "COLA-24-1188"

    def test_neither_dimension_alone_can_make_the_beer_sellable(self, api):
        """With the formula back in DRAFT both derived sellability flags are false.

        PRD §3.1: "`taproom_sellable` is true exactly when the brewery's
        `notice_status` is `ACTIVE` **and** the beer's `registration_state` is
        either `FORMULA_APPROVED` or `FORMULA_EXEMPT`; a certificate of label
        approval is emphatically **not** required to pour draft beer across the
        bar."

        Design: Difficulty/non_linear_state_machine/beer_registration_and_label_dimensions_advance_independently
        """
        beer, _ = self._label_approved_formula_rejected(api)

        stored = validate_success(api.get_beer(beer["id"], ADMIN))
        assert stored["taproom_sellable"] is False
        assert stored["distribution_sellable"] is False


class TestKegCyclesThroughASecondLap:
    def _keg_after_one_lap(self, api):
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
        runs = []
        for index in (1, 2):
            run = plan_run(
                api,
                batch["id"],
                package_type=PACKAGE_HALF_BBL_KEG,
                destination=DESTINATION_TAPROOM,
                units_planned=10,
                run_code=f"R-TAP-{index}",
            )
            runs.append(complete_run(api, run["id"], 10))
        keg = validate_success(
            api.create_keg_asset({"keg_serial": "KEG-0001", "size_bbl": KEG_SIZE_HALF_BBL}, CELLAR),
            201,
        )
        validate_success(api.clean_keg_asset(keg["id"], keg_clean_payload(200, 90), CELLAR))
        validate_success(
            api.fill_keg_asset(keg["id"], keg_fill_payload(runs[0]["id"]), CELLAR)
        )
        tapped = validate_success(
            api.move_keg_asset(keg["id"], keg_movement_payload("TAP"), TAPROOM)
        )
        validate_success(
            api.create_taproom_pour(
                pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )
        validate_success(
            api.move_keg_asset(keg["id"], keg_return_payload(15.0), TAPROOM)
        )
        return keg, runs, tapped

    def test_the_second_lap_starts_from_a_zeroed_meter_but_keeps_the_cycle_count(self, api):
        """A washed and refilled keg reports 1984.00 oz remaining and 0.00 poured.

        PRD §3.4: "On success the keg's `packaging_run_id` is set, its
        `filled_beer_id` is resolved by following the run to its batch and the
        batch to its beer, its `filled_volume_oz` is set to `size_bbl`
        multiplied by the 3,968 fluid ounces in a barrel — 1984.00 ounces for a
        half barrel, 992.00 for a quarter — its `remaining_volume_oz` is set
        equal to `filled_volume_oz`, and its `poured_volume_oz` is reset to 0."

        Design: Difficulty/non_linear_state_machine/keg_asset_cycles_back_through_clean_and_refill_from_a_second_run
        """
        keg, runs, tapped = self._keg_after_one_lap(api)

        validate_success(api.clean_keg_asset(keg["id"], keg_clean_payload(180, 75), CELLAR))
        refilled = validate_success(
            api.fill_keg_asset(keg["id"], keg_fill_payload(runs[1]["id"]), CELLAR)
        )

        assert refilled["state"] == KEG_FILLED
        assert refilled["cycle_count"] == 1
        assert refilled["packaging_run_id"] == runs[1]["id"]
        assert_oz(refilled["filled_volume_oz"], 1984.00, "filled_volume_oz")
        assert_oz(refilled["remaining_volume_oz"], 1984.00, "remaining_volume_oz")
        assert_oz(refilled["poured_volume_oz"], 0.00, "poured_volume_oz")
        assert refilled["depletion_variance_oz"] is None
        assert refilled["returned_volume_oz"] is None
        assert refilled["shrinkage_flagged"] is False
        assert_instant_equals(
            refilled["tapped_at_utc"], tapped["tapped_at_utc"], "tapped_at_utc"
        )
        assert refilled["deployment_channel"] == CHANNEL_TAPROOM

    def test_the_first_run_stays_reconciled_while_the_second_run_opens(self, api):
        """The refill opens run two; run one is terminal on its reconciliation dimension.

        PRD §3.3: "It then moves `OPEN → RECONCILED` — by system action, never
        by a client request — at the instant `kegs_outstanding_count` reaches
        zero after a returning keg is booked, provided `kegs_filled_count` is at
        least 1."

        Design: Difficulty/non_linear_state_machine/keg_asset_cycles_back_through_clean_and_refill_from_a_second_run
        """
        keg, runs, _ = self._keg_after_one_lap(api)

        validate_success(api.clean_keg_asset(keg["id"], keg_clean_payload(180, 75), CELLAR))
        validate_success(api.fill_keg_asset(keg["id"], keg_fill_payload(runs[1]["id"]), CELLAR))

        first = validate_success(api.get_packaging_run(runs[0]["id"], CELLAR))
        second = validate_success(api.get_packaging_run(runs[1]["id"], CELLAR))
        assert first["reconciliation_state"] == RECON_RECONCILED
        assert first["kegs_filled_count"] == 1
        assert first["kegs_outstanding_count"] == 0
        assert second["reconciliation_state"] == RECON_OPEN
        assert second["kegs_outstanding_count"] == 1
