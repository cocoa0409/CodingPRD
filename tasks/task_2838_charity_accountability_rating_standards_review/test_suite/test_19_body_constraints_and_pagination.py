"""Body-level constraints probed from both sides, and where pagination sits in the ladder."""
from test_helpers import (
    NON_EXISTENT_UUID,
    assert_instant,
    assert_ratio,
    create_draft_methodology,
    create_filing_record_payload,
    create_methodology_version_payload,
    create_organization,
    create_organization_payload,
    set_clock,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_each_body_level_constraint_answers_with_its_own_error_and_persists_nothing(
    api, admin_headers, analyst_headers
):
    """Seven rejections across five rules, and the rejected filing writes did not burn the
    organization's OCC version, so the same expected_organization_version still retries.

    PRD §2.8: "19. **Weight normalisation.** `weight_financial_health`, `weight_accountability`, `weight_transparency` and `weight_impact` sum to exactly 1.0000 and each one is strictly greater than 0.0000, else `ERR_WEIGHTS_NOT_NORMALIZED` (422), on `POST /methodology-versions`."

    PRD §2.8: "20. **Unique tax id.** `ein` is unique across all organizations, else `ERR_DUPLICATE_EIN` (409), on `POST /organizations`."

    PRD §2.8: "21. **Unique methodology label.** `version_label` is unique across all methodology versions, else `ERR_DUPLICATE_VERSION_LABEL` (409), on `POST /methodology-versions`."

    PRD §2.8: "29. **Expense identity.** `total_expense_cents` equals the sum of `program_expense_cents`, `fundraising_expense_cents` and `admin_expense_cents`, and `joint_cost_allocated_cents` is at most `program_expense_cents`. Otherwise `ERR_EXPENSE_COMPONENTS_MISMATCH` (422), on both `POST /filing-records` and `POST /filing-records/{filing_record_id}/validate`."

    PRD §2.5: "The clock may move forward or stay where it is, never backwards: a requested instant earlier than the current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 409)."

    Design: Corner/validations/weight_ein_label_expense_and_clock_constraints_each_fire_their_own_error
    """
    organization = create_organization()
    organization_version = organization["version"]
    create_draft_methodology()
    set_clock("2026-09-01T00:00:00Z")

    validate_error(
        api.create_methodology_version(
            create_methodology_version_payload(version_label="M9", weight_impact=0.14),
            admin_headers,
        ),
        "ERR_WEIGHTS_NOT_NORMALIZED",
        422,
    )
    validate_error(
        api.create_methodology_version(
            create_methodology_version_payload(
                version_label="M9", weight_transparency=0.35, weight_impact=0.0
            ),
            admin_headers,
        ),
        "ERR_WEIGHTS_NOT_NORMALIZED",
        422,
    )
    validate_error(
        api.create_methodology_version(
            create_methodology_version_payload(
                version_label="M1",
                weight_financial_health=0.25,
                weight_accountability=0.25,
                weight_transparency=0.25,
                weight_impact=0.25,
            ),
            admin_headers,
        ),
        "ERR_DUPLICATE_VERSION_LABEL",
        409,
    )
    validate_error(
        api.create_organization(
            create_organization_payload(
                legal_name="Copycat Relief Fund",
                fiscal_year_end_month=6,
                contact_email="ops@copycat.org",
            ),
            admin_headers,
        ),
        "ERR_DUPLICATE_EIN",
        409,
    )
    validate_error(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"], organization_version, admin_expense_cents=900000
            ),
            analyst_headers,
        ),
        "ERR_EXPENSE_COMPONENTS_MISMATCH",
        422,
    )
    validate_error(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"],
                organization_version,
                joint_cost_allocated_cents=8000001,
            ),
            analyst_headers,
        ),
        "ERR_EXPENSE_COMPONENTS_MISMATCH",
        422,
    )
    validate_error(
        api.set_clock(set_clock_payload("2026-08-31T23:59:59Z"), admin_headers),
        "ERR_CLOCK_NOT_MONOTONIC",
        409,
    )

    _drafts, draft_meta = validate_paginated(
        api.list_methodology_versions(admin_headers, params={"status": "DRAFT"})
    )
    assert draft_meta["total_count"] == 1
    _orgs, org_meta = validate_paginated(api.list_organizations(admin_headers))
    assert org_meta["total_count"] == 1
    _filings, filing_meta = validate_paginated(
        api.list_organization_filing_records(organization["id"], analyst_headers)
    )
    assert filing_meta["total_count"] == 0

    after = validate_success(api.get_organization(organization["id"], admin_headers))
    assert after["version"] == organization_version


def test_landing_exactly_on_each_constraint_is_admitted(api, admin_headers, analyst_headers):
    """Weights that sum to 1.0000 with three of them at 0.0001, an EIN one digit apart, a
    joint cost equal to program expense, a clock re-set to now, and both pagination bounds.

    PRD §3.1: "Each weight is a number between 0.0000 and 1.0000 carried to four decimal places, each must be strictly greater than zero, and the four must sum to exactly 1.0000; anything else is `ERR_WEIGHTS_NOT_NORMALIZED`."

    PRD §3.3: "Two arithmetic identities are enforced at submission and again at validation: `total_expense_cents` must equal the sum of `program_expense_cents`, `fundraising_expense_cents` and `admin_expense_cents`, and `joint_cost_allocated_cents` must not exceed `program_expense_cents`; a breach of either is `ERR_EXPENSE_COMPONENTS_MISMATCH`."

    PRD §2.3: "`limit` defaults to 10 when omitted, must be an integer, and must lie between a minimum of 1 and a maximum of 100 inclusive."

    PRD §2.3: "Unless an endpoint's own description in §4 names a different ordering, list results are sorted by `created_at` ascending."

    Design: Corner/validations/every_near_miss_that_lands_exactly_on_the_constraint_is_accepted
    """
    organization = create_organization()
    set_clock("2026-09-01T00:00:00Z")

    edge = validate_success(
        api.create_methodology_version(
            create_methodology_version_payload(
                version_label="M-EDGE",
                weight_financial_health=0.9997,
                weight_accountability=0.0001,
                weight_transparency=0.0001,
                weight_impact=0.0001,
            ),
            admin_headers,
        ),
        201,
    )
    assert edge["status"] == "DRAFT"
    assert_ratio(edge["weight_financial_health"], 0.9997, "weight_financial_health")
    assert_ratio(edge["weight_accountability"], 0.0001, "weight_accountability")
    assert_ratio(edge["weight_transparency"], 0.0001, "weight_transparency")
    assert_ratio(edge["weight_impact"], 0.0001, "weight_impact")

    sibling = validate_success(
        api.create_organization(
            create_organization_payload(
                legal_name="Harbor Relief Endowment",
                ein="111111112",
                org_type="PRIVATE_FOUNDATION",
                contact_email="ops@harborendowment.org",
            ),
            admin_headers,
        ),
        201,
    )
    assert sibling["ein"] == "111111112"

    filing = validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"],
                organization["version"],
                joint_cost_allocated_cents=8000000,
            ),
            analyst_headers,
        ),
        201,
    )
    assert filing["joint_cost_allocated_cents"] == 8000000
    assert filing["program_expense_cents"] == 8000000

    unmoved = set_clock("2026-09-01T00:00:00Z")
    assert_instant(unmoved["current_utc"], "2026-09-01T00:00:00Z", "current_utc")

    narrow, narrow_meta = validate_paginated(
        api.list_organizations(admin_headers, params={"limit": 1, "offset": 0})
    )
    assert len(narrow) == 1
    assert narrow_meta["total_count"] == 2
    assert narrow_meta["has_more"] is True
    wide, wide_meta = validate_paginated(
        api.list_organizations(admin_headers, params={"limit": 100, "offset": 0})
    )
    assert len(wide) == 2
    assert wide_meta["total_count"] == 2
    assert wide_meta["has_more"] is False
    assert narrow[0]["id"] == wide[0]["id"] == organization["id"]


def test_the_pagination_bounds_are_checked_after_the_role_and_path_gates(
    api, admin_headers, analyst_headers, public_headers
):
    """The identical limit=0 produces a 404, a 403 and a 400 depending on what else is
    wrong with the request, because priority 6 sits below priorities 2 and 3.

    PRD §2.8: "Checks are evaluated in one fixed ascending order, and the **first** failing check determines the response."

    PRD §2.8: "2. **Role admission.** `X-User-Role` is one of the six declared roles and is among the roles the target endpoint admits, on every endpoint, else `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §2.8: "6. **Pagination shape.** On every list endpoint, `limit` is an integer between 1 and 100 inclusive and `offset` is an integer of 0 or greater, else `ERR_INVALID_PAGINATION` (400)."

    PRD §4: "| `GET` | `/governance-profiles` | Reverse lookup of governance profiles by rating cycle. The array is length 0 or 1 for any single rating_cycle_id. | `MethodologyAdmin`, `RatingAnalyst`, `PublishingReviewer`, `AppealPanelist`, `OrganizationRep` |"

    Design: Corner/validations/pagination_bounds_are_the_last_gate_before_the_handler
    """
    organization = create_organization()

    validate_error(
        api.list_dimension_scores(
            NON_EXISTENT_UUID, analyst_headers, params={"limit": 0}
        ),
        "ERR_RATING_CYCLE_NOT_FOUND",
        404,
    )
    validate_error(
        api.list_governance_profiles(public_headers, params={"limit": 0}),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api.list_organizations(admin_headers, params={"limit": 0}),
        "ERR_INVALID_PAGINATION",
        400,
    )
    validate_error(
        api.list_organizations(admin_headers, params={"limit": 101}),
        "ERR_INVALID_PAGINATION",
        400,
    )
    validate_error(
        api.list_organizations(admin_headers, params={"offset": -1}),
        "ERR_INVALID_PAGINATION",
        400,
    )

    rows, meta = validate_paginated(
        api.list_organizations(admin_headers, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == organization["id"]
