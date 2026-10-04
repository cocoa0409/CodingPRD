"""Composite setup helpers.

Every test starts against a freshly restarted server (empty database), so all
preconditions are built from scratch through the PRD's public endpoints. The
helpers below encapsulate the repeated multi-step chains:

  seed_catalog                        tier + form catalog rows (idempotent per code)
  create_account / create_return      account + DRAFT return, returns-tracked
  add_form / remove_form              version-tracked form mutations
  get_pending_prompt / resolve_pending_prompt
  setup_return_with_forms             account + return + forms (prompt optionally resolved)
  setup_review_ready_return           + submit-review -> READY_FOR_REVIEW
  setup_submitted_return              + file -> SUBMITTED, PENDING FilingAttempt
  setup_accepted_return               + authority ACCEPTED
  setup_filed_claim                   + claim FILED
  setup_active_refund_transfer        + agreement ACTIVE, refund_transfer_selected

All identity threading is explicit: Taxpayer headers are built with the
owning account's id. Setup calls use the lenient get_success_data() so
failures surface as "Setup failed" instead of confusing assertions.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ACTIVE_BANK_DISCLOSURE_VERSION,
    FORM_SPECS,
    TEST_DEFAULTS,
)
from .factories import (
    add_state_return_payload,
    create_account_payload,
    create_return_payload,
    create_snapshot_payload,
    seed_form_payload,
    seed_tier_payload,
)
from .test_users import (
    TEST_USERS,
    make_taxpayer_headers,
)

_COUNTER = itertools.count(1)

# Tier -> forms it natively supports, for the standard catalog.
_TIER_FORMS = {
    "FREE": ["F1040", "W2_WH"],
    "DELUXE": ["SCH_E"],
    "PREMIER": ["SCH_D", "F8949", "F4562"],
    "SELF_EMPLOYED": ["SCH_C"],
}


class ReturnHandle:
    """Tracks a TaxReturn's id and latest observed version."""

    def __init__(self, account_id, data):
        self.account_id = account_id
        self.id = data["id"]
        self.version = data["version"]
        self.data = data

    def refresh(self, data):
        self.data = data
        self.version = data["version"]
        return data


def unique_email(prefix="filer"):
    return f"{prefix}-{next(_COUNTER)}@example.com"


# --- catalog -----------------------------------------------------------------

def seed_catalog(tiers=("FREE",), forms=("F1040",), operator_headers=None):
    """Seed tier and form catalog rows via the PlatformOperator endpoints.

    Always seeds the full standard catalog (every tier in TIER_PRICES and
    every form in FORM_SPECS): tests routinely add standard-catalog forms or
    select standard-catalog tiers beyond the rows named here (e.g. a W2_WH
    withholding form added after setup, or a select-tier escape to DELUXE),
    and the PRD's catalog is a global configuration surface rather than a
    per-test fixture. The `tiers`/`forms` arguments still drive the
    `supported_forms` wiring for the named tiers.
    """
    headers = operator_headers or TEST_USERS["platform_operator_headers"]
    from .constants import TIER_PRICES

    for code in TIER_PRICES:
        supported = [f for f in forms if FORM_SPECS.get(f, {}).get("minimum_tier") == code]
        if code in _TIER_FORMS and not supported:
            supported = [f for f in _TIER_FORMS[code] if f in forms]
        get_success_data(
            api_client.seed_tier(
                seed_tier_payload(code, supported_forms=supported), headers
            )
        )
    for code in FORM_SPECS:
        get_success_data(api_client.seed_form(seed_form_payload(code), headers))


# --- accounts and returns -----------------------------------------------------

def create_account(email=None, **overrides):
    """Register a TaxpayerAccount via the bootstrap endpoint."""
    email = email or unique_email()
    resp = api_client.create_account(
        create_account_payload(email=email, **overrides),
        TEST_USERS["taxpayer_headers"],
    )
    data = get_success_data(resp)
    data["_headers"] = make_taxpayer_headers(data["id"])
    return data


def taxpayer_headers_for(account):
    return make_taxpayer_headers(account["id"])


def create_return(account, tax_year=None):
    """Start a DRAFT return on the account; returns a ReturnHandle."""
    headers = taxpayer_headers_for(account)
    resp = api_client.create_return(
        account["id"],
        create_return_payload(tax_year=tax_year or TEST_DEFAULTS["TAX_YEAR"]),
        headers,
    )
    return ReturnHandle(account["id"], get_success_data(resp))


def get_return(ret, headers=None):
    resp = api_client.get_return(ret.id, headers or make_taxpayer_headers(ret.account_id))
    return get_success_data(resp)


def suspend_account(account):
    resp = api_client.suspend_account(
        account["id"], TEST_USERS["platform_operator_headers"]
    )
    return get_success_data(resp)


# --- forms --------------------------------------------------------------------

def add_form(ret, form_code, amount_cents=0):
    """Add a form at the tracked version; refreshes the handle's version."""
    resp = api_client.add_form(
        ret.id, form_code, amount_cents, ret.version,
        make_taxpayer_headers(ret.account_id),
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def remove_form(ret, form_id):
    resp = api_client.remove_form(
        ret.id, form_id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def list_forms(ret):
    resp = api_client.list_forms(ret.id, make_taxpayer_headers(ret.account_id))
    return get_success_data(resp)


# --- upgrade prompts -----------------------------------------------------------

def list_prompts(ret):
    resp = api_client.list_upgrade_prompts(
        ret.id, make_taxpayer_headers(ret.account_id)
    )
    return get_success_data(resp)


def get_pending_prompt(ret):
    """Return the single PENDING UpgradePrompt for the return (or None)."""
    for prompt in list_prompts(ret):
        if prompt.get("status") == "PENDING":
            return prompt
    return None


def acknowledge_prompt(ret, prompt_id):
    resp = api_client.acknowledge_prompt(
        ret.id, prompt_id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def decline_prompt(ret, prompt_id):
    resp = api_client.decline_prompt(
        ret.id, prompt_id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def resolve_pending_prompt(ret, mode="acknowledge"):
    """Resolve the return's outstanding PENDING prompt (ack or decline)."""
    prompt = get_pending_prompt(ret)
    assert prompt is not None, "Setup failed: no PENDING prompt to resolve"
    if mode == "acknowledge":
        return acknowledge_prompt(ret, prompt["id"])
    return decline_prompt(ret, prompt["id"])


# --- state returns ---------------------------------------------------------------

def add_state_return(ret, state_code, **overrides):
    payload = add_state_return_payload(state_code, ret.version, **overrides)
    resp = api_client.add_state_return(
        ret.id, payload, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def ready_state_return(ret, state_return_id):
    resp = api_client.ready_state_return(
        ret.id, state_return_id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def remove_state_return(ret, state_return_id):
    resp = api_client.remove_state_return(
        ret.id, state_return_id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


# --- snapshots -----------------------------------------------------------------

def create_snapshot(account, tax_year, carryforward_items):
    headers = taxpayer_headers_for(account)
    resp = api_client.create_snapshot(
        account["id"], create_snapshot_payload(tax_year, carryforward_items), headers
    )
    return get_success_data(resp)


def import_snapshot(account, snapshot_id, ret):
    resp = api_client.import_snapshot(
        account["id"], snapshot_id, ret.id, ret.version,
        taxpayer_headers_for(account),
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def get_snapshot(account, snapshot_id):
    resp = api_client.get_snapshot(
        account["id"], snapshot_id, taxpayer_headers_for(account)
    )
    return get_success_data(resp)


# --- review / filing lifecycle ---------------------------------------------------

def submit_review(ret):
    resp = api_client.submit_review(
        ret.id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(data)
    return data


def reopen_return(ret):
    resp = api_client.reopen_return(
        ret.id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(data)
    return data


def file_return(ret, payload_hash="hash-1"):
    resp = api_client.file_return(
        ret.id, payload_hash, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def amend_return(ret):
    resp = api_client.amend_return(
        ret.id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(data)
    return data


def filing_callback(filing_attempt_id, outcome, rejection_code=None):
    resp = api_client.filing_callback(
        filing_attempt_id, outcome,
        TEST_USERS["platform_operator_headers"],
        rejection_code=rejection_code,
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(
        to_iso8601, TEST_USERS["platform_operator_headers"]
    )
    return get_success_data(resp)


# --- composite scenarios ---------------------------------------------------------

def setup_return_with_forms(
    forms=("F1040",),
    agi_cents=TEST_DEFAULTS["AGI_CENTS"],
    resident_state_code=TEST_DEFAULTS["RESIDENT_STATE"],
    email=None,
    resolve_prompt=None,
    **account_overrides,
):
    """Account + DRAFT return + the given forms added in order.

    resolve_prompt: None (leave any PENDING prompt outstanding),
    "acknowledge", or "decline".
    Returns (account, ReturnHandle).
    """
    needed_tiers = {"FREE"}
    for code in forms:
        spec = FORM_SPECS.get(code)
        if spec:
            needed_tiers.add(spec["minimum_tier"])
    # Also include intermediate tiers so rank comparisons and price deltas
    # behave the same as the full catalog.
    all_tiers = ("FREE", "DELUXE", "PREMIER", "SELF_EMPLOYED")
    rank_of = {"FREE": 0, "DELUXE": 1, "PREMIER": 2, "SELF_EMPLOYED": 3}
    tiers = tuple(t for t in all_tiers if rank_of[t] <= max(rank_of[t] for t in needed_tiers))
    seed_catalog(tiers=tiers, forms=tuple(dict.fromkeys(forms)))
    account = create_account(
        email=email,
        agi_cents=agi_cents,
        resident_state_code=resident_state_code,
        **account_overrides,
    )
    ret = create_return(account)
    for code in forms:
        add_form(ret, code)
    if resolve_prompt:
        resolve_pending_prompt(ret, mode=resolve_prompt)
    return account, ret


def setup_review_ready_return(**kwargs):
    """Account + return + forms + submit-review. Returns (account, ret, data)."""
    account, ret = setup_return_with_forms(**kwargs)
    data = submit_review(ret)
    return account, ret, data


def setup_submitted_return(state_codes=(), ready_states=True, **kwargs):
    """Full path to SUBMITTED with one PENDING FilingAttempt.

    Optionally attaches state returns (marked READY when ready_states).
    Returns (account, ret, filing_attempt, state_return_ids).
    """
    account, ret = setup_return_with_forms(**kwargs)
    sr_ids = []
    for code in state_codes:
        sr = add_state_return(ret, code)
        sr_ids.append(sr["id"])
    if ready_states:
        for sr_id in sr_ids:
            ready_state_return(ret, sr_id)
    submit_review(ret)
    attempt = file_return(ret)
    return account, ret, attempt, sr_ids


def setup_accepted_return(**kwargs):
    """Full path through authority acceptance. Returns (account, ret, attempt)."""
    account, ret, attempt, _ = setup_submitted_return(**kwargs)
    filing_callback(attempt["id"], "ACCEPTED")
    ret.refresh(get_return(ret))
    return account, ret, attempt


def setup_filed_claim(claimed_error_amount_cents=8000, **kwargs):
    """Accepted return + one claim in FILED status.
    Returns (account, ret, attempt, claim)."""
    account, ret, _attempt = setup_accepted_return(**kwargs)
    headers = make_taxpayer_headers(account["id"])
    resp = api_client.create_claim(ret.id, claimed_error_amount_cents, headers)
    claim = get_success_data(resp)
    return account, ret, _attempt, claim


def setup_under_review_claim(claimed_error_amount_cents=8000, **kwargs):
    """Filed claim moved to UNDER_REVIEW by the adjuster."""
    account, ret, attempt, claim = setup_filed_claim(
        claimed_error_amount_cents, **kwargs
    )
    resp = api_client.start_claim_review(
        claim["id"], TEST_USERS["claims_adjuster_headers"]
    )
    claim = get_success_data(resp)
    return account, ret, attempt, claim


# --- refund transfer --------------------------------------------------------------

def create_refund_transfer(ret, bank_partner_code="BANK_A"):
    resp = api_client.create_refund_transfer(
        ret.id, bank_partner_code, ret.version,
        make_taxpayer_headers(ret.account_id),
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def accept_disclosure(ret):
    resp = api_client.accept_disclosure(
        ret.id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def void_refund_transfer(ret):
    resp = api_client.void_refund_transfer(
        ret.id, ret.version, make_taxpayer_headers(ret.account_id)
    )
    data = get_success_data(resp)
    ret.refresh(get_return(ret))
    return data


def list_refund_transfers(ret):
    resp = api_client.list_refund_transfers(
        ret.id, make_taxpayer_headers(ret.account_id)
    )
    return get_success_data(resp)


def setup_active_refund_transfer(forms=("F1040", "W2_WH"), bank="BANK_A", **kwargs):
    """Return with an ACTIVE refund-transfer agreement (disclosure accepted).

    Returns (account, ret, agreement)."""
    account, ret = setup_return_with_forms(forms=forms, **kwargs)
    agreement = create_refund_transfer(ret, bank_partner_code=bank)
    assert agreement["disclosure_version"] == ACTIVE_BANK_DISCLOSURE_VERSION
    accept_disclosure(ret)
    ret.refresh(get_return(ret))
    return account, ret, agreement
