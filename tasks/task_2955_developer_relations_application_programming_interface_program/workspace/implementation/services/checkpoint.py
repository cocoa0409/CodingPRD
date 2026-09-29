"""The programme checkpoint: six server-initiated steps in a fixed order."""
from constants import BURST_CREDIT_MULTIPLIER, RESET_PERIOD_DAYS
from db import store, whole_days_between

from . import lifecycle, trust, usage


def run_checkpoint():
    now = store.now()

    expired_lease_ids = []
    expired_certification_developer_ids = []
    sunset_version_ids = []
    retired_assignment_ids = []
    voided_upgrade_request_ids = []
    finalised_case_ids = []
    reset_assignment_ids = []
    rescored_developer_ids = []

    # ---- step 1: sandbox lease expiry
    for lease in store.ordered(store.sandbox_leases):
        if lease["state"] == "ACTIVE" and lease["expires_at"] <= now:
            lease["state"] = "EXPIRED"
            lease["released_at"] = now
            lease["closed_reason"] = "CHECKPOINT_EXPIRY"
            store.touch(lease)
            expired_lease_ids.append(lease["id"])

    # ---- step 2: certification lapse (the level itself is retained)
    for developer in store.ordered(store.developers):
        expires = developer["certification_expires_at"]
        if expires is not None and expires <= now:
            expired_certification_developer_ids.append(developer["id"])

    # ---- step 3: version sunset and the full cascade
    for version in store.ordered(store.api_versions):
        if version["lifecycle_state"] != "DEPRECATION_ANNOUNCED":
            continue
        if version["sunset_at"] is None or version["sunset_at"] > now:
            continue
        retired, voided = lifecycle.sunset_version(version)
        sunset_version_ids.append(version["id"])
        retired_assignment_ids.extend(retired)
        voided_upgrade_request_ids.extend(voided)

    # ---- step 4: case finalisation
    for case in store.ordered(store.violation_cases):
        if case["state"] != "UPHELD":
            continue
        if case["appeal_deadline"] is None or not case["appeal_deadline"] < now:
            continue
        awaiting = case["appeal_count"] > 0 and case["outcome"] != "UPHELD"
        if awaiting:
            continue
        case["state"] = "UPHELD_FINAL"
        store.touch(case)
        finalised_case_ids.append(case["id"])

    # ---- step 5: monthly reset
    for assignment in store.ordered(store.quota_assignments):
        if assignment["entitlement_state"] != "ACTIVE":
            continue
        last = assignment["last_reset_at"]
        if last is None or whole_days_between(last, now) < RESET_PERIOD_DAYS:
            continue
        assignment["monthly_calls_consumed"] = 0
        assignment["bonus_call_credit"] = 0
        assignment["burst_credit_balance"] = (
            assignment["burst_rpm"] * BURST_CREDIT_MULTIPLIER
        )
        assignment["last_reset_at"] = now
        usage.reevaluate_throttle(assignment)
        store.touch(assignment)
        reset_assignment_ids.append(assignment["id"])

    # ---- step 6: audited rescoring
    for developer in store.ordered(store.developers):
        previous = developer["audited_trust_score"]
        trust.refresh_audit(developer)
        if developer["audited_trust_score"] != previous:
            store.touch(developer)
        rescored_developer_ids.append(developer["id"])

    return {
        "expired_lease_ids": expired_lease_ids,
        "expired_certification_developer_ids": expired_certification_developer_ids,
        "sunset_version_ids": sunset_version_ids,
        "retired_assignment_ids": retired_assignment_ids,
        "voided_upgrade_request_ids": voided_upgrade_request_ids,
        "finalised_case_ids": finalised_case_ids,
        "reset_assignment_ids": reset_assignment_ids,
        "rescored_developer_ids": rescored_developer_ids,
    }
