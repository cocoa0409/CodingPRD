"""Three money formulas whose answer depends on the order in which their steps
are evaluated: the cash quote on a beneficiary notice, the three-bucket patient
responsibility with its nested unit minimum, and the refund split on a return.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assert_encounter_states,
    assert_money,
    assert_responsibility,
    assert_shelf,
    build_practice,
    inventory_manager_headers,
    practice_admin_headers,
    read_encounter,
    read_shelf,
)
from test_helpers import factories as f


def _knee_practice(api, on_shelf=10, requires_prior_auth=False):
    """A clinic stocking the adjustable knee orthosis: allowed 22000 cents,
    cash price 19999 cents."""
    practice = build_practice(
        api,
        product_factory=lambda supplier_id: f.knee_brace_product_payload(
            supplier_id, requires_prior_auth=requires_prior_auth
        ),
        with_shelf=False,
    )
    product = practice.product
    shelf = validate_success(
        api.create_par_level(
            f.par_level_payload(practice.clinic_id, product["id"]), inventory_manager_headers()
        ),
        201,
    )
    shelf = validate_success(
        api.receive_stock(
            shelf["id"], f.stock_receipt_payload(on_shelf), inventory_manager_headers()
        ),
        201,
    )
    practice.product_id = product["id"]
    practice.product = product
    practice.par_level_id = shelf["id"]
    practice.par_level = shelf
    return practice


def test_cash_quote_rounds_the_discounted_unit_price_before_multiplying(api):
    """Five uncovered units are quoted by rounding the discounted unit price once
    and then multiplying, which lands one cent below the figure a caller would get
    by discounting the whole line and rounding at the end.

    PRD: "Third, `estimated_subtotal_cents` is that already-rounded
    `unit_net_price_cents` multiplied by the quoted unit count — rounding first
    and multiplying second is required, and multiplying first and rounding the
    product is a different and incorrect number."

    Design: Difficulty/combinatorial_formula/abn_cash_quote_round_per_unit_then_multiply_mode_b
    """
    practice = _knee_practice(api)
    encounter_id = practice.verified_encounter(quantity=5, coverage={"covered": False})

    notice = practice.issue_abn(encounter_id)

    assert notice["notice_seq"] == 1
    assert notice["status"] == "ISSUED"
    assert_money(notice, "unit_net_price_cents", 16999)
    assert_money(notice, "estimated_subtotal_cents", 84995)
    assert notice["estimated_subtotal_cents"] != 84996, (
        "discounting the whole line and rounding once would answer 84996"
    )
    assert_encounter_states(
        read_encounter(api, encounter_id), financial_status="ABN_ISSUED"
    )


def test_cash_quote_charges_the_dispensing_fee_only_below_the_waiver_threshold(api):
    """The five-unit quote clears the waiver threshold on its subtotal alone and
    carries no fee, while a single-unit quote of the same device is undiscounted
    and does carry the fee.

    PRD: "Fourth, the flat dispensing fee of 2500 cents, twenty-five dollars, is
    charged as `dispensing_fee_cents` when `estimated_subtotal_cents` is strictly
    below the waiver threshold of 50000 cents, five hundred dollars, and is 0 when
    the subtotal reaches that threshold or exceeds it — the fee is waived **at**
    the threshold, and the threshold is keyed on the subtotal and never on the
    total."

    Design: Difficulty/combinatorial_formula/abn_cash_quote_round_per_unit_then_multiply_mode_b
    """
    practice = _knee_practice(api)
    bulk_encounter_id = practice.verified_encounter(quantity=5, coverage={"covered": False})
    bulk_notice = practice.issue_abn(bulk_encounter_id)

    assert_money(bulk_notice, "estimated_subtotal_cents", 84995)
    assert_money(bulk_notice, "dispensing_fee_cents", 0)
    assert_money(bulk_notice, "estimated_cost_cents", 84995)

    other_patient = validate_success(
        api.create_patient(
            practice.clinic_id,
            f.patient_payload(full_name="Joel Pike", dob="1958-09-19"),
            practice_admin_headers(),
        ),
        201,
    )
    single_encounter_id = practice.verified_encounter(
        quantity=1, coverage={"covered": False}, patient_id=other_patient["id"]
    )
    single_notice = practice.issue_abn(single_encounter_id)

    assert_money(single_notice, "unit_net_price_cents", 19999)
    assert_money(single_notice, "estimated_subtotal_cents", 19999)
    assert_money(single_notice, "dispensing_fee_cents", 2500)
    assert_money(single_notice, "estimated_cost_cents", 22499)


def _partially_authorized_encounter(api):
    """Three units of an authorization-bearing knee orthosis where the payer
    approved only two, with the excess unit's notice signed."""
    practice = _knee_practice(api, requires_prior_auth=True)
    encounter_id = practice.attested_encounter(quantity=3)
    practice.verify_coverage(
        encounter_id, covered=True, deductible_remaining_cents=0, coinsurance_pct=0.2
    )
    request = practice.request_prior_auth(encounter_id, requested_units=3)
    practice.decide_prior_auth(
        request["id"], decision="APPROVED", approved_units=2, auth_number="AUTH-77001"
    )
    notice = practice.issue_abn(encounter_id, reason_non_covered="UNITS_EXCEED_AUTH")
    practice.sign_abn(notice["id"], option="OPTION_1")
    return practice, encounter_id, notice


def test_partially_authorized_responsibility_takes_the_lesser_of_quantity_and_approval(api):
    """With three units ordered and two approved, the insurance line is computed
    over the approved units only and the third unit is priced as undiscounted cash.

    PRD: "Otherwise, if the product's `requires_prior_auth` is true,
    `covered_units` is the lesser of the encounter's `quantity` and the
    authorization's `approved_units`."

    Design: Difficulty/combinatorial_formula/patient_responsibility_nested_min_and_branch_selection_mode_a
    """
    practice, encounter_id, _notice = _partially_authorized_encounter(api)
    practice.reserve(encounter_id)
    practice.fit(encounter_id)

    delivered = practice.dispense(encounter_id)

    assert delivered["covered_units"] == 2
    assert_responsibility(
        delivered,
        patient_responsibility_cents=28799,
        billable_amount_cents=35200,
        responsibility_variant="INSURANCE_ASSIGNED",
    )
    assert_encounter_states(delivered, clinical_status="DELIVERED", financial_status="BILLED")


def test_single_excess_unit_is_priced_without_the_multi_unit_cash_discount(api):
    """The excess-unit notice quotes one unit, so the multi-unit discount does not
    apply even though the encounter as a whole orders three units, and the shelf
    gives up all three units at delivery.

    PRD: "The cash-excess bucket then prices the units beyond `covered_units` at
    the cash unit price: if the **excess** unit count alone is 2 or more, the
    per-unit figure is the product's `cash_price_cents` multiplied by 0.85 and
    rounded half up to a whole cent, and otherwise it is `cash_price_cents`
    unchanged — the multi-unit discount here is decided by the excess unit count
    alone and never by the encounter's whole `quantity`."

    Design: Difficulty/combinatorial_formula/patient_responsibility_nested_min_and_branch_selection_mode_a
    """
    practice, encounter_id, notice = _partially_authorized_encounter(api)

    assert notice["reason_non_covered"] == "UNITS_EXCEED_AUTH"
    assert_money(notice, "unit_net_price_cents", 19999)
    assert_money(notice, "estimated_subtotal_cents", 19999)
    assert_money(notice, "dispensing_fee_cents", 2500)
    assert_money(notice, "estimated_cost_cents", 22499)

    practice.reserve(encounter_id)
    practice.fit(encounter_id)
    practice.dispense(encounter_id)

    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=7,
        reserved_qty=0,
        available_qty=7,
        stock_posture="OK",
    )


def test_restock_refund_rounds_the_device_split_then_each_refund_line(api):
    """A poor-fit return of a sellable device splits the charge 85/15, rounds each
    refund line on its own and derives the retained fee by subtraction, so the two
    figures reconcile to the original charge exactly.

    PRD: "`refund_cents` is the sum of the two refunds, and `restock_fee_cents` is
    the charge less `refund_cents` — derived by subtraction, never by multiplying
    the charge by the fee fraction, so that the two figures always reconcile to the
    original charge to the cent."

    Design: Difficulty/combinatorial_formula/restock_refund_pinned_evaluation_order_mode_c
    """
    practice = build_practice(api)
    encounter_id = practice.delivered_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    opened = practice.open_return(encounter_id, reason="POOR_FIT")

    inspected = practice.inspect_return(opened["id"], condition="SELLABLE")

    assert inspected["status"] == "RESTOCKED"
    assert inspected["restock_eligible"] is True
    assert_money(inspected, "device_component_cents", 8755)
    assert_money(inspected, "fitting_component_cents", 1545)
    assert_money(inspected, "device_refund_cents", 7880)
    assert_money(inspected, "fitting_refund_cents", 1468)
    assert_money(inspected, "refund_cents", 9348)
    assert_money(inspected, "restock_fee_cents", 952)
    assert inspected["refund_cents"] + inspected["restock_fee_cents"] == 10300
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=10,
        stock_posture="OK",
    )


def test_non_sellable_poor_fit_return_uses_the_heaviest_fee_fraction(api):
    """The same poor-fit charge, inspected as soiled, is not restock-eligible, so
    the fee fraction is overridden upward and both refund lines shrink.

    PRD: "That table is then overridden in one case: when the return is **not**
    restock-eligible and the reason is `POOR_FIT` or `PATIENT_REFUSED`, the
    fraction becomes 0.25 — a patient-caused return of a device that can no longer
    be sold carries the heaviest fee, above either of that reason's own base rates."

    Design: Difficulty/combinatorial_formula/restock_refund_pinned_evaluation_order_mode_c
    """
    practice = build_practice(api)
    encounter_id = practice.delivered_encounter(
        coverage={"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}
    )
    opened = practice.open_return(encounter_id, reason="POOR_FIT")

    inspected = practice.inspect_return(opened["id"], condition="SOILED")

    assert inspected["status"] == "DESTROYED"
    assert inspected["restock_eligible"] is False
    assert_money(inspected, "device_component_cents", 8755)
    assert_money(inspected, "fitting_component_cents", 1545)
    assert_money(inspected, "device_refund_cents", 6566)
    assert_money(inspected, "fitting_refund_cents", 1352)
    assert_money(inspected, "refund_cents", 7918)
    assert_money(inspected, "restock_fee_cents", 2382)
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=9,
    )
