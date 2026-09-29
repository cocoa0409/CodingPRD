"""Variant-selected arithmetic and multi-factor formulas.

Covers the two families of money that share one input and diverge on a stored
discriminator — the period charge of PRD §3.8 and the loss assessment of
PRD §3.7 — and the two figures of PRD §3.2 and §3.8 that only fall out of
composing several factors in the order the PRD declares.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.assertions import (
    assert_cents,
    assert_fleet_counts,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
    assert_labor_hours,
    assert_line_types,
    line_by_type,
)


def _invoice_of_kind(api, contract_id, invoice_kind):
    rows = FX.invoices_for(api, contract_id, invoice_kind=invoice_kind)
    assert len(rows) == 1, f"expected one {invoice_kind} invoice, got {rows}"
    return rows[0]


# ---------------------------------------------------------------------------
# dual_variant_calc
# ---------------------------------------------------------------------------


def test_event_and_construction_prorate_the_same_monthly_differently(api):
    """PRD §3.8: "a contract with a `monthly_recurring_cents` of 60,000 billed
    over a seventeen-day window yields 34,000 cents under the event variant — a
    daily rate of 2,000 multiplied by seventeen days — and 36,429 cents under the
    construction variant, which has no whole cycle and prorates seventeen
    twenty-eighths of the month."

    Design: Difficulty/dual_variant_calc/event_vs_construction_proration_divergence
    """
    world = FX.seed_world(
        api,
        addons=(C.GATE_CODE, C.BARRICADE_CODE),
        crews=(C.CREW_A, C.CREW_B),
        jobsite={
            "site_label": "Quay Street Festival Lot",
            "address_line": "11 Quay Street",
            "phase_count": 4,
        },
    )
    construction_site = FX.add_jobsite(world, api, phase_count=4)

    event = FX.seed_installed_contract(
        api,
        world,
        event=True,
        linear_feet=250,
        addon_lines=[F.addon_line(C.BARRICADE_CODE, 10)],
    )
    construction = FX.seed_installed_contract(
        api,
        world,
        jobsite=construction_site,
        crew=world["crews"][C.CREW_B],
        linear_feet=250,
        addon_lines=[
            F.addon_line(C.GATE_CODE, 7),
            F.addon_line(C.BARRICADE_CODE, 4),
        ],
    )

    # The two configurations reach the same recurring figure by different routes:
    # 15500 of panel rent plus 32500 of barricades surged by 1.25, against 15500
    # plus 44500 of gates and barricades with no term discount at three months.
    assert_cents(
        event["quote"]["monthly_recurring_cents"], 60000, "monthly_recurring_cents"
    )
    assert_cents(
        construction["quote"]["monthly_recurring_cents"],
        60000,
        "monthly_recurring_cents",
    )
    assert_cents(event["quote"]["install_labor_cents"], 48750, "install_labor_cents")
    assert_cents(
        construction["quote"]["install_labor_cents"], 51250, "install_labor_cents"
    )

    event_contract = FX.read_contract(api, event["contract"]["id"])
    construction_contract = FX.read_contract(api, construction["contract"]["id"])
    assert event_contract["contract_type"] == C.CONTRACT_TYPE_EVENT
    assert construction_contract["contract_type"] == C.CONTRACT_TYPE_CONSTRUCTION
    assert_cents(
        event_contract["monthly_recurring_cents"], 60000, "monthly_recurring_cents"
    )
    assert_cents(
        construction_contract["monthly_recurring_cents"],
        60000,
        "monthly_recurring_cents",
    )
    for contract in (event_contract, construction_contract):
        assert contract["lifecycle_status"] == C.LIFECYCLE_ACTIVE
        assert contract["billing_status"] == C.BILLING_CURRENT
        assert_instant(
            contract["billing_anchor_utc"], C.CLOCK_AUG_20, "billing_anchor_utc"
        )

    FX.set_clock(api, C.CLOCK_SEP_06)
    window = F.billing_run_payload(C.CLOCK_AUG_20, C.CLOCK_SEP_06)
    event_invoice = validate_success(
        api.create_billing_run(event_contract["id"], window, U.ACCOUNT_MANAGER),
        expected_status=201,
    )
    construction_invoice = validate_success(
        api.create_billing_run(construction_contract["id"], window, U.ACCOUNT_MANAGER),
        expected_status=201,
    )

    assert event_invoice["invoice_kind"] == C.KIND_PERIODIC
    assert_integer(event_invoice["billable_days"], 17, "billable_days")
    assert_line_types(event_invoice, [C.LINE_RENTAL])
    event_rental = line_by_type(event_invoice, C.LINE_RENTAL)
    assert_cents(event_rental["amount_cents"], 34000, "RENTAL")
    assert_integer(event_rental["quantity"], 17, "quantity")
    assert_invoice_rollup(
        event_invoice, subtotal=34000, tax=3026, late_fee=0, total=37026
    )

    assert construction_invoice["invoice_kind"] == C.KIND_PERIODIC
    assert_integer(construction_invoice["billable_days"], 17, "billable_days")
    assert_line_types(construction_invoice, [C.LINE_RENTAL])
    construction_rental = line_by_type(construction_invoice, C.LINE_RENTAL)
    assert_cents(construction_rental["amount_cents"], 36429, "RENTAL")
    assert_integer(construction_rental["quantity"], 17, "quantity")
    assert_invoice_rollup(
        construction_invoice, subtotal=36429, tax=3242, late_fee=0, total=39671
    )

    assert (
        construction_invoice["subtotal_cents"] - event_invoice["subtotal_cents"] == 2429
    )

    assert_instant(
        FX.read_contract(api, event_contract["id"])["billed_through_utc"],
        C.CLOCK_SEP_06,
        "billed_through_utc",
    )
    assert_instant(
        FX.read_contract(api, construction_contract["id"])["billed_through_utc"],
        C.CLOCK_SEP_06,
        "billed_through_utc",
    )


def test_the_police_report_switches_the_loss_term_and_leaves_damage_alone(api):
    """PRD §3.7: "**The `DEPRECIATED_VALUE` variant** applies when
    `theft_police_report_number` is present **and** the contract's
    `contract_type` is `CONSTRUCTION`; both conditions must hold." and "Damage is
    never depreciated: a damaged panel is charged against undepreciated
    replacement cost no matter how old the batch is."

    Design: Difficulty/dual_variant_calc/theft_loss_replacement_vs_depreciated_divergence
    """
    world = FX.seed_world(
        api,
        crews=(C.CREW_A, C.CREW_B),
        jobsite={"site_label": "Foundry Road A", "address_line": "402 Foundry Road"},
    )
    site_b = FX.add_jobsite(
        world, api, site_label="Foundry Road B", address_line="418 Foundry Road"
    )

    plain = FX.seed_demobilizing_contract(api, world, linear_feet=500)
    reported = FX.seed_demobilizing_contract(
        api,
        world,
        jobsite=site_b,
        crew=world["crews"][C.CREW_B],
        linear_feet=500,
    )

    for state in (plain, reported):
        assert_cents(
            state["quote"]["monthly_recurring_cents"], 27000, "monthly_recurring_cents"
        )
        assert_cents(state["quote"]["install_labor_cents"], 47500, "install_labor_cents")
        assert_cents(state["quote"]["one_time_cents"], 78500, "one_time_cents")
        assert state["reconciliation"] is not None, "removal must open a reconciliation"
        assert state["reconciliation"]["status"] == C.REC_OPEN
        assert state["reconciliation"]["deployed_snapshot"] == [
            {"product_code": C.PANEL_CODE, "unit_count": 50}
        ]
        assert state["reconciliation"]["assessment_variant"] is None

    returns = [F.unit_return(C.PANEL_CODE, returned=43, damaged=2, missing=5)]

    replacement = FX.finalize_reconciliation(
        api,
        plain["reconciliation"]["id"],
        returns,
        auditor_note="no police report filed",
    )
    depreciated = FX.finalize_reconciliation(
        api,
        reported["reconciliation"]["id"],
        returns,
        theft_police_report_number="HPPD-2026-88134",
    )

    # Five missing panels of an eighteen-month-old batch: 5 x 24000 undepreciated
    # against 5 x 24000 x 0.64 depreciated, while the damage term is
    # 2 x 24000 x 0.35 in both.
    assert replacement["assessment_variant"] == C.VARIANT_REPLACEMENT_COST
    assert_cents(replacement["loss_charge_cents"], 120000, "loss_charge_cents")
    assert_cents(replacement["damage_charge_cents"], 16800, "damage_charge_cents")
    assert replacement["status"] == C.REC_FINALIZED
    assert replacement["finalized_by_user_id"] == U.YARD_AUDITOR_ID

    assert depreciated["assessment_variant"] == C.VARIANT_DEPRECIATED_VALUE
    assert_cents(depreciated["loss_charge_cents"], 76800, "loss_charge_cents")
    assert_cents(depreciated["damage_charge_cents"], 16800, "damage_charge_cents")
    assert depreciated["status"] == C.REC_FINALIZED

    assert (
        replacement["loss_charge_cents"] - depreciated["loss_charge_cents"] == 43200
    )
    assert replacement["damage_charge_cents"] == depreciated["damage_charge_cents"]

    plain_final = _invoice_of_kind(api, plain["contract"]["id"], C.KIND_FINAL)
    assert_line_types(plain_final, [C.LINE_LOSS, C.LINE_DAMAGE])
    assert_cents(line_by_type(plain_final, C.LINE_LOSS)["amount_cents"], 120000, "LOSS")
    assert_cents(line_by_type(plain_final, C.LINE_DAMAGE)["amount_cents"], 16800, "DAMAGE")
    assert_integer(line_by_type(plain_final, C.LINE_LOSS)["quantity"], 5, "quantity")
    assert_integer(line_by_type(plain_final, C.LINE_DAMAGE)["quantity"], 2, "quantity")
    assert_invoice_rollup(
        plain_final, subtotal=136800, tax=12175, late_fee=0, total=148975
    )

    reported_final = _invoice_of_kind(api, reported["contract"]["id"], C.KIND_FINAL)
    assert_line_types(reported_final, [C.LINE_LOSS, C.LINE_DAMAGE])
    assert_cents(
        line_by_type(reported_final, C.LINE_LOSS)["amount_cents"], 76800, "LOSS"
    )
    assert_cents(
        line_by_type(reported_final, C.LINE_DAMAGE)["amount_cents"], 16800, "DAMAGE"
    )
    assert_invoice_rollup(
        reported_final, subtotal=93600, tax=8330, late_fee=0, total=101930
    )

    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=386,
        reserved=0,
        deployed=0,
        damaged=4,
        lost=10,
    )


# ---------------------------------------------------------------------------
# combinatorial_formula
# ---------------------------------------------------------------------------


def test_five_pricing_factors_compose_in_the_declared_order(api):
    """PRD §3.2: "The arithmetic then runs as a fixed sequence of steps, and five
    independent inputs each select a different factor before all five land in one
    figure." The condition rate of step nine touches only the labor, and the term
    factor of step seven touches only the recurring figure.

    Design: Difficulty/combinatorial_formula/quote_pricing_five_factor_combination
    """
    world = FX.seed_world(
        api,
        addons=(C.GATE_CODE, C.WATER_BARRIER_CODE),
        jobsite={
            "site_label": "Quay Street Tower",
            "address_line": "11 Quay Street",
            "site_condition": C.CONDITION_SOIL,
            "requires_sidewalk_closure": True,
        },
    )
    asphalt_site = FX.add_jobsite(
        world,
        api,
        site_label="Foundry Road Deck",
        address_line="402 Foundry Road",
        site_condition=C.CONDITION_ASPHALT,
        requires_sidewalk_closure=True,
    )
    addons = [F.addon_line(C.GATE_CODE, 2), F.addon_line(C.WATER_BARRIER_CODE, 4)]

    def price(jobsite_id, term_months):
        return FX.seed_quote(
            api,
            jobsite_id,
            linear_feet=500,
            term_months=term_months,
            wind_screen=C.SCREEN_MESH_70,
            addon_lines=addons,
        )

    # 500 ft at the flat 54-cent band is 27000; the 1.15 mesh factor lifts it to
    # 31050; the 12-cent adder adds 6000; gates and water barriers add 17800; and
    # the twelve-month factor of 0.86 closes on 47171.
    on_soil = price(world["jobsite"]["id"], 12)
    on_asphalt = price(asphalt_site["id"], 12)

    assert_integer(on_soil["panel_unit_count"], 50, "panel_unit_count")
    assert_integer(on_soil["tier_rate_cents_per_ft"], 54, "tier_rate_cents_per_ft")
    assert_cents(on_soil["monthly_recurring_cents"], 47171, "monthly_recurring_cents")
    assert_cents(on_soil["install_labor_cents"], 62500, "install_labor_cents")
    assert_cents(on_soil["permit_handling_fee_cents"], 12500, "permit_handling_fee_cents")
    assert_cents(on_soil["one_time_cents"], 93500, "one_time_cents")

    assert_cents(on_asphalt["monthly_recurring_cents"], 47171, "monthly_recurring_cents")
    assert_cents(on_asphalt["install_labor_cents"], 85000, "install_labor_cents")
    assert_cents(on_asphalt["one_time_cents"], 116000, "one_time_cents")

    # Changing only the term re-prices the recurring figure at 0.92 and leaves the
    # one-time side untouched; it also supersedes the open DRAFT on its own site.
    shorter_term = price(world["jobsite"]["id"], 6)

    assert_cents(shorter_term["monthly_recurring_cents"], 50462, "monthly_recurring_cents")
    assert_cents(shorter_term["install_labor_cents"], 62500, "install_labor_cents")
    assert_cents(shorter_term["one_time_cents"], 93500, "one_time_cents")
    assert shorter_term["status"] == C.QUOTE_DRAFT

    assert FX.read_quote(api, on_soil["id"])["status"] == C.QUOTE_SUPERSEDED
    assert FX.read_quote(api, on_asphalt["id"])["status"] == C.QUOTE_DRAFT

    assert (
        on_asphalt["monthly_recurring_cents"] == on_soil["monthly_recurring_cents"]
    )
    assert on_asphalt["install_labor_cents"] - on_soil["install_labor_cents"] == 22500
    assert (
        shorter_term["monthly_recurring_cents"] - on_soil["monthly_recurring_cents"]
        == 3291
    )


def test_the_event_daily_rate_is_rounded_before_it_is_multiplied(api):
    """PRD §3.8: "A daily rate is then obtained by dividing the contract's
    `monthly_recurring_cents` by thirty and **rounding that quotient half up to
    whole cents first**, and the `RENTAL` line amount is that rounded daily rate
    multiplied by the day count."

    Design: Difficulty/combinatorial_formula/event_daily_rate_rounding_order
    """
    world = FX.seed_world(
        api,
        event_account=True,
        jobsite={
            "site_label": "Quay Street Festival Lot",
            "address_line": "11 Quay Street",
        },
    )
    state = FX.seed_installed_contract(
        api,
        world,
        event=True,
        linear_feet=250,
        wind_screen=C.SCREEN_MESH_70,
    )

    # 250 ft at 62 cents is 15500; the mesh factor gives 17825; the adder gives
    # 3000; and the unconditional 1.25 event surge closes on 26031.25 -> 26031.
    quote = state["quote"]
    assert_integer(quote["panel_unit_count"], 25, "panel_unit_count")
    assert_cents(quote["monthly_recurring_cents"], 26031, "monthly_recurring_cents")
    assert_cents(quote["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(quote["one_time_cents"], 66000, "one_time_cents")
    assert_labor_hours(state["install"]["estimated_labor_hours"], 2.25)

    mobilization = state["mobilization_invoice"]
    assert mobilization is not None, "the mobilization cascade must issue an invoice"
    assert mobilization["invoice_kind"] == C.KIND_MOBILIZATION
    assert_line_types(
        mobilization,
        [C.LINE_INSTALL_LABOR, C.LINE_DELIVERY, C.LINE_PERMIT_HANDLING],
    )
    assert_invoice_rollup(
        mobilization, subtotal=66000, tax=5874, late_fee=0, total=71874
    )

    FX.set_clock(api, C.CLOCK_SEP_06)
    periodic = validate_success(
        api.create_billing_run(
            state["contract"]["id"],
            F.billing_run_payload(C.CLOCK_AUG_20, C.CLOCK_SEP_06),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    # 26031 / 30 rounds to 868 before the multiplication; 868 x 17 is 14756, where
    # multiplying first and rounding once would have produced 14751.
    assert periodic["invoice_kind"] == C.KIND_PERIODIC
    assert_integer(periodic["billable_days"], 17, "billable_days")
    assert_line_types(periodic, [C.LINE_RENTAL])
    rental = line_by_type(periodic, C.LINE_RENTAL)
    assert_cents(rental["amount_cents"], 14756, "RENTAL")
    assert_integer(rental["quantity"], 17, "quantity")
    assert_invoice_rollup(periodic, subtotal=14756, tax=1313, late_fee=0, total=16069)
    assert periodic["subtotal_cents"] != 14751
