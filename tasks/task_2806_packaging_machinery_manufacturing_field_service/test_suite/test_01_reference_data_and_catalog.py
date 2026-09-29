"""Reference data: customer plants, the machine catalog and factory lines.

These are the four populations a PlatformAdmin seeds before any engineering work
can begin, together with the identity, default and uniqueness rules that govern
them.
"""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN,
    APP_ENGINEER,
    PLANNER,
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    assert_customer,
    assert_machine_model,
    assert_production_line,
    create_customer_payload,
    create_machine_model_payload,
    create_production_line_payload,
    seed_machine_model,
    seed_production_line,
)

def test_customer_registration_seeds_active_status_and_zero_open_orders():
    """Registering a customer plant echoes the declared inputs and seeds the
    derived trio the service owns: the lifecycle status, the open-order tally and
    the first version.

    PRD: "A newly registered customer has `status` `ACTIVE` and an
    `open_order_count` of 0; `open_order_count` is maintained by the service as
    the number of that customer's machine orders whose `fulfillment_status` is
    neither `ACCEPTED` nor `CANCELLED`, and it is re-derived whenever an order is
    created, engineered, or reaches final acceptance."

    Design: Corner/entities/customer_create_returns_201_with_status_active
    """
    response = api_client.create_customer(create_customer_payload(), ADMIN)
    data = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert response.json()["meta"]["api_request_id"]
    assert data["legal_name"] == "Northwind Beverages"
    assert data["region_code"] == "NA"
    assert data["product_variation_pct"] == pytest.approx(4.00, abs=0.01)
    assert data["status"] == "ACTIVE"
    assert data["open_order_count"] == 0
    assert data["version"] == 1
    assert_customer(data)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert data["updated_at"] is not None


def test_machine_model_read_back_returns_every_persisted_catalog_field():
    """A model read through its own endpoint returns the published specification
    plus the two fields the catalog owns, proving the row was persisted rather
    than merely reflected by the create handler.

    PRD: "Models are published with `lifecycle_status` `ACTIVE` and an
    `open_defect_review_count` of 0, the latter being a running tally of how many
    warranty claims across the installed base have had their machine-defect
    branch signed off against this model."

    Design: Corner/entities/machine_model_get_by_id_returns_stored_fields
    """
    model = seed_machine_model()

    data = validate_success(api_client.get_machine_model(model["id"], APP_ENGINEER))

    assert data["id"] == model["id"]
    assert data["model_code"] == "FL-600"
    assert data["machine_family"] == "FILLER"
    assert data["nameplate_rate_cpm"] == 600
    assert data["guarantee_efficiency_pct"] == pytest.approx(90.00, abs=0.01)
    assert data["base_price_cents"] == 68_000_000
    assert data["min_container_diameter_mm"] == 60
    assert data["max_container_diameter_mm"] == 110
    assert data["lifecycle_status"] == "ACTIVE"
    assert data["open_defect_review_count"] == 0
    assert_machine_model(data)


def test_customer_read_with_unknown_id_reports_the_customer_specific_not_found():
    """An unknown but well-formed customer id resolves to the customer's own
    not-found code rather than a generic 404 body.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/entities/customer_get_with_unknown_id_returns_customer_not_found
    """
    response = api_client.get_customer("00000000-0000-0000-0000-0000000000ff", ADMIN)

    error = validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"]


def test_customer_create_ignores_client_supplied_identity_and_status_fields():
    """Identity, timestamps, version and the lifecycle status are server-owned:
    smuggling them into the body changes nothing about the created row.

    PRD: "Clients never supply `id` values for resources they create; an `id`
    supplied in a request body is ignored."

    Design: Corner/entities/customer_system_fields_generated_on_create_input_ignored
    """
    smuggled_id = "deadbeef-0000-0000-0000-000000000001"
    payload = create_customer_payload(
        legal_name="Contoso Foods",
        region_code="EU",
        product_variation_pct=12.50,
        id=smuggled_id,
        status="SUSPENDED",
        version=42,
    )

    data = validate_success(api_client.create_customer(payload, ADMIN), 201)

    assert data["id"] != smuggled_id
    assert is_valid_uuid(data["id"])
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["product_variation_pct"] == pytest.approx(12.50, abs=0.01)


def test_production_line_create_ignores_a_smuggled_committed_days_ledger():
    """The committed-days ledger is derived from the line's slots, so a value
    supplied at creation is neither obeyed nor treated as a shape violation.

    PRD: "Lines open with `status` `OPEN` and `committed_slot_days` at 0."

    Design: Corner/entities/production_line_committed_slot_days_computed_input_ignored
    """
    payload = create_production_line_payload(committed_slot_days=99)

    data = validate_success(api_client.create_production_line(payload, ADMIN), 201)

    assert data["committed_slot_days"] == 0
    assert data["status"] == "OPEN"
    assert data["capacity_days_per_quarter"] == 120
    assert_production_line(data)


def test_machine_model_create_rejects_a_near_miss_machine_family():
    """`machine_family` is a closed set of four values, so a misspelling is a
    shape violation rather than a value the catalog stores verbatim.

    PRD: "Each `MachineModel` carries a `model_code` of 3 to 32 characters that
    must be unique across the catalog, a `machine_family` of `FILLER`, `CAPPER`,
    `LABELER` or `CARTONER`, a `nameplate_rate_cpm` of at least 1 container per
    minute measured at specification product, a `guarantee_efficiency_pct`
    between 50.00 and 100.00 inclusive to two decimal places that acts as the
    contractual attainment floor, a `base_price_cents` of at least 0 as the
    catalog list price, and the diameter window the base machine handles without
    change parts: `min_container_diameter_mm` of at least 1 and
    `max_container_diameter_mm` no smaller than the minimum."

    Design: Corner/entities/machine_model_create_with_unknown_machine_family_is_rejected
    """
    payload = create_machine_model_payload(
        model_code="XX-100",
        machine_family="FLLER",
        base_price_cents=1000,
    )

    response = api_client.create_machine_model(payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_machine_model_create_rejects_a_diameter_window_that_runs_backwards():
    """The diameter window is a relational constraint: both endpoints are legal
    integers on their own, yet a maximum below the minimum is still refused.

    PRD: "`ERR_INVALID_REQUEST` — body and query shape: required fields present,
    types correct, enum members drawn from the declared value set, numeric ranges
    honoured, an end date or end instant strictly after its matching start,
    `limit` inside 1 to 100 inclusive, `offset` at least 0."

    Design: Corner/entities/machine_model_max_diameter_below_min_is_rejected
    """
    payload = create_machine_model_payload(
        model_code="FL-601",
        min_container_diameter_mm=110,
        max_container_diameter_mm=60,
    )

    response = api_client.create_machine_model(payload, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_machine_model_read_with_unknown_id_reports_the_model_not_found_code():
    """The catalog read reports the model's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/machine_model_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_machine_model("11111111-1111-4111-8111-111111111111", ADMIN)

    validate_error(response, ApiErrorId.ERR_MACHINE_MODEL_NOT_FOUND.value, 404)


def test_production_line_read_with_unknown_id_reports_the_line_not_found_code():
    """The capacity read reports the line's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/production_line_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_production_line(
        "44444444-4444-4444-8444-444444444444", PLANNER
    )

    validate_error(response, ApiErrorId.ERR_PRODUCTION_LINE_NOT_FOUND.value, 404)


def test_field_engineer_read_with_unknown_id_reports_the_engineer_not_found_code():
    """The roster read reports the engineer's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/field_engineer_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_field_engineer(
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_FIELD_ENGINEER_NOT_FOUND.value, 404)


def test_second_line_reusing_an_existing_line_code_is_refused_and_changes_nothing():
    """Line codes are unique across the whole factory, and the rejected duplicate
    leaves the incumbent line's own family and capacity untouched.

    PRD: "A `ProductionLine` is created with a `line_code` of 2 to 24 characters
    unique across all lines — a duplicate again raising
    `ERR_DUPLICATE_IDENTIFIER` — a single `machine_family` that is the only
    family the line can build, a `changeover_buffer_days` of at least 0 that
    represents mandatory idle days appended to every occupied slot before the
    next slot may begin, and a `capacity_days_per_quarter` of at least 1 that is
    the build-day budget the line may commit over its rolling booking horizon."

    Design: Corner/errors/production_line_create_with_duplicate_line_code_returns_409
    """
    line = seed_production_line()

    response = api_client.create_production_line(
        create_production_line_payload(
            line_code="LINE-A",
            machine_family="CAPPER",
            changeover_buffer_days=2,
            capacity_days_per_quarter=90,
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, 409)
    survivor = validate_success(api_client.get_production_line(line["id"], PLANNER))
    assert survivor["machine_family"] == "FILLER"
    assert survivor["capacity_days_per_quarter"] == 120


def test_production_planner_cannot_open_a_new_production_line():
    """Planners consume lines but only a PlatformAdmin creates shop-floor
    capacity, and the denial precedes any field validation so nothing persists.

    PRD: "If both headers are present but the value of `X-User-Role` is not one
    of the six roles defined below, or is a valid role that is not authorised for
    the endpoint being called, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/production_line_create_by_production_planner_returns_403
    """
    payload = create_production_line_payload(line_code="LINE-Z")

    response = api_client.create_production_line(payload, PLANNER)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)
    assert "id" not in (response.json().get("data") or {})
