"""RBAC and ownership denials, creation baselines, envelope/system-field
behavior, pagination, and the default clock (PRD §2.1/§2.3/§2.4/§2.5/§2.11/§4)."""

from test_helpers import (
    ApiErrorId,
    ADMIN,
    ANON,
    ASSESSOR,
    NON_EXISTENT_UUID,
    STAFF,
    api_client,
    assert_funding_cycle,
    complete_assessment,
    create_application,
    create_application_payload,
    create_assessment,
    create_contractor_payload,
    create_cycle,
    create_event_payload,
    create_funding_cycle_payload,
    create_sponsor,
    create_sponsor_payload,
    create_commitment_payload,
    get_application,
    get_project_for_application,
    get_sponsor,
    get_work_order,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_homeowner_headers,
    make_sponsor_rep_headers,
    make_trade_partner_headers,
    open_selection,
    patch_application_status,
    run_selection,
    schedule_work_order_payload,
    scope_assessment,
    setup_project_with_work_order,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated,
)


def test_funding_cycle_create_applies_defaults_and_system_fields():
    """PRD §3.1: "A program year begins when a `PlatformAdmin` creates a
    funding cycle with a human-readable `name`, a four-digit `fiscal_year`, and
    the base appropriation `total_budget_cents`, which may not be negative."
    PRD §3.1: "The cycle's scoring variant, `priority_mode`, is either
    `STANDARD` or `HAZARD_PRIORITY` and defaults to `STANDARD` when omitted."
    PRD §3.1: "A new cycle is born `OPEN` with its pool equal to the base
    budget and both `reserved_cents` and `spent_cents` at zero, so
    `available_cents` initially equals the entire `pool_cents`."

    A cycle created without priority_mode returns 201 with the documented
    defaults and a zeroed ledger.

    Design: Corner/entities/funding_cycle_create_applies_defaults_and_system_fields
    """
    resp = api_client.create_funding_cycle(
        create_funding_cycle_payload(
            name="FY27 Bare", fiscal_year=2027, total_budget_cents=750_000
        ),
        ADMIN,
    )
    data = validate_created(resp)
    assert_funding_cycle(data)
    assert data["status"] == "OPEN"
    assert data["priority_mode"] == "STANDARD", "default applied"
    assert data["pool_cents"] == 750_000
    assert data["reserved_cents"] == 0
    assert data["spent_cents"] == 0
    assert data["available_cents"] == 750_000


def test_application_create_missing_required_income_returns_invalid_request():
    """PRD §3.2: "A household enters the pipeline when an application is
    submitted — self-service by an `Anonymous` caller, or assisted by
    `AffiliateStaff` — carrying the `funding_cycle_id` of the cycle applied to
    (a dangling reference is `ERR_FUNDING_CYCLE_NOT_FOUND`), the
    `homeowner_name`, the primary applicant's `date_of_birth`, the
    `household_size` (an occupant count between 1 and 8 inclusive), the annual
    `household_income_cents` (zero or more), two flags `is_veteran` and
    `has_disability`, two documentation flags `ownership_doc_provided` and
    `occupancy_doc_provided`, and the home's `address`."
    PRD §5: "The catalogue below enumerates every machine-readable error
    identifier the API can return and its HTTP status."

    household_income_cents is a required input; omitting it is rejected as
    ERR_INVALID_REQUEST (the catalogue's only 400 identifier applicable to a
    malformed create) and no record persists.

    Design: Corner/entities/application_create_missing_required_income_returns_invalid_request
    """
    cycle = create_cycle()
    payload = create_application_payload(cycle["id"], homeowner_name="No Income")
    del payload["household_income_cents"]
    resp = api_client.create_application(payload, ANON)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(
        api_client.list_applications(STAFF, params={"funding_cycle_id": cycle["id"]})
    )
    assert rows == [], "no HomeownerApplication record is created"


def test_contractor_create_with_invalid_enum_returns_invalid_request():
    """PRD §3.7: "A `PlatformAdmin` registers each firm with its `legal_name`,
    its `trade` (one of `CARPENTRY`, `ELECTRICAL`, `PLUMBING`, `ROOFING`,
    `HVAC`), the `license_number`, the `license_expires_on` and
    `insurance_expires_on` dates, and an optional `max_concurrent_jobs`
    defaulting to 1 — the maximum number of the firm's distinct work orders
    whose visit windows may share one calendar day."
    PRD §5: "The catalogue below enumerates every machine-readable error
    identifier the API can return and its HTTP status."

    trade "GLAZIER" is outside the declared enum and the create is rejected as
    ERR_INVALID_REQUEST before any record is written.

    Design: Corner/entities/contractor_create_with_invalid_enum_returns_invalid_request
    """
    resp = api_client.create_trade_contractor(
        create_contractor_payload(
            legal_name="Glass Co", trade="GLAZIER", license_number="G-1"
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_volunteer_get_unknown_id_returns_volunteer_not_found():
    """PRD §2.11: "The concrete not-found codes, all HTTP 404, are
    `ERR_FUNDING_CYCLE_NOT_FOUND`, `ERR_SELECTION_RUN_NOT_FOUND`,
    `ERR_SPONSOR_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_CONTRACTOR_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_MATERIAL_ORDER_NOT_FOUND`, and `ERR_WARRANTY_CLAIM_NOT_FOUND`."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    A well-formed UUID that matches no volunteer returns the typed 404 with a
    message, not a generic 500 or null body.

    Design: Corner/entities/volunteer_get_unknown_id_returns_volunteer_not_found
    """
    resp = api_client.get_volunteer(NON_EXISTENT_UUID, STAFF)
    error_data = validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND)
    assert error_data.get("message"), "error payload carries a human message"


def test_applications_list_paginates_and_reports_total_count():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, must be at least 1, and may not exceed 100.
    The `offset` parameter sets the number of items skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    With three applications on the cycle: limit=2 pages 2 then 1 rows, with
    total_count 3 throughout and has_more flipping false on the tail page; the
    funding_cycle_id filter scopes the set.

    Design: Corner/entities/applications_list_paginates_and_reports_total_count
    """
    cycle = create_cycle()
    for i in range(1, 4):
        create_application(
            cycle["id"],
            homeowner_name=f"P {i}",
            household_size=i,
            household_income_cents=i * 1_000_000,
        )
    page1, meta1 = validate_paginated(
        api_client.list_applications(
            STAFF, params={"funding_cycle_id": cycle["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api_client.list_applications(
            STAFF, params={"funding_cycle_id": cycle["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    for row in page1 + page2:
        assert row["funding_cycle_id"] == cycle["id"]


def test_sponsor_create_extra_field_ignored_input():
    """PRD §2.5: "The `id` is a server-minted UUID carrying no type prefix."
    PRD §3.1: "A `PlatformAdmin` first registers the sponsor itself with a
    legal `name`, a `contact_email`, and an optional `sponsor_tier` of
    `COMMUNITY`, `REGIONAL`, or `NATIONAL` (defaulting to `COMMUNITY`)."

    Client-supplied system fields in the create body do not persist: the
    returned id is a server-minted UUID (not the client's string), the
    created_at is server-stamped, and the tier defaults to COMMUNITY.

    Design: Corner/entities/sponsor_create_extra_field_ignored_input
    """
    payload = create_sponsor_payload(
        name="Junk Fields Inc", contact_email="j@x.example"
    )
    payload.update(
        {"id": "client-minted", "version": 99, "created_at": "1970-01-01T00:00:00Z"}
    )
    data = validate_created(api_client.create_sponsor(payload, ADMIN))
    assert is_valid_uuid(data["id"]), (
        "the server mints its own UUID rather than echoing the client's id"
    )
    assert data["name"] == "Junk Fields Inc"
    assert data["sponsor_tier"] == "COMMUNITY"
    fetched = get_sponsor(data["id"])
    assert is_iso8601_timestamp(fetched["created_at"])
    assert fetched["created_at"] != "1970-01-01T00:00:00Z"


def test_homeowner_cannot_verify_own_application():
    """PRD §2.1: "A `Homeowner` actor may drive its own application to
    `WITHDRAWN` and nothing else: any other `status` value from a `Homeowner`
    is a role-field violation rejected with `ERR_FORBIDDEN`."

    Even on its own record, a Homeowner's UNDER_VERIFICATION attempt is a
    role-field violation.

    Design: Corner/rbac/homeowner_cannot_verify_own_application
    """
    cycle = create_cycle()
    app = create_application(cycle["id"], homeowner_name="Self Verify")
    resp = api_client.patch_application(
        app["id"],
        {"status": "UNDER_VERIFICATION"},
        make_homeowner_headers(app["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_application(app["id"])["status"] == "SUBMITTED"


def test_homeowner_can_withdraw_own_application_but_not_others():
    """PRD §3.2: "From `UNDER_VERIFICATION`, `VERIFIED`, `CANDIDATE`, or
    `DEFERRED`, either staff or the owning homeowner — a `Homeowner` actor
    whose `X-User-ID` equals the application's `id` — may withdraw it."
    PRD §2.1: "An entity-backed identity mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    The same WITHDRAWN call succeeds on the caller's own application and fails
    the ownership check on a neighbour's.

    Design: Corner/rbac/homeowner_can_withdraw_own_application_but_not_others
    """
    cycle = create_cycle()
    app_a = create_application(cycle["id"], homeowner_name="Own A")
    patch_application_status(app_a["id"], "UNDER_VERIFICATION")
    app_b = create_application(cycle["id"], homeowner_name="Own B")
    own = api_client.patch_application(
        app_a["id"], {"status": "WITHDRAWN"}, make_homeowner_headers(app_a["id"])
    )
    assert validate_ok(own)["status"] == "WITHDRAWN", (
        "own record, permitted transition"
    )
    resp = api_client.patch_application(
        app_b["id"], {"status": "WITHDRAWN"}, make_homeowner_headers(app_a["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_application(app_b["id"])["status"] == "SUBMITTED"


def test_trade_partner_cannot_schedule_work_order():
    """PRD §2.1: "A request whose role is valid in general but absent from the
    target endpoint's authorization list is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: "Set the visit window (half-open); credential, overlap, and
    day-capacity checks | AffiliateStaff".

    Scheduling is staff-only: the contractor that owns the work order still
    gets ERR_FORBIDDEN from the schedule endpoint.

    Design: Corner/rbac/trade_partner_cannot_schedule_work_order
    """
    ctx = setup_project_with_work_order(
        wo_target_status="APPROVED", quote_cents=50_000
    )
    resp = api_client.schedule_trade_work_order(
        ctx["work_order"]["id"],
        schedule_work_order_payload(),
        make_trade_partner_headers(ctx["contractor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_work_order(ctx["work_order"]["id"])["status"] == "APPROVED"


def test_sponsor_rep_cannot_commit_for_other_sponsor():
    """PRD §3.1: "A pledge against a specific cycle is then created — by a
    `SponsorRep` whose `X-User-ID` equals the pledge's `sponsor_id` (otherwise
    `ERR_NOT_RESOURCE_OWNER`), or by `AffiliateStaff` — carrying `sponsor_id`,
    `funding_cycle_id`, a strictly positive `amount_cents`, and an optional
    `team_build_event_date` naming the sponsor's team-building day, which may
    be null."

    SponsorRep identity is the Sponsor id: pledging for a different sponsor is
    ERR_NOT_RESOURCE_OWNER while the matching call succeeds.

    Design: Corner/rbac/sponsor_rep_cannot_commit_for_other_sponsor
    """
    cycle = create_cycle()
    sp1 = create_sponsor(name="Sponsor One")
    sp2 = create_sponsor(name="Sponsor Two")
    resp = api_client.create_commitment(
        create_commitment_payload(sp2["id"], cycle["id"], 100_000),
        make_sponsor_rep_headers(sp1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    own = api_client.create_commitment(
        create_commitment_payload(sp1["id"], cycle["id"], 100_000),
        make_sponsor_rep_headers(sp1["id"]),
    )
    assert validate_created(own)["status"] == "PLEDGED"


def test_assessor_cannot_verify_application_and_anonymous_cannot_read_cycle():
    """PRD §2.1: "A request whose role is valid in general but absent from the
    target endpoint's authorization list is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "`Anonymous` is likewise opaque and represents the
    unauthenticated public caller: it presents the two headers like any other
    caller but may only submit a homeowner application or register as a
    volunteer, and it is explicitly excluded from `Any`-authorized endpoints."

    Two denial shapes in one sweep: Assessor is outside PATCH /applications,
    and Anonymous is outside the Any pseudo-role's GET surface.

    Design: Corner/rbac/assessor_cannot_verify_application_and_anonymous_cannot_read_cycle
    """
    cycle = create_cycle()
    app = create_application(cycle["id"], homeowner_name="Denied App")
    resp1 = api_client.patch_application(
        app["id"], {"status": "UNDER_VERIFICATION"}, ASSESSOR
    )
    validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)
    resp2 = api_client.get_funding_cycle(cycle["id"], ANON)
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)
    assert get_application(app["id"])["status"] == "SUBMITTED"


def test_event_create_before_default_clock_returns_event_date_past():
    """PRD §2.4: "Before any call has set it, the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its
    own."
    PRD §3.6: "The host project must be `PLANNING`, `READY`, or
    `EVENT_SCHEDULED` (else `ERR_INVALID_STATE`), and `event_date` must fall on
    or after the logical clock date (else `ERR_EVENT_DATE_PAST`)."

    This test never sets the clock: the documented default governs, so an
    event dated 2026-08-31 is rejected.

    Design: Corner/validations/event_create_before_default_clock_returns_event_date_past
    """
    cycle = create_cycle()
    app = create_application(cycle["id"], homeowner_name="Past Site")
    patch_application_status(app["id"], "UNDER_VERIFICATION")
    patch_application_status(app["id"], "VERIFIED")
    asm = create_assessment(app["id"], scheduled_on="2026-09-02")
    complete_assessment(asm["id"])
    scope_assessment(asm["id"])
    patch_application_status(app["id"], "CANDIDATE")
    open_selection(cycle["id"])
    run_selection(cycle["id"])
    project = get_project_for_application(app["id"])
    resp = api_client.create_event(
        create_event_payload(
            project["id"], name="Too Early", event_date="2026-08-31",
            max_volunteers=2,
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_DATE_PAST)
