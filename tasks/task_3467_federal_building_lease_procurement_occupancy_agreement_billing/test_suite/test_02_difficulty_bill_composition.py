"""Combinatorial formulas: pinned evaluation order and nested rounding."""
from test_helpers import (
    TEST_USERS, approve_alteration, assert_rent_bill, complete_alteration,
    create_alteration, create_ticket, estimate_alteration, generate_bill,
    make_agency_manager_headers, set_clock, setup_active_leased_oa,
    validate_success,
)

PM = TEST_USERS["gsa_property_manager_headers"]
ADMIN = TEST_USERS["gsa_admin_headers"]


def test_monthly_bill_pinned_ordering_fee_abatement_credit(api):
    """PRD §3.5: "`abatement_credit_cents` equals `shell_cents` when the
    agreement is leased and the month index falls within the lease's
    `free_rent_months`; otherwise it is zero."
    PRD §3.5: "The subtotal is `shell_cents` minus `abatement_credit_cents`,
    plus `operating_cents`, `tax_escalation_cents`, `ti_amortization_cents`,
    `alteration_amortization_cents`, and `lump_sum_charges_cents`."
    PRD §3.5: "`fee_cents` is the GSA fee: five percent of the subtotal,
    rounded half up."
    PRD §3.5: "`service_credit_applied_cents` consumes the agreement's
    `pending_service_credit_cents`, up to the subtotal plus the fee."
    PRD §3.5: "`total_cents` is the subtotal plus the fee minus the applied
    service credit, never below zero."
    PRD §3.7: "A breached ticket earns ten thousand cents per started
    twenty-four-hour block of overrun — partial blocks round up — capped at
    one hundred thousand cents."

    On the canonical February fixture the abatement strips the shell BEFORE the
    fee: subtotal 6,113,470 -> fee 305,674 (not 5% of the gross 23,188,470),
    and the 20,000-cent SLA credit (49h open vs 24h SLA -> 2 blocks) is
    consumed last, yielding total 6,399,144.

    Design: Difficulty/combinatorial_formula/monthly_bill_pinned_ordering_fee_abatement_credit
    """
    bundle = setup_active_leased_oa()  # 2027 stmt actual 460 recorded
    oa, agency, building = bundle["oa"], bundle["agency"], bundle["building"]
    agency_h = make_agency_manager_headers(agency["id"])

    # CRITICAL ticket open 2027-01-20T00:00 -> resolved 2027-01-22T01:00 (49h).
    set_clock("2027-01-20T00:00:00Z")
    ticket = create_ticket(building, oa, agency, category="MAINTENANCE",
                           severity="CRITICAL", description="Elevator bank outage")
    set_clock("2027-01-22T01:00:00Z")
    validate_success(api.resolve_ticket(ticket["id"], PM), 200)
    verified = validate_success(api.verify_ticket(ticket["id"], agency_h), 200)
    assert verified["sla_breached"] is True
    assert verified["credit_cents"] == 20000

    oa_mid = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_mid["pending_service_credit_cents"] == 20000

    bill = generate_bill(oa, "2027-02")
    assert_rent_bill(bill)
    assert bill["shell_cents"] == 17075000
    assert bill["abatement_credit_cents"] == 17075000, (
        "month_index 2 <= free_rent_months 3: shell fully abated")
    assert bill["operating_cents"] == 5122500
    assert bill["tax_escalation_cents"] == 341500
    assert bill["ti_amortization_cents"] == 649470
    assert bill["fee_cents"] == 305674, (
        "5% of the POST-abatement subtotal 6,113,470, not of the gross")
    assert bill["service_credit_applied_cents"] == 20000
    assert bill["total_cents"] == 6399144

    oa_after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_after["pending_service_credit_cents"] == 0, (
        "the credit is consumed last, at generation")


def test_alteration_amortization_monthly_first_rounding_residual_final(api):
    """PRD §3.6: "The level `monthly_amort_cents` is computed first — the
    principal times the monthly rate, divided by one minus the quantity
    one-plus-the-monthly-rate raised to the negative power of the term — and
    rounded half up to whole cents before anything else."
    PRD §3.6: "The `amortization_balance_cents` then tracks the exact,
    unrounded remaining balance: each month before the last, the balance grows
    by one month of interest and the level payment is subtracted; the final
    month — the agreement's end month — bills the remaining balance grown by
    one more month of interest, rounded half up, so the residual is absorbed by
    the last month."
    PRD §3.6: "Computing the total first and dividing is expressly forbidden:
    it produces different cents."
    PRD §3.5: "`alteration_amortization_cents` sums, over the agreement's
    `COMPLETED` amortized alterations whose billed span — from
    `amortization_start_month` through the agreement's end month — covers the
    billing month, that month's scheduled charge: the level
    `monthly_amort_cents` for every month of a schedule except its final month,
    which bills its residual amount instead (§3.6)."

    10,000,000 cents over 102 months at 7%/12: level month 130,359, final
    month 130,322 — the rounding drift lands entirely in the final month.

    Design: Difficulty/combinatorial_formula/alteration_amortization_monthly_first_rounding_residual_final
    """
    bundle = setup_active_leased_oa()
    oa, agency = bundle["oa"], bundle["agency"]

    alt = create_alteration(oa, agency, title="SCIF build-out",
                            description="Secure suite on floor 4", scope_sf=2000)
    estimate_alteration(alt, estimated_cost_cents=10000000,
                        work_start_date="2028-03-01", work_end_date="2028-06-10")
    approve_alteration(alt, agency, funding_method="AMORTIZED")
    done = complete_alteration(alt, "2028-06-15")

    assert done["amortization_months"] == 102, (
        "months 2028-07 .. 2036-12 inclusive")
    assert done["amortization_start_month"] == "2028-07"
    assert done["monthly_amort_cents"] == 130359

    bill_first = generate_bill(oa, "2028-08")
    assert_rent_bill(bill_first)
    assert bill_first["alteration_amortization_cents"] == 130359, (
        "a level month bills the rounded level payment")
    assert bill_first["total_cents"] == 24484770

    bill_final = generate_bill(oa, "2036-12")
    assert bill_final["alteration_amortization_cents"] == 130322, (
        "the final month absorbs the rounding residual")
    assert bill_final["total_cents"] == 24484732
