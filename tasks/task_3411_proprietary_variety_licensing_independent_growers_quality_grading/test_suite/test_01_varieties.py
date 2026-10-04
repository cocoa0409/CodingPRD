"""Variety registration, release, recall issuance, and recall-order listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_variety_payload, recall_variety_payload,
    set_clock, create_variety, create_released_variety, recall_variety,
    get_success_data, assert_variety, is_valid_uuid,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BREEDER = TEST_USERS["breeding_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_variety_create_returns_declared_fields_and_development(api):
    """PRD section 3.1: "A newly registered variety starts in `DEVELOPMENT` and
    cannot underlie any approved agreement."
    PRD section 2.4: "Every timestamp the server stamps on a mutation —
    `shipped_at`, `decided_at`, `issued_at`, `closed_at`, `settled_at`,
    `paid_at`, `enforced_at`, and their kin — is read from this clock at the
    moment of the mutation."

    Design: Corner/entities/variety_create_returns_declared_fields_and_development
    """
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_variety(create_variety_payload(), BREEDER)
    data = validate_success(resp, 201)
    assert_variety(data)
    assert is_valid_uuid(data["id"])
    assert data["variety_code"] == "BRB-STR-01"
    assert data["berry_type"] == "STRAWBERRY"
    assert data["name"] == "Cielo Rojo"
    assert data["status"] == "DEVELOPMENT"
    assert data["released_at"] is None
    assert data["recalled_at"] is None
    assert data["version"] == 1
    assert data["created_at"].startswith("2026-06-01T00:00:00"), (
        f"created_at must be stamped from the logical clock, got {data['created_at']}")


def test_variety_create_missing_berry_type_returns_400(api):
    """PRD section 2.8: "Required fields present, enum members valid, quantities
    positive, and temporal inputs well-formed — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/variety_create_missing_berry_type_returns_400
    """
    set_clock("2026-06-01T00:00:00Z")
    resp = api.create_variety(
        {"variety_code": "BRB-BLK-02", "name": "No Type Berry"}, BREEDER)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    assert isinstance(err["message"], str) and err["message"]


def test_variety_release_valid_transition(api):
    """PRD section 3.1: "Release moves a variety `DEVELOPMENT → RELEASED`,
    stamps `released_at` from the logical clock, and increments the variety's
    `version` by 1."

    Design: Corner/state_machines/variety_release_valid_transition
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_variety()
    resp = api.release_variety(variety["id"], BREEDER)
    data = validate_success(resp, 200)
    assert data["status"] == "RELEASED"
    assert data["released_at"].startswith("2026-06-01T00:00:00")
    assert data["version"] == 2
    assert data["recalled_at"] is None


def test_variety_recalled_terminal_lockdown(api):
    """PRD section 3.1: "`RECALLED` is a terminal state for the variety, and a
    variety's recall orders can be listed for audit."
    PRD section 2.8: "the generic `ERR_INVALID_STATE` (which covers
    terminal-state lockdown and repeated transitions)".

    Design: Corner/state_machines/variety_recalled_terminal_lockdown
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    order = recall_variety(variety["id"])
    resp = api.recall_variety(
        variety["id"],
        recall_variety_payload(reason="second recall attempt",
                               destroy_before="2026-12-01T00:00:00Z"),
        BREEDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp2 = api.release_variety(variety["id"], BREEDER)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_variety(variety["id"], ADMIN))
    assert current["status"] == "RECALLED"
    assert current["recalled_at"] is not None
    assert order["status"] == "ISSUED"
    rows, meta = validate_paginated(api.list_recall_orders(variety["id"], COMPLIANCE))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_recall_orders_subresource_lists_with_default_compensation(api):
    """PRD section 3.1: "When `compensation_per_plant_cents` is omitted it
    defaults to 22 cents per plant, and it may never be negative."
    PRD section 3.1: "`RECALLED` is a terminal state for the variety, and a
    variety's recall orders can be listed for audit."

    Design: Corner/entities/recall_orders_subresource_lists_with_default_compensation
    """
    set_clock("2026-06-01T00:00:00Z")
    variety = create_released_variety()
    order = recall_variety(variety["id"])  # no compensation_per_plant_cents
    rows, meta = validate_paginated(api.list_recall_orders(variety["id"], COMPLIANCE))
    assert len(rows) == 1 and meta["total_count"] == 1
    row = rows[0]
    assert row["id"] == order["id"]
    assert row["status"] == "ISSUED"
    assert row["compensation_per_plant_cents"] == 22
    assert row["variety_id"] == variety["id"]
    assert row["enforced_at"] is None
    assert row["plantings_recalled_count"] == 0
