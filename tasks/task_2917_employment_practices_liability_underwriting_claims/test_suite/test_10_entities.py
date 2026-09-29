"""Entity shape: declared fields, defaults, derived values and reference resolution."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_id_order,
    assert_null,
    assert_same_instant,
)


def test_registering_a_jurisdiction_echoes_every_declared_field(api):
    """A create returns 201 and every input field round-trips unchanged.

    PRD: "Registering one supplies a two-letter `code` matching exactly two
    uppercase letters, a display `name`, a `hazard_tier` drawn from `T1`, `T2`,
    `T3` and `T4`, the `admin_agency_name` of the body that issues charges of
    discrimination there, a `pre_suit_window_days` count of at least 0 whole
    days, a `wage_hour_multiplier` of at least 1.00 carried to two decimal
    places, and a `class_action_propensity_pct` between 0.00 and 100.00
    inclusive."

    Design: Corner/entities/create_jurisdiction_returns_201_with_every_declared_field
    """
    response = api.create_jurisdiction(F.jurisdiction("CA"), U.ADMIN)
    data = get_success_data(response, expected_status=201)
    assert_fields(
        data,
        {
            "code": "CA",
            "name": "California",
            "hazard_tier": T.HAZARD_TIER_4,
            "admin_agency_name": "California Civil Rights Department",
            "pre_suit_window_days": 180,
            "wage_hour_multiplier": 1.60,
            "class_action_propensity_pct": 42.00,
            "pre_suit_mediation_required": True,
        },
    )
    assert_common_fields(data, expected_version=1)
    assert_same_instant(data["updated_at"], data["created_at"], "updated_at")


def test_reading_a_rate_plan_by_id_returns_the_stored_row(api):
    """The GET view of a freshly created plan is the row as stored, still DRAFT.

    PRD: "A plan is created in `DRAFT` and is inert there."

    Design: Corner/entities/get_rate_plan_by_id_returns_the_stored_row_unchanged
    """
    created = get_success_data(api.create_rate_plan(F.rate_plan(), U.ADMIN), expected_status=201)
    data = get_success_data(api.get_rate_plan(created["id"], U.UNDERWRITER))
    assert_fields(
        data,
        {
            "id": created["id"],
            "name": "EPLI Standard 2026",
            "base_rate_per_employee_cents": 41750,
            "min_premium_cents": 750000,
            "wage_hour_sublimit_pct": 0.25,
            "third_party_sublimit_pct": 0.40,
            "status": T.RATE_PLAN_DRAFT,
            "version": 1,
        },
    )


def test_the_panel_roster_pages_by_blended_rate_and_filters_by_jurisdiction(api):
    """Paging reports total_count and has_more; the jurisdiction filter narrows the set.

    PRD: "defense panel firms by `blended_rate_cents` ascending and then
    `created_at` ascending"

    Design: Corner/entities/list_defense_panel_firms_paginates_with_total_count_and_has_more
    """
    S.create_jurisdictions(api, ["CA", "TX"])
    firm_a = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA", "TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    firm_b = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    firm_l = S.create_panel_firm(
        api,
        name="Lonestar Defense Group",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    assert firm_a["blended_rate_cents"] == 60400
    assert firm_b["blended_rate_cents"] == 48400

    rows, meta = validate_paginated(api.list_panel_firms(U.ADMIN, {"limit": 2, "offset": 0}))
    assert_fields(meta, {"limit": 2, "offset": 0, "total_count": 3, "has_more": True})
    assert_id_order(rows, [firm_b["id"], firm_l["id"]])

    rows, meta = validate_paginated(api.list_panel_firms(U.ADMIN, {"limit": 2, "offset": 2}))
    assert_fields(meta, {"limit": 2, "offset": 2, "total_count": 3, "has_more": False})
    assert_id_order(rows, [firm_a["id"]])

    rows, meta = validate_paginated(api.list_panel_firms(U.ADMIN, {"jurisdiction_code": "TX"}))
    assert_fields(meta, {"total_count": 2, "has_more": False})
    assert sorted(row["id"] for row in rows) == sorted([firm_a["id"], firm_l["id"]])
    assert firm_b["id"] not in [row["id"] for row in rows]

    _, meta = validate_paginated(api.list_panel_firms(U.ADMIN))
    assert_fields(meta, {"limit": 10, "offset": 0})


def test_reading_a_claim_that_was_never_minted_is_a_scoped_404(api):
    """A well-formed but unknown claim id resolves to ERR_CLAIM_NOT_FOUND.

    PRD: "Every identifier in the URL path resolves to an existing row of the
    expected type → otherwise the 404 matching that path segment"

    Design: Corner/entities/get_claim_by_unminted_uuid_returns_claim_not_found
    """
    body = validate_error(
        api.get_claim(NON_EXISTENT_UUID, U.ADJUSTER), E.ERR_CLAIM_NOT_FOUND, 404
    )
    assert isinstance(body["message"], str) and body["message"].strip() != ""


def test_an_applicant_create_missing_a_required_field_is_rejected(api):
    """Each of the three required applicant fields is individually mandatory.

    PRD: "Request shape: required body fields present, no unknown body fields,
    correct types, valid enum members, numeric values inside their permitted
    ranges, decimal-place limits respected, ISO 8601 instants well formed,
    interval fields correctly ordered"

    Design: Corner/entities/applicant_create_missing_required_fields_returns_invalid_request
    """
    S.create_jurisdiction(api, "TX")
    base = dict(
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    for missing in ("primary_jurisdiction_code", "jurisdiction_headcounts", "legal_name"):
        payload = {k: v for k, v in base.items() if k != missing}
        validate_error(
            api.create_applicant(payload, U.UNDERWRITER), E.ERR_INVALID_REQUEST, 400
        )


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults(api):
    """pre_suit_mediation_required, separations_since_assessment and third-party election default.

    PRD: "An optional `third_party_coverage_requested` boolean records whether
    coverage for customer and vendor claimants is wanted and defaults to false."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    plan_id = S.create_active_rate_plan(api)["id"]
    jurisdiction = get_success_data(
        api.create_jurisdiction(
            F.jurisdiction(
                "NY",
                pre_suit_window_days=150,
                class_action_propensity_pct=31.00,
                pre_suit_mediation_required=None,
            ),
            U.ADMIN,
        ),
        expected_status=201,
    )
    assert jurisdiction["pre_suit_mediation_required"] is False

    applicant = S.create_applicant(
        api,
        legal_name="Harborline Media Inc",
        total_headcount=30,
        prior_year_separations=3,
        jurisdiction_headcounts=[{"code": "NY", "headcount": 30}],
        primary_jurisdiction_code="NY",
    )
    assert applicant["separations_since_assessment"] == 0

    assessment = S.create_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    assert_fields(
        assessment,
        {
            "third_party_coverage_requested": False,
            "credit_basis_stale": False,
            "status": T.ASSESSMENT_DRAFT,
            "version": 1,
        },
    )
    assert_null(assessment, ["priced_by_user_id", "approved_by_user_id"])


def test_applicant_exposure_fields_are_derived_and_never_client_supplied(api):
    """The four derived values are computed server-side; supplying one is rejected.

    PRD: "**Turnover** is a straightforward ratio: a separations count
    multiplied by 100, divided by `total_headcount`, rounded half up to two
    decimal places."

    Design: Corner/entities/applicant_computed_exposure_fields_are_derived_and_unknown_input_rejected
    """
    S.create_jurisdiction(api, "TX")
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assert_fields(
        applicant,
        {
            "turnover_pct": 10.00,
            "hazard_load_pct": 0.070,
            "risk_credit_pct": 0.00,
            "exposure_score": 28.00,
            "version": 1,
        },
    )

    validate_error(
        api.create_applicant(
            F.applicant(
                legal_name="Bayline Foods Two LLC",
                total_headcount=40,
                prior_year_separations=4,
                jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
                primary_jurisdiction_code="TX",
                turnover_pct=1.0,
            ),
            U.UNDERWRITER,
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )


def test_rate_plan_create_mints_system_fields_and_activation_bumps_the_version(api):
    """The client never supplies id or status; activation is the single lifecycle move.

    PRD: "Activating it moves it `DRAFT → ACTIVE`, which is the only transition
    on the plan's lifecycle and is refused with
    `ERR_RATE_PLAN_NOT_ACTIVATABLE` on a plan that is not currently `DRAFT`;
    `ACTIVE` is terminal."

    Design: Corner/entities/rate_plan_create_mints_system_fields_and_activate_bumps_them
    """
    created = get_success_data(api.create_rate_plan(F.rate_plan(), U.ADMIN), expected_status=201)
    assert is_valid_uuid(created["id"])
    assert_fields(created, {"status": T.RATE_PLAN_DRAFT, "version": 1})
    assert_same_instant(created["updated_at"], created["created_at"], "updated_at")

    validate_error(
        api.create_rate_plan(F.rate_plan(name="EPLI Premier 2026", status="ACTIVE"), U.ADMIN),
        E.ERR_INVALID_REQUEST,
        400,
    )

    activated = get_success_data(api.activate_rate_plan(created["id"], U.ADMIN))
    assert_fields(activated, {"status": T.RATE_PLAN_ACTIVE, "version": 2})
    assert_same_instant(activated["created_at"], created["created_at"], "created_at")


def test_enum_range_and_interval_violations_all_report_invalid_request(api):
    """Six distinct shape violations across five entities each answer ERR_INVALID_REQUEST.

    PRD: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100, and a
    value outside that inclusive range is a malformed request rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/enum_range_and_interval_type_constraints_return_invalid_request
    """
    S.create_jurisdiction(api, "TX")
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )

    validate_error(
        api.create_jurisdiction(
            F.jurisdiction("NV", name="Nevada", hazard_tier="T5"), U.ADMIN
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_rate_plan(
            F.rate_plan(name="EPLI Wide 2026", wage_hour_sublimit_pct=1.5), U.ADMIN
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_applicant(
            F.applicant(
                legal_name="Zero Headcount LLC",
                total_headcount=0,
                prior_year_separations=0,
                jurisdiction_headcounts=[{"code": "TX", "headcount": 1}],
                primary_jurisdiction_code="TX",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_panel_firm(
            F.panel_firm(
                name="Global Reach Counsel LLP", tier="GLOBAL", jurisdiction_codes=["TX"]
            ),
            U.ADMIN,
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_risk_service(
            applicant["id"],
            F.risk_service(
                effective_from="2026-09-01T00:00:00.000Z",
                effective_to="2026-09-01T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_jurisdictions(U.ADMIN, {"limit": 101}), E.ERR_INVALID_REQUEST, 400
    )


def test_body_level_parent_references_that_do_not_resolve_are_scoped_404s(api):
    """An unknown policy path id and an unknown jurisdiction natural key each 404.

    PRD: "Every foreign key and natural key supplied in the request **body**
    resolves — `applicant_id`, `rate_plan_id`, `exposure_assessment_id`,
    `policy_id`, `lead_claim_id`, `claim_id`, `related_to_claim_id`,
    `panel_firm_id` and every entry of `excluded_panel_firm_ids`, plus the
    jurisdiction natural keys `primary_jurisdiction_code`, each `code` inside
    `jurisdiction_headcounts` and each entry of `jurisdiction_codes` → otherwise
    the corresponding 404 from the same family"

    Design: Corner/entities/claim_and_applicant_creates_reject_unresolvable_parent_references
    """
    S.create_jurisdiction(api, "TX")
    validate_error(
        api.report_claim(
            NON_EXISTENT_UUID,
            F.claim(first_notice_at="2026-08-05T00:00:00.000Z", alleged_damages_cents=5000000),
            U.ADJUSTER,
        ),
        E.ERR_POLICY_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_applicant(
            F.applicant(
                legal_name="Zephyr Freight LLC",
                total_headcount=10,
                prior_year_separations=1,
                jurisdiction_headcounts=[{"code": "ZZ", "headcount": 10}],
                primary_jurisdiction_code="ZZ",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_JURISDICTION_NOT_FOUND,
        404,
    )


def test_a_claim_may_point_at_an_earlier_claim_on_the_same_policy(api):
    """related_to_claim_id is a self-referential edge and a claims-list filter.

    PRD: "Two optional fields complete the payload: `claimant_count` defaults to
    1 and must be at least 1, with any value above 1 marking the matter as a
    class or mass claim, and `related_to_claim_id` optionally names an earlier
    claim this one is alleged to arise from."

    Design: Corner/entities/claim_related_to_claim_id_forms_a_self_referential_graph_edge
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    first = S.report_claim(
        api,
        policy["id"],
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )
    second = get_success_data(
        api.report_claim(
            policy["id"],
            F.claim(
                first_notice_at="2026-08-07T00:00:00.000Z",
                alleged_damages_cents=3000000,
                related_to_claim_id=first["id"],
            ),
            U.ADJUSTER,
        ),
        expected_status=201,
    )
    assert_fields(
        second, {"related_to_claim_id": first["id"], "policy_id": policy["id"]}
    )
    assert_null(second, ["related_claim_group_id"])
    assert_null(first, ["related_to_claim_id"])

    rows, meta = validate_paginated(
        api.list_claims(U.ADJUSTER, {"related_to_claim_id": first["id"]})
    )
    assert_fields(meta, {"total_count": 1, "has_more": False})
    assert_id_order(rows, [second["id"]])

    _, meta = validate_paginated(api.list_claims(U.ADJUSTER, {"policy_id": policy["id"]}))
    assert meta["total_count"] == 2
