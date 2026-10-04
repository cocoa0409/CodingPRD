"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds state from scratch against an empty database using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient) so a
failed precondition surfaces as a clear "Setup failed" error rather than a
confusing assertion failure mid-test.

Identity threading: PayerAdmin / PayerRep calls bind X-User-ID to the payer's
id; ProviderRep calls bind X-User-ID to the provider's id. Opaque roles use the
shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_payer_client_payload,
    create_repricing_policy_payload,
    create_provider_payload,
    create_network_agreement_payload,
    create_medicare_entry_payload,
    create_ucr_rate_payload,
    create_claim_payload,
    create_claim_line_payload,
    create_negotiation_case_payload,
    create_offer_payload,
    create_counter_payload,
    create_open_negotiation_payload,
    create_idr_submission_payload,
    create_appeal_payload,
    create_feed_batch_payload,
    create_fee_invoice_payload,
)
from .test_users import (
    TEST_USERS,
    make_payer_admin_headers,
    make_payer_rep_headers,
    make_provider_rep_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
NET = TEST_USERS["network_admin_headers"]
FEED = TEST_USERS["feed_operator_headers"]
IDR = TEST_USERS["idr_entity_headers"]


def _ctx(payer, provider):
    """Per-instance ownership-bound headers for a (payer, provider) pair."""
    return {
        "payer_admin": make_payer_admin_headers(payer["id"]),
        "payer_rep": make_payer_rep_headers(payer["id"]),
        "provider_rep": make_provider_rep_headers(provider["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 1/2: base entity creation
# ---------------------------------------------------------------------------

def create_payer(**overrides):
    """Create a PayerClient. Returns the payer dict."""
    return get_success_data(api_client.create_payer_client(
        create_payer_client_payload(**overrides), OPS))


def create_provider(npi="1000000001", **overrides):
    """Register a Provider. Returns the provider dict."""
    payload = create_provider_payload(npi=npi, **overrides)
    return get_success_data(api_client.create_provider(payload, NET))


def setup_payer_and_provider(payer_overrides=None, npi="1000000001", provider_overrides=None):
    """Create one payer and one provider. Returns (payer, provider, headers_ctx)."""
    payer = create_payer(**(payer_overrides or {}))
    provider = create_provider(npi=npi, **(provider_overrides or {}))
    return payer, provider, _ctx(payer, provider)


def create_medicare_entry(**overrides):
    return get_success_data(api_client.create_medicare_entry(
        create_medicare_entry_payload(**overrides), NET))


def create_ucr_rate(**overrides):
    return get_success_data(api_client.create_ucr_rate(
        create_ucr_rate_payload(**overrides), NET))


def create_policy(payer, ctx, **overrides):
    """Create a RepricingPolicy owned by payer. Returns the policy dict."""
    return get_success_data(api_client.create_repricing_policy(
        create_repricing_policy_payload(payer["id"], **overrides),
        ctx["payer_admin"]))


def create_agreement(provider, **overrides):
    return get_success_data(api_client.create_network_agreement(
        create_network_agreement_payload(provider["id"], **overrides), NET))


# ---------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_claim(payer, provider, ctx, **overrides):
    """Ingest a claim. Returns the claim dict (status RECEIVED, version 1)."""
    return get_success_data(api_client.create_claim(
        create_claim_payload(payer["id"], provider["id"], **overrides),
        ctx["payer_rep"]))


def add_line(claim_id, ctx, **overrides):
    """Add one claim line. Returns the ClaimLine dict."""
    return get_success_data(api_client.add_claim_line(
        claim_id, create_claim_line_payload(**overrides), ctx["payer_rep"]))


def reprice(claim_id, expected_version, ctx, **payload_overrides):
    """Reprice a claim. Returns the raw response (callers validate)."""
    payload = {"expected_claim_version": expected_version}
    payload.update(payload_overrides)
    return api_client.reprice_claim(claim_id, payload, ctx["payer_rep"])


def setup_priced_claim(payer_overrides=None, claim_overrides=None,
                       line_overrides=None, policy_overrides=None,
                       npi="1000000001", procedure_code="99283",
                       region_code="R1", medicare=True):
    """
    Canonical pipeline: payer + provider + Medicare entry + PERCENT_OF_MEDICARE
    x1.50 policy + claim + one line + reprice.

    Default fixture yields allowed 33000 on billed 60000 (99283 qty 2 @ 30000).

    Returns dict with keys:
      payer, provider, ctx, claim, line, determination, policy
    `claim` is re-fetched after pricing so derived fields are populated.
    """
    payer, provider, ctx = setup_payer_and_provider(
        payer_overrides=payer_overrides, npi=npi)
    policy = None
    if medicare:
        create_medicare_entry(procedure_code=procedure_code, region_code=region_code)
    if policy_overrides is not False:
        policy = create_policy(payer, ctx, **(policy_overrides or {}))
    claim = create_claim(payer, provider, ctx, **(claim_overrides or {}))
    line = add_line(claim["id"], ctx, **(line_overrides or {}))
    det = get_success_data(reprice(claim["id"], claim["version"] + 1, ctx))
    claim = get_success_data(api_client.get_claim(claim["id"], ctx["payer_rep"]))
    return {
        "payer": payer, "provider": provider, "ctx": ctx, "claim": claim,
        "line": line, "determination": det, "policy": policy,
    }


def setup_finalized_claim(**kwargs):
    """setup_priced_claim + finalize. Returns the same dict with updated claim."""
    env = setup_priced_claim(**kwargs)
    get_success_data(api_client.finalize_claim(env["claim"]["id"], env["ctx"]["payer_rep"]))
    env["claim"] = get_success_data(api_client.get_claim(
        env["claim"]["id"], env["ctx"]["payer_rep"]))
    return env


# ---------------------------------------------------------------------------
# Tier 3: negotiation lifecycle shortcuts
# ---------------------------------------------------------------------------

def open_case(claim_id, ctx, opened_by="payer_rep"):
    """Open a NegotiationCase on a claim. Returns the case dict (OPEN)."""
    return get_success_data(api_client.create_negotiation_case(
        create_negotiation_case_payload(claim_id), ctx[opened_by]))


def place_offer(case_id, offer_cents, expected_version, ctx):
    """Payer places an offer. Returns raw response."""
    return api_client.offer_negotiation_case(
        case_id, create_offer_payload(offer_cents, expected_version),
        ctx["payer_rep"])


def counter_case(case_id, counter_cents, ctx):
    """Provider counters. Returns raw response."""
    return api_client.counter_negotiation_case(
        case_id, create_counter_payload(counter_cents), ctx["provider_rep"])


def find_settlement_for_case(case_id, ctx):
    """Fetch the SettlementAgreement created by case acceptance."""
    data = get_success_data(api_client.list_settlement_agreements(
        ctx["payer_rep"], params={"negotiation_case_id": case_id}))
    rows = data if isinstance(data, list) else data.get("items", data)
    assert rows, f"Setup failed: no settlement agreement found for case {case_id}"
    return rows[0]


def setup_accepted_case(payer_offer=30000, counter=50000, accept_by="payer_rep",
                        **priced_kwargs):
    """
    Priced claim (33000 fixture) + case OPEN + payer offer + provider counter
    + acceptance. Default acceptance is by the payer (accepting the counter),
    leaving the case ACCEPTED with a PENDING_SIGNATURES settlement at the
    current offer.

    Returns dict: env keys plus case, settlement.
    """
    env = setup_priced_claim(**priced_kwargs)
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], payer_offer, case["version"], env["ctx"]))
    get_success_data(counter_case(case["id"], counter, env["ctx"]))
    get_success_data(api_client.accept_negotiation_case(case["id"], env["ctx"][accept_by]))
    settlement = find_settlement_for_case(case["id"], env["ctx"])
    case = get_success_data(api_client.get_negotiation_case(case["id"], env["ctx"]["payer_rep"]))
    env.update({"case": case, "settlement": settlement})
    return env


# ---------------------------------------------------------------------------
# Tier 3: NSA / IDR lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_expired_open_negotiation(initiated_at="2026-09-10T10:00:00Z",
                                   after_expiry="2026-10-23T00:00:00Z",
                                   initiated_by="PAYER", **priced_kwargs):
    """
    Priced NSA-flagged claim + OpenNegotiation initiated at `initiated_at`,
    then the logical clock advanced past expires_at so the negotiation is
    EXPIRED and the IDR window is open.

    Returns env dict plus open_negotiation.
    """
    get_success_data(api_client.set_clock(initiated_at, OPS))
    claim_overrides = dict(priced_kwargs.pop("claim_overrides", {}) or {})
    claim_overrides["nsa_flag"] = True
    env = setup_priced_claim(claim_overrides=claim_overrides, **priced_kwargs)
    opener = env["ctx"]["payer_rep"] if initiated_by == "PAYER" else env["ctx"]["provider_rep"]
    on = get_success_data(api_client.create_open_negotiation(
        create_open_negotiation_payload(env["claim"]["id"], initiated_by=initiated_by),
        opener))
    get_success_data(api_client.set_clock(after_expiry, OPS))
    on = get_success_data(api_client.get_open_negotiation(on["id"], env["ctx"]["payer_rep"]))
    env["open_negotiation"] = on
    return env


# ---------------------------------------------------------------------------
# Tier 5: invoicing
# ---------------------------------------------------------------------------

def issue_invoice(payer_id, claim_ids):
    """Create + issue a fee invoice. Returns the issued invoice dict."""
    invoice = get_success_data(api_client.create_fee_invoice(
        create_fee_invoice_payload(payer_id, claim_ids), OPS))
    return get_success_data(api_client.issue_fee_invoice(invoice["id"], OPS))
