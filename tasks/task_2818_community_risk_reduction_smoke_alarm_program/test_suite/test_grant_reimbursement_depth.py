"""Grant money: per-device reimbursement, the pinned rounding order, cost share
and the submit/return revision cycle."""

from typing import Any, Dict

from test_helpers.assertions import assert_integer_cents
from test_helpers.constants import (
    DeviceType,
    PlacementLocation,
    ReimbursementBasis,
    ReportDecision,
    ReportStatus,
)
from test_helpers.fixtures import (
    arrive,
    book_visit,
    compile_report,
    complete_visit,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_household,
    create_lot,
    create_partner,
    create_published_route,
    decide_report,
    deliver_education,
    pin_clock,
    read_installation,
    read_report,
    reserve_installation,
    submit_report,
    unit_rate_installations_scenario,
    verify_installation,
)
from test_helpers.test_users import GRANT_OFFICER_SUBMIT_ID

REPORT_PERIOD = {"period_start_date": "2026-07-01", "period_end_date": "2026-08-31"}

# A household of three sleeping areas across two storeys with a fuel-burning
# appliance needs five smoke devices and one CO device.
LARGE_HOUSEHOLD = {
    "address_line": "22 Birch Road",
    "occupant_count": 4,
    "sleeping_areas_count": 3,
    "storeys": 2,
    "children_under5": 1,
    "mobility_impaired_occupants": 1,
    "fuel_burning_appliance": True,
}


def _two_basis_scenario(api) -> Dict[str, Any]:
    """Six devices on one visit, three funded by a UNIT_RATE grant and three by an
    ACTUAL_COST grant, so the two bases can be compared on identical hardware."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    verifier = create_crew(api, crew_code="CREW-B2")

    partner_one = create_partner(api)
    partner_two = create_partner(
        api,
        org_name="Riverside Utility",
        org_type="UTILITY",
        contact_email="grants@riverside.example",
    )
    unit_grant = create_active_grant(api, partner_one["id"], grant_code="G-UNIT-1")
    actual_grant = create_active_grant(
        api,
        partner_two["id"],
        grant_code="G-ACTUAL-2",
        reimbursement_basis=ReimbursementBasis.ACTUAL_COST,
    )

    unit_smoke = create_lot(api, unit_grant["id"], sku="SMK-10Y-A")
    unit_co = create_lot(
        api,
        unit_grant["id"],
        sku="CO-A",
        device_type=DeviceType.CO_ALARM,
        unit_cost_cents=2990,
        received_qty=5,
    )
    actual_smoke = create_lot(api, actual_grant["id"], sku="SMK-10Y-B")
    actual_co = create_lot(
        api,
        actual_grant["id"],
        sku="CO-B",
        device_type=DeviceType.CO_ALARM,
        unit_cost_cents=2990,
        received_qty=5,
    )

    household = create_household(api, zone["id"], **LARGE_HOUSEHOLD)
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    visit = book_visit(api, household["id"], route["id"])
    visit = arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=1)

    placements = [
        (DeviceType.SMOKE_10YR, PlacementLocation.SLEEPING_AREA, 1, unit_smoke),
        (DeviceType.SMOKE_10YR, PlacementLocation.HALLWAY_OUTSIDE_SLEEPING, 2, unit_smoke),
        (DeviceType.CO_ALARM, PlacementLocation.LIVING_LEVEL, 1, unit_co),
        (DeviceType.SMOKE_10YR, PlacementLocation.LIVING_LEVEL, 1, actual_smoke),
        (DeviceType.SMOKE_10YR, PlacementLocation.BASEMENT_STAIR_TOP, 1, actual_smoke),
        (DeviceType.CO_ALARM, PlacementLocation.BASEMENT_STAIR_TOP, 1, actual_co),
    ]
    installations = [
        reserve_installation(
            api,
            visit["id"],
            crew["id"],
            device_type=device_type,
            placement_location=location,
            storey=storey,
            device_lot_id=lot["id"],
        )
        for device_type, location, storey, lot in placements
    ]

    deliver_education(api, visit["id"], crew["id"])
    complete_visit(api, visit["id"], crew["id"], occupant_signature_name="R. Diaz")
    for installation in installations:
        verify_installation(api, installation["id"], verifier["id"])

    return {
        "unit_grant": unit_grant,
        "actual_grant": actual_grant,
        "installations": [read_installation(api, row["id"]) for row in installations],
    }


def test_01_unit_rate_reimburses_the_flat_grant_rate_per_device(api):
    """Under UNIT_RATE the lot's real cost and the labour allocation are ignored.

    PRD: "Under the `UNIT_RATE` basis the base is the grant's flat
    `unit_rate_cents_by_type` entry for that installation's `device_type`; the lot's
    real acquisition cost and the labour allocation are both ignored entirely."

    Design: Difficulty/dual_variant_calc/installation_reimbursement_unit_rate_vs_actual_cost_diverges
    """
    ctx = _two_basis_scenario(api)
    smoke, _second, co_alarm = ctx["installations"][0:3]

    assert smoke["reserved_cost_cents"] == 1850
    assert smoke["reimbursable_cents"] == 1921
    assert co_alarm["reimbursable_cents"] == 3058
    assert_integer_cents(smoke["reimbursable_cents"], "reimbursable_cents")

    report = compile_report(api, ctx["unit_grant"]["id"], **REPORT_PERIOD)
    assert report["installation_count"] == 3
    assert report["household_count"] == 1
    assert report["served_zone_count"] == 1
    assert report["reimbursable_total_cents"] == 6900


def test_02_actual_cost_reimburses_the_snapshot_cost_plus_the_labour_allocation(api):
    """Under ACTUAL_COST the base is the reservation snapshot plus 740 cents.

    PRD: "Under the `ACTUAL_COST` basis the base is the installation's own
    `reserved_cost_cents` - the unit-cost snapshot taken at reservation - plus a flat
    labour allocation of 740 cents, that is $7.40 per device fitted."

    Design: Difficulty/dual_variant_calc/installation_reimbursement_unit_rate_vs_actual_cost_diverges
    """
    ctx = _two_basis_scenario(api)
    smoke, _second, co_alarm = ctx["installations"][3:6]

    assert smoke["reserved_cost_cents"] == 1850
    assert smoke["reimbursable_cents"] == 2266
    assert co_alarm["reimbursable_cents"] == 3264

    report = compile_report(api, ctx["actual_grant"]["id"], **REPORT_PERIOD)
    assert report["installation_count"] == 3
    assert report["reimbursable_total_cents"] == 7796


def test_03_the_two_bases_diverge_on_physically_identical_devices(api):
    """The same six devices reimburse different totals under the two bases.

    PRD: "In either case `reimbursable_cents` is that base multiplied by the grant's
    `reimbursement_pct` and divided by 100, rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/installation_reimbursement_unit_rate_vs_actual_cost_diverges
    """
    ctx = _two_basis_scenario(api)

    unit_report = compile_report(api, ctx["unit_grant"]["id"], **REPORT_PERIOD)
    actual_report = compile_report(api, ctx["actual_grant"]["id"], **REPORT_PERIOD)

    assert unit_report["reimbursable_total_cents"] == 6900
    assert actual_report["reimbursable_total_cents"] == 7796
    assert (
        unit_report["reimbursable_total_cents"]
        != actual_report["reimbursable_total_cents"]
    )
    for installation in ctx["installations"]:
        assert installation["status"] == "VERIFIED"


def test_04_the_report_total_rounds_each_installation_before_summing(api):
    """Two smoke devices and one CO device at 87.5% total 6900, not 6899.

    PRD: "Each installation is rounded to whole cents **first** and the
    already-rounded values are then added. Summing the unrounded products and
    rounding once at the end produces a different, incorrect answer ... two
    `SMOKE_10YR` devices and one `CO_ALARM` reimbursed at 87.5% of unit rates of
    2195, 2195 and 3495 cents total 6900 cents under the pinned per-installation
    rounding and 6899 cents under the forbidden alternative."

    Design: Difficulty/combinatorial_formula/report_total_rounds_each_installation_before_summing
    """
    ctx = unit_rate_installations_scenario(api)
    report = compile_report(api, ctx["grant"]["id"], **REPORT_PERIOD)

    assert report["installation_count"] == 3
    assert report["reimbursable_total_cents"] == 6900
    assert report["reimbursable_total_cents"] != 6899
    assert report["status"] == ReportStatus.DRAFT
    assert report["revision_no"] == 0


def test_05_the_report_total_is_the_sum_of_the_stored_per_device_figures(api):
    """The total is reconcilable device by device: 1921 + 1921 + 3058.

    PRD: "`reimbursable_total_cents` is the sum of the per-installation
    `reimbursable_cents` values, taken over the reportable set in ascending
    `installed_at` order and, for installations sharing an install instant,
    ascending `created_at`."

    Design: Difficulty/combinatorial_formula/report_total_rounds_each_installation_before_summing
    """
    ctx = unit_rate_installations_scenario(api)
    per_device = [row["reimbursable_cents"] for row in ctx["installations"]]

    assert per_device == [1921, 1921, 3058]
    report = compile_report(api, ctx["grant"]["id"], **REPORT_PERIOD)
    assert report["reimbursable_total_cents"] == sum(per_device)
    assert report["household_count"] == 1
    assert report["served_zone_count"] == 1


def test_06_the_indirect_rate_is_applied_to_the_direct_cost_only(api):
    """12.5% of the 6900 direct cost is 863, and total project cost excludes the match.

    PRD: "Step two: `indirect_cents` is the direct cost multiplied by the grant's
    `indirect_rate_pct` and divided by 100, rounded half up to a whole cent - the
    indirect rate is applied to the **direct cost only** and never to total project
    cost. Step three: `total_project_cents` is the direct cost added to
    `indirect_cents`; the partner's match is deliberately *not* a part of it."

    Design: Difficulty/combinatorial_formula/grant_cost_share_indirect_then_match_evaluation_order
    """
    ctx = unit_rate_installations_scenario(api)
    report = compile_report(api, ctx["grant"]["id"], **REPORT_PERIOD)

    assert report["reimbursable_total_cents"] == 6900
    assert report["indirect_cents"] == 863
    assert report["indirect_cents"] != 986
    assert report["total_project_cents"] == 7763
    assert_integer_cents(report["indirect_cents"], "indirect_cents")


def test_07_the_grant_share_is_the_residual_after_the_match_not_a_percentage(api):
    """The 20% match of 7763 is 1553 and the grant share is the 6210 remainder.

    PRD: "Step five: `grant_share_cents` is `total_project_cents` less
    `partner_match_required_cents`, an exact integer subtraction; the grant share is
    the residual and is never recomputed from a percentage of anything."

    Design: Difficulty/combinatorial_formula/grant_cost_share_indirect_then_match_evaluation_order
    """
    ctx = unit_rate_installations_scenario(api)
    report = compile_report(api, ctx["grant"]["id"], **REPORT_PERIOD)
    submitted = submit_report(api, report["id"], attestation_name="M. Trent")

    assert submitted["partner_match_required_cents"] == 1553
    assert submitted["grant_share_cents"] == 6210
    assert submitted["grant_share_cents"] != 6383
    assert (
        submitted["grant_share_cents"]
        == submitted["total_project_cents"] - submitted["partner_match_required_cents"]
    )
    assert submitted["status"] == ReportStatus.SUBMITTED
    assert submitted["submitted_by_user_id"] == GRANT_OFFICER_SUBMIT_ID


def test_08_a_returned_report_goes_back_to_draft_and_sheds_its_attestation(api):
    """RETURN increments the revision counter and clears the submission fields.

    PRD: "Return increments `revision_no` by 1 and clears `submitted_by_user_id`,
    `attestation_name` and `submitted_at`, so the row is genuinely back in the
    compile-and-attest cycle."

    Design: Difficulty/non_linear_state_machine/grant_report_returns_to_draft_and_resubmits_on_revision_cycle
    """
    ctx = unit_rate_installations_scenario(api, include_co_alarm=False)
    report = compile_report(api, ctx["grant"]["id"], **REPORT_PERIOD)
    submit_report(api, report["id"], attestation_name="M. Trent")
    returned = decide_report(
        api,
        report["id"],
        ctx["partner"]["id"],
        decision=ReportDecision.RETURN,
        reviewer_note="Serial numbers missing for two devices",
    )

    assert returned["status"] == ReportStatus.DRAFT
    assert returned["revision_no"] == 1
    assert returned["last_decision"] == ReportDecision.RETURN
    assert returned["reviewer_note"] == "Serial numbers missing for two devices"
    assert returned["submitted_by_user_id"] is None
    assert returned["attestation_name"] is None
    assert returned["submitted_at"] is None


def test_09_the_same_report_row_can_be_attested_again_after_a_return(api):
    """Re-submission returns the row to SUBMITTED while the revision history stands.

    PRD: "The same report row can then be submitted again by any `GrantOfficer`
    whose identifier differs from `compiled_by_user_id`, and the submit-return loop
    may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/grant_report_returns_to_draft_and_resubmits_on_revision_cycle
    """
    ctx = unit_rate_installations_scenario(api, include_co_alarm=False)
    report = compile_report(api, ctx["grant"]["id"], **REPORT_PERIOD)
    submit_report(api, report["id"], attestation_name="M. Trent")
    decide_report(
        api,
        report["id"],
        ctx["partner"]["id"],
        decision=ReportDecision.RETURN,
        reviewer_note="Serial numbers missing for two devices",
    )
    resubmitted = submit_report(api, report["id"], attestation_name="M. Trent")

    assert resubmitted["status"] == ReportStatus.SUBMITTED
    assert resubmitted["revision_no"] == 1
    assert resubmitted["last_decision"] == ReportDecision.RETURN
    assert resubmitted["submitted_by_user_id"] == GRANT_OFFICER_SUBMIT_ID
    assert resubmitted["installation_count"] == 2
    assert resubmitted["reimbursable_total_cents"] == 3842

    stored = read_report(api, report["id"])
    assert stored["reimbursable_total_cents"] == 3842
