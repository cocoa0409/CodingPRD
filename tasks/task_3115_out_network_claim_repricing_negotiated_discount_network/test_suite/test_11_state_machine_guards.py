"""Corner queue: state machines — reprice guards, terminal lockdown, appeal
window deadline."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_payer, create_provider, create_medicare_entry, create_policy,
    create_claim, add_line, reprice, setup_priced_claim, open_case,
    make_payer_admin_headers, make_payer_rep_headers, make_provider_rep_headers,
    TEST_USERS, ApiErrorId,
)
from prd_bench_local_runner.testing import validate_error_is_one_of

OPS = TEST_USERS["ops_admin_headers"]


def test_reprice_from_received_without_lines_returns_claim_has_no_lines():
    """PRD §3.4: "First, the claim must have at least one non-`VOID` line, else
    `ERR_CLAIM_HAS_NO_LINES` (HTTP 422)."
    PRD §3.3: "A newly ingested claim is in `RECEIVED` status with
    `billed_amount_cents` equal to 0"

    Design: Corner/state_machines/reprice_from_received_without_lines_returns_claim_has_no_lines
    """
    payer = create_payer()
    provider = create_provider(npi="2000000006")
    create_medicare_entry()
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    create_policy(payer, ctx)
    claim = create_claim(payer, provider, ctx, external_claim_ref="C3")

    res = reprice(claim["id"], claim["version"], ctx)
    # PRD §3.4 names ERR_CLAIM_HAS_NO_LINES first in the reprice sequence, but
    # §2.10 orders generic state validity (ERR_INVALID_STATE) ahead of the
    # policy-selection group; a RECEIVED claim may trip either gate.
    validate_error_is_one_of(res, ["ERR_CLAIM_HAS_NO_LINES", "ERR_INVALID_STATE"])
    claim_after = validate_success(api_client.get_claim(claim["id"],
                                                        ctx["payer_rep"]), 200)
    assert claim_after["status"] == "RECEIVED"


def test_reprice_from_finalized_returns_invalid_state():
    """PRD §3.4: "When a `PayerRep` asks to reprice a claim in `PENDING_LINES`"
    PRD §2.10: "generic state-transition validity (`ERR_INVALID_STATE`)"
    PRD §5: "`ERR_INVALID_STATE` | 409"

    Design: Corner/state_machines/reprice_from_finalized_returns_invalid_state
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "C4"},
                             npi="2000000007")
    ctx = env["ctx"]
    get_success_data(api_client.finalize_claim(env["claim"]["id"],
                                               ctx["payer_rep"]))
    finalized = validate_success(api_client.get_claim(env["claim"]["id"],
                                                      ctx["payer_rep"]), 200)
    res = reprice(env["claim"]["id"], finalized["version"], ctx)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_claim(env["claim"]["id"],
                                                  ctx["payer_rep"]), 200)
    assert after["status"] == "FINALIZED"


def test_terminal_negotiation_case_lockdown():
    """PRD §3.5: "Either side may walk away while the case is in `OPEN`,
    `OFFER_PENDING`, or `COUNTERED`: withdrawal moves the case to `WITHDRAWN`."
    PRD §2.10: "generic state-transition validity (`ERR_INVALID_STATE`)"
    PRD §5: "`ERR_INVALID_STATE` | 409"

    Design: Corner/state_machines/terminal_negotiation_case_lockdown
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "C5"},
                             npi="2000000008")
    ctx = env["ctx"]
    case = open_case(env["claim"]["id"], ctx)
    withdrawn = validate_success(api_client.withdraw_negotiation_case(
        case["id"], ctx["payer_rep"]), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    offer = api_client.offer_negotiation_case(
        case["id"], {"offer_cents": 30000,
                     "expected_case_version": withdrawn["version"]},
        ctx["payer_rep"])
    validate_error(offer, ApiErrorId.ERR_INVALID_STATE)
    again = api_client.withdraw_negotiation_case(case["id"], ctx["payer_rep"])
    validate_error(again, ApiErrorId.ERR_INVALID_STATE)

    case_after = validate_success(api_client.get_negotiation_case(
        case["id"], ctx["payer_rep"]), 200)
    assert case_after["status"] == "WITHDRAWN"


def test_appeal_window_deadline_enforced():
    """PRD §3.8: "The appeal window is hard: `appeal_window_deadline` is the
    determination's creation timestamp plus 45 calendar days, and an appeal
    submitted after that instant is rejected with `ERR_APPEAL_WINDOW_CLOSED`
    (HTTP 409)."

    Design: Corner/state_machines/appeal_window_deadline_enforced
    """
    get_success_data(api_client.set_clock("2026-09-10T10:00:00Z", OPS))
    payer = create_payer()
    provider = create_provider(npi="2000000009")
    create_medicare_entry()
    ctx = {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
    }
    ctx["provider_rep"] = make_provider_rep_headers(provider["id"])
    create_policy(payer, ctx)

    def _priced(ref):
        claim = create_claim(payer, provider, ctx, external_claim_ref=ref,
                             service_date="2026-09-01T00:00:00Z",
                             patient_responsibility_cents=0)
        add_line(claim["id"], ctx)
        det = get_success_data(reprice(claim["id"], claim["version"] + 1, ctx))
        return claim, det

    claim1, det1 = _priced("W1")
    claim2, det2 = _priced("W2")

    # Deadline = determination creation (2026-09-10T10:00:00Z) + 45 days
    # = 2026-10-25T10:00:00Z. Appeal at exactly the deadline succeeds.
    get_success_data(api_client.set_clock("2026-10-25T10:00:00Z", OPS))
    appeal1 = validate_success(api_client.create_appeal(
        claim1["id"], {"determination_id": det1["id"],
                       "appeal_reason": "at deadline"},
        ctx["provider_rep"]), 201)
    assert appeal1["status"] == "SUBMITTED"

    # One second past the deadline is rejected.
    get_success_data(api_client.set_clock("2026-10-25T10:00:01Z", OPS))
    late = api_client.create_appeal(
        claim2["id"], {"determination_id": det2["id"],
                       "appeal_reason": "one second late"},
        ctx["provider_rep"])
    validate_error(late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
