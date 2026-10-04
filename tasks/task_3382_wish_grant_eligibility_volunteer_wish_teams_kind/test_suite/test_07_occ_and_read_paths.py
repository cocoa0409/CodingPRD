"""Optimistic concurrency on wish-scoped writes, plus list-endpoint behavior:
pagination defaults, reverse filtering, and sub-resource listing.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_pagination_meta,
    create_approved_wish,
    create_chapter,
    create_draft_plan,
    create_fulfillment_plan_payload,
    create_donation_offer,
    add_line_item,
    create_volunteer_batch,
    create_volunteer_pair,
    create_wish_team,
    create_wish_team_payload,
    conclude_visit_completed,
    get_fulfillment_plan,
    get_wish,
    get_wish_team,
    get_wish_version,
    schedule_visit,
    set_clock,
    setup_planning_wish,
    validate_error,
    validate_paginated,
    validate_success,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]


def test_occ_team_create_stale_version_rejected():
    """PRD section 2.7: "Two write operations are guarded by optimistic
    concurrency control on the wish they target: creating a determination
    team, and creating a fulfillment plan. Both require the request to carry
    `expected_wish_version`, a non-optional field holding the wish's `version`
    as the client last observed it. If the wish's current `version` differs
    from the submitted value — because another write has advanced the wish
    since the client read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_team_create_stale_version_rejected
    """
    set_clock()
    chapter = create_chapter(territory_zip_prefixes=["900"])
    lead, second = create_volunteer_pair(chapter["id"])
    ctx = create_approved_wish(chapter=chapter)
    wish = ctx["wish"]
    assert wish["version"] == 1

    team1 = create_wish_team(wish["id"], lead["id"], second["id"],
                             expected_wish_version=1)
    assert team1["status"] == "ACTIVE"

    stale = api_client.create_wish_team(
        create_wish_team_payload(wish["id"], second["id"], lead["id"], 1),
        WISH_COORDINATOR)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_wish_version(wish["id"])
    assert fresh == 2, f"first team creation advanced the wish to version 2, got {fresh}"
    team2 = create_wish_team(wish["id"], second["id"], lead["id"],
                             expected_wish_version=fresh)
    assert team2["status"] == "ACTIVE"
    assert get_wish_team(team1["id"])["status"] == "DISBANDED"


def test_occ_plan_create_stale_version_rejected():
    """PRD section 2.7: "If the wish's current `version` differs from the
    submitted value — because another write has advanced the wish since the
    client read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412). Replacing a determination team and superseding a draft plan
    are legitimate product operations, so a client that re-reads the wish and
    resubmits with the fresh version succeeds"

    Design: Corner/complexity_layers/occ_plan_create_stale_version_rejected
    """
    set_clock()
    chapter = create_chapter(territory_zip_prefixes=["900"])
    lead, second = create_volunteer_pair(chapter["id"])
    ctx = create_approved_wish(chapter=chapter)
    wish = ctx["wish"]
    team = create_wish_team(wish["id"], lead["id"], second["id"])
    visit = schedule_visit(team["id"], lead["id"])
    conclude_visit_completed(visit["id"], lead["id"])

    observed = get_wish_version(wish["id"])
    plan1 = create_draft_plan(wish["id"], 100000, expected_wish_version=observed)
    assert plan1["status"] == "DRAFT"

    stale = api_client.create_fulfillment_plan(
        create_fulfillment_plan_payload(wish["id"], observed, 200000),
        WISH_COORDINATOR)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_wish_version(wish["id"])
    plan2 = create_draft_plan(wish["id"], 200000, expected_wish_version=fresh)
    assert plan2["status"] == "DRAFT"
    assert get_fulfillment_plan(plan1["id"])["status"] == "SUPERSEDED", (
        "the fresh create legitimately supersedes the prior DRAFT plan"
    )
    assert get_wish(wish["id"])["status"] == "PLANNING"


def test_volunteer_list_pagination_defaults():
    """PRD section 2.3: "`limit` defaults to 10, with a minimum of 1 and a
    maximum of 100. `offset` defaults to 0. List responses carry the
    pagination fields `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object."

    Design: Corner/endpoints/volunteer_list_pagination_defaults
    """
    chapter = create_chapter()
    create_volunteer_batch(chapter["id"], 12)

    page1 = api_client.list_volunteers(
        WISH_COORDINATOR, params={"chapter_id": chapter["id"]})
    items1, meta1 = validate_paginated(page1)
    assert len(items1) == 10, f"default page size is 10, got {len(items1)}"
    assert_pagination_meta(meta1, total_count=12, limit=10, offset=0,
                           has_more=True)
    assert page1.json()["response_type"] == "array"
    assert page1.json()["meta"]["api_request_id"]

    page2 = api_client.list_volunteers(
        WISH_COORDINATOR, params={"chapter_id": chapter["id"], "offset": 10})
    items2, meta2 = validate_paginated(page2)
    assert len(items2) == 2
    assert_pagination_meta(meta2, total_count=12, offset=10, has_more=False)


def test_wish_list_reverse_filter_by_chapter():
    """PRD section 4: GET /wish-grant/wishes accepts the optional filter
    `chapter_id`; PRD section 2.3: filtered list responses still paginate with
    `total_count` inside `meta`.

    Design: Corner/endpoints/wish_list_reverse_filter_by_chapter
    """
    set_clock()
    chapter_a = create_chapter(name="Chapter A", territory_zip_prefixes=["900"])
    chapter_b = create_chapter(name="Chapter B", territory_zip_prefixes=["800"])
    wish_a = create_approved_wish(chapter=chapter_a)["wish"]
    wish_b = create_approved_wish(
        chapter=chapter_b, zip_code="80044", child_full_name="Theo Alvarez",
        child_date_of_birth="2015-06-15", parent_email="alvarez@example.org",
        diagnosis_summary="cardiomyopathy", source_type="MEDICAL_PROFESSIONAL",
    )["wish"]

    resp = api_client.list_wishes(
        WISH_COORDINATOR, params={"chapter_id": chapter_a["id"]})
    items, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    ids = [w["id"] for w in items]
    assert ids == [wish_a["id"]], (
        f"chapter filter must isolate chapter A's wish: got {ids}, "
        f"expected [{wish_a['id']}] (chapter B's wish {wish_b['id']} excluded)"
    )


def test_plan_line_items_subresource_listing():
    """PRD section 4: GET /wish-grant/fulfillment-plans/{id}/line-items lists
    a plan's line items; PRD section 3.6: "A successful reservation pins
    `line_fmv_cents` at the line's `quantity` multiplied by the offer's
    `fmv_unit_cents` as of that moment"

    Design: Corner/endpoints/plan_line_items_subresource_listing
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=0)
    plan = ctx["plan"]
    offer = create_donation_offer(quantity_total=4, unit_retail_cents=12000)
    line1 = add_line_item(plan["id"], offer["id"], 2)
    line2 = add_line_item(plan["id"], offer["id"], 1)

    resp = api_client.list_plan_line_items(plan["id"], WISH_COORDINATOR)
    items, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    by_id = {item["id"]: item for item in items}
    assert by_id[line1["id"]]["quantity"] == 2
    assert by_id[line1["id"]]["line_fmv_cents"] == 24000
    assert by_id[line2["id"]]["quantity"] == 1
    assert by_id[line2["id"]]["line_fmv_cents"] == 12000
    assert all(item["status"] == "RESERVED" for item in items)

    plan_now = get_fulfillment_plan(plan["id"])
    assert plan_now["in_kind_value_cents"] == 36000
