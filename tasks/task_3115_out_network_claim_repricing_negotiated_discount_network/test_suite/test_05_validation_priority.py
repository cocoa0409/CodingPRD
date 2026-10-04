"""Difficulty queue: priority pair validation conflicts."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_claim, add_line, reprice,
    setup_priced_claim,
    make_payer_admin_headers, make_payer_rep_headers, make_provider_rep_headers,
    TEST_USERS, ApiErrorId,
)

OPS = TEST_USERS["ops_admin_headers"]


def test_suspended_payer_reprice_returns_payer_suspended_not_nsa_conflict():
    """PRD §2.10: "Only after those pass do business rules fire: suspended-payer
    checks (`ERR_PAYER_SUSPENDED`), generic state-transition validity
    (`ERR_INVALID_STATE`), NSA methodology conflict
    (`ERR_NSA_METHODOLOGY_CONFLICT`)"
    PRD §3.1: "While a payer is `SUSPENDED`, claim ingest, claim-line addition,
    and repricing for that payer are all rejected with `ERR_PAYER_SUSPENDED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_payer_state_error_beats_nsa_safety_error
    """
    payer = create_payer()
    provider = create_provider(npi="1000000009")
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx, claim_type="PROFESSIONAL",
                  network_status="OUT_OF_NETWORK",
                  methodology="NEGOTIATION_REQUIRED", percent_of_medicare=None,
                  priority=1)
    claim = create_claim(payer, provider, ctx, external_claim_ref="K1",
                         nsa_flag=True, patient_responsibility_cents=0)
    add_line(claim["id"], ctx, quantity_units=1, unit_charge_cents=50000)
    get_success_data(api_client.suspend_payer_client(payer["id"], OPS))

    res = reprice(claim["id"], claim["version"] + 1, ctx)
    assert res.status_code == 409
    err = validate_error(res, ApiErrorId.ERR_PAYER_SUSPENDED)
    assert err["error_id"] == "ERR_PAYER_SUSPENDED"


def test_suspended_payer_reprice_leaves_claim_pending():
    """PRD §3.4: "A failed reprice — one rejected with `ERR_NEGOTIATION_REQUIRED`,
    `ERR_NO_REPRICING_POLICY`, or `ERR_RATE_INPUT_MISSING` — is a pure
    rejection: the claim remains `PENDING_LINES` and no failure state is
    persisted."
    PRD §3.1: "While a payer is `SUSPENDED`, claim ingest, claim-line addition,
    and repricing for that payer are all rejected with `ERR_PAYER_SUSPENDED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_payer_state_error_beats_nsa_safety_error
    """
    payer = create_payer()
    provider = create_provider(npi="1000000019")
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx, claim_type="PROFESSIONAL",
                  network_status="OUT_OF_NETWORK",
                  methodology="NEGOTIATION_REQUIRED", percent_of_medicare=None,
                  priority=1)
    claim = create_claim(payer, provider, ctx, external_claim_ref="K2",
                         nsa_flag=True, patient_responsibility_cents=0)
    add_line(claim["id"], ctx, quantity_units=1, unit_charge_cents=50000)
    get_success_data(api_client.suspend_payer_client(payer["id"], OPS))

    reprice(claim["id"], claim["version"] + 1, ctx)
    claim_after = validate_success(api_client.get_claim(claim["id"],
                                                        ctx["payer_rep"]), 200)
    assert claim_after["status"] == "PENDING_LINES"


def _setup_nsa_open_negotiation_active():
    """Priced NSA claim + ACTIVE OpenNegotiation; clock before expiry."""
    get_success_data(api_client.set_clock("2026-09-10T10:00:00Z", OPS))
    env = setup_priced_claim(
        claim_overrides={"external_claim_ref": "L1", "nsa_flag": True,
                         "service_date": "2026-09-01T00:00:00Z",
                         "patient_responsibility_cents": 0},
        npi="1000000010")
    on = get_success_data(api_client.create_open_negotiation(
        {"claim_id": env["claim"]["id"], "initiated_by": "PAYER"},
        env["ctx"]["payer_rep"]))
    get_success_data(api_client.set_clock("2026-09-15T10:00:00Z", OPS))
    env["on"] = on
    return env


def test_idr_submission_while_negotiation_active_rejected():
    """PRD §3.7: "Submission to independent dispute resolution is forbidden
    strictly before `expires_at`. An IDR submission attempted while the open
    negotiation is still within its window is rejected with
    `ERR_OPEN_NEGOTIATION_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_error_beats_idr_amount_constraint
    """
    env = _setup_nsa_open_negotiation_active()
    res = api_client.create_idr_submission(
        {"claim_id": env["claim"]["id"],
         "open_negotiation_id": env["on"]["id"],
         "payer_offer_cents": 30000, "provider_offer_cents": 50000},
        env["ctx"]["provider_rep"])
    assert res.status_code == 409
    err = validate_error(res, ApiErrorId.ERR_OPEN_NEGOTIATION_ACTIVE)
    assert err["error_id"] == "ERR_OPEN_NEGOTIATION_ACTIVE"


def test_rejected_idr_submission_leaves_negotiation_active():
    """PRD §3.7: "An IDR submission attempted while the open negotiation is still
    within its window is rejected with `ERR_OPEN_NEGOTIATION_ACTIVE`
    (HTTP 409)."
    PRD §3.7: "Once the negotiation is `EXPIRED` and the logical clock has
    reached `expires_at`, either side may submit the dispute"

    Design: Difficulty/priority_pair_validation_conflict/temporal_window_error_beats_idr_amount_constraint
    """
    env = _setup_nsa_open_negotiation_active()
    api_client.create_idr_submission(
        {"claim_id": env["claim"]["id"],
         "open_negotiation_id": env["on"]["id"],
         "payer_offer_cents": 30000, "provider_offer_cents": 50000},
        env["ctx"]["provider_rep"])
    on_after = validate_success(api_client.get_open_negotiation(
        env["on"]["id"], env["ctx"]["payer_rep"]), 200)
    assert on_after["status"] == "ACTIVE"
