"""Standing up the programme: business units, their derived ledger fields,
people records, request-shape rejection and list pagination.
"""
from test_helpers import (
    ADMIN, COUNSEL, UNKNOWN_UUID, ApiErrorId, assert_business_unit,
    assert_employee, create_business_unit_payload, create_employee_payload,
    register_business_unit, register_employee, set_clock, validate_error,
    validate_paginated, validate_success,
)


def test_register_business_unit_returns_zeroed_ledger_and_version_one(api):
    """PRD §3.1: "Alongside those inputs, a freshly registered unit exposes six
    derived fields that the service maintains on its behalf: `exposure_points`
    starting at 0, `manual_exposure_adjustment_points` starting at 0,
    `review_minutes_consumed` starting at 0, `risk_band` starting at `LOW`,
    `posture` starting at `OPEN`, and `document_violation_count` starting at 0."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created
    and increments by exactly 1 on each mutation."

    Design: Corner/entities/business_unit_creation_returns_declared_defaults_and_version_one
    """
    set_clock()
    payload = create_business_unit_payload()
    data = validate_success(api.create_business_unit(payload, ADMIN), 201)

    assert_business_unit(data)
    assert data["exposure_points"] == 0
    assert data["manual_exposure_adjustment_points"] == 0
    assert data["review_minutes_consumed"] == 0
    assert data["document_violation_count"] == 0
    assert data["risk_band"] == "LOW"
    assert data["posture"] == "OPEN"
    assert data["version"] == 1


def test_business_unit_id_is_a_bare_uuid_without_a_type_prefix(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix — clients
    never supply it."

    Design: Corner/entities/business_unit_creation_returns_declared_defaults_and_version_one
    """
    set_clock()
    data = validate_success(
        api.create_business_unit(create_business_unit_payload(), ADMIN), 201)

    assert len(data["id"]) == 36, f"expected a bare UUID, got {data['id']!r}"
    assert data["id"].count("-") == 4
    assert "_" not in data["id"], "the id carries no type prefix"


def test_omitted_budget_fields_take_their_declared_defaults(api):
    """PRD §3.1: "`exposure_budget_points` caps the cumulative exposure the unit
    will tolerate before new competitor contacts are refused outright, and
    defaults to 100 when omitted; it must be strictly greater than zero."
    PRD §3.1: "`review_minutes_budget` caps the counsel review minutes the unit
    may reserve across all its trade-association participations, and defaults to
    480 — that is, eight hours of counsel attention per unit — and must likewise
    be strictly greater than zero."

    Design: Corner/entities/business_unit_optional_budget_fields_apply_declared_defaults
    """
    set_clock()
    payload = {
        "name": "Defaults Unit",
        "market_code": "EU-DEF",
        "market_share_bps": 900,
        "interaction_point_count": 1,
        "competitor_overlap_pct": 0,
    }
    data = validate_success(api.create_business_unit(payload, ADMIN), 201)

    assert data["exposure_budget_points"] == 100
    assert data["review_minutes_budget"] == 480


def test_reading_an_unknown_business_unit_returns_its_own_not_found_code(api):
    """PRD §2.7: "**Path existence.** Every resource named in the URL path
    exists, validated left to right — otherwise the not-found code for the
    entity that failed, HTTP 404. Applies to every endpoint carrying a path
    parameter."

    Design: Corner/entities/business_unit_get_with_unknown_uuid_returns_not_found
    """
    set_clock()
    resp = api.get_business_unit(UNKNOWN_UUID, COUNSEL)

    validate_error(resp, ApiErrorId.ERR_BUSINESS_UNIT_NOT_FOUND.value)
    assert resp.status_code == 404


def test_business_unit_without_market_code_is_rejected_as_invalid_request(api):
    """PRD §2.7: "**Request shape.** Every required field is present, every
    enum-valued field carries a declared member, numeric values respect their
    declared ranges (`market_share_bps` from 0 through 10000,
    `competitor_overlap_pct` from 0 through 100, `gravity_pct` from 0 through
    30, `score` from 0 through 100, `sample_size` strictly greater than 0,
    `affected_years` non-empty), and every datetime is well-formed ISO 8601 UTC
    — otherwise `ERR_INVALID_REQUEST`, HTTP 400."
    PRD §3.1: "The registration payload carries a `name`, a `market_code` naming
    the relevant market used for banding, a `market_share_bps` expressing market
    share in basis points (from 0 through 10000, so a unit holding one third of
    its market registers as 3333), an `interaction_point_count` counting
    recurring structural interaction points with competitors such as joint
    ventures, standards bodies and shared distributors (which may be zero but
    never negative), and a `competitor_overlap_pct` giving the percentage of
    revenue in product lines where a direct competitor is also present."

    Design: Corner/entities/business_unit_creation_missing_required_market_code_returns_invalid_request
    """
    set_clock()
    payload = {
        "name": "No Market Code",
        "market_share_bps": 1200,
        "interaction_point_count": 4,
        "competitor_overlap_pct": 25,
    }
    resp = api.create_business_unit(payload, ADMIN)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400

    rows, meta = validate_paginated(api.list_business_units(COUNSEL))
    assert meta["total_count"] == 0, "a rejected registration persists nothing"


def test_market_share_bps_above_ten_thousand_is_rejected_not_clamped(api):
    """PRD §2.7: "**Request shape.** Every required field is present, every
    enum-valued field carries a declared member, numeric values respect their
    declared ranges (`market_share_bps` from 0 through 10000,
    `competitor_overlap_pct` from 0 through 100, `gravity_pct` from 0 through
    30, `score` from 0 through 100, `sample_size` strictly greater than 0,
    `affected_years` non-empty), and every datetime is well-formed ISO 8601 UTC
    — otherwise `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/business_unit_market_share_bps_above_ten_thousand_returns_invalid_request
    """
    set_clock()
    payload = create_business_unit_payload(
        name="Impossible Share", market_code="EU-IMP", market_share_bps=20000)
    resp = api.create_business_unit(payload, ADMIN)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400


def test_undeclared_approval_tier_member_is_rejected_as_invalid_request(api):
    """PRD §3.4: "The administrator supplies its `name`, its `approval_tier` —
    one of `TIER_1_LOW`, `TIER_2_MEDIUM` or `TIER_3_HIGH`, expressing how much
    counsel scrutiny membership warrants — and a `competitor_density_pct` giving
    the percentage of the association's membership that competes with the
    participating unit."
    PRD §2.7: "**Request shape.** Every required field is present, every
    enum-valued field carries a declared member, numeric values respect their
    declared ranges (`market_share_bps` from 0 through 10000,
    `competitor_overlap_pct` from 0 through 100, `gravity_pct` from 0 through
    30, `score` from 0 through 100, `sample_size` strictly greater than 0,
    `affected_years` non-empty), and every datetime is well-formed ISO 8601 UTC
    — otherwise `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/trade_association_invalid_approval_tier_enum_returns_invalid_request
    """
    set_clock()
    payload = {
        "name": "Bad Tier Council",
        "approval_tier": "TIER_4_EXTREME",
        "competitor_density_pct": 10,
    }
    resp = api.create_association(payload, ADMIN)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400


def test_new_employee_starts_with_no_training_and_no_clearance(api):
    """PRD §3.1: "A new employee starts with `clearance_status` of `NONE` and
    `training_status` of `NONE`, and with a null `training_expires_at`."

    Design: Corner/entities/employee_computed_training_status_starts_none_and_clearance_starts_none
    """
    set_clock()
    unit = register_business_unit()
    payload = create_employee_payload(unit["id"], role_category="SALES")
    data = validate_success(api.create_employee(payload, ADMIN), 201)

    assert_employee(data)
    assert data["training_status"] == "NONE"
    assert data["training_expires_at"] is None
    assert data["clearance_status"] == "NONE"


def test_employee_against_an_unknown_business_unit_is_refused(api):
    """PRD §2.7: "**Body reference existence.** Every identifier supplied in the
    request body resolves to a live row, validated in the order the fields are
    listed for that endpoint — otherwise the not-found code for the entity that
    failed, HTTP 404. Applies to every write endpoint carrying reference
    fields."

    Design: Corner/entities/employee_creation_with_unknown_business_unit_returns_business_unit_not_found
    """
    set_clock()
    payload = {
        "business_unit_id": UNKNOWN_UUID,
        "full_name": "Ghost Employee",
        "email": "ghost@example.com",
        "role_category": "OTHER",
    }
    resp = api.create_employee(payload, ADMIN)

    validate_error(resp, ApiErrorId.ERR_BUSINESS_UNIT_NOT_FOUND.value)
    assert resp.status_code == 404


def test_employee_list_filtered_by_owning_business_unit(api):
    """PRD §3.1: "Employees may be listed filtered by their owning unit, their
    `role_category` and their `clearance_status`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`; `total_count` counts the rows matching the
    filters before the window is applied, and `has_more` is true exactly when
    rows remain beyond the current window."

    Design: Corner/entities/employees_filtered_list_by_business_unit_returns_only_that_units_rows
    """
    set_clock()
    unit_x = register_business_unit(name="Unit X", market_code="EU-X")
    unit_y = register_business_unit(name="Unit Y", market_code="EU-Y")
    x1 = register_employee(unit_x["id"], role_category="SALES")
    x2 = register_employee(unit_x["id"], role_category="LEGAL")
    y1 = register_employee(unit_y["id"], role_category="PRICING")

    rows, meta = validate_paginated(
        api.list_employees(COUNSEL, params={"business_unit_id": unit_x["id"]}))
    ids = [row["id"] for row in rows]
    assert meta["total_count"] == 2, "unit X holds exactly two employees"
    assert meta["has_more"] is False
    assert x1["id"] in ids and x2["id"] in ids
    assert y1["id"] not in ids, "unit Y's employee must not leak into the filter"

    rows_y, meta_y = validate_paginated(api.list_employees(
        COUNSEL, params={"business_unit_id": unit_y["id"], "limit": 1, "offset": 0}))
    assert meta_y["total_count"] == 1
    assert meta_y["has_more"] is False
    assert [row["id"] for row in rows_y] == [y1["id"]]


def test_pagination_limit_outside_one_through_hundred_is_refused(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, and must be an integer no
    smaller than 1 and no larger than 100. `offset` defaults to 0 when omitted,
    and must be an integer no smaller than 0; there is no upper bound on
    `offset`. A `limit` outside the permitted range, or a negative `offset`, or
    a non-integer value for either, is rejected with `ERR_INVALID_PAGINATION`
    and HTTP 400."

    Design: Corner/validations/pagination_limit_zero_returns_invalid_pagination
    """
    set_clock()
    register_business_unit()

    zero = api.list_business_units(COUNSEL, params={"limit": 0, "offset": 0})
    validate_error(zero, ApiErrorId.ERR_INVALID_PAGINATION.value)
    assert zero.status_code == 400

    over = api.list_business_units(COUNSEL, params={"limit": 101})
    validate_error(over, ApiErrorId.ERR_INVALID_PAGINATION.value)
    assert over.status_code == 400

    rows, meta = validate_paginated(api.list_business_units(COUNSEL))
    assert meta["limit"] == 10, "limit defaults to 10 when omitted"
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
