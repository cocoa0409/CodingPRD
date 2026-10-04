"""Difficulty queue: cross-entity state dependency — finalize blocked by an
open appeal; in-network pricing gated on the agreement's state."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_payer, create_provider, create_agreement,
    create_claim, add_line, reprice, setup_priced_claim,
    create_claim_payload, create_claim_line_payload,
    make_payer_rep_headers,
    ApiErrorId, TEST_USERS,
)

TEST_USERS_NET = TEST_USERS["network_admin_headers"]


def _setup_priced_claim_with_appeal_under_review():
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "O1",
                                              "patient_responsibility_cents": 0},
                             npi="1000000014")
    appeal = get_success_data(api_client.create_appeal(
        env["claim"]["id"],
        {"determination_id": env["determination"]["id"],
         "appeal_reason": "rate dispute"},
        env["ctx"]["provider_rep"]))
    get_success_data(api_client.start_review_appeal(appeal["id"],
                                                    env["ctx"]["payer_rep"]))
    env["appeal"] = appeal
    return env


def test_finalize_rejected_while_appeal_under_review():
    """PRD §3.9: "A claim in `PRICED` or `SETTLED` may be finalized by a
    `PayerRep`, provided no appeal for the claim is still `SUBMITTED` or
    `UNDER_REVIEW`."
    PRD §3.8: "While any appeal for a claim is in `SUBMITTED` or `UNDER_REVIEW`,
    finalizing that claim is rejected with `ERR_APPEAL_IN_PROGRESS` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_while_appeal_under_review
    """
    env = _setup_priced_claim_with_appeal_under_review()
    res = api_client.finalize_claim(env["claim"]["id"], env["ctx"]["payer_rep"])
    validate_error(res, ApiErrorId.ERR_APPEAL_IN_PROGRESS)
    claim = validate_success(api_client.get_claim(env["claim"]["id"],
                                                  env["ctx"]["payer_rep"]), 200)
    assert claim["status"] == "PRICED"


def test_finalize_succeeds_after_appeal_resolved_upheld():
    """PRD §3.9: "A claim in `PRICED` or `SETTLED` may be finalized by a
    `PayerRep`, provided no appeal for the claim is still `SUBMITTED` or
    `UNDER_REVIEW`. Finalization moves the claim to `FINALIZED` and makes it
    invoiceable."
    PRD §3.8: "An `outcome` of upheld moves the appeal to `RE_REVIEWED_UPHELD`;
    an `outcome` of denied moves it to `DENIED`; both leave the claim's amounts
    untouched."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_while_appeal_under_review
    """
    env = _setup_priced_claim_with_appeal_under_review()
    res = api_client.finalize_claim(env["claim"]["id"], env["ctx"]["payer_rep"])
    validate_error(res, ApiErrorId.ERR_APPEAL_IN_PROGRESS)

    resolved = validate_success(api_client.resolve_appeal(
        env["appeal"]["id"], {"outcome": "UPHELD"}, env["ctx"]["payer_rep"]), 200)
    assert resolved["status"] == "RE_REVIEWED_UPHELD"

    finalized = validate_success(api_client.finalize_claim(
        env["claim"]["id"], env["ctx"]["payer_rep"]), 200)
    assert finalized["status"] == "FINALIZED"
    assert finalized["allowed_amount_cents"] == 33000


def test_in_network_reprice_succeeds_while_agreement_active():
    """PRD §3.4: "when the claim's `network_status` is `IN_NETWORK`, an `ACTIVE`
    `NetworkAgreement` covering the claim's `provider_id` and `service_date`
    must exist — absence yields `ERR_NO_CONTRACTED_AGREEMENT` (HTTP 422), and
    in-network claims price directly off that agreement rather than off a
    policy."
    PRD §3.4: "Under `CONTRACTED_NETWORK`, the line's allowed amount is the
    gross multiplied by one minus the agreement's `discount_percent`, rounded
    half-up to whole cents."

    Design: Difficulty/cross_entity_state_dependency/in_network_pricing_depends_on_agreement_effective_state
    """
    payer = create_payer()
    provider = create_provider(npi="1000000015")
    pr = make_payer_rep_headers(payer["id"])
    agreement = create_agreement(provider, discount_percent=0.40)
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"],
                             external_claim_ref="P1", claim_type="FACILITY",
                             network_status="IN_NETWORK",
                             patient_responsibility_cents=0), pr))
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(), pr))
    det = validate_success(api_client.reprice_claim(
        claim["id"], {"expected_claim_version": claim["version"] + 1}, pr), 200)
    assert det["methodology"] == "CONTRACTED_NETWORK"
    assert det["agreement_id"] == agreement["id"]
    claim = validate_success(api_client.get_claim(claim["id"], pr), 200)
    assert claim["status"] == "PRICED"
    assert claim["allowed_amount_cents"] == 36000


def test_in_network_reprice_rejected_while_agreement_suspended():
    """PRD §3.4: "when the claim's `network_status` is `IN_NETWORK`, an `ACTIVE`
    `NetworkAgreement` covering the claim's `provider_id` and `service_date`
    must exist — absence yields `ERR_NO_CONTRACTED_AGREEMENT` (HTTP 422)"
    PRD §3.2: "Agreements are born `ACTIVE`, may be suspended to `SUSPENDED`,
    reinstated from `SUSPENDED` back to `ACTIVE`, and terminated from either
    `ACTIVE` or `SUSPENDED` to `TERMINATED`; each transition bumps the
    agreement's `version`."

    Design: Difficulty/cross_entity_state_dependency/in_network_pricing_depends_on_agreement_effective_state
    """
    payer = create_payer()
    provider = create_provider(npi="1000000016")
    pr = make_payer_rep_headers(payer["id"])
    agreement = create_agreement(provider, discount_percent=0.40)
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"],
                             external_claim_ref="Q1", claim_type="FACILITY",
                             network_status="IN_NETWORK",
                             patient_responsibility_cents=0), pr))
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(), pr))
    get_success_data(api_client.suspend_network_agreement(
        agreement["id"], TEST_USERS_NET))
    res = api_client.reprice_claim(
        claim["id"], {"expected_claim_version": claim["version"] + 1}, pr)
    validate_error(res, ApiErrorId.ERR_NO_CONTRACTED_AGREEMENT)
    claim = validate_success(api_client.get_claim(claim["id"], pr), 200)
    assert claim["status"] == "PENDING_LINES"
