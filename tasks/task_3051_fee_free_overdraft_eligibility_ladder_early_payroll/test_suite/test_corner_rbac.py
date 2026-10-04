"""Breadth tests for role authorization and member ownership."""

import test_helpers as th
from test_helpers import fixtures


def test_member_cannot_post_early(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    targeted endpoint is rejected with `ERR_FORBIDDEN` (403); the full
    per-endpoint authorization appears in §4."
    PRD §4: "| POST | /banking/deposits/{id}/post-early | Make payroll funds available ahead of settlement. | ProgramOps |"

    Design: Corner/rbac/member_cannot_post_early
    """
    member = fixtures.create_member(
        api, external_ref="c25", full_name="C TwentyFive", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    dep = fixtures.register_deposit(
        api,
        account["id"],
        originator_id="EMPC25",
        originator_type="PAYROLL",
        amount_cents=10000,
        settlement_date="2026-09-10T00:00:00Z",
        trace_id="c25-t1",
    )
    resp = api.post_early(dep["id"], {}, th.make_member_headers(member["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_member_cannot_touch_other_members_resources(api):
    """PRD §2.1: "Role identity is bound to resources as follows. When
    `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`
    record; ownership checks on any resource that hangs beneath a member — an
    account, an advance on an account, a deposit on an account, a dispute filed
    by the member — compare the resource's owning chain back to that member's
    `id`, and a mismatch is `ERR_FORBIDDEN`."

    Design: Corner/rbac/member_cannot_touch_other_members_resources
    """
    member_a = fixtures.create_member(
        api, external_ref="c26", full_name="C TwentySix", enrolled_at="2025-09-01T00:00:00Z"
    )
    member_b = fixtures.create_member(
        api, external_ref="c27", full_name="C TwentySeven", enrolled_at="2025-09-01T00:00:00Z"
    )
    resp = api.get_member(member_b["id"], th.make_member_headers(member_a["id"]))
    th.validate_error(resp, th.ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_disputes_agent_cannot_create_deposits(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    targeted endpoint is rejected with `ERR_FORBIDDEN` (403); the full
    per-endpoint authorization appears in §4."
    PRD §4: "| POST | /banking/accounts/{id}/deposits | Register an inbound ACH deposit file. | SponsorBankOps |"

    Design: Corner/rbac/disputes_agent_cannot_create_deposits
    """
    member = fixtures.create_member(
        api, external_ref="c28", full_name="C TwentyEight", enrolled_at="2025-09-01T00:00:00Z"
    )
    account = fixtures.open_account(api, member["id"])
    resp = api.create_deposit(
        account["id"],
        th.factories.deposit_payload(
            originator_id="EMPZ",
            originator_type="PAYROLL",
            amount_cents=10000,
            settlement_date="2026-09-10T00:00:00Z",
            trace_id="c28-t1",
        ),
        th.TEST_USERS["disputes_agent"],
    )
    th.validate_error(resp, th.ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
