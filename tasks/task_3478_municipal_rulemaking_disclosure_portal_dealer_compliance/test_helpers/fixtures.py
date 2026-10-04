"""Composite setup helpers that walk the public API to a wanted state.

Every test starts against an empty deployment (the harness restarts the server
before each test), so each test builds the world it needs through the API.
These helpers encapsulate the multi-step walks; setup calls use the lenient
success reader, so a failure inside a fixture reports as a setup failure.

Time discipline: the logical clock starts at 2026-09-01T00:00:00Z (PRD section
2.4) and only moves when a fixture or test moves it. Fixtures that need a
specific "now" take an ``anchor`` parameter naming the instant the clock is
expected to be at when the fixture runs, and advance from there with explicit
clock sets. Day arithmetic is exact ISO 8601 UTC day arithmetic, matching the
contract.

Identity threading: IssuerRep and DealerRep calls are ownership-gated on the
organization id, so the fixtures that make them build headers from the actual
Organization.id via the make_*_headers builders - never from the shared
fallback header sets.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_START, PASS_SCORES, REQUIRED_SERIES
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_dealer_rep_headers,
    make_issuer_rep_headers,
)

SYSTEM_ADMIN_HEADERS = TEST_USERS["system_admin_headers"]
OFFICER_HEADERS = TEST_USERS["rulemaking_officer_headers"]
REGULATOR_HEADERS = TEST_USERS["regulator_headers"]
PORTAL_OPERATOR_HEADERS = TEST_USERS["portal_operator_headers"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_officer_headers"]
EXAM_ADMIN_HEADERS = TEST_USERS["exam_admin_headers"]
LICENSING_HEADERS = TEST_USERS["licensing_officer_headers"]
PUBLIC_READER_HEADERS = TEST_USERS["public_reader_headers"]


# --- Instant arithmetic ---------------------------------------------------------

def _parse(iso: str) -> datetime:
    """Parse an ISO 8601 UTC instant in either spelling a PRD-faithful server may
    emit: whole-second (``...T00:00:00Z``) or three-fractional-digit
    (``...T00:00:00.000Z``) — the same two spellings ``assert_instant`` treats as
    equal via ``canonical_instant``."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(iso, fmt)
        except ValueError:
            continue
    raise ValueError(f"not an ISO 8601 UTC instant: {iso!r}")


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(iso: str, days: int) -> str:
    """Exact UTC day arithmetic on an instant."""
    return _fmt(_parse(iso) + timedelta(days=days))


def sub_seconds(iso: str, seconds: int) -> str:
    return _fmt(_parse(iso) - timedelta(seconds=seconds))


# --- Tier 1: primitives and single transitions -------------------------------------

def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Advance the logical clock and run the epoch pass; returns the write's data."""
    return get_success_data(api.set_clock(f.set_clock_payload(to_iso8601), SYSTEM_ADMIN_HEADERS))


def create_organization(api: ApiClient, org_type: str = "BROKER_DEALER", **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_organization(f.create_organization_payload(org_type=org_type, **overrides), PORTAL_OPERATOR_HEADERS)
    )


def create_dealer_org(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_organization(api, org_type="BROKER_DEALER", **overrides)


def create_advisor_org(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_organization(api, org_type="MUNICIPAL_ADVISOR", **overrides)


def create_issuer_org(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_organization(api, org_type="ISSUER", **overrides)


def suspend_organization(api: ApiClient, org_id: str, reason: str = "regulatory action") -> Dict[str, Any]:
    return get_success_data(
        api.suspend_organization(org_id, f.suspend_organization_payload(reason), COMPLIANCE_HEADERS)
    )


def read_organization(api: ApiClient, org_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_organization(org_id, headers or COMPLIANCE_HEADERS))


def create_rule_proposal(
    api: ApiClient,
    officer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A fresh proposal in DRAFT with comment_round 0."""
    return get_success_data(
        api.create_rule_proposal(f.create_rule_proposal_payload(**overrides), officer_headers or OFFICER_HEADERS)
    )


def open_comment_period(
    api: ApiClient,
    proposal_id: str,
    days: int = 21,
    expedited: Optional[bool] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.open_comment_period(
            proposal_id, f.open_comment_period_payload(days, expedited), officer_headers or OFFICER_HEADERS
        )
    )


def submit_proposal(
    api: ApiClient, proposal_id: str, officer_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.submit_for_approval(proposal_id, officer_headers or OFFICER_HEADERS))


def decide_proposal(
    api: ApiClient,
    proposal_id: str,
    decision: str = "APPROVE",
    reason: Optional[str] = None,
    regulator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_proposal(proposal_id, f.decide_proposal_payload(decision, reason), regulator_headers or REGULATOR_HEADERS)
    )


def read_proposal(api: ApiClient, proposal_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_rule_proposal(proposal_id, headers or OFFICER_HEADERS))


def create_comment_letter(
    api: ApiClient, proposal_id: str, reader_headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """A letter in RECEIVED on an open proposal whose window is live."""
    return get_success_data(
        api.create_comment_letter(proposal_id, f.create_comment_letter_payload(**overrides), reader_headers or PUBLIC_READER_HEADERS)
    )


def moderate_letter(
    api: ApiClient, letter_id: str, action: str = "PUBLISH", reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.moderate_comment_letter(letter_id, f.moderate_comment_letter_payload(action, reason), PORTAL_OPERATOR_HEADERS)
    )


def create_professional(
    api: ApiClient,
    employer_org_id: str,
    professional_class: str = "MUNICIPAL_DEALER_REP",
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_professional(
            f.create_professional_payload(employer_org_id, professional_class=professional_class, **overrides),
            EXAM_ADMIN_HEADERS,
        )
    )


def read_professional(api: ApiClient, professional_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_professional(professional_id, headers or EXAM_ADMIN_HEADERS))


def record_exam(
    api: ApiClient, professional_id: str, series_code: str = "MSRB_52", score: int = 80
) -> Dict[str, Any]:
    return get_success_data(
        api.create_exam_attempt(f.create_exam_attempt_payload(professional_id, series_code, score), EXAM_ADMIN_HEADERS)
    )


def record_ce_credits(
    api: ApiClient, professional_id: str, credits_total: float = 12, ethics_credits: float = 2
) -> Dict[str, Any]:
    return get_success_data(
        api.record_ce_credits(professional_id, f.ce_credits_payload(credits_total, ethics_credits), EXAM_ADMIN_HEADERS)
    )


def set_standing(
    api: ApiClient,
    professional_id: str,
    standing: str = "SUSPENDED",
    reason: Optional[str] = None,
    officer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.set_professional_standing(
            professional_id, f.set_standing_payload(standing, reason), officer_headers or COMPLIANCE_HEADERS
        )
    )


def create_trade(
    api: ApiClient,
    dealer_org_id: str,
    executed_at: str = CLOCK_START,
    **overrides: Any,
) -> Dict[str, Any]:
    """Report a trade for a dealer firm. Identity-threaded: the DealerRep
    headers are built from the firm id (X-User-ID == dealer_org_id). The
    default execution instant equals the fresh-deployment clock, so the report
    is timely and needs no clock move."""
    return get_success_data(
        api.create_trade_report(
            f.create_trade_report_payload(dealer_org_id, executed_at=executed_at, **overrides),
            make_dealer_rep_headers(dealer_org_id),
        )
    )


def cancel_trade(api: ApiClient, trade_id: str, dealer_org_id: str) -> Dict[str, Any]:
    return get_success_data(api.cancel_trade_report(trade_id, make_dealer_rep_headers(dealer_org_id)))


def read_trade(api: ApiClient, trade_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_trade_report(trade_id, headers or PORTAL_OPERATOR_HEADERS))


def create_disclosure(
    api: ApiClient, issuer_org_id: str, **overrides: Any
) -> Dict[str, Any]:
    """File a disclosure for an issuer/obligated-person org. Identity-threaded:
    IssuerRep headers carry the org id (X-User-ID == issuer_org_id)."""
    return get_success_data(
        api.create_disclosure_submission(
            f.create_disclosure_submission_payload(issuer_org_id, **overrides),
            make_issuer_rep_headers(issuer_org_id),
        )
    )


def review_submission(
    api: ApiClient, submission_id: str, outcome: str = "PUBLISH", deficiency_reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.review_submission(
            submission_id, f.review_submission_payload(outcome, deficiency_reason), PORTAL_OPERATOR_HEADERS
        )
    )


def create_subscription(
    api: ApiClient,
    licensee_org_id: str,
    product_code: str = "TRADE_REALTIME",
    subscriber_principal: str = "sub-1",
    license_scope: str = "INTERNAL",
    seats: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_data_subscription(
            f.create_data_subscription_payload(
                licensee_org_id,
                product_code=product_code,
                subscriber_principal=subscriber_principal,
                license_scope=license_scope,
                seats=seats,
                **overrides,
            ),
            LICENSING_HEADERS,
        )
    )


def transition_subscription(api: ApiClient, subscription_id: str, to_state: str = "ACTIVE") -> Dict[str, Any]:
    return get_success_data(
        api.transition_data_subscription(subscription_id, f.transition_subscription_payload(to_state), LICENSING_HEADERS)
    )


def read_subscription(api: ApiClient, subscription_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_data_subscription(subscription_id, headers or LICENSING_HEADERS))


def create_referral(
    api: ApiClient,
    rule_code: str,
    subject_org_id: Optional[str] = None,
    subject_professional_id: Optional[str] = None,
    creator_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_enforcement_referral(
            f.create_enforcement_referral_payload(
                rule_code, subject_org_id=subject_org_id, subject_professional_id=subject_professional_id, **overrides
            ),
            creator_headers or COMPLIANCE_HEADERS,
        )
    )


def advance_referral(
    api: ApiClient,
    referral_id: str,
    to_state: str = "REFERRED",
    officer_headers: Optional[Dict[str, str]] = None,
    guidance_text: Optional[str] = None,
    closure_notes: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_enforcement_referral(
            referral_id,
            f.advance_referral_payload(to_state, guidance_text=guidance_text, closure_notes=closure_notes),
            officer_headers or COMPLIANCE_HEADERS,
        )
    )


def read_referral(api: ApiClient, referral_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_enforcement_referral(referral_id, headers or COMPLIANCE_HEADERS))


def create_solicitation(api: ApiClient, advisor_org_id: str, **overrides: Any) -> Dict[str, Any]:
    """Log a solicitation for an advisor firm. Identity-threaded DealerRep."""
    return get_success_data(
        api.create_solicitation_record(
            f.create_solicitation_record_payload(advisor_org_id, **overrides),
            make_dealer_rep_headers(advisor_org_id),
        )
    )


# --- Tier 2: hierarchies ---------------------------------------------------------

def create_org_with_professional(
    api: ApiClient,
    org_type: str = "BROKER_DEALER",
    professional_class: str = "MUNICIPAL_DEALER_REP",
    **org_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An ACTIVE org with one registered professional (UNQUALIFIED x ACTIVE)."""
    org = create_organization(api, org_type=org_type, **org_overrides)
    prof = create_professional(api, org["id"], professional_class=professional_class)
    return org, prof


def create_qualified_professional(
    api: ApiClient,
    org_type: str = "BROKER_DEALER",
    professional_class: str = "MUNICIPAL_DEALER_REP",
    org: Optional[Dict[str, Any]] = None,
    pass_score_margin: int = 5,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An org plus a professional who has PASSED every required series of the
    class, leaving them QUALIFIED with standing ACTIVE and fresh CE anchors at
    the current logical time. Different series may be sat on the same day: the
    retake exclusion is per (professional, series) pair."""
    if org is None:
        org = create_organization(api, org_type=org_type)
    prof = create_professional(api, org["id"], professional_class=professional_class)
    for series in REQUIRED_SERIES[professional_class]:
        score = min(100, PASS_SCORES[series] + pass_score_margin)
        record_exam(api, prof["id"], series_code=series, score=score)
    return org, read_professional(api, prof["id"])


# --- Tier 3: proposal and referral lifecycles --------------------------------------

def create_open_for_comment_proposal(
    api: ApiClient,
    days: int = 21,
    expedited: Optional[bool] = None,
    officer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A proposal in OPEN_FOR_COMMENT; the clock is not moved, so the window
    opens at the current logical time and stays live for `days` days."""
    proposal = create_rule_proposal(api, officer_headers=officer_headers, **overrides)
    return open_comment_period(api, proposal["id"], days=days, expedited=expedited, officer_headers=officer_headers)


def create_pending_approval_proposal(
    api: ApiClient,
    days: int = 21,
    expedited: Optional[bool] = None,
    anchor: str = CLOCK_START,
    officer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A proposal in PENDING_APPROVAL. Assumes the clock is at `anchor` when
    called: opens the window there, advances exactly `days` days to the window
    end (submission is legal at the end instant), and submits."""
    proposal = create_open_for_comment_proposal(
        api, days=days, expedited=expedited, officer_headers=officer_headers, **overrides
    )
    set_clock(api, add_days(anchor, days))
    return submit_proposal(api, proposal["id"], officer_headers=officer_headers)


def create_approved_proposal(
    api: ApiClient,
    days: int = 21,
    expedited: Optional[bool] = None,
    anchor: str = CLOCK_START,
    officer_headers: Optional[Dict[str, str]] = None,
    regulator_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A proposal in APPROVED. The default officer and regulator identities
    differ, honouring segregation of duties. approval_at is the window-end
    instant (anchor + days)."""
    proposal = create_pending_approval_proposal(
        api, days=days, expedited=expedited, anchor=anchor, officer_headers=officer_headers, **overrides
    )
    return decide_proposal(api, proposal["id"], "APPROVE", regulator_headers=regulator_headers)


def create_disapproved_proposal(
    api: ApiClient,
    reason: str = "needs rework",
    anchor: str = CLOCK_START,
    **overrides: Any,
) -> Dict[str, Any]:
    """A proposal in DISAPPROVED, ready for the revision cycle."""
    proposal = create_pending_approval_proposal(api, anchor=anchor, **overrides)
    return decide_proposal(api, proposal["id"], "DISAPPROVE", reason=reason)


def create_effective_proposal(
    api: ApiClient,
    days: int = 21,
    expedited: bool = False,
    anchor: str = CLOCK_START,
    **overrides: Any,
) -> Dict[str, Any]:
    """A proposal walked all the way to EFFECTIVE. Approved at anchor + days;
    the clock is then advanced to the computed effectiveness instant
    (approval + 30 days standard, + 10 days expedited) so the epoch pass
    effectuates it."""
    proposal = create_approved_proposal(api, days=days, expedited=expedited, anchor=anchor, **overrides)
    approval_at = add_days(anchor, days)
    delay = 10 if proposal.get("expedited") else 30
    set_clock(api, add_days(approval_at, delay))
    return read_proposal(api, proposal["id"])


def create_referred_referral(
    api: ApiClient,
    rule_code: Optional[str] = None,
    subject_org: Optional[Dict[str, Any]] = None,
    creator_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """An EFFECTIVE rule, a dealer subject org, and a referral in REFERRED
    created by the given officer. Returns (referral, rule, subject_org)."""
    rule = create_effective_proposal(api, expedited=True, rule_code=rule_code or f.create_rule_proposal_payload()["rule_code"])
    if subject_org is None:
        subject_org = create_dealer_org(api)
    referral = create_referral(
        api, rule["rule_code"], subject_org_id=subject_org["id"], creator_headers=creator_headers
    )
    referral = advance_referral(api, referral["id"], "REFERRED", officer_headers=creator_headers)
    return referral, rule, subject_org


# --- Tier 4: accumulation and threshold targeting -----------------------------------

def create_late_trade(
    api: ApiClient,
    dealer_org_id: str,
    clock_to: str = "2026-09-01T09:00:00Z",
    gap_seconds: int = 3600,
    set_clock_first: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """A late trade: reported `gap_seconds` after execution (default 3600 s,
    well past the 900-second limit). Advances the clock to `clock_to` first
    unless the caller already did."""
    if set_clock_first:
        set_clock(api, clock_to)
    return create_trade(
        api, dealer_org_id, executed_at=sub_seconds(clock_to, gap_seconds), **overrides
    )


def create_late_trades(
    api: ApiClient,
    dealer_org_id: str,
    count: int,
    clock_to: str = "2026-09-01T09:00:00Z",
    gap_seconds: int = 3600,
) -> List[Dict[str, Any]]:
    """`count` late trades reported at one instant; the clock is advanced once."""
    set_clock(api, clock_to)
    return [
        create_late_trade(
            api, dealer_org_id, clock_to=clock_to, gap_seconds=gap_seconds, set_clock_first=False
        )
        for _ in range(count)
    ]


def create_trades(
    api: ApiClient,
    dealer_org_id: str,
    specs: Sequence[Dict[str, Any]],
    clock_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Several trades from explicit per-trade overrides (e.g. par amounts),
    under one clock position if given."""
    if clock_to is not None:
        set_clock(api, clock_to)
    return [create_trade(api, dealer_org_id, **spec) for spec in specs]


def setup_org_at_watch(
    api: ApiClient,
    with_pending_subscription: bool = True,
    product_code: str = "TRADE_REALTIME",
    clock_to: str = "2026-09-01T09:00:00Z",
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """A dealer org driven to WATCH: five late trades inside the trailing
    window trip the threshold (boundary inclusive), and the CLEAR -> WATCH
    degradation rejects the org's PENDING subscription if one was created.
    Returns (org, subscription-or-None, trades)."""
    org = create_dealer_org(api)
    subscription = (
        create_subscription(api, org["id"], product_code=product_code)
        if with_pending_subscription
        else None
    )
    trades = create_late_trades(api, org["id"], 5, clock_to=clock_to)
    return org, subscription, trades


def setup_active_subscription(
    api: ApiClient,
    product_code: str = "TRADE_REALTIME",
    subscriber_principal: str = "sub-ok",
    license_scope: str = "INTERNAL",
    seats: int = 3,
    org_type: str = "BROKER_DEALER",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An org with a subscription already advanced to ACTIVE, ready for a
    licensed feed pull by `subscriber_principal`. Returns (org, subscription)."""
    org = create_organization(api, org_type=org_type)
    subscription = create_subscription(
        api,
        org["id"],
        product_code=product_code,
        subscriber_principal=subscriber_principal,
        license_scope=license_scope,
        seats=seats,
    )
    subscription = transition_subscription(api, subscription["id"], "ACTIVE")
    return org, subscription


# --- Tier 5: terminal states and scheduled transitions ------------------------------

def create_superseded_pair(
    api: ApiClient,
    rule_code_a: str = "G-100",
    rule_code_b: str = "G-101",
    anchor: str = CLOCK_START,
    days: int = 21,
    with_referral: bool = False,
    referral_creator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Rule A EFFECTIVE, then superseded by rule B reaching EFFECTIVE.

    A is a standard rulemaking approved at anchor+days (effective +30 days);
    B declares supersedes_proposal_id=A, opens an expedited window when the
    clock reaches A's effectiveness, and is approved for effectiveness 10 days
    after its own window closes. One final clock set lands B in EFFECTIVE and
    A in SUPERSEDED. With ``with_referral``, an OPEN referral citing A's
    rule_code is created beforehand so the cascade flags it.

    Returns {"rule_a", "rule_b", "referral"} (referral None unless requested).
    """
    rule_a = create_effective_proposal(api, days=days, expedited=False, anchor=anchor, rule_code=rule_code_a)
    referral = None
    if with_referral:
        subject = create_dealer_org(api)
        referral = create_referral(
            api, rule_a["rule_code"], subject_org_id=subject["id"], creator_headers=referral_creator_headers
        )
    a_effective_at = add_days(anchor, days + 30)
    rule_b = create_effective_proposal(
        api,
        days=days,
        expedited=True,
        anchor=a_effective_at,
        rule_code=rule_code_b,
        supersedes_proposal_id=rule_a["id"],
    )
    return {
        "rule_a": read_proposal(api, rule_a["id"]),
        "rule_b": rule_b,
        "referral": read_referral(api, referral["id"]) if referral else None,
    }


def create_ce_due_professional(
    api: ApiClient,
    professional_class: str = "MUNICIPAL_DEALER_REP",
    anchor: str = CLOCK_START,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A professional moved QUALIFIED -> CE_DUE by the epoch pass. Qualified at
    `anchor`; the clock is advanced to the cycle end (anchor + 365 days), the
    first instant at which the transition fires. Returns (org, professional)."""
    org, prof = create_qualified_professional(api, professional_class=professional_class)
    set_clock(api, add_days(anchor, 365))
    return org, read_professional(api, prof["id"])


def create_lapsed_professional(
    api: ApiClient,
    professional_class: str = "MUNICIPAL_DEALER_REP",
    anchor: str = CLOCK_START,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A professional moved through CE_DUE to LAPSED: the clock passes the
    grace end (cycle end + 60 days) in one set; the pinned epoch order applies
    both transitions in the same pass. Returns (org, professional)."""
    org, prof = create_qualified_professional(api, professional_class=professional_class)
    set_clock(api, add_days(anchor, 365 + 60))
    return org, read_professional(api, prof["id"])


def create_closed_referral(
    api: ApiClient,
    closer_headers: Optional[Dict[str, str]] = None,
    to_state: str = "CLOSED_NO_ACTION",
    **kwargs: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A referral closed by a DIFFERENT officer than its creator (segregation
    of duties): the creator uses the shared compliance-officer headers, the
    closer defaults to the alternate identity."""
    referral, rule, subject_org = create_referred_referral(api, **kwargs)
    closer = closer_headers or make_compliance_officer_headers("co-2")
    guidance = "Published interpretation guidance." if to_state == "CLOSED_ACTION_TAKEN" else None
    referral = advance_referral(
        api, referral["id"], to_state, officer_headers=closer, guidance_text=guidance, closure_notes="closed"
    )
    return referral, rule, subject_org
