"""Composite state builders.

The server is relaunched before every test, so each test starts against an empty
database and builds whatever state it needs exclusively through the PRD's own
endpoints. Setup steps read their response through get_success_data(), which is
lenient about the exact 2xx code; the assertions that matter belong in the test.

Every builder that ends in an optimistic-concurrency-bearing call re-reads the
parent row immediately beforehand, because PRD §2.10 refuses a stale
expected_seller_version or expected_enforcement_action_version outright.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .assertions import shift
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    action_payload,
    adjudication_payload,
    appeal_decision_payload,
    appeal_payload,
    clock_payload,
    credit_payload,
    escalation_payload,
    forfeit_payload,
    hold_payload,
    listing_payload,
    poa_payload,
    poa_review_payload,
    policy_rule_payload,
    release_payload,
    seller_payload,
    snapshot_payload,
    violation_payload,
)
from .test_users import (
    ANONYMOUS,
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    REVIEWER_ALT,
    make_seller_headers,
)


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, instant: str, headers: Optional[Dict[str, str]] = None) -> None:
    """PRD §2.4: a ComplianceOfficer sets the logical clock to to_iso8601."""
    get_success_data(api.set_clock(clock_payload(instant), headers or OFFICER))


# --------------------------------------------------------------------------
# Sellers and money
# --------------------------------------------------------------------------
def register_seller(api, **kwargs) -> Dict[str, Any]:
    """PRD §3.1: registration is the one operation an Anonymous caller performs."""
    return get_success_data(api.register_seller(seller_payload(**kwargs), ANONYMOUS))


def read_seller(api, seller_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_seller(seller_id, headers or OFFICER))


def credit(api, seller_id: str, amount_cents: int,
           external_reference: Optional[str] = None,
           headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.credit_proceeds(
            seller_id, credit_payload(amount_cents, external_reference), headers or OFFICER
        )
    )


def funded_seller(api, amount_cents: int = 100000, **kwargs) -> Dict[str, Any]:
    """A registered seller carrying settled proceeds."""
    seller = register_seller(api, **kwargs)
    return credit(api, seller["id"], amount_cents)


# --------------------------------------------------------------------------
# Policy catalogue and listings
# --------------------------------------------------------------------------
def publish_rule(api, headers: Optional[Dict[str, str]] = None,
                 **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_policy_rule(policy_rule_payload(**kwargs), headers or OFFICER)
    )


def create_listing(api, seller_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_listing(listing_payload(seller_id, **kwargs), make_seller_headers(seller_id))
    )


def read_listings(api, seller_id: str, headers: Optional[Dict[str, str]] = None,
                  params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_seller_listings(seller_id, headers or OFFICER, params)
    )


# --------------------------------------------------------------------------
# Snapshots and evaluations
# --------------------------------------------------------------------------
def file_snapshot(api, seller_id: str, window_start: str, window_end: str,
                  headers: Optional[Dict[str, str]] = None, **counters) -> Dict[str, Any]:
    return get_success_data(
        api.create_snapshot(
            snapshot_payload(seller_id, window_start, window_end, **counters),
            headers or OFFICER,
        )
    )


def evaluate(api, seller_id: str,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.4: evaluation takes no payload whatsoever."""
    return get_success_data(api.create_health_evaluation(seller_id, headers or OFFICER))


# --------------------------------------------------------------------------
# Violations
# --------------------------------------------------------------------------
def file_violation(api, seller_id: str, policy_rule_id: str,
                   headers: Optional[Dict[str, str]] = None, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_violation(
            violation_payload(seller_id, policy_rule_id, **kwargs), headers or INVESTIGATOR
        )
    )


def open_investigation(api, violation_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.open_investigation(violation_id, headers or INVESTIGATOR))


def adjudicate(api, violation_id: str, outcome: str, decision_note: Optional[str] = None,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_violation(
            violation_id, adjudication_payload(outcome, decision_note), headers or INVESTIGATOR
        )
    )


def substantiated_violation(api, seller_id: str, policy_rule_id: str,
                            decision_note: Optional[str] = None,
                            headers: Optional[Dict[str, str]] = None,
                            **kwargs) -> Dict[str, Any]:
    """PRD §3.5: REPORTED -> UNDER_INVESTIGATION -> SUBSTANTIATED."""
    actor = headers or INVESTIGATOR
    violation = file_violation(api, seller_id, policy_rule_id, headers=actor, **kwargs)
    open_investigation(api, violation["id"], actor)
    return adjudicate(api, violation["id"], "SUBSTANTIATED", decision_note, actor)


# --------------------------------------------------------------------------
# Enforcement actions
# --------------------------------------------------------------------------
def issue_action(api, violation_id: str, action_type_override: Optional[str] = None,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.create_enforcement_action(
            action_payload(violation_id, action_type_override), headers or INVESTIGATOR
        )
    )


def read_action(api, action_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_enforcement_action(action_id, headers or INVESTIGATOR))


def acknowledge(api, action_id: str, seller_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.acknowledge_action(action_id, make_seller_headers(seller_id))
    )


def issued_action(api, seller_id: str, rule: Optional[Dict[str, Any]] = None,
                  action_type_override: Optional[str] = None,
                  decision_note: Optional[str] = None,
                  investigator: Optional[Dict[str, str]] = None,
                  **violation_kwargs) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Publish a rule if needed, drive a violation to SUBSTANTIATED and issue.

    Returns the (rule, violation, action) triple.
    """
    actor = investigator or INVESTIGATOR
    rule = rule if rule is not None else publish_rule(api)
    violation = substantiated_violation(
        api, seller_id, rule["id"], decision_note=decision_note, headers=actor,
        **violation_kwargs
    )
    action = issue_action(api, violation["id"], action_type_override, actor)
    return rule, violation, action


# --------------------------------------------------------------------------
# Plans of action
# --------------------------------------------------------------------------
def submit_poa(api, action_id: str, seller_id: str,
               expected_version: Optional[int] = None, **kwargs) -> Dict[str, Any]:
    """Re-reads the action's version unless the caller pins one deliberately."""
    if expected_version is None:
        expected_version = get_success_data(
            api.get_enforcement_action(action_id, make_seller_headers(seller_id))
        )["version"]
    return get_success_data(
        api.create_plan_of_action(
            poa_payload(action_id, expected_version, **kwargs), make_seller_headers(seller_id)
        )
    )


def review_poa(api, poa_id: str, decision: str, review_notes: Optional[str] = None,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.review_plan_of_action(
            poa_id, poa_review_payload(decision, review_notes), headers or OFFICER
        )
    )


def accepted_poa(api, action_id: str, seller_id: str,
                 reviewer: Optional[Dict[str, str]] = None,
                 review_notes: str = "The plan addresses the root cause and is accepted.",
                 **kwargs) -> Dict[str, Any]:
    poa = submit_poa(api, action_id, seller_id, **kwargs)
    return review_poa(api, poa["id"], "ACCEPT", review_notes, reviewer or OFFICER)


# --------------------------------------------------------------------------
# Appeals
# --------------------------------------------------------------------------
def file_appeal(api, action_id: str, seller_id: str,
                plan_of_action_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.create_appeal(
            appeal_payload(action_id, plan_of_action_id, **kwargs),
            make_seller_headers(seller_id),
        )
    )


def start_review(api, appeal_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.start_appeal_review(appeal_id, headers or REVIEWER))


def decide_appeal(api, appeal_id: str, outcome: str, denial_reason: Optional[str] = None,
                  rationale: Optional[str] = None,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.decide_appeal(
            appeal_id, appeal_decision_payload(outcome, denial_reason, rationale),
            headers or REVIEWER_ALT,
        )
    )


def denied_appeal(api, action_id: str, seller_id: str,
                  plan_of_action_id: Optional[str] = None,
                  denial_reason: str = "EVIDENCE_UPHELD",
                  reviewer: Optional[Dict[str, str]] = None,
                  decider: Optional[Dict[str, str]] = None,
                  **kwargs) -> Dict[str, Any]:
    """PRD §3.8: SUBMITTED -> UNDER_REVIEW -> DENIED."""
    appeal = file_appeal(api, action_id, seller_id, plan_of_action_id, **kwargs)
    start_review(api, appeal["id"], reviewer or REVIEWER)
    return decide_appeal(
        api, appeal["id"], "DENIED", denial_reason, headers=decider or REVIEWER
    )


def granted_appeal(api, action_id: str, seller_id: str,
                   plan_of_action_id: Optional[str] = None,
                   reviewer: Optional[Dict[str, str]] = None,
                   decider: Optional[Dict[str, str]] = None,
                   rationale: Optional[str] = None,
                   **kwargs) -> Dict[str, Any]:
    appeal = file_appeal(api, action_id, seller_id, plan_of_action_id, **kwargs)
    start_review(api, appeal["id"], reviewer or REVIEWER)
    return decide_appeal(
        api, appeal["id"], "GRANTED", rationale=rationale, headers=decider or REVIEWER_ALT
    )


def escalate(api, appeal_id: str, seller_id: str, **kwargs) -> Dict[str, Any]:
    return get_success_data(
        api.escalate_appeal(
            appeal_id, escalation_payload(**kwargs), make_seller_headers(seller_id)
        )
    )


def decide_escalation(api, appeal_id: str, outcome: str,
                      denial_reason: Optional[str] = None,
                      rationale: Optional[str] = None,
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.decide_escalation(
            appeal_id, appeal_decision_payload(outcome, denial_reason, rationale),
            headers or OFFICER,
        )
    )


# --------------------------------------------------------------------------
# Disbursement holds
# --------------------------------------------------------------------------
def open_hold(api, seller_id: str, coverage_start: str, coverage_end: str,
              reserve_basis: str = "ROLLING",
              enforcement_action_id: Optional[str] = None,
              hold_type: str = "RESERVE",
              expected_version: Optional[int] = None,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Re-reads the seller's version immediately before the OCC-bearing call."""
    actor = headers or INVESTIGATOR
    if expected_version is None:
        expected_version = read_seller(api, seller_id, actor)["version"]
    return get_success_data(
        api.create_hold(
            hold_payload(
                seller_id, coverage_start, coverage_end, expected_version,
                enforcement_action_id=enforcement_action_id, hold_type=hold_type,
                reserve_basis=reserve_basis,
            ),
            actor,
        )
    )


def release_hold(api, hold_id: str, release_reason: str = "MANUAL",
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.release_hold(hold_id, release_payload(release_reason), headers or OFFICER)
    )


def forfeit_hold(api, hold_id: str, forfeited_amount_cents: int,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.forfeit_hold(hold_id, forfeit_payload(forfeited_amount_cents), headers or OFFICER)
    )


def read_holds(api, headers: Optional[Dict[str, str]] = None,
               params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api.list_holds(headers or OFFICER, params))


def coverage(start_offset_days: int = 1, length_days: int = 7,
             anchor: str = DEFAULT_CLOCK_UTC) -> Tuple[str, str]:
    """A closed coverage interval expressed as days from an anchor instant."""
    start = shift(anchor, days=start_offset_days)
    return start, shift(start, days=length_days)


# --------------------------------------------------------------------------
# Postures worth reaching
# --------------------------------------------------------------------------
def seller_under_investigation(api, amount_cents: int = 100000,
                               rule: Optional[Dict[str, Any]] = None,
                               **seller_kwargs) -> Tuple[Dict[str, Any], Dict[str, Any],
                                                         Dict[str, Any]]:
    """A funded seller with one violation UNDER_INVESTIGATION, which per §3.9
    drives the funds dimension to RESERVE_HELD and authorises reserve holds.

    Returns the (seller, rule, violation) triple.
    """
    seller = funded_seller(api, amount_cents, **seller_kwargs)
    rule = rule if rule is not None else publish_rule(api)
    violation = file_violation(api, seller["id"], rule["id"])
    open_investigation(api, violation["id"])
    return read_seller(api, seller["id"]), rule, violation


def suspended_seller(api, amount_cents: int = 100000,
                     base_severity_weight: float = 8.00,
                     rule_kwargs: Optional[Dict[str, Any]] = None,
                     **seller_kwargs) -> Tuple[Dict[str, Any], Dict[str, Any],
                                               Dict[str, Any], Dict[str, Any]]:
    """A seller carrying a single twelve-point action, which per §3.6 selects
    ACCOUNT_SUSPENSION and per §3.9 sweeps the funds into FULL_HOLD.

    PRD §3.2 caps `base_severity_weight` at 8.00, so twelve points are reached the
    only way a first offence can reach them: PRD §3.6's rights-owner escalation
    multiplies an INTELLECTUAL_PROPERTY rule cited by a RIGHTS_OWNER by 1.50, and
    8.00 x 1.00 x 1.50 = 12.00.

    Returns the (seller, rule, violation, action) quadruple.
    """
    seller = funded_seller(api, amount_cents, **seller_kwargs)
    rule_fields: Dict[str, Any] = {"category": "INTELLECTUAL_PROPERTY"}
    rule_fields.update(rule_kwargs or {})
    rule = publish_rule(api, base_severity_weight=base_severity_weight, **rule_fields)
    rule, violation, action = issued_action(
        api, seller["id"], rule=rule, reporter_type="RIGHTS_OWNER"
    )
    return read_seller(api, seller["id"]), rule, violation, action


def banned_seller_via_escalation(api, amount_cents: int = 100000,
                                 **seller_kwargs) -> Tuple[Dict[str, Any], Dict[str, Any],
                                                           Dict[str, Any]]:
    """PRD §3.8: a FINAL_DENIED escalation against a suspension bans the seller
    with ban_reason ESCALATION_EXHAUSTED.

    Returns the (seller, action, appeal) triple.
    """
    seller, rule, violation, action = suspended_seller(api, amount_cents, **seller_kwargs)
    poa = accepted_poa(api, action["id"], seller["id"])
    appeal = denied_appeal(api, action["id"], seller["id"], poa["id"])
    escalate(api, appeal["id"], seller["id"])
    appeal = decide_escalation(
        api, appeal["id"], "FINAL_DENIED", "EVIDENCE_UPHELD", headers=OFFICER
    )
    return read_seller(api, seller["id"]), read_action(api, action["id"]), appeal


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
def read_notices(api, seller_id: str, headers: Optional[Dict[str, str]] = None,
                 params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(
        api.list_seller_notifications(seller_id, headers or OFFICER, params)
    )
