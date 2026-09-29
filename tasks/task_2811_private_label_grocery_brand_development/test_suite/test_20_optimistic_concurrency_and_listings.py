"""The version a client holds and the version the server holds: what moves it,
what leaves it alone, what a pin remembers, and how every child collection is
walked back to its parent."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_landed_costs,
    assert_money_cents,
    assert_page_window,
    assert_settlement,
    assert_shelf_slots,
    assert_status,
    assert_version_is,
    find_by_id,
    ids_of,
)
from test_helpers.constants import (
    ARTWORK_APPROVED,
    CCR_ACCEPTED,
    CCR_WITHDRAWN,
    CLAIM_APPROVED,
    DECISION_ACCEPT,
    ITEM_CONCEPT,
    ITEM_PACKAGING_APPROVED,
    ITEM_SOURCED,
    ITEM_SPEC_LOCKED,
    NUTRITION_VALID,
    RUN_SCHEDULED,
    SPEC_DRAFT,
    SPEC_LOCKED,
    SPEC_SUPERSEDE_PENDING,
    STUDY_BENCH_TOP,
    STUDY_CONSUMER_PANEL,
    TIER_T1,
)
from test_helpers.fixtures import (
    build_chain,
    read_artwork_round,
    read_budget_ledger,
    read_change_request,
    read_claim,
    read_cost_model,
    read_gap,
    read_item,
    read_scorecard,
    read_specification,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    QUALITY_HEADERS,
    SOURCING_HEADERS,
)

T1_REQUEST = {
    "requested_ingredient_cost_cents_per_unit": 147,
    "requested_packaging_cost_cents_per_unit": 31,
    "requested_conversion_cost_cents_per_unit": 48,
}


def test_a_shipment_feed_between_the_read_and_the_create_makes_the_pin_stale(api):
    """Another role's write to an unrelated field still invalidates the version.

    PRD 2.7: "If `expected_item_version` does not equal the item's current
    `version`, the create is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412)."

    PRD 3.8: "Posting the shipment feed is open to a `SourcingManager` or a
    `QualityAuditor` and supplies a single figure, `trailing_90d_units`, the units
    shipped over the trailing ninety days, which may be zero but never negative. It
    overwrites the stored value and then triggers the same recomputation a new
    complaint triggers."

    Design: Corner/cross_cutting_complexity_layers/spec_create_with_item_version_moved_by_a_shipment_feed_rejected
    """
    ctx = build_chain(api, upto=23)
    stale_version = ctx["item_version"]
    fed = validate_success(
        api.post_shipment_feed(
            ctx["item_id"], f.shipment_feed_payload(60000), QUALITY_HEADERS
        )
    )
    assert fed["version"] == stale_version + 1, "the feed is a mutation like any other"

    response = api.create_specification(
        f.specification_payload(
            ctx["item_id"],
            ctx["cost_model_id"],
            ctx["artwork_round_id"],
            stale_version,
        ),
        SOURCING_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_ITEM_VERSION.value, 412)

    _specs, meta = validate_paginated(
        api.list_specifications(SOURCING_HEADERS, params={"item_id": ctx["item_id"]})
    )
    assert meta["total_count"] == 0, "a 412 must not persist a specification"
    item = read_item(api, ctx["item_id"])
    assert item["spec_revision_count"] == 0, (
        "the revision counter must not move ahead of a refused create"
    )
    assert item["trailing_90d_units"] == 60000
    assert item["development_status"] == ITEM_PACKAGING_APPROVED
    assert_status(
        read_artwork_round(api, ctx["artwork_round_id"]), ARTWORK_APPROVED, "round"
    )


def test_a_withdrawn_request_still_leaves_the_cost_model_version_moved(api):
    """Two writes moved the row; the supplier's original version is twice stale.

    PRD 2.7: "If `expected_cost_model_version` does not equal the cost model's
    current `version`, the create is rejected with `ERR_STALE_COST_MODEL_VERSION`
    (HTTP 412)."

    PRD 3.9: "A successful create opens the request at `SUBMITTED` with
    `round_number` at 1, `counter_base_cents` and `decided_by_user_id` null,
    increases the cost model's `open_change_request_count` by 1 and increments that
    cost model's `version`."

    PRD 3.9: "The owning supplier may also withdraw its request from either
    `SUBMITTED` or `COUNTERED`, moving it to the terminal `WITHDRAWN`, which
    decreases the cost model's `open_change_request_count` by 1 and increments that
    model's `version`."

    Design: Corner/cross_cutting_complexity_layers/cost_change_create_with_version_moved_by_a_withdrawn_request_rejected
    """
    ctx = build_chain(api, upto=12)
    stale_version = read_cost_model(api, ctx["cost_model_id"])["version"]
    first = validate_success(
        api.create_change_request(
            f.change_request_payload(
                ctx["item_id"], ctx["cost_model_id"], stale_version, **T1_REQUEST
            ),
            ctx["supplier_headers"],
        ),
        expected_status=201,
    )
    validate_success(
        api.withdraw_change_request(first["id"], ctx["supplier_headers"])
    )

    response = api.create_change_request(
        f.change_request_payload(
            ctx["item_id"],
            ctx["cost_model_id"],
            stale_version,
            requested_ingredient_cost_cents_per_unit=150,
            requested_packaging_cost_cents_per_unit=31,
            requested_conversion_cost_cents_per_unit=48,
        ),
        ctx["supplier_headers"],
    )
    error = validate_error(
        response, ApiErrorId.ERR_STALE_COST_MODEL_VERSION.value, 412
    )
    assert error["error_id"] != ApiErrorId.ERR_OPEN_CHANGE_REQUEST_EXISTS.value, (
        "the withdrawal already cleared the open count"
    )

    rows, meta = validate_paginated(
        api.list_change_requests(
            SOURCING_HEADERS, params={"cost_model_id": ctx["cost_model_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [first["id"]]
    assert_status(
        read_change_request(api, first["id"]), CCR_WITHDRAWN, "cost change request"
    )
    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert cost_model["open_change_request_count"] == 0
    assert_money_cents(
        cost_model["effective_base_cents"], 221, "effective_base_cents"
    )
    assert_landed_costs(cost_model, audited=283)
    assert cost_model["version"] == stale_version + 2, (
        "the create and the withdrawal each moved the row"
    )


def test_three_intervening_reads_leave_the_pinned_version_current(api):
    """Two computed reads and a plain one: none of them is a mutation.

    PRD 2.5: "Thirteen of the fourteen collections additionally carry `updated_at`,
    in the same format, refreshed on every mutation of the row, and `version`, an
    integer that starts at 1 when the row is created and increases by exactly 1 on
    every mutation of that row — including mutations caused by a cascade from some
    other resource rather than by a request addressed at the row directly."

    PRD 2.7: "`POST /private-label/specifications` requires
    `expected_item_version`, carrying the `version` of the target `ProductItem` that
    the client last read."

    PRD 3.6: "Creation records the exact versions it observed.
    `pinned_cost_model_version` receives the cost model's current `version` and
    `pinned_artwork_version` receives the artwork round's current `version`, both as
    read at that instant."

    Design: Corner/cross_cutting_complexity_layers/reads_never_move_a_version_and_a_current_pin_is_accepted
    """
    ctx = build_chain(api, upto=22)
    before = read_item(api, ctx["item_id"])
    item_version = before["version"]
    revisions_before = before["spec_revision_count"]

    read_budget_ledger(api, ctx["program_id"])
    read_scorecard(api, ctx["supplier_id"])
    cost_model_version = read_cost_model(api, ctx["cost_model_id"])["version"]

    created = validate_success(
        api.create_specification(
            f.specification_payload(
                ctx["item_id"],
                ctx["cost_model_id"],
                ctx["artwork_round_id"],
                item_version,
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )

    assert_status(created, SPEC_DRAFT, "specification")
    assert created["revision_no"] == 1
    assert_version_is(created, 1, "specification")
    assert created["slotting_fee_cents"] is None
    assert created["pinned_cost_model_version"] == cost_model_version
    item = read_item(api, ctx["item_id"])
    assert item["spec_revision_count"] == revisions_before + 1
    assert item["version"] == item_version + 1, "the create is the only mutation"
    assert_version_is(
        read_cost_model(api, ctx["cost_model_id"]), cost_model_version, "cost model"
    )
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]),
        committed_budget_cents=0,
        lifetime_committed_cents=0,
    )


def test_accepting_a_t1_change_leaves_the_locked_pins_and_the_fee_alone(api):
    """The cost model moves 221 to 225; the pinned fee and price do not follow.

    PRD 2.7: "Optimistic concurrency control guards a create against an unobserved
    parent; pin staleness guards a lock against pins that went out of date after the
    specification was drafted."

    PRD 3.9: "the raw increase is 30, the percentage is 13.57, the tier is `T3`, the
    cap floors to 19, the capped increase is 19, the fee rounds to 2, the net increase
    is 17 and the accepted base becomes 238"

    PRD 3.9: "because the pinned cost model changed, the item's specification
    standing at `LOCKED` whose `pinned_cost_model_id` is this cost model transitions
    `LOCKED → SUPERSEDE_PENDING`, with its `version` incremented"

    Design: Corner/cross_cutting_complexity_layers/locked_specification_keeps_its_pinned_versions_when_the_cost_model_moves
    """
    ctx = build_chain(api, upto=25)
    locked = read_specification(api, ctx["specification_id"])
    pinned_cost_model_version = locked["pinned_cost_model_version"]
    pinned_artwork_version = locked["pinned_artwork_version"]
    request = validate_success(
        api.create_change_request(
            f.change_request_payload(
                ctx["item_id"],
                ctx["cost_model_id"],
                read_cost_model(api, ctx["cost_model_id"])["version"],
                **T1_REQUEST,
            ),
            ctx["supplier_headers"],
        ),
        expected_status=201,
    )

    decided = validate_success(
        api.decide_change_request(
            request["id"], f.decision_payload(DECISION_ACCEPT), SOURCING_HEADERS
        )
    )

    assert_status(decided, CCR_ACCEPTED, "cost change request")
    assert_settlement(
        decided, escalation_tier=TIER_T1, net_increase_cents=4, increase_pct=2.26
    )
    cost_model = read_cost_model(api, ctx["cost_model_id"])
    assert_money_cents(
        cost_model["effective_base_cents"], 225, "effective_base_cents"
    )
    assert_landed_costs(cost_model, audited=287)
    assert cost_model["open_change_request_count"] == 0
    spec = read_specification(api, ctx["specification_id"])
    assert_status(spec, SPEC_SUPERSEDE_PENDING, "specification")
    assert spec["pinned_cost_model_version"] == pinned_cost_model_version, (
        "a pin records a value, not a live reference"
    )
    assert spec["pinned_artwork_version"] == pinned_artwork_version
    assert_money_cents(spec["slotting_fee_cents"], 266980, "slotting_fee_cents")
    item = read_item(api, ctx["item_id"])
    assert_money_cents(item["retail_price_cents"], 409, "retail_price_cents")
    assert item["development_status"] == ITEM_SPEC_LOCKED
    assert read_artwork_round(api, ctx["artwork_round_id"])["nutrition_status"] == (
        NUTRITION_VALID
    )
    assert_status(read_claim(api, ctx["claim_id"]), CLAIM_APPROVED, "label claim")
    assert_budget_ledger(
        read_budget_ledger(api, ctx["program_id"]), committed_budget_cents=266980
    )


def test_the_supplier_filter_on_items_follows_the_award_not_the_creation(api):
    """Two items in one gap; only the awarded one answers the supplier filter.

    PRD 2.3: "Each collection's list endpoint also accepts the foreign keys of that
    collection as optional equality filters, so that every relationship is
    reverse-reachable: category gaps filter by `program_id`, suppliers by
    `program_id`, plant lines by `supplier_id`, plant audits by `supplier_id`, items
    by `gap_id`, `supplier_id` and `replacement_item_id`"

    PRD 3.3: "With `decision` set to `ACCEPT` the quote moves `SUBMITTED →
    ACCEPTED`, and three things happen together: the item's `supplier_id` is set to
    the quoting supplier, the item advances `CONCEPT → SOURCED`"

    PRD 3.3: "A successful creation opens the item at `development_status` `CONCEPT`
    and `quality_posture` `GREEN`, with `supplier_id` and `retail_price_cents` null"

    Design: Corner/endpoints/items_list_supplier_filter_reflects_cost_model_award_not_creation
    """
    ctx = build_chain(api, upto=12)
    unawarded = validate_success(
        api.create_item(f.second_item_payload(ctx["gap_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    by_supplier, supplier_meta = validate_paginated(
        api.list_items(SOURCING_HEADERS, params={"supplier_id": ctx["supplier_id"]})
    )
    by_gap, gap_meta = validate_paginated(
        api.list_items(SOURCING_HEADERS, params={"gap_id": ctx["gap_id"]})
    )

    assert ids_of(by_supplier) == [ctx["item_id"]], (
        "an item created but never awarded is not reachable from the supplier"
    )
    assert_page_window(supplier_meta, 10, 0, 1)
    assert unawarded["id"] not in ids_of(by_supplier)
    assert gap_meta["total_count"] == 2
    awarded_row = find_by_id(by_gap, ctx["item_id"])
    assert awarded_row["supplier_id"] == ctx["supplier_id"]
    assert awarded_row["development_status"] == ITEM_SOURCED
    unawarded_row = find_by_id(by_gap, unawarded["id"])
    assert unawarded_row["supplier_id"] is None
    assert unawarded_row["development_status"] == ITEM_CONCEPT
    assert_shelf_slots(
        read_gap(api, ctx["gap_id"]),
        slots_consumed=2,
        slots_open=0,
        shelf_slots_quota=2,
    )


def test_every_child_collection_is_reachable_from_its_parent_id(api):
    """Eleven filters walked in one pass, two of them over empty collections.

    PRD 2.3: "Each collection's list endpoint also accepts the foreign keys of that
    collection as optional equality filters, so that every relationship is
    reverse-reachable: category gaps filter by `program_id`, suppliers by
    `program_id`, plant lines by `supplier_id`, plant audits by `supplier_id`, items
    by `gap_id`, `supplier_id` and `replacement_item_id`, cost models by `item_id`
    and `supplier_id`, comparison studies by `item_id`, artwork rounds by `item_id`,
    label claims by `artwork_round_id`, specifications by `item_id`,
    `pinned_cost_model_id` and `pinned_artwork_round_id`, production runs by
    `item_id`, `specification_id` and `plant_line_id`, complaints by `item_id`, and
    cost change requests by `item_id` and `cost_model_id`."

    PRD 2.3: "`total_count` is the number of rows matching the filter before the
    window is applied and `has_more` is true exactly when rows remain beyond the
    returned window"

    Design: Corner/endpoints/every_child_collection_is_listable_by_its_parent_id
    """
    ctx = build_chain(api, upto=26)

    suppliers, _ = validate_paginated(
        api.list_suppliers(DIRECTOR_HEADERS, params={"program_id": ctx["program_id"]})
    )
    lines, _ = validate_paginated(
        api.list_plant_lines(
            DIRECTOR_HEADERS, params={"supplier_id": ctx["supplier_id"]}
        )
    )
    audits, _ = validate_paginated(
        api.list_plant_audits(
            DIRECTOR_HEADERS, params={"supplier_id": ctx["supplier_id"]}
        )
    )
    cost_models, _ = validate_paginated(
        api.list_cost_models(DIRECTOR_HEADERS, params={"item_id": ctx["item_id"]})
    )
    studies, _ = validate_paginated(
        api.list_studies(DIRECTOR_HEADERS, params={"item_id": ctx["item_id"]})
    )
    rounds, _ = validate_paginated(
        api.list_artwork_rounds(DIRECTOR_HEADERS, params={"item_id": ctx["item_id"]})
    )
    claims, _ = validate_paginated(
        api.list_label_claims(
            DIRECTOR_HEADERS, params={"artwork_round_id": ctx["artwork_round_id"]}
        )
    )
    specs, _ = validate_paginated(
        api.list_specifications(DIRECTOR_HEADERS, params={"item_id": ctx["item_id"]})
    )
    runs, _ = validate_paginated(
        api.list_production_runs(DIRECTOR_HEADERS, params={"item_id": ctx["item_id"]})
    )
    complaints, complaint_meta = validate_paginated(
        api.list_complaints(DIRECTOR_HEADERS, params={"item_id": ctx["item_id"]})
    )
    requests, request_meta = validate_paginated(
        api.list_change_requests(
            DIRECTOR_HEADERS, params={"cost_model_id": ctx["cost_model_id"]}
        )
    )

    assert ids_of(suppliers) == [ctx["supplier_id"]]
    assert ids_of(lines) == [ctx["plant_line_id"]]
    assert ids_of(audits) == [ctx["audit_id"]]
    assert ids_of(cost_models) == [ctx["cost_model_id"]]
    assert sorted(row["study_type"] for row in studies) == [
        STUDY_BENCH_TOP,
        STUDY_CONSUMER_PANEL,
    ]
    assert ids_of(rounds) == [ctx["artwork_round_id"]]
    assert ids_of(claims) == [ctx["claim_id"]]
    assert ids_of(specs) == [ctx["specification_id"]]
    assert_status(specs[0], SPEC_LOCKED, "specification")
    assert ids_of(runs) == [ctx["run_id"]]
    assert_status(runs[0], RUN_SCHEDULED, "production run")
    assert complaints == [], "an item with no complaints answers with an empty page"
    assert_page_window(complaint_meta, 10, 0, 0)
    assert requests == []
    assert_page_window(request_meta, 10, 0, 0)
