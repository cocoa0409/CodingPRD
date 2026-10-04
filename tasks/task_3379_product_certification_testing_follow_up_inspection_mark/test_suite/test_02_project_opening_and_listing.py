"""Project opening gates, listing, pagination, and access-control basics.

Covers system-managed project fields at creation, the project list filters and
the fixed pagination envelope, the three creation gates (manufacturer ACTIVE,
standard ACTIVE, category match), and the authentication / role / ownership
stages of the validation pipeline.
"""

from test_helpers import (
    ApiErrorId,
    BASE_CLOCK_ISO,
    assert_project,
    create_factory,
    create_manufacturer,
    create_standard,
    get_success_data,
    make_manufacturer_rep_headers,
    no_auth_headers,
    open_project,
    project_payload,
    protocol_spec,
    sample_payload,
    set_clock,
    setup_open_project,
    setup_world,
    standard_payload,
    suspend_manufacturer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_project_create_client_supplied_status_input_ignored(api, admin_headers):
    """PRD §3.2: "A new project is `STANDARD_SELECTED`, with `retest_count` at
    zero, `fee_snapshot_cents` null until the project first reaches evaluation,
    and `decided_by` and `decided_on` null until a decision is rendered."
    PRD §3.2: "The project's `manufacturer_id` is set from the representative's
    `X-User-ID`, never from the payload."

    Design: Corner/entities/project_create_client_supplied_status_input_ignored
    """
    ctx = setup_world(api)
    payload = project_payload(
        ctx["factory"]["id"],
        ctx["standard"]["id"],
        status="APPROVED",
        version=99,
        retest_count=7,
    )
    response = api.create_project(
        payload, make_manufacturer_rep_headers(ctx["manufacturer"]["id"])
    )
    data = validate_success(response, 201)
    assert_project(data)
    assert data["status"] == "STANDARD_SELECTED", (
        f"client-supplied status must be ignored, got {data['status']!r}"
    )
    assert data["version"] == 1
    assert data["retest_count"] == 0
    assert data["fee_snapshot_cents"] is None
    assert data["manufacturer_id"] == ctx["manufacturer"]["id"]


def test_projects_list_paginates_and_filters_by_status(api, officer_headers):
    """PRD §3.2: "Projects can be listed with optional filters on
    `manufacturer_id`, `factory_id`, `standard_id`, and `status`."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/projects_list_paginates_and_filters_by_status
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    open_project(
        api, mfr_id, ctx["factory"]["id"], ctx["standard"]["id"], product_model="AC-101"
    )
    open_project(
        api, mfr_id, ctx["factory"]["id"], ctx["standard"]["id"], product_model="AC-102"
    )
    page, meta = validate_paginated(
        api.list_projects(
            officer_headers, params={"manufacturer_id": mfr_id, "limit": 2, "offset": 0}
        )
    )
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    selected, meta_sel = validate_paginated(
        api.list_projects(
            officer_headers,
            params={"manufacturer_id": mfr_id, "status": "STANDARD_SELECTED"},
        )
    )
    assert meta_sel["total_count"] == 3
    assert len(selected) == 3
    approved, meta_app = validate_paginated(
        api.list_projects(
            officer_headers, params={"manufacturer_id": mfr_id, "status": "APPROVED"}
        )
    )
    assert approved == []
    assert meta_app["total_count"] == 0


def test_list_endpoints_apply_pagination_defaults(api, engineer_headers):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
    items skipped and defaults to 0."

    Design: Corner/endpoints/list_endpoints_apply_pagination_defaults
    """
    ctx = setup_open_project(api)
    data, meta = validate_paginated(
        api.list_projects(
            engineer_headers, params={"manufacturer_id": ctx["manufacturer"]["id"]}
        )
    )
    assert len(data) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_category_standard_mismatch_returns_422(api, admin_headers):
    """PRD §3.2: "Three gates guard creation: the manufacturer must be `ACTIVE`
    (`ERR_MANUFACTURER_SUSPENDED`); the selected standard must be `ACTIVE` at the
    current logical time — an `UPCOMING` or `RETIRED` edition is rejected with
    `ERR_STANDARD_NOT_ACTIVE`; and the supplied `category_code` must equal the
    selected standard's `category_code` (`ERR_CATEGORY_STANDARD_MISMATCH`)."

    Design: Corner/validations/category_standard_mismatch_returns_422
    """
    ctx = setup_world(api)
    response = api.create_project(
        project_payload(
            ctx["factory"]["id"], ctx["standard"]["id"], category_code="LIGHTING"
        ),
        make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CATEGORY_STANDARD_MISMATCH)


def test_suspended_manufacturer_blocked_from_new_projects(api, officer_headers):
    """PRD §3.1: "A `ComplianceOfficer` may later suspend a manufacturer,
    supplying a `reason` that is recorded as `suspension_reason`; from that
    moment the manufacturer's `status` is `SUSPENDED` and any attempt to open a
    new certification project for that manufacturer is rejected with
    `ERR_MANUFACTURER_SUSPENDED`."

    Design: Corner/validations/suspended_manufacturer_blocked_from_new_projects
    """
    ctx = setup_world(api)
    suspend_manufacturer(
        api, ctx["manufacturer"]["id"], reason="Misuse of mark investigation"
    )
    response = api.create_project(
        project_payload(ctx["factory"]["id"], ctx["standard"]["id"]),
        make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MANUFACTURER_SUSPENDED)
    manufacturer = get_success_data(
        api.get_manufacturer(ctx["manufacturer"]["id"], officer_headers)
    )
    assert manufacturer["status"] == "SUSPENDED"
    assert manufacturer["suspension_reason"] == "Misuse of mark investigation"


def test_retired_standard_blocks_new_projects(api, admin_headers):
    """PRD §2.6: "at or after `effective_to` it is `RETIRED`."
    PRD §3.2: "the selected standard must be `ACTIVE` at the current logical
    time — an `UPCOMING` or `RETIRED` edition is rejected with
    `ERR_STANDARD_NOT_ACTIVE`"

    Design: Corner/validations/retired_standard_blocks_new_projects
    """
    set_clock(api, BASE_CLOCK_ISO)
    retired = create_standard(
        api,
        standard_code="UL-60065",
        edition_label="Ed. 8",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        construction_requirements=["enclosure"],
        test_protocols=[protocol_spec("P-1", pass_threshold=10)],
    )
    assert retired["status"] == "RETIRED"
    manufacturer = create_manufacturer(api)
    factory = create_factory(api, manufacturer["id"])
    response = api.create_project(
        project_payload(factory["id"], retired["id"]),
        make_manufacturer_rep_headers(manufacturer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STANDARD_NOT_ACTIVE)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, carries an `X-User-Role`
    that is not one of the declared roles, or — for an entity-backed role —
    carries an `X-User-ID` that is not the `id` of an instance of the backing
    entity is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    set_clock(api, BASE_CLOCK_ISO)
    response = api.create_project({}, no_auth_headers())
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_manufacturer_rep_cannot_create_standard_returns_unauthorized(api):
    """PRD §3.1: "A `CertificationBodyAdmin` registers each standard edition by
    supplying the `category_code` of the product category it belongs to"
    PRD §2.1: "A request whose role is not permitted on the targeted endpoint is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/validations/manufacturer_rep_cannot_create_standard_returns_unauthorized
    """
    set_clock(api, BASE_CLOCK_ISO)
    manufacturer = create_manufacturer(api)
    response = api.create_standard(
        standard_payload(
            standard_code="UL-9999",
            edition_label="Ed. 1",
            construction_requirements=["enclosure"],
            test_protocols=[protocol_spec("P-1", pass_threshold=10)],
        ),
        make_manufacturer_rep_headers(manufacturer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_manufacturer_rep_cannot_touch_other_manufacturers_project_returns_forbidden(
    api, officer_headers
):
    """PRD §2.1: "A `ManufacturerRep` may mutate only resources whose
    `manufacturer_id` equals their own `X-User-ID` — this scope covers
    certification projects, samples, construction records, substitution
    requests, mark licenses, label batches, and field evaluations."
    PRD §2.1: "A violation of either ownership scope is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/manufacturer_rep_cannot_touch_other_manufacturers_project_returns_forbidden
    """
    ctx = setup_open_project(api)
    other = create_manufacturer(
        api, legal_name="Beacon Power Co", annual_revenue_tier="STANDARD"
    )
    response = api.submit_sample(
        ctx["project"]["id"],
        sample_payload(serial_no="SX-1"),
        make_manufacturer_rep_headers(other["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN)
    samples, _meta = validate_paginated(
        api.list_samples(ctx["project"]["id"], officer_headers)
    )
    assert samples == [], "no sample may be created by a foreign ManufacturerRep"
