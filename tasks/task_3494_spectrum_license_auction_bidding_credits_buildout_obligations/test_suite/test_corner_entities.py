"""Breadth tests over the entity surface: creation defaults and envelopes,
round-trips, not-found, required fields, enum membership, computed-field
ignoring, pagination, and server-side null defaults."""
from test_helpers import (
    CLOCK_EPOCH_ISO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_area,
    assert_applicant,
    assert_band_plan,
    assert_incumbent,
    assert_license_block,
    assert_millisecond_timestamp,
    create_applicant_payload,
    create_draft_plan,
    create_open_auction,
    get_applicant,
    register_applicant,
    register_incumbent,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_band_plan_creation_defaults_and_envelope(api, auction_admin_headers):
    """PRD §3.1: "an optional free-text `technical_rules` summary of power
    limits and out-of-band emission masks, which defaults to an empty string
    when omitted. A new band plan is `DRAFT`."
    PRD §4: "Operations that create a new resource — a band plan, license
    area, license block, auction, applicant, clock round, bid, assignment
    bid, transfer application, incumbent, or renewal application — return
    `201 Created`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The
    `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with
    three fractional digits."
    PRD §2.5: "The `version` field is an integer that starts at 1 and
    increments by exactly one on every mutation of the resource".

    Design: Corner/entities/band_plan_creation_defaults_and_envelope
    """
    set_clock(CLOCK_EPOCH_ISO)
    resp = api.create_band_plan(
        {"band_name": "3.5 GHz", "frequency_start_mhz": 3550, "frequency_end_mhz": 3700},
        auction_admin_headers,
    )
    data = validate_success(resp, 201)
    envelope = resp.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert_millisecond_timestamp(
        envelope["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
    )
    assert_band_plan(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["technical_rules"] == ""  # default applied when omitted
    assert data["created_at"] and data["updated_at"]


def test_license_block_create_roundtrip_via_plan_list(api, auction_admin_headers):
    """PRD §3.1: "A license block carries the plan's `band_plan_id`, a
    `category` of `CATEGORY_A`, `CATEGORY_B`, `CATEGORY_C`, or `CATEGORY_D`,
    an integer `mhz_size` of at least 1, a `supply_per_area` of at least 1
    (the number of licenses of this category that will exist in every license
    area), and a `price_per_mhz_pop_cents` opening-price coefficient of at
    least 0."

    Design: Corner/entities/license_block_create_roundtrip_via_plan_list
    """
    plan = create_draft_plan()
    resp = api.create_license_block(
        {
            "band_plan_id": plan["id"],
            "category": "CATEGORY_A",
            "mhz_size": 10,
            "supply_per_area": 2,
            "price_per_mhz_pop_cents": 50,
        },
        auction_admin_headers,
    )
    block = validate_success(resp, 201)
    assert_license_block(block)

    rows, _meta = validate_paginated(
        api.list_license_blocks(plan["id"], auction_admin_headers)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == block["id"]
    assert row["category"] == "CATEGORY_A"
    assert row["mhz_size"] == 10
    assert row["supply_per_area"] == 2
    assert row["price_per_mhz_pop_cents"] == 50
    assert row["version"] == 1
    assert row["created_at"]


def test_applicant_get_returns_stored_fields(api, transfer_reviewer_headers):
    """PRD §3.2: "The new applicant starts `SUBMITTED` with a zeroed ledger —
    `upfront_paid_cents`, `upfront_held_cents`, `upfront_refunded_cents`,
    `upfront_forfeited_cents`, `eligibility_units`,
    `initial_eligibility_units`, and `credit_pct` all begin at 0".
    PRD §4: "Rows marked "Any" are readable by all four roles."

    Design: Corner/entities/applicant_get_returns_stored_fields
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    r = register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )

    # Read by a role that is not the owner: reads are open to all four roles.
    data = validate_success(api.get_applicant(r["id"], transfer_reviewer_headers), 200)
    assert_applicant(data)
    assert data["legal_name"] == "Rural Wireless Co"
    assert data["claims_rural_credit"] is True
    assert data["claims_small_business"] is False
    assert data["service_population"] == 200_000
    assert data["own_annual_revenue_cents"] == 0
    assert data["ownership_interests"] == [
        {"holder_name": "Sole Owner", "stake_pct": 100, "holder_annual_revenue_cents": 0}
    ]
    # credit_pct is in PRD §3.2's zeroed-ledger list. attributable_revenue_cents
    # is not: PRD only says qualification computes it, so its pre-QUALIFY value
    # is not PRD-determined and is not asserted here.
    assert data["credit_pct"] == 0
    for field in (
        "upfront_paid_cents",
        "upfront_held_cents",
        "upfront_refunded_cents",
        "upfront_forfeited_cents",
        "eligibility_units",
        "initial_eligibility_units",
    ):
        assert data[field] == 0, f"{field} must start at 0"
    assert data["status"] == "SUBMITTED"
    assert data["version"] == 1


def test_get_license_not_found_returns_404(api, auction_admin_headers):
    """PRD §2.7: "path identifiers are resolved strictly left to right, and
    the first identifier that does not resolve to an existing resource yields
    `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/get_license_not_found_returns_404
    """
    set_clock(CLOCK_EPOCH_ISO)
    resp = api.get_license(NON_EXISTENT_UUID, auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert resp.json()["response_type"] == "error"


def test_license_area_create_missing_required_population(api, auction_admin_headers):
    """PRD §2.7: "a request body that is malformed — a missing required
    field, a mistyped or out-of-range value, or an unknown enum member — is
    rejected with `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "A license area carries the plan's `band_plan_id`, a short
    `area_code` such as PEA001, a display `name`, and a `population` of at
    least 1".

    Design: Corner/entities/license_area_create_missing_required_population
    """
    plan = create_draft_plan()
    resp = api.create_license_area(
        {"band_plan_id": plan["id"], "area_code": "PEA009", "name": "No Pop"},
        auction_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400

    rows, _meta = validate_paginated(
        api.list_license_areas(plan["id"], auction_admin_headers)
    )
    assert rows == []


def test_license_block_invalid_enum_category_returns_invalid_request(
    api, auction_admin_headers
):
    """PRD §2.7: "a request body that is malformed — a missing required
    field, a mistyped or out-of-range value, or an unknown enum member — is
    rejected with `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "a `category` of `CATEGORY_A`, `CATEGORY_B`, `CATEGORY_C`, or
    `CATEGORY_D`".

    Design: Corner/entities/license_block_invalid_enum_category_returns_invalid_request
    """
    plan = create_draft_plan()
    resp = api.create_license_block(
        {
            "band_plan_id": plan["id"],
            "category": "CATEGORY_Z",
            "mhz_size": 10,
            "supply_per_area": 1,
            "price_per_mhz_pop_cents": 50,
        },
        auction_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400

    rows, _meta = validate_paginated(
        api.list_license_blocks(plan["id"], auction_admin_headers)
    )
    assert rows == []


def test_applicant_computed_credit_pct_input_ignored(api, bidder_headers):
    """PRD §3.3: "The two credits are mutually exclusive — that is what the
    conflict check enforces — and `credit_pct` is only ever written by
    qualification: client-supplied values are ignored everywhere."

    Design: Corner/entities/applicant_computed_credit_pct_input_ignored
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    payload = create_applicant_payload(ctx["auction"]["id"], legal_name="Cheeky Bidder")
    payload["credit_pct"] = 99  # server-computed field; must be discarded
    data = validate_success(api.create_applicant(payload, bidder_headers), 201)
    assert data["credit_pct"] == 0
    assert get_applicant(data["id"])["credit_pct"] == 0


def test_applicants_list_paginates_with_total_count_and_has_more(
    api, auction_admin_headers
):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0." and "List responses
    carry `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the envelope."

    Design: Corner/entities/applicants_list_paginates_with_total_count_and_has_more
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]
    for name in ("Rural Wireless Co", "Beta Radio", "Gamma Radio"):
        register_applicant(auction_id, legal_name=name)

    page1, meta1 = validate_paginated(
        api.list_applicants(auction_id, auction_admin_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3  # spans the full filtered set, not the page
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_applicants(auction_id, auction_admin_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    ids1 = {row["id"] for row in page1}
    ids2 = {row["id"] for row in page2}
    assert ids1.isdisjoint(ids2)
    assert len(ids1 | ids2) == 3


def test_incumbent_window_fields_default_null(api):
    """PRD §3.1: "A new incumbent starts in `NOTIFIED` status; the relocation
    workflow of §3.7 later moves it through plan submission, dispute,
    relocation, and clearing, and its `transition_window_start`,
    `transition_window_end`, `shares_proportional`, and `shares_equal` fields
    stay unset until that workflow fills them in."

    Design: Corner/entities/incumbent_window_fields_default_null
    """
    plan = create_draft_plan()
    area = add_area(plan["id"], "PEA002")
    inc = register_incumbent(
        plan["id"], area["id"], callsign="KNEW100", relocation_cost_cents=750_000
    )
    assert_incumbent(inc)
    assert inc["status"] == "NOTIFIED"
    assert inc["transition_window_start"] is None
    assert inc["transition_window_end"] is None
    # PRD §3.1: the share arrays "stay unset" until the relocation workflow
    # fills them in. "Unset" does not uniquely determine null vs [], so the
    # assertion covers only the PRD content: no shares have been computed.
    assert inc["shares_proportional"] in (None, [])
    assert inc["shares_equal"] in (None, [])
    assert inc["version"] == 1
