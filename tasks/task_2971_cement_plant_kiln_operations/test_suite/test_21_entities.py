"""Breadth coverage of the entity contracts: the ledgers and enum defaults every
creation must materialise, the recomputation of the design and pile chemistry, the
four-figure silo inventory split, server-minted system fields, the paginated list
envelope, request-shape refusals, laboratory immutability and foreign-key integrity.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_amount,
    assert_instant_equals,
    assert_intensity,
    assert_oxide,
    assert_three_fractional_digits,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    ENV_HEADERS,
    LAB_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
    QUALITY_HEADERS,
)


# ---------------------------------------------------------------------------
# creation: reference data comes back with its ledgers already materialised
# ---------------------------------------------------------------------------
def test_a_new_plant_starts_with_its_permit_ledgers_initialised(api):
    """The plant's four derived figures are present and initialised on the creation
    response itself rather than left null until the first burn.

    PRD: "A new plant starts with `permit_nox_budget_remaining_kg` equal to
    `permit_annual_nox_budget_kg`, `rolling_nox_intensity_kg_per_tonne` at 0.000,
    `cement_tonne_balance_tonnes` at 0.00 and `production_posture` at `NORMAL`."

    Design: Corner/entities/reference_data_creation_returns_computed_ledgers_and_declared_defaults
    """
    fx.reset_clock(api)
    plant = validate_success(api.create_plant(f.plant_payload(), ADMIN_HEADERS), 201)

    assert is_valid_uuid(plant["id"])
    assert is_iso8601_timestamp(plant["created_at"])
    assert plant["version"] == 1
    assert_amount(
        plant["permit_annual_nox_budget_kg"], 2000000.00, "permit_annual_nox_budget_kg"
    )
    assert_amount(
        plant["permit_nox_budget_remaining_kg"],
        2000000.00,
        "permit_nox_budget_remaining_kg",
    )
    assert_intensity(
        plant["rolling_nox_intensity_kg_per_tonne"], 0.000, "rolling_nox_intensity"
    )
    assert_amount(
        plant["cement_tonne_balance_tonnes"], 0.00, "cement_tonne_balance_tonnes"
    )
    assert plant["production_posture"] == "NORMAL"

    fetched = validate_success(api.get_plant(plant["id"], ADMIN_HEADERS))
    assert_amount(
        fetched["permit_nox_budget_remaining_kg"],
        2000000.00,
        "permit_nox_budget_remaining_kg",
    )
    assert fetched["production_posture"] == "NORMAL"


def test_a_new_silo_starts_with_all_four_stock_figures_at_zero(api):
    """The silo's inventory is a four-way decomposition from the moment it is registered,
    and the spout count defaults to one when the caller omits it.

    PRD: "`available_tonnes` is what remains once both encumbrances are subtracted: it is
    the physical stock minus the reserved stock minus the unreleased stock, rounded to two
    decimals. All four figures begin at 0.00 when the silo is created."

    Design: Corner/entities/reference_data_creation_returns_computed_ledgers_and_declared_defaults
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)

    clinker = validate_success(
        api.create_silo(f.clinker_silo_payload(plant["id"]), ADMIN_HEADERS), 201
    )
    assert_amount(clinker["tonnes_on_hand"], 0.00, "tonnes_on_hand")
    assert_amount(clinker["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(clinker["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(clinker["available_tonnes"], 0.00, "available_tonnes")
    assert clinker["material_kind"] == "CLINKER"
    assert clinker["status"] == "OPEN"
    assert clinker["block_reason"] is None
    assert clinker["loadout_spouts"] == 1
    assert_amount(clinker["capacity_tonnes"], 20000.00, "capacity_tonnes")
    assert_amount(
        clinker["draw_rate_tonnes_per_hour"], 300.00, "draw_rate_tonnes_per_hour"
    )
    assert clinker["version"] == 1

    cement = validate_success(
        api.create_silo(f.cement_silo_payload(plant["id"]), ADMIN_HEADERS), 201
    )
    assert cement["material_kind"] == "CEMENT"
    assert cement["loadout_spouts"] == 2
    assert_amount(cement["available_tonnes"], 0.00, "available_tonnes")


def test_the_alternative_flags_default_to_false_across_the_two_catalogues(api):
    """Quarried rock and fossil fuel come back with `is_alternative` false and a zero
    substitution cap without either flag being sent; a by-product carries both.

    PRD: "Materials that are industrial by-products rather than quarried rock are flagged
    with `is_alternative` set to true, which defaults to false, and carry a
    `max_substitution_pct` giving the largest share of a pile's as-received tonnage that
    material may occupy; that cap defaults to 0 and is only meaningful on alternative
    materials."

    Design: Corner/entities/reference_data_creation_returns_computed_ledgers_and_declared_defaults
    """
    fx.reset_clock(api)

    limestone = validate_success(
        api.create_raw_material(f.limestone_payload("LS-1"), ENGINEER_HEADERS), 201
    )
    assert limestone["is_alternative"] is False
    assert_amount(limestone["max_substitution_pct"], 0.00, "max_substitution_pct")

    fly_ash = validate_success(
        api.create_raw_material(
            f.alt_raw_payload("FLY-1", max_substitution_pct=8.00), ENGINEER_HEADERS
        ),
        201,
    )
    assert fly_ash["is_alternative"] is True
    assert_amount(fly_ash["max_substitution_pct"], 8.00, "max_substitution_pct")

    gas = validate_success(
        api.create_fuel(f.natural_gas_payload("GAS-1"), ENV_HEADERS), 201
    )
    assert gas["is_alternative"] is False

    rdf = validate_success(api.create_fuel(f.rdf_payload("RDF-1"), ENV_HEADERS), 201)
    assert rdf["is_alternative"] is True

    tdf = validate_success(api.create_fuel(f.tdf_payload("TDF-1"), ENV_HEADERS), 201)
    assert tdf["is_alternative"] is True


def test_a_new_customer_is_active_off_credit_hold_and_owes_nothing(api):
    """The commercial defaults land on the creation response: an ACTIVE contract, no credit
    hold, and both tonnage ledgers at zero.

    PRD: "A customer record carries a legal `name`, a delivery `region_code`, a
    `contract_state` of `ACTIVE` or `SUSPENDED` that defaults to `ACTIVE`, a
    `contract_priority` where a **higher** value is served earlier in the allocation
    waterfall, a `contract_monthly_tonnes` base volume before any seasonal scaling, the
    `required_cement_type` that is the only type this customer accepts, a `max_so3_pct`
    specification ceiling on cement sulphate, and a `credit_hold` flag defaulting to false."

    Design: Corner/entities/reference_data_creation_returns_computed_ledgers_and_declared_defaults
    """
    fx.reset_clock(api)
    customer = validate_success(
        api.create_customer(f.customer_payload(), LOGISTICS_HEADERS), 201
    )

    assert customer["contract_state"] == "ACTIVE"
    assert customer["credit_hold"] is False
    assert customer["required_cement_type"] == "TYPE_IL"
    assert customer["contract_priority"] == 10
    assert_amount(customer["open_reserved_tonnes"], 0.00, "open_reserved_tonnes")
    assert_amount(customer["lifetime_loaded_tonnes"], 0.00, "lifetime_loaded_tonnes")
    assert customer["version"] == 1


# ---------------------------------------------------------------------------
# computed_fields: design chemistry frozen, pile chemistry re-derived
# ---------------------------------------------------------------------------
def test_design_oxides_and_modules_are_derived_from_the_dry_mass_fractions(api):
    """The 82.00 / 18.00 recipe reports four-decimal oxides and two-decimal modules computed
    from the dry-basis design fractions, and carries its declared tolerance defaults; the
    three-hop walk to APPROVED leaves version at 3.

    PRD: "For each of the four oxides in turn, multiply each component's `mass_fraction_pct`
    by that component's material content for the oxide, sum those products across the
    components, divide the sum by 100, and round half up to four decimal places."

    Design: Corner/entities/blended_pile_recomputes_dry_tonnage_and_modules_on_every_addition
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    design = fx.create_draft_design(api, plant["id"], materials)

    assert design["status"] == "DRAFT"
    assert design["revision_count"] == 0
    assert design["active_pile_count"] == 0
    assert design["created_by_user_id"] == ENGINEER_HEADERS["X-User-ID"]
    assert_amount(design["module_tolerance_lsf"], 1.50, "module_tolerance_lsf")
    assert_amount(design["pile_lsf_tolerance"], 2.00, "pile_lsf_tolerance")

    # 52.0 * 82.00 / 100 + 1.0 * 18.00 / 100 = 42.8200, and so on for the other three.
    assert_oxide(design["as_designed_cao_pct"], 42.8200, "as_designed_cao_pct")
    assert_oxide(design["as_designed_sio2_pct"], 13.6700, "as_designed_sio2_pct")
    assert_oxide(design["as_designed_al2o3_pct"], 4.0600, "as_designed_al2o3_pct")
    assert_oxide(design["as_designed_fe2o3_pct"], 1.6700, "as_designed_fe2o3_pct")
    assert_amount(design["as_designed_lsf"], 96.98, "as_designed_lsf")
    assert_amount(design["as_designed_sm"], 2.39, "as_designed_sm")
    assert_amount(design["as_designed_am"], 2.43, "as_designed_am")

    submitted = validate_success(api.submit_design(design["id"], ENGINEER_HEADERS))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == 2

    approved = validate_success(api.approve_design(design["id"], QUALITY_HEADERS))
    assert approved["status"] == "APPROVED"
    assert approved["version"] == 3
    assert approved["approved_by_user_id"] == QUALITY_HEADERS["X-User-ID"]
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00Z", "approved_at")


def test_the_pile_re_derives_its_dry_tonnage_and_modules_on_every_addition(api):
    """Each truck moves the bed's figures: 836.73 as-received tonnes of 2 percent limestone
    give 820.00 dry, and the 204.55 tonnes of 12 percent clay that follow bring the bed to
    1041.28 as-received against 1000.00 dry — which is exactly the design's own 82 / 18 dry
    split, so the blended modules land back on the design and lsf_deviation is 0.02.

    PRD: "`as_received_tonnes` is the sum of `tonnes_as_received` over the additions, rounded
    half up to two decimals."

    Design: Corner/entities/blended_pile_recomputes_dry_tonnage_and_modules_on_every_addition
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)
    materials = fx.create_raw_materials(api)
    design = fx.create_approved_design(api, plant["id"], materials)
    pile = fx.create_open_pile(api, plant["id"], design["id"], pile_code="PA")

    assert pile["status"] == "OPEN"
    assert pile["additions"] == []
    assert_amount(pile["as_received_tonnes"], 0.00, "as_received_tonnes")
    assert_amount(pile["dry_tonnes"], 0.00, "dry_tonnes")

    first = validate_success(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(materials["limestone"]["id"], 836.73, 2.0),
            ENGINEER_HEADERS,
        )
    )
    assert_amount(first["as_received_tonnes"], 836.73, "as_received_tonnes")
    assert_amount(first["dry_tonnes"], 820.00, "dry_tonnes")
    assert len(first["additions"]) == 1

    second = validate_success(
        api.add_pile_addition(
            pile["id"],
            f.addition_payload(materials["clay"]["id"], 204.55, 12.0),
            ENGINEER_HEADERS,
        )
    )
    assert_amount(second["as_received_tonnes"], 1041.28, "as_received_tonnes")
    assert_amount(second["dry_tonnes"], 1000.00, "dry_tonnes")
    assert_amount(second["alt_raw_share_pct"], 0.00, "alt_raw_share_pct")
    assert len(second["additions"]) == 2
    assert_oxide(second["as_blended_cao_pct"], 42.8200, "as_blended_cao_pct")
    assert_amount(second["as_blended_lsf"], 96.98, "as_blended_lsf")
    assert_amount(second["as_blended_sm"], 2.39, "as_blended_sm")
    assert_amount(second["as_blended_am"], 2.43, "as_blended_am")
    assert_amount(second["lsf_deviation"], 0.02, "lsf_deviation")

    counted = validate_success(api.get_design(design["id"], ENGINEER_HEADERS))
    assert counted["active_pile_count"] == 1


# ---------------------------------------------------------------------------
# retrieval: the four-figure inventory split across a release
# ---------------------------------------------------------------------------
def test_silo_read_returns_the_four_figure_inventory_split_after_a_release(api):
    """Completion makes 583.78 tonnes physically present but wholly unreleased, so
    availability stays 0.00; the release moves the same tonnage from unreleased to available
    without touching the physical figure.

    PRD: "`unreleased_tonnes` is stock physically present but not yet usable or sellable:
    clinker belonging to kiln runs whose quality dimension is still `PENDING_LAB` or has
    fallen to `QUARANTINED` in a clinker silo, and cement belonging to batches that have not
    yet reached `QUALIFIED` in a cement silo."

    Design: Corner/entities/silo_read_returns_the_four_figure_inventory_split_after_a_release
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    silo_id = env["clinker_silo"]["id"]
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    assert pile["status"] == "SEALED"
    assert_instant_equals(pile["sealed_at"], "2026-08-01T00:00:00Z", "sealed_at")
    assert_amount(pile["lsf_deviation"], 0.02, "lsf_deviation")

    run = fx.create_completed_run(
        api, env["kiln"]["id"], pile["id"], silo_id, env["fuels"]["gas"]["id"], 45.00
    )
    assert run["process_state"] == "COMPLETED"

    encumbered = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(encumbered["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(encumbered["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(encumbered["unreleased_tonnes"], 583.78, "unreleased_tonnes")
    assert_amount(encumbered["available_tonnes"], 0.00, "available_tonnes")

    kiln = validate_success(api.get_kiln(env["kiln"]["id"], OPERATOR_HEADERS))
    assert kiln["refractory_hours_since_reline"] == 12
    assert kiln["availability_state"] == "AVAILABLE"

    fx.record_free_lime(api, run["id"], 1.20)
    validate_success(api.release_clinker(run["id"], QUALITY_HEADERS))

    freed = validate_success(api.get_silo(silo_id, ENGINEER_HEADERS))
    assert_amount(freed["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(freed["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(freed["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(freed["available_tonnes"], 583.78, "available_tonnes")
    assert freed["status"] == "OPEN"
    assert freed["block_reason"] is None
    assert freed["material_kind"] == "CLINKER"
    assert_amount(freed["capacity_tonnes"], 20000.00, "capacity_tonnes")
    assert_amount(freed["draw_rate_tonnes_per_hour"], 300.00, "draw_rate_tonnes_per_hour")
    assert freed["loadout_spouts"] == 1


# ---------------------------------------------------------------------------
# defaults: the four independent dimensions of a new cement batch
# ---------------------------------------------------------------------------
def test_cement_batch_creation_applies_its_declared_enum_defaults(api):
    """A new batch carries four independent state dimensions and a zero allocation, and the
    reservation of the clinker draw is a side effect of the very same create.

    PRD: "A successful creation leaves the batch in `status` `PLANNED` with `feed_state`
    `FEED_READY`, `strength_branch_state` and `fineness_branch_state` both `PENDING`, and
    `certified_tonnes_allocated` at 0; it reserves the draw by growing the clinker silo's
    `reserved_tonnes` by `clinker_tonnes_drawn`, recomputing that silo's `available_tonnes`,
    and incrementing its `version`."

    Design: Corner/entities/cement_batch_creation_applies_declared_enum_defaults
    """
    env = fx.released_clinker_environment(api)
    silo = fx.data_of(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))

    batch = validate_success(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                env["clinker_silo"]["id"],
                env["cement_silo"]["id"],
                silo["version"],
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert batch["status"] == "PLANNED"
    assert batch["feed_state"] == "FEED_READY"
    assert batch["strength_branch_state"] == "PENDING"
    assert batch["fineness_branch_state"] == "PENDING"
    assert_amount(
        batch["certified_tonnes_allocated"], 0.00, "certified_tonnes_allocated"
    )
    assert batch["rejection_reason"] is None
    assert batch["grinding_started_at"] is None
    assert batch["ground_at"] is None
    assert batch["qualified_at"] is None
    assert batch["version"] == 1

    reserved = validate_success(
        api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS)
    )
    assert_amount(reserved["reserved_tonnes"], 500.00, "reserved_tonnes")
    assert_amount(reserved["available_tonnes"], 83.78, "available_tonnes")


# ---------------------------------------------------------------------------
# system_fields
# ---------------------------------------------------------------------------
def test_mill_certificate_system_fields_are_server_minted_not_client_supplied(api):
    """The draft comes back with a server-minted bare UUID, a three-decimal created_at and
    version 1, and it comes back DRAFT with a null issuer even though the request body tried
    to declare itself ISSUED by someone.

    PRD: "Every resource carries an `id`, which is a server-minted UUID with no type prefix,
    and a `created_at` timestamp in ISO 8601 UTC notation with exactly three fractional
    digits."

    Design: Corner/entities/mill_certificate_system_fields_are_server_minted_and_client_values_ignored
    """
    env = fx.qualified_cement_environment(api, strength_value=30.0)
    customer = fx.create_customer(api)

    certificate = validate_success(
        api.create_mill_certificate(
            f.mill_certificate_payload(
                env["batch"]["id"],
                customer["id"],
                574.72,
                status="ISSUED",
                issued_by_user_id="QM9",
                allocated_tonnes=999.99,
                version=42,
            ),
            QUALITY_HEADERS,
        ),
        201,
    )
    assert is_valid_uuid(certificate["id"])
    assert not certificate["id"].startswith("mc_")
    assert is_iso8601_timestamp(certificate["created_at"])
    assert_three_fractional_digits(certificate["created_at"], "created_at")
    assert certificate["version"] == 1
    assert certificate["status"] == "DRAFT"
    assert certificate["issued_by_user_id"] is None
    assert certificate["issued_at"] is None
    assert certificate["revoked_at"] is None

    stored = validate_success(api.get_mill_certificate(certificate["id"], QUALITY_HEADERS))
    assert stored["status"] == "DRAFT"
    assert stored["issued_by_user_id"] is None
    assert stored["version"] == 1


def test_a_draft_certificate_snapshots_the_newest_in_specification_results(api):
    """Drafting copies the laboratory record onto the document — Blaine 400 and 30.0 MPa —
    and immediately allocates the tonnage against the batch even though nothing has been
    issued yet.

    PRD: "The draft immediately snapshots the batch's laboratory record:
    `certified_blaine_m2_per_kg` takes the `value` of the batch's newest in-specification
    `BLAINE` test by `created_at` descending, and `certified_strength_mpa` takes the `value`
    of the batch's newest in-specification `COMPRESSIVE_STRENGTH_28D` test on the same
    ordering."

    Design: Corner/entities/mill_certificate_system_fields_are_server_minted_and_client_values_ignored
    """
    env = fx.qualified_cement_environment(api, strength_value=30.0)
    assert env["batch"]["status"] == "QUALIFIED"
    assert_amount(env["batch"]["cement_tonnes"], 574.72, "cement_tonnes")

    cement_silo = validate_success(api.get_silo(env["cement_silo"]["id"], QUALITY_HEADERS))
    assert_amount(cement_silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")
    assert_amount(cement_silo["available_tonnes"], 574.72, "available_tonnes")

    customer = fx.create_customer(api)
    certificate = validate_success(
        api.create_mill_certificate(
            f.mill_certificate_payload(env["batch"]["id"], customer["id"], 574.72),
            QUALITY_HEADERS,
        ),
        201,
    )
    assert certificate["certified_blaine_m2_per_kg"] == 400
    assert_amount(certificate["certified_strength_mpa"], 30.0, "certified_strength_mpa")
    assert_amount(certificate["allocated_tonnes"], 0.00, "allocated_tonnes")

    # A DRAFT certificate already counts against the batch's allocation.
    batch = validate_success(api.get_cement_batch(env["batch"]["id"], QUALITY_HEADERS))
    assert batch["status"] == "QUALIFIED"
    assert_amount(
        batch["certified_tonnes_allocated"], 574.72, "certified_tonnes_allocated"
    )


# ---------------------------------------------------------------------------
# listing
# ---------------------------------------------------------------------------
def test_loadout_order_listing_returns_the_paginated_envelope_with_filters(api):
    """total_count counts the rows the filters match, not the rows the page carries, so one
    order under limit 1 reads total_count 1 with has_more false, and a filter that matches
    nothing is an empty page rather than a 404.

    PRD: "`total_count` is the number of rows matching the request's filters before
    pagination is applied, and `has_more` is true when rows remain beyond the current page."

    Design: Corner/entities/loadout_order_listing_returns_the_paginated_envelope_with_filters
    """
    env = fx.certificate_chain(api)
    order = validate_success(api.get_loadout_order(env["order"]["id"], LOGISTICS_HEADERS))
    assert order["status"] == "RESERVED"
    assert_amount(order["scheduled_hours"], 2.00, "scheduled_hours")
    assert_amount(order["loaded_tonnes"], 0.00, "loaded_tonnes")
    assert order["void_reason"] is None
    assert order["loading_started_at"] is None
    assert order["completed_at"] is None

    rows, meta = validate_paginated(
        api.list_loadout_orders(
            LOGISTICS_HEADERS,
            params={"customer_id": env["customer"]["id"], "limit": 1, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert len(rows) == 1
    assert rows[0]["id"] == env["order"]["id"]

    empty_rows, empty_meta = validate_paginated(
        api.list_loadout_orders(
            LOGISTICS_HEADERS,
            params={"customer_id": env["customer"]["id"], "status": "VOIDED"},
        )
    )
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False
    assert empty_rows == []


def test_a_limit_outside_the_declared_range_is_refused(api):
    """The pagination window is 1 through 100 inclusive, so 0 and 101 are both refused
    before the query runs.

    PRD: "A `limit` outside the range 1 through 100, a negative `offset`, or a non-integer
    value for either is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/entities/loadout_order_listing_returns_the_paginated_envelope_with_filters
    """
    fx.reset_clock(api)

    validate_error(
        api.list_loadout_orders(LOGISTICS_HEADERS, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )
    validate_error(
        api.list_loadout_orders(LOGISTICS_HEADERS, params={"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )
    validate_error(
        api.list_loadout_orders(LOGISTICS_HEADERS, params={"offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )


# ---------------------------------------------------------------------------
# required_fields / type_constraints
# ---------------------------------------------------------------------------
def test_a_plant_created_without_its_free_lime_ceiling_is_rejected(api):
    """clinker_free_lime_max_pct is sourced from the request and has no default, so omitting
    it is a shape violation and nothing is persisted.

    PRD: "On every write endpoint: required fields present; numeric fields numeric, and
    non-negative wherever the field is a tonnage, a percentage or an energy; enum fields
    drawn from their declared value sets; datetime fields parseable as ISO 8601 UTC; array
    fields actually arrays; `gypsum_pct` between 2.00 and 7.00 inclusive;
    `blaine_target_m2_per_kg` inside the cement type's Blaine band; `as_of_month` between 1
    and 12 inclusive. Any violation yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/plant_create_missing_required_field_is_rejected
    """
    fx.reset_clock(api)
    payload = f.plant_payload()
    del payload["clinker_free_lime_max_pct"]

    validate_error(
        api.create_plant(payload, ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(api.list_plants(ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_a_silo_created_with_an_undeclared_material_kind_is_rejected(api):
    """material_kind is a two-member enum, so a plausible third value such as RAW_MEAL is a
    400 rather than a stored free-text kind.

    PRD: "Each silo is registered against a plant with a `code` that is unique within that
    plant, a `material_kind` of either `CLINKER` or `CEMENT`, a physical `capacity_tonnes`,
    a `draw_rate_tonnes_per_hour` describing the fastest rate at which material can be
    extracted, and a `loadout_spouts` count describing how many loading appointments may
    overlap in time on that silo."

    Design: Corner/entities/silo_create_invalid_enum_material_kind_is_rejected
    """
    fx.reset_clock(api)
    plant = fx.create_plant(api)

    validate_error(
        api.create_silo(
            f.clinker_silo_payload(
                plant["id"],
                code="SR1",
                material_kind="RAW_MEAL",
                capacity_tonnes=5000.00,
                draw_rate_tonnes_per_hour=100.00,
            ),
            ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_silos(ADMIN_HEADERS, params={"plant_id": plant["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# immutability
# ---------------------------------------------------------------------------
def test_a_lab_test_row_carries_no_version_and_is_superseded_never_edited(api):
    """The laboratory row is the one entity without the common mutation fields, and a
    correction is a second row: the first test remains readable and both stay listable.

    PRD: "The one exception is the laboratory test resource: a `LabTest` row is immutable
    once written, so it carries only `id` and `created_at` — it has neither an `updated_at`
    nor a `version` field at all."

    Design: Corner/entities/lab_test_is_immutable_with_no_update_endpoint_and_no_version
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_completed_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        env["fuels"]["gas"]["id"],
        45.00,
    )

    first = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.20, kiln_run_id=run["id"]), LAB_HEADERS
        ),
        201,
    )
    assert "updated_at" not in first
    assert "version" not in first
    assert is_valid_uuid(first["id"])
    assert is_iso8601_timestamp(first["created_at"])
    assert first["recorded_by_user_id"] == LAB_HEADERS["X-User-ID"]

    fetched = validate_success(api.get_lab_test(first["id"], QUALITY_HEADERS))
    assert fetched == first

    second = validate_success(
        api.create_lab_test(
            f.lab_test_payload("FREE_LIME", 1.25, kiln_run_id=run["id"]), LAB_HEADERS
        ),
        201,
    )
    assert second["id"] != first["id"]

    still_there = validate_success(api.get_lab_test(first["id"], QUALITY_HEADERS))
    assert still_there == first

    rows, meta = validate_paginated(
        api.list_lab_tests(QUALITY_HEADERS, params={"kiln_run_id": run["id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


# ---------------------------------------------------------------------------
# parent_relationships
# ---------------------------------------------------------------------------
def test_a_cement_silo_offered_as_the_clinker_target_is_a_kind_mismatch(api):
    """The cement silo exists and belongs to the same plant, so existence is satisfied and
    the request still fails on kind; no run is written.

    PRD: "The `clinker_silo_id` must additionally name a `CLINKER` silo belonging to the
    same plant as the kiln, else `ERR_SILO_KIND_MISMATCH`."

    Design: Corner/entities/kiln_run_create_with_a_cement_silo_as_the_clinker_target_not_found_or_kind_mismatch
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])

    validate_error(
        api.create_kiln_run(
            f.kiln_run_payload(
                env["kiln"]["id"],
                pile["id"],
                env["cement_silo"]["id"],
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-02T12:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_SILO_KIND_MISMATCH.value,
        422,
    )

    _rows, meta = validate_paginated(
        api.list_kiln_runs(OPERATOR_HEADERS, params={"kiln_id": env["kiln"]["id"]})
    )
    assert meta["total_count"] == 0


def test_an_unresolvable_reference_in_the_body_answers_before_the_kind_check(api):
    """A syntactically valid but non-existent id is a 404 from the referenced entity's own
    catalogue, whether it is the silo or the kiln that cannot be resolved.

    PRD: "On every endpoint whose body carries a foreign key: every such key resolves to an
    existing row of its target entity, else that referenced entity's own not-found error
    (404)."

    Design: Corner/entities/kiln_run_create_with_a_cement_silo_as_the_clinker_target_not_found_or_kind_mismatch
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])

    validate_error(
        api.create_kiln_run(
            f.kiln_run_payload(
                env["kiln"]["id"],
                pile["id"],
                NON_EXISTENT_UUID,
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-02T12:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_SILO_NOT_FOUND.value,
        404,
    )

    validate_error(
        api.create_kiln_run(
            f.kiln_run_payload(
                NON_EXISTENT_UUID,
                pile["id"],
                env["clinker_silo"]["id"],
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-02T12:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_KILN_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_kiln_runs(OPERATOR_HEADERS, params={"kiln_id": env["kiln"]["id"]})
    )
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# computed_fields
# ---------------------------------------------------------------------------
def test_client_supplied_values_for_the_derived_sulphate_and_tonnage_are_ignored(api):
    """A body that also declares cement_tonnes 999.99 and so3_pct 0.10 is answered with the
    derived 574.72 and 2.85, identical to the clean request.

    PRD: "Fourth, the blended sulphate content `so3_pct` is computed from the step-two
    tonnages and the step-three total: the drawn clinker tonnage multiplied by 0.60, plus
    `gypsum_tonnes` multiplied by 46.50, plus `limestone_tonnes` multiplied by 0.05, that
    sum divided by `cement_tonnes`, rounded half up to two decimals."

    Design: Corner/entities/computed_field_input_ignored_on_cement_batch_create
    """
    env = fx.released_clinker_environment(api)
    silo = fx.data_of(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))

    batch = validate_success(
        api.create_cement_batch(
            f.cement_batch_payload(
                env["plant_id"],
                env["clinker_silo"]["id"],
                env["cement_silo"]["id"],
                silo["version"],
                cement_tonnes=999.99,
                so3_pct=0.10,
                total_batch_tonnes=1.00,
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert_amount(batch["total_batch_tonnes"], 574.71, "total_batch_tonnes")
    assert_amount(batch["gypsum_tonnes"], 28.74, "gypsum_tonnes")
    assert_amount(batch["limestone_tonnes"], 45.98, "limestone_tonnes")
    assert_amount(batch["cement_tonnes"], 574.72, "cement_tonnes")
    assert_amount(batch["so3_pct"], 2.85, "so3_pct")
    assert batch["status"] == "PLANNED"
    assert batch["version"] == 1
