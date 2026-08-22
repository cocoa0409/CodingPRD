"""Formulary standing, cycle counts and the par-level replenishment projection."""

from test_helpers import (
    ApiErrorId,
    adjust_on_hand,
    adjust_on_hand_payload,
    assert_formulary_item,
    assert_replenishment_suggestion,
    create_formulary_item_payload,
    create_item,
    create_supply_room,
    decide_formulary_item,
    formulary_decision_payload,
    make_clinician_headers,
    make_materials_manager_headers,
    map_formulary_item,
    read_formulary_item,
    validate_error,
    validate_paginated,
    validate_success,
    SECOND_CLINICIAN_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]


def _mapping_at_reorder_point(lum_enabled=None):
    """An APPROVED mapping with par 100, reorder point 30 and 24 eaches to a
    case, driven to on_hand_qty exactly 30 by one cycle-count adjustment."""
    room = create_supply_room(
        facility_code="FAC-PAR",
        gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-PAR-PROBE-CS",
        description="Par probe, case of 24",
        manufacturer_code="MFR-ACME",
        uom="CS",
        wac_cents=7000,
        handling_class="AMBIENT",
        units_per_parent=24,
    )
    overrides = {"facility_item_code": "FAC-PAR-PROBE", "par_qty": 100,
                 "reorder_point": 30}
    if lum_enabled is not None:
        overrides["lum_enabled"] = lum_enabled
    mapping = map_formulary_item(room["id"], item["id"], **overrides)
    approved = decide_formulary_item(mapping["id"], "APPROVED")
    adjusted = adjust_on_hand(mapping["id"], room["id"], 30, approved["version"])
    return room, item, adjusted


def test_reorder_point_equal_to_par_qty_is_a_schema_violation(api):
    """PRD §2.9: "**Request schema.** Every required input field present, types
    correct, enum values inside their declared sets, integer bounds honoured
    (`requested_qty` greater than zero, `par_qty` greater than zero,
    `reorder_point` at least zero and strictly below `par_qty`,
    `floor_price_cents` greater than zero, `effective_to` strictly after
    `effective_from`, `window_open_min` at least zero and strictly below
    `window_close_min` which is at most 1439, `service_minutes` greater than
    zero, `arrival_min` between zero and 1439 inclusive), and pagination within
    its declared range — otherwise `ERR_VALIDATION` (400). Applies everywhere."

    Design: Corner/entities/formulary_item_rejects_reorder_point_not_below_par_qty
    """
    room = create_supply_room(
        facility_code="FAC-102", room_code="GEN-102", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-PAR-CS", description="Par bound probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=1000, handling_class="AMBIENT", units_per_parent=10,
    )

    response = api.create_formulary_item(
        room["id"],
        create_formulary_item_payload(
            item["id"], facility_item_code="FAC-PAR", par_qty=100, reorder_point=100
        ),
        make_materials_manager_headers(room["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    _rows, meta = validate_paginated(
        api.list_formulary_items(
            ADMIN, params={"supply_room_id": room["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, "the refused mapping must not be written"


def test_delisted_mapping_refuses_any_further_decision(api):
    """PRD §3.3: "`DELISTED` is terminal: any decision requested against a
    delisted mapping, and any decision requested from a state that does not
    permit it, is `ERR_FORMULARY_STATE_INVALID` (HTTP 409)."
    PRD §3.3: "Clinical standing is a `Clinician`'s decision, recorded as a
    `decision` of `APPROVED`, `RESTRICTED` or `DELISTED`, and every decision
    stamps `decided_by_user_id` with the acting user."

    Design: Corner/state_machines/formulary_decision_on_delisted_mapping_is_rejected
    """
    room = create_supply_room(
        facility_code="FAC-205", room_code="GEN-205", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-SM5-CS", description="Delist probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=2000, handling_class="AMBIENT", units_per_parent=10,
    )
    mapping = map_formulary_item(
        room["id"], item["id"], facility_item_code="FAC-SM5", par_qty=50,
        reorder_point=10,
    )
    decide_formulary_item(mapping["id"], "APPROVED")
    delisted = decide_formulary_item(mapping["id"], "DELISTED")
    assert delisted["formulary_status"] == "DELISTED"

    response = api.decide_formulary_item(
        mapping["id"],
        formulary_decision_payload("APPROVED"),
        make_clinician_headers(SECOND_CLINICIAN_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_FORMULARY_STATE_INVALID.value, 409)

    after = read_formulary_item(mapping["id"])
    assert_formulary_item(after)
    assert after["formulary_status"] == "DELISTED"
    assert after["decided_by_user_id"] == "clin-1", (
        "the refused decision must not restamp decided_by_user_id"
    )


def test_second_mapping_of_the_same_item_into_the_same_room_is_refused(api):
    """PRD §3.3: "Each room may map any given item once only; a repeat is
    `ERR_DUPLICATE_FORMULARY_ITEM`."

    Design: Corner/validations/duplicate_formulary_mapping_for_same_room_and_item_rejected
    """
    room = create_supply_room(
        facility_code="FAC-407", room_code="GEN-407", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-DUPFI-CS", description="Duplicate mapping probe",
        manufacturer_code="MFR-ACME", uom="CS", wac_cents=2000,
        handling_class="AMBIENT", units_per_parent=10,
    )
    first = map_formulary_item(
        room["id"], item["id"], facility_item_code="FAC-DUP-1", par_qty=50,
        reorder_point=10,
    )

    response = api.create_formulary_item(
        room["id"],
        create_formulary_item_payload(
            item["id"], facility_item_code="FAC-DUP-2", par_qty=80, reorder_point=20
        ),
        make_materials_manager_headers(room["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_FORMULARY_ITEM.value, 409)

    _rows, meta = validate_paginated(
        api.list_formulary_items(
            ADMIN, params={"supply_room_id": room["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    kept = read_formulary_item(first["id"])
    assert kept["facility_item_code"] == "FAC-DUP-1"
    assert kept["par_qty"] == 50


def test_replenishment_suggestion_persists_nothing(api):
    """PRD §3.3: "Replenishment suggestions are a pure projection: they read a
    mapping, compute a recommendation, persist nothing, and are available to
    both a `MaterialsManager` for its own room and to a `ContractAdmin`."
    PRD §3.3: "Under `LUM_SPLIT`, cases and loose eaches may be mixed: the
    suggested case quantity is the deficit divided by `units_per_parent`
    **rounded down** to a whole case; the suggested each quantity is whatever
    remains after removing those whole cases from the deficit; and the suggested
    total in eaches equals the deficit exactly."

    Design: Corner/endpoints/replenishment_suggestion_is_a_pure_computed_read
    """
    room = create_supply_room(
        facility_code="FAC-500", room_code="GEN-500", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-RO-CS", description="Read-only probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=3000, handling_class="AMBIENT", units_per_parent=12,
    )
    mapping = map_formulary_item(
        room["id"], item["id"], facility_item_code="FAC-RO", par_qty=40,
        reorder_point=10,
    )
    approved = decide_formulary_item(mapping["id"], "APPROVED")
    stocked = adjust_on_hand(mapping["id"], room["id"], 5, approved["version"])
    assert stocked["on_hand_qty"] == 5

    first = validate_success(
        api.get_replenishment_suggestion(
            mapping["id"], ADMIN, params={"variant": "LUM_SPLIT"}
        ),
        200,
    )
    second = validate_success(
        api.get_replenishment_suggestion(
            mapping["id"], ADMIN, params={"variant": "LUM_SPLIT"}
        ),
        200,
    )
    assert_replenishment_suggestion(first)

    assert first["suggested_case_qty"] == 2, "35 eaches of deficit is 2 whole cases of 12"
    assert first["suggested_each_qty"] == 11, "35 - 2 * 12 = 11 loose eaches"
    assert second["suggested_case_qty"] == first["suggested_case_qty"]
    assert second["suggested_each_qty"] == first["suggested_each_qty"]

    after = read_formulary_item(mapping["id"])
    assert after["on_hand_qty"] == 5
    assert after["version"] == stocked["version"], (
        "a pure projection may not advance the mapping's version"
    )


def test_stale_formulary_item_version_is_refused_on_the_second_adjustment(api):
    """PRD §2.7: "Posting a cycle-count delta —
    `POST /formulary-items/{formulary_item_id}/adjust-on-hand` — requires a
    non-optional `expected_formulary_item_version` field carrying the client's
    last observed `version` of the target `FormularyItem`. A mismatch against
    the formulary item's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §2.7: "A successful adjustment advances the formulary item's `version`
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_formulary_item_version_rejected_on_second_adjustment
    """
    room = create_supply_room(
        facility_code="FAC-801", room_code="GEN-801", gpo_member_class="ACUTE",
        room_type="GENERAL_STORE",
    )
    item = create_item(
        sku="SKU-OCC2-CS", description="OCC par probe", manufacturer_code="MFR-ACME",
        uom="CS", wac_cents=4000, handling_class="AMBIENT", units_per_parent=12,
    )
    mapping = map_formulary_item(
        room["id"], item["id"], facility_item_code="FAC-OCC2", par_qty=60,
        reorder_point=12,
    )
    approved = decide_formulary_item(mapping["id"], "APPROVED")
    version_at_approval = approved["version"]

    first = adjust_on_hand(mapping["id"], room["id"], 20, version_at_approval)
    assert first["on_hand_qty"] == 20
    assert first["version"] == version_at_approval + 1

    stale = api.adjust_on_hand(
        mapping["id"],
        adjust_on_hand_payload(7, version_at_approval),
        make_materials_manager_headers(room["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    unchanged = read_formulary_item(mapping["id"])
    assert unchanged["on_hand_qty"] == 20, "the refused delta must not be applied"
    assert unchanged["version"] == first["version"]

    retried = adjust_on_hand(mapping["id"], room["id"], 7, first["version"])
    assert retried["on_hand_qty"] == 27


class TestReplenishmentVariants:
    """The two suggestion variants disagree on identical mapping state."""

    def test_standard_topoff_suggests_whole_cases_only(self, api):
        """PRD §3.3: "Under `STANDARD_TOPOFF`, only whole cases may be picked:
        the suggested case quantity is the deficit in eaches divided by the
        item's `units_per_parent`, **rounded up** to the next whole case; the
        suggested each quantity is zero; and the suggested total in eaches is
        the case quantity multiplied by `units_per_parent`."
        PRD §3.3: "When it passes, `eligible` is true and the deficit is the par
        level minus the on-hand count, in eaches."

        Design: Difficulty/dual_variant_calc/par_suggestion_standard_topoff_vs_lum_split_diverge
        """
        _room, _item, mapping = _mapping_at_reorder_point(lum_enabled=True)
        assert mapping["on_hand_qty"] == 30

        suggestion = validate_success(
            api.get_replenishment_suggestion(
                mapping["id"], ADMIN, params={"variant": "STANDARD_TOPOFF"}
            ),
            200,
        )
        assert_replenishment_suggestion(suggestion)

        assert suggestion["eligible"] is True
        assert suggestion["deficit_eaches"] == 70
        assert suggestion["suggested_case_qty"] == 3
        assert suggestion["suggested_each_qty"] == 0
        assert suggestion["suggested_total_eaches"] == 72
        assert suggestion["variant"] == "STANDARD_TOPOFF"

    def test_lum_split_suggests_cases_plus_loose_eaches(self, api):
        """PRD §3.3: "Under `LUM_SPLIT`, cases and loose eaches may be mixed: the
        suggested case quantity is the deficit divided by `units_per_parent`
        **rounded down** to a whole case; the suggested each quantity is whatever
        remains after removing those whole cases from the deficit; and the
        suggested total in eaches equals the deficit exactly."
        PRD §3.3: "How that deficit is turned into a pick depends on the
        `variant` requested, and the response echoes the requested variant back."

        Design: Difficulty/dual_variant_calc/par_suggestion_standard_topoff_vs_lum_split_diverge
        """
        _room, _item, mapping = _mapping_at_reorder_point(lum_enabled=True)

        suggestion = validate_success(
            api.get_replenishment_suggestion(
                mapping["id"], ADMIN, params={"variant": "LUM_SPLIT"}
            ),
            200,
        )
        assert_replenishment_suggestion(suggestion)

        assert suggestion["eligible"] is True
        assert suggestion["deficit_eaches"] == 70
        assert suggestion["suggested_case_qty"] == 2
        assert suggestion["suggested_each_qty"] == 22
        assert suggestion["suggested_total_eaches"] == 70
        assert suggestion["variant"] == "LUM_SPLIT"

    def test_the_two_variants_disagree_on_identical_mapping_state(self, api):
        """PRD §3.3: "For a mapping with a par level of 100 eaches, 30 eaches on
        hand and 24 eaches to a case, the two variants disagree by design:
        whole-case top-off suggests 3 cases and 72 eaches, while the split
        variant suggests 2 cases plus 22 loose eaches and 70 eaches in total."

        Design: Difficulty/dual_variant_calc/par_suggestion_standard_topoff_vs_lum_split_diverge
        """
        _room, _item, mapping = _mapping_at_reorder_point(lum_enabled=True)

        topoff = validate_success(
            api.get_replenishment_suggestion(
                mapping["id"], ADMIN, params={"variant": "STANDARD_TOPOFF"}
            ),
            200,
        )
        split = validate_success(
            api.get_replenishment_suggestion(
                mapping["id"], ADMIN, params={"variant": "LUM_SPLIT"}
            ),
            200,
        )

        assert topoff["suggested_total_eaches"] == 72
        assert split["suggested_total_eaches"] == 70
        assert topoff["suggested_total_eaches"] != split["suggested_total_eaches"], (
            "the whole-case variant over-ships against the split variant"
        )
        assert topoff["deficit_eaches"] == split["deficit_eaches"] == 70
        assert topoff["eligible"] is True and split["eligible"] is True


class TestReorderPointBoundary:
    """The replenishment gate compares on-hand against the reorder point
    inclusively."""

    def test_replenishment_is_due_at_exactly_the_reorder_point(self, api):
        """PRD §3.3: "Eligibility is a two-part gate — the mapping's
        `formulary_status` must be `APPROVED` **and** its `on_hand_qty` must be
        less than or equal to its `reorder_point`. The boundary is inclusive: a
        count exactly equal to the reorder point **is** due for replenishment,
        while a count one greater is not."

        Design: Difficulty/boundary_precision_check/replenishment_due_at_exactly_reorder_point_not_one_above
        """
        _room, _item, mapping = _mapping_at_reorder_point()
        assert mapping["on_hand_qty"] == 30, "on hand sits exactly on the reorder point"

        suggestion = validate_success(
            api.get_replenishment_suggestion(
                mapping["id"], ADMIN, params={"variant": "STANDARD_TOPOFF"}
            ),
            200,
        )
        assert suggestion["eligible"] is True
        assert suggestion["suggested_total_eaches"] == 72

    def test_replenishment_is_not_due_one_each_above_the_reorder_point(self, api):
        """PRD §3.3: "Eligibility is a two-part gate — the mapping's
        `formulary_status` must be `APPROVED` **and** its `on_hand_qty` must be
        less than or equal to its `reorder_point`. The boundary is inclusive: a
        count exactly equal to the reorder point **is** due for replenishment,
        while a count one greater is not."
        PRD §3.3: "When the gate fails, the response reports `eligible` as false
        and `deficit_eaches`, `suggested_case_qty`, `suggested_each_qty` and
        `suggested_total_eaches` all as zero."

        Design: Difficulty/boundary_precision_check/replenishment_due_at_exactly_reorder_point_not_one_above
        """
        room, _item, mapping = _mapping_at_reorder_point()
        above = adjust_on_hand(mapping["id"], room["id"], 1, mapping["version"])
        assert above["on_hand_qty"] == 31

        suggestion = validate_success(
            api.get_replenishment_suggestion(
                mapping["id"], ADMIN, params={"variant": "STANDARD_TOPOFF"}
            ),
            200,
        )
        assert suggestion["eligible"] is False
        assert suggestion["deficit_eaches"] == 0
        assert suggestion["suggested_case_qty"] == 0
        assert suggestion["suggested_each_qty"] == 0
        assert suggestion["suggested_total_eaches"] == 0
