"""Corner queue: optimistic concurrency, frozen determination snapshots, and
immediate read-after-write consistency."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_claim, add_line, reprice, setup_priced_claim, open_case,
    place_offer, counter_case,
    create_claim_line_payload,
    make_payer_admin_headers, make_payer_rep_headers,
    ApiErrorId,
)


def test_reprice_stale_claim_version_rejected():
    """PRD §2.7: "Repricing a claim — the request body must carry
    `expected_claim_version`, holding the caller's last observed `version` of
    the target `Claim`. If the claim's current `version` has advanced (for
    example because another writer added a claim line that legitimately changed
    the billed amount the repricing is based on), the reprice is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/reprice_stale_claim_version_rejected
    """
    payer = create_payer()
    provider = create_provider(npi="8000000001")
    create_medicare_entry()
    create_medicare_entry(procedure_code="99284")
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx)
    claim = create_claim(payer, provider, ctx, external_claim_ref="O1",
                         patient_responsibility_cents=0)
    add_line(claim["id"], ctx)
    seen = validate_success(api_client.get_claim(claim["id"], ctx["payer_rep"]), 200)
    # A second line advances the version beyond what the caller observed.
    add_line(claim["id"], ctx, procedure_code="99284", quantity_units=1,
             unit_charge_cents=10000)

    res = reprice(claim["id"], seen["version"], ctx)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    claim_after = validate_success(api_client.get_claim(claim["id"],
                                                        ctx["payer_rep"]), 200)
    assert claim_after["status"] == "PENDING_LINES"
    assert claim_after["billed_amount_cents"] == 70000


def test_negotiation_offer_stale_case_version_rejected():
    """PRD §2.7: "Placing an offer on a negotiation case — the request body must
    carry `expected_case_version`, holding the caller's last observed `version`
    of the target `NegotiationCase`. If the case's `version` has advanced (for
    example because the provider countered and changed the offer currently on
    the table), the offer is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/negotiation_offer_stale_case_version_rejected
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "O2",
                                              "patient_responsibility_cents": 0},
                             npi="8000000002")
    case = open_case(env["claim"]["id"], env["ctx"])
    offered = get_success_data(place_offer(case["id"], 30000, case["version"],
                                           env["ctx"]))
    # Provider counter advances the case version.
    get_success_data(counter_case(case["id"], 50000, env["ctx"]))

    res = place_offer(case["id"], 40000, offered["version"], env["ctx"])
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    case_after = validate_success(api_client.get_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]), 200)
    assert case_after["status"] == "COUNTERED"
    assert case_after["current_offer_cents"] == 50000


def test_determination_input_snapshot_is_frozen_at_pricing():
    """PRD §2.8: "The `RepricingDetermination` created at pricing time carries
    an `input_snapshot` (a frozen JSON object naming every rate input used — fee
    schedule row ids, UCR row ids, agreement discount, policy parameters) and a
    `computation_trace` (an ordered list of computation steps with intermediate
    values). Both are written exactly once at determination creation and are
    immutable thereafter."

    Design: Corner/cross_cutting_complexity_layers/determination_input_snapshot_is_frozen_at_pricing
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "O3",
                                              "patient_responsibility_cents": 0},
                             npi="8000000003")
    ctx = env["ctx"]
    det_id = env["determination"]["id"]
    # A later, conflicting rate row must not retro-actively alter the price.
    create_medicare_entry(base_rate_cents=99999, geographic_adjustment_factor=1.00)

    claim = validate_success(api_client.get_claim(env["claim"]["id"],
                                                  ctx["payer_rep"]), 200)
    assert claim["allowed_amount_cents"] == 33000

    det = validate_success(api_client.get_determination(det_id, ctx["payer_rep"]), 200)
    assert det["status"] == "ACTIVE"
    assert det["computation_trace"], "computation_trace must be non-empty"
    snapshot = det["input_snapshot"]
    assert isinstance(snapshot, dict) and snapshot, (
        "input_snapshot must name the rate inputs used")
    assert "99999" not in str(snapshot), (
        "snapshot must reference the 10000-rate row read at pricing time")


def test_pricing_effects_visible_in_same_request_response():
    """PRD §3.4: "A successful reprice creates a `RepricingDetermination` in
    `ACTIVE` status recording the `claim_id`, the applied `methodology`, the
    driving `policy_id` (null for negotiated determinations), the `agreement_id`
    when the methodology is `CONTRACTED_NETWORK` (null otherwise), the frozen
    `input_snapshot`, the `computation_trace`, and any `defensibility_notes`."
    PRD §3.4: "The claim's `allowed_amount_cents` is the sum of the line allowed
    amounts; `payer_liability_cents` is the allowed amount minus
    `patient_responsibility_cents`; `savings_cents` is `billed_amount_cents`
    minus `allowed_amount_cents` plus `patient_responsibility_cents`; and
    `methodology_used` records the selected methodology. The claim transitions
    to `PRICED` and its `version` increments."

    Design: Corner/consistency_model/pricing_effects_visible_in_same_request_response
    """
    payer = create_payer()
    provider = create_provider(npi="8000000004")
    create_medicare_entry()
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx)
    claim = create_claim(payer, provider, ctx, external_claim_ref="O4",
                         patient_responsibility_cents=5000)
    add_line(claim["id"], ctx)

    det = validate_success(reprice(claim["id"], claim["version"] + 1, ctx), 200)
    assert det["status"] == "ACTIVE"
    assert det["methodology"] == "PERCENT_OF_MEDICARE"
    assert det["claim_id"] == claim["id"]

    after = validate_success(api_client.get_claim(claim["id"], ctx["payer_rep"]), 200)
    assert after["status"] == "PRICED"
    assert after["allowed_amount_cents"] == 33000
    assert after["payer_liability_cents"] == 28000
    assert after["savings_cents"] == 32000
