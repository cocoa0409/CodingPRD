"""RBAC: role denials and entity-backed ownership scoping."""
from test_helpers import (
    ApiErrorId,
    create_account,
    create_account_with_assigned_slot,
    get_account,
    get_success_data,
    make_extra_member_headers,
    support_headers,
    validate_error,
)


def test_support_agent_cannot_suspend(api):
    """PRD §4: the suspend operation (`POST /hv/accounts/{id}/suspend`) is
    authorized for PlatformAdmin only. PRD §2.1: "A request whose role is not
    listed for the endpoint ... is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/support_agent_cannot_suspend
    """
    account, _ = create_account(email="corner-sa@x.com")
    resp = api.suspend_account(account["id"], support_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = get_account(account["id"])
    assert after["status"] == "ACTIVE"


def test_extra_member_cannot_read_other_member(api):
    """PRD §2.1: "When `X-User-Role` is `ExtraMember`, `X-User-ID` is the `id` of
    the acting `Member` whose `member_role` is `EXTRA`; ownership checks follow
    the same account-matching rule." A request whose X-User-ID "resolves to a
    member that does not belong to the target account — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)".

    Design: Corner/rbac/extra_member_cannot_read_other_member
    """
    account_a, slot, extra_id, owner_a_h = create_account_with_assigned_slot(
        email="corner-xa@x.com", extra_email="extra-xa@x.com"
    )
    account_b, owner_b_h = create_account(email="corner-xb@x.com")
    extra_h = make_extra_member_headers(extra_id)

    own = get_success_data(api.get_member(account_a["owner_member_id"], extra_h))
    assert own["id"] == account_a["owner_member_id"]

    resp = api.get_member(account_b["owner_member_id"], extra_h)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
