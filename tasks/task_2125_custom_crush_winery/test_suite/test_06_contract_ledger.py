"""The contract ledger: cellar work orders, the five-step charge, disputes and
the segregation-of-duties gate on billing."""
import pytest

from test_helpers import (
    FACILITY_ADMIN_ID,
    ApiErrorId,
    assert_work_order,
    assert_work_order_billing_chain,
    bill_work_order,
    drive_work_order_to_completed,
    make_cellar_supervisor_headers,
    make_facility_admin_headers,
    new_accepted_intake,
    new_work_order,
    read_contract_version,
    setup_billed_work_order,
    setup_completed_work_order,
    setup_contract_with_lot,
    validate_error,
    validate_success,
)

# 14000 - 4000 = 10000 lb = 5.0 tons
FIVE_TON_MERLOT = {
    "gross_weight_lbs": 14000,
    "tare_weight_lbs": 4000,
    "varietal": "MERLOT",
    "appellation": "OAKVILLE",
    "block_code": "B07",
    "brix": 23.50,
    "ph": 3.55,
}
# 6000 - 4000 = 2000 lb = 1.0 ton at 23.50 Brix → 165.00 gallons
ONE_TON_PINOT = {
    "gross_weight_lbs": 6000,
    "tare_weight_lbs": 4000,
    "varietal": "PINOT_NOIR",
    "appellation": "NAPA_VALLEY",
    "block_code": "P01",
    "brix": 23.50,
    "ph": 3.45,
}


def test_dispute_reverses_the_billed_amount_out_of_the_contract_ledger(
    api, facility_admin_headers
):
    """PRD 3.6: "The disputed charge is compensated out of the ledger
    immediately: the contract's `billed_total_cents` is reduced by that order's
    `billable_amount_cents` and the contract's `version` increments, while
    `billable_amount_cents`, `subtotal_cents` and `volume_discount_pct` on the
    order are all reset to 0."

    Design: Corner/state_machines/corner_work_order_dispute_reverses_contract_ledger
    """
    scenario = setup_billed_work_order()

    data = validate_success(
        api.work_order_transition(
            scenario["work_order"]["id"],
            {
                "action": "DISPUTE",
                "dispute_reason": "Crew size billed as two, only one worker attended.",
            },
            scenario["rep_headers"],
        )
    )

    assert_work_order(data)
    assert data["status"] == "DISPUTED"
    assert data["billable_amount_cents"] == 0
    assert data["subtotal_cents"] == 0
    assert data["volume_discount_pct"] == pytest.approx(0, abs=0.01)
    assert data["dispute_reason"] == "Crew size billed as two, only one worker attended."
    assert data["billed_by_user_id"] == FACILITY_ADMIN_ID, (
        "the audit stamp of who billed the order survives the dispute"
    )

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["billed_total_cents"] == 950000, (
        f"the ledger must return to the pre-billing crush fee, got "
        f"{contract['billed_total_cents']}"
    )


def test_the_dispute_and_rebill_cycle_reprices_from_scratch(api, facility_admin_headers):
    """PRD 3.6: "A `FacilityAdmin` then settles the dispute by completing the
    order again from `DISPUTED`, supplying the corrected `actual_labor_hours`
    (present and greater than zero); that returns the order to `COMPLETED` and
    clears `dispute_reason` to null."
    PRD 3.6: "The whole `COMPLETED` to `BILLED` to `DISPUTED` to `COMPLETED`
    cycle may repeat until the client accepts the charge, and each fresh billing
    re-selects the discount tier from whatever the contract's ledger reads at
    that moment."

    Design: Corner/state_machines/corner_work_order_dispute_recomplete_rebill_cycle
    """
    scenario = setup_billed_work_order()
    work_order_id = scenario["work_order"]["id"]
    validate_success(
        api.work_order_transition(
            work_order_id,
            {"action": "DISPUTE", "dispute_reason": "Only one worker attended."},
            scenario["rep_headers"],
        )
    )

    recompleted = validate_success(
        api.work_order_transition(
            work_order_id,
            {"action": "COMPLETE", "actual_labor_hours": 1.25},
            facility_admin_headers,
        )
    )
    assert recompleted["status"] == "COMPLETED"
    assert recompleted["dispute_reason"] is None

    rebilled = validate_success(
        api.bill_work_order(
            work_order_id,
            {"expected_contract_version": read_contract_version(scenario["contract"]["id"])},
            facility_admin_headers,
        )
    )
    assert rebilled["status"] == "BILLED"
    assert rebilled["base_labor_cents"] == 25000, "1.25 hours x 2 crew x 10000 cents"
    assert rebilled["subtotal_cents"] == 27000
    assert rebilled["volume_discount_pct"] == pytest.approx(0, abs=0.01), (
        "the basis 950000 + 27000 is below the first discount threshold"
    )
    assert rebilled["billable_amount_cents"] == 27000

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["billed_total_cents"] == 977000


def test_the_rush_surcharge_is_taken_on_base_labour_before_the_subtotal(
    api, facility_admin_headers
):
    """PRD 3.6: "First, `base_labor_cents` is `actual_labor_hours` multiplied by
    `crew_size` multiplied by the contract's `labor_rate_cents_per_hour`,
    rounded half up to whole cents. Second, `rush_surcharge_cents` is 25 percent
    of `base_labor_cents`, rounded half up to whole cents, when `rush` is true,
    and is 0 when it is false. Third, `subtotal_cents` is `base_labor_cents`
    plus `rush_surcharge_cents` plus `material_cost_cents`."

    Design: Corner/calculations/corner_work_order_rush_surcharge_precedes_subtotal
    """
    scenario = setup_contract_with_lot(
        clock="2026-09-10T00:00:00Z",
        load=ONE_TON_PINOT,
        delivery_ticket="DT-L1",
        lot_code="PN-NAP-26-01",
        crush_rate_cents_per_ton=45000,
        labor_rate_cents_per_hour=9500,
    )
    assert scenario["intake"]["crush_fee_cents"] == 45000
    assert scenario["lot"]["volume_gallons"] == pytest.approx(165.00, abs=0.01)

    order = new_work_order(
        scenario["lot"]["id"],
        operation_type="ADDITION",
        scheduled_at="2026-09-12T08:00:00Z",
        labor_hours=6.50,
        crew_size=3,
        material_cost_cents=42000,
        rush=True,
    )
    drive_work_order_to_completed(order["id"], actual_labor_hours=6.50)

    data = validate_success(
        api.bill_work_order(
            order["id"],
            {"expected_contract_version": read_contract_version(scenario["contract"]["id"])},
            facility_admin_headers,
        )
    )

    assert data["base_labor_cents"] == 185250, "6.50 hours x 3 crew x 9500 cents"
    assert data["rush_surcharge_cents"] == 46313, (
        f"25 percent of 185250 is 46312.5, which rounds half up to 46313; got "
        f"{data['rush_surcharge_cents']}"
    )
    assert data["subtotal_cents"] == 273563, (
        f"185250 + 46313 + 42000, not the 285313 a surcharge-on-everything "
        f"reading would give; got {data['subtotal_cents']}"
    )
    assert data["volume_discount_pct"] == pytest.approx(0, abs=0.01)
    assert data["billable_amount_cents"] == 273563
    assert_work_order_billing_chain(data)

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["billed_total_cents"] == 318563


def test_billing_with_a_stale_contract_version_is_refused(api, facility_admin_headers):
    """PRD 2.6: "A `POST /work-orders/{id}/bill` request must carry
    `expected_contract_version` equal to the governing `Contract`'s current
    `version`. Billing selects a volume-discount tier from the contract's
    `billed_total_cents`, and any other posting — a crush fee, a storage
    accrual, another work order — legitimately moves that total and would
    silently reprice this order. A mismatch is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

    Design: Corner/errors/corner_stale_contract_version_on_work_order_bill_rejected
    """
    scenario = setup_completed_work_order(delivery_ticket="DT-Y1")
    contract_id = scenario["contract"]["id"]
    stale_version = read_contract_version(contract_id)
    new_accepted_intake(contract_id, "DT-Y2", load=FIVE_TON_MERLOT)

    response = api.bill_work_order(
        scenario["work_order"]["id"],
        {"expected_contract_version": stale_version},
        facility_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, 412)

    unbilled = validate_success(
        api.get_work_order(scenario["work_order"]["id"], facility_admin_headers)
    )
    assert unbilled["status"] == "COMPLETED"
    assert unbilled["billable_amount_cents"] == 0

    contract = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert contract["billed_total_cents"] == 1200000, (
        f"only the two crush fees have posted, got {contract['billed_total_cents']}"
    )

    billed = validate_success(
        api.bill_work_order(
            scenario["work_order"]["id"],
            {"expected_contract_version": contract["version"]},
            facility_admin_headers,
        )
    )
    assert billed["status"] == "BILLED"
    assert billed["billable_amount_cents"] == 49400

    after = validate_success(api.get_contract(contract_id, facility_admin_headers))
    assert after["billed_total_cents"] == 1249400


def test_a_compliance_officer_may_not_bill_a_work_order(api, compliance_officer_headers,
                                                        facility_admin_headers):
    """PRD 2.1: "A `FacilityAdmin` is the facility's operations manager. This
    role owns the commercial surface — clients, contracts, cooperage, bottling
    lines and dry goods — and is the only role permitted to bill a work order
    onto the contract ledger."
    PRD 2.1: "First, the caller's role must appear in the authorized-role list
    published for the target endpoint in §4; a caller whose role is absent from
    that list is rejected with `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/corner_compliance_officer_cannot_bill_work_orders
    """
    scenario = setup_completed_work_order(
        actual_labor_hours=1.00,
        work_order_overrides={"operation_type": "TOPPING", "labor_hours": 1.00,
                              "crew_size": 1},
        delivery_ticket="DT-AH1",
    )

    response = api.bill_work_order(
        scenario["work_order"]["id"],
        {"expected_contract_version": read_contract_version(scenario["contract"]["id"])},
        compliance_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    order = validate_success(
        api.get_work_order(scenario["work_order"]["id"], facility_admin_headers)
    )
    assert order["status"] == "COMPLETED"
    assert order["billed_by_user_id"] is None

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["billed_total_cents"] == 950000


def test_segregation_of_duties_compares_user_ids_not_roles(api, facility_admin_headers):
    """PRD 2.9: "A work order is executed by one cellar user and billed by
    another: the `X-User-ID` billing an order must differ from the
    `executed_by_user_id` recorded when the order started."
    PRD 2.9: "Because these are user-identity comparisons and not role
    comparisons, two different `ComplianceOfficer` user ids satisfy the filing
    rule while one officer acting twice does not."

    Design: Corner/rbac/corner_shared_user_id_across_roles_cannot_bill_own_work_order
    """
    dual_supervisor = make_cellar_supervisor_headers("u-dual")
    dual_admin = make_facility_admin_headers("u-dual")
    scenario = setup_completed_work_order(
        supervisor_headers=dual_supervisor, delivery_ticket="DT-AJ1"
    )
    assert scenario["work_order"]["executed_by_user_id"] == "u-dual"

    version = read_contract_version(scenario["contract"]["id"])
    response = api.bill_work_order(
        scenario["work_order"]["id"], {"expected_contract_version": version}, dual_admin
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    billed = validate_success(
        api.bill_work_order(
            scenario["work_order"]["id"],
            {"expected_contract_version": version},
            facility_admin_headers,
        )
    )
    assert billed["status"] == "BILLED"
    assert billed["billed_by_user_id"] == FACILITY_ADMIN_ID

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["billed_total_cents"] == 999400


# ── The volume-discount tier read from the undiscounted basis ────────


def test_discount_tier_is_selected_from_the_undiscounted_basis(
    api, facility_admin_headers
):
    """PRD 3.6: "Fourth, the volume-discount tier is selected — once — from an
    **undiscounted** basis: take the contract's `billed_total_cents` as it
    stands immediately before this bill and add `subtotal_cents`. If that basis
    is at least 3,000,000 cents (thirty thousand dollars of contract-to-date
    business) then `volume_discount_pct` is 10; otherwise, if it is at least
    1,000,000 cents (ten thousand dollars) then `volume_discount_pct` is 5;
    otherwise it is 0."
    PRD 3.6: "Fifth, `billable_amount_cents` is `subtotal_cents` less the
    discount, where the discount is `subtotal_cents` multiplied by
    `volume_discount_pct` divided by 100 and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/work_order_discount_tier_read_from_undiscounted_basis
    """
    scenario = setup_completed_work_order(delivery_ticket="DT-3001")

    data = validate_success(
        api.bill_work_order(
            scenario["work_order"]["id"],
            {"expected_contract_version": read_contract_version(scenario["contract"]["id"])},
            facility_admin_headers,
        )
    )

    assert data["base_labor_cents"] == 50000, "2.50 hours x 2 crew x 10000 cents"
    assert data["rush_surcharge_cents"] == 0, "rush is false on this order"
    assert data["subtotal_cents"] == 52000
    assert data["volume_discount_pct"] == pytest.approx(5, abs=0.01), (
        f"the undiscounted basis 950000 + 52000 clears 1,000,000 cents, got "
        f"{data['volume_discount_pct']}"
    )
    assert data["billable_amount_cents"] == 49400, (
        f"52000 less 5 percent, not the 52000 a re-selecting reading would "
        f"bill; got {data['billable_amount_cents']}"
    )
    assert_work_order_billing_chain(data)


def test_the_tier_is_never_re_selected_after_the_discount_lands(
    api, facility_admin_headers
):
    """PRD 3.6: "The tier is never re-selected after the discount is applied, so
    the result stays well defined even when discounting would drop the running
    total back below the threshold that selected the tier."
    PRD 3.6: "The order then moves `COMPLETED` to `BILLED`, `billed_by_user_id`
    records the acting admin, the contract's `billed_total_cents` increases by
    `billable_amount_cents`, and the contract's `version` increments by 1."

    Design: Difficulty/combinatorial_formula/work_order_discount_tier_read_from_undiscounted_basis
    """
    scenario = setup_completed_work_order(delivery_ticket="DT-3001")

    billed = validate_success(
        api.bill_work_order(
            scenario["work_order"]["id"],
            {"expected_contract_version": read_contract_version(scenario["contract"]["id"])},
            facility_admin_headers,
        )
    )
    assert billed["status"] == "BILLED"
    assert billed["billed_by_user_id"] == FACILITY_ADMIN_ID

    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["billed_total_cents"] == 999400, (
        f"950000 + 49400, which falls back below the 1,000,000-cent threshold "
        f"that selected the tier; got {contract['billed_total_cents']}"
    )


# ── The cross-entity gate on scheduling a work order ─────────────────


def test_scheduling_is_blocked_while_the_governing_contract_is_suspended(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.6: "A `CellarSupervisor` schedules the order, moving `REQUESTED` to
    `SCHEDULED`; the governing contract must be `ACTIVE`
    (`ERR_CONTRACT_NOT_ACTIVE`) and the target lot must not already be finished
    with — a lot standing in `CONSUMED` or `BOTTLED` is refused with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/work_order_schedule_gated_by_contract_status
    """
    scenario = setup_contract_with_lot(
        clock="2026-09-20T00:00:00Z", delivery_ticket="DT-9001"
    )
    order = new_work_order(
        scenario["lot"]["id"],
        headers=scenario["rep_headers"],
        operation_type="RACKING",
        scheduled_at="2026-09-22T14:00:00Z",
        labor_hours=1.50,
        crew_size=2,
    )
    validate_success(
        api.contract_transition(
            scenario["contract"]["id"], {"action": "SUSPEND"}, facility_admin_headers
        )
    )

    response = api.work_order_transition(
        order["id"], {"action": "SCHEDULE"}, cellar_supervisor_headers
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

    stored = validate_success(api.get_work_order(order["id"], facility_admin_headers))
    assert stored["status"] == "REQUESTED", (
        f"the rejected schedule must leave the order in REQUESTED, got "
        f"{stored['status']}"
    )


def test_reinstating_the_contract_unblocks_the_identical_schedule_call(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.1: "Reinstating a `SUSPENDED` contract returns it to `ACTIVE`,
    again requiring the client to be `ACTIVE`."
    PRD 3.6: "Two optional inputs shape the eventual charge:
    `material_cost_cents` passes additive and material costs straight through
    and defaults to 0 when omitted, and `rush` is a boolean that defaults to
    false and, when true, adds a quarter again to the base labour charge at
    billing time."

    Design: Difficulty/cross_entity_state_dependency/work_order_schedule_gated_by_contract_status
    """
    scenario = setup_contract_with_lot(
        clock="2026-09-20T00:00:00Z", delivery_ticket="DT-9001"
    )
    order = new_work_order(
        scenario["lot"]["id"],
        headers=scenario["rep_headers"],
        operation_type="RACKING",
        scheduled_at="2026-09-22T14:00:00Z",
        labor_hours=1.50,
        crew_size=2,
    )
    assert order["material_cost_cents"] == 0, "material_cost_cents defaults to 0"
    assert order["rush"] is False, "rush defaults to false"

    validate_success(
        api.contract_transition(
            scenario["contract"]["id"], {"action": "SUSPEND"}, facility_admin_headers
        )
    )
    api.work_order_transition(order["id"], {"action": "SCHEDULE"}, cellar_supervisor_headers)
    validate_success(
        api.contract_transition(
            scenario["contract"]["id"], {"action": "REINSTATE"}, facility_admin_headers
        )
    )

    scheduled = validate_success(
        api.work_order_transition(
            order["id"], {"action": "SCHEDULE"}, cellar_supervisor_headers
        )
    )
    assert scheduled["status"] == "SCHEDULED", (
        "the same call must succeed once the contract is ACTIVE again"
    )
