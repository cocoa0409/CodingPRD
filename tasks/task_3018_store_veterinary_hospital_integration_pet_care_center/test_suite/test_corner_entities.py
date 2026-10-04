"""Resource creation, the common-field split, and store-scoped uniqueness."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_bay,
    create_member,
    create_pet,
    create_store,
    factories,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]
ANY = TEST_USERS["any_headers"]


def test_store_create_mints_every_derived_field_and_opens_in_the_open_posture(api):
    """Only the five declared inputs are supplied; the rest come back computed.

    PRD §3.1: "The new centre opens in the `OPEN` posture with an
    `hospital_occupancy` of zero, and every derived counter it carries starts at
    zero as well: no clinics are `FROZEN`, no training slots are `RESTRICTED` or
    awaiting acknowledgement, no pharmacy orders are held, no cross-sell credit
    has been granted, and the store's `incident_risk_index` stands at zero."
    PRD §2.4: "The `version` starts at 1 for a newly created row"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/store_create_mints_derived_fields_and_starts_open
    """
    response = api.create_store(
        factories.store_payload(
            store_code="ST-1001", city="Reno", state_code="NY", service_bay_count=3,
            hospital_capacity=4,
        ),
        ADMIN,
    )
    store = validate_success(response, 201)
    body = response.json()

    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert store["store_code"] == "ST-1001"
    assert store["state_code"] == "NY"
    assert store["hospital_capacity"] == 4
    assert store["hospital_posture"] == "OPEN"
    assert store["hospital_occupancy"] == 0
    assert store["frozen_vaccination_clinics"] == 0
    assert store["restricted_training_slots_pending"] == 0
    assert store["stores_held_total"] == 0
    assert store["cross_sell_credit_balance_cents"] == 0
    assert store["incident_risk_index"] == 0
    assert store["pharmacy_hold_until"] is None
    assert store["version"] == 1


def test_pet_create_sets_the_three_system_fields_rather_than_taking_them_from_the_client(api):
    """A freshly registered pet reads back with the three server-set fields.

    PRD §3.1: "Three fields on the new pet are set by the system rather than
    supplied: `status` begins `ACTIVE`, `risk_score` begins at zero, and
    `rabies_vaccination_expires_at` begins null."
    PRD §3.1: "A pet's weight must be strictly greater than zero."
    PRD §2.4: "The `version` starts at 1 for a newly created row"

    Design: Corner/entities/pet_create_ignores_client_supplied_risk_and_expiry
    """
    store = create_store(api, store_code="ST-1002", state_code="TX", hospital_capacity=3)
    member = create_member(
        api, store["id"], full_name="Aldous Pike", email="aldous@example.com", state_code="TX"
    )
    pet = create_pet(
        api, member["id"], name="Nutmeg", species="FELINE", breed="Maine Coon", weight_kg=6.2
    )
    assert pet["risk_score"] == 0
    assert pet["rabies_vaccination_expires_at"] is None
    assert pet["status"] == "ACTIVE"
    assert pet["version"] == 1
    assert pet["weight_kg"] == 6.2


def test_breed_handling_rule_carries_no_updated_at_and_no_version(api):
    """Reference configuration is written once and read thereafter.

    PRD §2.4: "The `BreedHandlingRule` is reference configuration that is written
    once and read thereafter, and it carries only `id` and `created_at` — it has
    no `updated_at` and no `version`."
    PRD §3.1: "Breed handling rules, registered by a `PlatformAdmin`, carry a
    `breed`, a `species`, a `risk_points` value that must be zero or greater, a
    `handling_tier` of `STANDARD`, `SENSITIVE` or `HIGH_RISK`, and an
    `allowed_for_grooming` flag that defaults to true."

    Design: Corner/entities/breed_handling_rule_is_immutable_and_has_no_version
    """
    create_store(api, store_code="ST-1003", state_code="FL", hospital_capacity=3)
    rule = get_success_data(
        api.create_breed_rule(
            factories.breed_rule_payload(
                breed="Akita", species="CANINE", risk_points=20, handling_tier="SENSITIVE",
                allowed_for_grooming=True,
            ),
            ADMIN,
        ),
        201,
    )
    assert rule["risk_points"] == 20
    assert rule["handling_tier"] == "SENSITIVE"
    assert rule["allowed_for_grooming"] is True
    assert rule["created_at"]
    assert "updated_at" not in rule
    assert "version" not in rule


def test_an_unknown_store_on_a_nested_path_reports_the_store_as_missing(api):
    """The left-to-right resolution order names the store, not the leaf.

    PRD §2.12: "when a path carries more than one identifier the server validates
    them in left-to-right order: the store is resolved before anything nested
    inside it, then the member, then the pet, booking, encounter, package or
    clinic, and only then the leaf resource."
    PRD §2.12: "The request is rejected as soon as an identifier in that order
    fails to resolve, with the not-found error belonging to that particular
    entity — `ERR_STORE_NOT_FOUND`"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/store_not_found_on_a_descendant_path_identifier
    """
    response = api.get_store_service_bay(NON_EXISTENT_UUID, NON_EXISTENT_UUID, ANY)
    error = validate_error(response, ApiErrorId.STORE_NOT_FOUND.value)
    body = response.json()

    assert set(error.keys()) == {"error_id", "message"}
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert "data" in body and "id" not in error


def test_a_second_bay_of_the_same_code_is_refused_within_a_store_but_not_between_stores(api):
    """Bay-code uniqueness is scoped to the owning store.

    PRD §3.1: "Bays are the units of shared-space contention — a booking competes
    for a bay and a time window, not for a room number or a person — and a second
    bay of the same code in the same store is refused as a duplicate."
        PRD §2.13: "Declared uniqueness is enforced across the graph as well: a
    duplicate `store_code`, a duplicate member `email`, a duplicate `bay_code`
    within a store, a breed rule repeated for the same breed and species, a rabies
    certificate serial already in use, and a member attempting to hold a second
    `ACTIVE` package at a tier already active are each refused"
    PRD §3.1: "A new bay starts `ACTIVE`"

    Design: Corner/entities/service_bay_code_uniqueness_within_a_store
    """
    first_store = create_store(api, store_code="ST-1004", state_code="CA", hospital_capacity=3)
    second_store = create_store(api, store_code="ST-1005", state_code="CA", hospital_capacity=3)
    create_bay(api, first_store["id"], "GROOMING")

    duplicate = api.create_service_bay(
        first_store["id"], factories.service_bay_payload("GROOMING"), MANAGER
    )
    validate_error(duplicate, ApiErrorId.BAY_CODE_DUPLICATE.value)

    elsewhere = create_bay(api, second_store["id"], "GROOMING")
    assert elsewhere["bay_code"] == "GROOMING"
    assert elsewhere["status"] == "ACTIVE"
    assert elsewhere["store_id"] == second_store["id"]