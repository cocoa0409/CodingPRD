"""Role authorization, resource ownership and the stale-version concurrency guard."""
from test_helpers import (
    ApiErrorId,
    activate_lease,
    book_job,
    create_branch,
    create_customer,
    get_assessment,
    get_job,
    get_lease,
    get_refurbishment_order,
    get_unit,
    make_branch_ops_headers,
    make_customer_headers,
    make_damage_assessor_headers,
    make_fleet_admin_headers,
    make_headers,
    make_leasing_agent_headers,
    quote_refurbishment,
    setup_rural_catalog,
    setup_rural_finalized_assessment,
    setup_rural_lease,
    setup_rural_submitted_assessment,
    setup_rural_vacated_lease,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    AUSTIN_YARD,
    create_branch_payload,
    create_damage_assessment_payload,
    create_lease_payload,
    create_refurbishment_order_payload,
)


def test_branch_ops_cannot_quote_a_lease(api):
    """PRD §2.1: "When a caller's role is not listed among the roles authorized
    for the operation being invoked, the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §2.1: "A `LeasingAgent` staffs the commercial desk: it registers
    lessees, quotes and reserves leases, attaches accessory packages, files
    permit applications, and activates, voids or extends leases."
    PRD §2.1: "A `BranchOps` account is a yard operations login belonging to
    exactly one branch; it books and runs logistics jobs and quotes and
    completes refurbishment work."

    Design: Corner/rbac/branch_ops_cannot_create_a_lease
    """
    ctx = setup_rural_catalog()

    response = api.create_lease(
        create_lease_payload(ctx["customer"]["id"], ctx["unit"]["id"],
                             ctx["jurisdiction"]["id"], ctx["config"]["id"],
                             site_address="9 County Road 12, Rural TX",
                             start_date="2026-10-01", term_months=12),
        make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    _, meta = validate_paginated(api.list_leases(
        make_leasing_agent_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 0, (
        f"the forbidden quote must not persist, got {meta['total_count']}")
    assert get_unit(ctx["unit"]["id"])["status"] == "IN_FLEET", (
        "the forbidden quote must not reserve the unit")


def test_branch_ops_cannot_dispatch_another_branchs_job(api):
    """PRD §2.1: "- When `X-User-Role` is `BranchOps`, `X-User-ID` is the `id`
    of the acting `Branch`; ownership checks on any resource that references a
    `Branch` compare the resource's foreign-key field to `X-User-ID` —
    specifically `origin_branch_id` on a logistics job and `branch_id` on a
    refurbishment order."
    PRD §2.1: "Ownership is enforced on exactly nine operations, and a violation
    on any of them is answered with `ERR_NOT_RESOURCE_OWNER` and HTTP 403:
    booking a logistics job, dispatching a logistics job, completing a logistics
    job, cancelling a logistics job, quoting a refurbishment order, completing a
    refurbishment order, disputing a damage assessment, reading a single lease,
    and reading a single damage assessment."

    Design: Corner/rbac/branch_ops_cannot_dispatch_another_branchs_job
    """
    ctx = setup_rural_lease()
    other_branch = create_branch(**AUSTIN_YARD)
    activate_lease(ctx["lease"]["id"])
    job = book_job(ctx["lease"]["id"], ctx["branch"]["id"],
                   job_type="DELIVERY_INSTALL", scheduled_date="2026-10-01",
                   mileage_miles=40, crew_hours=4.0)

    trespass = api.dispatch_logistics_job(
        job["id"], make_branch_ops_headers(other_branch["id"]))
    validate_error(trespass, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert get_job(job["id"])["status"] == "SCHEDULED", (
        "the trespassing dispatch must leave the job SCHEDULED")

    owned = validate_success(api.dispatch_logistics_job(
        job["id"], make_branch_ops_headers(ctx["branch"]["id"])))
    assert owned["status"] == "DISPATCHED", (
        f"the owning branch may dispatch, got {owned['status']}")
    assert get_unit(ctx["unit"]["id"])["status"] == "IN_TRANSIT"


def test_missing_or_unknown_role_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    the five role names the system recognises, the request is rejected with
    `ERR_UNAUTHENTICATED` and HTTP 401."
    PRD §2.1: "This check runs before anything else, including the existence of
    any resource named in the path."
    PRD §2.1: "The five roles are `FleetAdmin`, `BranchOps`, `LeasingAgent`,
    `DamageAssessor`, and `Customer`."

    PRD §2.2: "- The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "- The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    headerless = api.create_branch(
        create_branch_payload(name="Headerless Yard", region_code="TX-N",
                              yard_capacity_units=5, daily_dispatch_capacity=1,
                              labor_rate_cents_per_hour=9_000),
        {"Content-Type": "application/json"})
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value)
    body = headerless.json()
    assert body["response_type"] == "error", (
        f"Expected response_type 'error', got {body['response_type']}")
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    bogus_role = api.create_branch(
        create_branch_payload(name="Bogus Role Yard", region_code="TX-N",
                              yard_capacity_units=5, daily_dispatch_capacity=1,
                              labor_rate_cents_per_hour=9_000),
        make_headers("who-1", "SuperUser"))
    validate_error(bogus_role, ApiErrorId.ERR_UNAUTHENTICATED.value)
    bogus_body = bogus_role.json()
    assert bogus_body["response_type"] == "error"
    assert isinstance(bogus_body["data"].get("message"), str)


def test_customer_cannot_dispute_another_customers_assessment(api):
    """PRD §2.1: "- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer`; ownership checks compare the `customer_id` of the
    lease standing behind the addressed resource to `X-User-ID`."
    PRD §3.9: "A `Customer` whose `X-User-ID` matches the `customer_id` of the
    lease behind the assessment may push a `SUBMITTED` assessment back with a
    mandatory `dispute_reason`, moving it `SUBMITTED → DISPUTED` and
    incrementing `dispute_rounds` by one."
    PRD §2.1: "Ownership is enforced on exactly nine operations, and a violation
    on any of them is answered with `ERR_NOT_RESOURCE_OWNER` and HTTP 403:
    booking a logistics job, dispatching a logistics job, completing a logistics
    job, cancelling a logistics job, quoting a refurbishment order, completing a
    refurbishment order, disputing a damage assessment, reading a single lease,
    and reading a single damage assessment."

    Design: Corner/rbac/customer_cannot_dispute_another_customers_assessment
    """
    ctx = setup_rural_submitted_assessment()
    rival = create_customer(name="Rival Rentals", billing_email="ap@rival.test",
                            credit_tier="STANDARD", credit_limit_cents=9_000_000)

    trespass = api.dispute_damage_assessment(
        ctx["assessment"]["id"], {"dispute_reason": "Not my unit"},
        make_customer_headers(rival["id"]))
    validate_error(trespass, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    unchanged = get_assessment(ctx["assessment"]["id"])
    assert unchanged["dispute_rounds"] == 0, (
        f"the trespassing dispute must not count, got "
        f"{unchanged['dispute_rounds']}")
    assert unchanged["status"] == "SUBMITTED"

    owned = validate_success(api.dispute_damage_assessment(
        ctx["assessment"]["id"],
        {"dispute_reason": "HVAC was already noisy at delivery"},
        make_customer_headers(ctx["customer"]["id"])))
    assert owned["status"] == "DISPUTED", (
        f"the owning lessee may push back, got {owned['status']}")
    assert owned["dispute_rounds"] == 1


# ─── Stale-version protection on re-quotes and re-assessments ────────────────

def test_stale_expected_unit_version_on_a_requote_is_rejected(api):
    """PRD §2.8: "A `POST /refurbishment-orders` request must carry
    `expected_unit_version`, a non-optional field holding the client's last
    observed `version` of the target `Unit`. If that value does not equal the
    unit's current `version`, the create is rejected with
    `ERR_STALE_UNIT_VERSION` and HTTP 412, so a client cannot retire a quote
    whose surrounding unit state it has not observed."
    PRD §3.9: "Any refurbishment order already sitting at `QUOTED` on that unit
    moves `QUOTED → SUPERSEDED`; the unit's `latest_quote_estimate_cents` is set
    to the **new** order's `estimated_cost_cents`; and the unit's `version` is
    incremented by one."

    PRD §3.9: "The labour line takes the estimated `labor_hours`, multiplies by
    the servicing branch's `labor_rate_cents_per_hour` and by a scope factor of
    0.45 for `COSMETIC`, 1.00 for `STANDARD`, or 1.85 for `FULL`, and rounds
    half up to a whole cent. The parts line multiplies the estimated
    `parts_cost_cents` by the same scope factor and rounds half up. The recovery
    line takes sixty percent of the assessment's `chargeable_cents` and rounds
    half up — the shop expects to recover most, but not all, of what the lessee
    was charged."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_unit_version_on_a_requote_returns_412
    """
    ctx = setup_rural_finalized_assessment()
    stale_version = get_unit(ctx["unit"]["id"])["version"]

    first = quote_refurbishment(
        ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
        expected_unit_version=stale_version, scope="COSMETIC", labor_hours=12.5,
        parts_cost_cents=143_719, target_condition_grade="B")
    assert first["estimated_cost_cents"] == 194_124, (
        f"Expected 51750 + 64674 + 77700 = 194124, got "
        f"{first['estimated_cost_cents']}")

    # The first quote bumped the unit's version, so the same value is now stale.
    stale = api.create_refurbishment_order(
        create_refurbishment_order_payload(
            ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
            stale_version, scope="FULL", labor_hours=8.0,
            parts_cost_cents=50_000, target_condition_grade="A"),
        make_branch_ops_headers(ctx["branch"]["id"]))
    validate_error(stale, ApiErrorId.ERR_STALE_UNIT_VERSION.value)

    _, meta = validate_paginated(api.list_refurbishment_orders(
        make_fleet_admin_headers(), params={"unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the stale create must persist no row, got {meta['total_count']}")
    assert get_unit(ctx["unit"]["id"])["latest_quote_estimate_cents"] == 194_124, (
        "the stale create must not rewrite the published quote")


def test_requoting_after_a_re_read_supersedes_the_earlier_quote(api):
    """PRD §2.8: "Two creation operations in this system are legitimately
    repeatable — quoting refurbishment for a returned unit, and opening a damage
    assessment for a vacated lease — because a second create deliberately
    retires the earlier record rather than colliding with it."
    PRD §3.9: "Any refurbishment order already sitting at `QUOTED` on that unit
    moves `QUOTED → SUPERSEDED`; the unit's `latest_quote_estimate_cents` is set
    to the **new** order's `estimated_cost_cents`; and the unit's `version` is
    incremented by one."
    PRD §3.9: "The unit's `status` is deliberately not changed: the building
    stays `RETURNED` until someone with spending authority approves the work."


    PRD §3.9: "The labour line takes the estimated `labor_hours`, multiplies by
    the servicing branch's `labor_rate_cents_per_hour` and by a scope factor of
    0.45 for `COSMETIC`, 1.00 for `STANDARD`, or 1.85 for `FULL`, and rounds
    half up to a whole cent. The parts line multiplies the estimated
    `parts_cost_cents` by the same scope factor and rounds half up. The recovery
    line takes sixty percent of the assessment's `chargeable_cents` and rounds
    half up — the shop expects to recover most, but not all, of what the lessee
    was charged."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_unit_version_on_a_requote_returns_412
    """
    ctx = setup_rural_finalized_assessment()
    stale_version = get_unit(ctx["unit"]["id"])["version"]

    first = quote_refurbishment(
        ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
        expected_unit_version=stale_version, scope="COSMETIC", labor_hours=12.5,
        parts_cost_cents=143_719, target_condition_grade="B")
    validate_error(
        api.create_refurbishment_order(
            create_refurbishment_order_payload(
                ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
                stale_version, scope="FULL", labor_hours=8.0,
                parts_cost_cents=50_000, target_condition_grade="A"),
            make_branch_ops_headers(ctx["branch"]["id"])),
        ApiErrorId.ERR_STALE_UNIT_VERSION.value)

    fresh_version = get_unit(ctx["unit"]["id"])["version"]
    second = validate_success(api.create_refurbishment_order(
        create_refurbishment_order_payload(
            ctx["unit"]["id"], ctx["branch"]["id"], ctx["assessment"]["id"],
            fresh_version, scope="FULL", labor_hours=8.0,
            parts_cost_cents=50_000, target_condition_grade="A"),
        make_branch_ops_headers(ctx["branch"]["id"])), 201)

    assert second["estimated_cost_cents"] == 306_360, (
        f"Expected 136160 labour + 92500 parts + 77700 recovery = 306360, got "
        f"{second['estimated_cost_cents']}")
    assert get_refurbishment_order(first["id"])["status"] == "SUPERSEDED", (
        "the earlier quote must be retired by the re-quote")
    assert second["status"] == "QUOTED"

    unit = get_unit(ctx["unit"]["id"])
    assert unit["latest_quote_estimate_cents"] == 306_360, (
        f"the newest quote must be published on the unit, got "
        f"{unit['latest_quote_estimate_cents']}")
    assert unit["status"] == "RETURNED", (
        f"quoting never moves the unit, got {unit['status']}")

    _, meta = validate_paginated(api.list_refurbishment_orders(
        make_fleet_admin_headers(), params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 2, (
        f"Expected the superseded and the live quote, got {meta['total_count']}")


def test_stale_expected_lease_version_on_a_reassessment_is_rejected(api):
    """PRD §2.8: "A `POST /damage-assessments` request must carry
    `expected_lease_version`, a non-optional field holding the client's last
    observed `version` of the target `Lease`. If that value does not equal the
    lease's current `version`, the create is rejected with
    `ERR_STALE_LEASE_VERSION` and HTTP 412, so an inspector cannot supersede an
    assessment on a lease whose settlement state has moved on since it was
    read."
    PRD §3.9: "Creating a new assessment for a lease retires every existing
    assessment on that lease that is still open, taking it `DRAFT → SUPERSEDED`,
    `SUBMITTED → SUPERSEDED` or `DISPUTED → SUPERSEDED` according to where it
    stood, increments the lease's `assessment_round` by one so the number of
    rounds ever opened is auditable, and increments the lease's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lease_version_on_a_reassessment_returns_412
    """
    ctx = setup_rural_vacated_lease()
    stale_version = get_lease(ctx["lease"]["id"])["version"]

    first = validate_success(api.create_damage_assessment(
        create_damage_assessment_payload(ctx["lease"]["id"], ctx["unit"]["id"],
                                         ctx["teardown_job"]["id"], stale_version),
        make_damage_assessor_headers()), 201)
    assert get_lease(ctx["lease"]["id"])["assessment_round"] == 1, (
        "opening the first assessment raises assessment_round to 1")

    stale = api.create_damage_assessment(
        create_damage_assessment_payload(ctx["lease"]["id"], ctx["unit"]["id"],
                                         ctx["teardown_job"]["id"], stale_version),
        make_damage_assessor_headers())
    validate_error(stale, ApiErrorId.ERR_STALE_LEASE_VERSION.value)

    _, meta = validate_paginated(api.list_damage_assessments(
        make_fleet_admin_headers(), params={"lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the stale create must persist no row, got {meta['total_count']}")
    assert get_assessment(first["id"])["status"] == "DRAFT", (
        "the refused create must leave the first assessment open")
    assert get_lease(ctx["lease"]["id"])["assessment_round"] == 1, (
        "the refused create must not raise assessment_round")


def test_reassessment_after_a_re_read_supersedes_the_open_assessment(api):
    """PRD §3.9: "Creating a new assessment for a lease retires every existing
    assessment on that lease that is still open, taking it `DRAFT → SUPERSEDED`,
    `SUBMITTED → SUPERSEDED` or `DISPUTED → SUPERSEDED` according to where it
    stood, increments the lease's `assessment_round` by one so the number of
    rounds ever opened is auditable, and increments the lease's `version` by
    one."
    PRD §3.9: "On creation the system stamps `assessor_user_id` with the
    inspector's `X-User-ID` — the handle that later blocks that same operator
    from authorizing the resulting spend — and copies the unit's present
    `condition_grade` into the assessment's `condition_grade_before`, freezing
    the "as returned" grade before any repair is contemplated."
    PRD §2.8: "Two creation operations in this system are legitimately
    repeatable — quoting refurbishment for a returned unit, and opening a damage
    assessment for a vacated lease — because a second create deliberately
    retires the earlier record rather than colliding with it."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_lease_version_on_a_reassessment_returns_412
    """
    ctx = setup_rural_vacated_lease()
    stale_version = get_lease(ctx["lease"]["id"])["version"]

    first = validate_success(api.create_damage_assessment(
        create_damage_assessment_payload(ctx["lease"]["id"], ctx["unit"]["id"],
                                         ctx["teardown_job"]["id"], stale_version),
        make_damage_assessor_headers()), 201)
    validate_error(
        api.create_damage_assessment(
            create_damage_assessment_payload(ctx["lease"]["id"], ctx["unit"]["id"],
                                             ctx["teardown_job"]["id"],
                                             stale_version),
            make_damage_assessor_headers()),
        ApiErrorId.ERR_STALE_LEASE_VERSION.value)

    fresh_version = get_lease(ctx["lease"]["id"])["version"]
    second = validate_success(api.create_damage_assessment(
        create_damage_assessment_payload(ctx["lease"]["id"], ctx["unit"]["id"],
                                         ctx["teardown_job"]["id"], fresh_version),
        make_damage_assessor_headers("inspector-12")), 201)

    assert get_assessment(first["id"])["status"] == "SUPERSEDED", (
        "the open assessment must be retired by the re-assessment")
    assert second["status"] == "DRAFT", (
        f"the fresh assessment starts in DRAFT, got {second['status']}")
    assert second["assessor_user_id"] == "inspector-12", (
        f"the opening inspector's handle must be stamped, got "
        f"{second['assessor_user_id']}")
    assert second["condition_grade_before"] == "A", (
        f"the unit's present grade is frozen, got "
        f"{second['condition_grade_before']}")
    assert get_lease(ctx["lease"]["id"])["assessment_round"] == 2, (
        "the second round must be auditable on the lease")

    _, meta = validate_paginated(api.list_damage_assessments(
        make_fleet_admin_headers(), params={"lease_id": ctx["lease"]["id"]}))
    assert meta["total_count"] == 2, (
        f"Expected the superseded and the fresh assessment, got "
        f"{meta['total_count']}")
