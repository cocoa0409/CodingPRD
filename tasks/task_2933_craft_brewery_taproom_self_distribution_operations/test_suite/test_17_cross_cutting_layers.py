"""Optimistic concurrency on both guarded parents, and the cumulative credit threshold."""

from test_helpers import (
    ADMIN,
    APPT_PROPOSED,
    BASIS_WHOLE_KEG_REMOVAL,
    BATCH_CONDITIONING,
    CELLAR,
    COMPLIANCE,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_LICENSE_VERSION,
    KEG_SIZE_HALF_BBL,
    LICENSE_WHOLESALER_ONLY,
    PACKAGE_HALF_BBL_KEG,
    REPORT_DRAFT,
    REPORT_FILED,
    RUN_PLANNED,
    SCOPE_ALL_BRANDS,
    appointment_payload,
    assert_bbl,
    assert_cents,
    license_ytd_payload,
    packaging_run_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_completed_run,
    create_conditioning_batch,
    create_exempt_beer,
    create_license,
    create_tank,
    create_tapped_keg,
    draft_report,
    file_report,
    set_brewery_carry_in,
    set_clock,
)
from test_helpers.test_users import USER_ADMIN_1

LICENSE_WINDOW = {
    "effective_from_utc": "2026-01-01T00:00:00Z",
    "expires_at_utc": "2027-01-01T00:00:00Z",
}


class TestStaleBatchVersion:
    def test_the_first_create_spends_the_version_and_a_re_read_restores_it(self, api):
        """A legal second run is refused at 412, then accepted verbatim after one GET.

        PRD §2.7: "A request to create a packaging run must carry
        `expected_batch_version` as a required, non-optional field holding the
        `version` of the target batch as the client last observed it."

        PRD §2.7: "Creating the run itself increments the batch's `version` by 1, so
        a second create replayed from the same observed version is rejected."

        PRD §3.3: "Creation nevertheless increments the owning batch's `version` by
        1, because the run has staked a claim on the batch's remaining volume; that
        increment is exactly what makes a second create replayed from the same
        observed version fail the stale-batch check."

        Design: Corner/cross_cutting_complexity_layers/stale_batch_version_blocks_a_second_planned_run_and_a_refresh_lets_it_through
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
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
        batch_v = batch["version"]

        first = validate_success(
            api.create_packaging_run(
                packaging_run_payload(
                    batch["id"],
                    batch_v,
                    package_type=PACKAGE_HALF_BBL_KEG,
                    destination=DESTINATION_DISTRIBUTION,
                    units_planned=10,
                    run_code="R-1",
                ),
                CELLAR,
            ),
            201,
        )
        assert first["state"] == RUN_PLANNED
        assert_bbl(first["bbl_removed"], 0.000, "bbl_removed")

        replay = packaging_run_payload(
            batch["id"],
            batch_v,
            package_type=PACKAGE_HALF_BBL_KEG,
            destination=DESTINATION_TAPROOM,
            units_planned=4,
            run_code="R-2",
        )
        validate_error(
            api.create_packaging_run(replay, CELLAR), ERR_STALE_BATCH_VERSION, 412
        )
        _, refused_meta = validate_paginated(
            api.list_packaging_runs(CELLAR, {"batch_id": batch["id"]})
        )
        assert refused_meta["total_count"] == 1

        refreshed = validate_success(api.get_batch(batch["id"], CELLAR))
        batch_v2 = refreshed["version"]
        assert batch_v2 == batch_v + 1

        replay["expected_batch_version"] = batch_v2
        second = validate_success(api.create_packaging_run(replay, CELLAR), 201)

        assert second["state"] == RUN_PLANNED
        assert second["destination"] == DESTINATION_TAPROOM
        assert second["units_planned"] == 4
        assert second["units_produced"] is None
        _, accepted_meta = validate_paginated(
            api.list_packaging_runs(CELLAR, {"batch_id": batch["id"]})
        )
        assert accepted_meta["total_count"] == 2
        settled = validate_success(api.get_batch(batch["id"], CELLAR))
        assert settled["state"] == BATCH_CONDITIONING
        assert_bbl(settled["packaged_bbl"], 0.000, "packaged_bbl")
        assert_bbl(settled["remaining_bbl"], 16.000, "remaining_bbl")
        assert settled["version"] == batch_v2 + 1


class TestStaleLicenseVersion:
    def test_a_compliance_side_adjustment_invalidates_the_admin_s_observed_token(
        self, api
    ):
        """The token is the licence's own version, bumped by a write the proposer never made.

        PRD §2.7: "A request to create a distributor appointment must carry
        `expected_state_license_version` as a required, non-optional field holding the
        `version` of the target state licence as the client last observed it."

        PRD §2.7: "If it does not equal that licence's current `version`, the request
        is rejected with `ERR_STALE_LICENSE_VERSION` (HTTP 412)."

        PRD §3.6: "As with the brewery, a `ComplianceOfficer` may seed history by
        supplying `carry_in_barrels_ytd`, the barrels already self-distributed into
        that state this calendar year; the call overwrites the field, re-derives
        `barrels_shipped_ytd`, moves the effective distance to `annual_barrel_cap`,
        and increments the licence's `version` by 1."

        PRD §3.6: "`active_appointment_count` is the number of distributor
        appointments under this licence whose `state` is either `ACTIVE` or
        `TERMINATION_REQUESTED`; an appointment whose termination has been requested
        but not yet finalised still counts, because it is still live."

        Design: Corner/cross_cutting_complexity_layers/stale_license_version_blocks_a_proposal_after_a_ytd_adjustment
        """
        bootstrap_brewery(api, home_state_code="OR")
        license_row = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            **LICENSE_WINDOW,
        )
        lic_v = license_row["version"]

        adjusted = validate_success(
            api.set_license_ytd_adjustments(
                license_row["id"], license_ytd_payload(0.000), COMPLIANCE
            )
        )
        lic_v_after = adjusted["version"]
        assert lic_v_after == lic_v + 1
        assert_bbl(adjusted["carry_in_barrels_ytd"], 0.000, "carry_in_barrels_ytd")

        stale = appointment_payload(
            license_row["id"], lic_v, distributor_name="Evergreen Beverage Co"
        )
        validate_error(
            api.create_distributor_appointment(stale, ADMIN),
            ERR_STALE_LICENSE_VERSION,
            412,
        )
        _, refused_meta = validate_paginated(
            api.list_distributor_appointments(
                ADMIN, {"state_license_id": license_row["id"]}
            )
        )
        assert refused_meta["total_count"] == 0

        refreshed = validate_success(api.get_state_license(license_row["id"], ADMIN))
        lic_v2 = refreshed["version"]
        assert lic_v2 == lic_v_after

        stale["expected_state_license_version"] = lic_v2
        appointment = validate_success(
            api.create_distributor_appointment(stale, ADMIN), 201
        )

        assert appointment["state"] == APPT_PROPOSED
        assert appointment["brand_scope"] == SCOPE_ALL_BRANDS
        assert appointment["appointed_beer_id"] is None
        assert appointment["proposed_by_user_id"] == USER_ADMIN_1
        assert appointment["approved_by_user_id"] is None
        assert appointment["activated_at_utc"] is None
        settled = validate_success(api.get_state_license(license_row["id"], COMPLIANCE))
        assert settled["active_appointment_count"] == 0
        assert_bbl(settled["barrels_shipped_ytd"], 0.000, "barrels_shipped_ytd")
        assert validate_success(api.get_brewery(ADMIN))[
            "franchise_locked_state_codes"
        ] == []
        _, accepted_meta = validate_paginated(
            api.list_distributor_appointments(
                ADMIN, {"state_license_id": license_row["id"]}
            )
        )
        assert accepted_meta["total_count"] == 1


class TestSmallBrewerCreditThreshold:
    def test_two_identical_periods_diverge_by_271_cents_on_filing_order_alone(self, api):
        """Both drafts quote the credited 447; filing August pushes the year onto the line.

        PRD §3.8: "Every barrel and tax figure is computed at draft time and
        recomputed at filing time, where it is frozen."

        PRD §3.8: "The return's opening tier position is `ytd_bbl_before_period`: the
        brewery's `carry_in_taproom_bbl` plus its `carry_in_distribution_bbl`, plus the
        sum of `total_taxable_bbl` over every excise report whose `state` is `FILED`
        and whose `period_end_utc` is at or before this return's `period_start_utc`."

        PRD §3.8: "Under a `taproom_basis` of `WHOLE_KEG_REMOVAL`, tax is determined
        on the whole container at the moment it is tapped, and pours are ignored
        entirely."

        PRD §3.8: "A small-brewer credit then applies conditionally: when
        `ytd_bbl_before_period` plus `total_bbl` is at most 15,000 barrels — the
        comparison inclusive — `state_tax_cents` is half the raw state amount, that is
        the raw amount multiplied by the complement of a fifty-percent credit, rounded
        half up to whole cents; when the sum exceeds 15,000 barrels the credit is lost
        entirely and `state_tax_cents` is the raw state amount unchanged."

        Design: Corner/cross_cutting_complexity_layers/small_brewer_state_credit_is_lost_the_moment_the_cumulative_year_passes_fifteen_thousand_barrels
        """
        bootstrap_brewery(api, home_state_code="OR")
        set_brewery_carry_in(api, taproom_bbl=0.000, distribution_bbl=14999.500)
        beer = create_exempt_beer(api, name="Ridgeline IPA", abv_pct=6.8)
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
            units_planned=2,
            run_code="R-TAP-1",
        )
        set_clock(api, "2026-08-15T00:00:00Z")
        create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")
        set_clock(api, "2026-09-10T00:00:00Z")
        create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0002")

        august = draft_report(
            api,
            period_start_utc="2026-08-01T00:00:00Z",
            period_end_utc="2026-09-01T00:00:00Z",
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
        )
        september = draft_report(
            api,
            period_start_utc="2026-09-01T00:00:00Z",
            period_end_utc="2026-10-01T00:00:00Z",
            taproom_basis=BASIS_WHOLE_KEG_REMOVAL,
        )

        for draft, label in ((august, "august draft"), (september, "september draft")):
            assert draft["state"] == REPORT_DRAFT
            assert_bbl(
                draft["ytd_bbl_before_period"], 14999.500, f"{label} ytd_bbl_before_period"
            )
            assert_bbl(draft["taproom_bbl"], 0.500, f"{label} taproom_bbl")
            assert_bbl(draft["distribution_bbl"], 0.000, f"{label} distribution_bbl")
            assert_bbl(draft["total_taxable_bbl"], 0.500, f"{label} total_taxable_bbl")
            assert_cents(draft["federal_tax_cents"], 175, f"{label} federal_tax_cents")
            assert_cents(draft["state_tax_cents"], 272, f"{label} state_tax_cents")
            assert_cents(draft["total_tax_due_cents"], 447, f"{label} total_tax_due_cents")

        filed_august = file_report(api, august["id"])
        assert filed_august["state"] == REPORT_FILED
        assert_bbl(
            filed_august["ytd_bbl_before_period"], 14999.500, "august ytd_bbl_before_period"
        )
        assert_cents(filed_august["federal_tax_cents"], 175, "august federal_tax_cents")
        assert_cents(filed_august["state_tax_cents"], 272, "august state_tax_cents")
        assert_cents(filed_august["total_tax_due_cents"], 447, "august total_tax_due_cents")

        brewery = validate_success(api.get_brewery(COMPLIANCE))
        assert_bbl(brewery["taproom_bbl_ytd"], 0.500, "taproom_bbl_ytd")
        assert_bbl(brewery["distribution_bbl_ytd"], 14999.500, "distribution_bbl_ytd")
        assert_bbl(brewery["total_bbl_ytd"], 15000.000, "total_bbl_ytd")

        set_clock(api, "2026-10-01T00:00:00Z")
        filed_september = file_report(api, september["id"])

        assert filed_september["state"] == REPORT_FILED
        assert_bbl(
            filed_september["ytd_bbl_before_period"],
            15000.000,
            "september ytd_bbl_before_period",
        )
        assert_bbl(filed_september["taproom_bbl"], 0.500, "september taproom_bbl")
        assert_bbl(filed_september["distribution_bbl"], 0.000, "september distribution_bbl")
        assert_cents(filed_september["federal_tax_cents"], 175, "september federal_tax_cents")
        assert_cents(filed_september["state_tax_cents"], 543, "september state_tax_cents")
        assert_cents(
            filed_september["total_tax_due_cents"], 718, "september total_tax_due_cents"
        )
        assert (
            filed_september["total_tax_due_cents"] - filed_august["total_tax_due_cents"]
            == 271
        )
        assert filed_september["taproom_bbl"] == filed_august["taproom_bbl"]
