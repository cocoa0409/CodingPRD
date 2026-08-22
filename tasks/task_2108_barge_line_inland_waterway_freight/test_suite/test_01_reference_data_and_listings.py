"""Reference-data registration, defaults, immutability and list conventions."""
from test_helpers import (
    ApiErrorId,
    assert_barge,
    assert_commodity,
    assert_three_fractional_digits,
    create_barge,
    create_barge_payload,
    create_commodity,
    create_freight_contract_payload,
    create_shipper,
    is_valid_uuid,
    make_contract_manager_headers,
    make_waterway_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_waterway_admin_headers()
BILLER = make_contract_manager_headers()


def test_register_barge_applies_idle_and_washed_defaults(api):
    """PRD §3.1: "Registration always sets `operational_status` to `IDLE` — the
    axis moves only through fleeting, tow makeup and wash-rack events — and
    leaves `last_cleaning_certificate_number` empty until a passing inspection
    writes one."
    PRD §3.1: "Two further attributes are optional at registration and exist so
    that an operator can record a hull arriving from elsewhere with a known
    history: `cleanliness_status`, which defaults to `WASHED` when omitted, and
    `last_cargo_commodity_id`, which is null when omitted."
    PRD §2.4: "Every stored resource carries a server-minted `id` that is a UUID
    string with no type prefix of any kind."

    Design: Corner/entities/create_barge_applies_defaults_and_mints_system_fields
    """
    response = api.create_barge(
        create_barge_payload(hull_number="BL-9001", capacity_tons=1750,
                             light_draft_feet=1.5, tons_per_inch_immersion=17.0),
        ADMIN)
    data = validate_success(response, 201)
    assert_barge(data)
    assert data["operational_status"] == "IDLE", (
        f"a freshly registered hull is IDLE, got {data['operational_status']}")
    assert data["cleanliness_status"] == "WASHED", (
        f"cleanliness_status defaults to WASHED, got {data['cleanliness_status']}")
    assert data.get("last_cargo_commodity_id") is None, (
        "last_cargo_commodity_id is null when omitted")
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), "id must be a bare UUID"
    assert_three_fractional_digits(data["created_at"])


def test_register_barge_records_prior_cargo_and_cleanliness(api):
    """PRD §3.1: "Two further attributes are optional at registration and exist
    so that an operator can record a hull arriving from elsewhere with a known
    history: `cleanliness_status`, which defaults to `WASHED` when omitted, and
    `last_cargo_commodity_id`, which is null when omitted."

    Design: Corner/entities/create_barge_accepts_optional_prior_cargo_and_cleanliness
    """
    uan = create_commodity(code="UAN32", commodity_group="FERTILIZER",
                           residue_class="TOXIC", hazard_flag=True, stowage_factor=0.85)
    data = validate_success(api.create_barge(
        create_barge_payload(hull_number="BL-9002", cleanliness_status="DIRTY",
                             last_cargo_commodity_id=uan["id"]), ADMIN), 201)
    assert data["cleanliness_status"] == "DIRTY", (
        "a supplied cleanliness_status overrides the WASHED default")
    assert data["last_cargo_commodity_id"] == uan["id"], (
        "the supplied prior cargo must be stored on the hull")
    assert data["operational_status"] == "IDLE", (
        "the operational axis still opens at IDLE")


def test_register_barge_never_opens_a_hull_in_tow(api):
    """PRD §3.1: "Registration always sets `operational_status` to `IDLE` — the
    axis moves only through fleeting, tow makeup and wash-rack events — and
    leaves `last_cleaning_certificate_number` empty until a passing inspection
    writes one."
    PRD §2.4: "Clients never supply an `id`; a client-supplied `id` in a request
    body is ignored."

    Design: Corner/entities/create_barge_with_system_field_in_body_input_ignored
    """
    payload = create_barge_payload(hull_number="BL-9003")
    payload["operational_status"] = "IN_TOW"
    response = api.create_barge(payload, ADMIN)
    assert response.status_code in (201, 400), (
        f"a body-supplied operational_status is either ignored or rejected, "
        f"got HTTP {response.status_code}")
    if response.status_code == 201:
        data = validate_success(response, 201)
        assert data["operational_status"] == "IDLE", (
            "the hull must never open in IN_TOW")
    else:
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_list_barges_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "Every collection endpoint accepts two optional query
    parameters. `limit` controls page size: it defaults to 10, its minimum
    accepted value is 1, and its maximum accepted value is 100."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates
    whether rows remain beyond the current page."

    Design: Corner/entities/list_barges_paginates_with_total_count_and_has_more
    """
    for hull in ("BL-9101", "BL-9102", "BL-9103"):
        create_barge(hull_number=hull)

    first, meta = validate_paginated(api.list_barges(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(first) == 2, f"limit 2 must return two rows, got {len(first)}"
    assert meta["total_count"] == 3, f"total_count counts all matches, got {meta['total_count']}"
    assert meta["has_more"] is True, "rows remain beyond the first page"

    second, meta2 = validate_paginated(api.list_barges(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(second) == 1, f"the tail page carries one row, got {len(second)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False, "no rows remain beyond the tail page"


def test_list_barges_filtered_by_last_cargo_commodity(api):
    """PRD §3.1: "Hulls may be listed narrowed by `operational_status`, by
    `cleanliness_status`, or by `last_cargo_commodity_id`, the last of which
    answers "which hulls last carried this cargo"."

    Design: Corner/entities/list_barges_filtered_by_last_cargo_commodity_id_finds_the_hull
    """
    uan = create_commodity(code="UAN32", commodity_group="FERTILIZER",
                           residue_class="TOXIC", hazard_flag=True, stowage_factor=0.85)
    with_cargo = create_barge(hull_number="BL-9201", last_cargo_commodity_id=uan["id"])
    without_cargo = create_barge(hull_number="BL-9202")

    rows, meta = validate_paginated(
        api.list_barges(ADMIN, params={"last_cargo_commodity_id": uan["id"]}))
    assert meta["total_count"] == 1, (
        f"only the hull whose last cargo was UAN32 matches, got {meta['total_count']}")
    assert rows[0]["id"] == with_cargo["id"]
    assert without_cargo["id"] not in [row["id"] for row in rows], (
        "a hull with no prior cargo must not match the filter")


def test_commodity_read_carries_no_version_or_updated_at(api):
    """PRD §2.4: "Four resource kinds are deliberately immutable reference
    records and therefore carry **only** `id` and `created_at` — they have no
    `updated_at` field and no `version` field at all: commodities, compatibility
    rules, fuel index postings, and river stage readings."
    PRD §2.4: "Implementations must not emit `updated_at` or `version` on those
    four."

    Design: Corner/entities/commodity_is_immutable_and_exposes_no_update_endpoint
    """
    corn = create_commodity(code="CORN", commodity_group="GRAIN",
                            residue_class="CLEAN", hazard_flag=False,
                            stowage_factor=1.28)
    data = validate_success(api.get_commodity(corn["id"], ADMIN))
    assert_commodity(data)
    assert data["code"] == "CORN"
    assert data["commodity_group"] == "GRAIN"
    assert data["residue_class"] == "CLEAN"
    assert data["hazard_flag"] is False
    assert float(data["stowage_factor"]) == 1.28
    assert "updated_at" not in data, "a commodity must not emit updated_at"
    assert "version" not in data, "a commodity must not emit version"


def test_create_contract_without_declared_value_is_rejected(api):
    """PRD §3.3: "It also declares `laytime_hours`, the free laytime allowance
    of at least zero hours granted per barge before demurrage begins to accrue,
    and `declared_value_cents_per_ton` greater than zero, the per-ton value used
    to price loss and short claims."
    PRD §2.7: "**Request shape.** The body carries every required field, every
    enum-typed value is a declared member of its enumeration, every numeric
    field satisfies its declared range, and every datetime parses as ISO 8601 —
    otherwise `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."

    Design: Corner/entities/create_freight_contract_missing_required_field_returns_invalid_request
    """
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    shipper = create_shipper()
    payload = create_freight_contract_payload(shipper["id"], corn["id"])
    payload.pop("declared_value_cents_per_ton")

    validate_error(api.create_freight_contract(payload, BILLER),
                   ApiErrorId.ERR_INVALID_REQUEST.value)
    _, meta = validate_paginated(
        api.list_freight_contracts(BILLER, params={"shipper_id": shipper["id"]}))
    assert meta["total_count"] == 0, "the rejected draft must not have been stored"


def test_create_contract_defaults_claim_settlement_basis_to_deductible(api):
    """PRD §3.3: "One further input, `claim_settlement_basis`, is optional and
    defaults to `DEDUCTIBLE`; its only other legal value is `FRANCHISE`, and it
    decides which of two assessed settlement variants is actually paid when a
    claim is approved."
    PRD §3.3: "A new contract begins with `movement_status` `DRAFT` and
    `billing_status` `NOT_BILLED`, and its `distance_miles` is not yet resolved."

    Design: Corner/entities/create_freight_contract_defaults_claim_settlement_basis_to_deductible
    """
    corn = create_commodity(code="CORN", commodity_group="GRAIN")
    shipper = create_shipper()
    data = validate_success(api.create_freight_contract(
        create_freight_contract_payload(shipper["id"], corn["id"]), BILLER), 201)
    assert data["claim_settlement_basis"] == "DEDUCTIBLE", (
        f"omitting the basis stores DEDUCTIBLE, got {data['claim_settlement_basis']}")
    assert data["movement_status"] == "DRAFT"
    assert data["billing_status"] == "NOT_BILLED"


def test_duplicate_hull_number_rejected(api):
    """PRD §2.7: "**Reference-data uniqueness.** `hull_number` is unique across
    all barges and `code` is unique across all commodities — otherwise
    `ERR_DUPLICATE_HULL_NUMBER` (409). Guards two operations: registering a
    barge, and registering a commodity. The same code covers both collisions."

    Design: Corner/entities/duplicate_hull_number_rejected
    """
    create_barge(hull_number="BL-9301")
    validate_error(
        api.create_barge(
            create_barge_payload(hull_number="BL-9301", capacity_tons=2000,
                                 light_draft_feet=1.6, tons_per_inch_immersion=18.0),
            ADMIN),
        ApiErrorId.ERR_DUPLICATE_HULL_NUMBER.value)
    _, meta = validate_paginated(api.list_barges(ADMIN))
    assert meta["total_count"] == 1, "the duplicate registration must not be stored"


def test_list_with_limit_zero_is_rejected(api):
    """PRD §2.3: "A `limit` outside the range of 1 through 100 inclusive, or a
    negative `offset`, or either parameter supplied as a non-integer, is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/list_endpoint_with_limit_zero_returns_invalid_pagination
    """
    validate_error(api.list_barges(ADMIN, params={"limit": 0}),
                   ApiErrorId.ERR_INVALID_PAGINATION.value)


def test_limit_one_hundred_accepted_and_one_hundred_one_rejected(api):
    """PRD §2.3: "Every collection endpoint accepts two optional query
    parameters. `limit` controls page size: it defaults to 10, its minimum
    accepted value is 1, and its maximum accepted value is 100."
    PRD §2.3: "A `limit` outside the range of 1 through 100 inclusive, or a
    negative `offset`, or either parameter supplied as a non-integer, is
    rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/list_endpoint_with_limit_one_hundred_is_accepted_at_the_ceiling
    """
    create_barge(hull_number="BL-9401")
    rows, meta = validate_paginated(
        api.list_barges(ADMIN, params={"limit": 100, "offset": 0}))
    assert meta["total_count"] == 1, "limit 100 sits on the inclusive ceiling"
    assert len(rows) == 1
    validate_error(api.list_barges(ADMIN, params={"limit": 101, "offset": 0}),
                   ApiErrorId.ERR_INVALID_PAGINATION.value)
