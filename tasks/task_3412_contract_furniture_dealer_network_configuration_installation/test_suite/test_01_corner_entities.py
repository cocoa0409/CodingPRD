"""Entity creation defaults, required fields, shape constraints, computed
fields, server-minted system fields, not-found behavior, and FK reverse
listing (PRD §2.5, §2.9, §3.1-§3.4)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_configuration,
    assert_dealer,
    assert_end_user,
    create_configuration,
    create_dealer,
    is_valid_uuid,
    lock_configuration,
    make_dealer_headers,
    make_end_user_payload,
    make_module_entry,
    setup_dealer_world,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_ADMIN = TEST_USERS["admin_headers"]


def test_dealer_creation_applies_defaults(api):
    """PRD §3.1: "an optional `showroom_compliant` flag that defaults to true.
    A new dealer starts in `ACTIVE` status, with `suspended_at` null."
    PRD §2.5: "Every resource in this API carries the same four system-managed
    properties: `id`, a server-minted UUID with no type prefix".

    Design: Corner/entities/entity_dealer_creation_applies_defaults
    """
    resp = api.create_dealer(
        {
            "name": "Dealer Alpha",
            "territory_codes": ["MI"],
            "service_capability_level": 3,
        },
        TEST_ADMIN,
    )
    dealer = validate_success(resp, 201)
    assert_dealer(dealer)
    assert dealer["showroom_compliant"] is True
    assert dealer["status"] == "ACTIVE"
    assert dealer["suspended_at"] is None
    assert dealer["version"] == 1
    assert is_valid_uuid(dealer["id"])


def test_dealer_missing_name_returns_400(api):
    """PRD §2.9: "(5) request body shape, else `ERR_VALIDATION`" — "required
    fields present". PRD §3.1: "A `ManufacturerAdmin` onboards a dealership
    by creating a `Dealer` with a company `name`, a non-empty
    `territory_codes` array in which every entry is a two-letter uppercase
    code, a `service_capability_level` from 1 to 5, and an optional
    `showroom_compliant` flag that defaults to true."

    Design: Corner/entities/entity_dealer_missing_name_returns_400
    """
    resp = api.create_dealer(
        {"territory_codes": ["MI"], "service_capability_level": 3}, TEST_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_enduser_missing_industry_returns_400(api):
    """PRD §3.2: "Large corporate customers are registered as `EndUser`
    records carrying a `name` and a free-text `industry` label" and §2.9 step
    5 rejects missing required fields with `ERR_VALIDATION`.

    Design: Corner/entities/entity_enduser_missing_industry_returns_400
    """
    resp = api.create_end_user({"name": "MegaCorp"}, TEST_ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_configuration_qty_zero_rejected(api):
    """PRD §3.4: "a `modules` array — a non-empty list of entries, each naming
    a `module_type`, a `fabric_grade`, and a `qty` of at least 1"; §2.9 step 5:
    "`qty`, `planned_units`, and `crew_size` at least 1" else ERR_VALIDATION.

    Design: Corner/entities/entity_configuration_qty_zero_rejected
    """
    dealer = create_dealer(api)
    resp = api.create_configuration(
        {
            "name": "Zero qty",
            "modules": [make_module_entry("TASK_CHAIR_SET", "A", 0)],
        },
        make_dealer_headers(dealer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_lock_computes_totals_and_lead_time(api):
    """PRD §3.4: "On success the system computes and caches three figures —
    `total_units`, `list_total_cents`, and `max_lead_time_days`". For
    2 x WORKSTATION_6X6 (A) + 1 x STORAGE_WALL on families with base leads
    42/21: total_units 3, list_total_cents 2*85837 + 66300 = 237974, lead
    max(42+0, 21+0) + 3 queue days (total <= 49) = 45.

    Design: Corner/entities/entity_lock_computes_totals_and_lead_time
    """
    ctx = setup_dealer_world(
        api,
        family_specs=(("SYS-7500", "SYSTEMS", 42), ("STOR-1100", "STORAGE", 21)),
    )
    spec = create_configuration(
        api,
        ctx["dealer"]["id"],
        modules=[
            make_module_entry("WORKSTATION_6X6", "A", 2),
            make_module_entry("STORAGE_WALL", None, 1),
        ],
    )
    locked = lock_configuration(api, spec, ctx["dealer"]["id"])
    assert_configuration(locked)
    assert locked["status"] == "LOCKED"
    assert locked["total_units"] == 3
    assert locked["list_total_cents"] == 237974
    assert locked["max_lead_time_days"] == 45


def test_system_fields_client_input_ignored(api):
    """PRD §2.9 step 5: "Unknown input fields are ignored — never stored and
    never an error — including a client-supplied `id`, `created_at`, or
    `version`."

    Design: Corner/entities/entity_system_fields_client_input_ignored
    """
    supplied_id = "11111111-1111-1111-1111-111111111111"
    payload = make_end_user_payload()
    payload["id"] = supplied_id
    payload["version"] = 99
    resp = api.create_end_user(payload, TEST_ADMIN)
    end_user = validate_success(resp, 201)
    assert_end_user(end_user)
    assert end_user["version"] == 1, "server mints its own version"
    assert end_user["id"] != supplied_id, "server mints its own id"
    assert is_valid_uuid(end_user["id"])


def test_get_nonexistent_configuration_returns_404(api):
    """PRD §2.9 step 3: "resource existence — URL path identifiers are
    resolved left to right" and "a missing identifier yielding the
    referenced resource's not-found error" (§5 maps
    ERR_CONFIGURATION_NOT_FOUND to 404).

    Design: Corner/entities/entity_get_nonexistent_configuration_returns_404
    """
    dealer = create_dealer(api)
    resp = api.get_configuration(
        NON_EXISTENT_UUID, make_dealer_headers(dealer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONFIGURATION_NOT_FOUND)


def test_fk_reverse_list_configurations_by_dealer(api):
    """PRD §3.4: "Configurations can be listed filtered by `dealer_id` and
    `status`". A dealer with no configurations yields an empty page, not an
    error.

    Design: Corner/entities/entity_fk_reverse_list_configurations_by_dealer
    """
    dealer_a = create_dealer(api, name="Dealer A")
    dealer_b = create_dealer(api, name="Dealer B", territory_codes=["OH"])
    create_configuration(api, dealer_a["id"], name="A spec")

    data_a, meta_a = validate_paginated(
        api.list_configurations(TEST_ADMIN, params={"dealer_id": dealer_a["id"]})
    )
    assert meta_a["total_count"] == 1
    assert len(data_a) == 1
    assert data_a[0]["dealer_id"] == dealer_a["id"]

    data_b, meta_b = validate_paginated(
        api.list_configurations(TEST_ADMIN, params={"dealer_id": dealer_b["id"]})
    )
    assert meta_b["total_count"] == 0
    assert data_b == []
