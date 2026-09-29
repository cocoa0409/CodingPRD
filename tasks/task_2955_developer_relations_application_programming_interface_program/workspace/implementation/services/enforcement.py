"""Violation cases: penalty points, standing cascades and revocation."""
from datetime import timedelta

from constants import (
    APPEAL_WINDOW_DAYS,
    CATEGORY_BASE_POINTS,
    LIVE_CASE_STATES,
    REMEDIATION_DAYS,
    RESTRICTION_THRESHOLD,
    REVOCATION_THRESHOLD,
    SEVERITY_FACTOR,
)
from db import store

from . import quota
from .common import assignments_of_developer


def penalty_points_for(category, severity):
    return CATEGORY_BASE_POINTS[category] * SEVERITY_FACTOR[severity]


def cases_of_developer(developer_id):
    return [
        c
        for c in store.ordered(store.violation_cases)
        if c["developer_id"] == developer_id
    ]


def has_live_case(developer_id, excluding_case_id=None):
    for case in store.violation_cases.values():
        if case["developer_id"] != developer_id:
            continue
        if excluding_case_id is not None and case["id"] == excluding_case_id:
            continue
        if case["state"] in LIVE_CASE_STATES:
            return True
    return False


def remediation_deadline(severity):
    return store.now() + timedelta(days=REMEDIATION_DAYS[severity])


def appeal_deadline():
    return store.now() + timedelta(days=APPEAL_WINDOW_DAYS)


def evidence_windows_attributable(developer_id, window_ids):
    """Every cited window must belong to an entitlement of the target developer."""
    owned = set(
        a["id"]
        for a in store.quota_assignments.values()
        if a["developer_id"] == developer_id
    )
    for window_id in window_ids:
        window = store.usage_windows.get(window_id)
        if window is None or window["quota_assignment_id"] not in owned:
            return False
    return True


# ------------------------------------------------------------------- cascades
def revoke_active_leases(developer_id):
    revoked = []
    for lease in store.ordered(store.sandbox_leases):
        if lease["developer_id"] != developer_id or lease["state"] != "ACTIVE":
            continue
        lease["state"] = "REVOKED"
        lease["released_at"] = store.now()
        lease["closed_reason"] = "STANDING_CASCADE"
        store.touch(lease)
        revoked.append(lease["id"])
    return revoked


def restriction_cascade(developer):
    """Suspend entitlements, void upgrades, delist directory, revoke leases."""
    for assignment in assignments_of_developer(developer["id"]):
        if assignment["entitlement_state"] == "ACTIVE":
            quota.suspend(assignment, "STANDING_RESTRICTION", standing_cascade=True)
    if developer["directory_state"] == "LISTED":
        developer["directory_state"] = "DELISTED"
    revoke_active_leases(developer["id"])


def restoration_cascade(developer):
    """Restore entitlements suspended by a standing restriction."""
    for assignment in assignments_of_developer(developer["id"]):
        if (
            assignment["entitlement_state"] == "SUSPENDED"
            and assignment["suspension_reason"] == "STANDING_RESTRICTION"
        ):
            quota.restore(assignment)


def revocation_cascade(developer):
    for assignment in assignments_of_developer(developer["id"]):
        if assignment["entitlement_state"] != "RETIRED":
            quota.retire(assignment)
    if developer["directory_state"] != "DELISTED":
        developer["directory_state"] = "DELISTED"
    revoke_active_leases(developer["id"])
    for application in store.ordered(store.access_applications):
        if application["developer_id"] != developer["id"]:
            continue
        if application["state"] in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED"):
            application["state"] = "REJECTED"
            application["decision_reason"] = "ACCESS_REVOKED"
            application["decided_at"] = store.now()
            store.touch(application)


def revocation_grounds_met(developer):
    if developer["violation_points"] >= REVOCATION_THRESHOLD:
        return True
    for case in store.violation_cases.values():
        if case["developer_id"] == developer["id"] and case["state"] == "UPHELD_FINAL":
            return True
    return False


def is_investigator_of_any_case(developer_id, user_id):
    for case in store.violation_cases.values():
        if case["developer_id"] != developer_id:
            continue
        if case["investigator_user_id"] is not None and (
            case["investigator_user_id"] == user_id
        ):
            return True
    return False


# --------------------------------------------------------------- adjudication
def apply_upheld(case, developer):
    developer["violation_points"] += case["penalty_points"]
    case["points_applied"] = case["penalty_points"]
    case["appeal_deadline"] = appeal_deadline()
    if developer["violation_points"] >= RESTRICTION_THRESHOLD:
        if developer["standing"] == "UNDER_REVIEW":
            developer["standing"] = "RESTRICTED"
            restriction_cascade(developer)


def apply_dismissed(case, developer):
    developer["violation_points"] -= case["points_applied"]
    case["points_applied"] = 0
    if (
        developer["standing"] == "RESTRICTED"
        and developer["violation_points"] < RESTRICTION_THRESHOLD
    ):
        developer["standing"] = "GOOD_STANDING"
        restoration_cascade(developer)
    elif developer["standing"] == "UNDER_REVIEW" and not has_live_case(
        developer["id"], excluding_case_id=case["id"]
    ):
        developer["standing"] = "GOOD_STANDING"
