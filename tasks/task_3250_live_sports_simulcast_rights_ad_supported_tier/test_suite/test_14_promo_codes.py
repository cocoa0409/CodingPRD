"""Partners, promo codes, redemption gating (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    PM,
    create_partner,
    create_viewer,
    issue_promo_code,
    make_viewer_headers,
    set_clock,
    validate_error,
    validate_success,
    viewer_with_bundle_entitlement,
)


def test_promo_quota_exhausted_on_partner(api):
    """PRD §3.6: "Issuing a promo code under a partner is permitted only when
    the partner's `codes_issued` is strictly less than `max_promo_codes`; a
    request at or beyond quota is rejected with `ERR_PROMO_QUOTA_EXHAUSTED`
    (HTTP 422)."

    Design: Corner/validations/promo_quota_exhausted_on_partner
    """
    partner = create_partner(max_promo_codes=1)
    first = issue_promo_code(partner["id"])
    assert first["code_status"] == "ISSUED"
    resp = api.issue_promo_code(partner["id"], PM)
    validate_error(resp, ApiErrorId.ERR_PROMO_QUOTA_EXHAUSTED)
    after = validate_success(api.get_partner(partner["id"], PM))
    assert after["codes_issued"] == 1


def test_promo_redeem_expired_code_rejected(api):
    """PRD §3.6: "A successful issuance mints a server-generated unique
    `code` string, sets `issued_at` to the current logical time, sets
    `expires_at` to `issued_at` plus 72 hours" and "Redemption requires the
    code to be in `ISSUED` (not `REDEEMED`, `REVOKED`, or `EXPIRED`), the
    current logical time to be strictly less than the code's `expires_at`
    ... A failure surfaces `ERR_PROMO_INVALID` (HTTP 422)."
    PRD §3.6: "A code in `ISSUED` whose `expires_at` is reached by the
    logical clock transitions to `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/promo_redeem_gated_by_partner_state
    """
    partner = create_partner(max_promo_codes=3)
    code = issue_promo_code(partner["id"])  # issued at clock default 2026-09-01
    viewer = create_viewer()
    set_clock("2026-09-30T00:00:00Z")  # well past issued_at + 72h
    resp = api.redeem_promo_code(
        {"code": code["code"], "viewer_id": viewer["id"]},
        make_viewer_headers(viewer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROMO_INVALID)


def test_promo_code_transitions_to_expired_under_clock(api):
    """PRD §3.6: "A code in `ISSUED` whose `expires_at` is reached by the
    logical clock transitions to `EXPIRED`."
    PRD §2.8: "Advancing the logical clock re-evaluates all time-driven
    transitions, including: promo code expiry ...".

    Design: Difficulty/cross_entity_state_dependency/promo_redeem_gated_by_partner_state
    """
    partner = create_partner(max_promo_codes=3)
    code = issue_promo_code(partner["id"])
    assert code["code_status"] == "ISSUED"
    assert code["expires_at"] == "2026-09-04T00:00:00Z", (
        f"expires_at should be issued_at + 72h, got {code['expires_at']}"
    )
    set_clock("2026-09-04T00:00:01Z")
    after = validate_success(api.get_promo_code(code["id"], PM))
    assert after["code_status"] == "EXPIRED"


def test_viewer_cannot_redeem_for_other_viewer(api):
    """PRD §2.1: "For the `Viewer` role, `X-User-ID` is **entity-backed**:
    it is the `id` of the acting `Viewer`. Ownership checks on any resource
    that references a `Viewer` compare the resource's foreign-key field to
    `X-User-ID`. Concretely, a viewer may only request a view grant for
    itself (the `viewer_id` in the request body must equal `X-User-ID`), may
    only redeem a promo code for itself, and may only cancel its own
    subscription (the `{id}` path parameter must equal `X-User-ID`)."

    Design: Corner/rbac/viewer_cannot_redeem_for_other_viewer
    """
    viewer_a = create_viewer()
    viewer_b = create_viewer()
    partner = create_partner()
    code = issue_promo_code(partner["id"])
    resp = api.redeem_promo_code(
        {"code": code["code"], "viewer_id": viewer_b["id"]},
        make_viewer_headers(viewer_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
