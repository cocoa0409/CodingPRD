"""Corner coverage of the member, signer and loan entity surfaces: creation
fields, retrieval, pagination, required fields, defaults, computed fields and
per-member serial sequencing."""
import pytest

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    add_signer,
    api_client,
    assert_member,
    create_active_member,
    create_member,
    create_member_payload,
    member_rep,
    read_loan,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_member_create_returns_declared_fields_and_pending_activation(api):
    """PRD §3.1: "A newly admitted member enters in `PENDING_ACTIVATION` status,
    with `termination_effective_date` null."
    PRD §2.5: "The `version` field is an integer that starts at 1 on creation
    and increments by exactly 1 on every mutation, including system-driven
    cascades; it is the basis of the optimistic concurrency rules in §2.8."

    Design: Corner/entities/member_create_returns_declared_fields_and_pending_activation
    """
    data = validate_success(
        api.create_member(
            {
                "legal_name": "First Registry Bank",
                "org_id": "2000000",
                "org_id_type": "TAX_ID",
                "member_type": "ORIGINATOR",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert_member(data)
    assert data["legal_name"] == "First Registry Bank", data
    assert data["org_id"] == "2000000", data
    assert data["status"] == "PENDING_ACTIVATION", data
    assert data["version"] == 1, data
    assert data["termination_effective_date"] is None, data


def test_member_get_returns_stored_entity_and_unknown_id_is_404(api):
    """PRD §2.9: "the first identifier that does not resolve produces the
    corresponding not-found error: `ERR_MEMBER_NOT_FOUND`, ... (all HTTP 404)."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/member_get_returns_stored_entity_and_unknown_id_is_404
    """
    member = create_member(org_id="2000000")

    found = validate_success(api.get_member(member["id"], ADMIN))
    assert found["org_id"] == "2000000", found
    assert found["id"] == member["id"], found

    resp = api.get_member(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404, resp.text
    err = validate_error(resp, "ERR_MEMBER_NOT_FOUND")
    assert isinstance(err["message"], str) and err["message"], err


def test_members_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned in one
    page; it defaults to 10, accepts a minimum of 1, and refuses values above
    100. The `offset` parameter skips a number of items from the head of the
    result set and defaults to 0."
    PRD §2.3: "The `meta` object of every list response carries `limit`,
    `offset`, `total_count`, and `has_more`, allowing clients to page
    exhaustively without probing."

    Design: Corner/entities/members_list_paginates_with_total_count_and_has_more
    """
    for i in range(3):
        create_member(org_id=f"200000{i + 1}", legal_name=f"M{i + 1}")

    rows, meta = validate_paginated(api.list_members(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2, rows
    assert meta["total_count"] == 3, meta
    assert meta["has_more"] is True, meta

    rows2, meta2 = validate_paginated(api.list_members(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(rows2) == 1, rows2
    assert meta2["total_count"] == 3, meta2
    assert meta2["has_more"] is False, meta2

    pending, meta3 = validate_paginated(
        api.list_members(ADMIN, params={"status": "PENDING_ACTIVATION"})
    )
    assert meta3["total_count"] == 3, meta3


def test_member_create_missing_org_id_returns_invalid_request(api):
    """PRD §2.9: "**Shape.** Every required input field of the endpoint must be
    present and well-typed; a missing or malformed required field yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/member_create_missing_org_id_returns_invalid_request
    """
    resp = api.create_member(
        {"legal_name": "No Org Id Bank", "org_id_type": "TAX_ID",
         "member_type": "SERVICER"},
        ADMIN,
    )
    assert resp.status_code == 400, resp.text
    validate_error(resp, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(api.list_members(ADMIN))
    assert meta["total_count"] == 0, meta


def test_signer_create_omitting_effective_until_defaults_to_null_open_ended(api):
    """PRD §3.1: "The window is half-open: authority begins at `effective_from`
    inclusive and ends at `effective_until` exclusive, and a null
    `effective_until` means the authority is open-ended."
    PRD §3.1: "A new signer enters in `ACTIVE` status immediately."

    Design: Corner/entities/signer_create_omitting_effective_until_defaults_to_null_open_ended
    """
    a = create_member(org_id="1000000")
    signer = add_signer(a["id"], effective_from="2026-01-01T00:00:00Z")
    assert signer["status"] == "ACTIVE", signer
    assert signer["role_scope"] == "ALL", signer
    assert signer["effective_until"] is None, signer


def test_loan_min_and_foreclosure_mode_are_computed_not_client_supplied(api):
    """PRD §3.2: "On acceptance, the registry stamps the loan with its
    provenance and identity. The registering member's next `serial` is consumed
    (never reused, even if the member later terminates), the eighteen-digit
    `min` is minted per §2.6, `registering_member_id` records the acting member,
    and both `current_investor_id` and `current_servicer_id` are initialized to
    the registering member — at closing, the registrant holds both rights."
    PRD §2.6: "A loan's `min` concatenates three parts into exactly eighteen
    digits: the registering member's seven-digit `org_id`, then the member's
    ten-digit registration `serial` zero-padded on the left, then a single Luhn
    check digit computed over the first seventeen digits."

    Design: Corner/entities/loan_min_and_foreclosure_mode_are_computed_not_client_supplied
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    loan = register_loan(a["id"], loan_amount_cents=12345678)

    assert loan["min"] == "100000000000000016", loan
    assert loan["serial"] == 1, loan
    assert loan["foreclosure_mode"] == "IN_REGISTRY_ALLOWED", loan
    assert loan["current_investor_id"] == a["id"], loan
    assert loan["current_servicer_id"] == a["id"], loan
    assert loan["registering_member_id"] == a["id"], loan
    assert loan["status"] == "ACTIVE", loan
    assert loan["version"] == 1, loan
    assert loan["assigned_out_at"] is None, loan


def test_ny_property_state_derives_assign_out_required_mode(api):
    """PRD §3.2: "The derived `foreclosure_mode` is determined by
    `property_state`: loans secured by property in New York or California are
    classified `ASSIGN_OUT_REQUIRED`, reflecting jurisdictional requirements
    that foreclosure proceed on an assignment out of the registry; loans in
    every other state are `IN_REGISTRY_ALLOWED`."

    Design: Corner/entities/ny_property_state_derives_assign_out_required_mode
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    ny_loan = register_loan(a["id"], property_state="NY", loan_amount_cents=10000000)
    tx_loan = register_loan(a["id"], property_state="TX", loan_amount_cents=10000000)
    ca_loan = register_loan(a["id"], property_state="CA", loan_amount_cents=10000000)

    assert ny_loan["foreclosure_mode"] == "ASSIGN_OUT_REQUIRED", ny_loan
    assert ca_loan["foreclosure_mode"] == "ASSIGN_OUT_REQUIRED", ca_loan
    assert tx_loan["foreclosure_mode"] == "IN_REGISTRY_ALLOWED", tx_loan


def test_loan_serial_is_per_member_and_never_reused(api):
    """PRD §2.6: "The serial that feeds this construction is per-member: each
    member's first successfully registered loan receives serial 1, each
    subsequent successful registration increments it, serials are never reused,
    and they survive member termination."

    Design: Corner/entities/loan_serial_is_per_member_and_never_reused
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")

    a1 = register_loan(a["id"], loan_amount_cents=10000000)
    a2 = register_loan(a["id"], loan_amount_cents=10000000)
    b1 = register_loan(b["id"], loan_amount_cents=10000000)

    assert a1["serial"] == 1 and a1["min"] == "100000000000000016", a1
    assert a2["serial"] == 2 and a2["min"] == "100000000000000024", a2
    # B's serial sequence restarts at 1 and mints its own check digit.
    assert b1["serial"] == 1 and b1["min"] == "100000100000000014", b1


def test_invalid_enum_member_type_rejected(api):
    """PRD §3.1: "A `RegistryAdmin` admits an organization to the registry by
    registering it with its `legal_name`, its seven-digit `org_id`, the
    `org_id_type` classifying that identifier, and a `member_type` drawn from
    `ORIGINATOR`, `SERVICER`, `INVESTOR`, `SUBSERVICER`, or `CUSTODIAN`."
    PRD §2.9: "a missing or malformed required field yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/invalid_enum_member_type_rejected
    """
    resp = api.create_member(
        {"legal_name": "Bad Type Co", "org_id": "2000009",
         "org_id_type": "TAX_ID", "member_type": "HEDGE_FUND"},
        ADMIN,
    )
    assert resp.status_code == 400, resp.text
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_loan_create_by_suspended_member_rejected_and_by_pending_member_rejected(api):
    """PRD §3.2: "Registration itself requires the registering member to be
    `ACTIVE` — a suspended or pending member cannot place loans on the
    registry."

    Design: Corner/entities/loan_create_by_suspended_member_rejected_and_by_pending_member_rejected
    """
    from test_helpers import create_loan_payload
    set_clock("2026-01-05T00:00:00Z")
    # P stays PENDING_ACTIVATION (has a signer, never activated).
    p = create_member(org_id="2000010")
    add_signer(p["id"])
    # S is activated then suspended.
    s = create_member(org_id="2000011")
    add_signer(s["id"])
    validate_success(api.activate_member(s["id"], ADMIN))
    validate_success(api.suspend_member(s["id"], ADMIN))

    payload = create_loan_payload()
    resp_p = api.create_loan(payload, member_rep(p["id"]))
    assert resp_p.status_code == 409, resp_p.text
    validate_error(resp_p, "ERR_MEMBER_NOT_ACTIVE")

    resp_s = api.create_loan(payload, member_rep(s["id"]))
    assert resp_s.status_code == 409, resp_s.text
    validate_error(resp_s, "ERR_MEMBER_NOT_ACTIVE")

    rows, meta = validate_paginated(api.list_loans(ADMIN))
    assert meta["total_count"] == 0, meta
