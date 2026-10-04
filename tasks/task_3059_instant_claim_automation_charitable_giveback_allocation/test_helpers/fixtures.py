"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
failed setup surfaces as a clear "Setup failed" error.

Common composite fixture: a bound policy requires
  clock → cause → cohort → APPROVED filing → ACTIVE fee config →
  policyholder → quote → application → approve.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload,
    create_cause_payload,
    create_cohort_payload,
    create_claim_payload,
    create_fee_config_payload,
    create_policyholder_payload,
    create_quote_payload,
    create_rate_filing_payload,
    create_treaty_payload,
)
from .test_users import TEST_USERS, make_adjuster_headers, make_policyholder_headers

START_CLOCK = "2026-09-01T00:00:00Z"

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]
ADJ_1 = TEST_USERS["adjuster_1_headers"]
ADJ_2 = TEST_USERS["adjuster_2_headers"]


# ---------------------------------------------------------------------------
# Tier 1: atomic resource builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = START_CLOCK):
    """Advance the logical clock; returns the echoed current_utc payload."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_cause(name: str = "Cause C") -> dict:
    return get_success_data(api_client.create_cause(create_cause_payload(name=name), ADMIN))


def create_cohort(cohort_year: int, cause_id: str) -> dict:
    payload = create_cohort_payload(cohort_year=cohort_year, cause_id=cause_id)
    return get_success_data(api_client.create_cohort(payload, ADMIN))


def create_cause_and_cohort(cohort_year: int = 2026, cause_name: str = "Cause C") -> tuple:
    cause = create_cause(cause_name)
    cohort = create_cohort(cohort_year, cause["id"])
    return cause, cohort


def create_approved_filing(
    state_code: str = "TX",
    filing_mode: str = "PCT_OF_PREMIUM",
    max_flat_fee_pct: float = 0.30,
    max_flat_fee_cap_cents: int = 90000,
) -> dict:
    payload = create_rate_filing_payload(
        state_code=state_code,
        filing_mode=filing_mode,
        max_flat_fee_pct=max_flat_fee_pct,
        max_flat_fee_cap_cents=max_flat_fee_cap_cents,
    )
    filing = get_success_data(api_client.create_rate_filing(payload, UNDERWRITER))
    return get_success_data(api_client.approve_rate_filing(filing["id"], UNDERWRITER))


def create_active_fee_config(
    state_code: str = "TX",
    filing_id: str = None,
    flat_fee_pct: float = 0.20,
    flat_fee_cents: int = 90000,
) -> dict:
    payload = create_fee_config_payload(
        state_code=state_code,
        filing_id=filing_id,
        flat_fee_pct=flat_fee_pct,
        flat_fee_cents=flat_fee_cents,
    )
    fc = get_success_data(api_client.create_fee_config(payload, UNDERWRITER))
    return get_success_data(api_client.activate_fee_config(fc["id"], UNDERWRITER))


def setup_state_fee(
    state_code: str = "TX",
    filing_mode: str = "PCT_OF_PREMIUM",
    max_flat_fee_pct: float = 0.30,
    max_flat_fee_cap_cents: int = 90000,
    flat_fee_pct: float = 0.20,
    flat_fee_cents: int = 90000,
) -> tuple:
    """APPROVED filing + ACTIVE fee config for one state. Returns (filing, fee_config)."""
    filing = create_approved_filing(
        state_code=state_code,
        filing_mode=filing_mode,
        max_flat_fee_pct=max_flat_fee_pct,
        max_flat_fee_cap_cents=max_flat_fee_cap_cents,
    )
    fc = create_active_fee_config(
        state_code=state_code,
        filing_id=filing["id"],
        flat_fee_pct=flat_fee_pct,
        flat_fee_cents=flat_fee_cents,
    )
    return filing, fc


def create_policyholder(state_code: str = "TX", email: str = None, full_name: str = "P") -> dict:
    if email is None:
        email = f"ph-{uuid.uuid4().hex[:8]}@example.com"
    payload = create_policyholder_payload(email=email, full_name=full_name, state_code=state_code)
    return get_success_data(api_client.create_policyholder(payload, ANONYMOUS))


def create_quote(ph_id: str, coverage_amount_cents: int = 500000, premium_cents: int = 100000) -> dict:
    payload = create_quote_payload(
        coverage_amount_cents=coverage_amount_cents, premium_cents=premium_cents
    )
    return get_success_data(api_client.create_quote(payload, make_policyholder_headers(ph_id)))


def create_application(
    ph_id: str,
    quote_id: str,
    checkout_velocity_seconds: int = 60,
    device_reuse_count: int = 0,
    answers_ipa_acknowledged: bool = True,
) -> dict:
    payload = create_application_payload(
        quote_id=quote_id,
        checkout_velocity_seconds=checkout_velocity_seconds,
        device_reuse_count=device_reuse_count,
        answers_ipa_acknowledged=answers_ipa_acknowledged,
    )
    return get_success_data(api_client.create_application(payload, make_policyholder_headers(ph_id)))


def create_active_treaty(name: str = "QS-75", quota_share_pct: float = 0.75) -> dict:
    treaty = get_success_data(
        api_client.create_treaty(create_treaty_payload(name=name, quota_share_pct=quota_share_pct), FINANCE)
    )
    return get_success_data(api_client.activate_treaty(treaty["id"], FINANCE))


def attach_treaty(cohort_id: str, treaty_id: str) -> dict:
    return get_success_data(
        api_client.attach_cohort_reinsurance(cohort_id, {"treaty_id": treaty_id}, FINANCE)
    )


# ---------------------------------------------------------------------------
# Tier 2: bound policy hierarchy
# ---------------------------------------------------------------------------

def bind_policy(
    ph_id: str,
    quote_id: str,
    application_id: str,
) -> dict:
    """Approve a clean UNDER_REVIEW application; returns the created Policy."""
    return get_success_data(api_client.approve_application(application_id, UNDERWRITER))


def setup_bound_policy(
    state_code: str = "TX",
    premium_cents: int = 100000,
    coverage_amount_cents: int = 500000,
    cohort_year: int = 2026,
    filing_mode: str = "PCT_OF_PREMIUM",
    max_flat_fee_pct: float = 0.30,
    max_flat_fee_cap_cents: int = 90000,
    flat_fee_pct: float = 0.20,
    flat_fee_cents: int = 90000,
    attach_treaty_quota: float = None,
    start_clock: str = START_CLOCK,
    application_overrides: dict = None,
    email: str = None,
) -> dict:
    """Full standard stack. Returns a dict with every created resource:
    cause, cohort, filing, fee_config, policyholder, quote, application, policy
    (and treaty when attach_treaty_quota is given).
    """
    set_clock(start_clock)
    cause, cohort = create_cause_and_cohort(cohort_year)
    filing, fee_config = setup_state_fee(
        state_code=state_code,
        filing_mode=filing_mode,
        max_flat_fee_pct=max_flat_fee_pct,
        max_flat_fee_cap_cents=max_flat_fee_cap_cents,
        flat_fee_pct=flat_fee_pct,
        flat_fee_cents=flat_fee_cents,
    )
    treaty = None
    if attach_treaty_quota is not None:
        treaty = create_active_treaty(quota_share_pct=attach_treaty_quota)
        attach_treaty(cohort["id"], treaty["id"])
    ph = create_policyholder(state_code=state_code, email=email)
    quote = create_quote(ph["id"], coverage_amount_cents, premium_cents)
    app_kwargs = dict(application_overrides or {})
    application = create_application(ph["id"], quote["id"], **app_kwargs)
    policy = bind_policy(ph["id"], quote["id"], application["id"])
    return {
        "cause": cause,
        "cohort": cohort,
        "filing": filing,
        "fee_config": fee_config,
        "treaty": treaty,
        "policyholder": ph,
        "quote": quote,
        "application": application,
        "policy": policy,
    }


def pay_premium(policy_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.pay_premium(policy_id, {"amount_cents": amount_cents}, FINANCE)
    )


# ---------------------------------------------------------------------------
# Tier 3: claims lifecycle
# ---------------------------------------------------------------------------

def file_claim(
    ph_id: str,
    policy_id: str,
    claimed_amount_cents: int,
    fraud_score: float,
    video_statement_ref: str = "vid",
) -> dict:
    payload = create_claim_payload(
        policy_id=policy_id,
        video_statement_ref=video_statement_ref,
        claimed_amount_cents=claimed_amount_cents,
        fraud_score=fraud_score,
    )
    return get_success_data(api_client.create_claim(payload, make_policyholder_headers(ph_id)))


def create_escalated_claim(ph_id: str, policy_id: str, claimed_amount_cents: int) -> dict:
    """A claim with an elevated fraud score always escalates."""
    claim = file_claim(ph_id, policy_id, claimed_amount_cents, 0.90)
    assert claim["status"] == "ESCALATED", f"Setup failed: claim not ESCALATED: {claim}"
    return claim


def approve_escalated_claim(claim_id: str, claim_version: int, payout_cents: int) -> dict:
    return get_success_data(
        api_client.approve_claim(
            claim_id,
            {"payout_cents": payout_cents, "expected_claim_version": claim_version},
            ADJ_1,
        )
    )


def deny_escalated_claim(
    claim_id: str,
    claim_version: int,
    denial_reason: str = "COVERAGE",
    adjuster_headers=None,
) -> dict:
    headers = adjuster_headers if adjuster_headers is not None else ADJ_1
    return get_success_data(
        api_client.deny_claim(
            claim_id,
            {"denial_reason": denial_reason, "expected_claim_version": claim_version},
            headers,
        )
    )


def file_appeal(ph_id: str, claim_id: str, statement: str = "please review") -> dict:
    return get_success_data(
        api_client.create_appeal(claim_id, {"statement": statement}, make_policyholder_headers(ph_id))
    )


def setup_denied_claim_with_appeal(
    denial_reason: str = "COVERAGE",
    claimed_amount_cents: int = 50000,
    premium_cents: int = 100000,
    state_code: str = "TX",
) -> dict:
    """Standard stack + escalated claim denied by adj-1 + PENDING appeal.
    Returns the setup dict plus claim and appeal."""
    ctx = setup_bound_policy(state_code=state_code, premium_cents=premium_cents)
    pay_premium(ctx["policy"]["id"], premium_cents)
    ph = ctx["policyholder"]
    claim = create_escalated_claim(ph["id"], ctx["policy"]["id"], claimed_amount_cents)
    deny_escalated_claim(claim["id"], claim["version"], denial_reason)
    appeal = file_appeal(ph["id"], claim["id"])
    ctx["claim"] = claim
    ctx["appeal"] = appeal
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: strike / debarment accumulation
# ---------------------------------------------------------------------------

def deny_claims_with_fraud(ph_id: str, policy_id: str, count: int, amount_cents: int = 30000):
    """File and FRAUD-deny `count` escalated claims; returns the claims."""
    claims = []
    for i in range(count):
        claim = create_escalated_claim(ph_id, policy_id, amount_cents)
        deny_escalated_claim(claim["id"], claim["version"], "FRAUD")
        claims.append(claim)
    return claims


# ---------------------------------------------------------------------------
# Ledger reads
# ---------------------------------------------------------------------------

def list_ledger_entries(policy_id: str, kind: str = None, headers=None) -> list:
    params = {"kind": kind} if kind else None
    data = get_success_data(api_client.list_policy_ledger(policy_id, headers or FINANCE, params))
    if isinstance(data, list):
        return data
    return data


def ledger_amount(policy_id: str, kind: str, headers=None) -> int:
    """Sum of amount_cents over ledger entries of the given kind."""
    return sum(e["amount_cents"] for e in list_ledger_entries(policy_id, kind, headers))


def get_cohort(cohort_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_cohort(cohort_id, headers or FINANCE))


def get_policy(policy_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_policy(policy_id, headers or FINANCE))


def get_policyholder(ph_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_policyholder(ph_id, headers or ADMIN))
