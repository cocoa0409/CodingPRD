"""The error catalogue: which refusal wins, and which key each gate reads."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories
from test_helpers import fixtures as F
from test_helpers.constants import DELI_FOUR_RUNGS, MISSING_ID_ALT, PRODUCE_TWO_RUNGS
from test_helpers.test_users import (
    admin_headers,
    auditor_headers,
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    manager_headers,
)

RECORDER_USER_ID = "u-clerk-1"
VERIFIER_USER_ID = "u-mgr-1"
APPROVER_USER_ID = "u-mgr-2"


def test_every_read_answers_the_not_found_code_of_its_own_collection(api):
    """One syntactically valid identifier, eleven collections, eleven different 404 codes.

    PRD 2.5: "Where a path does carry identifiers, they are validated strictly left to
    right, and the first identifier that does not resolve decides the response with its own
    dedicated 404 code: `ERR_STORE_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_LADDER_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`,
    `ERR_PICKUP_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SHRINK_EVENT_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` and `ERR_RECOMMENDATION_NOT_FOUND`."

    PRD 2.11: "4. Path-identifier existence, validated left to right -- the matching 404
    code from 2.5."

    The database is empty, so nothing but the collection segment of the path can decide
    which identifier comes back.

    Design: Corner/errors/every_read_answers_its_own_entity_specific_not_found_code
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    missing = MISSING_ID_ALT
    acting = admin_headers()

    catalogue = [
        ("stores", api.get_store(missing, acting), "ERR_STORE_NOT_FOUND"),
        (
            "food-bank-partners",
            api.get_food_bank_partner(missing, acting),
            "ERR_PARTNER_NOT_FOUND",
        ),
        (
            "markdown-ladders",
            api.get_markdown_ladder(missing, acting),
            "ERR_LADDER_NOT_FOUND",
        ),
        ("departments", api.get_department(missing, acting), "ERR_DEPARTMENT_NOT_FOUND"),
        (
            "markdown-labels",
            api.get_markdown_label(missing, acting),
            "ERR_LABEL_NOT_FOUND",
        ),
        (
            "scan-price-checks",
            api.get_scan_price_check(missing, acting),
            "ERR_CHECK_NOT_FOUND",
        ),
        (
            "donation-assignments",
            api.get_donation_assignment(missing, acting),
            "ERR_ASSIGNMENT_NOT_FOUND",
        ),
        (
            "shrink-events",
            api.get_shrink_event(missing, acting),
            "ERR_SHRINK_EVENT_NOT_FOUND",
        ),
        (
            "compliance-audits",
            api.get_compliance_audit(missing, acting),
            "ERR_AUDIT_NOT_FOUND",
        ),
        ("audit-findings", api.get_audit_finding(missing, acting), "ERR_FINDING_NOT_FOUND"),
        (
            "order-recommendations",
            api.get_order_recommendation(missing, acting),
            "ERR_RECOMMENDATION_NOT_FOUND",
        ),
    ]

    seen = []
    for collection, response, expected_error_id in catalogue:
        assert response.status_code == 404, (
            f"read of {collection}/{missing} answered {response.status_code}, "
            f"expected 404 with {expected_error_id}"
        )
        validate_error(response, expected_error_id, expected_status=404)
        seen.append(expected_error_id)

    # The whole point of the catalogue is that no two collections share a code.
    assert len(set(seen)) == len(seen), f"duplicate error_id in the 404 catalogue: {seen}"


def test_store_number_and_ladder_name_collide_globally_but_a_department_code_only_per_store(
    api,
):
    """Two globally unique keys and one composite key, each refusing on its own scope.

    PRD 3.1: "The `store_number` is exactly four digits, characters `0` through `9` only, and
    must be globally unique -- a second store claiming a number already taken is refused with
    `ERR_STORE_NUMBER_DUPLICATE`."

    PRD 3.1: "A ladder has a `name` of 1 to 60 characters that must be globally unique -- a
    duplicate is refused with `ERR_LADDER_NAME_DUPLICATE` -- and a `department_code` drawn
    from the same six-member set, restricting which departments may attach to it."

    PRD 3.1: "The pair of `store_id` and `code` must be unique, so a store cannot hold two
    `BAKERY` departments -- a duplicate is refused with `ERR_DEPARTMENT_CODE_DUPLICATE`."

    PRD 2.11: "40. Uniqueness -- store number globally, ladder name globally, department code
    within a store, item UPC within a department -- on store creation, ladder creation,
    department creation and item creation".

    The design index writes the colliding SEAFOOD ladder with a single rung.  That payload
    could never reach the uniqueness check at all: PRD 3.1 declares `rungs` "an ordered array
    of between 2 and 6 objects", and PRD 2.11 puts request shape at check 3, far above
    uniqueness at check 40, so a one-rung array answers `ERR_INVALID_REQUEST` instead.  The
    retry therefore carries two well-ordered rungs, leaving the duplicated name as its only
    defect.

    Design: Corner/errors/registry_uniqueness_conflicts_are_scoped_to_their_declared_keys
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    store_a = F.build_store(api, store_number="0412", region_code="MID-ATL")
    ladder = F.build_ladder(
        api,
        name="MEAT-STD-2026",
        department_code="MEAT",
        rungs=factories.ladder_rungs((3, 15, False), (1, 50, True)),
    )
    F.build_department(api, store_a["id"], ladder["id"], code="MEAT", shelf_life_days_default=10)

    same_number = api.create_store(
        factories.create_store_payload(
            store_number="0412", name="Fresh Market 0412 Annex", region_code="SOUTH-E"
        ),
        admin_headers(),
    )
    validate_error(same_number, "ERR_STORE_NUMBER_DUPLICATE", expected_status=409)

    same_name = api.create_markdown_ladder(
        factories.create_markdown_ladder_payload(
            name="MEAT-STD-2026",
            department_code="SEAFOOD",
            rungs=factories.ladder_rungs((2, 30, False), (0, 50, True)),
        ),
        admin_headers(),
    )
    validate_error(same_name, "ERR_LADDER_NAME_DUPLICATE", expected_status=409)

    same_code = api.create_department(
        factories.create_department_payload(
            store_a["id"], ladder["id"], code="MEAT", shelf_life_days_default=8
        ),
        admin_headers(),
    )
    validate_error(same_code, "ERR_DEPARTMENT_CODE_DUPLICATE", expected_status=409)

    # The very same MEAT code is free on a second store, which is what makes the
    # department key composite rather than global.
    store_b = F.build_store(
        api, store_number="0413", name="Fresh Market 0413", region_code="MID-ATL"
    )
    dept_b = F.build_department(
        api, store_b["id"], ladder["id"], code="MEAT", shelf_life_days_default=10
    )
    A.assert_fields(dept_b, code="MEAT", store_id=store_b["id"])

    rows, meta = validate_paginated(
        api.list_stores(
            admin_headers(), params={"region_code": "MID-ATL", "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, (
        "only the two accepted MID-ATL stores may exist; the refused 0412 retry named "
        f"SOUTH-E and wrote nothing, so total_count should be 2, got {meta['total_count']}"
    )
    A.assert_contains_ids(rows, [store_a["id"], store_b["id"]])


def test_five_referential_gates_each_read_a_different_neighbour_of_the_request(api):
    """The ladder's code, the item's status, the store's flag, its dock list, the partner's region.

    PRD 3.1: "The attached ladder's `department_code` must equal the department's own `code`;
    attaching a `MEAT` ladder to a `DAIRY` department is refused with
    `ERR_LADDER_DEPARTMENT_MISMATCH`."

    PRD 3.1: "`status` is `ACTIVE` or `DISCONTINUED`, defaulting to `ACTIVE`; receiving a new
    lot for a `DISCONTINUED` item is refused with `ERR_ITEM_DISCONTINUED`."

    PRD 3.7: "the store must be `ACTIVE` with `donation_program_enabled` true, else
    `ERR_DONATION_PROGRAM_DISABLED`; the `dock_door_code` must appear in the store's
    `dock_door_codes`, else `ERR_DOCK_DOOR_UNKNOWN`".

    PRD 3.1: "a `service_region_code` of 1 to 24 characters that must equal the `region_code`
    of any store whose dock it is booked on -- a mismatch is refused with
    `ERR_PARTNER_REGION_MISMATCH`."

    PRD 3.1: "Later on, an administrator may revise a store's `status`,
    `donation_program_enabled`, `dock_door_codes` and `name`; each such revision bumps the
    store's `version` by one."

    Two corrections to the design index, both forced by the PRD text.  It calls
    `donation_program_enabled` a "false default", but PRD 3.1 says the flag "defaults to
    true", so the store is created with an explicit false to keep the
    `ERR_DONATION_PROGRAM_DISABLED` refusal PRD-derived.  And it writes both ladders with a
    single rung, while PRD 3.1 requires "an ordered array of between 2 and 6 objects" -- a
    one-rung ladder would never be created at all -- so each ladder carries two well-ordered
    rungs.

    Design: Corner/errors/registry_reference_gates_reject_before_any_row_is_written
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    store = F.build_store(
        api,
        store_number="0412",
        name="Fresh Market 0412",
        region_code="MID-ATL",
        dock_door_codes=["D1"],
        donation_program_enabled=False,
    )
    deli_ladder = F.build_ladder(
        api,
        name="DELI-STD-2026",
        department_code="DELI",
        rungs=[DELI_FOUR_RUNGS[0], DELI_FOUR_RUNGS[2]],
    )
    produce_ladder = F.build_ladder(
        api,
        name="PRODUCE-STD-2026",
        department_code="PRODUCE",
        rungs=PRODUCE_TWO_RUNGS,
    )
    department = F.build_department(
        api, store["id"], produce_ladder["id"], code="PRODUCE", shelf_life_days_default=5
    )
    item = F.build_item(
        api,
        department["id"],
        headers=manager_headers(),
        upc="000444555666",
        description="Blueberries 6oz",
        base_retail_cents=599,
        unit_cost_cents=300,
        daily_forecast_units=8.00,
    )
    discontinued = validate_success(
        api.update_item(item["id"], {"status": "DISCONTINUED"}, manager_headers())
    )
    A.assert_fields(discontinued, status="DISCONTINUED", version=2)

    partner_mid = F.build_partner(
        api,
        name="Mid-Atlantic Food Bank",
        contact_email="ops@mafb.example",
        service_region_code="MID-ATL",
        accepted_department_codes=["PRODUCE"],
    )
    partner_south = F.build_partner(
        api,
        name="Southeast Pantry",
        contact_email="ops@sep.example",
        service_region_code="SOUTH-E",
        accepted_department_codes=["PRODUCE"],
    )

    # 1. The ladder's own department_code is read, not the department's request.
    mismatched = api.create_department(
        factories.create_department_payload(
            store["id"], deli_ladder["id"], code="SEAFOOD", shelf_life_days_default=4
        ),
        admin_headers(),
    )
    validate_error(mismatched, "ERR_LADDER_DEPARTMENT_MISMATCH", expected_status=422)

    # 2. The item's status is read.
    on_discontinued = api.create_lot(
        factories.create_lot_payload(
            item["id"], production_date="2026-08-10", quantity_original=10
        ),
        clerk_headers(),
    )
    validate_error(on_discontinued, "ERR_ITEM_DISCONTINUED", expected_status=409)

    # 3. The store's donation flag is read.
    pickup_payload = factories.create_donation_pickup_payload(
        store["id"],
        partner_mid["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
    )
    programme_off = api.create_donation_pickup(pickup_payload, manager_headers())
    validate_error(programme_off, "ERR_DONATION_PROGRAM_DISABLED", expected_status=409)

    switched_on = validate_success(
        api.update_store(store["id"], {"donation_program_enabled": True}, admin_headers())
    )
    A.assert_fields(switched_on, donation_program_enabled=True, version=2)

    # 4. The store's dock_door_codes list is read.
    unknown_dock = api.create_donation_pickup(
        factories.create_donation_pickup_payload(
            store["id"],
            partner_mid["id"],
            dock_door_code="D9",
            scheduled_window_start="2026-08-13T14:00:00.000Z",
            scheduled_window_end="2026-08-13T15:00:00.000Z",
        ),
        manager_headers(),
    )
    validate_error(unknown_dock, "ERR_DOCK_DOOR_UNKNOWN", expected_status=422)

    # 5. The partner's service_region_code is read.
    wrong_region = api.create_donation_pickup(
        factories.create_donation_pickup_payload(
            store["id"],
            partner_south["id"],
            dock_door_code="D1",
            scheduled_window_start="2026-08-13T14:00:00.000Z",
            scheduled_window_end="2026-08-13T15:00:00.000Z",
        ),
        manager_headers(),
    )
    validate_error(wrong_region, "ERR_PARTNER_REGION_MISMATCH", expected_status=422)

    # Nothing else was wrong: the same window on the same dock is now bookable, which also
    # proves the two refused bookings reserved no dock window of their own.
    booked = validate_success(
        api.create_donation_pickup(pickup_payload, manager_headers()), expected_status=201
    )
    A.assert_fields(
        booked, logistics_status="SCHEDULED", manifest_status="DRAFT", assignment_count=0
    )

    rows, meta = validate_paginated(
        api.list_donation_pickups(
            manager_headers(), params={"store_id": store["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        "three of the four bookings were refused before any row was written, so exactly one "
        f"pickup should exist, got total_count {meta['total_count']}"
    )
    A.assert_ids_equal(rows, [booked["id"]])

    # The refused department and the refused lot wrote nothing either.
    _dept_rows, dept_meta = validate_paginated(
        api.list_departments(
            admin_headers(), params={"store_id": store["id"], "limit": 10, "offset": 0}
        )
    )
    assert dept_meta["total_count"] == 1, (
        "the SEAFOOD department was refused on the ladder mismatch, so the store should hold "
        f"only its PRODUCE department, got total_count {dept_meta['total_count']}"
    )
    _lot_rows, lot_meta = validate_paginated(
        api.list_lots(clerk_headers(), params={"item_id": item["id"], "limit": 10, "offset": 0})
    )
    assert lot_meta["total_count"] == 0, (
        "the lot on the discontinued item was refused, so the item should hold no lots, got "
        f"total_count {lot_meta['total_count']}"
    )


def test_a_same_day_re_ladder_is_refused_before_the_deep_rung_demands_an_approver(api):
    """One lot, two gates: the rung must deepen, and the deep rung must be signed for.

    PRD 3.3: "Above all it must **strictly deepen**: the effective rung index must be greater
    than the lot's `current_rung_index`, and an equal or shallower landing is refused with
    `ERR_RUNG_NOT_DEEPER` and HTTP 409."

    PRD 3.3: "Two situations demand a named approver: the effective rung's
    `requires_manager_approval` flag is true, or the caller supplied `override_price_cents`.
    In either case the request must come from a `DepartmentManager` **and** carry a non-null
    `approval_manager_user_id`; if the role is wrong or the approver is missing, the markdown
    is refused with `ERR_MANAGER_APPROVAL_REQUIRED` and HTTP 422."

    PRD 3.3: "On a re-ladder the new label's `supersedes_label_id` is set to the `id` of the
    lot's newest label still in `QUEUED`, `PRINTED` or `APPLIED`, and **that superseded label
    is transitioned to `VOIDED`** in the same operation".

    PRD 2.11 puts the deepening check at 32 and manager approval at 33, so on the second day
    the deepening test passes first and the approval gate is the one that speaks.

    Arithmetic.  Day one has 3 days remaining, which selects rung 0 at 15 percent: 599 less 15
    percent is 509.15, rounded half up to 509.  Day three has 1 day remaining, which selects
    rung 1 at 50 percent: 599 less 50 percent is 299.5, rounded half up to 300, and the cost
    floor of 40 percent of 420 cents is 168, so the floor does not bite.  The landed discount
    is (599 - 300) / 599 * 100 = 49.9165..., which is 49.92 to two places and sits inside the
    ladder's default 75 percent cap.

    Design: Corner/errors/reladder_and_approval_gates_on_the_same_lot
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label_one = F.cut_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers()
    )
    A.assert_label(label_one, "QUEUED", 599, 509, 15.03, reason="LADDER_AUTO")
    priced = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(priced, 509, 0, 15.03, status="MARKED_DOWN")
    A.assert_fields(priced, version=2)

    # Same day, same rung: the ladder has nowhere deeper to go.
    not_deeper = api.create_markdown(
        chain.lot["id"],
        {"expected_lot_version": priced["version"], "pricing_variant": "LADDER_DAYS"},
        clerk_headers(),
    )
    validate_error(not_deeper, "ERR_RUNG_NOT_DEEPER", expected_status=409)
    after_refusal = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(after_refusal, 509, 0, 15.03, status="MARKED_DOWN")
    A.assert_unchanged(priced, after_refusal, "version", "current_price_cents")

    # Two days later the ladder can deepen, but rung 1 requires an approver.
    F.set_clock(api, "2026-08-14T00:00:00.000Z")
    clerk_attempt = api.create_markdown(
        chain.lot["id"],
        {"expected_lot_version": 2, "pricing_variant": "LADDER_DAYS"},
        make_clerk_headers(RECORDER_USER_ID),
    )
    validate_error(clerk_attempt, "ERR_MANAGER_APPROVAL_REQUIRED", expected_status=422)

    unnamed_approver = api.create_markdown(
        chain.lot["id"],
        {"expected_lot_version": 2, "pricing_variant": "LADDER_DAYS"},
        make_manager_headers(VERIFIER_USER_ID),
    )
    validate_error(unnamed_approver, "ERR_MANAGER_APPROVAL_REQUIRED", expected_status=422)

    still_untouched = F.reload_lot(api, chain.lot["id"])
    A.assert_unchanged(
        priced, still_untouched, "version", "current_price_cents", "current_rung_index"
    )

    label_two = F.cut_markdown(
        api,
        chain.lot,
        pricing_variant="LADDER_DAYS",
        approval_manager_user_id=APPROVER_USER_ID,
        headers=make_manager_headers(VERIFIER_USER_ID),
        expected_lot_version=2,
    )
    A.assert_label(
        label_two,
        "QUEUED",
        509,
        300,
        49.92,
        reason="RE_LADDER",
        barcode=A.expected_barcode("000111222333", 300),
    )
    A.assert_fields(
        label_two,
        rung_index=1,
        supersedes_label_id=label_one["id"],
        approved_by_user_id=APPROVER_USER_ID,
    )

    walked = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(walked, 300, 1, 49.92, status="MARKED_DOWN")
    A.assert_fields(walked, version=3)

    superseded = F.reload_label(api, label_one["id"])
    A.assert_fields(superseded, status="VOIDED")


def test_resubmit_and_void_both_demand_a_disputed_event_and_a_label_voids_only_once(api):
    """Two lifecycles refusing their wrong starting state, and a cost basis that survives.

    PRD 3.6: "Resubmission requires the event to be `DISPUTED`, refusing anything else with
    `ERR_SHRINK_NOT_DISPUTED` and HTTP 409".

    PRD 3.6: "Alternatively a `DepartmentManager` voids the event for good: this too requires
    `DISPUTED`, refusing anything else with `ERR_SHRINK_NOT_DISPUTED`, moves `status` to
    `VOIDED`, and increments `version` by one."

    PRD 3.6: "Disputing a `RECORDED` event is the cheap case: `status` becomes `DISPUTED`,
    `verified_by_user_id` and `verified_at` are set to null, the event's `version` is
    incremented by one, and **no unit movement occurs at all**".

    PRD 3.6: "It overwrites `quantity_units`, `note`, `recorded_by_user_id` (now the
    resubmitting clerk, which re-arms the segregation-of-duties check against whoever verifies
    next) and `retail_value_cents`, **preserves the original `unit_cost_cents_snapshot`** so the
    cost basis cannot be re-dated, recomputes `cost_value_cents`, moves `status` from
    `DISPUTED` back to `RECORDED`, and increments `version` by one -- closing the
    `RECORDED` -> `VERIFIED` -> `DISPUTED` -> `RECORDED` cycle."

    PRD 3.4: "A label may be voided from `QUEUED`, `PRINTED` or `APPLIED`; only a label already
    in `VOIDED` refuses the operation, with `ERR_LABEL_ALREADY_VOIDED` and HTTP 409."

    PRD 3.4: "Voiding a label is the manager's escape hatch for a mis-printed tag, and it does
    **not** change the shelf price: the lot keeps its `current_price_cents`,
    `current_rung_index` and `total_discount_pct` exactly as they stand."

    The design index asserts `cost_value_cents` 1260 on the corrected 3-unit event, which is
    the bare 3 x 420.  PRD 3.6 makes the surcharge mandatory -- "the units written off
    multiplied by that cost snapshot, then increased by a waste-handling surcharge of 3.5
    percent, then rounded half up to whole cents" -- so 1260 x 1.035 = 1304.1 lands on 1304.
    `retail_value_cents` is 3 x the lot's 509-cent shelf price, that is 1527.

    Design: Corner/errors/shrink_and_label_state_gates_reject_the_wrong_starting_state
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label = F.cut_markdown(api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers())
    A.assert_label(label, "QUEUED", 599, 509, 15.03)

    recorder = make_clerk_headers(RECORDER_USER_ID)
    verifier = make_manager_headers(VERIFIER_USER_ID)
    event = F.record_shrink(api, chain.lot["id"], 2, "DAMAGE", headers=recorder)
    A.assert_fields(
        event, status="RECORDED", quantity_units=2, unit_cost_cents_snapshot=420, version=1
    )

    resubmit_payload = factories.resubmit_shrink_event_payload(3, note="recount")
    too_early = api.resubmit_shrink_event(event["id"], resubmit_payload, recorder)
    validate_error(too_early, "ERR_SHRINK_NOT_DISPUTED", expected_status=409)

    void_too_early = api.void_shrink_event(event["id"], verifier)
    validate_error(void_too_early, "ERR_SHRINK_NOT_DISPUTED", expected_status=409)

    disputed = F.dispute_shrink(
        api, event["id"], dispute_note="quantity looks high", headers=verifier
    )
    A.assert_fields(disputed, status="DISPUTED", version=2)
    A.assert_absent_or_none(disputed, "verified_by_user_id", "verified_at")

    corrected = validate_success(
        api.resubmit_shrink_event(event["id"], resubmit_payload, recorder)
    )
    A.assert_fields(
        corrected,
        status="RECORDED",
        quantity_units=3,
        unit_cost_cents_snapshot=420,
        note="recount",
        version=3,
    )
    A.assert_money_cents(corrected["cost_value_cents"], 1304, "cost_value_cents")
    A.assert_money_cents(corrected["retail_value_cents"], 1527, "retail_value_cents")

    # Nothing was ever verified, so no unit has moved through any of this.
    held = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(held, quantity_on_hand=24, units_shrunk=0)
    A.assert_lot_units_conservation(held)

    voided = validate_success(api.void_markdown_label(label["id"], verifier))
    A.assert_fields(voided, status="VOIDED")

    twice = api.void_markdown_label(label["id"], verifier)
    validate_error(twice, "ERR_LABEL_ALREADY_VOIDED", expected_status=409)

    # Voiding the tag is not voiding the markdown.
    still_marked_down = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(still_marked_down, 509, 0, 15.03, status="MARKED_DOWN")
    # The label never reached APPLIED, so there was no promotional lift to lose:
    # 4.00 forecast units at the STANDARD multiplier over 3 days is 12 of 24 units.
    A.assert_percent(
        still_marked_down["expected_sell_through_pct"], 50.0, "expected_sell_through_pct"
    )


def test_the_pickups_two_dimensions_gate_independently_from_seal_to_reconciliation(api):
    """Six refusals walked across one pickup, each one naming the dimension it read.

    PRD 3.7: "A donation pickup carries **two independent status dimensions**:
    `logistics_status`, tracking the truck and the dock, which starts at `SCHEDULED` and may
    reach `CONFIRMED`, `COMPLETED`, `CANCELLED` or `MISSED`; and `manifest_status`, tracking
    the paperwork, which starts at `DRAFT` and may reach `SEALED` and then `RECONCILED`.
    Neither dimension constrains the other's transition".

    PRD 3.7: "A line may be added only while the pickup's `manifest_status` is `DRAFT`; once the
    manifest is `SEALED` or `RECONCILED`, further lines are refused with `ERR_MANIFEST_SEALED`
    and HTTP 409."

    PRD 3.7: "Only a `DepartmentManager` may seal, and sealing requires `manifest_status` to be
    `DRAFT` -- resealing is refused with `ERR_MANIFEST_SEALED`".

    PRD 3.7: "Confirmation requires `logistics_status` to be `SCHEDULED`, refusing anything else
    with `ERR_PICKUP_NOT_CONFIRMABLE` and HTTP 409".

    PRD 3.7: "Completion requires `logistics_status` to be `CONFIRMED`, refusing anything else
    with `ERR_PICKUP_NOT_COMPLETABLE`, requires `manifest_status` to be `SEALED`, refusing a
    still-draft manifest with `ERR_MANIFEST_NOT_SEALED` and HTTP 409, and requires ownership."

    PRD 3.7: "Reconciliation requires `manifest_status` to be `SEALED`, refusing anything else
    with `ERR_MANIFEST_NOT_SEALED`, and requires `logistics_status` to have reached
    `COMPLETED`, `CANCELLED` or `MISSED`, refusing a pickup still `SCHEDULED` or `CONFIRMED`
    with `ERR_PICKUP_NOT_RECONCILABLE` and HTTP 409."

    PRD 3.7: "A lot whose line took its whole remaining balance -- that is, a line whose
    `quantity_units` equalled the lot's `quantity_on_hand` -- is drained to zero and becomes
    `DONATED`".

    Valuation.  One line of 10 units at the 599-cent snapshot is 5,990 cents provisional,
    which is below 50,000, so the credit rate is 62.50 percent; 5,990 x 62.5 / 100 = 3,743.75,
    rounded half up to 3,744, and the manifest credit is that single rounded line.  Every line
    ends `PICKED_UP`, so reconciliation narrows the input set to the same line and rewrites the
    same figures.

    Design: Corner/errors/pickup_and_manifest_dimension_gates_across_the_whole_lifecycle
    """
    chain = F.build_produce_chain(
        api,
        store_overrides={
            "store_number": "0412",
            "name": "Fresh Market 0412",
            "region_code": "MID-ATL",
            "dock_door_codes": ["D1"],
            "donation_program_enabled": True,
        },
        item_overrides={
            "upc": "000444555666",
            "description": "Blueberries 6oz",
            "base_retail_cents": 599,
            "unit_cost_cents": 300,
            "daily_forecast_units": 8.00,
        },
        lot_overrides={"production_date": "2026-08-10", "quantity_original": 10},
    )
    lot_two = F.build_lot(
        api, chain.item["id"], production_date="2026-08-10", quantity_original=10
    )
    pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )
    F.set_clock(api, "2026-08-13T00:00:00.000Z")
    line_one = F.pledge_lot(api, pickup["id"], chain.lot["id"], 10, headers=clerk_headers())

    sealed = F.seal_pickup(api, pickup["id"])
    A.assert_fields(
        sealed,
        manifest_status="SEALED",
        logistics_status="SCHEDULED",
        assignment_count=1,
    )
    A.assert_money_cents(sealed["provisional_value_cents"], 5990, "provisional_value_cents")
    A.assert_percent(sealed["credit_rate_pct"], 62.5, "credit_rate_pct")
    A.assert_money_cents(sealed["manifest_credit_cents"], 3744, "manifest_credit_cents")

    # Sealing the paperwork did not move the truck, so completion is still refused.
    early_complete = api.complete_donation_pickup(pickup["id"], chain.partner_headers)
    validate_error(early_complete, "ERR_PICKUP_NOT_COMPLETABLE", expected_status=409)

    late_line = api.create_donation_assignment(
        pickup["id"],
        factories.create_donation_assignment_payload(lot_two["id"], 10),
        clerk_headers(),
    )
    validate_error(late_line, "ERR_MANIFEST_SEALED", expected_status=409)
    A.assert_fields(F.reload_pickup(api, pickup["id"]), assignment_count=1)

    reseal = api.seal_donation_pickup(pickup["id"], manager_headers())
    validate_error(reseal, "ERR_MANIFEST_SEALED", expected_status=409)

    early_reconcile = api.reconcile_donation_pickup(pickup["id"], manager_headers())
    validate_error(early_reconcile, "ERR_PICKUP_NOT_RECONCILABLE", expected_status=409)

    confirmed = F.confirm_pickup(api, pickup["id"], chain.partner["id"])
    A.assert_fields(confirmed, logistics_status="CONFIRMED", manifest_status="SEALED")

    reconfirm = api.confirm_donation_pickup(pickup["id"], chain.partner_headers)
    validate_error(reconfirm, "ERR_PICKUP_NOT_CONFIRMABLE", expected_status=409)

    completed = F.complete_pickup(api, pickup["id"], chain.partner["id"])
    A.assert_fields(
        completed,
        logistics_status="COMPLETED",
        manifest_status="SEALED",
        units_picked_up_total=10,
    )

    confirm_after = api.confirm_donation_pickup(pickup["id"], chain.partner_headers)
    validate_error(confirm_after, "ERR_PICKUP_NOT_CONFIRMABLE", expected_status=409)

    reconciled = validate_success(
        api.reconcile_donation_pickup(pickup["id"], manager_headers())
    )
    A.assert_fields(reconciled, manifest_status="RECONCILED", logistics_status="COMPLETED")
    A.assert_money_cents(
        reconciled["provisional_value_cents"], 5990, "provisional_value_cents"
    )
    A.assert_money_cents(reconciled["manifest_credit_cents"], 3744, "manifest_credit_cents")

    picked_up = validate_success(api.get_donation_assignment(line_one["id"], manager_headers()))
    A.assert_fields(picked_up, status="PICKED_UP", quantity_units=10)
    A.assert_money_cents(picked_up["line_credit_cents"], 3744, "line_credit_cents")

    donated = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(donated, status="DONATED", units_donated=10, quantity_on_hand=0)
    A.assert_lot_units_conservation(donated)

    untouched = F.reload_lot(api, lot_two["id"])
    A.assert_fields(untouched, status="FRESH", quantity_on_hand=10, units_donated=0)

    partner = validate_success(api.get_food_bank_partner(chain.partner["id"], admin_headers()))
    A.assert_fields(partner, pickups_completed_count=1, units_received_total=10)


def test_five_audit_gates_run_from_an_unopened_window_to_an_already_closed_finding(api):
    """The sweep, the second sweep, the escalation, the two remediations and the second waiver.

    PRD 3.8: "Sweeping an audit is a once-only act, and it requires `sweep_status` to still be
    `NOT_STARTED`; a second sweep is refused with `ERR_AUDIT_ALREADY_SWEPT` and HTTP 409. It
    also requires the logical clock to be inside the audit's window -- at or after
    `window_start_at` and strictly before `window_end_at` -- and a clock outside that half-open
    interval is refused with `ERR_AUDIT_WINDOW_NOT_OPEN` and HTTP 409."

    PRD 3.8: "An audit whose `severity` is anything other than `CRITICAL` is refused with
    `ERR_ESCALATION_NOT_WARRANTED` and HTTP 422".

    PRD 3.8: "Supplying neither `remediation` nor `waive` is refused with
    `ERR_REMEDIATION_NOT_PERMITTED` and HTTP 422."

    PRD 3.8: "Sending `remediation` as `WITHDRAWN` is the substantive path, available to both
    roles, and it requires the finding's lot to still hold units -- a lot already at zero is
    refused with `ERR_REMEDIATION_NOT_PERMITTED`."

    PRD 3.8: "A finding must be `OPEN`; closing an already-closed one is refused with
    `ERR_FINDING_ALREADY_RESOLVED`."

    PRD 3.8: "A waiver is only permitted when the finding scored at `severity_multiplier` 1 --
    that is, when `hours_past_date` fell at or inside the department's
    `past_date_tolerance_hours`. [...] A waiver moves `status` from `OPEN` to `WAIVED`, leaves
    `remediation` at `NONE`, records `resolved_by_user_id`, increments the finding's `version`
    by one, **leaves the lot on the shelf entirely untouched**".

    PRD 3.8: "Once the audit has been swept and every one of its findings has reached
    `RESOLVED` or `WAIVED`, the audit's `disposition_status` moves to `REMEDIATED` -- from
    `PENDING` or from `ESCALATED` alike".

    Arithmetic.  The lot was produced 2026-07-30 against a 10-day shelf life, so its
    `sell_by_at` is 2026-08-09T00:00:00.000Z; the sweep runs at 02:00 that morning, which is
    7,200 seconds, a floor of 2 whole hours past date.  That is at or below the department's
    default tolerance of 4 hours, so the multiplier is 1 and `severity_points` is 4 units x 1,
    banding the audit as `MINOR` on the 1-through-9 range -- which is precisely why the
    escalation is not warranted.  The withdrawal then books 4 units at 420 cents plus the 3.5
    percent surcharge, that is 1,739 cents of shrink against no cost of goods at all, so the
    trailing ratio lands on 100.00 percent and clause 3 of PRD 2.8 holds the department at
    `WATCH` once its last finding has closed.

    Design: Corner/errors/audit_and_finding_gates_from_window_to_closure
    """
    chain = F.build_meat_chain(
        api,
        clock="2026-08-08T06:00:00.000Z",
        lot_overrides={"production_date": "2026-07-30", "quantity_original": 4},
    )
    audit = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-09T00:00:00.000Z",
        "2026-08-10T00:00:00.000Z",
    )
    A.assert_fields(audit, sweep_status="NOT_STARTED", disposition_status="PENDING")

    before_window = api.sweep_compliance_audit(audit["id"], auditor_headers())
    validate_error(before_window, "ERR_AUDIT_WINDOW_NOT_OPEN", expected_status=409)
    A.assert_fields(F.reload_audit(api, audit["id"]), sweep_status="NOT_STARTED")

    F.set_clock(api, "2026-08-09T02:00:00.000Z")
    swept = F.sweep_audit(api, audit["id"])
    A.assert_fields(
        swept,
        sweep_status="SWEPT",
        disposition_status="PENDING",
        past_date_lot_count=1,
        past_date_units_total=4,
        severity_points_total=4,
        severity="MINOR",
    )

    again = api.sweep_compliance_audit(audit["id"], auditor_headers())
    validate_error(again, "ERR_AUDIT_ALREADY_SWEPT", expected_status=409)

    not_critical = api.escalate_compliance_audit(
        audit["id"], {"escalation_note": "walk the case again"}, auditor_headers()
    )
    validate_error(not_critical, "ERR_ESCALATION_NOT_WARRANTED", expected_status=422)
    A.assert_fields(F.reload_audit(api, audit["id"]), disposition_status="PENDING")

    rows, meta = validate_paginated(
        api.list_audit_findings(
            auditor_headers(),
            params={"audit_id": audit["id"], "status": "OPEN", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, (
        f"the sweep wrote one finding per past-date lot, got total_count {meta['total_count']}"
    )
    finding = rows[0]
    A.assert_fields(
        finding,
        lot_id=chain.lot["id"],
        hours_past_date=2,
        units_on_shelf=4,
        severity_multiplier=1,
        severity_points=4,
        remediation="NONE",
        status="OPEN",
    )

    neither_field = api.remediate_audit_finding(
        finding["id"], {"resolution_note": "no action recorded"}, auditor_headers()
    )
    validate_error(neither_field, "ERR_REMEDIATION_NOT_PERMITTED", expected_status=422)

    withdrawn = F.withdraw_lot(
        api, chain.lot["id"], reason_note="pulled by the night crew"
    )
    A.assert_fields(withdrawn, status="WITHDRAWN", quantity_on_hand=0)

    empty_lot = api.remediate_audit_finding(
        finding["id"],
        {"remediation": "WITHDRAWN", "resolution_note": "already off the shelf"},
        auditor_headers(),
    )
    validate_error(empty_lot, "ERR_REMEDIATION_NOT_PERMITTED", expected_status=422)
    A.assert_fields(F.reload_finding(api, finding["id"]), status="OPEN", remediation="NONE")

    waived = F.remediate_finding(
        api, finding["id"], waive=True, resolution_note="inside tolerance"
    )
    A.assert_fields(waived, status="WAIVED", remediation="NONE")
    assert waived["resolved_by_user_id"], "a waiver records the acting auditor"

    twice = api.remediate_audit_finding(
        finding["id"], {"waive": True, "resolution_note": "again"}, auditor_headers()
    )
    validate_error(twice, "ERR_FINDING_ALREADY_RESOLVED", expected_status=409)

    bubbled = F.reload_audit(api, audit["id"])
    A.assert_fields(bubbled, disposition_status="REMEDIATED", sweep_status="SWEPT")

    department = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(
        department, "WATCH", shrink_cost_ratio_pct=100.00, open_finding_count=0
    )


def test_three_recommendation_refusals_leave_the_items_version_where_it_stood(api):
    """Both arms of the window rule, then the empty window, then the once-only issue.

    PRD 3.9: "The window must have an end date at or after its start date and must span at most
    31 days; a reversed or over-long window is refused with `ERR_RECOMMENDATION_WINDOW_INVALID`
    and HTTP 422."

    PRD 3.9: "`received_units` is the sum of `quantity_original` across every lot of the item
    created inside the window; if that comes to 0 there is no history to reason from, and the
    request is refused with `ERR_INSUFFICIENT_SHRINK_HISTORY` and HTTP 422."

    PRD 3.9: "`CHRONOLOGICAL_ACTUAL`, which is the default when `method` is omitted, counts only
    shrink events in `VERIFIED` or `POSTED` -- money the department has already recognised."

    PRD 3.9: "Finally `recommended_order_units` is the item's `daily_forecast_units` multiplied
    by a three-day order horizon, dampened by the shrink rate -- that is, multiplied by one
    minus the shrink rate expressed as a fraction -- with `open_units` subtracted, the result
    rounded half up to a whole number, and then floored at 0 so the recommendation is never
    negative. **The dampener uses the already-rounded two-decimal `shrink_rate_pct`, not the raw
    unrounded ratio.**"

    PRD 3.9: "A new recommendation lands in `DRAFT` with `issued_by_user_id` null, and it writes
    `received_units`, `shrink_units`, `shrink_rate_pct`, `open_units` and
    `recommended_order_units`. Creating it **increments the item's `version` by one**".

    PRD 3.9: "Issuing a recommendation to the buying system requires its `status` to be `DRAFT`,
    refusing anything else with `ERR_RECOMMENDATION_NOT_ISSUABLE` and HTTP 409".

    Arithmetic.  The single 24-unit lot was created inside the one-day window, so
    `received_units` is 24 and the verified 2-unit DAMAGE event gives `shrink_units` 2:
    2 / 24 * 100 = 8.3333..., that is 8.33 to two places.  20 units sold and 2 written off
    leave 2 units on a still-`FRESH` lot, so `open_units` is 2.  The order number is
    4.00 x 3 x (1 - 0.0833) = 11.0004, less 2 open units, that is 9.0004 rounded half up to 9.
    None of the three refusals may move the item's `version`, because none of them creates a
    recommendation.

    Design: Corner/errors/recommendation_window_and_issue_gates
    """
    chain = F.build_meat_chain(api)
    F.post_sale(api, chain.lot["id"], 20, register_lane_code="L07")
    event = F.record_shrink(
        api, chain.lot["id"], 2, "DAMAGE", headers=make_clerk_headers(RECORDER_USER_ID)
    )
    F.verify_shrink(api, event["id"], headers=make_manager_headers(VERIFIER_USER_ID))
    on_shelf = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(on_shelf, status="FRESH", quantity_on_hand=2, units_shrunk=2, units_sold=20)

    reversed_window = api.create_order_recommendation(
        factories.create_order_recommendation_payload(
            chain.item["id"], "2026-08-10", "2026-08-09", 1
        ),
        manager_headers(),
    )
    validate_error(reversed_window, "ERR_RECOMMENDATION_WINDOW_INVALID", expected_status=422)

    too_long = api.create_order_recommendation(
        factories.create_order_recommendation_payload(
            chain.item["id"], "2026-07-01", "2026-08-31", 1
        ),
        manager_headers(),
    )
    validate_error(too_long, "ERR_RECOMMENDATION_WINDOW_INVALID", expected_status=422)

    no_history = api.create_order_recommendation(
        factories.create_order_recommendation_payload(
            chain.item["id"], "2026-08-01", "2026-08-05", 1
        ),
        manager_headers(),
    )
    validate_error(no_history, "ERR_INSUFFICIENT_SHRINK_HISTORY", expected_status=422)

    A.assert_fields(F.reload_item(api, chain.item["id"]), version=1)
    _rows, empty_meta = validate_paginated(
        api.list_order_recommendations(
            manager_headers(), params={"item_id": chain.item["id"], "limit": 10, "offset": 0}
        )
    )
    assert empty_meta["total_count"] == 0, (
        "all three refusals happened before any recommendation row was written, got "
        f"total_count {empty_meta['total_count']}"
    )

    recommendation = F.build_recommendation(
        api, chain.item, "2026-08-10", "2026-08-10", expected_item_version=1
    )
    A.assert_fields(
        recommendation,
        status="DRAFT",
        method="CHRONOLOGICAL_ACTUAL",
        received_units=24,
        shrink_units=2,
        open_units=2,
        recommended_order_units=9,
    )
    A.assert_percent(recommendation["shrink_rate_pct"], 8.33, "shrink_rate_pct")
    A.assert_absent_or_none(
        recommendation, "issued_by_user_id", "supersedes_recommendation_id"
    )

    A.assert_fields(F.reload_item(api, chain.item["id"]), version=2)

    issued = validate_success(
        api.issue_order_recommendation(recommendation["id"], manager_headers())
    )
    A.assert_fields(issued, status="ISSUED")
    assert issued["issued_by_user_id"], "issuance records the acting manager"

    twice = api.issue_order_recommendation(recommendation["id"], manager_headers())
    validate_error(twice, "ERR_RECOMMENDATION_NOT_ISSUABLE", expected_status=409)

    rows, meta = validate_paginated(
        api.list_order_recommendations(
            manager_headers(),
            params={
                "item_id": chain.item["id"],
                "status": "ISSUED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one recommendation reached ISSUED, got total_count {meta['total_count']}"
    )
    A.assert_ids_equal(rows, [recommendation["id"]])
