"""Version lifecycle: deprecation notice requirement and the sunset cascade."""
from constants import (
    BASE_NOTICE_DAYS,
    BREAKING_CHANGE_EXTRA_DAYS,
    ESCALATION_ENTITLED_TIERS,
    PARTNER_PINNED_EXTRA_DAYS,
)
from db import store

from . import quota
from .common import assignments_pinned_to_version


def required_notice_days(version, product):
    total = BASE_NOTICE_DAYS[product["data_sensitivity"]]
    if version["breaking_change"]:
        total += BREAKING_CHANGE_EXTRA_DAYS
    for assignment in assignments_pinned_to_version(version["id"]):
        if (
            assignment["entitlement_state"] == "ACTIVE"
            and assignment["tier"] in ESCALATION_ENTITLED_TIERS
        ):
            total += PARTNER_PINNED_EXTRA_DAYS
            break
    return total


def announced_count(product_id, excluding_version_id):
    count = 0
    for version in store.api_versions.values():
        if version["api_product_id"] != product_id:
            continue
        if version["id"] == excluding_version_id:
            continue
        if version["lifecycle_state"] == "DEPRECATION_ANNOUNCED":
            count += 1
    return count


def sunset_version(version):
    """Move a version to SUNSET and fire the full cascade."""
    version["lifecycle_state"] = "SUNSET"
    version["sunset_completed_at"] = store.now()
    store.touch(version)

    retired = []
    voided = []
    for assignment in assignments_pinned_to_version(version["id"]):
        if assignment["entitlement_state"] in ("ACTIVE", "SUSPENDED"):
            voided.extend(quota.retire(assignment))
            retired.append(assignment["id"])

    for application in store.ordered(store.access_applications):
        if application["target_api_version_id"] != version["id"]:
            continue
        if application["state"] in ("SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED"):
            application["state"] = "REJECTED"
            application["decision_reason"] = "TARGET_VERSION_SUNSET"
            application["decided_at"] = store.now()
            store.touch(application)

    return retired, voided
