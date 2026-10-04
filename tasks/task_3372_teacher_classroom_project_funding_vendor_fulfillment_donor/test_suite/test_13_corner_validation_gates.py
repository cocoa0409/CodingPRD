"""Validation corners, part one: optimistic concurrency, segregation of
duties, the project-creation gates, and the submit-time fiscal checks."""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_cents,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    make_teacher_headers,
    reviewer_headers,
)


def test_occ_conflict_on_a_stale_project_version(api):
    """A second add carrying the pre-first-add version is stale and rejected.

    PRD: "**Adding an item to a project** requires `expected_project_version` carrying the client's last observed `version` of the project. If the project's current `version` has advanced since the client last read it — for example because another item add or a submit changed the item set and totals — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    Design: Corner/validations/occ_conflict_on_stale_project_version
    """
    world = fixtures.seed_school_teacher(api)
    vendor_world = fixtures.seed_vendor_with_items(api)
    world.update(vendor_world)
    pencil = fixtures.create_catalog_item(api, world["vendor"]["id"], **f.pencil_item_spec())

    project = fixtures.create_project(api, world["teacher"])
    stale_version = project["version"]  # the version observed at creation

    # The first add succeeds and advances the project's version.
    first = fixtures.add_item(api, project["id"], world["teacher"], world["items"][0]["id"], 4)
    assert first["quantity"] == 4

    # The second add replays the creation-time version: stale.
    res = api.add_project_item(
        project["id"],
        f.add_item_payload(pencil["id"], 1, stale_version),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)

    rows = fixtures.project_items_for(api, project["id"])
    assert len(rows) == 1, "the stale add was rejected before any write"


def test_vet_by_the_screening_reviewer_violates_segregation(api):
    """The reviewer who screened a project may not vet it; a different
    reviewer vets the same payload successfully.

    PRD: "Segregation of duties binds the vet stage: for all three vetting outcomes, the acting reviewer's `X-User-ID` must differ from the project's `screened_by_id` — the person who screened a project may not vet it — otherwise the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/validations/vet_by_screening_reviewer_violates_segregation
    """
    world = fixtures.setup_draft_project(api)
    project_id = world["project"]["id"]
    fixtures.submit_project(api, project_id, world["teacher"])
    fixtures.review_project(api, project_id, "SCREEN", "APPROVE", "rev-ana")

    res = api.review_project(
        project_id, f.review_payload("VET", "APPROVE"), reviewer_headers("rev-ana")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    vetted = validate_success(
        api.review_project(
            project_id, f.review_payload("VET", "APPROVE"), reviewer_headers("rev-ben")
        ),
        200,
    )
    assert vetted["status"] == "FUNDING"
    assert vetted["screened_by_id"] == "rev-ana"
    assert vetted["vetted_by_id"] == "rev-ben"


def test_second_live_project_returns_active_project_exists(api):
    """A teacher with a project anywhere in the live pipeline cannot open
    another one.

    PRD: "Creation is gated: the teacher must be `VERIFIED` (not `PENDING_VERIFICATION`, not `SUSPENDED`), must not already have another project in `DRAFT`, `IN_REVIEW`, `VETTING`, `RETURNED`, `FUNDING`, or `FUNDED` (`ERR_ACTIVE_PROJECT_EXISTS`)"
    Design: Corner/validations/second_live_project_returns_active_project_exists
    """
    world = fixtures.seed_school_teacher(api)
    teacher = world["teacher"]
    fixtures.create_project(api, teacher)

    res = api.create_project(
        f.project_payload(title="Second Project", subject="MATH", grade_band="K_2",
                          funding_window_days=45),
        make_teacher_headers(teacher["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ACTIVE_PROJECT_EXISTS, 409)
    assert len(fixtures.projects_for_teacher(api, teacher["id"])) == 1


def test_funding_window_below_minimum_returns_invalid_request(api):
    """funding_window_days 10 is below the declared range: a request-shape
    failure before any gate runs.

    PRD: "**Request well-formedness** — required fields present, enum values valid, scalar ranges respected: `funding_window_days` between 30 and 180 inclusive, `quantity` at least 1, `amount_cents` at least 1, `match_ratio` greater than 0 and at most 2.0, poverty and ELL percentages between 0.0 and 100.0 inclusive, and minimum lengths on the thank-you note and impact report at submission. Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
    Design: Corner/validations/funding_window_below_minimum_returns_invalid_request
    """
    world = fixtures.seed_school_teacher(api)
    teacher = world["teacher"]

    res = api.create_project(
        f.project_payload(title="Too Short", funding_window_days=10),
        make_teacher_headers(teacher["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert fixtures.projects_for_teacher(api, teacher["id"]) == []


def test_suspended_teacher_write_returns_teacher_suspended(api):
    """After the fraud cascade suspends the teacher (and cancels the pipeline,
    so the active-project gate no longer applies), a fresh create reports the
    suspension.

    PRD: "The full employment state set is `PENDING_VERIFICATION`, `VERIFIED`, and `SUSPENDED`; a `SUSPENDED` teacher is barred from every teacher-initiated write — creating a project, adding an item, submitting a project, or submitting a thank-you package — with `ERR_TEACHER_SUSPENDED`, and this check is evaluated after the pending-verification check."
    Design: Corner/validations/suspended_teacher_write_returns_teacher_suspended
    """
    world = fixtures.setup_suspended_teacher(api)
    teacher = world["teacher"]
    assert teacher["employment_status"] == "SUSPENDED"
    assert world["project"]["status"] == "CANCELLED", "the pipeline was cancelled"

    res = api.create_project(
        f.project_payload(title="Fresh Start", subject="MATH", grade_band="K_2",
                          funding_window_days=45),
        make_teacher_headers(teacher["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TEACHER_SUSPENDED, 409)
    # No new project was created: only the cancelled one remains.
    assert len(fixtures.projects_for_teacher(api, teacher["id"])) == 1


def test_fulfilled_project_with_pending_package_blocks_new_project(api):
    """The thank-you gate: while a FULFILLED project's package is PENDING the
    teacher cannot open another project.

    PRD: "When every purchase order of the project has reached `DELIVERED`, the project bubbles up from `FUNDED` to `FULFILLED` automatically, and from that moment the thank-you gate applies to the teacher: while any `PENDING` thank-you package sits on a `FULFILLED` project of theirs, creating a new project is rejected with `ERR_THANK_YOU_OUTSTANDING`."
    Design: Corner/validations/fulfilled_project_with_pending_package_blocks_new_project
    """
    world = fixtures.setup_fulfilled_project(api)
    assert world["project"]["status"] == "FULFILLED"
    teacher = world["teacher"]

    res = api.create_project(
        f.project_payload(title="Second Project", subject="MATH", grade_band="K_2",
                          funding_window_days=45),
        make_teacher_headers(teacher["id"]),
    )
    validate_error(res, ApiErrorId.ERR_THANK_YOU_OUTSTANDING, 409)
    assert len(fixtures.projects_for_teacher(api, teacher["id"])) == 1


def test_add_discontinued_item_returns_catalog_item_unavailable(api):
    """A DISCONTINUED item that is not on the project fails the referential
    availability rule.

    PRD: "A `DISCONTINUED` item can no longer be added to any project — the add fails with `ERR_CATALOG_ITEM_UNAVAILABLE`."
    Design: Corner/validations/add_discontinued_item_returns_catalog_item_unavailable
    """
    world = fixtures.seed_school_teacher(api)
    vendor_world = fixtures.seed_vendor_with_items(api)
    world.update(vendor_world)
    item = world["items"][0]
    validate_success(
        api.patch_catalog_item(world["vendor"]["id"], item["id"], {"status": "DISCONTINUED"},
                               ADMIN_HEADERS),
        200,
    )
    project = fixtures.create_project(api, world["teacher"])

    res = api.add_project_item(
        project["id"],
        f.add_item_payload(item["id"], 2, project["version"]),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CATALOG_ITEM_UNAVAILABLE, 422)
    assert fixtures.project_items_for(api, project["id"]) == []


def test_submit_with_no_items_returns_no_items(api):
    """The empty-project check runs before the goal-range check.

    PRD: "Two fiscal checks then run in a pinned order: the project must contain at least one item (`ERR_NO_ITEMS`, checked first, so an empty project never reports the goal-range error), and the computed goal must lie between 10000 and 200000 cents inclusive (`ERR_GOAL_OUT_OF_RANGE`)."
    Design: Corner/validations/submit_with_no_items_returns_no_items
    """
    world = fixtures.seed_school_teacher(api)
    project = fixtures.create_project(api, world["teacher"])

    res = api.submit_project(
        project["id"], f.submit_payload(project["version"]),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NO_ITEMS, 422)
    assert fixtures.read_project(api, project["id"])["status"] == "DRAFT"


def test_submit_with_a_tiny_goal_returns_goal_out_of_range(api):
    """One pencil box plus its shipping quote lands below the 10000-cent
    floor, so the computed goal rejects the submit.

    PRD: "Two fiscal checks then run in a pinned order: the project must contain at least one item (`ERR_NO_ITEMS`, checked first, so an empty project never reports the goal-range error), and the computed goal must lie between 10000 and 200000 cents inclusive (`ERR_GOAL_OUT_OF_RANGE`)."
    Design: Corner/validations/submit_with_tiny_goal_returns_goal_out_of_range
    """
    world = fixtures.seed_school_teacher(api)
    vendor_world = fixtures.seed_vendor_with_items(api, item_specs=[(f.pencil_item_spec(), 1)])
    world.update(vendor_world)

    project = fixtures.create_project(api, world["teacher"])
    fixtures.add_item(api, project["id"], world["teacher"], world["items"][0]["id"], 1)

    provisional = fixtures.read_project(api, project["id"])
    # 300 + (tier 1 base 299 + ceil(4/16)=1 lb x 120) = 719.
    assert_cents(provisional["provisional_total_cents"], 719, "provisional_total_cents")

    res = api.submit_project(
        project["id"],
        f.submit_payload(fixtures.current_project_version(api, project["id"])),
        make_teacher_headers(world["teacher"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_GOAL_OUT_OF_RANGE, 422)

    project_after = fixtures.read_project(api, project["id"])
    assert project_after["status"] == "DRAFT"
    assert project_after["goal_cents"] is None
