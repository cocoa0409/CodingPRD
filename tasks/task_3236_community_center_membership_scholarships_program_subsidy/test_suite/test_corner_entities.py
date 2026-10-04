"""Corner probes against entity shape, creation defaults and listing pages."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BOARD_MEMBER_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    FRONT_DESK_HEADERS,
    assert_common_fields,
    assert_envelope_meta,
    assert_list_page,
    assert_membership,
)
from test_helpers import factories, fixtures

UNKNOWN_ID = "11111111-2222-3333-4444-555555555555"


def test_association_create_applies_defaults_and_common_fields(api):
    """A minimal association body comes back with the declared defaults and the
    full common-field contract.

    PRD §3.1: "an `AssociationAdmin` creates the `Association`, supplying its
    legal `name`, whether `reciprocity_enabled` is on (it defaults to true), the
    `ami_base_cents` area median income for a one-person household in cents, and
    the active `campaign_year`."
    PRD §2.4: "Every persisted resource carries a server-minted `id` that is a
    UUID with no type prefix, plus `created_at` and `updated_at` timestamps in
    ISO 8601 UTC with three fractional digits, and an integer `version` that
    starts at 1 on creation and increments by exactly 1 on every mutation of the
    record."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/association_create_returns_defaults_and_common_fields
    """
    fixtures.set_clock(api)
    response = api.create_association(
        {"name": "Metro YMCA", "ami_base_cents": 5_000_000, "campaign_year": 2026},
        ASSOCIATION_ADMIN_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)

    association = validate_success(response, 201)
    assert association["reciprocity_enabled"] is True
    assert association["version"] == 1
    assert_common_fields(association, "association")


def test_category_create_rejects_undeclared_household_type(api):
    """household_type is a closed enum; an undeclared value is a 400.

    PRD §3.1: "A category record carries the offering `branch_id`, a display
    `name`, a `household_type` of exactly one of `ADULT`, `TWO_ADULT`, `FAMILY`,
    `SENIOR`, `YOUNG_ADULT`, or `TEEN`, the one-time `joining_fee_cents`, the
    standard `monthly_dues_cents` before assistance, the household caps
    `max_adults` and `max_dependents`, and an optional `hold_fee_cents` that
    defaults to 1000 cents"
    PRD §2.7: "then request-schema and composition checks (`ERR_INVALID_REQUEST`,
    `ERR_DOCUMENTATION_MISSING`, `ERR_HOUSEHOLD_CAP_EXCEEDED`,
    `ERR_TIME_RANGE_INVALID`)"

    Design: Corner/entities/category_create_rejects_invalid_household_type_enum
    """
    world = fixtures.setup_association_and_branch(api)
    response = api.create_category(
        factories.category_payload(world["branch"]["id"], household_type="HOUSEHOLD"),
        BRANCH_DIRECTOR_HEADERS,
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    rows, meta = validate_paginated(
        api.list_categories(BRANCH_DIRECTOR_HEADERS, {"branch_id": world["branch"]["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_membership_create_ignores_client_supplied_system_fields(api):
    """System-owned fields in a join body are ignored; the new row shows the
    declared birth state.

    PRD §3.2: "A new membership is born with `status` `ACTIVE`, `draft_status`
    `CURRENT`, `version` 1, and an `anniversary_day` equal to the day-of-month
    of the activation date capped at 28, which is the day each month on which
    the recurring draft runs."
    PRD §2.4: "an integer `version` that starts at 1 on creation and increments
    by exactly 1 on every mutation of the record"

    Design: Corner/entities/membership_computed_fields_ignore_client_input
    """
    world = fixtures.setup_branch_with_category(api)
    member = fixtures.create_member(api, world["branch"]["id"])
    payload = factories.membership_payload(
        world["branch"]["id"], world["category"]["id"], member["id"]
    )
    payload.update(
        {
            "status": "CANCELLED",
            "draft_status": "DELINQUENT",
            "assistance_pct": 0.75,
            "lifetime_billed_cents": 999_999,
            "hold_days_used_trailing_12mo": 42,
        }
    )
    membership = get_success_data(api.create_membership(payload, FRONT_DESK_HEADERS))
    assert membership["status"] == "ACTIVE"
    assert membership["draft_status"] == "CURRENT"
    assert membership["assistance_pct"] == 0
    assert membership["lifetime_billed_cents"] == 0
    assert membership["hold_days_used_trailing_12mo"] == 0
    assert_membership(membership)


def test_member_get_with_unknown_id_is_not_found(api):
    """A syntactically valid but unallocated id on a member path is a 404.

    PRD §2.7: "Existence of every path identifier follows (`ERR_NOT_FOUND`)"

    Design: Corner/entities/member_get_with_unknown_id_returns_not_found
    """
    response = api.get_member(UNKNOWN_ID, FRONT_DESK_HEADERS)
    validate_error(response, "ERR_NOT_FOUND")


def test_memberships_list_paginates_with_total_count_and_has_more(api):
    """total_count spans the filtered set; has_more reports whether records
    remain beyond the page; defaults are limit 10, offset 0.

    PRD §2.3: "List endpoints accept two optional query parameters, `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0. Every list response includes the pagination fields
    `limit`, `offset`, `total_count`, and `has_more` in its `meta` object, where
    `total_count` is the full count of matching records and `has_more` reports
    whether further records exist beyond the current window."

    Design: Corner/entities/memberships_list_paginates_with_total_count_and_has_more
    """
    world = fixtures.setup_branch_with_category(api)
    for index in range(3):
        member = fixtures.create_member(
            api,
            world["branch"]["id"],
            full_name=f"M {index}",
            email=f"m{index}@x.com",
            birth_date="1990-01-01",
        )
        get_success_data(
            api.create_membership(
                factories.membership_payload(world["branch"]["id"], world["category"]["id"], member["id"]),
                FRONT_DESK_HEADERS,
            )
        )

    page1, meta1 = validate_paginated(
        api.list_memberships(BRANCH_DIRECTOR_HEADERS, {"branch_id": world["branch"]["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert_list_page(meta1, 2, 0, 3, True)

    page2, meta2 = validate_paginated(
        api.list_memberships(BRANCH_DIRECTOR_HEADERS, {"branch_id": world["branch"]["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert_list_page(meta2, 2, 2, 3, False)

    page_all, meta_all = validate_paginated(
        api.list_memberships(BRANCH_DIRECTOR_HEADERS, {"branch_id": world["branch"]["id"]})
    )
    assert len(page_all) == 3
    assert_list_page(meta_all, 10, 0, 3, False)
