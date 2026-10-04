"""Quality control reviews and regulatory inspection responses."""

from core import constants as C
from core.clock import now as clock_now
from core.db import new_row, store, touch
from core.errors import ERR_INVALID_STATE, ApiError
from services import calc


def create_review_row(engagement_id, reviewer_id, review_type, inspection_body,
                      received_on, due_on, deficiency_count, remediation_plan_ref):
    return new_row("reviews", {
        "engagement_id": engagement_id,
        "reviewer_id": reviewer_id,
        "review_type": review_type,
        "inspection_body": inspection_body,
        "received_on": received_on,
        "due_on": due_on,
        "response_due_on": calc.inspection_response_due(
            review_type, inspection_body, deficiency_count, received_on),
        "deficiency_count": int(deficiency_count or 0),
        "remediation_plan_ref": remediation_plan_ref,
        "status": "SCHEDULED",
    })


def apply_review_action(review, action, now=None):
    now = now or clock_now()
    status = review.get("status")
    engagement = store.engagements.get(review.get("engagement_id"))
    if action == "START":
        if status != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, "START requires a SCHEDULED review.")
        review["status"] = "IN_PROGRESS"
    elif action == "PASS":
        if status != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, "PASS requires a review in IN_PROGRESS.")
        if int(review.get("deficiency_count") or 0) != 0:
            raise ApiError(ERR_INVALID_STATE, "PASS requires a review with zero deficiencies.")
        review["status"] = "PASSED"
        if engagement is not None:
            engagement["quality_review_required"] = False
            touch(engagement)
    elif action == "FAIL":
        if status != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, "FAIL requires a review in IN_PROGRESS.")
        if int(review.get("deficiency_count") or 0) <= 0:
            raise ApiError(ERR_INVALID_STATE, "FAIL requires at least one deficiency.")
        review["status"] = "DEFICIENT"
        if engagement is not None and int(review.get("deficiency_count") or 0) >= 3 \
                and engagement.get("status") == "ACTIVE":
            engagement["status"] = "SUSPENDED"
            engagement["_suspended_by_review_id"] = review.get("id")
            touch(engagement)
    elif action == "REMEDIATE":
        if status != "DEFICIENT":
            raise ApiError(ERR_INVALID_STATE, "REMEDIATE requires a DEFICIENT review.")
        if not review.get("remediation_plan_ref"):
            raise ApiError(ERR_INVALID_STATE, "REMEDIATE requires a remediation plan reference.")
        review["status"] = "REMEDIATED"
        if engagement is not None \
                and engagement.get("_suspended_by_review_id") == review.get("id") \
                and engagement.get("independence_status") != "FROZEN":
            engagement["status"] = "ACTIVE"
            engagement["_suspended_by_review_id"] = None
            touch(engagement)
    elif action == "REOPEN":
        if status != "REMEDIATED":
            raise ApiError(ERR_INVALID_STATE, "REOPEN requires a REMEDIATED review.")
        review["status"] = "IN_PROGRESS"
    else:
        raise ApiError(ERR_INVALID_STATE, "Unknown action '%s' for a quality review." % action)
    touch(review)
    return review
