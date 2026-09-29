"""Projects, the derived buyout ledger, and MaterialPackage registration.

Covers project creation and its zeroed roll-ups, package retrieval and listing,
required-field / enum / body-FK refusals, the submittal-review default, the
server-minted baselines, scope-code uniqueness scoping, and the PATCH rebaseline.
"""
import re

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_material_package,
    assert_project,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_material_package_payload,
    create_project_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]

# PRD §2.4: an ISO 8601 UTC instant with exactly three fractional digits.
_THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)

# The literal project the design instances open, money as JSON numbers (PRD §2.6).
_PROJECT_LITERALS = {
    "name": "Riverside Medical Tower",
    "contract_number": "GC-2996-A",
    "owner_name": "Riverside Health System",
    "schedule_data_date": "2026-08-01T00:00:00.000Z",
    "escalation_contingency_budget": 500000.00,
}

# The literal steel package: 21 + 70 + 20 = 111 lead days off 2027-03-01.
_STEEL_PACKAGE_LITERALS = {
    "scope_code": "STRUCT-STEEL-01",
    "description": "Structural steel frame package",
    "commodity_index_code": "PPI_STEEL_MILL",
    "estimated_cost": 1200000.00,
    "required_onsite_date": "2027-03-01T00:00:00.000Z",
    "fabrication_duration_days": 70,
    "delivery_transit_days": 20,
    "submittal_review_days": 21,
}


def _open_literal_project(**overrides) -> dict:
    """Open the design instances' literal project and return the created row."""
    payload = create_project_payload(**{**_PROJECT_LITERALS, **overrides})
    return validate_success(
        api_client.create_project(payload, BUYOUT_MANAGER), 201
    )


def _register_literal_package(project_id, *, drop=(), **overrides) -> dict:
    """Register the literal steel package, dropping any field named in `drop`."""
    payload = create_material_package_payload(
        project_id=project_id, **{**_STEEL_PACKAGE_LITERALS, **overrides}
    )
    for field in drop:
        payload.pop(field, None)
    return validate_success(
        api_client.create_material_package(payload, BUYOUT_MANAGER), 201
    )


def _package_create_response(project_id, *, drop=(), **overrides):
    """The raw create response, for the refusal instances that inspect error ids."""
    payload = create_material_package_payload(
        project_id=project_id, **{**_STEEL_PACKAGE_LITERALS, **overrides}
    )
    for field in drop:
        payload.pop(field, None)
    return api_client.create_material_package(payload, BUYOUT_MANAGER)


# ---------------------------------------------------------------------------
# Queue B: entities / creation_project_returns_201_with_a_zeroed_derived_ledger
# ---------------------------------------------------------------------------

def test_projects_creation_returns_201_with_a_zeroed_derived_ledger():
    """A freshly opened project returns 201 with every roll-up 0.00 except the
    contingency remaining, which is the whole budget just supplied.

    PRD §3.1: "A freshly opened project has `version` 1 and reports every money
    roll-up as 0.00, with the single exception of `escalation_contingency_remaining`,
    which equals the budget just supplied."
    PRD §3.1: "`buyout_variance` is the full-programme figure: `estimated_total_cost`
    across every package, less `committed_total_cost`, rounded half up to 2 decimal
    places."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/creation_project_returns_201_with_a_zeroed_derived_ledger
    """
    response = api_client.create_project(
        create_project_payload(**_PROJECT_LITERALS), BUYOUT_MANAGER
    )
    project = validate_success(response, 201)
    assert_project(project)

    assert project["name"] == "Riverside Medical Tower"
    assert project["contract_number"] == "GC-2996-A"
    assert project["owner_name"] == "Riverside Health System"
    assert project["escalation_contingency_budget"] == 500000.00
    assert project["estimated_total_cost"] == 0.00
    assert project["committed_total_cost"] == 0.00
    assert project["buyout_variance"] == 0.00
    assert project["bought_out_variance"] == 0.00
    assert project["escalation_contingency_committed"] == 0.00
    assert project["escalation_contingency_remaining"] == 500000.00
    assert project["change_order_recovered_amount"] == 0.00
    assert project["version"] == 1

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


# ---------------------------------------------------------------------------
# Queue B: entities / retrieval_material_package_returns_stored_and_clock_derived_fields
# ---------------------------------------------------------------------------

def test_projects_retrieval_package_returns_stored_and_clock_derived_fields():
    """A GET of an untouched package re-derives its whole release-for-fabrication
    schedule against the 2026-08-01 startup clock.

    PRD §3.1: "`lead_time_days` is the sum of `submittal_review_days`,
    `fabrication_duration_days` and `delivery_transit_days`."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."
    PRD §3.1: "`float_days` measures how much room is left before the release date
    arrives: it is the number of whole days from the current logical clock forward to
    `release_for_fabrication_date`, taken toward negative infinity"
    PRD §3.1: "`rff_risk_band` reads `CRITICAL` when `float_days` is zero or less,
    `AT_RISK` when it is between 1 and 14 inclusive, and `ON_TRACK` when it is 15 or
    more."
    PRD §3.1: "it is true when `fabrication_duration_days` plus
    `delivery_transit_days` alone reaches at least 90 days"
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."
    PRD §2.5: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`"

    Design: Corner/entities/retrieval_material_package_returns_stored_and_clock_derived_fields
    """
    project = _open_literal_project()
    created = _register_literal_package(project["id"])

    package = validate_success(
        api_client.get_material_package(created["id"], BUYOUT_MANAGER), 200
    )
    assert_material_package(package)

    assert package["lead_time_days"] == 111
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-11-10T00:00:00.000Z"
    )
    assert package["float_days"] == 101
    assert package["rff_risk_band"] == "ON_TRACK"
    assert package["is_long_lead"] is True
    assert package["open_quote_count"] == 0
    assert package["status"] == "IDENTIFIED"


# ---------------------------------------------------------------------------
# Queue B: entities / listing_material_packages_paginates_with_total_count_and_has_more
# ---------------------------------------------------------------------------

def test_projects_listing_packages_paginates_with_total_count_and_has_more():
    """With three packages on one project, total_count reports the filtered
    population before pagination and has_more flips off on the last page.

    PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10 when
    omitted, may not be lower than 1, and may not exceed 100."
    PRD §2.3: "`total_count` counts every row matching the request's filters before
    pagination is applied and `has_more` states whether any matching row remains
    beyond the current page."
    PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by
    their creation timestamp, `created_at`, ascending — oldest first."
    PRD §2.3: "a project's packages by filtering on `project_id`"

    Design: Corner/entities/listing_material_packages_paginates_with_total_count_and_has_more
    """
    project = _open_literal_project()
    first = _register_literal_package(project["id"])
    second = _register_literal_package(
        project["id"],
        drop=("submittal_review_days",),
        scope_code="STRUCT-STEEL-02",
        description="Miscellaneous metals package",
        estimated_cost=900000.00,
        fabrication_duration_days=60,
        delivery_transit_days=29,
    )
    third = _register_literal_package(
        project["id"],
        drop=("submittal_review_days",),
        scope_code="ELEC-FEEDER-01",
        description="Electrical feeder conductor package",
        estimated_cost=400000.00,
        fabrication_duration_days=30,
        delivery_transit_days=10,
    )

    page_one, meta_one = validate_paginated(
        api_client.list_material_packages(
            BUYOUT_MANAGER,
            params={"project_id": project["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2, f"limit 2 must return exactly 2 rows, got {len(page_one)}"
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert [row["id"] for row in page_one] == [first["id"], second["id"]]

    page_two, meta_two = validate_paginated(
        api_client.list_material_packages(
            BUYOUT_MANAGER,
            params={"project_id": project["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1, f"offset 2 must return the last row only, got {len(page_two)}"
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2
    assert page_two[0]["id"] == third["id"]


# ---------------------------------------------------------------------------
# Queue B: entities / required_fields_material_package_create_missing_estimated_cost_rejected
# ---------------------------------------------------------------------------

def test_projects_package_create_missing_estimated_cost_is_rejected():
    """estimated_cost carries no default, so omitting it is a shape failure and no
    package row is written.

    PRD §2.9: "On every write endpoint, all required fields are present ... All of
    these are `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "plus a free-text `description`, an `estimated_cost` greater than zero
    with at most 2 decimal places, and a `commodity_index_code` naming the published
    price index this commodity escalates against."
    PRD §3.1: "`estimated_total_cost` is the sum of `estimated_cost` over every scope
    package belonging to the project"

    Design: Corner/entities/required_fields_material_package_create_missing_estimated_cost_rejected
    """
    project = _open_literal_project()

    response = _package_create_response(project["id"], drop=("estimated_cost",))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(
        api_client.list_material_packages(
            BUYOUT_MANAGER, params={"project_id": project["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused create must not write a package row"
    assert rows == []

    refreshed = validate_success(
        api_client.get_project(project["id"], BUYOUT_MANAGER), 200
    )
    assert refreshed["estimated_total_cost"] == 0.00


# ---------------------------------------------------------------------------
# Queue B: entities / defaults_submittal_review_days_defaults_to_twenty_one
# ---------------------------------------------------------------------------

def test_projects_submittal_review_days_defaults_to_twenty_one():
    """Omitting submittal_review_days applies the declared default 21, which enters
    lead_time_days but never the long-lead test.

    PRD §3.1: "a `submittal_review_days` submittal-and-review duration between 0 and
    180 calendar days inclusive that defaults to 21 when omitted."
    PRD §3.1: "`lead_time_days` is the sum of `submittal_review_days`,
    `fabrication_duration_days` and `delivery_transit_days`."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."
    PRD §3.1: "it is true when `fabrication_duration_days` plus
    `delivery_transit_days` alone reaches at least 90 days — three months of pure
    market lead time — and it excludes `submittal_review_days` entirely, even though
    that duration *is* included in `lead_time_days`."

    Design: Corner/entities/defaults_submittal_review_days_defaults_to_twenty_one
    """
    project = _open_literal_project()

    package = _register_literal_package(
        project["id"],
        drop=("submittal_review_days",),
        scope_code="STRUCT-STEEL-02",
        description="Miscellaneous metals package",
        estimated_cost=900000.00,
        fabrication_duration_days=60,
        delivery_transit_days=29,
    )
    assert_material_package(package)

    assert package["submittal_review_days"] == 21
    assert package["lead_time_days"] == 110
    assert_instant_equals(
        package["release_for_fabrication_date"], "2026-11-11T00:00:00.000Z"
    )
    assert package["float_days"] == 102
    assert package["rff_risk_band"] == "ON_TRACK"
    assert package["is_long_lead"] is False, "60 + 29 == 89 is below the 90-day threshold"


# ---------------------------------------------------------------------------
# Queue B: entities / system_fields_package_baselines_and_status_are_server_minted
# ---------------------------------------------------------------------------

def test_projects_package_baselines_and_status_are_server_minted():
    """The server seeds both baselines from the submitted values, sets status
    IDENTIFIED, and mints the identity and audit fields itself.

    PRD §3.1: "At creation the server also snapshots `baseline_estimated_cost` from
    the supplied `estimated_cost` and `baseline_fabrication_duration_days` from the
    supplied `fabrication_duration_days`"
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."
    PRD §2.4: "Every resource the API mints carries a server-generated `id`, formatted
    as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601
    UTC instant with exactly three fractional digits (for example,
    `2026-08-01T00:00:00.000Z`). Clients never supply an `id`."
    PRD §2.4: "additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on
    every mutation of the row, and `version`, an integer that starts at 1 when the row
    is created and increments by exactly 1 on each mutation."

    Design: Corner/entities/system_fields_package_baselines_and_status_are_server_minted
    """
    project = _open_literal_project()
    package = _register_literal_package(project["id"])
    assert_material_package(package)

    assert package["baseline_estimated_cost"] == 1200000.00
    assert package["estimated_cost"] == 1200000.00
    assert package["baseline_fabrication_duration_days"] == 70
    assert package["fabrication_duration_days"] == 70
    assert package["status"] == "IDENTIFIED"
    assert package["version"] == 1

    assert is_valid_uuid(package["id"]), f"id must be a bare UUID, got {package['id']!r}"
    assert "_" not in package["id"], "the id carries no type prefix"
    for field in ("created_at", "updated_at"):
        assert _THREE_FRACTIONAL_DIGITS.match(package[field]), (
            f"{field} must be an ISO 8601 UTC instant with exactly three fractional "
            f"digits, got {package[field]!r}"
        )


# ---------------------------------------------------------------------------
# Queue B: entities / type_constraints_undeclared_commodity_index_code_rejected
# ---------------------------------------------------------------------------

def test_projects_undeclared_commodity_index_code_is_rejected():
    """commodity_index_code is an enum, so an undeclared member is refused rather
    than stored verbatim.

    PRD §2.9: "each enum field carries a declared member ... All of these are
    `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "That code is one of `PPI_STEEL_MILL`, `PPI_COPPER_WIRE`, `PPI_LUMBER`,
    `PPI_CEMENT` or `PPI_SWITCHGEAR`."

    Design: Corner/entities/type_constraints_undeclared_commodity_index_code_rejected
    """
    project = _open_literal_project()

    response = _package_create_response(
        project["id"],
        drop=("submittal_review_days",),
        commodity_index_code="PPI_UNOBTANIUM",
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(
        api_client.list_material_packages(
            BUYOUT_MANAGER, params={"project_id": project["id"]}
        )
    )
    assert meta["total_count"] == 0, "an undeclared enum member must not be stored"
    assert rows == []


# ---------------------------------------------------------------------------
# Queue B: entities / parent_relationships_material_package_with_unknown_project_id_not_found
# ---------------------------------------------------------------------------

def test_projects_package_with_unknown_project_id_is_not_found():
    """project_id is a body foreign key, so an unknown parent is attributed to the
    project rather than to the package.

    PRD §2.8: "The same mapping applies to body foreign keys. A `project_id` that
    names no project is `ERR_PROJECT_NOT_FOUND`"
    PRD §2.9: "**Body foreign-key existence.** Every foreign key in the body resolves,
    per §2.8 (404)."

    Design: Corner/entities/parent_relationships_material_package_with_unknown_project_id_not_found
    """
    response = _package_create_response(
        "00000000-0000-4000-8000-000000000999", drop=("submittal_review_days",)
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(api_client.list_material_packages(BUYOUT_MANAGER))
    assert meta["total_count"] == 0, "no MaterialPackage row may exist"
    assert rows == []


# ---------------------------------------------------------------------------
# Queue B: validations / violation_error_duplicate_scope_code_on_the_same_project
# ---------------------------------------------------------------------------

def test_projects_duplicate_scope_code_on_the_same_project_is_refused():
    """Re-using a scope code inside one project is refused and nothing is written,
    even though every other field of the second attempt differs.

    PRD §3.1: "The package carries a `scope_code` of 1 to 40 characters that must be
    unique within its project, compared case-sensitively — a repeat is
    `ERR_DUPLICATE_SCOPE_CODE`"
    PRD §2.9: "A package's `scope_code` is unique within its project
    (`ERR_DUPLICATE_SCOPE_CODE`, 409)"
    PRD §3.1: "`estimated_total_cost` is the sum of `estimated_cost` over every scope
    package belonging to the project"

    Design: Corner/validations/violation_error_duplicate_scope_code_on_the_same_project
    """
    project = _open_literal_project()
    first = _register_literal_package(project["id"])

    response = _package_create_response(
        project["id"],
        description="Second attempt at the same scope code",
        estimated_cost=777000.00,
        fabrication_duration_days=40,
        delivery_transit_days=15,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SCOPE_CODE.value, 409)

    rows, meta = validate_paginated(
        api_client.list_material_packages(
            BUYOUT_MANAGER, params={"project_id": project["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]

    survivor = validate_success(
        api_client.get_material_package(first["id"], BUYOUT_MANAGER), 200
    )
    assert survivor["estimated_cost"] == 1200000.00, "the refusal must not overwrite the row"
    assert survivor["fabrication_duration_days"] == 70

    refreshed = validate_success(
        api_client.get_project(project["id"], BUYOUT_MANAGER), 200
    )
    assert refreshed["estimated_total_cost"] == 1200000.00


# ---------------------------------------------------------------------------
# Queue B: validations / satisfaction_pass_the_same_scope_code_under_another_project_is_accepted
# ---------------------------------------------------------------------------

def test_projects_same_scope_code_under_another_project_is_accepted():
    """The uniqueness constraint is per-parent, so the same scope code is legal on a
    second project and each project's roll-up counts only its own package.

    PRD §3.1: "The package carries a `scope_code` of 1 to 40 characters that must be
    unique within its project, compared case-sensitively"
    PRD §3.1: "`estimated_total_cost` is the sum of `estimated_cost` over every scope
    package belonging to the project — every package, with no status filter at all"

    Design: Corner/validations/satisfaction_pass_the_same_scope_code_under_another_project_is_accepted
    """
    first_project = _open_literal_project()
    _register_literal_package(first_project["id"])

    second_project = _open_literal_project(
        name="Lakeside Clinic Addition",
        contract_number="GC-2996-B",
        escalation_contingency_budget=200000.00,
    )
    second_package = _register_literal_package(
        second_project["id"],
        description="Steel frame for the clinic addition",
        estimated_cost=450000.00,
    )
    assert_material_package(second_package)

    assert second_package["scope_code"] == "STRUCT-STEEL-01"
    assert second_package["project_id"] == second_project["id"]

    first_read = validate_success(
        api_client.get_project(first_project["id"], BUYOUT_MANAGER), 200
    )
    second_read = validate_success(
        api_client.get_project(second_project["id"], BUYOUT_MANAGER), 200
    )
    assert first_read["estimated_total_cost"] == 1200000.00
    assert second_read["estimated_total_cost"] == 450000.00


# ---------------------------------------------------------------------------
# Queue B: endpoints / standard_crud_patch_reshapes_the_schedule_and_rebaselines_the_package
# ---------------------------------------------------------------------------

def test_projects_patch_reshapes_the_schedule_and_rebaselines_the_package():
    """A partial PATCH of the fabrication duration alone re-runs the whole schedule
    derivation and rebaselines the duration snapshot, leaving the untouched fields as
    they stand.

    PRD §3.1: "a `BuyoutManager` may revise a package's `required_onsite_date`,
    `fabrication_duration_days`, `delivery_transit_days`, `submittal_review_days` or
    `estimated_cost` — each optional, with the omitted ones left as they stand."
    PRD §3.1: "Such a revision re-runs the whole release-for-fabrication derivation
    over the new durations, and it also rebaselines `baseline_estimated_cost` and
    `baseline_fabrication_duration_days` to the revised values"
    PRD §3.1: "`lead_time_days` is the sum of `submittal_review_days`,
    `fabrication_duration_days` and `delivery_transit_days`."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."
    PRD §2.4: "`version`, an integer that starts at 1 when the row is created and
    increments by exactly 1 on each mutation."

    Design: Corner/endpoints/standard_crud_patch_reshapes_the_schedule_and_rebaselines_the_package
    """
    project = _open_literal_project()
    package = _register_literal_package(project["id"])
    assert package["version"] == 1

    patched = validate_success(
        api_client.update_material_package(
            package["id"], {"fabrication_duration_days": 100}, BUYOUT_MANAGER
        ),
        200,
    )
    assert_material_package(patched)

    assert patched["fabrication_duration_days"] == 100
    assert patched["delivery_transit_days"] == 20
    assert patched["submittal_review_days"] == 21
    assert patched["lead_time_days"] == 141
    assert_instant_equals(
        patched["release_for_fabrication_date"], "2026-10-11T00:00:00.000Z"
    )
    assert patched["float_days"] == 71
    assert patched["rff_risk_band"] == "ON_TRACK"
    assert patched["is_long_lead"] is True
    assert patched["baseline_fabrication_duration_days"] == 100, "the duration is rebaselined"
    assert patched["baseline_estimated_cost"] == 1200000.00
    assert patched["estimated_cost"] == 1200000.00
    assert patched["status"] == "IDENTIFIED"
    assert patched["version"] == 2

    refreshed = validate_success(
        api_client.get_project(project["id"], BUYOUT_MANAGER), 200
    )
    assert refreshed["estimated_total_cost"] == 1200000.00
