"""Difficulty queue: boundary precision — IDR submission at the exact expiry
instant and the round-5 negotiation expiry."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_priced_claim, open_case, place_offer, counter_case,
    create_agreement, create_policy, create_claim, add_line, reprice,
    create_network_agreement_payload,
    TEST_USERS, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]


def _setup_nsa_negotiation_expiring_at(expiry="2026-10-22T10:00:00.000Z"):
    """
    NSA claim priced at 33000; OpenNegotiation initiated 2026-09-10T10:00:00Z
    (Thursday) so expires_at lands on the given instant (30 business days);
    one contracted agreement makes the QPA computable at submission.
    """
    get_success_data(api_client.set_clock("2026-09-10T10:00:00Z", OPS))
    env = setup_priced_claim(
        claim_overrides={"external_claim_ref": "M1", "nsa_flag": True,
                         "service_date": "2026-09-01T00:00:00Z",
                         "patient_responsibility_cents": 0},
        npi="1000000011")
    on = get_success_data(api_client.create_open_negotiation(
        {"claim_id": env["claim"]["id"], "initiated_by": "PROVIDER"},
        env["ctx"]["provider_rep"]))
    assert on["expires_at"].startswith(expiry), (
        f"fixture misconfigured: expires_at {on['expires_at']} != {expiry}")
    create_agreement(env["provider"], network_name="NQ", discount_percent=0.50)
    # PRD §3.7: QPA candidates are agreements whose determination snapshots
    # priced the claim's primary procedure_code under CONTRACTED_NETWORK in the
    # claim's region. Price a separate ANCILLARY claim under a
    # CONTRACTED_NETWORK policy so a qualifying snapshot (unit charge 30000,
    # discount 0.50 -> rate 15000) exists before submission.
    create_policy(env["payer"], env["ctx"], claim_type="ANCILLARY",
                  methodology="CONTRACTED_NETWORK", percent_of_medicare=None,
                  priority=1)
    qpa_claim = create_claim(env["payer"], env["provider"], env["ctx"],
                             external_claim_ref="M1-QPA", claim_type="ANCILLARY",
                             service_date="2026-09-01T00:00:00Z",
                             patient_responsibility_cents=0)
    add_line(qpa_claim["id"], env["ctx"], quantity_units=1,
             unit_charge_cents=30000)
    get_success_data(reprice(qpa_claim["id"], qpa_claim["version"] + 1,
                             env["ctx"]))
    env["on"] = on
    return env


def _idr_payload(env):
    return {"claim_id": env["claim"]["id"],
            "open_negotiation_id": env["on"]["id"],
            "payer_offer_cents": 30000, "provider_offer_cents": 50000}


def test_idr_submission_one_second_before_expiry_rejected():
    """PRD §3.7: "Submission to independent dispute resolution is forbidden
    strictly before `expires_at`. An IDR submission attempted while the open
    negotiation is still within its window is rejected with
    `ERR_OPEN_NEGOTIATION_ACTIVE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/idr_submission_at_exact_expiry_instant_is_allowed
    """
    env = _setup_nsa_negotiation_expiring_at()
    get_success_data(api_client.set_clock("2026-10-22T09:59:59Z", OPS))
    res = api_client.create_idr_submission(_idr_payload(env), env["ctx"]["payer_rep"])
    validate_error(res, ApiErrorId.ERR_OPEN_NEGOTIATION_ACTIVE)
    on = validate_success(api_client.get_open_negotiation(
        env["on"]["id"], env["ctx"]["payer_rep"]), 200)
    assert on["status"] == "ACTIVE"


def test_idr_submission_at_exact_expiry_succeeds_with_qpa():
    """PRD §3.7: "Submission to independent dispute resolution is forbidden
    strictly before `expires_at`."
    PRD §3.7: "Once the negotiation is `EXPIRED` and the logical clock has
    reached `expires_at`, either side may submit the dispute, supplying
    `claim_id`, the completed `open_negotiation_id`, a `payer_offer_cents`, and
    a `provider_offer_cents`. The submission is born `SUBMITTED`, the referenced
    `OpenNegotiation` transitions from `EXPIRED` to `SUPERSEDED_BY_IDR`, and the
    qualifying payment amount is computed at submission time."
    PRD §3.7: "each candidate contributes a per-unit contracted rate — the
    agreement's discount applied to the snapshotted gross unit charge recorded
    in its `input_snapshot`."

    Design: Difficulty/boundary_precision_check/idr_submission_at_exact_expiry_instant_is_allowed
    """
    env = _setup_nsa_negotiation_expiring_at()
    get_success_data(api_client.set_clock("2026-10-22T09:59:59Z", OPS))
    res = api_client.create_idr_submission(_idr_payload(env), env["ctx"]["payer_rep"])
    validate_error(res, ApiErrorId.ERR_OPEN_NEGOTIATION_ACTIVE)

    get_success_data(api_client.set_clock("2026-10-22T10:00:00Z", OPS))
    idr = validate_success(
        api_client.create_idr_submission(_idr_payload(env), env["ctx"]["payer_rep"]),
        201)
    assert idr["status"] == "SUBMITTED"
    # single candidate: unit 30000 x (1 - 0.50) = 15000
    assert idr["qpa_cents"] == 15000
    on = validate_success(api_client.get_open_negotiation(
        env["on"]["id"], env["ctx"]["payer_rep"]), 200)
    assert on["status"] == "SUPERSEDED_BY_IDR"


def _run_counters(env, case_id, counters_and_offers):
    """Alternate provider counters and payer offers; returns last case dict."""
    ctx = env["ctx"]
    case = get_success_data(api_client.get_negotiation_case(
        case_id, ctx["payer_rep"]))
    for counter, offer in counters_and_offers:
        case = get_success_data(counter_case(case_id, counter, ctx))
        if offer is not None:
            case = get_success_data(place_offer(case_id, offer, case["version"], ctx))
    return case


def test_four_counters_leave_case_countered_at_round_four():
    """PRD §3.5: "A valid counter moves the case from `OFFER_PENDING` to
    `COUNTERED`, sets `current_offer_cents` to the counter, and increments
    `round_count`. The negotiation has a hard round cap: when `round_count`
    reaches 5, the case immediately auto-transitions from `COUNTERED` to
    `EXPIRED`, bumping its `version`."

    Design: Difficulty/boundary_precision_check/fifth_counter_expires_case_at_round_count_five
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "N1",
                                              "patient_responsibility_cents": 0},
                             npi="1000000012")
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 30000, case["version"], env["ctx"]))
    case = _run_counters(env, case["id"], [
        (50000, 40000), (49000, 41000), (48000, 42000), (47000, None),
    ])
    assert case["status"] == "COUNTERED"
    assert case["round_count"] == 4


def test_fifth_counter_expires_case_and_sixth_is_rejected():
    """PRD §3.5: "The negotiation has a hard round cap: when `round_count`
    reaches 5, the case immediately auto-transitions from `COUNTERED` to
    `EXPIRED`, bumping its `version`."
    PRD §5: "`ERR_INVALID_STATE` | 409"

    Design: Difficulty/boundary_precision_check/fifth_counter_expires_case_at_round_count_five
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "N2",
                                              "patient_responsibility_cents": 0},
                             npi="1000000013")
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 30000, case["version"], env["ctx"]))
    case = _run_counters(env, case["id"], [
        (50000, 40000), (49000, 41000), (48000, 42000), (47000, 43000),
    ])
    fifth = validate_success(counter_case(case["id"], 46000, env["ctx"]), 200)
    assert fifth["round_count"] == 5
    assert fifth["status"] == "EXPIRED"

    sixth = api_client.counter_negotiation_case(
        case["id"], {"counter_cents": 45000}, env["ctx"]["provider_rep"])
    validate_error(sixth, ApiErrorId.ERR_INVALID_STATE)
