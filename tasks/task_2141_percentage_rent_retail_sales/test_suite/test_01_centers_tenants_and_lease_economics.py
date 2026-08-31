"""Standing up centers, tenants and leases: registration, derived economics,
activation and the lease amendment concurrency guard.
"""
from test_helpers import (
    AUDITOR, CENTER_ADMIN, LEASE_ADMIN, TEST_DEFAULTS, ApiErrorId,
    activate_lease, assert_center, assert_instant_equals, assert_lease,
    assert_tenant, create_center, create_center_payload, create_lease,
    create_lease_payload, create_tenant, create_tenant_payload, lease_version,
    read_center, read_lease, read_tenant, set_clock, set_tenant_status,
    setup_active_lease, validate_error, validate_paginated, validate_success,
)

UNKNOWN_IDS = {
    "center": "00000000-0000-4000-8000-000000000001",
    "tenant": "00000000-0000-4000-8000-000000000002",
    "lease_year": "00000000-0000-4000-8000-000000000003",
    "sales_report": "00000000-0000-4000-8000-000000000004",
    "charge": "00000000-0000-4000-8000-000000000005",
    "co_tenancy_clause": "00000000-0000-4000-8000-000000000006",
    "co_tenancy_event": "00000000-0000-4000-8000-000000000007",
    "kick_out_clause": "00000000-0000-4000-8000-000000000008",
    "audit": "00000000-0000-4000-8000-000000000009",
    "lease": "00000000-0000-4000-8000-000000000000",
}


def test_register_center_starts_with_zeroed_occupancy_metrics(api):
    """PRD §3.1: "Three further attributes are derived rather than supplied and
    initialise to zero on registration: `occupied_gla_sqft`, `occupancy_bps`
    and `open_anchor_count`."
    PRD §2.4: "Alongside `id`, most resources carry `created_at` and
    `updated_at` — both ISO 8601 UTC timestamps with three fractional digits —
    and `version`, an integer that starts at 1 when the resource is created and
    increases by exactly 1 on every mutation of that resource, including
    mutations performed as a side effect of an operation targeting some other
    resource."

    Design: Corner/entities/create_center_returns_201_with_derived_zero_metrics
    """
    payload = create_center_payload(fiscal_year_start_month=9)
    data = validate_success(api.create_center(payload, CENTER_ADMIN), 201)

    assert_center(data)
    assert data["occupied_gla_sqft"] == 0
    assert data["occupancy_bps"] == 0
    assert data["open_anchor_count"] == 0
    assert data["version"] == 1, "a freshly created resource carries version 1"
    assert data["code"] == "NGC"
    assert data["fiscal_year_start_month"] == 9


def test_center_fiscal_year_start_month_defaults_to_january(api):
    """PRD §3.1: "The centre's reporting calendar opens on
    `fiscal_year_start_month`, a calendar month from 1 to 12 that defaults to 1
    when the caller omits it."

    Design: Corner/entities/center_fiscal_year_start_month_defaults_to_one
    """
    payload = create_center_payload(name="Southgate Plaza", code="SGP",
                                    total_gla_sqft=250_000,
                                    anchor_gla_sqft=100_000)
    payload.pop("fiscal_year_start_month", None)

    data = validate_success(api.create_center(payload, CENTER_ADMIN), 201)
    assert data["fiscal_year_start_month"] == 1


def test_tenant_registers_in_prospect_with_derived_anchor_flag(api):
    """PRD §3.1: "From the category the service derives `is_anchor`, which is
    true exactly when the category is `ANCHOR` or `JUNIOR_ANCHOR` and false for
    the other three. A newly registered tenant enters the system in `PROSPECT`
    status."
    PRD §3.1: "`open_anchor_count` becomes the number of tenants of that center
    whose `is_anchor` is true **and** whose `status` is `OPERATING` — dark and
    vacated anchors do not count, which is precisely why an anchor going dark
    is a co-tenancy event."

    Design: Corner/entities/tenant_created_in_prospect_with_derived_is_anchor
    """
    center = create_center()

    junior = validate_success(
        api.create_tenant(
            create_tenant_payload(center["id"], legal_name="Junior Box LLC",
                                  trade_name="JuniorBox",
                                  category="JUNIOR_ANCHOR", gla_sqft=40_000),
            CENTER_ADMIN),
        201,
    )
    inline = validate_success(
        api.create_tenant(
            create_tenant_payload(center["id"], legal_name="Small Shop LLC",
                                  trade_name="SmallShop", category="INLINE",
                                  gla_sqft=2_000),
            LEASE_ADMIN),
        201,
    )

    assert_tenant(junior)
    assert_tenant(inline)
    assert junior["status"] == "PROSPECT"
    assert junior["is_anchor"] is True
    assert inline["is_anchor"] is False

    center_now = read_center(center["id"])
    assert center_now["open_anchor_count"] == 0, (
        "a PROSPECT anchor is not OPERATING, so it is not counted")


def test_lease_publishes_natural_breakpoint_and_documented_starting_values(api):
    """PRD §3.2: "A `NATURAL` breakpoint is derived: `natural_breakpoint_cents`
    is the lease's `annual_base_rent_cents` multiplied by 10000 and divided by
    `percentage_rate_bps`, rounded half up to whole cents."
    PRD §3.2: "The service still computes `natural_breakpoint_cents` for
    reference in both cases, and it publishes `effective_breakpoint_cents`,
    which equals `artificial_breakpoint_cents` when the type is `ARTIFICIAL`
    and equals `natural_breakpoint_cents` when the type is `NATURAL`."
    PRD §3.2: "`delinquency_strikes` counts estimate billings issued against
    this lease's reports and starts at 0."

    Design: Corner/entities/lease_natural_breakpoint_is_computed_from_base_rent_and_rate
    """
    center = create_center()
    tenant = create_tenant(center["id"], legal_name="Natural BP LLC",
                           trade_name="NatShop")

    data = validate_success(
        api.create_lease(
            create_lease_payload(center["id"], tenant["id"], suite_code="3101"),
            CENTER_ADMIN),
        201,
    )

    assert_lease(data)
    assert data["natural_breakpoint_cents"] == 200_000_000
    assert data["effective_breakpoint_cents"] == 200_000_000
    assert data["status"] == "DRAFT"
    assert data["co_tenancy_status"] == "COMPLIANT"
    assert data["delinquency_strikes"] == 0
    assert data["watchlist_status"] == "NORMAL"


def test_read_lease_with_unknown_id_returns_lease_not_found(api):
    """PRD §2.9: "**Existence.** Every resource named in the URL path must
    exist, validated left to right; only then is every id referenced in the
    request body resolved. The rejection is the not-found code matching
    whichever resource was missing: `ERR_CENTER_NOT_FOUND`,
    `ERR_TENANT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_LEASE_YEAR_NOT_FOUND`,
    `ERR_SALES_REPORT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
    `ERR_CO_TENANCY_CLAUSE_NOT_FOUND`, `ERR_CO_TENANCY_EVENT_NOT_FOUND`,
    `ERR_KICK_OUT_CLAUSE_NOT_FOUND` or `ERR_AUDIT_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_lease_with_unknown_id_returns_not_found
    """
    create_center()

    validate_error(api.get_lease(UNKNOWN_IDS["lease"], LEASE_ADMIN),
                   ApiErrorId.ERR_LEASE_NOT_FOUND.value, 404)


def test_each_unknown_resource_answers_with_its_own_not_found_code(api):
    """PRD §2.9: "**Existence.** Every resource named in the URL path must
    exist, validated left to right; only then is every id referenced in the
    request body resolved. The rejection is the not-found code matching
    whichever resource was missing: `ERR_CENTER_NOT_FOUND`,
    `ERR_TENANT_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_LEASE_YEAR_NOT_FOUND`,
    `ERR_SALES_REPORT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
    `ERR_CO_TENANCY_CLAUSE_NOT_FOUND`, `ERR_CO_TENANCY_EVENT_NOT_FOUND`,
    `ERR_KICK_OUT_CLAUSE_NOT_FOUND` or `ERR_AUDIT_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/not_found_errors_for_every_unknown_resource_id
    """
    validate_error(api.get_center(UNKNOWN_IDS["center"], CENTER_ADMIN),
                   ApiErrorId.ERR_CENTER_NOT_FOUND.value, 404)
    validate_error(api.get_tenant(UNKNOWN_IDS["tenant"], CENTER_ADMIN),
                   ApiErrorId.ERR_TENANT_NOT_FOUND.value, 404)
    validate_error(api.get_lease_year(UNKNOWN_IDS["lease_year"], LEASE_ADMIN),
                   ApiErrorId.ERR_LEASE_YEAR_NOT_FOUND.value, 404)
    validate_error(api.get_sales_report(UNKNOWN_IDS["sales_report"], LEASE_ADMIN),
                   ApiErrorId.ERR_SALES_REPORT_NOT_FOUND.value, 404)
    validate_error(api.get_charge(UNKNOWN_IDS["charge"], LEASE_ADMIN),
                   ApiErrorId.ERR_CHARGE_NOT_FOUND.value, 404)
    validate_error(
        api.get_co_tenancy_clause(UNKNOWN_IDS["co_tenancy_clause"], CENTER_ADMIN),
        ApiErrorId.ERR_CO_TENANCY_CLAUSE_NOT_FOUND.value, 404)
    validate_error(
        api.get_co_tenancy_event(UNKNOWN_IDS["co_tenancy_event"], CENTER_ADMIN),
        ApiErrorId.ERR_CO_TENANCY_EVENT_NOT_FOUND.value, 404)
    validate_error(
        api.get_kick_out_clause(UNKNOWN_IDS["kick_out_clause"], CENTER_ADMIN),
        ApiErrorId.ERR_KICK_OUT_CLAUSE_NOT_FOUND.value, 404)
    validate_error(api.get_audit(UNKNOWN_IDS["audit"], AUDITOR),
                   ApiErrorId.ERR_AUDIT_NOT_FOUND.value, 404)


def test_create_lease_without_percentage_rate_is_rejected(api):
    """PRD §2.9: "**Request shape.** The body is well formed: every required
    field is present, every enum-typed field names a declared member, every
    integer sits inside its declared range, `period_end` is strictly after
    `period_start`, and `audit_window_end` is greater than or equal to
    `audit_window_start` — otherwise `ERR_INVALID_REQUEST` (400). This runs on
    every endpoint."

    Design: Corner/entities/create_lease_missing_required_field_returns_invalid_request
    """
    center = create_center()
    tenant = create_tenant(center["id"], legal_name="Missing Field LLC",
                           trade_name="MissShop")
    payload = create_lease_payload(center["id"], tenant["id"], suite_code="3201")
    payload.pop("percentage_rate_bps")

    validate_error(api.create_lease(payload, CENTER_ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_leases(LEASE_ADMIN, params={"center_id": center["id"]}))
    assert meta["total_count"] == 0, "the rejected lease must not have been stored"
    assert rows == []


def test_create_tenant_with_undeclared_category_is_rejected(api):
    """PRD §3.1: "The permitted categories are `ANCHOR`, `JUNIOR_ANCHOR`,
    `INLINE`, `FOOD` and `KIOSK`."
    PRD §2.9: "**Request shape.** The body is well formed: every required field
    is present, every enum-typed field names a declared member, every integer
    sits inside its declared range, `period_end` is strictly after
    `period_start`, and `audit_window_end` is greater than or equal to
    `audit_window_start` — otherwise `ERR_INVALID_REQUEST` (400). This runs on
    every endpoint."

    Design: Corner/entities/create_tenant_with_invalid_category_enum_returns_invalid_request
    """
    center = create_center()

    validate_error(
        api.create_tenant(
            create_tenant_payload(center["id"], legal_name="Bad Enum LLC",
                                  trade_name="BadEnum", category="POPUP",
                                  gla_sqft=1_000),
            CENTER_ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _rows, meta = validate_paginated(
        api.list_tenants(CENTER_ADMIN, params={"center_id": center["id"]}))
    assert meta["total_count"] == 0, "the rejected tenant must not have been stored"


def test_lease_naming_a_tenant_of_another_center_is_refused(api):
    """PRD §3.2: "The named tenant must belong to the named center; a
    `tenant_id` whose tenant sits in a different center is refused with
    `ERR_CENTER_MISMATCH`."

    Design: Corner/entities/create_lease_with_tenant_from_another_center_returns_center_mismatch
    """
    center_a = create_center()
    center_b = create_center(name="Southgate Plaza", code="SGP",
                             total_gla_sqft=250_000, anchor_gla_sqft=100_000)
    tenant_b = create_tenant(center_b["id"], legal_name="Wrong Center LLC",
                             trade_name="WrongShop")

    validate_error(
        api.create_lease(
            create_lease_payload(center_a["id"], tenant_b["id"],
                                 suite_code="3301"),
            CENTER_ADMIN),
        ApiErrorId.ERR_CENTER_MISMATCH.value, 409)

    _rows, meta = validate_paginated(
        api.list_leases(LEASE_ADMIN, params={"center_id": center_a["id"]}))
    assert meta["total_count"] == 0


def test_artificial_breakpoint_configuration_is_validated_both_ways(api):
    """PRD §3.2: "A lease declaring `ARTIFICIAL` without a positive
    `artificial_breakpoint_cents`, or declaring `NATURAL` while supplying an
    `artificial_breakpoint_cents` at all, is refused with
    `ERR_BREAKPOINT_CONFIG_INVALID`."

    Design: Corner/validations/artificial_breakpoint_without_amount_returns_422
    """
    center = create_center()
    tenant = create_tenant(center["id"], legal_name="Bad BP LLC",
                           trade_name="BadBPShop")

    validate_error(
        api.create_lease(
            create_lease_payload(center["id"], tenant["id"], suite_code="6301",
                                 breakpoint_type="ARTIFICIAL"),
            CENTER_ADMIN),
        ApiErrorId.ERR_BREAKPOINT_CONFIG_INVALID.value, 422)

    validate_error(
        api.create_lease(
            create_lease_payload(center["id"], tenant["id"], suite_code="6302",
                                 breakpoint_type="NATURAL",
                                 artificial_breakpoint_cents=40_000_000),
            CENTER_ADMIN),
        ApiErrorId.ERR_BREAKPOINT_CONFIG_INVALID.value, 422)

    _rows, meta = validate_paginated(
        api.list_leases(LEASE_ADMIN, params={"center_id": center["id"]}))
    assert meta["total_count"] == 0, "neither ill-configured lease may exist"


def test_lease_listing_pages_and_filters_by_status(api):
    """PRD §2.3: "Every list endpoint accepts two query-string parameters.
    `limit` controls page size; it defaults to 10, may not be smaller than 1,
    and may not be larger than 100."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the filters before the page window is applied and `has_more`
    indicates whether any rows remain beyond the current window."
    PRD §3.1: "`occupied_gla_sqft` becomes the sum of `leased_sqft` over every
    lease of that center whose status is `ACTIVE`, `RELIEF_ACTIVE` or
    `TERMINATION_PENDING`; leases still in `DRAFT` and leases already
    `TERMINATED` contribute nothing."

    Design: Corner/entities/list_leases_honours_limit_offset_and_status_filter
    """
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    leases = []
    for index, name in enumerate(["Page One", "Page Two", "Page Three"], start=1):
        tenant = create_tenant(center["id"], legal_name=f"{name} LLC",
                               trade_name=name.replace(" ", ""))
        leases.append(create_lease(center["id"], tenant["id"],
                                   suite_code=f"340{index}"))
    activate_lease(leases[0]["id"])
    activate_lease(leases[1]["id"])

    rows, meta = validate_paginated(
        api.list_leases(LEASE_ADMIN,
                        params={"center_id": center["id"], "limit": 2,
                                "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    active_rows, active_meta = validate_paginated(
        api.list_leases(LEASE_ADMIN,
                        params={"center_id": center["id"], "status": "ACTIVE"}))
    assert len(active_rows) == 2
    assert active_meta["total_count"] == 2
    assert active_meta["has_more"] is False

    center_now = read_center(center["id"])
    assert center_now["occupied_gla_sqft"] == 8_000, (
        "only the two ACTIVE leases count toward occupied area")


def test_activating_a_draft_lease_sets_rent_and_raises_center_occupancy(api):
    """PRD §3.2: "Activating a lease moves it `DRAFT → ACTIVE`, and it is
    available to a `CenterAdmin` or a `LeaseAdministrator`."
    PRD §3.2: "On activation the service sets `effective_monthly_rent_cents` to
    `annual_base_rent_cents` divided by twelve rounded half up, sets
    `relief_monthly_credit_cents` to 0, runs the center occupancy monitor of
    Section 3.1 — which raises `occupied_gla_sqft` and `occupancy_bps` — and
    advances the lease's `version` by 1."
    PRD §3.1: "`occupancy_bps` becomes the occupied area multiplied by 10000
    and divided by `total_gla_sqft`, floored to a whole basis point, and is
    defined as 0 when `total_gla_sqft` is zero."

    Design: Corner/state_machines/activate_lease_from_draft_moves_to_active_and_raises_occupancy
    """
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    tenant = create_tenant(center["id"], legal_name="Activate LLC",
                           trade_name="ActShop")
    lease = create_lease(center["id"], tenant["id"], suite_code="3601")

    data = validate_success(api.activate_lease(lease["id"], LEASE_ADMIN))

    assert_lease(data)
    assert data["status"] == "ACTIVE"
    assert data["effective_monthly_rent_cents"] == 1_000_000
    assert data["relief_monthly_credit_cents"] == 0
    assert data["version"] == 2, "activation advances the lease version by 1"

    center_now = read_center(center["id"])
    assert center_now["occupied_gla_sqft"] == 4_000
    assert center_now["occupancy_bps"] == 100


def test_second_activation_of_an_active_lease_is_refused(api):
    """PRD §3.2: "Activation requires the lease to be in `DRAFT` and the lease's
    tenant to be in `PROSPECT` or `OPERATING`; a tenant already `DARK` or
    `VACATED` blocks it with `ERR_TENANT_STATE_INVALID`, and a lease not in
    `DRAFT` is refused with `ERR_LEASE_STATE_INVALID`."

    Design: Corner/state_machines/activate_lease_twice_second_call_rejected
    """
    scene = setup_active_lease(suite_code="3701")

    validate_error(api.activate_lease(scene["lease"]["id"], CENTER_ADMIN),
                   ApiErrorId.ERR_LEASE_STATE_INVALID.value, 409)

    lease_now = read_lease(scene["lease"]["id"])
    assert lease_now["status"] == "ACTIVE"
    assert lease_now["version"] == 2, "the refused call changed nothing"

    center_now = read_center(scene["center"]["id"])
    assert center_now["occupied_gla_sqft"] == 4_000, (
        "leased area must not be counted twice")


def test_terminating_an_active_lease_is_refused(api):
    """PRD §3.2: "A lease reaches `TERMINATED` only through
    `TERMINATION_PENDING`, and only a `CenterAdmin` may complete it. The lease
    must be in `TERMINATION_PENDING`, and no reporting year of that lease may
    still be `OPEN` or `RECONCILING` — an unfinished year blocks the
    termination with `ERR_LEASE_YEAR_STATE_INVALID`."
    PRD §2.9: "The rejection is the state code matching the entity that
    blocked: `ERR_TENANT_STATE_INVALID`, `ERR_LEASE_STATE_INVALID`,
    `ERR_LEASE_YEAR_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`,
    `ERR_CHARGE_STATE_INVALID`, `ERR_CO_TENANCY_EVENT_STATE_INVALID`,
    `ERR_KICK_OUT_STATE_INVALID` or `ERR_AUDIT_STATE_INVALID`, each HTTP 409."

    Design: Corner/state_machines/terminate_lease_from_active_rejected
    """
    scene = setup_active_lease(suite_code="3801")

    validate_error(api.terminate_lease(scene["lease"]["id"], CENTER_ADMIN),
                   ApiErrorId.ERR_LEASE_STATE_INVALID.value, 409)

    assert read_lease(scene["lease"]["id"])["status"] == "ACTIVE"


def test_reopening_a_vacated_tenant_is_refused(api):
    """PRD §3.1: "A tenant that surrenders its space reaches the terminal
    `VACATED` status either as `OPERATING → VACATED` or as `DARK → VACATED`. No
    other pairing is legal; a request naming a `to_status` that is not
    reachable from the tenant's current status is refused with
    `ERR_TENANT_STATE_INVALID`."

    Design: Corner/state_machines/tenant_status_change_from_vacated_rejected
    """
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    tenant = create_tenant(center["id"], legal_name="Gone LLC",
                           trade_name="GoneShop")
    set_tenant_status(tenant["id"], "OPERATING")
    set_tenant_status(tenant["id"], "VACATED")

    validate_error(
        api.set_tenant_status(tenant["id"], {"to_status": "OPERATING"},
                              CENTER_ADMIN),
        ApiErrorId.ERR_TENANT_STATE_INVALID.value, 409)

    tenant_now = read_tenant(tenant["id"])
    assert_tenant(tenant_now)
    assert tenant_now["status"] == "VACATED"


def test_logical_clock_reads_its_documented_default_before_any_set_call(api):
    """PRD §2.6: "Before any caller sets it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; it must never fall back to real wall-clock time."

    Design: Corner/endpoints/clock_defaults_to_2026_08_01_before_any_set_call
    """
    create_center()

    data = validate_success(api.get_clock(LEASE_ADMIN))
    assert_instant_equals(data["current_utc"], "2026-08-01T00:00:00Z",
                          "the logical clock's default")


def test_amendment_carrying_a_stale_lease_version_is_rejected(api):
    """PRD §2.8: "`POST /retail/leases/{id}/amendments` requires a non-optional
    `expected_lease_version` field in its request body, carrying the client's
    last observed `version` of the target `Lease`."
    PRD §2.8: "If `expected_lease_version` does not equal the lease's current
    `version`, the request is rejected with `ERR_STALE_LEASE_VERSION` (HTTP
    412). A successful amendment advances the lease's `version` by 1."
    PRD §3.2: "After the restatement the service recomputes
    `natural_breakpoint_cents` and `effective_breakpoint_cents` from the new
    terms, applying the same `ERR_BREAKPOINT_CONFIG_INVALID` consistency rule
    as at creation, and advances the lease's `version` by 1."

    Design: Corner/cross_cutting_layers/stale_lease_version_on_amendment_returns_412
    """
    set_clock(TEST_DEFAULTS["CLOCK_AT_YEAR_START"])
    center = create_center()
    tenant = create_tenant(center["id"], legal_name="Amend LLC",
                           trade_name="AmendShop")
    created = create_lease(center["id"], tenant["id"], suite_code="9201")
    version_at_creation = created["version"]
    activate_lease(created["id"])
    version_now = lease_version(created["id"])
    assert version_now != version_at_creation

    validate_error(
        api.amend_lease(created["id"],
                        {"expected_lease_version": version_at_creation,
                         "percentage_rate_bps": 500},
                        CENTER_ADMIN),
        ApiErrorId.ERR_STALE_LEASE_VERSION.value, 412)
    assert read_lease(created["id"])["percentage_rate_bps"] == 600

    amended = validate_success(
        api.amend_lease(created["id"],
                        {"expected_lease_version": version_now,
                         "percentage_rate_bps": 500},
                        CENTER_ADMIN))
    assert amended["percentage_rate_bps"] == 500
    assert amended["natural_breakpoint_cents"] == 240_000_000
    assert amended["effective_breakpoint_cents"] == 240_000_000
    assert amended["version"] == 3
