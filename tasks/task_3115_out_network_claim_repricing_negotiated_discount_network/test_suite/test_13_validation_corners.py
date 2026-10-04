"""Corner queue: validations — repricing guard rails, negotiation bounds,
uniqueness, and the policy selector."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_claim, add_line, reprice, setup_priced_claim, open_case,
    place_offer, counter_case,
    create_claim_payload, create_provider_payload,
    make_payer_admin_headers, make_payer_rep_headers,
    TEST_USERS, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]
NET = TEST_USERS["network_admin_headers"]


def test_negotiation_required_policy_blocks_direct_reprice():
    """PRD §3.4: "Sixth, if the selected policy's methodology is
    `NEGOTIATION_REQUIRED`, direct repricing is forbidden and the request is
    rejected with `ERR_NEGOTIATION_REQUIRED` (HTTP 422)."
    PRD §3.4: "A failed reprice — one rejected with `ERR_NEGOTIATION_REQUIRED`,
    `ERR_NO_REPRICING_POLICY`, or `ERR_RATE_INPUT_MISSING` — is a pure
    rejection: the claim remains `PENDING_LINES` and no failure state is
    persisted."

    Design: Corner/validations/negotiation_required_policy_blocks_direct_reprice
    """
    payer = create_payer()
    provider = create_provider(npi="4000000001")
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx, methodology="NEGOTIATION_REQUIRED",
                  percent_of_medicare=None, priority=1)
    claim = create_claim(payer, provider, ctx, external_claim_ref="N1",
                         patient_responsibility_cents=0)
    add_line(claim["id"], ctx, quantity_units=1, unit_charge_cents=50000)

    res = reprice(claim["id"], claim["version"] + 1, ctx)
    validate_error(res, ApiErrorId.ERR_NEGOTIATION_REQUIRED)
    claim_after = validate_success(api_client.get_claim(claim["id"],
                                                        ctx["payer_rep"]), 200)
    assert claim_after["status"] == "PENDING_LINES"


def test_missing_medicare_rate_row_blocks_reprice():
    """PRD §3.4: "Seventh, the rate inputs the methodology needs must exist: a
    `MedicareFeeScheduleEntry` matching each priced line's `procedure_code` and
    `region_code` for `PERCENT_OF_MEDICARE`, a `UsualCustomaryRate` row for
    `REFERENCE_BASED` or `UCR`, and the covering `NetworkAgreement` for
    in-network claims — a missing row yields `ERR_RATE_INPUT_MISSING`
    (HTTP 422)."

    Design: Corner/validations/missing_medicare_rate_row_blocks_reprice
    """
    payer = create_payer()
    provider = create_provider(npi="4000000002")
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx)  # PERCENT_OF_MEDICARE policy, but no rate row
    claim = create_claim(payer, provider, ctx, external_claim_ref="N2",
                         patient_responsibility_cents=0)
    add_line(claim["id"], ctx, procedure_code="99999", quantity_units=1,
             unit_charge_cents=50000, region_code="R9")

    res = reprice(claim["id"], claim["version"] + 1, ctx)
    validate_error(res, ApiErrorId.ERR_RATE_INPUT_MISSING)
    claim_after = validate_success(api_client.get_claim(claim["id"],
                                                        ctx["payer_rep"]), 200)
    assert claim_after["status"] == "PENDING_LINES"


def test_counter_below_current_offer_rejected():
    """PRD §3.5: "The counter must be at least the `current_offer_cents` on the
    table — a lower counter is rejected with `ERR_COUNTER_BELOW_OFFER`
    (HTTP 422) — and must not exceed the claim's `billed_amount_cents`."

    Design: Corner/validations/counter_below_current_offer_rejected
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "N3",
                                              "patient_responsibility_cents": 0},
                             npi="4000000003")
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 30000, case["version"], env["ctx"]))

    res = counter_case(case["id"], 25000, env["ctx"])
    validate_error(res, ApiErrorId.ERR_COUNTER_BELOW_OFFER)
    case_after = validate_success(api_client.get_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]), 200)
    assert case_after["status"] == "OFFER_PENDING"
    assert case_after["round_count"] == 0


def test_offer_above_billed_rejected():
    """PRD §3.5: "The offer must be greater than zero and no more than the
    claim's `billed_amount_cents`, else the request is rejected with
    `ERR_OFFER_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/offer_above_billed_rejected
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "N4",
                                              "patient_responsibility_cents": 0},
                             npi="4000000004")
    case = open_case(env["claim"]["id"], env["ctx"])

    res = place_offer(case["id"], 60001, case["version"], env["ctx"])
    validate_error(res, ApiErrorId.ERR_OFFER_OUT_OF_RANGE)
    case_after = validate_success(api_client.get_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]), 200)
    assert case_after["status"] == "OPEN"


def test_duplicate_claim_ref_and_duplicate_npi_rejected():
    """PRD §3.3: "an `external_claim_ref` that is unique among that payer's
    claims (a duplicate surfaces `ERR_DUPLICATE_CLAIM_REF`, HTTP 409)"
    PRD §3.2: "`npi` (the National Provider Identifier, unique across the
    platform — registering a provider whose `npi` is already on file is rejected
    with `ERR_DUPLICATE_NPI`, HTTP 409)"

    Design: Corner/validations/duplicate_claim_ref_and_duplicate_npi_rejected
    """
    payer1 = create_payer(payer_name="P1")
    payer2 = create_payer(payer_name="P2", fee_percent=0.20,
                          fee_cap_cents_per_claim=4000)
    provider = create_provider(npi="4000000005")
    pr1 = make_payer_rep_headers(payer1["id"])
    pr2 = make_payer_rep_headers(payer2["id"])
    get_success_data(api_client.create_claim(
        create_claim_payload(payer1["id"], provider["id"],
                             external_claim_ref="DUP"), pr1))

    same_payer = api_client.create_claim(
        create_claim_payload(payer1["id"], provider["id"],
                             external_claim_ref="DUP", claim_type="FACILITY",
                             network_status="IN_NETWORK"), pr1)
    validate_error(same_payer, ApiErrorId.ERR_DUPLICATE_CLAIM_REF)

    other_payer = validate_success(api_client.create_claim(
        create_claim_payload(payer2["id"], provider["id"],
                             external_claim_ref="DUP"), pr2), 201)
    assert other_payer["payer_client_id"] == payer2["id"]

    dupe_npi = api_client.create_provider(
        create_provider_payload(npi="4000000005", legal_name="PR-dupe",
                                tin="T2"), NET)
    validate_error(dupe_npi, ApiErrorId.ERR_DUPLICATE_NPI)


def test_policy_selector_priority_and_created_at_tiebreak():
    """PRD §3.1: "A policy's `priority` is an integer selector rank — lower wins
    — and ties are broken by the policy's `created_at` ascending, so the
    earliest-created policy at the lowest priority value is the one selected."
    PRD §3.4: "candidates are filtered by the claim's `payer_client_id`,
    `claim_type`, and `network_status`, ranked by `priority` ascending with
    `created_at` ascending as tie-breaker"

    Design: Corner/validations/policy_selector_priority_and_created_at_tiebreak
    """
    payer = create_payer()
    provider = create_provider(npi="4000000006")
    create_medicare_entry()
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    # Priority ordering: priority 1 (x1.50) beats priority 5 (x2.00).
    create_policy(payer, ctx, percent_of_medicare=2.00, priority=5)
    create_policy(payer, ctx, percent_of_medicare=1.50, priority=1)
    # Tie-break: both priority 3 on FACILITY; older (x1.20) created before the
    # clock advances, newer (x1.80) after.
    create_policy(payer, ctx, claim_type="FACILITY", percent_of_medicare=1.20,
                  priority=3)
    get_success_data(api_client.set_clock("2026-09-02T00:00:00Z", OPS))
    create_policy(payer, ctx, claim_type="FACILITY", percent_of_medicare=1.80,
                  priority=3)

    claim1 = create_claim(payer, provider, ctx, external_claim_ref="SEL1")
    add_line(claim1["id"], ctx)
    get_success_data(reprice(claim1["id"], claim1["version"] + 1, ctx))
    claim1 = validate_success(api_client.get_claim(claim1["id"],
                                                   ctx["payer_rep"]), 200)
    assert claim1["allowed_amount_cents"] == 33000

    claim2 = create_claim(payer, provider, ctx, external_claim_ref="SEL2",
                          claim_type="FACILITY")
    add_line(claim2["id"], ctx)
    get_success_data(reprice(claim2["id"], claim2["version"] + 1, ctx))
    claim2 = validate_success(api_client.get_claim(claim2["id"],
                                                   ctx["payer_rep"]), 200)
    # older policy wins: round(22000 * 1.20) = 26400
    assert claim2["allowed_amount_cents"] == 26400
