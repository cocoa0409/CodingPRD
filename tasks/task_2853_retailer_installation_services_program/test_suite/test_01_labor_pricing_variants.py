"""Labour pricing: the provisional quote, the final charge and the tier ladder.

The labour charge is built in six ordered steps and exists in two variants that
answer differently for the same project. These tests drive one project all the way
through its measurement, its permit and its installation so that both variants are
observable side by side, and they pin the arithmetic of the tier ladder, the
site-condition surcharges and the jurisdiction multiplier.
"""

from test_helpers import (
    PROJECT_COORDINATOR,
    ChangeOrderOrigin,
    ChangeOrderStatus,
    FinancialStatus,
    FulfillmentStatus,
    MeasurementStatus,
    PermitStatus,
    assert_deposit_buckets,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_units,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_installer_headers,
)

# Provisional quote for 420.00 units of FLOORING at 425 cents in a jurisdiction whose
# labor_complexity_multiplier is 1.15: bands 200.00 * 425 = 85000 and 220.00 * 391 =
# 86020 give a base of 171020, no surcharge, and 171020 * 1.15 = 196673.
QUOTED = 196673
DEPOSIT = 59002


def _measured_lifecycle(api, measured_units, subfloor, obstructions, stairs):
    """Sell one project on a measurement-required category and complete its in-home
    visit with the supplied site detail, leaving the auto-raised variance disclosure
    undecided."""
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    project = fx.pay_deposit(api, project, base["customer"]["id"])
    ctx = dict(base)
    ctx["project"] = project
    fx.set_clock(api, "2026-08-05T09:00:00.000Z")
    measurement = fx.book_measurement(api, project["id"],
                                      "2026-08-05T09:00:00.000Z")
    ctx["measurement"] = fx.complete_measurement(
        api, measurement["id"], measured_units,
        subfloor_condition=subfloor, obstruction_count=obstructions,
        stair_flight_count=stairs,
    )
    ctx["variance_change_order"] = fx.variance_change_order(api, project["id"])
    ctx["project"] = fx.read_project(api, project["id"])
    return ctx


def _install_to_completion(api, ctx):
    """Permit, deliver, schedule and install the measured project, returning the
    completed assignment."""
    project_id = ctx["project"]["id"]
    network = fx.activated_installer(api, ctx["jurisdiction"]["id"])
    installer = network["installer"]
    ctx["installer"] = installer
    fx.set_clock(api, "2026-08-10T00:00:00.000Z")
    get_success_data(api.apply_permit(project_id, f.permit_apply_payload(),
                                      PROJECT_COORDINATOR))
    get_success_data(
        api.issue_permit(project_id,
                         f.permit_issue_payload(18500, "2026-08-10T00:00:00.000Z"),
                         PROJECT_COORDINATOR)
    )
    ctx["delivery"] = fx.plan_delivery(api, project_id)
    installer_headers = make_installer_headers(installer["id"])
    assignment = fx.hold_assignment(api, project_id, installer["id"],
                                    fx.project_version(api, project_id))
    get_success_data(api.confirm_assignment(assignment["id"], PROJECT_COORDINATOR))
    fx.set_clock(api, "2026-08-25T08:00:00.000Z")
    get_success_data(api.start_assignment(assignment["id"], installer_headers))
    fx.set_clock(api, "2026-08-25T15:30:00.000Z")
    ctx["assignment"] = get_success_data(
        api.complete_assignment(assignment["id"],
                                f.completion_payload("2026-08-25T15:30:00.000Z"),
                                installer_headers)
    )
    ctx["project"] = fx.read_project(api, project_id)
    return ctx


def test_provisional_quote_and_final_charge_diverge_on_one_project(api):
    """The frozen provisional quote and the final labour charge are different numbers
    for the same project once the house has actually been measured.

    PRD 3.3: "First, a unit quantity is chosen: the provisional variant uses the
    project's `estimated_units`, while the final variant uses the `measured_units` of
    the project's most recent measurement whose `status` is `COMPLETED`".

    Design: Difficulty/dual_variant_calc/project_labor_charge_provisional_versus_final_diverge_on_same_project
    """
    ctx = _measured_lifecycle(api, 468.00, "MAJOR", 3, 2)
    project = ctx["project"]
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    assert_money(project["deposit_required_cents"], DEPOSIT, "deposit_required_cents")
    assert_units(project["effective_units"], 468.00, "effective_units")
    assert_units(project["estimated_units"], 420.00, "estimated_units")
    assert project["final_labor_cents"] is None, (
        "final_labor_cents stays null until the installer reports the work finished"
    )
    assert_score(ctx["measurement"]["variance_pct"], 11.43, "variance_pct")

    # The disclosure is the final variant minus the frozen quote, so the divergence is
    # already observable before the crew arrives: 253942 - 196673.
    assert_money(ctx["variance_change_order"]["upcharge_cents"], 57269,
                 "variance disclosure upcharge_cents")
    fx.accept_change_order(api, ctx["variance_change_order"]["id"],
                           ctx["customer"]["id"])

    ctx = _install_to_completion(api, ctx)
    project = ctx["project"]
    # Final variant on 468.00 units: bands 85000 + 268.00 * 391 = 104788 give a base
    # of 189788; MAJOR subfloor adds 17081, three obstructions 5550 and two stair
    # flights 8400; (189788 + 31031) * 1.15 = 253941.85 rounds to 253942.
    assert_money(project["final_labor_cents"], 253942, "final_labor_cents")
    assert_money(project["quoted_labor_cents"], QUOTED,
                 "quoted_labor_cents after the final variant ran")
    assert project["final_labor_cents"] - project["quoted_labor_cents"] == 57269, (
        "the two variants must differ by 57269 cents on this project"
    )
    assert_units(project["effective_units"], 468.00, "effective_units")
    assert ctx["assignment"]["on_time"] is True


def test_final_variant_invoice_excludes_the_variance_disclosure(api):
    """The invoice assembled when the crew reports the work finished charges the
    measured units exactly once: the accepted variance disclosure adds nothing.

    PRD 3.4: "It is a disclosure and nothing more: accepting such a change order adds
    **nothing** to `change_order_upcharge_cents`, because those same measured units
    are already charged by the final labour variant when the installer reports the
    work complete."

    Design: Difficulty/dual_variant_calc/project_labor_charge_provisional_versus_final_diverge_on_same_project
    """
    ctx = _measured_lifecycle(api, 468.00, "MAJOR", 3, 2)
    fx.accept_change_order(api, ctx["variance_change_order"]["id"],
                           ctx["customer"]["id"])
    ctx = _install_to_completion(api, ctx)
    project = ctx["project"]

    assert_money(project["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents")
    assert_money(project["permit_fee_cents_billed"], 18500,
                 "permit_fee_cents_billed")
    # total_due_cents is final_labor_cents + change_order_upcharge_cents +
    # permit_fee_cents_billed = 253942 + 0 + 18500.
    assert_money(project["total_due_cents"], 272442, "total_due_cents")
    assert_deposit_buckets(project, paid=DEPOSIT, held=0, applied=DEPOSIT,
                           refunded=0, forfeited=0)
    assert_money(project["balance_due_cents"], 213440, "balance_due_cents")
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.INSTALL_COMPLETE,
                              financial=FinancialStatus.BALANCE_DUE)
    assert_instant(project["install_completed_at"], "2026-08-25T15:30:00.000Z",
                   "install_completed_at")


def test_tier_ladder_surcharges_and_multiplier_compose_non_linearly(api):
    """A quantity that reaches the third tier, a MINOR subfloor and one obstruction
    compose into a charge that no single-rate or single-factor shortcut reproduces.

    PRD 3.3: "Fifth, the base amount and the surcharge amount are **added first**, the
    sum is multiplied **once** by the jurisdiction's `labor_complexity_multiplier`, and
    that product is rounded half up **once** to whole cents."

    Design: Difficulty/combinatorial_formula/labor_charge_tier_ladder_times_surcharges_times_multiplier_non_linear
    """
    ctx = _measured_lifecycle(api, 520.00, "MINOR", 1, 0)
    disclosure = ctx["variance_change_order"]

    # 520.00 units: 200.00 * 425 = 85000, 300.00 * 391 = 117300 and 20.00 * 361 = 7220
    # give a base of 209520. MINOR subfloor adds round_half_up(209520 * 0.04) = 8381
    # and one obstruction 1850, so the surcharge is 10231. (209520 + 10231) * 1.15 =
    # 252713.65 rounds to 252714, and the disclosure is 252714 - 196673.
    assert_money(disclosure["upcharge_cents"], 56041, "disclosure upcharge_cents")

    # Charging every unit at the base rate instead of spreading the quantity across
    # the three marginal tiers would disclose 69771.
    assert disclosure["upcharge_cents"] != 69771, (
        "the billable quantity must be spread across the three marginal tiers"
    )
    # Multiplying only the base amount and then adding the surcharge would disclose
    # 54506; the surcharge is added before the single multiplication.
    assert disclosure["upcharge_cents"] != 54506, (
        "the multiplier applies to the base amount plus the surcharge amount"
    )
    # Computing the surcharge from the already-multiplied base would disclose 55763.
    assert disclosure["upcharge_cents"] != 55763, (
        "the subfloor surcharge is a fraction of the unmultiplied base amount"
    )


def test_material_variance_opens_a_disclosure_without_moving_the_frozen_quote(api):
    """The same measurement that drives the non-linear charge also computes the
    variance, opens the disclosure and leaves every frozen money field alone.

    PRD 3.4: "`change_order_triggered` is set true when `variance_pct` is 10.00 or
    greater and false otherwise; the project's `effective_units` is overwritten with
    `measured_units` — note that `estimated_units` itself is never overwritten,
    because `variance_pct` must remain reproducible".

    Design: Difficulty/combinatorial_formula/labor_charge_tier_ladder_times_surcharges_times_multiplier_non_linear
    """
    ctx = _measured_lifecycle(api, 520.00, "MINOR", 1, 0)
    measurement = ctx["measurement"]
    project = ctx["project"]
    disclosure = ctx["variance_change_order"]

    assert measurement["status"] == MeasurementStatus.COMPLETED
    # |520.00 - 420.00| / 420.00 * 100 = 23.8095... rounds to 23.81.
    assert_score(measurement["variance_pct"], 23.81, "variance_pct")
    assert measurement["change_order_triggered"] is True
    assert_units(project["effective_units"], 520.00, "effective_units")
    assert_units(project["estimated_units"], 420.00, "estimated_units")

    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    assert_money(project["deposit_required_cents"], DEPOSIT, "deposit_required_cents")
    assert_money(project["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents while the disclosure is undecided")
    assert project["final_labor_cents"] is None

    assert disclosure["origin"] == ChangeOrderOrigin.MEASUREMENT_VARIANCE
    assert disclosure["status"] == ChangeOrderStatus.PENDING_CUSTOMER
    assert disclosure["lines"] == []
    assert disclosure["source_measurement_id"] == measurement["id"]
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.CHANGE_PENDING,
                              financial=FinancialStatus.DEPOSIT_HELD,
                              permit=PermitStatus.PENDING_APPLICATION)
