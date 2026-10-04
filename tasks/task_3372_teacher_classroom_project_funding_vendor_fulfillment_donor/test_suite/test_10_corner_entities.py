"""Entity-surface corners: creation-time computation, defaults, system-sourced
fields, not-found envelopes, append-only shape, and list pagination."""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_catalog_item,
    assert_cents,
    assert_one_dp,
    assert_school,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import make_teacher_headers


def test_school_create_computes_both_equity_score_variants(api):
    """School creation computes and returns both equity score faces.

    PRD: "Every school carries two equity scores, computed at creation and reflected on every read, which deliberately diverge."
    PRD: "The **banded** score, `equity_score_banded`, is a step function of `poverty_pct` alone: at least 90.0 scores 100; at least 75.0 (but below 90.0) scores 80; at least 50.0 (but below 75.0) scores 50; below 50.0 scores 10."
    PRD: "The **weighted** score, `equity_score_weighted`, is seven-tenths of `poverty_pct` plus three-tenths of `ell_pct`, rounded half up to one decimal place"
    Design: Corner/entities/school_create_computes_both_equity_score_variants
    """
    fixtures.set_clock(api)
    res = api.create_school(
        f.school_payload(poverty_pct=80.0, ell_pct=90.0), ADMIN_HEADERS
    )
    assert res.status_code == 201
    body = res.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    school = body["data"]
    assert_school(school)
    assert school["equity_score_banded"] == 80, "80.0 poverty lands in the >= 75 band"
    assert_one_dp(school["equity_score_weighted"], 83.0, "weighted")  # 0.7*80 + 0.3*90
    assert school["version"] == 1


def test_catalog_item_defaults_fragile_false_and_cap_null(api):
    """The two optional item fields default server-side when omitted.

    PRD: "Two optional fields complete the item: `fragile` (default false) marks items needing fragile handling, and `max_quantity_per_project` (default null) caps how many units one project may request, where null means 99. A new item's `status` is `ACTIVE`."
    Design: Corner/entities/catalog_item_defaults_fragile_false_and_cap_null
    """
    fixtures.set_clock(api)
    vendor = fixtures.create_vendor(api)

    payload = f.book_item_spec()
    assert "fragile" not in payload and "max_quantity_per_project" not in payload
    res = api.create_catalog_item(vendor["id"], payload, ADMIN_HEADERS)
    assert res.status_code == 201

    item = res.json()["data"]
    assert_catalog_item(item)
    assert item["fragile"] is False
    assert item["max_quantity_per_project"] is None
    assert item["status"] == "ACTIVE"
    assert item["version"] == 1


def test_project_create_ignores_a_smuggled_status_field(api):
    """status, teacher_id and school_id are system-sourced: a create body
    carrying status=FUNDING still yields a DRAFT project owned and sited by
    the acting teacher.

    PRD: "The project's `teacher_id` is taken from the acting teacher's `X-User-ID`, and its `school_id` is denormalized from the teacher's employing school at creation and never changes afterward. A new project starts in `DRAFT` with `funded_cents` at 0 and its provisional totals null until items exist."
    Design: Corner/entities/project_create_with_supplied_status_field_input_ignored
    """
    world = fixtures.seed_school_teacher(api)
    teacher = world["teacher"]

    payload = f.project_payload()
    payload["status"] = "FUNDING"  # smuggled system field: must not take effect
    res = api.create_project(payload, make_teacher_headers(teacher["id"]))
    assert res.status_code == 201

    project = res.json()["data"]
    assert project["status"] == "DRAFT", "the smuggled FUNDING was ignored"
    assert project["teacher_id"] == teacher["id"]
    assert project["school_id"] == world["school"]["id"]
    assert_cents(project["funded_cents"], 0, "funded_cents")
    assert project["version"] == 1


def test_project_get_with_unknown_id_returns_not_found(api):
    """A syntactically valid but unallocated project id is a 404 in the error
    envelope.

    PRD: "**Existence** — path identifiers and body-referenced ids exist. Nested paths are validated strictly left to right — the project before the item, the fund before the allocation — and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first missing identifier."
    Design: Corner/entities/project_get_unknown_id_returns_not_found
    """
    fixtures.set_clock(api)
    res = api.get_project(NON_EXISTENT_UUID, ADMIN_HEADERS)
    error = validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)
    assert res.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]


def test_thank_you_package_carries_no_version_or_updated_at(api):
    """The thank-you package is the one resource without the full common
    field quartet.

    PRD: "Every primary resource carries a standard set of system-managed fields:"
    PRD: "The one exception is the ThankYouPackage: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it."
    Design: Corner/entities/thank_you_package_has_no_version_field
    """
    world = fixtures.setup_funded_project(api)
    packages, meta = validate_paginated(
        api.get_thank_you_package(world["project"]["id"], ADMIN_HEADERS)
    )
    assert len(packages) == 1
    package = packages[0]
    assert package["status"] == "PENDING"
    assert package["id"]
    assert package["created_at"]
    assert package["submitted_at"] is None
    assert "version" not in package, "append-only: no version key"
    assert "updated_at" not in package, "append-only: no updated_at key"


def test_teachers_list_paginates_with_total_count_and_has_more(api):
    """Limit and offset page through the filtered set; the meta block reports
    the page served and the size of the whole collection.

    PRD: "`limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items and defaults to 0."
    PRD: "List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    Design: Corner/entities/teachers_list_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api)
    school = fixtures.create_school(api)
    for _ in range(3):
        fixtures.create_teacher(api, school["id"])

    page1, meta1 = validate_paginated(
        api.list_teachers(ADMIN_HEADERS, {"school_id": school["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_teachers(ADMIN_HEADERS, {"school_id": school["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    # Defaults: limit 10, offset 0 — all three rows come back in one page.
    page_all, meta_all = validate_paginated(
        api.list_teachers(ADMIN_HEADERS, {"school_id": school["id"]})
    )
    assert len(page_all) == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert meta_all["has_more"] is False
