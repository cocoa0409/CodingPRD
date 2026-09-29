"""Composite state builders.

The server is restarted with an empty database before every test, so each
fixture builds the state it needs from scratch through the PRD's own endpoints —
there is no seeded data and no back door. Every helper returns the response
payload of the row it created, so callers always hold a current `version`.

None of these helpers moves the logical clock as a trailing side effect: clock
placement is part of what most rules are about, so tests set the clock
themselves with set_clock() and a helper only advances it where its docstring
says so explicitly. That also keeps every helper safe to call twice in one test.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .test_users import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    BILLING_1,
    COUNSELOR_1,
    COUNSELOR_2,
    HRA_ADMIN_1,
    HRA_ADMIN_2,
    ACTUARY_1,
    COMPLIANCE_1,
    make_actuary_headers,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_compliance_officer_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
    make_hra_administrator_headers,
    make_retiree_headers,
)

Json = Dict[str, Any]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(api, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Json:
    """Move the logical UTC clock. Only BenefitsAdmin may do this."""
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), headers))


# --------------------------------------------------------------------------- #
# PlanYear
# --------------------------------------------------------------------------- #
def make_plan_year(
    api,
    year: int = f.PLAN_YEAR_2027,
    overrides: Optional[Json] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Register a plan year. It starts in DRAFT."""
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    return get_success_data(
        api.create_plan_year(f.plan_year_payload(year, overrides), headers)
    )


def advance_plan_year(
    api, plan_year_id: str, to_status: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    """Take one declared plan-year lifecycle hop."""
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    return get_success_data(
        api.set_plan_year_status(
            plan_year_id, f.plan_year_status_payload(to_status), headers
        )
    )


def make_open_plan_year(
    api,
    year: int = f.PLAN_YEAR_2027,
    overrides: Optional[Json] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Register a plan year and take the single declared DRAFT to OPEN hop."""
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    plan_year = make_plan_year(api, year=year, overrides=overrides, headers=headers)
    return advance_plan_year(api, plan_year["id"], "OPEN", headers)


# --------------------------------------------------------------------------- #
# PlanOption
# --------------------------------------------------------------------------- #
def make_plan_option(
    api,
    payload: Json,
    activate: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Create a plan option, optionally taking the DRAFT to ACTIVE hop."""
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    option = get_success_data(api.create_plan_option(payload, headers))
    if activate:
        option = get_success_data(api.activate_plan_option(option["id"], headers))
    return option


def make_pre65_core(
    api,
    plan_year_id: str,
    activate: bool = True,
    overrides: Optional[Json] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """PRE65-CORE: pre-Medicare group coverage at 74500 cents a month, open to
    every grandfather group, with no prescription subsidy vehicle."""
    return make_plan_option(
        api, f.pre65_core_payload(plan_year_id, overrides), activate, headers
    )


def make_exch_hra(
    api,
    plan_year_id: str,
    activate: bool = True,
    overrides: Optional[Json] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """EXCH-HRA: individual-exchange HRA coverage with a zero premium."""
    return make_plan_option(
        api, f.exch_hra_payload(plan_year_id, overrides), activate, headers
    )


def make_med_wrap(
    api,
    plan_year_id: str,
    activate: bool = True,
    attest: bool = True,
    certify: bool = True,
    overrides: Optional[Json] = None,
    attest_overrides: Optional[Json] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """MED-WRAP: Medicare group wrap coverage funded through EGWP.

    Because its subsidy vehicle is EGWP, the option carries a second status
    dimension: the actuary attests the prescription values and then compliance
    certifies them. `attest` and `certify` let a test stop the option at exactly
    the dimension value the rule under test needs.
    """
    admin = headers or make_benefits_admin_headers(ADMIN_1)
    option = make_plan_option(
        api, f.med_wrap_payload(plan_year_id, overrides), activate, admin
    )
    if attest:
        option = get_success_data(
            api.attest_plan_option(
                option["id"],
                f.attest_payload(overrides=attest_overrides),
                make_actuary_headers(ACTUARY_1),
            )
        )
    if certify:
        option = get_success_data(
            api.certify_subsidy(
                option["id"],
                f.subsidy_certification_payload("CERTIFY"),
                make_compliance_officer_headers(COMPLIANCE_1),
            )
        )
    return option


# --------------------------------------------------------------------------- #
# Retiree
# --------------------------------------------------------------------------- #
def make_retiree(
    api,
    payload: Optional[Json] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Register a retiree. The grandfather group derives from hire_date alone."""
    headers = headers or make_eligibility_analyst_headers(ANALYST_1)
    return get_success_data(
        api.create_retiree(payload if payload is not None else f.retiree_r1_payload(), headers)
    )


def make_retiree_r1(api, overrides: Optional[Json] = None, headers=None) -> Json:
    return make_retiree(api, f.retiree_r1_payload(overrides), headers)


def make_retiree_r2(api, overrides: Optional[Json] = None, headers=None) -> Json:
    return make_retiree(api, f.retiree_r2_payload(overrides), headers)


def make_retiree_r3(api, overrides: Optional[Json] = None, headers=None) -> Json:
    return make_retiree(api, f.retiree_r3_payload(overrides), headers)


def make_retiree_r4(api, overrides: Optional[Json] = None, headers=None) -> Json:
    return make_retiree(api, f.retiree_r4_payload(overrides), headers)


def reload_retiree(api, retiree_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_eligibility_analyst_headers(ANALYST_1)
    return get_success_data(api.get_retiree(retiree_id, headers))


# --------------------------------------------------------------------------- #
# EligibilityDetermination
# --------------------------------------------------------------------------- #
def make_determination(
    api,
    retiree: Json,
    plan_year_id: str,
    certify: bool = True,
    creator_user_id: str = ANALYST_1,
    certifier_user_id: str = ANALYST_2,
) -> Json:
    """Create a determination for a retiree, optionally certifying it.

    The determination create call carries the retiree's current version, and the
    certifying user differs from the creating user so the segregation-of-duties
    pairing on certify is satisfied.
    """
    determination = get_success_data(
        api.create_determination(
            f.determination_payload(retiree["id"], plan_year_id, retiree["version"]),
            make_eligibility_analyst_headers(creator_user_id),
        )
    )
    if certify:
        determination = get_success_data(
            api.certify_determination(
                determination["id"],
                make_eligibility_analyst_headers(certifier_user_id),
            )
        )
    return determination


def make_certified_retiree(
    api,
    plan_year_id: str,
    payload: Optional[Json] = None,
    creator_user_id: str = ANALYST_1,
    certifier_user_id: str = ANALYST_2,
) -> Dict[str, Json]:
    """A retiree plus a CERTIFIED determination for the plan year.

    Returns {"retiree": <row reloaded after certification>, "determination": <row>}
    so the caller sees the eligibility_status the certification wrote back.
    """
    retiree = make_retiree(api, payload)
    determination = make_determination(
        api,
        retiree,
        plan_year_id,
        certify=True,
        creator_user_id=creator_user_id,
        certifier_user_id=certifier_user_id,
    )
    return {
        "retiree": reload_retiree(api, retiree["id"]),
        "determination": determination,
    }


# --------------------------------------------------------------------------- #
# ElectionEvent and Enrollment
# --------------------------------------------------------------------------- #
def make_election_event(
    api,
    retiree_id: str,
    plan_year_id: str,
    plan_option_id: str,
    event_type: str = "ANNUAL_OPEN",
    event_date: str = "2026-10-20",
    review: bool = False,
    creator_user_id: str = COUNSELOR_1,
    reviewer_user_id: str = COUNSELOR_2,
    overrides: Optional[Json] = None,
) -> Json:
    """Submit an election event, optionally taking the SUBMITTED to UNDER_REVIEW hop."""
    election = get_success_data(
        api.create_election_event(
            f.election_event_payload(
                retiree_id,
                plan_year_id,
                plan_option_id,
                event_type,
                event_date,
                overrides,
            ),
            make_enrollment_counselor_headers(creator_user_id),
        )
    )
    if review:
        election = get_success_data(
            api.review_election_event(
                election["id"], make_enrollment_counselor_headers(reviewer_user_id)
            )
        )
    return election


def decide_election_event(
    api,
    election_event_id: str,
    decision: str = "APPROVE",
    denial_reason_code: Optional[str] = None,
    decider_user_id: str = COUNSELOR_2,
) -> Json:
    """Decide a reviewed election. The deciding user must differ from the user
    that created the election."""
    return get_success_data(
        api.decide_election_event(
            election_event_id,
            f.election_decision_payload(decision, denial_reason_code),
            make_enrollment_counselor_headers(decider_user_id),
        )
    )


def make_enrollment(
    api,
    retiree_id: str,
    plan_year_id: str,
    plan_option_id: str,
    event_type: str = "ANNUAL_OPEN",
    event_date: str = "2026-10-20",
    creator_user_id: str = COUNSELOR_1,
    reviewer_user_id: str = COUNSELOR_2,
) -> Dict[str, Json]:
    """Drive one election all the way from submission to an approved enrollment.

    Returns {"election": <APPROVED election>, "enrollment": <materialised row>}.
    The enrollment is read back through its own endpoint so the caller holds the
    derived payer order, premium and coverage status.
    """
    election = make_election_event(
        api,
        retiree_id,
        plan_year_id,
        plan_option_id,
        event_type,
        event_date,
        review=True,
        creator_user_id=creator_user_id,
        reviewer_user_id=reviewer_user_id,
    )
    election = decide_election_event(
        api, election["id"], "APPROVE", decider_user_id=reviewer_user_id
    )
    enrollment = reload_enrollment(api, election["resulting_enrollment_id"])
    return {"election": election, "enrollment": enrollment}


def reload_enrollment(api, enrollment_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_enrollment_counselor_headers(COUNSELOR_1)
    return get_success_data(api.get_enrollment(enrollment_id, headers))


def terminate_enrollment(
    api,
    enrollment_id: str,
    termination_reason: str = "RETIREE_VOLUNTARY_WITHDRAWAL",
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    headers = headers or make_enrollment_counselor_headers(COUNSELOR_1)
    return get_success_data(
        api.terminate_enrollment(
            enrollment_id, f.terminate_payload(termination_reason), headers
        )
    )


def reload_plan_option(api, plan_option_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    return get_success_data(api.get_plan_option(plan_option_id, headers))


def reload_plan_year(api, plan_year_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    return get_success_data(api.get_plan_year(plan_year_id, headers))


def reload_election_event(api, election_event_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_enrollment_counselor_headers(COUNSELOR_1)
    return get_success_data(api.get_election_event(election_event_id, headers))


def reload_determination(api, determination_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_eligibility_analyst_headers(ANALYST_1)
    return get_success_data(api.get_determination(determination_id, headers))


# --------------------------------------------------------------------------- #
# HraAccount and ReimbursementClaim
# --------------------------------------------------------------------------- #
def make_hra_account(
    api,
    retiree_id: str,
    plan_year_id: str,
    covered_months: int = 12,
    prior_year_account_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    """Open an HRA account. Funding is computed at creation and funded_cents is
    fixed from then on."""
    headers = headers or make_hra_administrator_headers(HRA_ADMIN_1)
    return get_success_data(
        api.create_hra_account(
            f.hra_account_payload(
                retiree_id, plan_year_id, covered_months, prior_year_account_id
            ),
            headers,
        )
    )


def reload_hra_account(api, hra_account_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_hra_administrator_headers(HRA_ADMIN_1)
    return get_success_data(api.get_hra_account(hra_account_id, headers))


def close_hra_year(api, hra_account_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_hra_administrator_headers(HRA_ADMIN_1)
    return get_success_data(api.close_hra_year(hra_account_id, headers))


def make_claim(
    api,
    hra_account: Json,
    retiree_id: str,
    expense_category: str = "QUALIFIED_MEDICAL",
    service_date: str = "2027-03-15",
    submitted_cents: int = 30000,
    documentation_reference: Optional[str] = "DOC-2027-0315",
    overrides: Optional[Json] = None,
) -> Json:
    """Submit a claim as the owning retiree.

    The claim body carries the account's current version, and the caller's
    X-User-ID is the Retiree row id because the Retiree role is entity-backed.
    Pass a freshly reloaded account whenever an earlier hop changed it.
    """
    return get_success_data(
        api.create_claim(
            f.claim_payload(
                hra_account["id"],
                hra_account["version"],
                expense_category,
                service_date,
                submitted_cents,
                documentation_reference,
                overrides,
            ),
            make_retiree_headers(retiree_id),
        )
    )


def review_claim(
    api,
    claim_id: str,
    decision: str = "APPROVE",
    denial_reason_code: Optional[str] = None,
    reviewer_user_id: str = HRA_ADMIN_2,
) -> Json:
    """Review a submitted claim. The reviewer differs from the claim's creator."""
    return get_success_data(
        api.review_claim(
            claim_id,
            f.claim_review_payload(decision, denial_reason_code),
            make_hra_administrator_headers(reviewer_user_id),
        )
    )


def settle_claim(
    api, claim_id: str, action: str = "PAY", settler_user_id: str = BILLING_1
) -> Json:
    """Settle a reviewed claim. The settling user differs from the reviewer."""
    return get_success_data(
        api.settle_claim(
            claim_id,
            f.claim_settlement_payload(action),
            make_billing_clerk_headers(settler_user_id),
        )
    )


def reload_claim(api, claim_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_hra_administrator_headers(HRA_ADMIN_1)
    return get_success_data(api.get_claim(claim_id, headers))


# --------------------------------------------------------------------------- #
# PremiumInvoice
# --------------------------------------------------------------------------- #
def make_invoice(
    api,
    enrollment_id: str,
    billing_period_start: str = "2027-01-01T00:00:00Z",
    billing_period_end: str = "2027-01-31T00:00:00Z",
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    headers = headers or make_billing_clerk_headers(BILLING_1)
    return get_success_data(
        api.create_invoice(
            f.invoice_payload(enrollment_id, billing_period_start, billing_period_end),
            headers,
        )
    )


def pay_invoice(
    api, invoice_id: str, amount_cents: int, headers: Optional[Dict[str, str]] = None
) -> Json:
    headers = headers or make_billing_clerk_headers(BILLING_1)
    return get_success_data(
        api.pay_invoice(invoice_id, f.payment_payload(amount_cents), headers)
    )


def reload_invoice(api, invoice_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    headers = headers or make_billing_clerk_headers(BILLING_1)
    return get_success_data(api.get_invoice(invoice_id, headers))


def run_daily(api, headers: Optional[Dict[str, str]] = None) -> Json:
    """Run the daily administration sweep and return its six counters."""
    headers = headers or make_benefits_admin_headers(ADMIN_1)
    return get_success_data(api.daily_run(headers))


# --------------------------------------------------------------------------- #
# Whole-program builders
# --------------------------------------------------------------------------- #
def standard_program(
    api,
    clock: str = "2026-10-20T00:00:00Z",
    year: int = f.PLAN_YEAR_2027,
    plan_year_overrides: Optional[Json] = None,
) -> Dict[str, Json]:
    """The shared starting point: the clock inside the annual election window, an
    OPEN plan year and an ACTIVE PRE65-CORE option.

    Returns {"plan_year": ..., "pre65_core": ...}. The clock is set first, before
    anything is created, so the helper is safe to call once per test and never
    leaves the clock somewhere a later hop would not expect.
    """
    set_clock(api, clock)
    plan_year = make_open_plan_year(api, year=year, overrides=plan_year_overrides)
    pre65_core = make_pre65_core(api, plan_year["id"])
    return {"plan_year": plan_year, "pre65_core": pre65_core}


def enrolled_retiree(
    api,
    clock: str = "2026-10-20T00:00:00Z",
    year: int = f.PLAN_YEAR_2027,
    plan_year_overrides: Optional[Json] = None,
    retiree_payload: Optional[Json] = None,
) -> Dict[str, Json]:
    """A certified, eligible retiree holding an approved enrollment on PRE65-CORE.

    Returns {"plan_year", "pre65_core", "retiree", "determination", "election",
    "enrollment"}.
    """
    program = standard_program(
        api, clock=clock, year=year, plan_year_overrides=plan_year_overrides
    )
    certified = make_certified_retiree(api, program["plan_year"]["id"], retiree_payload)
    enrolled = make_enrollment(
        api,
        certified["retiree"]["id"],
        program["plan_year"]["id"],
        program["pre65_core"]["id"],
    )
    return {
        "plan_year": program["plan_year"],
        "pre65_core": program["pre65_core"],
        "retiree": certified["retiree"],
        "determination": certified["determination"],
        "election": enrolled["election"],
        "enrollment": enrolled["enrollment"],
    }


def hra_funded_retiree(
    api,
    covered_months: int = 7,
    clock: str = "2026-10-20T00:00:00Z",
    year: int = f.PLAN_YEAR_2027,
    retiree_payload: Optional[Json] = None,
) -> Dict[str, Json]:
    """A Medicare-enrolled, certified retiree with an OPEN HRA account.

    Returns {"plan_year", "retiree", "determination", "hra_account"}. No plan
    option or enrollment is built, because an HRA account depends only on the
    retiree's certified determination for the plan year.
    """
    set_clock(api, clock)
    plan_year = make_open_plan_year(api, year=year)
    certified = make_certified_retiree(
        api,
        plan_year["id"],
        retiree_payload if retiree_payload is not None else f.retiree_r2_payload(),
    )
    account = make_hra_account(
        api, certified["retiree"]["id"], plan_year["id"], covered_months
    )
    return {
        "plan_year": plan_year,
        "retiree": certified["retiree"],
        "determination": certified["determination"],
        "hra_account": account,
    }


def list_ids(rows: List[Json]) -> List[str]:
    return [row["id"] for row in rows]


__all__ = [
    "set_clock",
    "make_plan_year",
    "advance_plan_year",
    "make_open_plan_year",
    "make_plan_option",
    "make_pre65_core",
    "make_exch_hra",
    "make_med_wrap",
    "make_retiree",
    "make_retiree_r1",
    "make_retiree_r2",
    "make_retiree_r3",
    "make_retiree_r4",
    "reload_retiree",
    "make_determination",
    "make_certified_retiree",
    "make_election_event",
    "decide_election_event",
    "make_enrollment",
    "reload_enrollment",
    "terminate_enrollment",
    "reload_plan_option",
    "reload_plan_year",
    "reload_election_event",
    "reload_determination",
    "make_hra_account",
    "reload_hra_account",
    "close_hra_year",
    "make_claim",
    "review_claim",
    "settle_claim",
    "reload_claim",
    "make_invoice",
    "pay_invoice",
    "reload_invoice",
    "run_daily",
    "standard_program",
    "enrolled_retiree",
    "hra_funded_retiree",
    "list_ids",
]
