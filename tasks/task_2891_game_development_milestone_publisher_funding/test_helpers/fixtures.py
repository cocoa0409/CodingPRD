"""Composite setup helpers.

The server is restarted before every test, so each of these builds its world from
an empty database using nothing but the endpoints of PRD §4: register the parties,
draft the agreement, carve the milestone schedule, activate, deliver builds and
record verdicts. Every ownership-gated call is threaded with the real row id the
PRD requires in `X-User-ID`.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import ALPHA_PASSING_METRICS, FUNCTION_DUAL, FUNCTION_FINANCE, FUNCTION_REVIEW
from .test_users import (
    ADMIN_HEADERS,
    make_developer_headers,
    make_publisher_finance_headers,
    make_publisher_reviewer_headers,
)

DEFAULT_CRITERIA_3 = ["Core loop playable", "Two biomes complete", "Save and load"]
DEFAULT_CRITERIA_2 = ["Core loop playable", "Two biomes complete"]
DEFAULT_CRITERIA_1 = ["Core loop playable"]


class Registry:
    """The studio, the publisher and the publisher-side operators."""

    def __init__(self, api, studio_id: str, publisher_id: str,
                 reviewer_id: Optional[str] = None, finance_id: Optional[str] = None,
                 dual_id: Optional[str] = None):
        self.api = api
        self.studio_id = studio_id
        self.publisher_id = publisher_id
        self.reviewer_id = reviewer_id
        self.finance_id = finance_id
        self.dual_id = dual_id
        self.admin = ADMIN_HEADERS
        self.dev = make_developer_headers(studio_id)
        self.reviewer = make_publisher_reviewer_headers(reviewer_id) if reviewer_id else None
        self.finance = make_publisher_finance_headers(finance_id) if finance_id else None
        self.dual_reviewer = (
            make_publisher_reviewer_headers(dual_id) if dual_id else None
        )
        self.dual_finance = make_publisher_finance_headers(dual_id) if dual_id else None

    def add_publisher_user(self, display_name: str, function: str) -> str:
        row = get_success_data(
            self.api.create_publisher_user(
                f.publisher_user_payload(self.publisher_id, display_name, function),
                self.admin,
            )
        )
        return row["id"]


def setup_registry(api, studio_name: str = "Northlight Studio",
                   studio_email: str = "dev@northlight.example",
                   studio_country: str = "SE",
                   publisher_name: str = "Vantage Publishing",
                   publisher_email: str = "ops@vantage.example",
                   publisher_country: str = "US",
                   with_reviewer: bool = True,
                   with_finance: bool = True,
                   with_dual: bool = False) -> Registry:
    """Register the studio, the publisher and the operators the tests act as."""
    studio = get_success_data(
        api.create_studio(
            f.studio_payload(studio_name, studio_email, studio_country), ADMIN_HEADERS
        )
    )
    publisher = get_success_data(
        api.create_publisher(
            f.publisher_payload(publisher_name, publisher_email, publisher_country),
            ADMIN_HEADERS,
        )
    )
    reviewer_id = None
    finance_id = None
    dual_id = None
    if with_reviewer:
        reviewer_id = get_success_data(
            api.create_publisher_user(
                f.publisher_user_payload(publisher["id"], "Rae Reviewer", FUNCTION_REVIEW),
                ADMIN_HEADERS,
            )
        )["id"]
    if with_finance:
        finance_id = get_success_data(
            api.create_publisher_user(
                f.publisher_user_payload(publisher["id"], "Fen Finance", FUNCTION_FINANCE),
                ADMIN_HEADERS,
            )
        )["id"]
    if with_dual:
        dual_id = get_success_data(
            api.create_publisher_user(
                f.publisher_user_payload(publisher["id"], "Dana Dual", FUNCTION_DUAL),
                ADMIN_HEADERS,
            )
        )["id"]
    return Registry(api, studio["id"], publisher["id"], reviewer_id, finance_id, dual_id)


# ---------------------------------------------------------------- primitives
def draft_agreement(reg: Registry, title: str, advance_total_cents: int,
                    royalty_rate_bps: int = 2500,
                    ship_date_original: str = "2027-03-31",
                    recoupable_cost_cap_bps: Optional[int] = 2000,
                    platform_fee_bps: Optional[int] = 3000,
                    live_ops_quarterly_funding_cents: Optional[int] = None) -> Dict:
    return get_success_data(
        reg.api.create_agreement(
            f.agreement_payload(
                reg.studio_id, reg.publisher_id, title, advance_total_cents,
                royalty_rate_bps, ship_date_original,
                recoupable_cost_cap_bps, platform_fee_bps,
                live_ops_quarterly_funding_cents,
            ),
            reg.finance or reg.admin,
        )
    )


def add_milestone(reg: Registry, agreement_id: str, sequence_index: int, title: str,
                  gate_profile: str, funded_amount_cents: int,
                  contractor_budget_cents: int,
                  acceptance_criteria: Optional[List[str]] = None,
                  depends_on_milestone_id: Optional[str] = None) -> Dict:
    return get_success_data(
        reg.api.create_milestone(
            f.milestone_payload(
                agreement_id, sequence_index, title, gate_profile,
                funded_amount_cents, contractor_budget_cents,
                acceptance_criteria or DEFAULT_CRITERIA_3, depends_on_milestone_id,
            ),
            reg.dev,
        )
    )


def activate(reg: Registry, agreement_id: str) -> Dict:
    return get_success_data(reg.api.activate_agreement(agreement_id, reg.finance))


def agreement_version(reg: Registry, agreement_id: str) -> int:
    return get_success_data(reg.api.get_agreement(agreement_id, reg.finance))["version"]


def read_agreement(reg: Registry, agreement_id: str) -> Dict:
    return get_success_data(reg.api.get_agreement(agreement_id, reg.finance))


def read_milestone(reg: Registry, milestone_id: str) -> Dict:
    return get_success_data(reg.api.get_milestone(milestone_id, reg.dev))


def submit_build(reg: Registry, milestone_id: str, build_number: int, metrics: Dict,
                 addressed_condition_indexes: Optional[List[int]] = None) -> Dict:
    return get_success_data(
        reg.api.create_build(
            f.build_payload_from_metrics(
                milestone_id, build_number, metrics, addressed_condition_indexes
            ),
            reg.dev,
        )
    )


def record_accepted_review(reg: Registry, build_id: str, day: str = "2026-08-01",
                           start_hour: int = 9, end_hour: int = 13,
                           reviewer_headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        reg.api.create_review(
            f.accepted_review_payload(build_id, day, start_hour, end_hour),
            reviewer_headers or reg.reviewer,
        )
    )


def record_conditional_review(reg: Registry, build_id: str, conditions: List[int],
                              cure_days: int = 14, day: str = "2026-08-01",
                              start_hour: int = 9, end_hour: int = 13,
                              reviewer_headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        reg.api.create_review(
            f.conditional_review_payload(
                build_id, conditions, cure_days, day, start_hour, end_hour
            ),
            reviewer_headers or reg.reviewer,
        )
    )


def record_rejected_review(reg: Registry, build_id: str, day: str = "2026-08-01",
                           start_hour: int = 9, end_hour: int = 12,
                           reviewer_headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        reg.api.create_review(
            f.rejected_review_payload(build_id, day, start_hour, end_hour),
            reviewer_headers or reg.reviewer,
        )
    )


def payment_of_milestone(reg: Registry, milestone_id: str) -> Dict:
    rows = get_success_data(
        reg.api.list_payments(reg.finance, {"milestone_id": milestone_id})
    )
    assert len(rows) == 1, f"expected exactly one payment for {milestone_id}, got {len(rows)}"
    return rows[0]


def authorize_payment(reg: Registry, payment_id: str, memo: Optional[str] = None,
                      finance_headers: Optional[Dict] = None) -> Dict:
    payload = {"memo": memo} if memo is not None else {}
    return get_success_data(
        reg.api.authorize_payment(payment_id, finance_headers or reg.finance, payload)
    )


def accept_milestone(reg: Registry, milestone_id: str, build_number: int = 1,
                     metrics: Optional[Dict] = None, day: str = "2026-08-01",
                     start_hour: int = 9, end_hour: int = 13,
                     reviewer_headers: Optional[Dict] = None) -> Dict:
    """Deliver a gate-clearing build and record an accepting verdict on it."""
    build = submit_build(reg, milestone_id, build_number, metrics or ALPHA_PASSING_METRICS)
    review = record_accepted_review(
        reg, build["id"], day, start_hour, end_hour, reviewer_headers
    )
    return {"build": build, "review": review}


def create_engagement(reg: Registry, milestone_id: str, vendor_code: str,
                      committed_cents: int, start_date: str, end_date: str,
                      scope_summary: str = "Outsourced production work") -> Dict:
    return get_success_data(
        reg.api.create_engagement(
            f.engagement_payload(
                milestone_id, vendor_code, committed_cents, start_date, end_date,
                scope_summary,
            ),
            reg.dev,
        )
    )


def submit_invoice(reg: Registry, engagement_id: str, invoice_number: str,
                   amount_cents: int, period_end_date: str = "2026-08-31") -> Dict:
    return get_success_data(
        reg.api.create_invoice(
            f.invoice_payload(engagement_id, invoice_number, amount_cents, period_end_date),
            reg.dev,
        )
    )


def approve_invoice(reg: Registry, invoice_id: str) -> Dict:
    return get_success_data(
        reg.api.decide_invoice(invoice_id, f.approve_invoice_payload(), reg.finance)
    )


# ---------------------------------------------------------- scenario builders
class Scenario:
    """A registry plus the agreement and milestones a test operates on."""

    def __init__(self, reg: Registry, agreement: Dict, milestones: List[Dict]):
        self.reg = reg
        self.api = reg.api
        self.agreement = agreement
        self.agreement_id = agreement["id"]
        self.milestones = milestones

    @property
    def m1(self) -> Dict:
        return self.milestones[0]

    @property
    def m2(self) -> Dict:
        return self.milestones[1]

    @property
    def m3(self) -> Dict:
        return self.milestones[2]

    def read_agreement(self) -> Dict:
        return read_agreement(self.reg, self.agreement_id)

    def version(self) -> int:
        return agreement_version(self.reg, self.agreement_id)

    def read_milestone(self, milestone_id: str) -> Dict:
        return read_milestone(self.reg, milestone_id)


def setup_aurora_drift(api, activate_agreement: bool = True,
                       ship_date_original: str = "2027-03-31",
                       live_ops_quarterly_funding_cents: Optional[int] = 500000,
                       reg: Optional[Registry] = None) -> Scenario:
    """The canonical three-milestone deal: a 12000000 advance carved
    3600000 ALPHA / 5400000 BETA / 3000000 GOLD."""
    reg = reg or setup_registry(api)
    agreement = draft_agreement(
        reg, "Aurora Drift", 12000000, 2500, ship_date_original,
        2000, 3000, live_ops_quarterly_funding_cents,
    )
    m1 = add_milestone(reg, agreement["id"], 1, "Vertical Slice", "ALPHA",
                       3600000, 800000, DEFAULT_CRITERIA_3)
    m2 = add_milestone(reg, agreement["id"], 2, "Content Complete", "BETA",
                       5400000, 600000, DEFAULT_CRITERIA_3, m1["id"])
    m3 = add_milestone(reg, agreement["id"], 3, "Ship Candidate", "GOLD",
                       3000000, 400000, DEFAULT_CRITERIA_3, m2["id"])
    if activate_agreement:
        agreement = activate(reg, agreement["id"])
    return Scenario(reg, agreement, [m1, m2, m3])


def setup_single_alpha(api, title: str = "Aurora Solo", advance_total_cents: int = 3600000,
                       contractor_budget_cents: int = 800000,
                       acceptance_criteria: Optional[List[str]] = None,
                       activate_agreement: bool = True,
                       ship_date_original: str = "2027-03-31",
                       royalty_rate_bps: int = 2500,
                       recoupable_cost_cap_bps: Optional[int] = 2000,
                       platform_fee_bps: Optional[int] = 3000,
                       live_ops_quarterly_funding_cents: Optional[int] = None,
                       reg: Optional[Registry] = None,
                       with_dual: bool = False) -> Scenario:
    """One ALPHA milestone funded with the whole advance."""
    reg = reg or setup_registry(api, with_dual=with_dual)
    agreement = draft_agreement(
        reg, title, advance_total_cents, royalty_rate_bps, ship_date_original,
        recoupable_cost_cap_bps, platform_fee_bps, live_ops_quarterly_funding_cents,
    )
    m1 = add_milestone(reg, agreement["id"], 1, "Vertical Slice", "ALPHA",
                       advance_total_cents, contractor_budget_cents,
                       acceptance_criteria or DEFAULT_CRITERIA_2)
    if activate_agreement:
        agreement = activate(reg, agreement["id"])
    return Scenario(reg, agreement, [m1])


def setup_twinpeak(api, activate_agreement: bool = True,
                   live_ops_quarterly_funding_cents: Optional[int] = 200000,
                   reg: Optional[Registry] = None,
                   with_dual: bool = False) -> Scenario:
    """A 6000000 advance across an ALPHA milestone and a dependent BETA milestone."""
    reg = reg or setup_registry(api, with_dual=with_dual)
    agreement = draft_agreement(
        reg, "Twinpeak", 6000000, 2500, "2027-06-30", 2000, 3000,
        live_ops_quarterly_funding_cents,
    )
    m1 = add_milestone(reg, agreement["id"], 1, "Vertical Slice", "ALPHA",
                       3600000, 800000, DEFAULT_CRITERIA_3)
    m2 = add_milestone(reg, agreement["id"], 2, "Content Complete", "BETA",
                       2400000, 600000, DEFAULT_CRITERIA_3, m1["id"])
    if activate_agreement:
        agreement = activate(reg, agreement["id"])
    return Scenario(reg, agreement, [m1, m2])


def setup_single_gold(api, title: str = "Sunset Cut",
                      advance_total_cents: int = 3000000,
                      live_ops_quarterly_funding_cents: Optional[int] = 400000,
                      activate_agreement: bool = True,
                      reg: Optional[Registry] = None) -> Scenario:
    """One GOLD milestone: accepting it completes the agreement."""
    reg = reg or setup_registry(api)
    agreement = draft_agreement(
        reg, title, advance_total_cents, 2500, "2027-03-31", 2000, 3000,
        live_ops_quarterly_funding_cents,
    )
    m1 = add_milestone(reg, agreement["id"], 1, "Ship Candidate", "GOLD",
                       advance_total_cents, 0, DEFAULT_CRITERIA_2)
    if activate_agreement:
        agreement = activate(reg, agreement["id"])
    return Scenario(reg, agreement, [m1])
