"""Resource creation, projection recalibration, input refusals and OCC guards."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    is_valid_uuid,
    make_customer_headers,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_pet, assert_prescription
from test_helpers.fixtures import (
    add_item,
    authorize,
    compose,
    compose_ok,
    create_pet,
    create_plan,
    create_product,
    create_shipment,
    create_site,
    create_veterinarian,
    read_item,
    read_plan,
    read_prescription,
    read_site,
    run_callback_attempt,
    set_clock,
    setup_prescription_item,
    ship_order,
    ship_order_ok,
)


def test_pet_registration_carries_system_fields_and_starts_alive(api):
    """PRD §3.1: "A `Customer` begins by registering a pet, supplying `pet_name`,
    `species`, `breed`, `weight_kg` and `owner_state`. The response carries the newly
    minted `id` and the `created_at` stamp; a pet has no `updated_at` and no
    `version`, so nothing about a pet can be optimistically locked. Registration
    fixes `pet_status` at `ACTIVE`, and the derived lifecycle label
    `pet_lifecycle_state` reads `ALIVE`."

    Design: Corner/entities/pet_creation_carries_the_system_fields_and_starts_alive
    """
    set_clock()
    resp = api_client.create_pet(
        {"pet_name": "Biscuit", "species": "DOG", "breed": "Corgi",
         "weight_kg": 12.5, "owner_state": "CA"},
        TEST_USERS["customer_headers"])
    data = validate_success(resp, 201)

    assert is_valid_uuid(data["id"])
    assert data["pet_name"] == "Biscuit"
    assert data["species"] == "DOG"
    assert data["breed"] == "Corgi"
    assert data["weight_kg"] == 12.5
    assert data["owner_state"] == "CA"
    assert data["pet_status"] == "ACTIVE"
    assert data["pet_lifecycle_state"] == "ALIVE"
    assert data["created_at"]
    assert_pet(data)


def test_pet_creation_ignores_a_client_supplied_status(api):
    """PRD §2.4: "`Pet` is the exception: it carries only `id` and `created_at`, and
    has neither `updated_at` nor `version`, so no optimistic-concurrency check may be
    attempted against a pet."
    PRD §3.1: "Registration fixes `pet_status` at `ACTIVE`"

    Design: Corner/entities/pet_creation_carries_the_system_fields_and_starts_alive
    """
    set_clock()
    resp = api_client.create_pet(
        {"pet_name": "Rogue", "species": "DOG", "breed": "Corgi",
         "weight_kg": 12.5, "owner_state": "CA", "pet_status": "PASSED"},
        TEST_USERS["customer_headers"])
    data = validate_success(resp, 201)

    assert data["pet_status"] == "ACTIVE", (
        "a client-supplied status cannot override the fixed initial status"
    )
    assert data["pet_lifecycle_state"] == "ALIVE"
    assert "updated_at" not in data or data.get("updated_at") is None


def test_recording_a_weight_recalibrates_the_item_projection(api):
    """PRD §3.2: "A caller supplies the new `weight_kg` value; the pet's `weight_kg`
    is overwritten, the daily dosage is recomputed, every autoship item belonging to
    that pet has its `unit_lifecycle_equivalent_days` recomputed, and every plan
    belonging to that pet has its `cadence_prompt_due_days_delta` recomputed."
    PRD §2.5: "values below 14 become 14, values above 84 become 84, and the clamped
    value is the equivalent lifecycle day count recorded on the item."

    Design: Corner/entities/pet_weight_update_recalibrates_dosage_and_cadence
    """
    set_clock()
    product = create_product(sku="ENT-01", product_name="Weight calibration chew",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.2, pack_size_units=60,
                             unit_price_cents=1400)
    pet = create_pet(pet_name="Nutmeg", species="DOG", breed="Vizsla",
                     weight_kg=20.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)
    before = item["unit_lifecycle_equivalent_days"]
    assert before == 60

    resp = api_client.record_weight(pet["id"], {"weight_kg": 30.0},
                                   make_customer_headers(pet["id"]))
    updated_pet = validate_success(resp, 200)
    assert updated_pet["weight_kg"] == 30.0

    item_after = read_item(plan, pet, item)
    assert item_after["unit_lifecycle_equivalent_days"] == 30, (
        "the equivalent duration is recomputed rather than cached"
    )
    assert item_after["unit_lifecycle_equivalent_days"] != before


def test_recording_a_weight_is_deterministic(api):
    """PRD §3.2: "Recording a pet's weight is the lever that recalibrates the whole
    household's schedule."
    PRD §3.2: "Because the pet itself carries no `version`, long-running
    recalibration can never be blocked by a stale-version check."

    Design: Corner/entities/pet_weight_update_recalibrates_dosage_and_cadence
    """
    set_clock()
    product = create_product(sku="ENT-01", product_name="Weight calibration chew",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.070, pack_size_units=30,
                             unit_price_cents=1400)
    pet = create_pet(pet_name="Nutmeg", species="DOG", breed="Vizsla",
                     weight_kg=14.0, owner_state="CA")
    plan = create_plan(pet)
    item = add_item(plan, pet, product, cadence_days=28)

    api_client.record_weight(pet["id"], {"weight_kg": 42.0},
                            make_customer_headers(pet["id"]))
    once = read_item(plan, pet, item)["unit_lifecycle_equivalent_days"]
    api_client.record_weight(pet["id"], {"weight_kg": 42.0},
                            make_customer_headers(pet["id"]))
    twice = read_item(plan, pet, item)["unit_lifecycle_equivalent_days"]

    assert once == twice == 30, "the same weight posted twice leaves the projection unchanged"


def test_pet_read_with_an_unknown_id_returns_resource_not_found(api):
    """PRD §2.10: "Where a path names more than one identifier, the platform resolves
    them strictly left to right and stops at the first identifier that does not
    resolve to an existing resource ... The request is rejected with
    `ERR_RESOURCE_NOT_FOUND` and HTTP 404 for the first unresolvable identifier."

    Design: Corner/entities/pet_read_with_an_unknown_id_returns_resource_not_found
    """
    set_clock()
    resp = api_client.get_pet("00000000-0000-4000-8000-000000000000",
                              TEST_USERS["customer_headers"])
    validate_error(resp, "ERR_RESOURCE_NOT_FOUND")
    assert resp.status_code == 404


def test_unknown_id_error_is_consistent_across_path_scopes(api):
    """PRD §2.10: "An identifier that does exist but belongs to a different owning
    party is reported as absent rather than as forbidden, so that resource ownership
    is not observable through error codes."

    Design: Corner/entities/pet_read_with_an_unknown_id_returns_resource_not_found
    """
    set_clock()
    pet_resp = api_client.get_pet("00000000-0000-4000-8000-000000000000",
                                  TEST_USERS["customer_headers"])
    plan_resp = api_client.get_plan("00000000-0000-4000-8000-000000000000",
                                    TEST_USERS["customer_service_headers"])
    validate_error(pet_resp, "ERR_RESOURCE_NOT_FOUND")
    validate_error(plan_resp, "ERR_RESOURCE_NOT_FOUND")
    assert pet_resp.status_code == plan_resp.status_code == 404


def test_invalid_cadence_values_are_refused_without_creating_anything(api):
    """PRD §3.1: "the cadence must be a member of the set 14, 21, 28, 42, 56 or 84
    days, and the default quantity must be at least 1 — a cadence outside that set,
    or a quantity below 1, is rejected with `ERR_INVALID_CADENCE` and HTTP 400."

    Design: Corner/errors/invalid_weights_are_refused_at_the_envelope_level
    """
    set_clock()
    product = create_product(sku="ERR-01", product_name="Invalid weight pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=900)
    pet = create_pet(pet_name="Rook", species="CAT", breed="Savannah",
                     weight_kg=5.0, owner_state="CA")
    plan = create_plan(pet)

    resp = api_client.add_item(plan["id"],
                              {"product_id": product["id"], "cadence_days": 15,
                               "default_quantity": 1},
                              make_customer_headers(pet["id"]))
    validate_error(resp, "ERR_INVALID_CADENCE")
    assert resp.status_code == 400

    items = get_success_data(api_client.list_plan_items(
        plan["id"], TEST_USERS["customer_service_headers"]))
    assert items == [], "the refusal created nothing"


def test_default_quantity_below_one_is_refused_at_the_same_point(api):
    """PRD §3.1: "the default quantity must be at least 1 — a cadence outside that
    set, or a quantity below 1, is rejected with `ERR_INVALID_CADENCE` and HTTP 400."

    Design: Corner/errors/invalid_weights_are_refused_at_the_envelope_level
    """
    set_clock()
    product = create_product(sku="ERR-01", product_name="Invalid weight pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=900)
    pet = create_pet(pet_name="Rook", species="CAT", breed="Savannah",
                     weight_kg=5.0, owner_state="CA")
    plan = create_plan(pet)

    resp = api_client.add_item(plan["id"],
                              {"product_id": product["id"], "cadence_days": 28,
                               "default_quantity": 0},
                              make_customer_headers(pet["id"]))
    validate_error(resp, "ERR_INVALID_CADENCE")
    assert resp.status_code == 400


def test_a_redundant_promotion_on_a_recurring_order_is_refused(api):
    """PRD §3.4: "When the raw discount is greater than zero and a `promotion_code` is
    present, the request is likewise refused with `ERR_PROMO_STACKING_NOT_ALLOWED`,
    because a promotion never stacks on a nonzero autoship discount."
    PRD §3.4: "The `override_code` is the caller-supplied escape hatch recorded
    alongside the request; it does not bypass the stacking prohibition."

    Design: Corner/errors/redundant_promotion_on_a_recurring_order_returns_the_stacking_error
    """
    set_clock()
    product = create_product(sku="ERR-02", product_name="Stacking pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=4000)
    pet = create_pet(pet_name="Marjoram", species="DOG", breed="Saluki",
                     weight_kg=22.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=14)
    first_order = compose_ok(plan, pet)
    assert first_order["order_kind"] == "FIRST"

    set_clock("2026-09-15T00:00:00Z")
    resp = compose(plan, pet, promotion_code="WELCOME10")

    validate_error(resp, "ERR_PROMO_STACKING_NOT_ALLOWED")
    assert resp.status_code == 422
    orders = get_success_data(api_client.list_plan_orders(
        plan["id"], TEST_USERS["customer_service_headers"]))
    assert len(orders) == 1, "the compose did not partially apply"


def test_the_same_compose_succeeds_without_a_promotion(api):
    """PRD §3.4: "Promotions are reconciled against the discount, and the
    reconciliation is deliberately restrictive."
    PRD §3.4: "In every other case the residual is exactly 0."

    Design: Corner/errors/redundant_promotion_on_a_recurring_order_returns_the_stacking_error
    """
    set_clock()
    product = create_product(sku="ERR-02", product_name="Stacking pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=4000)
    pet = create_pet(pet_name="Marjoram", species="DOG", breed="Saluki",
                     weight_kg=22.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=14)
    compose_ok(plan, pet)
    set_clock("2026-09-15T00:00:00Z")

    order = compose_ok(plan, pet)
    assert order["order_kind"] == "RECURRING", (
        "the refusal above is attributable to the stacking guard alone"
    )
    assert order["residual_promo_discount_cents"] == 0


def test_stale_plan_version_is_refused_by_the_occ_rule(api):
    """PRD §2.9: "If the plan's current `version` has advanced past the supplied
    value — because another composer legitimately advanced the plan by composing
    from it — the request is rejected with `ERR_STALE_PLAN_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_is_rejected_by_the_occ_rule
    """
    set_clock()
    product = create_product(sku="OCC-01", product_name="Occ pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Sorghum", species="DOG", breed="Otterhound",
                     weight_kg=34.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    observed = read_plan(plan, pet)["version"]
    set_clock("2026-10-01T00:00:00Z")
    compose_ok(plan, pet, expected_plan_version=observed)

    resp = compose(plan, pet, expected_plan_version=observed)
    validate_error(resp, "ERR_STALE_PLAN_VERSION")
    assert resp.status_code == 412
    assert read_plan(plan, pet)["version"] > observed


def test_occ_guard_is_a_version_check_rather_than_a_state_restriction(api):
    """PRD §2.12: "Stale-version rejection sits outside the business ladder: the two
    optimistically controlled writes evaluate their expected-version field at the
    point described in §2.9, so a compose or cadence request carrying a version the
    parent has already advanced past is rejected with `ERR_STALE_PLAN_VERSION` ...
    regardless of whether the underlying business rules would also have failed."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_is_rejected_by_the_occ_rule
    """
    set_clock()
    product = create_product(sku="OCC-01", product_name="Occ pack",
                             medication_scope="OTC", cold_pack_required=False,
                             unit_dose_mg_per_kg=0.02, pack_size_units=10,
                             unit_price_cents=1000)
    pet = create_pet(pet_name="Sorghum", species="DOG", breed="Otterhound",
                     weight_kg=34.0, owner_state="CA")
    plan = create_plan(pet)
    add_item(plan, pet, product, cadence_days=28)
    observed = read_plan(plan, pet)["version"]
    set_clock("2026-10-01T00:00:00Z")
    compose_ok(plan, pet, expected_plan_version=observed)

    stale = compose(plan, pet, expected_plan_version=observed)
    assert stale.json()["data"]["error_id"] == "ERR_STALE_PLAN_VERSION"
    fresh = compose(plan, pet)
    assert fresh.status_code == 201, (
        "the identical call with the fresh version succeeds"
    )


def test_cadence_stale_item_version_is_refused_by_the_occ_rule(api):
    """PRD §2.9: "If the item's current `version` has advanced past the supplied
    value — because prescription verification activity legitimately advanced the
    item's version since the client's read — the request is rejected with
    `ERR_STALE_ITEM_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/cadence_stale_item_version_is_rejected_by_the_occ_rule
    """
    bundle = setup_prescription_item()
    plan = bundle["plan"]
    pet = bundle["pet"]
    item = bundle["item"]
    observed = read_item(plan, pet, item)["version"]

    run_callback_attempt(bundle["rx"])
    assert read_item(plan, pet, item)["version"] > observed, (
        "the callback attempt advanced the item's version past the captured value"
    )

    resp = api_client.change_cadence(
        plan["id"], item["id"],
        {"expected_item_version": observed, "cadence_days": 42},
        make_customer_headers(pet["id"]))
    validate_error(resp, "ERR_STALE_ITEM_VERSION")
    assert resp.status_code == 412
    assert read_item(plan, pet, item)["cadence_days"] == 28


def test_resubmitting_the_fresh_item_version_succeeds(api):
    """PRD §2.9: "The second is an item cadence change. A cadence update must carry
    `expected_item_version`, a non-optional field holding the client's last observed
    `version` of the target `AutoshipItem`."

    Design: Corner/cross_cutting_complexity_layers/cadence_stale_item_version_is_rejected_by_the_occ_rule
    """
    bundle = setup_prescription_item()
    plan = bundle["plan"]
    pet = bundle["pet"]
    item = bundle["item"]
    observed = read_item(plan, pet, item)["version"]
    run_callback_attempt(bundle["rx"])
    validate_error(api_client.change_cadence(
        plan["id"], item["id"],
        {"expected_item_version": observed, "cadence_days": 42},
        make_customer_headers(pet["id"])), "ERR_STALE_ITEM_VERSION")

    fresh_version = read_item(plan, pet, item)["version"]
    changed = get_success_data(api_client.change_cadence(
        plan["id"], item["id"],
        {"expected_item_version": fresh_version, "cadence_days": 42},
        make_customer_headers(pet["id"])), 200)
    assert changed["cadence_days"] == 42


def test_existing_prescription_is_unchanged_by_a_forbidden_authorisation(api):
    """PRD §2.12: "Once identity and addressability are established, a state
    transition request is checked against its governing transition before any
    business rule"
    PRD §3.3: "Several conditions must hold, and they are evaluated in the order
    given: the prescription must be in `VERIFICATION_IN_PROGRESS`"

    Design: Corner/rbac/clinic_contact_cannot_run_the_callback_workflow
    """
    bundle = setup_prescription_item()
    vet = bundle["vet"]
    rx = bundle["rx"]
    get_success_data(api_client.record_clinic_contact(
        rx["id"], TEST_USERS["pharmacy_technician_headers"]))

    # A role that holds no authorisation capability at all is refused, and the
    # prescription is left exactly where the callback workflow put it.
    denied = api_client.authorize_prescription(
        rx["id"], {}, TEST_USERS["customer_headers"])
    validate_error(denied, "ERR_ROLE_NOT_PERMITTED")
    assert denied.status_code == 403

    rx_after = read_prescription(rx)
    assert rx_after["rx_status"] == "VERIFICATION_IN_PROGRESS"
    assert rx_after["callback_attempt_count"] == 1
    assert_prescription(rx_after)