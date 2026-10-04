"""Production slots: date check, capacity units, confirm gate, completion (PRD §3.4, §2.10, §2.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_flavor_payload, create_production_slot_payload,
    make_flavor, make_flavor_in_state, make_limited_run_flavor,
    promote_flavor_to,
)

PS = TEST_USERS["plant_scheduler_headers"]
FM = TEST_USERS["flavor_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]




def test_slot_date_in_past_rejected(api):
    """PRD §3.4: "The date may not be before the current logical date, failing
    with `ERR_SLOT_DATE_PAST` (HTTP 422). Creation applies the date check first
    and the capacity check second."

    Design: Corner/validations/slot_date_in_past_rejected
    """
    flavor = make_flavor_in_state("TEST_BATCH", name="Past Slot")
    resp = api.create_production_slot(
        create_production_slot_payload(flavor["id"], production_date="2026-08-01"),
        PS)
    validate_error(resp, ApiErrorId.ERR_SLOT_DATE_PAST)


def test_slot_create_exceeding_plant_capacity_rejected(api):
    """PRD §3.4: "the planned pints are divided by 100, the result is multiplied by a chunk factor of 1.5 when the flavor's `chunk_load_pct` is at least 20 (1.0 otherwise) and by a swirl factor of 1.25 when the flavor's `swirl_load_pct` is at least 15 (1.0 otherwise) — the factors multiply, so a formulation heavy in both consumes 1.875 units per hundred pints — and the product is rounded up to a whole number of units."
    PRD §3.4: "the sum of `capacity_units` over slots in `PLANNED` or
    `CONFIRMED` in the same plant-date-shift bucket, plus the new slot's units,
    must stay within the plant's budget, failing with
    `ERR_PLANT_CAPACITY_EXCEEDED` (HTTP 422)."
    PRD §2.10: "1000 units at `VT_WATERBURY`, 800 at `VT_ST_ALBANS`, and 600 at
    `NL_HELLENDOORN`."

    Design: Corner/state_machines/slot_create_exceeding_plant_capacity_rejected
    """
    flavor = make_flavor_in_state("TEST_BATCH", name="Chunk Monster",
                                  chunk_load_pct=25, swirl_load_pct=0)
    # 54000/100 * 1.5 = 810 units > 800 (VT_ST_ALBANS budget)
    resp = api.create_production_slot(
        create_production_slot_payload(
            flavor["id"], plant_code="VT_ST_ALBANS", planned_pints=54000), PS)
    validate_error(resp, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)


def test_slot_units_chunk_swirl_multiplicative(api):
    """PRD §3.4: "the planned pints are divided by 100, the result is multiplied by a chunk factor of 1.5 when the flavor's `chunk_load_pct` is at least 20 (1.0 otherwise) and by a swirl factor of 1.25 when the flavor's `swirl_load_pct` is at least 15 (1.0 otherwise) — the factors multiply, so a formulation heavy in both consumes 1.875 units per hundred pints — and the product is rounded up to a whole number of units."

    Design: Corner/calculations/slot_units_chunk_swirl_multiplicative
    """
    heavy = make_flavor(name="Heavy Chunk", chunk_load_pct=25, swirl_load_pct=20)
    plain = make_flavor(name="Plain Jane", chunk_load_pct=5, swirl_load_pct=5)

    heavy_slot = validate_success(api.create_production_slot(
        create_production_slot_payload(heavy["id"], planned_pints=500), PS),
        expected_status=201)
    assert heavy_slot["capacity_units"] == 10  # ceil(5 * 1.5 * 1.25) = ceil(9.375)

    plain_slot = validate_success(api.create_production_slot(
        create_production_slot_payload(plain["id"], planned_pints=500,
                                       shift="NIGHT"), PS),
        expected_status=201)
    assert plain_slot["capacity_units"] == 5  # ceil(5 * 1.0 * 1.0)


def test_slot_completes_on_clock_advance(api):
    """PRD §2.5: "A production slot in `CONFIRMED` whose `production_date` is
    strictly before the current logical date transitions to `COMPLETED`."

    Design: Corner/state_machines/slot_completes_on_clock_advance
    """
    flavor = make_flavor_in_state("TEST_BATCH", name="Sched Swirl")
    slot = get_success_data(api.create_production_slot(
        create_production_slot_payload(flavor["id"],
                                       production_date="2026-09-10"), PS))
    confirmed = validate_success(api.confirm_production_slot(slot["id"], PS))
    assert confirmed["status"] == "CONFIRMED"

    validate_success(api.set_clock({"to_iso8601": "2026-09-11T00:00:00Z"}, POC))
    after = get_success_data(api.get_production_slot(slot["id"], PS))
    assert after["status"] == "COMPLETED"


def test_slot_confirm_requires_flavor_schedulable(api):
    """PRD §3.4: "Confirming a slot additionally requires the flavor's lifecycle to be schedulable — `TEST_BATCH`, `LIMITED_RUN`, or `CORE_LINE` — failing with `ERR_FLAVOR_NOT_SCHEDULABLE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/slot_confirm_requires_flavor_schedulable
    """
    flavor = make_flavor(name="Lab Prototype")  # stays DEVELOPMENT
    slot = validate_success(api.create_production_slot(
        create_production_slot_payload(flavor["id"]), PS), expected_status=201)
    assert slot["status"] == "PLANNED", "creation does not gate on flavor state"

    resp = api.confirm_production_slot(slot["id"], PS)
    validate_error(resp, ApiErrorId.ERR_FLAVOR_NOT_SCHEDULABLE)
    after = get_success_data(api.get_production_slot(slot["id"], PS))
    assert after["status"] == "PLANNED"


def test_slot_confirm_succeeds_once_flavor_schedulable(api):
    """PRD §3.4: "Confirming a slot additionally requires the flavor's lifecycle to be schedulable — `TEST_BATCH`, `LIMITED_RUN`, or `CORE_LINE` — failing with `ERR_FLAVOR_NOT_SCHEDULABLE` (HTTP 409)".
    PRD §3.4: "confirmation re-runs the same capacity check before moving the
    slot from `PLANNED` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/slot_confirm_requires_flavor_schedulable
    """
    flavor = make_flavor(name="Late Bloomer")  # DEVELOPMENT at slot creation
    slot = validate_success(api.create_production_slot(
        create_production_slot_payload(flavor["id"]), PS), expected_status=201)

    resp = api.confirm_production_slot(slot["id"], PS)
    validate_error(resp, ApiErrorId.ERR_FLAVOR_NOT_SCHEDULABLE)

    promote_flavor_to(flavor["id"], "TEST_BATCH")
    confirmed = validate_success(api.confirm_production_slot(slot["id"], PS))
    assert confirmed["status"] == "CONFIRMED", \
        "promoting the flavor opens the confirm gate"
