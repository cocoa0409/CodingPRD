"""Composite setup helpers.

Every helper builds its state from scratch through the public API, because each
test starts against an empty service. All setup calls go through the lenient
`get_success_data` validator so a broken precondition reads as a setup failure.
"""
from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    APPROVAL_TIERS,
    CLOCK_EPOCH,
    CORE_VOLUME_TIERS,
    PRODUCT_CORE,
    PRODUCT_SERVICE,
    PRODUCT_SUPPORT,
    PRODUCT_USAGE,
)
from .factories import (
    account_payload,
    approval_tier_payload,
    bundle_rule_payload,
    competitive_exception_payload,
    credit_decision_payload,
    delegation_grant_payload,
    desk_policy_payload,
    exception_decision_payload,
    exception_revoke_payload,
    nonstandard_term_payload,
    order_form_payload,
    product_payload,
    quote_line_patch_payload,
    quote_line_payload,
    quote_patch_payload,
    quote_payload,
    renegotiate_payload,
    revrec_assessment_payload,
    revrec_decision_payload,
    reverse_booking_payload,
    signature_payload,
    step_decision_payload,
    term_review_payload,
    volume_tier_payload,
)
from .test_users import (
    TEST_USERS,
    USER_IDS,
    make_cfo_headers,
    make_deal_desk_analyst_headers,
    make_legal_counsel_headers,
    make_platform_admin_headers,
    make_revenue_accountant_headers,
    make_sales_director_headers,
    make_sales_rep_headers,
    make_vp_sales_headers,
)

ADMIN = TEST_USERS["admin_headers"]
REP = TEST_USERS["rep_headers"]
ANALYST = TEST_USERS["analyst_headers"]
DIRECTOR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
CFO = TEST_USERS["cfo_headers"]
LEGAL = TEST_USERS["legal_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

# Headers for the approver that owns each approval matrix role.
ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    "DealDeskAnalyst": ANALYST,
    "SalesDirector": DIRECTOR,
    "VPSales": VP,
    "CFO": CFO,
}


# ---------------------------------------------------------------------------
# Clock and sweeps
# ---------------------------------------------------------------------------

def set_clock(api: ApiClient, to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Advance the logical clock to an exact instant."""
    return get_success_data(api.set_clock(to_iso8601, headers or ADMIN))


def run_expiry_sweep(api: ApiClient, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.run_expiry_sweep(headers or ADMIN))


def run_sla_sweep(api: ApiClient, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.run_sla_escalation_sweep(headers or ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 — the configured desk: policy, matrix, catalogue, bands, account
# ---------------------------------------------------------------------------

def create_desk_policy_with_matrix(
    api: ApiClient,
    activate: bool = True,
    tiers: Sequence[dict] = APPROVAL_TIERS,
    headers: Optional[dict] = None,
    **policy_overrides,
) -> dict:
    """Create a DRAFT policy revision plus its approval matrix, optionally activating it.

    Returns {"policy": <policy>, "tiers": [<tier>, ...]}.
    """
    headers = headers or ADMIN
    policy = get_success_data(api.create_desk_policy(desk_policy_payload(**policy_overrides), headers))
    created_tiers = []
    for tier in tiers:
        created_tiers.append(
            get_success_data(
                api.create_approval_tier(
                    approval_tier_payload(policy["id"], tier["tier_level"], **{
                        key: value for key, value in tier.items() if key != "tier_level"
                    }),
                    headers,
                )
            )
        )
    if activate:
        policy = get_success_data(api.activate_desk_policy(policy["id"], headers))
    return {"policy": policy, "tiers": created_tiers}


def setup_base_config(
    api: ApiClient,
    clock: Optional[str] = CLOCK_EPOCH,
    account_overrides: Optional[dict] = None,
    **policy_overrides,
) -> dict:
    """The configured desk every scenario starts from.

    Sets the logical clock, creates and activates one desk policy revision with
    its four approval matrix bands, creates the four catalogue products, the
    three Core Platform quantity bands and the Core -> Support bundle rule, and
    creates one customer account.

    Returns a dict with keys: policy, tiers, core, support, service, usage,
    volume_tiers, bundle_rule, account.
    """
    if clock is not None:
        set_clock(api, clock)
    configured = create_desk_policy_with_matrix(api, activate=True, **policy_overrides)

    core = get_success_data(api.create_product(product_payload(**PRODUCT_CORE), ADMIN))
    support = get_success_data(api.create_product(product_payload(**PRODUCT_SUPPORT), ADMIN))
    service = get_success_data(api.create_product(product_payload(**PRODUCT_SERVICE), ADMIN))
    usage = get_success_data(api.create_product(product_payload(**PRODUCT_USAGE), ADMIN))

    volume_tiers = []
    for band in CORE_VOLUME_TIERS:
        volume_tiers.append(
            get_success_data(
                api.create_volume_tier(
                    volume_tier_payload(
                        core["id"],
                        band["tier_level"],
                        band["min_quantity"],
                        band.get("max_quantity"),
                        band["tier_discount_pct"],
                    ),
                    ADMIN,
                )
            )
        )

    bundle_rule = get_success_data(
        api.create_bundle_rule(bundle_rule_payload(core["id"], support["id"]), ADMIN)
    )

    account = get_success_data(
        api.create_account(account_payload(**(account_overrides or {})), ANALYST)
    )

    return {
        "policy": configured["policy"],
        "tiers": configured["tiers"],
        "core": core,
        "support": support,
        "service": service,
        "usage": usage,
        "volume_tiers": volume_tiers,
        "bundle_rule": bundle_rule,
        "account": account,
    }


def create_account(api: ApiClient, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(api.create_account(account_payload(**overrides), headers or ANALYST))


def set_credit_status(
    api: ApiClient,
    account_id: str,
    credit_status: str,
    credit_note: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.create_credit_decision(
            account_id, credit_decision_payload(credit_status, credit_note), headers or CFO
        )
    )


def tier_for_level(base: dict, tier_level: int) -> dict:
    return next(tier for tier in base["tiers"] if tier["tier_level"] == tier_level)


# ---------------------------------------------------------------------------
# Tier 2 — quotes, lines, terms
# ---------------------------------------------------------------------------

def create_quote(
    api: ApiClient,
    account_id: str,
    term_months: int = 12,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_quote(
            quote_payload(account_id, term_months=term_months, **overrides), headers or REP
        )
    )


def read_quote(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_quote(quote_id, headers or REP))


def patch_quote(api: ApiClient, quote_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.update_quote(quote_id, quote_patch_payload(**overrides), headers or REP)
    )


def add_line(
    api: ApiClient,
    quote_id: str,
    product_id: str,
    quantity: int,
    requested_discount_pct: Optional[float] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.create_quote_line(
            quote_line_payload(quote_id, product_id, quantity, requested_discount_pct),
            headers or REP,
        )
    )


def patch_line(api: ApiClient, line_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.update_quote_line(line_id, quote_line_patch_payload(**overrides), headers or REP)
    )


def setup_quote_with_lines(
    api: ApiClient,
    base: dict,
    lines: Sequence[Tuple[str, int, float]],
    term_months: int = 12,
    headers: Optional[dict] = None,
    **quote_overrides,
) -> Tuple[dict, List[dict]]:
    """Create a DRAFT quote and add the given lines.

    `lines` is a sequence of (product key in `base`, quantity, requested discount).
    Returns (quote as last read, [line, ...]).
    """
    headers = headers or REP
    quote = create_quote(api, base["account"]["id"], term_months=term_months, headers=headers,
                         **quote_overrides)
    created = []
    for product_key, quantity, discount in lines:
        created.append(
            add_line(api, quote["id"], base[product_key]["id"], quantity, discount, headers)
        )
    return read_quote(api, quote["id"], headers), created


def setup_single_line_quote(
    api: ApiClient,
    base: dict,
    product_key: str,
    quantity: int,
    requested_discount_pct: float = 0.0,
    term_months: int = 12,
    headers: Optional[dict] = None,
    **quote_overrides,
) -> Tuple[dict, dict]:
    """One DRAFT quote carrying exactly one line. Returns (quote, line)."""
    quote, lines = setup_quote_with_lines(
        api, base, [(product_key, quantity, requested_discount_pct)],
        term_months=term_months, headers=headers, **quote_overrides,
    )
    return quote, lines[0]


def add_term(
    api: ApiClient,
    quote_id: str,
    term_category: str,
    requested_numeric_value: float,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_nonstandard_term(
            nonstandard_term_payload(quote_id, term_category, requested_numeric_value, **overrides),
            headers or REP,
        )
    )


def add_price_hold_term(
    api: ApiClient,
    quote_id: str,
    hold_product_id: str,
    hold_start_date: str,
    hold_end_date: str,
    requested_numeric_value: float = 24,
    headers: Optional[dict] = None,
    requested_text: Optional[str] = "Renewal price cap",
) -> dict:
    return add_term(
        api,
        quote_id,
        "PRICE_HOLD_RENEWAL",
        requested_numeric_value,
        headers=headers,
        requested_text=requested_text,
        hold_product_id=hold_product_id,
        hold_start_date=hold_start_date,
        hold_end_date=hold_end_date,
    )


def review_term(
    api: ApiClient,
    term_id: str,
    decision: str,
    headers: Optional[dict] = None,
    reviewer_note: Optional[str] = None,
) -> dict:
    default = CFO if decision == "COSIGN" else LEGAL
    return get_success_data(
        api.review_nonstandard_term(
            term_id, term_review_payload(decision, reviewer_note), headers or default
        )
    )


def list_terms(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> List[dict]:
    response = api.list_quote_nonstandard_terms(quote_id, headers or REP)
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 3 — exceptions and revenue recognition
# ---------------------------------------------------------------------------

def file_exception(api: ApiClient, quote_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    return get_success_data(
        api.create_competitive_exception(
            competitive_exception_payload(quote_id, **overrides), headers or REP
        )
    )


def decide_exception(
    api: ApiClient,
    exception_id: str,
    decision: str,
    headers: Optional[dict] = None,
    decision_note: Optional[str] = None,
) -> dict:
    return get_success_data(
        api.decide_competitive_exception(
            exception_id, exception_decision_payload(decision, decision_note), headers or ANALYST
        )
    )


def revoke_exception(
    api: ApiClient,
    exception_id: str,
    headers: Optional[dict] = None,
    decision_note: Optional[str] = None,
) -> dict:
    return get_success_data(
        api.revoke_competitive_exception(
            exception_id, exception_revoke_payload(decision_note), headers or CFO
        )
    )


def setup_accepted_exception(
    api: ApiClient,
    quote_id: str,
    author_headers: Optional[dict] = None,
    decider_headers: Optional[dict] = None,
) -> dict:
    """File an exception as the rep and accept it as a different user."""
    exception = file_exception(api, quote_id, author_headers or REP)
    return decide_exception(api, exception["id"], "ACCEPT", decider_headers or ANALYST)


def open_revrec(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api.create_revrec_assessment(revrec_assessment_payload(quote_id), headers or ACCOUNTANT)
    )


def assess_revrec(
    api: ApiClient,
    assessment_id: str,
    decision: str = "CLEAR",
    headers: Optional[dict] = None,
    assessment_note: Optional[str] = None,
) -> dict:
    return get_success_data(
        api.assess_revrec_assessment(
            assessment_id, revrec_decision_payload(decision, assessment_note), headers or ACCOUNTANT
        )
    )


def setup_cleared_revrec(api: ApiClient, quote_id: str) -> dict:
    """Open an assessment on the quote and clear it."""
    assessment = open_revrec(api, quote_id)
    return assess_revrec(api, assessment["id"], "CLEAR")


# ---------------------------------------------------------------------------
# Tier 4 — submission, the approval request and its steps
# ---------------------------------------------------------------------------

def submit_quote(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.submit_quote(quote_id, headers or REP))


def approval_requests_of(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> List[dict]:
    return get_success_data(api.list_quote_approval_requests(quote_id, headers or REP))


def latest_approval_request(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> dict:
    requests = approval_requests_of(api, quote_id, headers)
    assert requests, f"quote {quote_id} has no approval request"
    return requests[-1]


def steps_of_request(api: ApiClient, request_id: str, headers: Optional[dict] = None) -> List[dict]:
    response = api.list_approval_steps(headers or REP, params={"approval_request_id": request_id})
    return get_success_data(response)


def pending_step_of_request(
    api: ApiClient, request_id: str, headers: Optional[dict] = None
) -> Optional[dict]:
    for step in steps_of_request(api, request_id, headers):
        if step["decision"] == "PENDING":
            return step
    return None


def read_step(api: ApiClient, step_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_approval_step(step_id, headers or REP))


def decide_step(
    api: ApiClient,
    step_id: str,
    decision: str,
    headers: Optional[dict] = None,
    decision_note: Optional[str] = None,
) -> dict:
    """Decide a step. With no headers, the approver who owns the step's role acts."""
    if headers is None:
        step = read_step(api, step_id)
        headers = ROLE_HEADERS[step["assigned_role"]]
    return get_success_data(
        api.decide_approval_step(step_id, step_decision_payload(decision, decision_note), headers)
    )


def approve_pending_steps(api: ApiClient, quote_id: str, max_rounds: int = 6) -> dict:
    """Approve every step the request raises until the discount track clears.

    Each step is decided by the approver holding the step's own assigned_role.
    Returns the approval request as it then stands.
    """
    request = latest_approval_request(api, quote_id)
    for _ in range(max_rounds):
        step = pending_step_of_request(api, request["id"])
        if step is None:
            break
        decide_step(api, step["id"], "APPROVE")
        request = latest_approval_request(api, quote_id)
    return request


def setup_submitted_quote(
    api: ApiClient,
    base: dict,
    lines: Sequence[Tuple[str, int, float]],
    term_months: int = 12,
    headers: Optional[dict] = None,
    **quote_overrides,
) -> dict:
    """Build a quote, submit it, and return the whole submitted scenario.

    Returns {"quote": ..., "lines": [...], "request": ..., "step": <first pending step or None>}.
    """
    headers = headers or REP
    quote, lines_created = setup_quote_with_lines(
        api, base, lines, term_months=term_months, headers=headers, **quote_overrides
    )
    quote = submit_quote(api, quote["id"], headers)
    request = latest_approval_request(api, quote["id"])
    return {
        "quote": quote,
        "lines": lines_created,
        "request": request,
        "step": pending_step_of_request(api, request["id"]),
    }


def setup_approved_quote(
    api: ApiClient,
    base: dict,
    lines: Sequence[Tuple[str, int, float]] = (("support", 10, 0.0),),
    term_months: int = 12,
    headers: Optional[dict] = None,
    **quote_overrides,
) -> dict:
    """Submit a quote and drive it all the way to APPROVED.

    A quote whose final blended discount is zero is approved by the submission
    itself; anything discounted is walked through its approval steps.
    """
    scenario = setup_submitted_quote(
        api, base, lines, term_months=term_months, headers=headers, **quote_overrides
    )
    if scenario["step"] is not None:
        approve_pending_steps(api, scenario["quote"]["id"])
    scenario["quote"] = read_quote(api, scenario["quote"]["id"], headers or REP)
    scenario["request"] = latest_approval_request(api, scenario["quote"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Delegation grants
# ---------------------------------------------------------------------------

def create_grant(
    api: ApiClient,
    grantee_user_id: str,
    tier_level: int,
    max_discount_pct: float,
    starts_at: str,
    ends_at: str,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.create_delegation_grant(
            delegation_grant_payload(
                grantee_user_id, tier_level, max_discount_pct, starts_at, ends_at
            ),
            headers or DIRECTOR,
        )
    )


def revoke_grant(api: ApiClient, grant_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.revoke_delegation_grant(grant_id, headers or DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 5 — order forms, signature routing, booking and reversal
# ---------------------------------------------------------------------------

def generate_order_form(
    api: ApiClient,
    quote_id: str,
    expected_quote_version: Optional[int] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Generate an order form, defaulting the expected version to the quote's current one."""
    headers = headers or REP
    if expected_quote_version is None:
        expected_quote_version = read_quote(api, quote_id, headers)["version"]
    return get_success_data(
        api.create_order_form(
            order_form_payload(quote_id, expected_quote_version, **overrides), headers
        )
    )


def send_order_form(api: ApiClient, form_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.send_order_form(form_id, headers or REP))


def record_signature(
    api: ApiClient,
    form_id: str,
    outcome: str = "SIGNED",
    signed_by_name: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.record_order_form_signature(
            form_id, signature_payload(outcome, signed_by_name), headers or ANALYST
        )
    )


def book_order_form(api: ApiClient, form_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.book_order_form(form_id, headers or ANALYST))


def reverse_booking(
    api: ApiClient,
    form_id: str,
    reversal_reason: str = "Booked against the wrong entity.",
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api.reverse_order_form_booking(
            form_id, reverse_booking_payload(reversal_reason), headers or CFO
        )
    )


def setup_signed_order_form(
    api: ApiClient,
    base: dict,
    lines: Sequence[Tuple[str, int, float]] = (("support", 10, 0.0),),
    term_months: int = 12,
    headers: Optional[dict] = None,
    **quote_overrides,
) -> dict:
    """Approved quote -> generated form -> sent -> signed.

    Returns {"quote": ..., "lines": [...], "form": ..., "request": ...}.
    """
    scenario = setup_approved_quote(
        api, base, lines, term_months=term_months, headers=headers, **quote_overrides
    )
    form = generate_order_form(api, scenario["quote"]["id"], headers=headers or REP)
    send_order_form(api, form["id"], headers or REP)
    form = record_signature(api, form["id"], "SIGNED", "Dana Signer")
    scenario["form"] = form
    return scenario


def setup_booked_order_form(
    api: ApiClient,
    base: dict,
    lines: Sequence[Tuple[str, int, float]] = (("support", 10, 0.0),),
    term_months: int = 12,
    headers: Optional[dict] = None,
    **quote_overrides,
) -> dict:
    """Approved quote -> generated -> sent -> signed -> booked."""
    scenario = setup_signed_order_form(
        api, base, lines, term_months=term_months, headers=headers, **quote_overrides
    )
    scenario["form"] = book_order_form(api, scenario["form"]["id"])
    scenario["quote"] = read_quote(api, scenario["quote"]["id"], headers or REP)
    return scenario


def read_account(api: ApiClient, account_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_account(account_id, headers or ANALYST))


def read_order_form(api: ApiClient, form_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_order_form(form_id, headers or REP))


def read_exception(api: ApiClient, quote_id: str, exception_id: str,
                   headers: Optional[dict] = None) -> dict:
    for exception in get_success_data(
        api.list_quote_competitive_exceptions(quote_id, headers or REP)
    ):
        if exception["id"] == exception_id:
            return exception
    raise AssertionError(f"exception {exception_id} not listed on quote {quote_id}")


def read_term(api: ApiClient, quote_id: str, term_id: str, headers: Optional[dict] = None) -> dict:
    for term in list_terms(api, quote_id, headers):
        if term["id"] == term_id:
            return term
    raise AssertionError(f"term {term_id} not listed on quote {quote_id}")


def read_revrec(api: ApiClient, quote_id: str, assessment_id: str,
                headers: Optional[dict] = None) -> dict:
    for assessment in get_success_data(
        api.list_quote_revrec_assessments(quote_id, headers or REP)
    ):
        if assessment["id"] == assessment_id:
            return assessment
    raise AssertionError(f"assessment {assessment_id} not listed on quote {quote_id}")


def read_pricing_preview(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.get_pricing_preview(quote_id, headers or REP))


def renegotiate(
    api: ApiClient,
    quote_id: str,
    expected_quote_version: int,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api.renegotiate_quote(
            quote_id, renegotiate_payload(expected_quote_version, **overrides), headers or REP
        )
    )


def reopen_quote(api: ApiClient, quote_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api.reopen_quote(quote_id, headers or REP))
