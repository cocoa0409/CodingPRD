"""Registry resources: declared defaults, server-stamped fields and read shapes."""

from test_helpers import (
    ApiErrorId,
    CAP_SOURCE_DEMAND,
    HARVEST_WILD,
    KIOSK_PROVISIONING,
    LICENSE_ACTIVE,
    OPS_ALTERNATE_ID,
    PACK_ON_SHELF,
    PLAN_DRAFT,
    POS_NOT_CONNECTED,
    POSTURE_FACTOR_CLEAR,
    SETTLEMENT_DRAFT,
    SPACE_UNVERIFIED,
    UNKNOWN_CHEF_ID,
    UNKNOWN_FISH_LOT_ID,
    add_draft_plan,
    add_kiosk,
    assert_close,
    assert_host_store,
    assert_instant_equals,
    assert_license_agreement,
    assert_pack_lot,
    assert_production_plan,
    assert_settlement_statement,
    base_world,
    certification_payload,
    cold_chain_reading_payload,
    fish_lot_payload,
    host_store_payload,
    list_meta,
    make_franchisor_ops_headers,
    pack_lot_payload,
    settled_world,
    shelf_ready_world,
    validate_error,
    validate_list,
    validate_success,
)


def test_host_store_registration_returns_declared_defaults(api):
    """A newly registered store carries the declared integration and space defaults.

    "A newly registered store starts with `pos_integration_status` of
    `NOT_CONNECTED`, `pos_terminal_count` of 0, `space_compliance_state` of
    `UNVERIFIED`, and `attested_sushi_space_sqft`, `attested_case_linear_ft` and
    `last_attested_on` all null."

    Design: Corner/entities/host_store_creation_returns_declared_defaults
    """
    response = api.create_host_store(host_store_payload(), make_franchisor_ops_headers())
    store = validate_success(response, 201)
    assert_host_store(store)

    assert store["pos_integration_status"] == POS_NOT_CONNECTED
    assert store["pos_terminal_count"] == 0
    assert store["space_compliance_state"] == SPACE_UNVERIFIED
    assert store["attested_sushi_space_sqft"] is None
    assert store["attested_case_linear_ft"] is None
    assert store["last_attested_on"] is None
    assert store["version"] == 1
    assert_instant_equals(store["updated_at"], store["created_at"])
    assert store["name"] == "Northgate Market 418"
    assert store["weekly_traffic_count"] == 63000
    assert store["refrigerated_case_capacity_packs"] == 400


def test_license_agreement_read_returns_the_stored_row(api):
    """Reading an activated agreement returns its stored terms and derived counters.

    "Activation recomputes `space_shortfall_sqft` from the store's current
    attestation, re-derives the store's `space_compliance_state` against this
    agreement's obligations, and increments the agreement's `version` by 1."

    Design: Corner/entities/license_agreement_retrieval_returns_stored_row
    """
    world = base_world()

    response = api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    agreement = validate_success(response)
    assert_license_agreement(agreement)

    assert agreement["status"] == LICENSE_ACTIVE
    assert agreement["host_store_id"] == world["host_store_id"]
    assert agreement["min_space_sqft_obligation"] == 220
    assert_close(agreement["min_case_linear_ft_obligation"], 18.0, places=1)
    assert agreement["space_credit_cents_per_sqft"] == 1250
    assert agreement["effective_from"] == "2026-08-01"
    assert agreement["effective_to"] == "2027-07-31"
    assert agreement["space_shortfall_sqft"] == 0
    assert agreement["active_kiosk_count"] == 1
    assert agreement["lifetime_share_accrued_cents"] == 0
    assert agreement["suspension_reason"] is None


def test_kiosk_listing_pages_with_total_count_and_has_more(api):
    """The kiosk list applies limit and offset and reports the unpaged total.

    "For list responses the `meta` object carries `limit` and `offset` as they
    were applied, `total_count` as the number of rows matching the filters before
    pagination, and `has_more` as true when rows remain beyond the current
    window."

    Design: Corner/entities/kiosk_listing_is_paginated_with_total_count_and_has_more
    """
    world = base_world()
    add_kiosk(world, "K-418-B", "Mika Sato")

    first_page = api.list_kiosks(world["ops_headers"], {"limit": 1, "offset": 0})
    items = validate_list(first_page, expected_total=2)
    meta = list_meta(first_page)
    assert len(items) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    second_page = api.list_kiosks(world["ops_headers"], {"limit": 1, "offset": 1})
    second_items = validate_list(second_page, expected_total=2)
    assert len(second_items) == 1
    assert second_items[0]["id"] != items[0]["id"]
    assert list_meta(second_page)["has_more"] is False

    defaults = api.list_kiosks(world["ops_headers"])
    validate_list(defaults, expected_total=2)
    default_meta = list_meta(defaults)
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["has_more"] is False


def test_kiosk_listing_rejects_limits_outside_the_declared_bounds(api):
    """A limit below one or above one hundred is a schema violation.

    "`limit` defaults to 10, may not be smaller than 1 and may not be larger than
    100; `offset` defaults to 0 and may not be negative. A value outside those
    bounds is a schema violation and is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/kiosk_listing_is_paginated_with_total_count_and_has_more
    """
    world = base_world()

    validate_error(
        api.list_kiosks(world["ops_headers"], {"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.list_kiosks(world["ops_headers"], {"limit": 101}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.list_kiosks(world["ops_headers"], {"offset": -1}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    filtered = api.list_kiosks(world["ops_headers"], {"operational_state": "SUSPENDED"})
    validate_list(filtered, expected_total=0)


def test_fish_lot_read_with_an_unresolvable_id_is_not_found(api):
    """A sourcing id that resolves to nothing yields the sourcing not-found code.

    "Every id the request references resolves." The applicable code for a fish lot
    is `ERR_SOURCING_RECORD_NOT_FOUND` at HTTP 404.

    Design: Corner/entities/fish_lot_get_with_unknown_id_returns_not_found
    """
    world = base_world()

    validate_error(
        api.get_fish_lot(UNKNOWN_FISH_LOT_ID, world["ops_headers"]),
        ApiErrorId.ERR_SOURCING_RECORD_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_cold_chain_readings(UNKNOWN_FISH_LOT_ID, world["ops_headers"]),
        ApiErrorId.ERR_SOURCING_RECORD_NOT_FOUND.value,
        404,
    )


def test_pack_lot_build_without_pack_count_is_a_schema_violation(api):
    """Omitting a required field is rejected and consumes nothing.

    "Required fields present, types correct, enum values inside their declared
    set, numeric range constraints respected, ISO 8601 instants well formed, and
    every start/end pair strictly ordered with the start before the end.
    Violations are `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/pack_lot_create_missing_required_pack_count_returns_invalid_request
    """
    world = shelf_ready_world()
    payload = pack_lot_payload(world["rice_batch_id"], world["fish_lot_id"])
    payload.pop("pack_count")

    validate_error(
        api.create_pack_lot(payload, world["chef_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_list(api.list_pack_lots(world["ops_headers"]), expected_total=0)
    batch = validate_success(api.get_rice_batch(world["rice_batch_id"], world["ops_headers"]))
    assert batch["status"] == "APPROVED"
    lot = validate_success(api.get_fish_lot(world["fish_lot_id"], world["ops_headers"]))
    assert_close(lot["allocated_kg"], 0.0)
    assert_close(lot["remaining_kg"], 12.0)
    plan = validate_success(api.get_production_plan(world["plan_id"], world["ops_headers"]))
    assert plan["actual_pack_count"] == 0


def test_production_plan_creation_applies_declared_defaults(api):
    """A fresh plan is DRAFT with its targets frozen and its actuals still empty.

    "From the pack target the plan derives `planned_rice_kg`, the pack count
    multiplied by 0.12 kilograms of cooked rice per pack — 120 grams — rounded half
    up to two decimal places."

    Design: Corner/entities/production_plan_creation_applies_declared_defaults
    """
    world = base_world()
    plan = add_draft_plan(world)
    assert_production_plan(plan)

    assert plan["status"] == PLAN_DRAFT
    assert plan["kiosk_id"] == world["kiosk_id"]
    assert plan["production_date"] == "2026-08-03"
    assert plan["traffic_forecast"] == 9000
    assert plan["planned_pack_count"] == 162
    assert_close(plan["planned_rice_kg"], 19.44, places=2)
    assert_close(plan["posture_factor_applied"], POSTURE_FACTOR_CLEAR, places=2)
    assert plan["binding_cap_source"] == CAP_SOURCE_DEMAND
    assert plan["actual_pack_count"] == 0
    assert plan["forecast_variance_pct"] is None
    assert plan["superseded_plan_id"] is None
    assert plan["void_reason"] is None
    assert plan["version"] == 1


def test_pack_lot_computed_fields_ignore_client_supplied_values(api):
    """Shelf expiry and consumed fish mass are computed, not accepted from the body.

    "Its `shelf_expiry_at` is `produced_at` plus 720 minutes, the twelve hours a
    case-held sushi pack is allowed. Its `consumed_fish_kg` is `pack_count`
    multiplied by 0.045 kilograms of fish per pack, rounded half up to three decimal
    places"

    Design: Corner/entities/pack_lot_computed_fields_ignore_extra_field_input
    """
    world = shelf_ready_world()
    payload = pack_lot_payload(
        world["rice_batch_id"],
        world["fish_lot_id"],
        shelf_expiry_at="2026-08-04T00:00:00Z",
        consumed_fish_kg=99.0,
    )

    pack_lot = validate_success(api.create_pack_lot(payload, world["chef_headers"]), 201)
    assert_pack_lot(pack_lot)

    assert_instant_equals(pack_lot["shelf_expiry_at"], "2026-08-03T20:00:00Z")
    assert_close(pack_lot["consumed_fish_kg"], 7.200)
    assert pack_lot["status"] == PACK_ON_SHELF
    assert pack_lot["sold_count"] == 0
    assert pack_lot["discarded_count"] == 0
    assert pack_lot["unsold_count"] == 160

    lot = validate_success(api.get_fish_lot(world["fish_lot_id"], world["ops_headers"]))
    assert_close(lot["allocated_kg"], 7.200)
    assert_close(lot["remaining_kg"], 4.800)
    batch = validate_success(api.get_rice_batch(world["rice_batch_id"], world["ops_headers"]))
    assert batch["status"] == "CONSUMED"


def test_settlement_statement_system_fields_are_server_stamped(api):
    """The drafting operator is recorded from the header and the lifecycle fields start null.

    "The new statement starts in `DRAFT` with `revision_round` 1,
    `created_by_user_id` taken from the acting header, and `issued_by_user_id`,
    `dispute_reason`, `revision_note`, `void_reason`, `paid_amount_cents` and
    `paid_at` all null."

    Design: Corner/entities/settlement_statement_system_fields_are_server_stamped
    """
    world = settled_world(statement_overrides={"created_by": OPS_ALTERNATE_ID})
    statement = validate_success(
        api.get_settlement_statement(world["statement_id"], world["ops_headers"])
    )
    assert_settlement_statement(statement)

    assert statement["status"] == SETTLEMENT_DRAFT
    assert statement["created_by_user_id"] == OPS_ALTERNATE_ID
    assert statement["revision_round"] == 1
    assert statement["issued_by_user_id"] is None
    assert statement["superseded_statement_id"] is None
    assert statement["dispute_reason"] is None
    assert statement["revision_note"] is None
    assert statement["void_reason"] is None
    assert statement["paid_amount_cents"] is None
    assert statement["paid_at"] is None
    assert statement["version"] == 1


def test_fish_lot_creation_rejects_values_outside_declared_sets(api):
    """Species, harvest method and net weight are all checked against their declarations.

    "Required fields present, types correct, enum values inside their declared
    set, numeric range constraints respected, ISO 8601 instants well formed, and
    every start/end pair strictly ordered with the start before the end."

    Design: Corner/entities/fish_lot_create_with_invalid_enum_species_rejected
    """
    world = base_world()

    validate_error(
        api.create_fish_lot(
            fish_lot_payload(world["kiosk_id"], species="TUNA_BIGEYE"),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.create_fish_lot(
            fish_lot_payload(world["kiosk_id"], net_weight_kg=0),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.create_fish_lot(
            fish_lot_payload(world["kiosk_id"], harvest_method="WILD_CAUGHT"),
            world["chef_headers"],
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_list(api.list_fish_lots(world["ops_headers"]), expected_total=0)

    accepted = validate_success(
        api.create_fish_lot(
            fish_lot_payload(world["kiosk_id"], harvest_method=HARVEST_WILD),
            world["chef_headers"],
        ),
        201,
    )
    assert accepted["harvest_method"] == HARVEST_WILD


def test_cold_chain_reading_carries_no_version_or_updated_at(api):
    """A cold-chain reading is append-only evidence with no mutable fields.

    "Two record types are pure append-only evidence and therefore carry only `id`
    and `created_at` — they have no `updated_at` and no `version` field at all,
    and their payloads must not contain those keys: `ColdChainReading` (a
    temperature reading of a fish lot) and `DiscardEvent` (a record of packs
    destroyed)."

    Design: Corner/entities/cold_chain_reading_is_immutable_with_no_version_field
    """
    world = base_world()
    lot = validate_success(
        api.create_fish_lot(
            fish_lot_payload(
                world["kiosk_id"], received_at="2026-08-03T07:00:00Z", receiving_temp_c=2.8
            ),
            world["chef_headers"],
        ),
        201,
    )

    reading = validate_success(
        api.create_cold_chain_reading(
            lot["id"],
            cold_chain_reading_payload("2026-08-03T07:50:00Z", 3.0),
            world["chef_headers"],
        ),
        201,
    )

    assert "version" not in reading
    assert "updated_at" not in reading
    assert_instant_equals(reading["recorded_at"], "2026-08-03T07:50:00Z")
    assert reading["breach_minutes_attributed"] == 0
    assert reading["lot_breach_minutes_after"] == 0

    stored = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert stored["cold_chain_breach_minutes"] == 0
    assert stored["status"] == "RECEIVED"
    validate_list(
        api.list_cold_chain_readings(lot["id"], world["ops_headers"]), expected_total=1
    )


def test_certification_creation_under_an_unknown_chef_is_not_found(api):
    """A path parameter that resolves to nothing is checked before the body.

    "Path parameters are checked first, left to right along the URL, and then
    request-body foreign keys in the order the body fields are declared for that
    endpoint."

    Design: Corner/entities/certification_create_under_unknown_chef_returns_not_found
    """
    world = base_world()

    validate_error(
        api.create_certification(
            UNKNOWN_CHEF_ID, certification_payload(), world["auditor_headers"]
        ),
        ApiErrorId.ERR_CHEF_RECORD_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_certification(
            UNKNOWN_CHEF_ID,
            certification_payload(cert_type="FOOD_HANDLER_BASIC"),
            world["auditor_headers"],
        ),
        ApiErrorId.ERR_CHEF_RECORD_NOT_FOUND.value,
        404,
    )

    validate_list(
        api.list_certifications(world["chef_id"], world["auditor_headers"]),
        expected_total=2,
    )


def test_chef_and_kiosk_hold_reciprocal_references_after_placement(api):
    """Placement writes the assignment on the chef and the lead reference on the kiosk.

    "Placement is a franchisor-operations act: it sets the chef's
    `assigned_kiosk_id` to the supplied kiosk and, when `as_lead_chef` is true, also
    writes that chef into the kiosk's `lead_chef_id`."

    Design: Corner/entities/chef_and_kiosk_hold_reciprocal_references_after_placement
    """
    world = base_world(commission=False)

    chef = validate_success(api.get_chef(world["chef_id"], world["ops_headers"]))
    kiosk = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))

    assert chef["assigned_kiosk_id"] == world["kiosk_id"]
    assert kiosk["lead_chef_id"] == world["chef_id"]
    assert kiosk["certified_chef_count"] == 1
    assert kiosk["operational_state"] == KIOSK_PROVISIONING

    validate_list(
        api.list_kiosks(world["ops_headers"], {"lead_chef_id": world["chef_id"]}),
        expected_total=1,
    )
    validate_list(
        api.list_chefs(world["ops_headers"], {"assigned_kiosk_id": world["kiosk_id"]}),
        expected_total=1,
    )
