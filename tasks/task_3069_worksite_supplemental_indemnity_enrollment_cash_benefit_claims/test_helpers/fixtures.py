"""Composite preconditions.

The server starts each test against an empty store with the logical clock at its
2026-09-01T00:00:00Z default, so every precondition here is built by calling the same
public endpoints a real caller would. Setup calls go through ``get_success_data``,
which accepts any 2xx, so a fixture never hard-codes the 200-versus-201 split; the
tests themselves assert the status codes that matter.

Counselor-driven calls (campaign open/lock/close/reopen, policy intake and lifecycle)
thread the acting counselor's id into ``X-User-ID`` because the server compares a
campaign's ``counselor_id`` against it.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_counselor_headers,
    make_group_admin_headers,
)
from .types import JsonObject, ResourceId


class Bundle(object):
    """A small attribute bag so a test can read ``bundle.policy["id"]`` fluently."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "Bundle(%s)" % ", ".join(sorted(self.__dict__))


# ------------------------------------------------------------------- logical clock
def set_clock(client: ApiClient, to_iso8601: str) -> JsonObject:
    """Move the logical clock; the response reports the resulting clock as current_utc."""
    return get_success_data(client.set_clock(to_iso8601, make_carrier_admin_headers()))


# --------------------------------------------------------------- employer groups
def create_group(client: ApiClient, **overrides) -> JsonObject:
    """Create an employer group (PROSPECT)."""
    return get_success_data(
        client.create_employer_group(
            factories.employer_group_payload(**overrides), make_carrier_admin_headers()
        )
    )


def activate_group(client: ApiClient, group_id: ResourceId) -> JsonObject:
    return get_success_data(
        client.activate_employer_group(group_id, make_carrier_admin_headers())
    )


def create_active_group(client: ApiClient, **overrides) -> JsonObject:
    """Create + activate. Sensible zero-participation defaults so a bare campaign
    close is not participation-gated unless the caller overrides them."""
    overrides.setdefault("participation_minimum_pct", 0.0)
    overrides.setdefault("participation_minimum_count", 0)
    group = create_group(client, **overrides)
    return activate_group(client, group["id"])


def read_group(client: ApiClient, group_id: ResourceId) -> JsonObject:
    return get_success_data(client.get_employer_group(group_id, make_carrier_admin_headers()))


def group_version(client: ApiClient, group_id: ResourceId) -> int:
    return read_group(client, group_id)["version"]


# --------------------------------------------------------------------- counselors
def create_counselor(client: ApiClient, **overrides) -> JsonObject:
    """Onboard a counselor (ACTIVE)."""
    return get_success_data(
        client.create_benefit_counselor(
            factories.benefit_counselor_payload(**overrides),
            make_carrier_admin_headers(),
        )
    )


# -------------------------------------------- policy series and benefit schedules
def create_series(client: ApiClient, **overrides) -> JsonObject:
    return get_success_data(
        client.create_policy_series(
            factories.policy_series_payload(**overrides), make_carrier_admin_headers()
        )
    )


def create_schedule(client: ApiClient, series_id: ResourceId, **overrides) -> JsonObject:
    return get_success_data(
        client.create_benefit_schedule(
            factories.benefit_schedule_payload(series_id, **overrides),
            make_carrier_admin_headers(),
        )
    )


def publish_schedule(client: ApiClient, schedule_id: ResourceId, series_id: ResourceId) -> JsonObject:
    """Publish a schedule, re-reading the series for its current OCC version."""
    version = get_success_data(
        client.get_policy_series(series_id, make_carrier_admin_headers())
    )["version"]
    return get_success_data(
        client.publish_benefit_schedule(
            schedule_id, {"expected_series_version": version}, make_carrier_admin_headers()
        )
    )


def activate_series(client: ApiClient, series_id: ResourceId) -> JsonObject:
    return get_success_data(
        client.activate_policy_series(series_id, make_carrier_admin_headers())
    )


def create_active_series(client: ApiClient, series_overrides=None, schedule_overrides=None,
                         benefit_items=None) -> Bundle:
    """Series with one PUBLISHED schedule, activated. Returns (series, schedule)."""
    series = create_series(client, **(series_overrides or {}))
    schedule = create_schedule(
        client, series["id"], benefit_items=benefit_items, **(schedule_overrides or {})
    )
    publish_schedule(client, schedule["id"], series["id"])
    series = activate_series(client, series["id"])
    return Bundle(series=series, schedule=schedule)


# ------------------------------------------------------------------ campaigns
def create_campaign(client: ApiClient, group_id: ResourceId, counselor: JsonObject,
                    **overrides) -> JsonObject:
    """Create a campaign (DRAFT) filed by its lead counselor."""
    return get_success_data(
        client.create_enrollment_campaign(
            factories.enrollment_campaign_payload(group_id, counselor["id"], **overrides),
            make_counselor_headers(counselor["id"]),
        )
    )


def open_campaign(client: ApiClient, campaign_id: ResourceId, counselor: JsonObject) -> JsonObject:
    return get_success_data(
        client.open_enrollment_campaign(campaign_id, make_counselor_headers(counselor["id"]))
    )


def lock_campaign(client: ApiClient, campaign_id: ResourceId, counselor: JsonObject) -> JsonObject:
    return get_success_data(
        client.lock_enrollment_campaign(campaign_id, make_counselor_headers(counselor["id"]))
    )


def close_campaign(client: ApiClient, campaign_id: ResourceId, group_id: ResourceId,
                   counselor: JsonObject) -> JsonObject:
    """Close a campaign, re-reading the employer group for its current OCC version."""
    version = group_version(client, group_id)
    return get_success_data(
        client.close_enrollment_campaign(
            campaign_id, {"expected_group_version": version},
            make_counselor_headers(counselor["id"]),
        )
    )


def setup_open_campaign(client: ApiClient, group_overrides=None, schedule_overrides=None,
                        benefit_items=None, campaign_overrides=None) -> Bundle:
    """ACTIVE group + ACTIVE counselor + ACTIVE series with PUBLISHED schedule +
    OPEN campaign. The most common floor for policy and claim scenarios."""
    group = create_active_group(client, **(group_overrides or {}))
    counselor = create_counselor(client)
    series_bundle = create_active_series(
        client, schedule_overrides=schedule_overrides, benefit_items=benefit_items
    )
    campaign = create_campaign(
        client, group["id"], counselor, **(campaign_overrides or {})
    )
    campaign = open_campaign(client, campaign["id"], counselor)
    return Bundle(
        group=group,
        counselor=counselor,
        series=series_bundle.series,
        schedule=series_bundle.schedule,
        campaign=campaign,
    )


# --------------------------------------------------------------------- employees
def create_employee(client: ApiClient, group_id: ResourceId, **overrides) -> JsonObject:
    return get_success_data(
        client.create_employee(
            factories.employee_payload(group_id, **overrides),
            make_group_admin_headers(),
        )
    )


# ---------------------------------------------------------------------- policies
def apply_policy(client: ApiClient, campaign_id: ResourceId, employee_id: ResourceId,
                 series_id: ResourceId, counselor: JsonObject, **overrides) -> JsonObject:
    """File an application (APPLIED) under an OPEN campaign."""
    return get_success_data(
        client.create_policy(
            factories.policy_payload(campaign_id, employee_id, series_id, **overrides),
            make_counselor_headers(counselor["id"]),
        )
    )


def issue_policy(client: ApiClient, policy_id: ResourceId, counselor: JsonObject) -> JsonObject:
    return get_success_data(
        client.issue_policy(policy_id, make_counselor_headers(counselor["id"]))
    )


def activate_policy(client: ApiClient, policy_id: ResourceId, counselor: JsonObject) -> JsonObject:
    return get_success_data(
        client.activate_policy(policy_id, make_counselor_headers(counselor["id"]))
    )


def lapse_policy(client: ApiClient, policy_id: ResourceId, counselor: JsonObject) -> JsonObject:
    return get_success_data(
        client.lapse_policy(policy_id, make_counselor_headers(counselor["id"]))
    )


def read_policy(client: ApiClient, policy_id: ResourceId) -> JsonObject:
    return get_success_data(client.get_policy(policy_id, make_carrier_admin_headers()))


def setup_issued_policy(client: ApiClient, group_overrides=None, schedule_overrides=None,
                        benefit_items=None, campaign_overrides=None,
                        employee_overrides=None, policy_overrides=None) -> Bundle:
    """Open campaign + one employee + one policy issued directly. The floor for
    claim, wellness, and payroll scenarios."""
    base = setup_open_campaign(
        client,
        group_overrides=group_overrides,
        schedule_overrides=schedule_overrides,
        benefit_items=benefit_items,
        campaign_overrides=campaign_overrides,
    )
    employee = create_employee(client, base.group["id"], **(employee_overrides or {}))
    policy = apply_policy(
        client, base.campaign["id"], employee["id"], base.series["id"],
        base.counselor, **(policy_overrides or {}),
    )
    policy = issue_policy(client, policy["id"], base.counselor)
    base.employee = employee
    base.policy = policy
    return base


def setup_active_policy(client: ApiClient, **kwargs) -> Bundle:
    """setup_issued_policy + policy activated to ACTIVE."""
    base = setup_issued_policy(client, **kwargs)
    base.policy = activate_policy(client, base.policy["id"], base.counselor)
    return base


# ------------------------------------------------------------------------ claims
def submit_claim(client: ApiClient, policy_id: ResourceId, event_code: str,
                 **overrides) -> JsonObject:
    return get_success_data(
        client.create_claim(
            factories.claim_payload(policy_id, event_code, **overrides),
            make_claims_adjuster_headers(),
        )
    )


def review_claim(client: ApiClient, claim_id: ResourceId) -> JsonObject:
    return get_success_data(client.review_claim(claim_id, make_claims_adjuster_headers()))


def attach_document(client: ApiClient, claim_id: ResourceId, **overrides) -> JsonObject:
    return get_success_data(
        client.create_claim_document(
            factories.claim_document_payload(claim_id, **overrides),
            make_claims_adjuster_headers(),
        )
    )


def accept_document(client: ApiClient, document_id: ResourceId) -> JsonObject:
    return get_success_data(
        client.accept_claim_document(document_id, make_claims_adjuster_headers())
    )


def reject_document(client: ApiClient, document_id: ResourceId) -> JsonObject:
    return get_success_data(
        client.reject_claim_document(document_id, make_claims_adjuster_headers())
    )


def adjudicate_claim(client: ApiClient, claim_id: ResourceId, decision: str) -> JsonObject:
    return get_success_data(
        client.adjudicate_claim(claim_id, {"decision": decision}, make_claims_adjuster_headers())
    )


def pay_claim(client: ApiClient, claim_id: ResourceId) -> JsonObject:
    return get_success_data(client.pay_claim(claim_id, make_claims_adjuster_headers()))


def void_claim(client: ApiClient, claim_id: ResourceId) -> JsonObject:
    """Void an APPROVED or PAID claim, compensating the ledger when paid."""
    return get_success_data(client.void_claim(claim_id, make_claims_adjuster_headers()))


def approve_claim_with_document(client: ApiClient, claim_id: ResourceId,
                                doc_type: str = "DIAGNOSIS_PROOF") -> JsonObject:
    """Attach + accept one proof document, then adjudicate APPROVE. Assumes the
    claim is already UNDER_REVIEW."""
    document = attach_document(client, claim_id, doc_type=doc_type)
    accept_document(client, document["id"])
    return adjudicate_claim(client, claim_id, "APPROVE")


def pay_claim_full_cycle(client: ApiClient, claim_id: ResourceId) -> JsonObject:
    """review -> document -> approve -> pay. Assumes the claim is SUBMITTED."""
    review_claim(client, claim_id)
    approve_claim_with_document(client, claim_id)
    return pay_claim(client, claim_id)


def read_claim(client: ApiClient, claim_id: ResourceId) -> JsonObject:
    return get_success_data(client.get_claim(claim_id, make_claims_adjuster_headers()))


# ------------------------------------------------------------ wellness benefits
def submit_wellness(client: ApiClient, policy_id: ResourceId, **overrides) -> JsonObject:
    return get_success_data(
        client.create_wellness_benefit(
            factories.wellness_benefit_payload(policy_id, **overrides),
            make_claims_adjuster_headers(),
        )
    )


# ------------------------------------------------------------- payroll cycles
def create_payroll_cycle(client: ApiClient, group_id: ResourceId, **overrides) -> JsonObject:
    return get_success_data(
        client.create_payroll_cycle(
            factories.payroll_cycle_payload(group_id, **overrides),
            make_group_admin_headers(),
        )
    )


def finalize_payroll_cycle(client: ApiClient, cycle_id: ResourceId) -> JsonObject:
    return get_success_data(
        client.finalize_payroll_cycle(cycle_id, make_group_admin_headers())
    )


def list_cycle_lines(client: ApiClient, cycle_id: ResourceId) -> list:
    """All deduction lines of a cycle (single page; scenarios stay small)."""
    data = get_success_data(
        client.list_cycle_deduction_lines(cycle_id, make_group_admin_headers())
    )
    return data


def read_payroll_cycle(client: ApiClient, cycle_id: ResourceId) -> JsonObject:
    return get_success_data(client.get_payroll_cycle(cycle_id, make_group_admin_headers()))


__all__ = [
    "Bundle",
    "set_clock",
    "create_group",
    "activate_group",
    "create_active_group",
    "read_group",
    "group_version",
    "create_counselor",
    "create_series",
    "create_schedule",
    "publish_schedule",
    "activate_series",
    "create_active_series",
    "create_campaign",
    "open_campaign",
    "lock_campaign",
    "close_campaign",
    "setup_open_campaign",
    "create_employee",
    "apply_policy",
    "issue_policy",
    "activate_policy",
    "lapse_policy",
    "read_policy",
    "setup_issued_policy",
    "setup_active_policy",
    "submit_claim",
    "review_claim",
    "attach_document",
    "accept_document",
    "reject_document",
    "adjudicate_claim",
    "pay_claim",
    "approve_claim_with_document",
    "pay_claim_full_cycle",
    "read_claim",
    "submit_wellness",
    "create_payroll_cycle",
    "finalize_payroll_cycle",
    "list_cycle_lines",
    "read_payroll_cycle",
]
