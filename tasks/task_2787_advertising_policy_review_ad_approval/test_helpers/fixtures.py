"""Composite setup helpers.

Every helper here drives the API exactly as a client would, using only the
endpoints the PRD declares. The harness restarts the service before each test, so
each helper builds all of its preconditions from an empty database with the
logical clock at its declared start instant.

Server-authored rows never appear in the response of the call that created them,
so the helpers that need them re-read them from the list endpoint the PRD
nominates: review tasks by `ad_creative_id`, disapproval notices by
`ad_creative_id`, appeals by `disapproval_notice_id`, enforcement actions and
ledger entries by advertiser.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_START_INSTANT
from .test_users import ADMIN, ANALYST, make_advertiser_headers, make_reviewer_headers


# ---------------------------------------------------------------------------
# Tier 0 - the logical clock and the sweep (PRD §2.8)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers: Dict = ADMIN) -> dict:
    """Advance the logical clock and return `{current_utc, previous_utc}`."""
    return get_success_data(
        api_client.set_clock(factories.set_clock_payload(to_iso8601), headers)
    )


def run_sweep(headers: Dict = ADMIN) -> dict:
    """Run the deterministic policy sweep and return its counter block."""
    return get_success_data(api_client.run_policy_sweep(headers))


def advance_clock_and_sweep(to_iso8601: str, headers: Dict = ADMIN) -> dict:
    """Move the clock forward then run the sweep at the new instant."""
    set_clock(to_iso8601, headers)
    return run_sweep(headers)


# ---------------------------------------------------------------------------
# Tier 1 - single rows in their initial state
# ---------------------------------------------------------------------------
def create_policy_rule(
    code: str,
    category_class: str = "RESTRICTED",
    base_severity_weight: float = 6.00,
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_policy_rule(
            factories.create_policy_rule_payload(
                code, category_class, base_severity_weight, **overrides
            ),
            headers,
        )
    )


def read_policy_rule(policy_rule_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_policy_rule(policy_rule_id, headers))


def add_country_override(
    policy_rule_id: str,
    country_code: str,
    disposition: str = "RESTRICTED_CERT_REQUIRED",
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_country_override(
            policy_rule_id,
            factories.create_country_override_payload(
                country_code, disposition, **overrides
            ),
            headers,
        )
    )


def create_advertiser(headers: Dict = ADMIN, **overrides) -> dict:
    return get_success_data(
        api_client.create_advertiser(
            factories.create_advertiser_payload(**overrides), headers
        )
    )


def read_advertiser(advertiser_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_advertiser(advertiser_id, headers))


def record_verification(
    advertiser_id: str,
    dimension: str,
    outcome: str,
    evidence_ref: Optional[str] = None,
    headers: Dict = ADMIN,
) -> dict:
    return get_success_data(
        api_client.record_verification(
            advertiser_id,
            factories.record_verification_payload(dimension, outcome, evidence_ref),
            headers,
        )
    )


def verify_advertiser_core_axes(advertiser_id: str, headers: Dict = ADMIN) -> dict:
    """Bring `identity_status` and `business_standing_status` to `VERIFIED`.

    PRD §3.4 clause 4 routes a creative to manual review while either axis is
    anything other than `VERIFIED`, so an advertiser that is meant to auto-approve
    must pass through both verifications first.
    """
    record_verification(advertiser_id, "IDENTITY", "VERIFIED", headers=headers)
    return record_verification(
        advertiser_id, "BUSINESS_STANDING", "VERIFIED", headers=headers
    )


def create_verified_advertiser(headers: Dict = ADMIN, **overrides) -> dict:
    """An advertiser whose identity and business standing are both `VERIFIED`."""
    advertiser = create_advertiser(headers=headers, **overrides)
    return verify_advertiser_core_axes(advertiser["id"], headers=headers)


def create_reviewer(
    queue_specialties: Optional[Sequence[str]] = None,
    country_authorizations: Optional[Sequence[str]] = None,
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_reviewer(
            factories.create_reviewer_payload(
                queue_specialties, country_authorizations, **overrides
            ),
            headers,
        )
    )


def read_reviewer(reviewer_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_reviewer(reviewer_id, headers))


def patch_reviewer(reviewer_id: str, headers: Dict = ADMIN, **fields) -> dict:
    return get_success_data(
        api_client.update_reviewer(
            reviewer_id, factories.update_reviewer_payload(**fields), headers
        )
    )


def create_creative(
    advertiser_id: str,
    declared_category_codes: Optional[Sequence[str]] = None,
    target_country_codes: Optional[Sequence[str]] = None,
    headers: Optional[Dict] = None,
    **overrides,
) -> dict:
    """Create a DRAFT creative as its owning advertiser."""
    return get_success_data(
        api_client.create_ad_creative(
            factories.create_ad_creative_payload(
                advertiser_id,
                declared_category_codes,
                target_country_codes,
                **overrides,
            ),
            headers or make_advertiser_headers(advertiser_id),
        )
    )


def read_creative(
    ad_creative_id: str, headers: Optional[Dict] = None, advertiser_id: Optional[str] = None
) -> dict:
    return get_success_data(
        api_client.get_ad_creative(
            ad_creative_id,
            headers
            or (make_advertiser_headers(advertiser_id) if advertiser_id else ADMIN),
        )
    )


def submit_creative(
    ad_creative_id: str, advertiser_id: str, headers: Optional[Dict] = None
) -> dict:
    return get_success_data(
        api_client.submit_ad_creative(
            ad_creative_id, headers or make_advertiser_headers(advertiser_id)
        )
    )


def withdraw_creative(
    ad_creative_id: str, advertiser_id: str, headers: Optional[Dict] = None
) -> dict:
    return get_success_data(
        api_client.withdraw_ad_creative(
            ad_creative_id, headers or make_advertiser_headers(advertiser_id)
        )
    )


def revise_creative(
    ad_creative_id: str,
    advertiser_id: str,
    headers: Optional[Dict] = None,
    **fields,
) -> dict:
    return get_success_data(
        api_client.revise_ad_creative(
            ad_creative_id,
            factories.revise_ad_creative_payload(**fields),
            headers or make_advertiser_headers(advertiser_id),
        )
    )


def create_certification(
    advertiser_id: str,
    policy_rule_id: str,
    valid_from: str = CLOCK_START_INSTANT,
    valid_until: str = "2027-08-01T00:00:00.000Z",
    issuing_country_code: str = "US",
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_certification(
            factories.create_certification_payload(
                advertiser_id,
                policy_rule_id,
                valid_from,
                valid_until,
                issuing_country_code,
                **overrides,
            ),
            headers,
        )
    )


def read_certification(certification_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_certification(certification_id, headers))


def revoke_certification(
    certification_id: str,
    revocation_reason: str = "License withdrawn",
    headers: Dict = ADMIN,
) -> dict:
    return get_success_data(
        api_client.revoke_certification(
            certification_id,
            factories.revoke_certification_payload(revocation_reason),
            headers,
        )
    )


def mint_enforcement_action(
    advertiser_id: str,
    action_type: str,
    expected_advertiser_version: int,
    headers: Dict = ADMIN,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_enforcement_action(
            advertiser_id,
            factories.create_enforcement_action_payload(
                action_type, expected_advertiser_version, **overrides
            ),
            headers,
        )
    )


def record_destination_check(
    ad_creative_id: str,
    fetched_final_url: str,
    check_type: str = "INITIAL",
    user_agent_variant: str = "CRAWLER",
    fetched_content_category: str = "GENERAL",
    http_status: int = 200,
    headers: Dict = ANALYST,
) -> dict:
    return get_success_data(
        api_client.create_destination_check(
            ad_creative_id,
            factories.create_destination_check_payload(
                fetched_final_url,
                check_type,
                user_agent_variant,
                fetched_content_category,
                http_status,
            ),
            headers,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 - reading back the rows the service authors on its own
# ---------------------------------------------------------------------------
def list_tasks_for_creative(
    ad_creative_id: str, headers: Dict = ADMIN, **params
) -> List[dict]:
    """Review tasks are never client-created, so they are read back by creative."""
    query = {"ad_creative_id": ad_creative_id}
    query.update(params)
    return get_success_data(api_client.list_review_tasks(headers, query))


def only_task_for_creative(ad_creative_id: str, headers: Dict = ADMIN) -> dict:
    tasks = list_tasks_for_creative(ad_creative_id, headers)
    assert len(tasks) == 1, f"expected exactly one review task, got {len(tasks)}"
    return tasks[0]


def open_task_for_creative(ad_creative_id: str, headers: Dict = ADMIN) -> dict:
    """The single QUEUED or CLAIMED task on a creative."""
    tasks = [
        task
        for task in list_tasks_for_creative(ad_creative_id, headers)
        if task["status"] in ("QUEUED", "CLAIMED")
    ]
    assert len(tasks) == 1, f"expected exactly one open review task, got {len(tasks)}"
    return tasks[0]


def newest_task_for_creative(ad_creative_id: str, headers: Dict = ADMIN) -> dict:
    tasks = list_tasks_for_creative(ad_creative_id, headers)
    assert tasks, "expected at least one review task"
    return sorted(tasks, key=lambda task: task["created_at"])[-1]


def read_task(review_task_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_review_task(review_task_id, headers))


def list_notices_for_creative(
    ad_creative_id: str, headers: Dict = ADMIN, **params
) -> List[dict]:
    query = {"ad_creative_id": ad_creative_id}
    query.update(params)
    return get_success_data(api_client.list_disapproval_notices(headers, query))


def only_notice_for_creative(ad_creative_id: str, headers: Dict = ADMIN) -> dict:
    notices = list_notices_for_creative(ad_creative_id, headers)
    assert len(notices) == 1, f"expected exactly one notice, got {len(notices)}"
    return notices[0]


def newest_notice_for_creative(ad_creative_id: str, headers: Dict = ADMIN) -> dict:
    notices = list_notices_for_creative(ad_creative_id, headers)
    assert notices, "expected at least one disapproval notice"
    return sorted(notices, key=lambda notice: notice["created_at"])[-1]


def read_notice(notice_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_disapproval_notice(notice_id, headers))


def read_appeal(appeal_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, headers))


def ledger_for_advertiser(advertiser_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    return get_success_data(
        api_client.list_advertiser_ledger_entries(advertiser_id, headers, params or None)
    )


def ledger_for_notice(notice_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    return get_success_data(
        api_client.list_notice_ledger_entries(notice_id, headers, params or None)
    )


def actions_for_advertiser(advertiser_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    query = {"advertiser_id": advertiser_id}
    query.update(params)
    return get_success_data(api_client.list_enforcement_actions(headers, query))


def read_action(enforcement_action_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(
        api_client.get_enforcement_action(enforcement_action_id, headers)
    )


def in_force_action(advertiser_id: str, headers: Dict = ADMIN) -> Optional[dict]:
    actions = actions_for_advertiser(advertiser_id, headers, status="ACTIVE")
    return actions[0] if actions else None


def archive_entries_for_creative(
    ad_creative_id: str, headers: Dict = ADMIN, **params
) -> List[dict]:
    return get_success_data(
        api_client.list_creative_archive_entries(
            ad_creative_id, headers, params or None
        )
    )


def archive_entries_for_advertiser(
    advertiser_id: str, headers: Dict = ADMIN, **params
) -> List[dict]:
    return get_success_data(
        api_client.list_advertiser_archive_entries(
            advertiser_id, headers, params or None
        )
    )


def runs_for_creative(ad_creative_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    return get_success_data(
        api_client.list_screening_runs(ad_creative_id, headers, params or None)
    )


def decisions_for_run(screening_run_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    return get_success_data(
        api_client.list_run_classifier_decisions(
            screening_run_id, headers, params or None
        )
    )


def decisions_by_rule(policy_rule_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    return get_success_data(
        api_client.list_rule_classifier_decisions(
            policy_rule_id, headers, params or None
        )
    )


def checks_for_creative(ad_creative_id: str, headers: Dict = ADMIN, **params) -> List[dict]:
    return get_success_data(
        api_client.list_destination_checks(ad_creative_id, headers, params or None)
    )


# ---------------------------------------------------------------------------
# Tier 3 - lifecycle shortcuts
# ---------------------------------------------------------------------------
def screen_creative(
    ad_creative_id: str,
    decisions: Sequence[Tuple[str, float]],
    expected_ad_creative_version: int,
    classifier_version: Optional[str] = None,
    headers: Dict = ADMIN,
) -> dict:
    """Ingest one screening run from `(policy_rule_id, confidence)` pairs."""
    payload_decisions = [
        factories.classifier_decision_payload(rule_id, confidence)
        for rule_id, confidence in decisions
    ]
    return get_success_data(
        api_client.create_screening_run(
            ad_creative_id,
            factories.create_screening_run_payload(
                payload_decisions, expected_ad_creative_version, classifier_version
            ),
            headers,
        )
    )


def submitted_creative(
    advertiser_id: str,
    declared_category_codes: Sequence[str],
    target_country_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> dict:
    """A creative taken from DRAFT to SCREENING by its owner."""
    creative = create_creative(
        advertiser_id, declared_category_codes, target_country_codes, **overrides
    )
    return submit_creative(creative["id"], advertiser_id)


def screened_creative(
    advertiser_id: str,
    declared_category_codes: Sequence[str],
    decisions: Sequence[Tuple[str, float]],
    target_country_codes: Optional[Sequence[str]] = None,
    classifier_version: Optional[str] = None,
    **overrides,
) -> Tuple[dict, dict]:
    """Create, submit and screen a creative; return `(creative, screening_run)`."""
    submitted = submitted_creative(
        advertiser_id, declared_category_codes, target_country_codes, **overrides
    )
    run = screen_creative(
        submitted["id"],
        decisions,
        submitted["version"],
        classifier_version=classifier_version,
    )
    return read_creative(submitted["id"], advertiser_id=advertiser_id), run


def creative_in_manual_review(
    advertiser_id: str,
    declared_category_codes: Sequence[str],
    decisions: Sequence[Tuple[str, float]],
    target_country_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> Tuple[dict, dict]:
    """A creative routed to PENDING_MANUAL_REVIEW; returns `(creative, task)`."""
    creative, _run = screened_creative(
        advertiser_id,
        declared_category_codes,
        decisions,
        target_country_codes,
        **overrides,
    )
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW", (
        f"expected PENDING_MANUAL_REVIEW, got {creative['review_status']}"
    )
    return creative, only_task_for_creative(creative["id"])


def claim_task(review_task_id: str, reviewer_id: str) -> dict:
    return get_success_data(
        api_client.claim_review_task(review_task_id, make_reviewer_headers(reviewer_id))
    )


def release_task(review_task_id: str, reviewer_id: str) -> dict:
    return get_success_data(
        api_client.release_review_task(
            review_task_id, make_reviewer_headers(reviewer_id)
        )
    )


def requeue_task(review_task_id: str, headers: Dict = ADMIN) -> dict:
    return get_success_data(api_client.requeue_review_task(review_task_id, headers))


def decide_task(
    review_task_id: str,
    reviewer_id: str,
    resolution: str,
    reason_codes: Optional[Sequence[str]] = None,
    limited_country_codes: Optional[Sequence[str]] = None,
    note: Optional[str] = None,
) -> dict:
    return get_success_data(
        api_client.decide_review_task(
            review_task_id,
            factories.decide_review_task_payload(
                resolution, reason_codes, limited_country_codes, note
            ),
            make_reviewer_headers(reviewer_id),
        )
    )


def claimed_task(
    advertiser_id: str,
    declared_category_codes: Sequence[str],
    decisions: Sequence[Tuple[str, float]],
    reviewer_id: str,
    target_country_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> Tuple[dict, dict]:
    """A creative in manual review whose only task is CLAIMED by `reviewer_id`."""
    creative, task = creative_in_manual_review(
        advertiser_id,
        declared_category_codes,
        decisions,
        target_country_codes,
        **overrides,
    )
    return creative, claim_task(task["id"], reviewer_id)


# ---------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# ---------------------------------------------------------------------------
def disapproved_by_reviewer(
    advertiser_id: str,
    declared_category_codes: Sequence[str],
    decisions: Sequence[Tuple[str, float]],
    reviewer_id: str,
    reason_codes: Sequence[str] = ("MANUAL_REVIEW",),
    target_country_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> Tuple[dict, dict, dict]:
    """Drive a creative all the way to a reviewer disapproval.

    Returns `(creative, task, notice)` where the notice is the one the six-hop
    cascade wrote.
    """
    creative, task = claimed_task(
        advertiser_id,
        declared_category_codes,
        decisions,
        reviewer_id,
        target_country_codes,
        **overrides,
    )
    resolved = decide_task(
        task["id"], reviewer_id, "DISAPPROVE", reason_codes=list(reason_codes)
    )
    notice = newest_notice_for_creative(creative["id"])
    return read_creative(creative["id"], advertiser_id=advertiser_id), resolved, notice


def auto_disapproved_creative(
    advertiser_id: str,
    declared_category_codes: Sequence[str],
    decisions: Sequence[Tuple[str, float]],
    target_country_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> Tuple[dict, dict, dict]:
    """A creative auto-disapproved by screening; returns `(creative, run, notice)`."""
    creative, run = screened_creative(
        advertiser_id,
        declared_category_codes,
        decisions,
        target_country_codes,
        **overrides,
    )
    assert run["outcome"] == "AUTO_DISAPPROVED", (
        f"expected AUTO_DISAPPROVED, got {run['outcome']}"
    )
    return creative, run, newest_notice_for_creative(creative["id"])


def file_appeal(
    notice_id: str,
    advertiser_id: str,
    justification: Optional[str] = None,
    evidence_certification_id: Optional[str] = None,
) -> dict:
    return get_success_data(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notice_id, justification, evidence_certification_id
            ),
            make_advertiser_headers(advertiser_id),
        )
    )


def decide_appeal(
    appeal_id: str, reviewer_id: str, outcome: str, note: Optional[str] = None
) -> dict:
    return get_success_data(
        api_client.decide_appeal(
            appeal_id,
            factories.decide_appeal_payload(outcome, note),
            make_reviewer_headers(reviewer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 5 - whole-scenario builders
# ---------------------------------------------------------------------------
def basic_policy_framework(
    prohibited_code: str = "TOBACCO",
    restricted_code: str = "ALC_SPIRITS",
    regulated_code: str = "FIN_CREDIT",
) -> Dict[str, dict]:
    """One rule per category class, all on default thresholds and queues."""
    return {
        "prohibited": create_policy_rule(prohibited_code, "PROHIBITED", 12.00),
        "restricted": create_policy_rule(restricted_code, "RESTRICTED", 6.00),
        "regulated": create_policy_rule(regulated_code, "REGULATED", 3.00),
    }


def reviewer_for_queue(
    queue: str = "STANDARD",
    countries: Sequence[str] = ("US",),
    max_concurrent_claims: Optional[int] = None,
    display_name: Optional[str] = None,
) -> dict:
    overrides: Dict = {}
    if max_concurrent_claims is not None:
        overrides["max_concurrent_claims"] = max_concurrent_claims
    if display_name is not None:
        overrides["display_name"] = display_name
    return create_reviewer([queue], list(countries), **overrides)


def all_queue_reviewer(
    countries: Sequence[str] = ("US",),
    max_concurrent_claims: Optional[int] = None,
    display_name: Optional[str] = None,
) -> dict:
    """A reviewer specialised in all three queues - useful when the queue the
    routing rule picks is not the point of the test."""
    overrides: Dict = {}
    if max_concurrent_claims is not None:
        overrides["max_concurrent_claims"] = max_concurrent_claims
    if display_name is not None:
        overrides["display_name"] = display_name
    return create_reviewer(
        ["STANDARD", "REGULATED_CERT", "POLITICAL"], list(countries), **overrides
    )


def advertiser_at_account_status(
    status: str, headers: Dict = ADMIN, **overrides
) -> dict:
    """An advertiser driven to `WARNED`, `RESTRICTED` or `SUSPENDED` posture.

    PRD §3.2 derives `account_status` from the in-force enforcement action, and
    PRD §3.9 lets a manual mint choose the action type outright, so the shortest
    path to a posture is one manual action of the matching type.
    """
    advertiser = create_advertiser(headers=headers, **overrides)
    if status == "ACTIVE":
        return advertiser
    action_type = {
        "WARNED": "WARNING",
        "RESTRICTED": "RESTRICTION",
        "SUSPENDED": "SUSPENSION",
    }[status]
    mint_enforcement_action(
        advertiser["id"], action_type, advertiser["version"], headers=headers
    )
    return read_advertiser(advertiser["id"], headers=headers)
