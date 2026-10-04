"""Corner queue: endpoints — line-add recomputation, determination chain reads,
and suspended-payer claim ingest."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_claim, add_line, reprice, setup_priced_claim,
    create_claim_payload, create_claim_line_payload,
    make_payer_rep_headers, make_provider_rep_headers,
    TEST_USERS, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]


def test_lines_endpoint_recomputes_billed_and_flips_status():
    """PRD §3.3: "The first line added moves the claim from `RECEIVED` to
    `PENDING_LINES`; subsequent lines keep it in `PENDING_LINES`. Every line
    addition recomputes the claim's `billed_amount_cents` as the sum over all
    non-`VOID` lines of each line's `unit_charge_cents` multiplied by its
    `quantity_units`, and bumps the claim's `version`."

    Design: Corner/endpoints/lines_endpoint_recomputes_billed_and_flips_status
    """
    payer = create_payer()
    provider = create_provider(npi="5000000001")
    pr = make_payer_rep_headers(payer["id"])
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"],
                             external_claim_ref="E1"), pr))
    assert claim["version"] == 1
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(), pr))
    get_success_data(api_client.add_claim_line(
        claim["id"], create_claim_line_payload(
            procedure_code="99284", quantity_units=1, unit_charge_cents=10000), pr))

    claim = validate_success(api_client.get_claim(claim["id"], pr), 200)
    assert claim["billed_amount_cents"] == 70000
    assert claim["status"] == "PENDING_LINES"
    assert claim["version"] == 3


def test_determinations_subresource_returns_chain_in_order():
    """PRD §3.4: "A claim's full determination chain can be listed under the
    claim"
    PRD §2.9: "Each repricing event — an appeal resolved in the provider's
    favor, an executed settlement, an open-negotiation agreement, or an IDR
    decision — creates a new `ACTIVE` determination whose
    `supersedes_determination_id` points at the previously active determination,
    and the prior determination transitions to `SUPERSEDED`."
    PRD §3.8: "a new `RepricingDetermination` is created with the methodology
    copied from the appealed determination, superseding the previously active
    one"

    Design: Corner/endpoints/determinations_subresource_returns_chain_in_order
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "E2"},
                             npi="5000000002")
    ctx = env["ctx"]
    appeal = get_success_data(api_client.create_appeal(
        env["claim"]["id"],
        {"determination_id": env["determination"]["id"],
         "appeal_reason": "dispute"},
        ctx["provider_rep"]))
    get_success_data(api_client.start_review_appeal(appeal["id"], ctx["payer_rep"]))
    get_success_data(api_client.resolve_appeal(
        appeal["id"], {"outcome": "ADJUSTED", "adjusted_amount_cents": 44000},
        ctx["payer_rep"]))

    dets, _ = validate_paginated(api_client.list_claim_determinations(
        env["claim"]["id"], ctx["payer_rep"]))
    assert len(dets) == 2
    original = [d for d in dets if d["id"] == env["determination"]["id"]][0]
    assert original["status"] == "SUPERSEDED"
    active = [d for d in dets if d["status"] == "ACTIVE"][0]
    assert active["supersedes_determination_id"] == env["determination"]["id"]
    assert active["methodology"] == "PERCENT_OF_MEDICARE"


def test_claim_create_on_suspended_payer_rejected():
    """PRD §3.1: "While a payer is `SUSPENDED`, claim ingest, claim-line
    addition, and repricing for that payer are all rejected with
    `ERR_PAYER_SUSPENDED` (HTTP 409)."

    Design: Corner/endpoints/claim_create_on_suspended_payer_rejected
    """
    payer = create_payer()
    provider = create_provider(npi="5000000003")
    pr = make_payer_rep_headers(payer["id"])
    get_success_data(api_client.suspend_payer_client(payer["id"], OPS))

    res = api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"],
                             external_claim_ref="E3"), pr)
    validate_error(res, ApiErrorId.ERR_PAYER_SUSPENDED)

    data, meta = validate_paginated(api_client.list_claims(
        pr, params={"payer_client_id": payer["id"]}))
    assert meta["total_count"] == 0
