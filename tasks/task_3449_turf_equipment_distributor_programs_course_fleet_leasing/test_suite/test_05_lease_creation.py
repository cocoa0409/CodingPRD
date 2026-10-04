"""Fleet lease origination: initial state, computed end_date, unit expansion
order, the past-window and territory gates, and the closed-interval cycle
overlap rule (PRD §3.4, §2.3, §2.5).
"""
from test_helpers import (
    ApiErrorId,
    create_catalog_model,
    create_course_for,
    create_distributor_active,
    create_distributor_payload,
    create_lease_for,
    create_lease_payload,
    create_technician_payload,
    list_lease_units,
    make_distributor_manager_headers,
    setup_lease_in_state,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

WK_MDX = {
    "model_code": "WK-MDX",
    "category": "UTILITY_VEHICLE",
    "tier": "PRO",
    "list_price_cents": 2800000,
    "eligible_turf_types": ["BENTGRASS", "BERMUDA", "POA_ANNUA", "MIXED"],
    "warranty_labor_hourly_cap_cents": 8500,
    "parts_support_years": 8,
}

SIERRA = {
    "name": "Sierra Turf Supply",
    "territory_codes": ["AZ"],
    "labor_rate_cents": 13500,
    "annual_claim_cap_cents": 30000000,
}


def test_lease_created_in_draft_initial_state(api, corporate_admin_headers):
    """PRD §3.4: "The system computes `end_date` as `start_date` advanced by
    `cycle_months` months. The lease opens in `DRAFT` with `version` 1, and
    each line expands into LeaseUnit rows in line order: every unit is created
    in `ORDERED` with its `lease_id` and `model_id` recorded and a 1-based
    `unit_seq` assigned in expansion order, which remains the canonical sort
    key for unit listings."
    PRD §2.4: "A newly created FleetLease starts with `version` set to 1."

    Design: Corner/state_machines/lease_created_in_draft_initial_state
    """
    ctx = setup_program()
    lease = validate_success(
        api.create_lease(
            create_lease_payload(
                ctx["course"]["id"],
                [{"model_id": ctx["model"]["id"], "qty": 2}],
                cycle_months=24,
                start_date="2027-01-04",
            ),
            make_distributor_manager_headers(ctx["distributor"]["id"]),
        ),
        201,
    )
    assert lease["status"] == "DRAFT" and lease["version"] == 1
    assert lease["end_date"] == "2029-01-04", (
        f"end_date = 2027-01-04 + 24 months = 2029-01-04, got {lease['end_date']!r}"
    )
    units = list_lease_units(lease)
    assert [u["unit_seq"] for u in units] == [1, 2]
    assert all(u["status"] == "ORDERED" for u in units)


def test_lease_create_client_computed_fields_input_ignored(api):
    """PRD §3.4: "The lease opens in `DRAFT` with `version` 1"
    PRD §3.4: "Approval is also when the lease's economics are fixed."

    Design: Corner/entities/lease_create_client_computed_fields_input_ignored
    """
    ctx = setup_program()
    payload = create_lease_payload(
        ctx["course"]["id"],
        [{"model_id": ctx["model"]["id"], "qty": 1}],
        cycle_months=36,
        start_date="2027-03-01",
    )
    # Client-injected system fields must not steer the lifecycle or financials.
    payload["status"] = "ACTIVE"
    payload["monthly_rate_cents"] = 1
    lease = validate_success(
        api.create_lease(payload, make_distributor_manager_headers(ctx["distributor"]["id"])),
        201,
    )
    assert lease["status"] == "DRAFT", (
        f"injected status=ACTIVE ignored; the lease opens in DRAFT, got {lease['status']!r}"
    )
    assert lease["version"] == 1
    assert lease["end_date"] == "2030-03-01"
    assert lease.get("monthly_rate_cents") is None, (
        "lease economics are fixed at approval, not at creation"
    )


def test_clock_default_is_fixed_start(api):
    """PRD §2.5: "At startup the logical clock reads exactly
    2026-09-01T00:00:00Z, and it never falls back to wall-clock time."
    PRD §3.4: "The `start_date` must not lie before the current logical date,
    else `ERR_WINDOW_IN_PAST` (HTTP 422)."

    Design: Corner/endpoints/clock_default_is_fixed_start
    """
    ctx = setup_program()
    lease = validate_success(
        api.create_lease(
            create_lease_payload(
                ctx["course"]["id"],
                [{"model_id": ctx["model"]["id"], "qty": 1}],
                cycle_months=36,
                start_date="2026-09-01",
            ),
            make_distributor_manager_headers(ctx["distributor"]["id"]),
        ),
        201,
    )
    assert lease["status"] == "DRAFT", (
        "start_date equal to the fixed startup clock date is not in the past"
    )


def test_lease_create_window_in_past_rejected(api):
    """PRD §3.4: "The `start_date` must not lie before the current logical
    date, else `ERR_WINDOW_IN_PAST` (HTTP 422)."

    Design: Corner/validations/lease_create_window_in_past_rejected
    """
    ctx = setup_program()
    resp = api.create_lease(
        create_lease_payload(
            ctx["course"]["id"],
            [{"model_id": ctx["model"]["id"], "qty": 1}],
            cycle_months=36,
            start_date="2026-08-01",
        ),
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST.value)


def test_foreign_course_lease_create_rejected_territory(api, corporate_admin_headers):
    """PRD §2.8: "When a request could fail several checks at once, the checks
    are evaluated in the following priority order, and the earliest failing
    tier determines the response"
    PRD §2.8: "9. Territory integrity — a lease's course must be assigned to
    the acting distributor, and a claim's technician and unit must both belong
    to the acting distributor (`ERR_TERRITORY_MISMATCH`, 409)."
    PRD §2.8: "10. Temporal windows — lease start dates not in the past, lease
    cycle non-overlap, irrigation window validity and non-overlap, and warranty
    coverage windows (`ERR_WINDOW_IN_PAST`, `ERR_LEASE_CYCLE_OVERLAP`,
    `ERR_WINDOW_OVERLAP`, `ERR_WARRANTY_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_lease_create
    """
    d1, _t1 = create_distributor_active()
    d2, _t2 = create_distributor_active(**SIERRA)
    course = create_course_for(d1)
    model = create_catalog_model()
    resp = api.create_lease(
        create_lease_payload(
            course["id"],
            [{"model_id": model["id"], "qty": 1}],
            cycle_months=36,
            start_date="2026-08-01",  # also before the default logical date
        ),
        make_distributor_manager_headers(d2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_MISMATCH.value)


def test_territory_rejection_creates_no_lease(api, corporate_admin_headers):
    """PRD §3.4: "Territory integrity gates creation: the course's
    `assigned_distributor_id` must equal the acting distributor, else
    `ERR_TERRITORY_MISMATCH` (HTTP 409)."
    PRD §4: "| GET | `/turf/leases` | List leases; optional filters
    `course_id`, `distributor_id`, and `status` | CorporateAdmin,
    DistributorManager, CourseManager |"

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_lease_create
    """
    d1, _t1 = create_distributor_active()
    d2, _t2 = create_distributor_active(**SIERRA)
    course = create_course_for(d1)
    model = create_catalog_model()
    resp = api.create_lease(
        create_lease_payload(
            course["id"],
            [{"model_id": model["id"], "qty": 1}],
            cycle_months=36,
            start_date="2026-08-01",
        ),
        make_distributor_manager_headers(d2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_MISMATCH.value)
    data, meta = validate_paginated(
        api.list_leases(corporate_admin_headers, params={"distributor_id": d2["id"]})
    )
    assert meta["total_count"] == 0 and data == [], (
        f"the rejected creation must persist no lease for the foreign "
        f"distributor, got total_count {meta['total_count']}"
    )


def test_shared_boundary_date_overlaps(api):
    """PRD §3.4: "And the new lease's closed interval from `start_date` through
    `end_date` must not intersect the closed interval of any sibling lease of
    the same course in `APPROVED`, `ACTIVE`, or `TURNOVER_IN_PROGRESS` —
    shared boundary dates count as overlap — else `ERR_LEASE_CYCLE_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lease_cycle_closed_interval_overlap
    """
    ctx = setup_lease_in_state(
        "APPROVED",
        lease_overrides={"cycle_months": 36, "start_date": "2026-09-01"},
    )
    # The approved sibling occupies the closed interval [2026-09-01, 2029-09-01].
    resp = api.create_lease(
        create_lease_payload(
            ctx["course"]["id"],
            [{"model_id": ctx["model"]["id"], "qty": 1}],
            cycle_months=36,
            start_date="2029-09-01",
        ),
        make_distributor_manager_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEASE_CYCLE_OVERLAP.value)


def test_day_after_end_date_accepted(api):
    """PRD §3.4: "shared boundary dates count as overlap — else
    `ERR_LEASE_CYCLE_OVERLAP` (HTTP 409)"
    PRD §3.4: "The lease opens in `DRAFT` with `version` 1"

    Design: Difficulty/resource_temporal_overlap/lease_cycle_closed_interval_overlap
    """
    ctx = setup_lease_in_state(
        "APPROVED",
        lease_overrides={"cycle_months": 36, "start_date": "2026-09-01"},
    )
    lease = validate_success(
        api.create_lease(
            create_lease_payload(
                ctx["course"]["id"],
                [{"model_id": ctx["model"]["id"], "qty": 1}],
                cycle_months=36,
                start_date="2029-09-02",  # first date clear of the closed sibling interval
            ),
            make_distributor_manager_headers(ctx["distributor"]["id"]),
        ),
        201,
    )
    assert lease["status"] == "DRAFT"


def test_units_list_sorted_by_unit_seq(api, corporate_admin_headers):
    """PRD §2.3: "The lease-unit listing is the documented exception: units are
    sorted by `unit_seq` ascending, so a lease's equipment always reads in
    line-expansion order."
    PRD §3.4: "each line expands into LeaseUnit rows in line order: every unit
    is created in `ORDERED` with its `lease_id` and `model_id` recorded and a
    1-based `unit_seq` assigned in expansion order, which remains the canonical
    sort key for unit listings."

    Design: Corner/endpoints/units_list_sorted_by_unit_seq
    """
    ctx = setup_program()
    m2 = create_catalog_model(**WK_MDX)
    lease = create_lease_for(
        ctx["distributor"],
        ctx["course"],
        [{"model_id": m2["id"], "qty": 1}, {"model_id": ctx["model"]["id"], "qty": 2}],
    )
    data, _meta = validate_paginated(
        api.list_units(corporate_admin_headers, params={"lease_id": lease["id"]})
    )
    assert [u["unit_seq"] for u in data] == [1, 2, 3], (
        f"units must read in line-expansion order, got "
        f"{[u['unit_seq'] for u in data]}"
    )
    assert data[0]["model_id"] == m2["id"], "the first line expands first"
    assert data[2]["model_id"] == ctx["model"]["id"]


def test_technicians_list_filters_by_distributor_and_paginates(api, corporate_admin_headers):
    """PRD §4: "| GET | `/turf/technicians` | List technicians; optional
    filters `distributor_id` and `cert_status` | CorporateAdmin,
    DistributorManager |"
    PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/technicians_list_filters_by_distributor_and_paginates
    """
    d1 = validate_success(
        api.create_distributor(create_distributor_payload(), corporate_admin_headers), 201
    )
    d2 = validate_success(
        api.create_distributor(create_distributor_payload(**SIERRA), corporate_admin_headers),
        201,
    )
    mgr1 = make_distributor_manager_headers(d1["id"])
    mgr2 = make_distributor_manager_headers(d2["id"])
    for name in ("Tech A", "Tech B"):
        validate_success(
            api.create_technician(create_technician_payload(full_name=name), mgr1), 201
        )
    validate_success(
        api.create_technician(create_technician_payload(full_name="Tech C"), mgr2), 201
    )

    data, meta = validate_paginated(
        api.list_technicians(corporate_admin_headers, params={"distributor_id": d1["id"]})
    )
    assert meta["total_count"] == 2 and len(data) == 2
    assert all(t["distributor_id"] == d1["id"] for t in data)

    page, meta = validate_paginated(
        api.list_technicians(
            corporate_admin_headers,
            params={"distributor_id": d1["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(page) == 1
    assert meta["has_more"] is True and meta["total_count"] == 2
