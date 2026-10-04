"""Composite setup helpers.

The server is restarted before every test, so each fixture builds its entire
precondition chain from scratch through declared endpoints. Setup calls use the
lenient `get_success_data()` so a setup problem surfaces as a clear
"Setup failed" message. OCC-guarded filing calls always re-read the lender's
current version immediately before sending, so fixtures never guess versions.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import WATERFALL_ORDER
from .factories import (
    agreement_payload,
    appraisal_payload,
    claim_payload,
    defect_payload,
    filing_decision_payload,
    filing_payload,
    lender_payload,
    loan_case_payload,
    loss_mitigation_payload,
    review_payload,
)
from .test_users import (
    APPROVER_BETA_ID,
    EXAMINER_ID,
    REVIEWER_ALPHA_ID,
    REVIEWER_GAMMA_ID,
    TEST_USERS,
    make_approver_headers,
    make_examiner_headers,
    make_lender_officer_headers,
    make_reviewer_headers,
    make_servicer_officer_headers,
)

PA = TEST_USERS["platform_admin_headers"]


def _data(response, what: str):
    assert response.status_code < 300, (
        f"Setup failed: {what} returned {response.status_code}: {response.text[:400]}"
    )
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return _data(api_client.set_current_utc(to_iso8601, PA), f"set clock to {to_iso8601}")


# ---------------------------------------------------------------------------
# Lender lifecycle
# ---------------------------------------------------------------------------
def create_lender(**overrides) -> dict:
    return _data(
        api_client.create_lender(lender_payload(**overrides), PA),
        "create lender",
    )


def get_lender(lender_id: str) -> dict:
    return _data(api_client.get_lender(lender_id, PA), f"get lender {lender_id}")


def lender_version(lender_id: str) -> int:
    return get_lender(lender_id)["version"]


def lender_status(lender_id: str) -> str:
    return get_lender(lender_id)["status"]


def submit_filing(lender_id: str, **overrides) -> dict:
    """File audited financials as the owning LenderOfficer (OCC version re-read)."""
    payload = filing_payload(lender_version(lender_id), **overrides)
    return _data(
        api_client.create_financial_filing(
            lender_id, payload, make_lender_officer_headers(lender_id)
        ),
        f"submit filing for lender {lender_id}",
    )


def decide_filing(filing_id: str, lender_id: str, decision: str = "ACCEPT",
                  reviewer: str = REVIEWER_ALPHA_ID) -> dict:
    payload = filing_decision_payload(lender_version(lender_id), decision)
    return _data(
        api_client.decide_financial_filing(
            filing_id, payload, make_reviewer_headers(reviewer)
        ),
        f"decide filing {filing_id} {decision}",
    )


def lender_action(lender_id: str, action: str, role_headers: dict, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return _data(
        api_client.lender_status_change(lender_id, payload, role_headers),
        f"lender {lender_id} action {action}",
    )


def advance_lender(lender_id: str, reviewer: str = REVIEWER_ALPHA_ID) -> dict:
    return lender_action(
        lender_id, "ADVANCE_TO_FIELD_REVIEW", make_reviewer_headers(reviewer)
    )


def approve_lender_action(lender_id: str, approver: str = APPROVER_BETA_ID) -> dict:
    return lender_action(lender_id, "APPROVE", make_approver_headers(approver))


def setup_approved_lender(lender_overrides=None, filing_overrides=None,
                          advancer: str = REVIEWER_ALPHA_ID,
                          approver: str = APPROVER_BETA_ID) -> dict:
    """Create a lender and drive it to APPROVED with an accepted fresh filing.

    Segregation of duties is respected: the approver differs from the advancer.
    """
    lender = create_lender(**(lender_overrides or {}))
    lid = lender["id"]
    filing = submit_filing(lid, **(filing_overrides or {}))
    decide_filing(filing["id"], lid, "ACCEPT", reviewer=advancer)
    advance_lender(lid, reviewer=advancer)
    approve_lender_action(lid, approver=approver)
    return get_lender(lid)


# ---------------------------------------------------------------------------
# Loan cases, appraisals, endorsement
# ---------------------------------------------------------------------------
def create_case(lender_id: str, **overrides) -> dict:
    return _data(
        api_client.create_loan_case(
            loan_case_payload(lender_id, **overrides),
            make_lender_officer_headers(lender_id),
        ),
        f"create case for lender {lender_id}",
    )


def get_case(case_id: str) -> dict:
    return _data(api_client.get_loan_case(case_id, PA), f"get case {case_id}")


def attach_appraisal(case_id: str, lender_id: str, accept: bool = True,
                     reviewer: str = REVIEWER_ALPHA_ID, **overrides) -> dict:
    appraisal = _data(
        api_client.create_appraisal(
            case_id, appraisal_payload(**overrides),
            make_lender_officer_headers(lender_id),
        ),
        f"deliver appraisal on case {case_id}",
    )
    if accept:
        appraisal = _data(
            api_client.decide_appraisal(
                appraisal["id"], {"decision": "ACCEPT"},
                make_reviewer_headers(reviewer),
            ),
            f"accept appraisal {appraisal['id']}",
        )
    return appraisal


def submit_case(case_id: str, lender_id: str) -> dict:
    return _data(
        api_client.submit_underwriting(case_id, make_lender_officer_headers(lender_id)),
        f"submit underwriting for case {case_id}",
    )


def endorse_case(case_id: str, reviewer: str = REVIEWER_ALPHA_ID) -> dict:
    return _data(
        api_client.endorsement_review(
            case_id, {"decision": "ENDORSE"}, make_reviewer_headers(reviewer)
        ),
        f"endorse case {case_id}",
    )


def setup_endorsed_case(lender=None, case_overrides=None, appraisal_overrides=None,
                        endorser: str = REVIEWER_ALPHA_ID, **lender_kwargs) -> tuple:
    """Approved lender + one case walked to ENDORSED. Returns (lender, case)."""
    if lender is None:
        lender = setup_approved_lender(**lender_kwargs)
    lid = lender["id"]
    case = create_case(lid, **(case_overrides or {}))
    attach_appraisal(case["id"], lid, **(appraisal_overrides or {}))
    submit_case(case["id"], lid)
    case = endorse_case(case["id"], reviewer=endorser)
    return lender, case


def declare_default(case_id: str, lender_id: str) -> dict:
    return _data(
        api_client.declare_default(case_id, make_servicer_officer_headers(lender_id)),
        f"declare default on case {case_id}",
    )


# ---------------------------------------------------------------------------
# Repair escrows
# ---------------------------------------------------------------------------
def create_escrow(case_id: str, lender_id: str, **overrides) -> dict:
    return _data(
        api_client.create_repair_escrow(
            case_id, overrides or {"amount_cents": 500_000,
                                   "start_date": "2026-09-01",
                                   "end_date": "2026-12-31"},
            make_lender_officer_headers(lender_id),
        ),
        f"create escrow on case {case_id}",
    )


def list_escrows(case_id: str) -> list:
    return _data(
        api_client.list_repair_escrows(case_id, PA),
        f"list escrows of case {case_id}",
    )


# ---------------------------------------------------------------------------
# MIP
# ---------------------------------------------------------------------------
def bill_annual_mip(case_id: str, lender_id: str, balance_cents: int) -> dict:
    return _data(
        api_client.mip_event(
            case_id,
            {"event_type": "ANNUAL_BILL", "current_balance_cents": balance_cents},
            make_servicer_officer_headers(lender_id),
        ),
        f"annual MIP bill on case {case_id}",
    )


def list_mip_entries(case_id: str) -> list:
    return _data(
        api_client.list_mip_ledger_entries(case_id, PA),
        f"list MIP entries of case {case_id}",
    )


# ---------------------------------------------------------------------------
# Post-endorsement reviews and defects
# ---------------------------------------------------------------------------
def open_review(case_id: str, reviewer: str = REVIEWER_GAMMA_ID, **overrides) -> dict:
    """Open a post-endorsement review. Default reviewer differs from the
    default endorser so the segregation gate passes."""
    return _data(
        api_client.create_post_endorsement_review(
            case_id, review_payload(**overrides), make_reviewer_headers(reviewer)
        ),
        f"open review on case {case_id}",
    )


def record_defect(review_id: str, reviewer: str = REVIEWER_GAMMA_ID, **overrides) -> dict:
    return _data(
        api_client.create_defect(
            review_id, defect_payload(**overrides), make_reviewer_headers(reviewer)
        ),
        f"record defect on review {review_id}",
    )


def confirm_defect(defect_id: str, decision: str = "CONFIRM",
                   approver: str = APPROVER_BETA_ID) -> dict:
    return _data(
        api_client.confirm_defect(
            defect_id, {"decision": decision}, make_approver_headers(approver)
        ),
        f"defect {defect_id} decision {decision}",
    )


def close_review(review_id: str, reviewer: str = REVIEWER_GAMMA_ID) -> dict:
    return _data(
        api_client.close_review(review_id, make_reviewer_headers(reviewer)),
        f"close review {review_id}",
    )


def get_review_of_case(case_id: str) -> dict:
    reviews = _data(
        api_client.list_post_endorsement_reviews(case_id, PA),
        f"list reviews of case {case_id}",
    )
    assert reviews, f"expected a review on case {case_id}"
    return reviews[0]


# ---------------------------------------------------------------------------
# Indemnification agreements
# ---------------------------------------------------------------------------
def draft_agreement(case_id: str, approver: str = APPROVER_BETA_ID, **overrides) -> dict:
    return _data(
        api_client.create_indemnification_agreement(
            case_id, agreement_payload(**overrides), make_approver_headers(approver)
        ),
        f"draft agreement on case {case_id}",
    )


def execute_agreement(agreement_id: str, lender_id: str) -> dict:
    return _data(
        api_client.execute_indemnification(
            agreement_id, make_lender_officer_headers(lender_id)
        ),
        f"execute agreement {agreement_id}",
    )


def list_agreements(case_id: str) -> list:
    return _data(
        api_client.list_indemnification_agreements(case_id, PA),
        f"list agreements of case {case_id}",
    )


def setup_case_with_confirmed_tier1_defect(case_overrides=None, **lender_kwargs):
    """Endorsed-then-defaulted case carrying a CONFIRMED TIER_1 defect.

    INCOME_MISCALC (weight 40) recorded while the case is IN_DEFAULT scores
    round(40 * 1.25) == 50, the TIER_1 boundary.
    Returns (lender, case, review, defect).
    """
    lender, case = setup_endorsed_case(
        case_overrides=case_overrides, **lender_kwargs
    )
    lid, cid = lender["id"], case["id"]
    declare_default(cid, lid)
    review = open_review(cid)
    defect = record_defect(review["id"], defect_code="INCOME_MISCALC",
                           detail="income overstated")
    defect = confirm_defect(defect["id"], "CONFIRM")
    return lender, get_case(cid), review, defect


def setup_case_with_executed_agreement(**kwargs):
    """Case with a CONFIRMED TIER_1 defect and an EXECUTED indemnification
    agreement (drafted by the approver, executed by the owning lender officer).
    Returns (lender, case, agreement)."""
    lender, case, _review, _defect = setup_case_with_confirmed_tier1_defect(**kwargs)
    lid, cid = lender["id"], case["id"]
    agreement = draft_agreement(cid, coverage_cap_cents=1_000_000)
    agreement = execute_agreement(agreement["id"], lid)
    return lender, case, agreement


# ---------------------------------------------------------------------------
# Loss mitigation waterfall
# ---------------------------------------------------------------------------
def create_lm_action(case_id: str, lender_id: str, action_type: str) -> dict:
    return _data(
        api_client.create_loss_mitigation_action(
            case_id, loss_mitigation_payload(action_type),
            make_servicer_officer_headers(lender_id),
        ),
        f"create {action_type} action on case {case_id}",
    )


def evaluate_lm_action(action_id: str, lender_id: str, decision: str, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    return _data(
        api_client.evaluate_loss_mitigation_action(
            action_id, payload, make_servicer_officer_headers(lender_id)
        ),
        f"evaluate action {action_id} {decision}",
    )


def exhaust_waterfall(case_id: str, lender_id: str, decision: str = "INFEASIBLE") -> list:
    """Work all six waterfall tiers to a terminal non-APPROVED state."""
    actions = []
    for action_type in WATERFALL_ORDER:
        action = create_lm_action(case_id, lender_id, action_type)
        action = evaluate_lm_action(action["id"], lender_id, decision)
        actions.append(action)
    return actions


# ---------------------------------------------------------------------------
# Insurance claims
# ---------------------------------------------------------------------------
def file_claim(case_id: str, lender_id: str, **overrides) -> dict:
    return _data(
        api_client.create_claim(
            case_id, claim_payload(**overrides),
            make_servicer_officer_headers(lender_id),
        ),
        f"file claim on case {case_id}",
    )


def setup_claim_filed(case_overrides=None, claim_overrides=None, **lender_kwargs):
    """Endorsed -> defaulted -> waterfall exhausted -> claim filed.
    Returns (lender, case, claim)."""
    lender, case = setup_endorsed_case(
        case_overrides=case_overrides, **lender_kwargs
    )
    lid, cid = lender["id"], case["id"]
    declare_default(cid, lid)
    exhaust_waterfall(cid, lid)
    claim = file_claim(cid, lid, **(claim_overrides or {}))
    return lender, get_case(cid), claim
