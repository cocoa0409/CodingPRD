"""Role permissions: operations reserved to a single role."""

from test_helpers import (
    api_client,
    make_account_headers,
    make_recipient_headers,
    setup_single_signer_envelope,
    validate_error,
    validate_success,
)


def test_recipient_cannot_send_an_envelope(api):
    """PRD §2.1: "A well-formed request that nonetheless asks for an operation
    its role may not perform is rejected separately with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: `POST /esign/envelopes/{id}/send` is listed with Authorized Role
    `Account` only.
    PRD §2.1: "When `X-User-Role` is `Recipient`, `X-User-ID` is the `id` of the
    acting `Recipient`, and a recipient may act only on the recipient row it
    names."

    Design: Corner/rbac/recipient_cannot_send_envelope
    """
    ctx = setup_single_signer_envelope(subject="RBAC envelope")
    envelope, recipient = ctx["envelope"], ctx["recipient"]

    res = api_client.send_envelope(
        envelope["id"], make_recipient_headers(recipient["id"])
    )
    validate_error(res, "ERR_FORBIDDEN")
    assert res.status_code == 403


def test_account_cannot_purge_an_envelope(api):
    """PRD §2.1: "A well-formed request that nonetheless asks for an operation
    its role may not perform is rejected separately with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: `POST /esign/envelopes/{id}/purge` is listed with Authorized Role
    `PlatformAdmin` only.

    Design: Corner/rbac/account_cannot_purge_envelope
    """
    ctx = setup_single_signer_envelope(subject="Purge RBAC envelope")
    account, envelope = ctx["account"], ctx["envelope"]

    sent = validate_success(
        api_client.send_envelope(envelope["id"], make_account_headers(account["id"])), 200
    )

    res = api_client.purge_envelope(
        envelope["id"],
        {"expected_envelope_version": sent["version"]},
        make_account_headers(account["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN")
    assert res.status_code == 403