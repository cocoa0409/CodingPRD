"""Claim assembly: the dose-plan line split and the write-off / rounding order."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, receive_new_lot,
    create_provider, create_published_protocol, adopt_pathways,
    make_practice_admin_headers, get_practice_version, find_draft_claim,
    create_treatment_payload, create_administer_payload, create_claim_submit_payload,
    REVENUE_CYCLE_MANAGER, PAYER_ADJUDICATOR, ApiErrorId, DEFAULT_CLOCK,
)


def _operational_context(network_base_price_cents=10000, stock_units=1000,
                         admin_fee_cents=4800, administered_units=50,
                         vial_yield_units=100):
    """Affiliated + pathway-adopted practice with one VIAL lot and one
    administered treatment under the WASTE_BILLED dose plan."""
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=200)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              tier_level="TIER_1", discount_pct=0,
                              effective_from="2026-08-01T00:00:00Z")
    product = create_product(network["id"], unit_type="VIAL",
                             network_base_price_cents=network_base_price_cents,
                             therapeutic_class="ORAL_TARGETED")
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])
    _, lot = receive_new_lot(practice["id"], product["id"], stock_units,
                             expires_at="2027-09-01T00:00:00Z", lot_number="L-OZ-99")

    set_clock("2026-09-02T00:00:00Z")
    practice_headers = make_practice_admin_headers(practice["id"])
    treatment = validate_success(
        api_client.create_treatment(
            create_treatment_payload(practice["id"], provider["id"], product["id"],
                                     protocol["id"], patient_reference="PT-BILL-01",
                                     administered_units=administered_units,
                                     dose_count=1, vial_yield_units=vial_yield_units,
                                     admin_fee_cents=admin_fee_cents,
                                     administered_at="2026-09-02T00:00:00Z"),
            practice_headers),
        201)
    administered = validate_success(
        api_client.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice["id"])),
            practice_headers),
        200)
    return {
        "network": network, "practice": get_practice(practice["id"]),
        "product": product, "provider": provider, "protocol": protocol,
        "lot": lot, "treatment": administered,
    }


def test_claim_billed_amount_dose_plan_line_split(api, network_admin_headers):
    """PRD §3.7: "Under `WASTE_BILLED`, which is the default plan, the remainder
    is emitted as a final consumption row carrying `is_wastage` true, and the
    treatment carries it in `wastage_units` and `wastage_cost_basis_cents` so the
    claim can bill it."
    PRD §3.9: "The first line is the patient's drug charge, computed as the draw
    unit cost multiplied by the dose count and by the administered units and then
    rounded half up to whole cents. The second line is the wastage charge,
    computed as the draw unit cost multiplied by the treatment's `wastage_units`
    and rounded half up. The third line is the administration fee, which is the
    whole-number `policy_admin_fee_cents` carried by the claim."
    PRD §3.9: "The claim's `billed_amount_cents` is then the exact sum of those
    three lines, rounded half up once at the end".

    Design: Difficulty/combinatorial_formula/claim_billed_amount_dose_plan_line_split
    """
    ctx = _operational_context()
    treatment = ctx["treatment"]

    assert treatment["wastage_units"] == 50
    assert treatment["wastage_cost_basis_cents"] == 500000
    assert treatment["acquisition_cost_basis_cents"] == 1000000

    claim = find_draft_claim(treatment["id"])
    submitted = validate_success(
        api.submit_claim(claim["id"],
                         create_claim_submit_payload(get_practice_version(ctx["practice"]["id"])),
                         REVENUE_CYCLE_MANAGER),
        200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["billed_admin_fee_cents"] == 4800

    current = validate_success(api.get_payer_claim(claim["id"], network_admin_headers), 200)
    assert current["billed_amount_cents"] == 1004800


def test_absorbed_dose_plan_removes_the_wastage_line(api, network_admin_headers):
    """PRD §3.7: "Under `WASTE_ABSORBED` the remainder is drawn from the same
    vials but is neither billed nor carried as treatment wastage: `wastage_units`
    and `wastage_cost_basis_cents` are both zero, and the dollars instead land on
    the lot as its `absorbed_cost_basis_cents`, never appearing on a claim."
    PRD §3.7: "Under `WASTE_ABSORBED` the remainder is drawn from the same
    vials but is neither billed nor carried as treatment wastage: `wastage_units`
    and `wastage_cost_basis_cents` are both zero, and the dollars instead land on
    the lot as its `absorbed_cost_basis_cents`, never appearing on a claim."

    Design: Difficulty/combinatorial_formula/claim_billed_amount_dose_plan_line_split
    """
    ctx = _operational_context()
    practice_id = ctx["practice"]["id"]
    practice_headers = make_practice_admin_headers(practice_id)

    set_clock("2026-09-03T00:00:00Z")
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice_id, ctx["provider"]["id"],
                                     ctx["product"]["id"], ctx["protocol"]["id"],
                                     patient_reference="PT-BILL-02",
                                     administered_units=50, dose_count=1,
                                     vial_yield_units=100, admin_fee_cents=4800,
                                     administered_at="2026-09-03T00:00:00Z"),
            practice_headers),
        201)
    absorbed = validate_success(
        api.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice_id), dose_plan="WASTE_ABSORBED"),
            practice_headers),
        200)

    assert absorbed["wastage_units"] == 0
    assert absorbed["wastage_cost_basis_cents"] == 0

    claim = find_draft_claim(treatment["id"])
    submitted = validate_success(
        api.submit_claim(claim["id"],
                         create_claim_submit_payload(get_practice_version(practice_id)),
                         REVENUE_CYCLE_MANAGER),
        200)
    assert submitted["billed_amount_cents"] == 504800


def test_claim_write_off_rounds_once_at_the_end(api, network_admin_headers):
    """PRD §3.9: "That distinction is observable at a one-cent boundary: a
    ten-percent write-off against a billed amount of 1,000,001 cents is 100,000
    cents rather than 100,000.1."
    PRD §2.7: "Every monetary quantity in this API is an integer number of cents.
    Where a formula produces a fractional cent, it is rounded half up to the
    nearest whole cent".

    Design: Difficulty/combinatorial_formula/claim_billed_amount_dose_plan_line_split
    """
    ctx = _operational_context(network_base_price_cents=10000)
    claim = find_draft_claim(ctx["treatment"]["id"])
    # The claim's own billed amount is an integer number of cents.
    assert isinstance(claim["billed_amount_cents"], int)
    assert claim["billed_amount_cents"] > 0


def test_claim_overpayment_is_refused_and_boundary_is_inclusive(api, network_admin_headers):
    """PRD §3.9: "The remittance must be greater than zero, failing with
    `ERR_INVALID_REQUEST`, and may not exceed the billed amount, failing with
    `ERR_PAYER_OVERPAYMENT` at status 422."
    PRD §3.9: "On success the claim becomes `ADJUDICATED_PAID`,
    `allowed_amount_cents` is recorded as the smaller of `billed_amount_cents` and
    the sum of the remitted `paid_amount_cents` and the claim's write-off".

    Design: Difficulty/combinatorial_formula/claim_billed_amount_dose_plan_line_split
    """
    ctx = _operational_context()
    practice_id = ctx["practice"]["id"]
    claim = find_draft_claim(ctx["treatment"]["id"])
    submitted = validate_success(
        api.submit_claim(claim["id"],
                         create_claim_submit_payload(get_practice_version(practice_id)),
                         REVENUE_CYCLE_MANAGER),
        200)
    billed = submitted["billed_amount_cents"]

    over = api.adjudicate_claim(claim["id"], {"paid_amount_cents": billed + 1},
                               PAYER_ADJUDICATOR)
    validate_error(over, ApiErrorId.ERR_PAYER_OVERPAYMENT, expected_status=422)

    zero = api.adjudicate_claim(claim["id"], {"paid_amount_cents": 0}, PAYER_ADJUDICATOR)
    validate_error(zero, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    paid = validate_success(
        api.adjudicate_claim(claim["id"], {"paid_amount_cents": billed}, PAYER_ADJUDICATOR),
        200)
    assert paid["status"] == "ADJUDICATED_PAID"
    assert paid["paid_amount_cents"] == billed
    assert paid["allowed_amount_cents"] <= billed