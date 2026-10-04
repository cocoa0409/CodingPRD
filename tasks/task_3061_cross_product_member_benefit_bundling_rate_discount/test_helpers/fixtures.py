"""Composite setup helpers.

Each fixture walks the API through the multi-step preamble a group of tests
shares, so tests can spend their body on assertions rather than on plumbing.
Every helper builds its preconditions from scratch; the runner restarts the
server before each test, so nothing is carried over.

Members are the only entity-backed role, so every ownership-guarded call uses
`make_member_headers(member["id"])` rather than the shared role constant.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    book_coaching_session_payload,
    create_cross_sell_check_payload,
    create_deposit_enrollment_payload,
    create_deposit_payload,
    create_entitlement_payload,
    create_holding_payload,
    create_loan_account_payload,
    create_member_payload,
    create_rule_payload,
    rewards_adjust_payload,
    unique_suffix,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["platform_admin_headers"]
BENEFITS = TEST_USERS["benefits_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


def _data(response, what):
    """Lenient extraction so a setup failure reads as 'Setup failed: <what>'."""
    try:
        return get_success_data(response)
    except Exception as exc:  # pragma: no cover - setup diagnostics path
        raise AssertionError(
            f"Setup failed: {what} returned {response.status_code}: {response.text[:500]}"
        ) from exc


# =========================================================================
# Tier 0 — clock and identity
# =========================================================================

def set_clock(instant: str = C.DEFAULT_CLOCK):
    """Advance the logical clock to a supplied instant."""
    return _data(api_client.set_current_utc({"current_utc": instant}, ADMIN), "set logical clock")


def register_member(**overrides):
    """Register a member in PROSPECT standing. Returns the member object."""
    resp = api_client.create_member(create_member_payload(**overrides), TEST_USERS["anonymous_headers"])
    return _data(resp, "register member")


def register_member_with_headers(**overrides):
    """Register a member and also return the member-scoped auth headers."""
    member = register_member(**overrides)
    return member, make_member_headers(member["id"])


def open_holding(member_id, product_line, balance_cents=0, **overrides):
    payload = create_holding_payload(member_id, product_line=product_line,
                                     balance_cents=balance_cents, **overrides)
    return _data(api_client.create_holding(payload, ADMIN), f"open {product_line} holding")


def adopt(member_id, holding_id):
    return _data(api_client.adopt_holding(holding_id, make_member_headers(member_id)),
                 "adopt holding")


# =========================================================================
# Tier 1 — state progression shortcuts
# =========================================================================

def create_adopted_holding(member_id, product_line, balance_cents=0):
    """Open a holding and adopt it. Returns the ADOPTED holding."""
    holding = open_holding(member_id, product_line, balance_cents)
    return adopt(member_id, holding["id"])


def create_member_with_adopted_holdings(lines, balances=None):
    """Register a member, open and adopt one holding per line.

    Returns (member, {line: holding}).
    """
    balances = balances or {}
    member = register_member()
    holdings = {}
    for line in lines:
        holdings[line] = create_adopted_holding(member["id"], line, balances.get(line, 0))
    member = fetch_member(member["id"])
    return member, holdings


def create_rule(rule_code=tuple(), **overrides):
    code = rule_code if isinstance(rule_code, str) else f"RULE_{unique_suffix()}"
    payload = create_rule_payload(code, **overrides)
    return _data(api_client.create_rule(payload, BENEFITS), "create rate-discount rule")


def create_active_rule(rule_code=tuple(), **overrides):
    rule = create_rule(rule_code, **overrides)
    activate_rule(rule["id"])
    return fetch_rule(rule["id"])


def activate_rule(rule_id):
    return _data(api_client.activate_rule(rule_id, BENEFITS), "activate rule")


def retire_rule(rule_id):
    return _data(api_client.retire_rule(rule_id, BENEFITS), "retire rule")


def loan_account_in_state(member_id, holding_id, **overrides):
    """Originate a loan against an adopted lending holding."""
    payload = create_loan_account_payload(member_id, holding_id, **overrides)
    return _data(api_client.create_loan_account(payload, UNDERWRITER), "originate loan account")


def enroll_loan_autopay(member_id, loan_account_id):
    return _data(api_client.enroll_autopay(loan_account_id, make_member_headers(member_id)),
                 "enrol autopay")


def finalize_loan(loan_account_id):
    return _data(api_client.finalize_pricing(loan_account_id, UNDERWRITER), "finalize pricing")


def attach_application(loan_account_id, rule_id, version=None):
    if version is None:
        version = fetch_loan(loan_account_id)["version"]
    return _data(
        api_client.create_application(
            loan_account_id, {"rule_id": rule_id, "expected_loan_account_version": version}, BENEFITS
        ),
        "attach discount application",
    )


# =========================================================================
# Retrieval helpers
# =========================================================================

def fetch_member(member_id, headers=None):
    return _data(api_client.get_member(member_id, headers or ADMIN), "get member")


def fetch_holding(holding_id):
    return _data(api_client.get_holding(holding_id, ADMIN), "get holding")


def fetch_loan(loan_account_id, headers=None):
    return _data(api_client.get_loan_account(loan_account_id, headers or UNDERWRITER), "get loan account")


def fetch_rule(rule_id):
    return _data(api_client.get_rule(rule_id, UNDERWRITER), "get rule")


def fetch_enrollment(enrollment_id):
    return _data(api_client.get_deposit_enrollment(enrollment_id, ADMIN), "get deposit enrollment")


def fetch_entitlement(entitlement_id):
    return _data(api_client.get_entitlement(entitlement_id, BENEFITS), "get entitlement")


def fetch_cycle(cycle_id):
    return _data(api_client.get_requalification_cycle(cycle_id, ADMIN), "get requalification cycle")


def fetch_notice(notice_id):
    return _data(api_client.get_churn_notice(notice_id, ADMIN), "get churn notice")


def fetch_application(application_id):
    return _data(api_client.get_application(application_id, BENEFITS), "get discount application")


def fetch_session(session_id):
    return _data(api_client.get_coaching_session(session_id, ADMIN), "get coaching session")


def fetch_check(check_id):
    return _data(api_client.get_cross_sell_check(check_id, COMPLIANCE), "get cross-sell check")


def list_holdings(member_id=None, **params):
    if member_id:
        params["member_id"] = member_id
    return _data(api_client.list_holdings(ADMIN, params=params), "list holdings")


def list_applications(loan_account_id=None, **params):
    if loan_account_id:
        params["loan_account_id"] = loan_account_id
    return _data(api_client.list_applications(BENEFITS, params=params), "list applications")


def list_ledger_entries(member_id=None, **params):
    if member_id:
        params["member_id"] = member_id
    return _data(api_client.list_ledger_entries(BENEFITS, params=params), "list ledger entries")


def list_notices(member_id=None, **params):
    if member_id:
        params["member_id"] = member_id
    return _data(api_client.list_churn_notices(ADMIN, params=params), "list churn notices")


def list_cycles(member_id=None, **params):
    if member_id:
        params["member_id"] = member_id
    return _data(api_client.list_requalification_cycles(ADMIN, params=params), "list cycles")


def list_entitlements(member_id=None, **params):
    if member_id:
        params["member_id"] = member_id
    return _data(api_client.list_entitlements(BENEFITS, params=params), "list entitlements")


def paginated(response):
    """Return (rows, meta) from a list response."""
    body = response.json()
    return body["data"], body["meta"]


# =========================================================================
# Tier 2 — deposit enrolment lifecycle
# =========================================================================

def create_enrollment(member_id, required_monthly_amount_cents=C.TEST_DEFAULTS["REQUIRED_MONTHLY_AMOUNT_CENTS"]):
    payload = create_deposit_enrollment_payload(
        member_id, required_monthly_amount_cents=required_monthly_amount_cents
    )
    return _data(api_client.create_deposit_enrollment(payload, ADMIN), "open deposit enrollment")


def post_deposit(member_id, enrollment_id, amount_cents, posted_at, holding_id=None):
    payload = create_deposit_payload(enrollment_id, amount_cents, posted_at)
    if holding_id:
        payload["holding_id"] = holding_id
    return _data(api_client.post_deposit(member_id, payload, ADMIN), "post deposit")


def activate_enrollment(enrollment_id):
    return _data(api_client.activate_enrollment(enrollment_id, ADMIN), "activate enrollment")


def lapse_enrollment(enrollment_id):
    return _data(api_client.lapse_enrollment(enrollment_id, ADMIN), "lapse enrollment")


def create_active_enrollment(member_id, required_monthly_amount_cents=C.TEST_DEFAULTS["REQUIRED_MONTHLY_AMOUNT_CENTS"],
                             amount_cents=None, posted_at=None, holding_id=None,
                             extra_postings=None):
    """Open an enrolment with a qualifying posting and activate it.

    Returns (enrollment, holding_or_None) where holding is the BANKING holding
    credited by the posting when one was supplied.
    """
    amount_cents = amount_cents if amount_cents is not None else required_monthly_amount_cents
    posted_at = posted_at or C.DEFAULT_CLOCK
    enrollment = create_enrollment(member_id, required_monthly_amount_cents)
    post_deposit(member_id, enrollment["id"], amount_cents, posted_at, holding_id=holding_id)
    for posting in (extra_postings or []):
        post_deposit(member_id, enrollment["id"], posting["amount_cents"], posting["posted_at"],
                     holding_id=posting.get("holding_id"))
    activated = activate_enrollment(enrollment["id"])
    return activated


def enrollment_in_grace(member_id, banking_holding_id=None, required_monthly_amount_cents=None,
                        grace_clock="2026-11-01T00:00:00Z"):
    """Active enrolment with one missed month, then moved into GRACE.

    The September posting qualifies; the clock is advanced to the first instant
    of November, by which point September is complete and qualified while October
    is complete and unposted, so the missed-cycle count has reached 1 and the
    ACTIVE -> GRACE transition is admitted. Returns the GRACE enrolment.
    """
    threshold = required_monthly_amount_cents or C.TEST_DEFAULTS["REQUIRED_MONTHLY_AMOUNT_CENTS"]
    enrollment = create_enrollment(member_id, threshold)
    post_deposit(member_id, enrollment["id"], threshold, "2026-09-01T00:00:00Z",
                 holding_id=banking_holding_id)
    activate_enrollment(enrollment["id"])
    set_clock(grace_clock)
    return lapse_enrollment(enrollment["id"])


def lapse_enrollment_past_grace(member_id, banking_holding_id=None, threshold=None,
                                land_clock="2027-01-01T00:00:00Z"):
    """Drive an enrolment all the way to LAPSED, past its grace deadline.

    The clock is advanced well beyond any plausible grace deadline so the
    GRACE -> LAPSED transition is admitted regardless of how the deadline is
    computed. Returns the LAPSED enrolment.
    """
    grace = enrollment_in_grace(member_id, banking_holding_id, threshold)
    set_clock(land_clock)
    return lapse_enrollment(grace["id"])


# =========================================================================
# Tier 3 — entitlement helpers
# =========================================================================

def declare_entitlement(member_id, source_holding_id, benefit_code, value_bps=50, governing_rule_id=None):
    payload = create_entitlement_payload(source_holding_id, benefit_code, value_bps=value_bps)
    if governing_rule_id:
        payload["governing_rule_id"] = governing_rule_id
    return _data(
        api_client.create_entitlement(member_id, payload, BENEFITS),
        "declare benefit entitlement",
    )


def create_granted_entitlement(member_id, product_line, benefit_code, value_bps=50,
                               governing_rule_id=None, balance_cents=0):
    """Adopt a fresh holding of `product_line` and declare the entitlement over it.

    Returns (holding, entitlement).
    """
    holding = create_adopted_holding(member_id, product_line, balance_cents)
    entitlement = declare_entitlement(member_id, holding["id"], benefit_code,
                                      value_bps=value_bps, governing_rule_id=governing_rule_id)
    return holding, entitlement


def reconcile_entitlements(member_id):
    return _data(api_client.reconcile_entitlements(member_id, COMPLIANCE), "reconcile entitlements")


# =========================================================================
# Tier 4 — accumulation / threshold targeting
# =========================================================================

def setup_member_with_priced_loan(base_apr_bps, rule_specs, autopay=False,
                                  principal_cents=C.TEST_DEFAULTS["PRINCIPAL_CENTS"],
                                  loan_type="PERSONAL", other_lines=(), balances=None):
    """Member + adopted LENDING holding + loan + a set of ACTIVE rules.

    `rule_specs` is a list of dicts; each may carry rule_code, discount_kind,
    stacking_class, discount_bps, effective_from, effective_to,
    requires_direct_deposit and min_member_tier. Every rule is activated, so the
    loan's provisional stack is re-derived from the whole candidate pool.

    Returns a dict with member, holding, loan, rules (list) and rules_by_code.
    """
    lines = ["LENDING", *other_lines]
    member, holdings = create_member_with_adopted_holdings(lines, balances)
    rules = []
    for spec in rule_specs:
        spec = dict(spec)
        code = spec.pop("rule_code", None)
        rules.append(create_active_rule(code, **spec))
    rules_by_code = {rule["rule_code"]: rule for rule in rules}
    holding = holdings["LENDING"]
    loan = loan_account_in_state(member["id"], holding["id"], loan_type=loan_type,
                                 principal_cents=principal_cents, base_apr_bps=base_apr_bps)
    if autopay:
        enroll_loan_autopay(member["id"], loan["id"])
    return {
        "member": fetch_member(member["id"]),
        "holding": holding,
        "loan": fetch_loan(loan["id"]),
        "rules": rules,
        "rules_by_code": rules_by_code,
    }


def setup_node_map(base_apr_bps=1200, base_bps=275, autopay_bps=50,
                   principal_cents=1200000):
    """The canonical two-class stack around a known member tier.

    Member holds an ADOPTED LENDING holding and an ACTIVE direct-deposit
    enrolment credited against an ADOPTED BANKING holding, so the tier is PLUS
    and a direct-deposit rule prices as well. A BASE rule and an ADDITIVE
    autopay rule are ACTIVE — and the loan is enrolled in autopay, because a
    rule whose kind is autopay does not enter the candidate pool of a loan whose
    `autopay_status` is anything other than `ENROLLED` (PRD §2.5) — so the
    provisional stack reads base_bps + autopay_bps.

    Returns a dict with member, loan, banking_holding, rules and rules_by_code.
    """
    token = unique_suffix()
    member, holdings = create_member_with_adopted_holdings(["LENDING", "BANKING"],
                                                           {"BANKING": 200000})
    copy = {
        "base_bps": base_bps,
        "autopay_bps": autopay_bps,
    }
    base_rule = create_active_rule(f"NODE_BASE_{token}", discount_kind="MEMBER_TIER",
                                   stacking_class="BASE", discount_bps=copy["base_bps"])
    additive_rule = create_active_rule(f"NODE_ADD_{token}", discount_kind="AUTOPAY",
                                       stacking_class="ADDITIVE", discount_bps=copy["autopay_bps"])
    loan = loan_account_in_state(member["id"], holdings["LENDING"]["id"],
                                 principal_cents=principal_cents, base_apr_bps=base_apr_bps)
    enroll_loan_autopay(member["id"], loan["id"])
    enrollment = create_enrollment(member["id"])
    post_deposit(member["id"], enrollment["id"], 200000, C.DEFAULT_CLOCK,
                 holding_id=holdings["BANKING"]["id"])
    activate_enrollment(enrollment["id"])
    return {
        "member": fetch_member(member["id"]),
        "holding": holdings["LENDING"],
        "banking_holding": holdings["BANKING"],
        "loan": fetch_loan(loan["id"]),
        "rules": [base_rule, additive_rule],
        "rules_by_code": {base_rule["rule_code"]: base_rule,
                          additive_rule["rule_code"]: additive_rule},
        "components": copy,
    }


def setup_cumulative_autopay_stack(base_apr_bps=1200, base_bps=250, autopay_bps=75,
                                   principal_cents=C.TEST_DEFAULTS["PRINCIPAL_CENTS"]):
    """The canonical two-class stack: one BASE rule and one ADDITIVE autopay rule.

    The member holds an adopted LENDING holding and an adopted BANKING holding, so
    two adopted products across two distinct lines reach `PLUS` under the
    top-down threshold rule of §2.4.

    Returns the setup dict from setup_member_with_priced_loan with autopay on.
    """
    token = unique_suffix()
    return setup_member_with_priced_loan(
        base_apr_bps,
        [
            {"rule_code": f"BASE_{token}", "discount_kind": "MEMBER_TIER",
             "stacking_class": "BASE", "discount_bps": base_bps},
            {"rule_code": f"AUTO_{token}", "discount_kind": "AUTOPAY",
             "stacking_class": "ADDITIVE", "discount_bps": autopay_bps},
        ],
        autopay=True,
        principal_cents=principal_cents,
        other_lines=["BANKING"],
    )


def setup_final_priced_loan(stack_bps=325, base_apr_bps=1200, principal_cents=C.TEST_DEFAULTS["PRINCIPAL_CENTS"],
                            discount_kind="AUTOPAY", stacking_class="ADDITIVE",
                            with_banking=True, requires_direct_deposit=False,
                            other_lines=(), other_rules=()):
    """A loan frozen at FINAL with one rule applied and snapshotted.

    The attached rule carries the requested magnitude directly, so the frozen
    discount stack equals `stack_bps` under the FINAL variant. `other_rules`
    are created and activated but never attached, modelling the rules a later
    activation can add to the provisional pool while the frozen loan is unmoved.

    Returns a dict with member, holding, banking_holding, loan, rule and
    rules_by_code.
    """
    token = unique_suffix()
    lines = ["LENDING", *other_lines]
    balances = {"BANKING": 150000} if with_banking else {}
    if with_banking and "BANKING" not in lines:
        lines.append("BANKING")
    member, holdings = create_member_with_adopted_holdings(lines, balances)
    rule = create_active_rule(f"FRZ_{token}", discount_kind=discount_kind,
                              stacking_class=stacking_class, discount_bps=stack_bps,
                              requires_direct_deposit=requires_direct_deposit)
    extra = []
    for spec in other_rules:
        spec = dict(spec)
        code = spec.pop("rule_code", None)
        extra.append(create_active_rule(code, **spec))
    loan = loan_account_in_state(member["id"], holdings["LENDING"]["id"],
                                 principal_cents=principal_cents, base_apr_bps=base_apr_bps)
    enroll_loan_autopay(member["id"], loan["id"])
    attach_application(loan["id"], rule["id"])
    finalize_loan(loan["id"])
    rules_by_code = {r["rule_code"]: r for r in [rule, *extra]}
    return {
        "member": fetch_member(member["id"]),
        "holding": holdings["LENDING"],
        "banking_holding": holdings.get("BANKING"),
        "loan": fetch_loan(loan["id"]),
        "rule": rule,
        "extra_rules": extra,
        "rules_by_code": rules_by_code,
    }


def setup_active_enrollment_for(member_id, required_monthly_amount_cents=None,
                                banking_holding_id=None, amount_cents=None,
                                posted_at=None):
    """Attach an ACTIVE enrolment to an existing member.

    Returns the enrolment. When a banking holding id is supplied the posting
    credits it.
    """
    threshold = required_monthly_amount_cents or C.TEST_DEFAULTS["REQUIRED_MONTHLY_AMOUNT_CENTS"]
    amount = amount_cents if amount_cents is not None else threshold
    return create_active_enrollment(
        member_id, required_monthly_amount_cents=threshold, amount_cents=amount,
        posted_at=posted_at or C.DEFAULT_CLOCK, holding_id=banking_holding_id,
    )


def setup_grace_enrollment_for(member_id, banking_holding_id=None,
                               required_monthly_amount_cents=None):
    """Attach a GRACE-status enrolment to an existing member."""
    return enrollment_in_grace(member_id, banking_holding_id, required_monthly_amount_cents)


def setup_lapsed_enrollment_for(member_id, banking_holding_id=None,
                                required_monthly_amount_cents=None):
    """Attach a LAPSED enrolment to an existing member."""
    return lapse_enrollment_past_grace(member_id, banking_holding_id,
                                       required_monthly_amount_cents)


def setup_member_near_band_boundary(balance_cents, threshold=None,
                                    product_line="BANKING",
                                    with_deposit_entitlement=False):
    """Member with an ACTIVE enrolment funded to an exact qualifying balance.

    The posting amount is the band balance the caller wants the member to hold,
    but never below the enrolment's required monthly threshold, because a posting
    below that threshold would not qualify the enrolment for activation (PRD
    §3.3: a pending enrolment is activated only when at least one posted deposit
    has reached `required_monthly_amount_cents`). The BANKING balance therefore
    reaches the threshold even when the caller's target sits one cent below it.
    """
    threshold = threshold or C.TEST_DEFAULTS["REQUIRED_MONTHLY_AMOUNT_CENTS"]
    member = register_member()
    holding = create_adopted_holding(member["id"], product_line, 0)
    enrollment = create_enrollment(member["id"], threshold)
    entitlement = None
    if with_deposit_entitlement:
        entitlement = declare_entitlement(member["id"], holding["id"], "DIRECT_DEPOSIT",
                                          value_bps=50)
    posting_amount = max(balance_cents, threshold)
    post_deposit(member["id"], enrollment["id"], posting_amount,
                 C.DEFAULT_CLOCK, holding_id=holding["id"] if product_line == "BANKING" else None)
    activated = activate_enrollment(enrollment["id"])
    return {
        "member": fetch_member(member["id"]),
        "holding": fetch_holding(holding["id"]),
        "enrollment": fetch_enrollment(activated["id"]),
        "entitlement": fetch_entitlement(entitlement["id"]) if entitlement else None,
    }


def setup_rewards_member(points_delta, principal_cents=500000, base_apr_bps=1100,
                         loan_type="PERSONAL"):
    """Member with an adopted LENDING holding, a loan and a posted points balance."""
    member, holdings = create_member_with_adopted_holdings(["LENDING"])
    loan = loan_account_in_state(member["id"], holdings["LENDING"]["id"],
                                 loan_type=loan_type, principal_cents=principal_cents,
                                 base_apr_bps=base_apr_bps)
    _data(api_client.adjust_rewards(member["id"], rewards_adjust_payload(points_delta), BENEFITS),
          "post opening points adjustment")
    return {
        "member": fetch_member(member["id"]),
        "holding": holdings["LENDING"],
        "loan": fetch_loan(loan["id"]),
    }


def setup_member_with_loan_only(principal_cents=400000, base_apr_bps=1000, loan_type="PERSONAL"):
    """Member + adopted LENDING holding + loan, with no points and no rules."""
    member, holdings = create_member_with_adopted_holdings(["LENDING"])
    loan = loan_account_in_state(member["id"], holdings["LENDING"]["id"],
                                 loan_type=loan_type, principal_cents=principal_cents,
                                 base_apr_bps=base_apr_bps)
    return {"member": fetch_member(member["id"]), "holding": holdings["LENDING"],
            "loan": fetch_loan(loan["id"])}


# =========================================================================
# Tier 5 — terminal / cascade setups
# =========================================================================

def setup_deposit_lapse_cascade(base_apr_bps=1200, discount_bps=50,
                                principal_cents=1500000):
    """Full deposit-lapse cascade setup, ready for the triggering lapse.

    Member + adopted BANKING and LENDING holdings; a DIRECT_DEPOSIT rule that
    requires an active enrolment; an ACTIVE enrolment; a GRANTED DEPOSIT_RATE_BOOST
    entitlement; a loan priced at the discount and then finalized. The enrolment
    sits in GRACE past its deadline, so one more lapse request lands LAPSED.

    Returns a dict with member, loan, rule, enrollment, entitlement and holding.
    """
    token = unique_suffix()
    member = register_member()
    banking = create_adopted_holding(member["id"], "BANKING", 300000)
    lending = create_adopted_holding(member["id"], "LENDING", 0)

    rule = create_active_rule(f"DIRECT_DEPOSIT_{token}", discount_kind="DIRECT_DEPOSIT",
                              stacking_class="ADDITIVE", discount_bps=discount_bps,
                              requires_direct_deposit=True)
    enrollment = create_enrollment(member["id"])
    declare_entitlement(member["id"], banking["id"], "DIRECT_DEPOSIT",
                        value_bps=discount_bps)
    post_deposit(member["id"], enrollment["id"], 250000, C.DEFAULT_CLOCK,
                 holding_id=banking["id"])
    enrollment = activate_enrollment(enrollment["id"])

    loan = loan_account_in_state(member["id"], lending["id"],
                                 principal_cents=principal_cents, base_apr_bps=base_apr_bps)
    attach_application(loan["id"], rule["id"])
    finalize_loan(loan["id"])

    # ACTIVE -> GRACE once a month has been missed, then move the clock well past
    # the grace deadline so the next lapse request lands LAPSED.
    set_clock("2026-11-01T00:00:00Z")
    lapse_enrollment(enrollment["id"])
    set_clock("2027-01-01T00:00:00Z")

    return {
        "member": fetch_member(member["id"]),
        "banking_holding": banking,
        "lending_holding": lending,
        "rule": rule,
        "enrollment": fetch_enrollment(enrollment["id"]),
        "entitlements": list_entitlements(member["id"]),
        "loan": fetch_loan(loan["id"]),
    }


def setup_holding_close_cascade(base_apr_bps=1300, discount_bps=100,
                                principal_cents=900000):
    """Career-bundle cascade setup: closing the CAREER holding revokes the benefit.

    Member + adopted CAREER and LENDING holdings; a CAREER_SERVICES rule; a
    GRANTED LOAN_RATE_DISCOUNT entitlement governed by that rule, sourced from the
    CAREER holding; a loan priced at the discount and finalized.

    Returns a dict with member, career_holding, lending_holding, rule,
    entitlement and loan.
    """
    token = unique_suffix()
    member = register_member()
    career = create_adopted_holding(member["id"], "CAREER", 0)
    lending = create_adopted_holding(member["id"], "LENDING", 0)

    rule = create_active_rule(f"CAREER_BUNDLE_{token}", discount_kind="CAREER_SERVICES",
                              stacking_class="ADDITIVE", discount_bps=discount_bps)
    entitlement = declare_entitlement(member["id"], career["id"], "LOAN_RATE_DISCOUNT",
                                      value_bps=discount_bps, governing_rule_id=rule["id"])
    loan = loan_account_in_state(member["id"], lending["id"],
                                 principal_cents=principal_cents, base_apr_bps=base_apr_bps)
    attach_application(loan["id"], rule["id"])
    finalize_loan(loan["id"])

    return {
        "member": fetch_member(member["id"]),
        "career_holding": career,
        "lending_holding": lending,
        "rule": rule,
        "entitlement": entitlement,
        "loan": fetch_loan(loan["id"]),
    }


def setup_lapsed_member_with_products(member_id=None):
    """Drive a member with one adopted product into MEMBER_LAPSED.

    The enrolment lapses (40 points), the tier is NONE or BASE (25) and the
    qualifying balance is depleted (15), so the score clears the lapse band.
    Returns (member, enrollment, holding).
    """
    if member_id is None:
        member = register_member()
        member_id = member["id"]
    holding = create_adopted_holding(member_id, "INVESTING", 0)
    enrollment = lapse_enrollment_past_grace(member_id)
    detect_churn(member_id)
    return fetch_member(member_id), enrollment, holding


def detect_churn(member_id):
    return _data(api_client.detect_churn(member_id, ADMIN), "detect churn")


def open_cycle(member_id, headers=None):
    member = fetch_member(member_id)
    return _data(
        api_client.open_requalification_cycle(
            member_id, {"expected_member_version": member["version"]}, headers or ADMIN
        ),
        "open requalification cycle",
    )


def open_cycle_with_stale_version(member_id, stale_version):
    return api_client.open_requalification_cycle(
        member_id, {"expected_member_version": stale_version}, ADMIN
    )


def evaluate_cycle(cycle_id):
    return _data(api_client.evaluate_cycle(cycle_id, ADMIN), "evaluate cycle")


def open_remediation(cycle_id):
    return _data(api_client.open_remediation(cycle_id, ADMIN), "open remediation")


def close_cycle(cycle_id):
    return _data(api_client.close_cycle(cycle_id, ADMIN), "close cycle")


# =========================================================================
# Coaching / cross-sell setups
# =========================================================================

def setup_career_member_with_entitlement(source_line="CAREER"):
    """Member with an adopted holding and a GRANTED career-coaching credit."""
    member = register_member()
    holding = create_adopted_holding(member["id"], source_line, 0)
    entitlement = declare_entitlement(member["id"], holding["id"], "CAREER_COACHING_CREDIT",
                                      value_bps=1)
    return {"member": fetch_member(member["id"]), "holding": holding,
            "entitlement": entitlement}


def book_session(member_id, coach_ref, session_kind, starts_at, ends_at, capacity_total=1):
    payload = book_coaching_session_payload(member_id, coach_ref, session_kind,
                                            starts_at, ends_at, capacity_total=capacity_total)
    return _data(api_client.book_coaching_session(payload, BENEFITS), "book coaching session")


def confirm_session(member_id, session_id):
    return _data(api_client.confirm_coaching_session(session_id, make_member_headers(member_id)),
                 "confirm session")


def complete_session(session_id):
    return _data(api_client.complete_coaching_session(session_id, ADMIN), "complete session")


def setup_member_with_notice(status="QUEUED", notice_type=None, member_id=None):
    """A member carrying a churn notice, optionally advanced to SENT.

    Returns (member, notice).
    """
    member = register_member(member_number="M-NOTICE", email="notice.member@x.com")
    member_id = member["id"]
    create_adopted_holding(member_id, "INVESTING", 0)
    enrollment = create_enrollment(member_id)
    post_deposit(member_id, enrollment["id"], 200000, C.DEFAULT_CLOCK)
    activate_enrollment(enrollment["id"])
    set_clock("2026-11-01T00:00:00Z")
    lapse_enrollment(enrollment["id"])
    notices = list_notices(member_id, status="QUEUED")
    assert notices, "Setup failed: no queued churn notice was raised by the lapse"
    notice = notices[0]
    if status == "SENT":
        _data(api_client.send_churn_notice(notice["id"], ADMIN), "send churn notice")
        notice = fetch_notice(notice["id"])
    return fetch_member(member_id), notice


def setup_cross_sell_member(target_line, consent_recorded, source_lines=("LENDING",),
                            balance_cents=None):
    """Member holding the source lines, plus a PENDING cross-sell check."""
    member, holdings = create_member_with_adopted_holdings(list(source_lines),
                                                           balance_cents or {})
    check = _data(
        api_client.create_cross_sell_check(
            create_cross_sell_check_payload(member["id"], target_line,
                                            consent_recorded=consent_recorded),
            BENEFITS,
        ),
        "open cross-sell check",
    )
    return {"member": fetch_member(member["id"]), "holdings": holdings, "check": check}


def setup_member_with_lending_loan_final(pricing_final=True, base_apr_bps=1090,
                                         principal_cents=400000):
    """Member with an adopted LENDING holding and a loan that is FINAL or PROVISIONAL."""
    member, holdings = create_member_with_adopted_holdings(["LENDING"])
    loan = loan_account_in_state(member["id"], holdings["LENDING"]["id"],
                                 principal_cents=principal_cents, base_apr_bps=base_apr_bps)
    if pricing_final:
        finalize_loan(loan["id"])
    return {"member": fetch_member(member["id"]), "holding": holdings["LENDING"],
            "loan": fetch_loan(loan["id"])}


__all__ = [name for name in dir() if not name.startswith("_") and name not in (
    "api_client", "get_success_data", "C",
)]