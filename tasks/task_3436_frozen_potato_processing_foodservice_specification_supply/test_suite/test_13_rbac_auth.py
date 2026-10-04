"""Auth and ownership: header presence, role authorization, and the two
entity-backed ownership rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contracted_lot_payload,
    create_crop_contract_payload,
    create_cut_specification_payload,
    make_chain,
    make_chain_customer_headers,
    make_grower,
    make_grower_headers,
    make_spec,
    set_clock,
    setup_chain_with_validated_spec,
    setup_procurement,
    validate_error,
    validate_paginated,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]
QA = TEST_USERS["qa_lead_headers"]


def test_contract_create_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value outside this declared set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.10: "1. **Header presence and role validity** — the `X-User-ID` and
    `X-User-Role` headers must both be present and the role must be one of the
    nine declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400). Applies to every endpoint."

    Design: Corner/validations/contract_create_missing_auth_headers_unauthenticated
    """
    resp = api.create_crop_contract(create_crop_contract_payload(
        "00000000-0000-4000-8000-000000000000"
    ), {})
    body = resp.json()
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert resp.status_code == 400, "header presence is priority 1, ahead of even existence"
    assert body["response_type"] == "error"


def test_grower_role_cannot_validate_spec_returns_403(api):
    """PRD §2.1: "Each operation restricts which roles may invoke it; an
    authenticated caller whose role is not in the operation's role list is
    rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: the validate operation is authorized for QualityAssuranceLead
    only.

    Design: Corner/rbac/grower_role_cannot_validate_spec_returns_403
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    chain = make_chain(api=api)
    spec = make_spec(chain["id"], api=api)  # SUBMITTED

    resp = api.validate_cut_specification(
        spec["id"], {"panel_score": 8.0}, make_grower_headers(grower["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert resp.status_code == 403

    reread = validate_success(api.get_cut_specification(spec["id"], QA))
    assert reread["status"] == "SUBMITTED"
    assert reread["panel_score"] is None


def test_chain_customer_cannot_create_spec_for_another_chain(api):
    """PRD §2.1: "the chain customer may author a cut specification only with
    `customer_id` equal to `X-User-ID`, and may request a revision only on a
    specification it owns, with violations likewise rejected as
    `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/rbac/chain_customer_cannot_create_spec_for_another_chain
    """
    set_clock(api=api)
    chain_a = make_chain(api=api)
    chain_b = make_chain(api=api, chain_code="CH-BETA", legal_name="Beta Diner Group",
                         priority_tier="TIER_2_PREFERRED")

    resp = api.create_cut_specification(
        create_cut_specification_payload(chain_b["id"], spec_code="SP-X"),
        make_chain_customer_headers(chain_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert resp.status_code == 403, "chain A's portal user cannot author chain B's spec"

    rows, _ = validate_paginated(
        api.list_cut_specifications(QA, params={"customer_id": chain_b["id"]})
    )
    assert rows == []


def test_grower_cannot_deliver_against_another_growers_contract(api):
    """PRD §2.1: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of
    the acting `Grower`; ownership checks on any resource that references a
    grower compare the resource's foreign-key field to `X-User-ID` —
    concretely, a grower may deliver a contracted potato lot only against a
    crop contract whose `grower_id` equals the caller's `X-User-ID`, and any
    mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/grower_cannot_deliver_against_another_growers_contract
    """
    world = setup_procurement(api=api)  # ACTIVE contract owned by GR-100, in-window
    grower2 = make_grower(api=api, grower_code="GR-200",
                          legal_name="Snake River Produce Inc",
                          region="SNAKE_RIVER_VALLEY")

    resp = api.create_potato_lot(
        create_contracted_lot_payload(world["contract"]["id"], world["facility"]["id"]),
        make_grower_headers(grower2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert resp.status_code == 403, (
        "the contract is ACTIVE and in-window; only the ownership gate fails"
    )

    rows, _ = validate_paginated(
        api.list_potato_lots(GRM, params={"contract_id": world["contract"]["id"]})
    )
    assert rows == []
