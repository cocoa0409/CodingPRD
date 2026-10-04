"""Difficulty queue: dual-variant calculation — two pricing baselines and the
provisional-price vs executed-settlement divergence."""
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_agreement, create_claim, add_line, reprice, open_case, place_offer,
    find_settlement_for_case,
    create_payer_client_payload, create_provider_payload,
    create_network_agreement_payload, create_medicare_entry_payload,
    create_repricing_policy_payload, create_claim_payload,
    create_claim_line_payload, create_negotiation_case_payload,
    create_offer_payload,
    TEST_USERS, make_payer_admin_headers, make_payer_rep_headers,
    make_provider_rep_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
NET = TEST_USERS["network_admin_headers"]


def _setup_dual_variant_world():
    """Payer + provider + agreement + Medicare entry + two OON policies."""
    payer = get_success_data(api_client.create_payer_client(
        create_payer_client_payload(transparency_reporting_enabled=True), OPS))
    provider = get_success_data(api_client.create_provider(
        create_provider_payload(npi="1000000001", legal_name="PR1", tin="T1"), NET))
    pa = make_payer_admin_headers(payer["id"])
    pr = make_payer_rep_headers(payer["id"])
    get_success_data(api_client.create_network_agreement(
        create_network_agreement_payload(provider["id"], network_name="N1",
                                         discount_percent=0.40), NET))
    get_success_data(api_client.create_medicare_entry(
        create_medicare_entry_payload(), NET))
    get_success_data(api_client.create_repricing_policy(
        create_repricing_policy_payload(
            payer["id"], claim_type="ANCILLARY", methodology="CONTRACTED_NETWORK",
            percent_of_medicare=None, priority=1), pa))
    get_success_data(api_client.create_repricing_policy(
        create_repricing_policy_payload(
            payer["id"], claim_type="PROFESSIONAL",
            methodology="PERCENT_OF_MEDICARE", percent_of_medicare=1.50,
            priority=1), pa))
    return payer, provider, pr


def _make_claim_with_line(payer, provider, pr, ref, claim_type):
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"], external_claim_ref=ref,
                             claim_type=claim_type,
                             patient_responsibility_cents=5000), pr))
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(), pr))
    return claim


def test_contracted_network_prices_off_billed_charges():
    """PRD §3.4: "Under `CONTRACTED_NETWORK`, the line's allowed amount is the
    gross multiplied by one minus the agreement's `discount_percent`, rounded
    half-up to whole cents."
    PRD §3.4: "the same claim priced under `CONTRACTED_NETWORK` and under
    `PERCENT_OF_MEDICARE` will generally produce different allowed amounts,
    because the former's baseline is billed charges and the latter's baseline is
    the Medicare schedule."

    Design: Difficulty/dual_variant_calc/contracted_network_vs_medicare_schedule_same_lines
    """
    payer, provider, pr = _setup_dual_variant_world()
    claim_a = _make_claim_with_line(payer, provider, pr, "A1", "ANCILLARY")
    det = validate_success(reprice(claim_a["id"], claim_a["version"] + 1,
                                   {"payer_rep": pr}), 200)
    claim_a = validate_success(api_client.get_claim(claim_a["id"], pr), 200)
    assert det["methodology"] == "CONTRACTED_NETWORK"
    assert claim_a["allowed_amount_cents"] == 36000
    assert claim_a["methodology_used"] == "CONTRACTED_NETWORK"


def test_medicare_schedule_variant_diverges_on_same_lines():
    """PRD §3.4: "Under `PERCENT_OF_MEDICARE`, a schedule base is first computed
    as the fee schedule entry's `base_rate_cents` multiplied by its
    `geographic_adjustment_factor` and by the line's `quantity_units`, rounded
    half-up; the line's allowed amount is then that base multiplied by the
    policy's `percent_of_medicare`, again rounded half-up."
    PRD §3.4: "the same claim priced under `CONTRACTED_NETWORK` and under
    `PERCENT_OF_MEDICARE` will generally produce different allowed amounts,
    because the former's baseline is billed charges and the latter's baseline is
    the Medicare schedule."

    Design: Difficulty/dual_variant_calc/contracted_network_vs_medicare_schedule_same_lines
    """
    payer, provider, pr = _setup_dual_variant_world()
    claim_a = _make_claim_with_line(payer, provider, pr, "A1", "ANCILLARY")
    claim_b = _make_claim_with_line(payer, provider, pr, "B1", "PROFESSIONAL")
    validate_success(reprice(claim_a["id"], claim_a["version"] + 1,
                             {"payer_rep": pr}), 200)
    det_b = validate_success(reprice(claim_b["id"], claim_b["version"] + 1,
                                     {"payer_rep": pr}), 200)
    claim_a = validate_success(api_client.get_claim(claim_a["id"], pr), 200)
    claim_b = validate_success(api_client.get_claim(claim_b["id"], pr), 200)
    assert det_b["methodology"] == "PERCENT_OF_MEDICARE"
    assert claim_b["allowed_amount_cents"] == 33000
    assert claim_b["methodology_used"] == "PERCENT_OF_MEDICARE"
    assert claim_a["allowed_amount_cents"] != claim_b["allowed_amount_cents"]


def _setup_provisional_price_world():
    """Claim C priced at 33000; negotiation accepted at 40000; payer has signed."""
    payer = get_success_data(api_client.create_payer_client(
        create_payer_client_payload(), OPS))
    provider = get_success_data(api_client.create_provider(
        create_provider_payload(npi="1000000002", legal_name="PR1", tin="T1"), NET))
    pa = make_payer_admin_headers(payer["id"])
    pr = make_payer_rep_headers(payer["id"])
    prov = make_provider_rep_headers(provider["id"])
    get_success_data(api_client.create_medicare_entry(
        create_medicare_entry_payload(), NET))
    get_success_data(api_client.create_repricing_policy(
        create_repricing_policy_payload(payer["id"]), pa))
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"], external_claim_ref="C1",
                             patient_responsibility_cents=5000), pr))
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(), pr))
    validate_success(reprice(claim["id"], claim["version"] + 1, {"payer_rep": pr}), 200)
    case = get_success_data(api_client.create_negotiation_case(
        create_negotiation_case_payload(claim["id"]), pr))
    get_success_data(api_client.offer_negotiation_case(
        case["id"], create_offer_payload(40000, case["version"]), pr))
    get_success_data(api_client.accept_negotiation_case(case["id"], prov))
    settlement = find_settlement_for_case(case["id"], {"payer_rep": pr})
    get_success_data(api_client.sign_settlement_agreement(settlement["id"], pr))
    return payer, provider, pr, prov, claim, case, settlement


def test_provisional_price_replaced_by_executed_settlement():
    """PRD §3.6: "first the claim transitions `PRICED` to `SETTLED`, its
    `allowed_amount_cents` is replaced by the agreement's `settled_amount_cents`
    with `payer_liability_cents` and `savings_cents` recomputed from the new
    allowed amount, and a new `RepricingDetermination` with `methodology`
    `NEGOTIATED` and `policy_id` null is created superseding the previously
    active determination"

    Design: Difficulty/dual_variant_calc/provisional_price_vs_executed_settlement_divergence
    """
    (payer, provider, pr, prov, claim, case, settlement) = (
        _setup_provisional_price_world())
    # Provisional policy price visible before execution.
    interim = validate_success(api_client.get_claim(claim["id"], pr), 200)
    assert interim["status"] == "PRICED"
    assert interim["allowed_amount_cents"] == 33000
    assert interim["savings_cents"] == 32000

    executed = validate_success(
        api_client.sign_settlement_agreement(settlement["id"], prov), 200)
    assert executed["status"] == "EXECUTED"

    settled = validate_success(api_client.get_claim(claim["id"], pr), 200)
    assert settled["status"] == "SETTLED"
    assert settled["allowed_amount_cents"] == 40000
    assert settled["payer_liability_cents"] == 35000
    assert settled["savings_cents"] == 25000


def test_executed_settlement_leaves_exactly_one_active_negotiated_determination():
    """PRD §2.9: "Each repricing event — an appeal resolved in the provider's
    favor, an executed settlement, an open-negotiation agreement, or an IDR
    decision — creates a new `ACTIVE` determination whose
    `supersedes_determination_id` points at the previously active determination,
    and the prior determination transitions to `SUPERSEDED`."
    PRD §2.9: "Determinations created through negotiation carry `methodology`
    `NEGOTIATED` with `policy_id` null"

    Design: Difficulty/dual_variant_calc/provisional_price_vs_executed_settlement_divergence
    """
    (payer, provider, pr, prov, claim, case, settlement) = (
        _setup_provisional_price_world())
    validate_success(api_client.sign_settlement_agreement(settlement["id"], prov), 200)

    dets, meta = validate_paginated(
        api_client.list_claim_determinations(claim["id"], pr))
    assert len(dets) == 2
    active = [d for d in dets if d["status"] == "ACTIVE"]
    superseded = [d for d in dets if d["status"] == "SUPERSEDED"]
    assert len(active) == 1 and len(superseded) == 1
    assert active[0]["methodology"] == "NEGOTIATED"
    assert active[0]["policy_id"] is None
    assert active[0]["supersedes_determination_id"] == superseded[0]["id"]
