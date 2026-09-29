"""Staged setup helpers.

Every helper drives the public API only; nothing reaches into server state.
The bootstrap chain follows the workflow order of PRD §3.1 through §3.9:
park -> opportunity -> prospectus -> proposal -> panel -> award -> bond ->
execution -> season -> receipts -> reconciliation -> audit -> compliance.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as F
from .test_users import (
    admin_headers,
    auditor_headers,
    award_officer_headers,
    concessionaire_headers,
    exec_officer_headers,
    panelist_headers,
    specialist_headers,
    PANELIST_ONE_USER_ID,
    PANELIST_TWO_USER_ID,
)

BOOTSTRAP_CLOCK = "2027-01-05T00:00:00Z"
POST_DEADLINE_CLOCK = "2027-02-02T00:00:00Z"

PANEL_SCORES_ONE = {
    "score_experience": 81,
    "score_operating_plan": 86,
    "score_capital_investment": 91,
    "score_financial_capacity": 76,
    "score_fee_offer": 71,
}
PANEL_SCORES_TWO = {
    "score_experience": 82,
    "score_operating_plan": 85,
    "score_capital_investment": 90,
    "score_financial_capacity": 75,
    "score_fee_offer": 70,
}


def _data(response: Any, expected_status: int = 200) -> Dict[str, Any]:
    validate_success(response, expected_status)
    return get_success_data(response)


# ─── logical clock ─────────────────────────────────────────────────────────

def set_clock(api, current_utc: str) -> Dict[str, Any]:
    return _data(api.set_clock(current_utc, admin_headers()))


# ─── registers ─────────────────────────────────────────────────────────────

def register_park(api, **overrides: Any) -> Dict[str, Any]:
    return _data(api.create_park(F.park_payload(**overrides), admin_headers()), 201)


def register_offeror(api, **overrides: Any) -> Dict[str, Any]:
    return _data(api.create_offeror(F.offeror_payload(**overrides), admin_headers()), 201)


# ─── opportunity ───────────────────────────────────────────────────────────

def create_opportunity(api, park_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.create_opportunity(F.opportunity_payload(park_id, **overrides), specialist_headers()),
        201,
    )


def record_market_analysis(api, opportunity_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.record_market_analysis(
            opportunity_id, F.market_analysis_payload(**overrides), specialist_headers()
        )
    )


def approve_solicitation(api, opportunity_id: str, headers=None) -> Dict[str, Any]:
    return _data(
        api.approve_solicitation(opportunity_id, headers or award_officer_headers())
    )


def approved_opportunity(api, park_id: str, analysis=None, **overrides: Any) -> Dict[str, Any]:
    opportunity = create_opportunity(api, park_id, **overrides)
    record_market_analysis(api, opportunity["id"], **(analysis or {}))
    return approve_solicitation(api, opportunity["id"])


# ─── prospectus ────────────────────────────────────────────────────────────

def draft_prospectus(api, opportunity_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.create_prospectus(
            F.prospectus_payload(opportunity_id, **overrides), specialist_headers()
        ),
        201,
    )


def issue_prospectus(api, prospectus_id: str) -> Dict[str, Any]:
    return _data(api.issue_prospectus(prospectus_id, specialist_headers()))


def close_prospectus(api, prospectus_id: str) -> Dict[str, Any]:
    return _data(api.close_prospectus(prospectus_id, specialist_headers()))


def award_prospectus(api, prospectus_id: str, term_start: str = "2027-03-01", headers=None):
    return _data(
        api.award_prospectus(
            prospectus_id, F.award_payload(term_start), headers or award_officer_headers()
        ),
        201,
    )


# ─── proposal and panel ────────────────────────────────────────────────────

def submit_proposal(api, prospectus_id: str, offeror_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.create_proposal(
            F.proposal_payload(prospectus_id, offeror_id, **overrides),
            concessionaire_headers(offeror_id),
        ),
        201,
    )


def begin_review(api, proposal_id: str) -> Dict[str, Any]:
    return _data(api.begin_review(proposal_id, specialist_headers()))


def file_evaluation(api, proposal_id: str, panelist_user_id: str, **scores: Any):
    return _data(
        api.file_evaluation(
            proposal_id, F.evaluation_payload(**scores), panelist_headers(panelist_user_id)
        ),
        201,
    )


def score_proposal(api, proposal_id: str, first=None, second=None) -> Dict[str, Any]:
    """Files the two sheets that complete the panel and score the proposal."""
    begin_review(api, proposal_id)
    file_evaluation(api, proposal_id, PANELIST_ONE_USER_ID, **(first or PANEL_SCORES_ONE))
    file_evaluation(api, proposal_id, PANELIST_TWO_USER_ID, **(second or PANEL_SCORES_TWO))
    return _data(api.get_proposal(proposal_id, specialist_headers()))


# ─── bond, execution ───────────────────────────────────────────────────────

def post_bond(api, bond_id: str, offeror_id: str, penal_sum_cents: int = 3000000, **overrides):
    return _data(
        api.post_bond(
            bond_id,
            F.post_bond_payload(penal_sum_cents, **overrides),
            concessionaire_headers(offeror_id),
        )
    )


def execute_lease(api, lease_id: str, headers=None, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.execute_lease(
            lease_id, F.execute_lease_payload(**overrides), headers or exec_officer_headers()
        )
    )


def read_lease(api, lease_id: str) -> Dict[str, Any]:
    return _data(api.get_lease(lease_id, award_officer_headers()))


def lease_version(api, lease_id: str) -> int:
    return read_lease(api, lease_id)["version"]


# ─── operating plan ────────────────────────────────────────────────────────

def submit_operating_plan(api, lease_id: str, offeror_id: str, **overrides: Any):
    version = overrides.pop("expected_lease_version", None)
    if version is None:
        version = lease_version(api, lease_id)
    return _data(
        api.create_operating_plan(
            F.operating_plan_payload(lease_id, version, **overrides),
            concessionaire_headers(offeror_id),
        ),
        201,
    )


def approve_operating_plan(api, plan_id: str, headers=None) -> Dict[str, Any]:
    return _data(api.approve_operating_plan(plan_id, headers or award_officer_headers()))


def approved_season(api, lease_id: str, offeror_id: str, **overrides: Any) -> Dict[str, Any]:
    plan = submit_operating_plan(api, lease_id, offeror_id, **overrides)
    return approve_operating_plan(api, plan["id"])


# ─── capital improvement ───────────────────────────────────────────────────

def propose_improvement(api, lease_id: str, offeror_id: str, **overrides: Any):
    return _data(
        api.create_improvement(
            F.improvement_payload(lease_id, **overrides), concessionaire_headers(offeror_id)
        ),
        201,
    )


def approve_improvement(api, improvement_id: str, approved_cost_cents: int = 8000000, headers=None):
    return _data(
        api.approve_improvement(
            improvement_id,
            F.approve_improvement_payload(approved_cost_cents),
            headers or award_officer_headers(),
        )
    )


def place_improvement_in_service(
    api, improvement_id: str, offeror_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _data(
        api.place_improvement_in_service(
            improvement_id,
            F.place_in_service_payload(**overrides),
            concessionaire_headers(offeror_id),
        )
    )


# ─── gross receipts ────────────────────────────────────────────────────────

def file_report(api, lease_id: str, offeror_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.create_report(
            F.report_payload(lease_id, **overrides), concessionaire_headers(offeror_id)
        ),
        201,
    )


def accept_report(api, report_id: str, remittance_received_cents: int, headers=None):
    return _data(
        api.accept_report(
            report_id,
            F.accept_report_payload(remittance_received_cents),
            headers or award_officer_headers(),
        )
    )


def accepted_report(api, lease_id: str, offeror_id: str, **overrides: Any) -> Dict[str, Any]:
    """Files a report and accepts it for exactly its own assessed fee."""
    report = file_report(api, lease_id, offeror_id, **overrides)
    return accept_report(api, report["id"], report["assessed_fee_cents"])


# ─── reconciliation ────────────────────────────────────────────────────────

def create_reconciliation(api, lease_id: str, headers=None, **overrides: Any) -> Dict[str, Any]:
    version = overrides.pop("expected_lease_version", None)
    if version is None:
        version = lease_version(api, lease_id)
    return _data(
        api.create_reconciliation(
            F.reconciliation_payload(lease_id, version, **overrides),
            headers or award_officer_headers(),
        ),
        201,
    )


def settle_reconciliation(api, reconciliation_id: str, offeror_id: str, payment_amount_cents: int):
    return _data(
        api.settle_reconciliation(
            reconciliation_id,
            F.settle_payload(payment_amount_cents),
            concessionaire_headers(offeror_id),
        )
    )


# ─── audit ─────────────────────────────────────────────────────────────────

def open_audit(api, lease_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.create_audit(F.audit_payload(lease_id, **overrides), auditor_headers()), 201
    )


def begin_fieldwork(api, audit_id: str) -> Dict[str, Any]:
    return _data(api.begin_fieldwork(audit_id, auditor_headers()))


def issue_findings(api, audit_id: str, adjusted_gross_receipts_cents: int, **overrides: Any):
    return _data(
        api.issue_findings(
            audit_id,
            F.issue_findings_payload(adjusted_gross_receipts_cents, **overrides),
            auditor_headers(),
        )
    )


def finalize_audit(api, audit_id: str) -> Dict[str, Any]:
    return _data(api.finalize_audit(audit_id, auditor_headers()))


def withdraw_findings(api, audit_id: str, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.withdraw_findings(audit_id, F.withdraw_findings_payload(**overrides), auditor_headers())
    )


# ─── compliance ────────────────────────────────────────────────────────────

def issue_compliance_action(api, lease_id: str, headers=None, **overrides: Any):
    return _data(
        api.create_compliance_action(
            F.compliance_action_payload(lease_id, **overrides),
            headers or award_officer_headers(),
        ),
        201,
    )


def accept_cure(api, action_id: str, headers=None, **overrides: Any) -> Dict[str, Any]:
    return _data(
        api.accept_cure(
            action_id, F.accept_cure_payload(**overrides), headers or award_officer_headers()
        )
    )


def order_bond_draw(api, action_id: str, draw_amount_cents: int, headers=None):
    return _data(
        api.order_bond_draw(
            action_id,
            F.order_bond_draw_payload(draw_amount_cents),
            headers or award_officer_headers(),
        )
    )


# ─── composite scenarios ───────────────────────────────────────────────────

def setup_issued_prospectus(
    api,
    park: Optional[Dict[str, Any]] = None,
    offeror: Optional[Dict[str, Any]] = None,
    opportunity: Optional[Dict[str, Any]] = None,
    analysis: Optional[Dict[str, Any]] = None,
    prospectus: Optional[Dict[str, Any]] = None,
    clock: str = BOOTSTRAP_CLOCK,
) -> Dict[str, Any]:
    """Park, eligible offeror and an ISSUED solicitation with the window open."""
    if clock:
        set_clock(api, clock)
    park_row = register_park(api, **(park or {}))
    offeror_row = register_offeror(api, **(offeror or {}))
    opportunity_row = approved_opportunity(
        api, park_row["id"], analysis=analysis, **(opportunity or {})
    )
    prospectus_row = draft_prospectus(api, opportunity_row["id"], **(prospectus or {}))
    prospectus_row = issue_prospectus(api, prospectus_row["id"])
    return {
        "park": park_row,
        "park_id": park_row["id"],
        "offeror": offeror_row,
        "offeror_id": offeror_row["id"],
        "offeror_headers": concessionaire_headers(offeror_row["id"]),
        "opportunity": opportunity_row,
        "opportunity_id": opportunity_row["id"],
        "prospectus": prospectus_row,
        "prospectus_id": prospectus_row["id"],
    }


def setup_scored_proposal(
    api,
    proposal: Optional[Dict[str, Any]] = None,
    first_scores: Optional[Dict[str, Any]] = None,
    second_scores: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An ISSUED solicitation carrying one SCORED proposal."""
    ctx = setup_issued_prospectus(api, **kwargs)
    proposal_row = submit_proposal(
        api, ctx["prospectus_id"], ctx["offeror_id"], **(proposal or {})
    )
    scored = score_proposal(
        api, proposal_row["id"], first=first_scores, second=second_scores
    )
    ctx.update({"proposal": scored, "proposal_id": scored["id"]})
    return ctx


def setup_awarded_lease(
    api,
    term_start: str = "2027-03-01",
    close_clock: str = POST_DEADLINE_CLOCK,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A lease in PENDING_EXECUTION with its bond row still PENDING."""
    ctx = setup_scored_proposal(api, **kwargs)
    if close_clock:
        set_clock(api, close_clock)
    close_prospectus(api, ctx["prospectus_id"])
    lease = award_prospectus(api, ctx["prospectus_id"], term_start)
    ctx.update(
        {
            "lease": lease,
            "lease_id": lease["id"],
            "bond_id": lease["performance_bond_id"],
        }
    )
    return ctx


def setup_active_lease(
    api,
    penal_sum_cents: int = 3000000,
    execute: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A bonded, insured, executed lease: ACTIVE / COMPLIANT."""
    ctx = setup_awarded_lease(api, **kwargs)
    bond = post_bond(api, ctx["bond_id"], ctx["offeror_id"], penal_sum_cents)
    lease = execute_lease(api, ctx["lease_id"], **(execute or {}))
    ctx.update({"bond": bond, "lease": lease})
    return ctx


def setup_lease_with_season(
    api, plan: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """An ACTIVE lease with one APPROVED season covering 2027-03-01..2027-12-31."""
    ctx = setup_active_lease(api, **kwargs)
    season = approved_season(api, ctx["lease_id"], ctx["offeror_id"], **(plan or {}))
    ctx.update({"plan": season, "plan_id": season["id"]})
    ctx["lease"] = read_lease(api, ctx["lease_id"])
    return ctx


def setup_lease_with_accepted_reports(
    api,
    periods: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An ACTIVE lease with a season and one accepted report per supplied period."""
    ctx = setup_lease_with_season(api, **kwargs)
    reports: List[Dict[str, Any]] = []
    for period in periods or [{}]:
        reports.append(accepted_report(api, ctx["lease_id"], ctx["offeror_id"], **period))
    ctx.update(
        {
            "reports": reports,
            "report_ids": [row["id"] for row in reports],
            "lease": read_lease(api, ctx["lease_id"]),
        }
    )
    return ctx
