"""Corner coverage: entity creation, computed fields, required fields, not-found,
pagination, append-only immutability, residency membership."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    NON_EXISTENT_UUID,
    checkout,
    create_patron,
    create_patron_payload,
    make_library_admin_headers,
    setup_base,
    setup_base_with_title,
    setup_ocou_library,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_library_create_applies_policy_defaults(api):
    """PRD §3.1: "Registering a library requires a `name` and the
    `residency_region_codes` array — the postal codes eligible for card
    registration — and accepts a long list of optional policy knobs, each with
    a default: `card_validity_days` (730), `max_concurrent_loans` (10),
    `max_concurrent_holds` (15), `loan_period_days` (21),
    `renewal_period_days` (21), `max_renewals` (2), `pickup_window_hours` (72),
    `skip_the_line_loan_days` (7), `auto_purchase_enabled` (false),
    `holds_per_copy_ratio` (4), `wait_target_days` (28), and
    `auto_purchase_max_cents` (10000). A new library starts `ACTIVE` with
    `version` 1."

    Design: Corner/entities/library_create_applies_policy_defaults_and_returns_common_fields
    """
    from test_helpers import create_consortium, set_clock, api_client
    set_clock()
    consortium = create_consortium()
    resp = api_client.create_library(
        consortium["id"],
        {"name": "Library L", "residency_region_codes": ["94301"]},
        ADMIN,
    )
    lib = validate_success(resp, expected_status=201)
    assert lib["loan_period_days"] == 21
    assert lib["renewal_period_days"] == 21
    assert lib["max_renewals"] == 2
    assert lib["pickup_window_hours"] == 72
    assert lib["card_validity_days"] == 730
    assert lib["max_concurrent_loans"] == 10
    assert lib["max_concurrent_holds"] == 15
    assert lib["auto_purchase_enabled"] is False
    assert lib["holds_per_copy_ratio"] == 4
    assert lib["wait_target_days"] == 28
    assert lib["auto_purchase_max_cents"] == 10000
    assert lib["status"] == "ACTIVE"
    assert lib["version"] == 1
    assert lib["id"] and lib["created_at"] and lib["updated_at"]


def test_patron_create_computes_card_expiry_from_library_validity(api):
    """PRD §3.3: "A registered card starts `ACTIVE`, and the server computes
    `card_expires_at` as the registration date plus the library's
    `card_validity_days`."

    Design: Corner/entities/patron_create_computes_card_expiry_from_library_validity
    """
    ctx = setup_base()
    lib = ctx["library"]
    patron = create_patron(lib["id"], external_card_number="P-0",
                           full_name="Patron Zero")
    assert patron["status"] == "ACTIVE"
    assert patron["card_expires_at"] == "2028-08-31T00:00:00Z", (
        f"2026-09-01 + 730 days, got {patron['card_expires_at']}"
    )
    assert patron["active_loan_count"] == 0
    assert patron["active_hold_count"] == 0


def test_patron_create_missing_postal_code_returns_invalid_request(api):
    """PRD §2.9: "First, request-body well-formedness: required fields present,
    value types correct, enum members recognized, no nulls in required
    positions — violations return `ERR_INVALID_REQUEST`."

    Design: Corner/entities/patron_create_missing_required_postal_code_returns_invalid_request
    """
    ctx = setup_base()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    resp = api.create_patron(
        lib["id"], {"external_card_number": "P-9", "full_name": "No Zip"},
        lib_admin,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    patrons, meta = validate_paginated(api.list_patrons(lib["id"], lib_admin))
    assert len(patrons) == 0, "no patron row may be created by the rejected call"


def test_title_get_with_unknown_id_returns_title_not_found(api):
    """PRD §2.9: "Fourth, path-template identifiers resolve, validated
    left-to-right (consortium before library before the child resource) with
    the corresponding not-found error (`ERR_NOT_FOUND` generically, or the
    entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/entities/title_get_with_unknown_id_returns_title_not_found
    """
    ctx = setup_base()
    resp = api.get_title(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TITLE_NOT_FOUND)


def test_patrons_list_paginates_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the
    number of items skipped and defaults to 0. All list endpoints sort by
    `created_at` in ascending order unless otherwise specified. The `meta`
    object of every list response carries `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/patrons_list_paginates_total_count_and_has_more
    """
    ctx = setup_base()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    for i in range(3):
        create_patron(lib["id"], external_card_number=f"P-{i}",
                      full_name=f"Patron {i}")
    page1, meta1 = validate_paginated(
        api.list_patrons(lib["id"], lib_admin, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api.list_patrons(lib["id"], lib_admin, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    page_all, meta_all = validate_paginated(api.list_patrons(lib["id"], lib_admin))
    assert len(page_all) == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_circulation_event_is_immutable_append_only(api):
    """PRD §2.4: "The CirculationEvent resource is the single exception: it
    carries `id` and `created_at` only. Because events are immutable records of
    things that already happened, they have no `updated_at` and no `version`;
    both fields are absent from the event representation."

    Design: Corner/entities/circulation_event_is_immutable_append_only
    """
    ctx = setup_ocou_library(copies=1)
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    loan = checkout(p0["id"], ctx["title"]["id"])
    events, meta = validate_paginated(
        api.list_events(ANALYST, params={"loan_id": loan["id"],
                                         "event_type": "CHECKOUT"})
    )
    assert len(events) == 1
    event = events[0]
    assert event["id"] and event["created_at"]
    assert event["occurred_at"] == "2026-09-01T00:00:00Z"
    assert "updated_at" not in event, "events carry no updated_at"
    assert "version" not in event, "events carry no version"


def test_patron_residency_region_outside_list_rejected(api):
    """PRD §3.3: "Registration enforces the residency rule: the supplied
    `postal_code` must be an element of the library's
    `residency_region_codes`, or the request fails with
    `ERR_RESIDENCY_VIOLATION`."

    Design: Corner/entities/patron_residency_region_outside_list_rejected
    """
    ctx = setup_base()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    resp = api.create_patron(
        lib["id"],
        {"external_card_number": "P-X", "full_name": "Out Of Area",
         "postal_code": "10001"},
        lib_admin,
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_VIOLATION)
    patrons, meta = validate_paginated(api.list_patrons(lib["id"], lib_admin))
    assert len(patrons) == 0
