"""Corner queue B — rbac section instances."""

from test_helpers import (
    ApiErrorId,
    create_approved_recipient,
    get_success_data,
    make_admin_headers,
    make_recipient_headers,
    make_reviewer_headers,
    validate_error,
    validate_success,
)


def test_recipient_role_cannot_review_recipients(api):
    """PRD §4: "`POST /recipients/{recipientId}/review` — Approve or reject a
    recipient (segregation of duties enforced) — ComplianceReviewer."
    PRD §2.1: "When the role is legitimate but is not permitted to invoke the
    requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/recipient_role_cannot_review_recipients
    """
    admin = make_admin_headers()
    recipient = get_success_data(
        api.create_recipient(
            {"name": "RbacApp", "declared_use_case": "rbac test", "minimization_policy": "BROAD"},
            admin,
        )
    )

    resp = api.review_recipient(
        recipient["id"], {"decision": "APPROVE"}, make_recipient_headers(recipient["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    reread = validate_success(api.get_recipient(recipient["id"], admin))
    assert reread["status"] == "PENDING_REVIEW"


def test_compliance_reviewer_cannot_suspend_recipient(api):
    """PRD §4: "`POST /recipients/{recipientId}/suspend` — Suspend an APPROVED
    recipient with the full revocation cascade — PlatformAdmin."
    PRD §2.1: "When the role is legitimate but is not permitted to invoke the
    requested endpoint, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/compliance_reviewer_cannot_suspend_recipient
    """
    rec = create_approved_recipient(api, name="RbacSuspend", tier_scopes=["BALANCE"], tier_name="RbTier")
    recipient = rec["recipient"]

    resp = api.suspend_recipient(recipient["id"], make_reviewer_headers("reviewer_2"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    reread = validate_success(api.get_recipient(recipient["id"], rec["admin"]))
    assert reread["status"] == "APPROVED"
