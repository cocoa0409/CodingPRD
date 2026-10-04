"""Claim-state gating on the payer side and the observable effect of a freeze."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, receive_new_lot,
    create_provider, create_published_protocol, adopt_pathways, find_draft_claim,
    make_practice_admin_headers, get_practice_version, create_treatment_payload,
    create_administer_payload, create_purchase_order_payload,
    REVENUE_CYCLE_MANAGER, PAYER_ADJUDICATOR, DEFAULT_CLOCK,
)


def _draft_claim_context():
    """Affiliated + pathway-adopted practice with one administered treatment whose
    claim is still DRAFT."""
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-08-01T00:00:00Z")
    product = create_product(network["id"], unit_type="VIAL")
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])
    receive_new_lot(practice["id"], product["id"], 400)

    set_clock("2026-09-02T00:00:00Z")
    treatment = validate_success(
        api_client.create_treatment(
            create_treatment_payload(practice["id"], provider["id"], product["id"],
                                     protocol["id"], patient_reference="PT-DRF-1",
                                     administered_units=100, dose_count=1,
                                     vial_yield_units=100,
                                     administered_at="2026-09-02T00:00:00Z"),
            make_practice_admin_headers(practice["id"])),
        201)
    validate_success(
        api_client.administer_treatment(
            treatment["id"],
            create_administer_payload(get_practice_version(practice["id"])),
            make_practice_admin_headers(practice["id"])),
        200)
    return network, practice, product, treatment, find_draft_claim(treatment["id"])


def test_claim_appeal_twice_returns_appeal_limit_reached(api, network_admin_headers):
    """PRD §3.9: "Adjudication is accepted from `SUBMITTED` or from `APPEALED`,
    and any other status fails with `ERR_CLAIM_NOT_SUBMITTED`."
    PRD §3.9: "A denial is recorded by the same `PayerAdjudicator` role against a
    claim in `SUBMITTED` or `APPEALED`, any other status failing with
    `ERR_CLAIM_NOT_SUBMITTED`".

    Design: Corner/state_machines/claim_appeal_twice_returns_appeal_limit_reached
    """
    _, _, _, _, claim = _draft_claim_context()
    assert claim["status"] == "DRAFT"
    assert claim["appeal_round"] == 0

    res_adjudicate = api.adjudicate_claim(
        claim["id"], {"paid_amount_cents": 100000}, PAYER_ADJUDICATOR)
    validate_error(res_adjudicate, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, expected_status=409)

    res_deny = api.deny_claim(
        claim["id"], {"denial_reason_code": "MEDICAL_NECESSITY"}, PAYER_ADJUDICATOR)
    validate_error(res_deny, ApiErrorId.ERR_CLAIM_NOT_SUBMITTED, expected_status=409)

    current = validate_success(api.get_payer_claim(claim["id"], network_admin_headers), 200)
    assert current["status"] == "DRAFT"
    assert current["appeal_round"] == 0


def test_frozen_terms_change_behavior_on_the_same_agreement(api, network_admin_headers):
    """PRD §2.10: "A network may be placed into a frozen commercial window by an
    operator holding `NetworkAdmin`."
    PRD §2.10: "A freeze is not a change to any agreement's own status. It
    changes the price: an agreement inside a frozen window keeps its `ACTIVE`
    status while the discount it nominates is not credited".
    PRD §3.5: "The `frozen_terms_list_price` variant applies when the order's
    instant sits inside a frozen commercial-terms window: the agreement keeps its
    `ACTIVE` status but the discount is deliberately not credited, so the order
    lands at the same list price as the fallback while having reached it through a
    live agreement."

    Design: Corner/cross_cutting_complexity_layers/frozen_terms_change_behavior_on_the_same_agreement
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=100)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    agreement = create_approved_agreement(practice["id"], practice["version"],
                                          tier_level="TIER_1", discount_pct=0.10,
                                          effective_from="2026-08-01T00:00:00Z")
    product = create_product(network["id"], unit_type="VIAL",
                             network_base_price_cents=1000)

    frozen = validate_success(
        api.freeze_commercial_terms(network["id"], network_admin_headers), 200)
    assert frozen["is_commercial_terms_frozen"] is True

    agreement_after = validate_success(
        api.get_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert agreement_after["status"] == "ACTIVE"

    # An order inside the frozen window lands at list price, not at the discount.
    order = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=10),
            make_practice_admin_headers(practice["id"])),
        201)
    assert order["unit_price_cents"] == 1000