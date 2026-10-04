"""Composite setup helpers.

Every helper builds preconditions from scratch via PRD-declared endpoints
(the server is restarted with an empty database before every test). Setup
calls use the lenient get_success_data() so a failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.

Identity threading: Policyholder is entity-backed — every ownership-gated
call uses make_policyholder_headers(account["id"]).
"""

import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_EFFECTIVE_AT, RULE_WINDOW_FROM, RULE_WINDOW_TO
from .factories import (
    create_appetite_rule_payload,
    create_business_account_payload,
    create_claim_payload,
    create_class_code_payload,
    create_endorsement_payload,
    create_evidence_payload,
    create_quote_payload,
    create_risk_signal_payload,
)
from .test_users import (
    make_claims_adjuster_headers,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    make_platform_admin_headers,
    make_policyholder_headers,
    make_underwriter_headers,
)

ADMIN = make_platform_admin_headers("setup-admin")
AGENT_SETUP = {"X-User-ID": "setup-agent", "X-User-Role": "Agent", "Content-Type": "application/json"}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{_uuid.uuid4().hex[:10]}"


def _fail(what: str, resp):
    raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")


def _data(resp, what: str):
    if resp.status_code >= 400:
        _fail(what, resp)
    return get_success_data(resp)


# --- Tier 1: appetite + class ----------------------------------------------

def setup_class_and_rule(code, description, keyword, eligible_lines,
                         base_rates_cents, risk_factor, appetite_active=True):
    """Create one class code plus one enabled ADMIT rule for `keyword`
    covering the whole test horizon. Returns (class_code, rule)."""
    cc = _data(
        api_client.create_class_code(
            create_class_code_payload(
                code=code, description=description,
                eligible_lines=eligible_lines,
                base_rates_cents=base_rates_cents,
                risk_factor=risk_factor, appetite_active=appetite_active,
            ), ADMIN,
        ), "create_class_code",
    )
    rule = _data(
        api_client.create_appetite_rule(
            create_appetite_rule_payload(keyword=keyword, class_code=code), ADMIN,
        ), "create_appetite_rule",
    )
    return cc, rule


# --- Tier 2: accounts -------------------------------------------------------

def setup_account(channel="DIRECT", partner_tenant=None, legal_name=None):
    """Onboard one business account (as Agent). Returns the account."""
    payload = create_business_account_payload(
        legal_name=legal_name or _uniq("Co"),
        contact_email=f"{_uuid.uuid4().hex[:10]}@example.com",
        channel=channel,
    )
    if partner_tenant is not None:
        payload["partner_tenant"] = partner_tenant
    return _data(api_client.create_business_account(payload, AGENT_SETUP),
                 "create_business_account")


# --- Tier 3: quotes and policies -------------------------------------------

def setup_quoted(account, raw_description, selected_lines, exposure_units=10,
                 requested_effective_at=CLOCK_DEFAULT_EFFECTIVE_AT,
                 uw_answers=None, channel_partner_id=None):
    """Create a quote as the account's policyholder. Asserts it routes QUOTED.
    Returns the quote."""
    payload = create_quote_payload(
        business_account_id=account["id"],
        raw_description=raw_description,
        selected_lines=selected_lines,
        exposure_units=exposure_units,
        requested_effective_at=requested_effective_at,
        uw_answers=uw_answers or {},
    )
    if channel_partner_id is not None:
        payload["channel_partner_id"] = channel_partner_id
    ph = make_policyholder_headers(account["id"])
    quote = _data(api_client.create_quote(payload, ph), "create_quote")
    assert quote.get("status") == "QUOTED", (
        f"Setup expected QUOTED, got {quote.get('status')} "
        f"(risk_score={quote.get('risk_score')})"
    )
    return quote


def bind_quote(account, quote):
    """Bind a QUOTED quote as its policyholder. Returns the created Policy."""
    ph = make_policyholder_headers(account["id"])
    policy = _data(
        api_client.bind_quote(
            quote["id"], {"expected_quote_version": quote["version"]}, ph,
        ), "bind_quote",
    )
    return policy


def setup_policy(account, raw_description, selected_lines, exposure_units=10,
                 requested_effective_at=CLOCK_DEFAULT_EFFECTIVE_AT,
                 uw_answers=None):
    """Quote + bind in one shot. Returns the Policy (BOUND/ACTIVE)."""
    quote = setup_quoted(
        account, raw_description, selected_lines, exposure_units,
        requested_effective_at, uw_answers,
    )
    return bind_quote(account, quote)


def refresh_policy(policy_id, headers=None):
    return _data(api_client.get_policy(policy_id, headers or ADMIN), "get_policy")


# --- Tier 4: clock -----------------------------------------------------------

def set_clock(to_iso8601: str):
    return _data(api_client.set_clock(to_iso8601, ADMIN), "set_clock")


# --- Tier 5: endorsements / certificates ------------------------------------

def create_effective_endorsement(account, policy, payload_overrides):
    """Create an endorsement as the policyholder with the current
    expected_policy_version (read fresh). Returns the EFFECTIVE endorsement."""
    ph = make_policyholder_headers(account["id"])
    current = refresh_policy(policy["id"])
    payload = {"expected_policy_version": current["version"]}
    payload.update(payload_overrides)
    return _data(
        api_client.create_endorsement(policy["id"], payload, ph),
        "create_endorsement",
    )


def setup_policy_with_certificate(account, raw_description, selected_lines,
                                  ai_holder_name="Landlord LP",
                                  exposure_units=10):
    """Policy + EFFECTIVE ADDITIONAL_INSURED endorsement + ISSUED certificate.
    Returns (policy, endorsement, certificate)."""
    policy = setup_policy(account, raw_description, selected_lines, exposure_units)
    ph = make_policyholder_headers(account["id"])
    endorsement = create_effective_endorsement(account, policy, {
        "endorsement_type": "ADDITIONAL_INSURED",
        "effective_at": CLOCK_DEFAULT_EFFECTIVE_AT,
        "ai_holder_name": ai_holder_name,
    })
    cert = _data(
        api_client.create_certificate(
            {"policy_id": policy["id"], "endorsement_id": endorsement["id"]}, ph,
        ), "create_certificate",
    )
    return policy, endorsement, cert


# --- Tier 6: claims ----------------------------------------------------------

def submit_claim(account, policy, claim_amount_cents=150000,
                 loss_occurred_at=CLOCK_DEFAULT_EFFECTIVE_AT,
                 description="Ladder fell"):
    """Policyholder files a claim. Returns the Claim (status per triage)."""
    ph = make_policyholder_headers(account["id"])
    return _data(
        api_client.create_claim(
            create_claim_payload(
                policy_id=policy["id"],
                loss_occurred_at=loss_occurred_at,
                description=description,
                claim_amount_cents=claim_amount_cents,
            ), ph,
        ), "create_claim",
    )


def attach_evidence(account, claim, photo_ref=None,
                    exif_taken_at=CLOCK_DEFAULT_EFFECTIVE_AT,
                    file_size_bytes=2048):
    ph = make_policyholder_headers(account["id"])
    return _data(
        api_client.attach_evidence(
            claim["id"],
            create_evidence_payload(
                photo_ref=photo_ref or _uniq("ph://ev"),
                exif_taken_at=exif_taken_at,
                file_size_bytes=file_size_bytes,
            ), ph,
        ), "attach_evidence",
    )


def pay_claim(claim_id, adjuster_id, finance_id):
    """Walk a claim IN_REVIEW -> APPROVED -> PAID with distinct adjuster and
    finance identities (segregation of duties). Returns the paid Claim."""
    adj = make_claims_adjuster_headers(adjuster_id)
    fin = make_finance_officer_headers(finance_id)
    _data(api_client.triage_claim(claim_id, adj), "triage_claim")
    _data(api_client.approve_claim(claim_id, adj), "approve_claim")
    return _data(api_client.payout_claim(claim_id, fin), "payout_claim")


def setup_paid_claim(account, policy, adjuster_id, finance_id,
                     claim_amount_cents=150000):
    """File a claim on `policy` and pay it (distinct adjuster/finance).
    Returns the PAID claim. Claims the claims_free_flag for the account."""
    claim = submit_claim(account, policy, claim_amount_cents)
    assert claim["status"] == "SUBMITTED", (
        f"Setup expected SUBMITTED claim (needs adjuster flow), got {claim['status']}"
    )
    return pay_claim(claim["id"], adjuster_id, finance_id)


# --- Tier 7: referrals --------------------------------------------------------

def setup_referred_quote(account, raw_description, selected_lines,
                         signal_severities, uw_answers,
                         exposure_units=10):
    """Inject PENDING risk signals then create a quote routed to REFERRED.
    Returns (quote, referral)."""
    for sev in signal_severities:
        _data(
            api_client.create_risk_signal(
                create_risk_signal_payload(
                    business_account_id=account["id"],
                    signal_type="LOSS_HISTORY",
                    severity=sev,
                    detail=_uniq("sig"),
                ), ADMIN,
            ), "create_risk_signal",
        )
    ph = make_policyholder_headers(account["id"])
    quote = _data(
        api_client.create_quote(
            create_quote_payload(
                business_account_id=account["id"],
                raw_description=raw_description,
                selected_lines=selected_lines,
                exposure_units=exposure_units,
                uw_answers=uw_answers,
            ), ph,
        ), "create_quote",
    )
    assert quote.get("status") == "REFERRED", (
        f"Setup expected REFERRED, got {quote.get('status')} "
        f"(risk_score={quote.get('risk_score')})"
    )
    uw = make_underwriter_headers("setup-uw")
    refs = _data(api_client.get_quote_referral(quote["id"], uw),
                 "get_quote_referral")
    assert isinstance(refs, list) and len(refs) == 1, (
        f"Setup expected exactly one referral, got {refs}"
    )
    return quote, refs[0]


def approve_referral(referral_id, underwriter_id):
    uw = make_underwriter_headers(underwriter_id)
    return _data(api_client.approve_referral(referral_id, uw), "approve_referral")


def get_quote(quote_id, headers=None):
    return _data(api_client.get_quote(quote_id, headers or ADMIN), "get_quote")


def get_account(account_id, headers=None):
    return _data(
        api_client.get_business_account(account_id, headers or ADMIN),
        "get_business_account",
    )


def list_policy_certificates(policy_id, headers=None):
    return _data(
        api_client.list_policy_certificates(policy_id, headers or ADMIN),
        "list_policy_certificates",
    )


def list_non_renewal_notices(policy_id, headers=None):
    hdrs = headers or make_compliance_officer_headers("setup-co")
    return _data(api_client.list_non_renewal_notices(policy_id, hdrs),
                 "list_non_renewal_notices")
