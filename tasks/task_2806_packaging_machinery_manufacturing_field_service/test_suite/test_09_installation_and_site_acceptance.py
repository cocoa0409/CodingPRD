"""Recording the asset on the customer's floor and honouring the guarantee there.

Site acceptance reuses the factory scoring machinery but adds an ownership chain,
a calendar ordering against the factory run and a training log.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    INSPECTOR,
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    book_test,
    create_acceptance_test_payload,
    create_installed_machine_payload,
    finalize_acceptance_test_payload,
    read_customer,
    read_machine,
    read_order,
    read_test,
    seed_customer,
    setup_installed_machine,
    setup_reference_data,
    setup_shipped_order,
    start_test,
)


def test_a_site_test_may_not_be_dated_before_the_factory_test_it_follows():
    """The order is already installed so the state gate passes; the only defect is the
    calendar, and the same booking one day later is accepted.

    PRD: "A factory test may only be booked while the order is `IN_BUILD`; a site test
    may only be booked while the order is `INSTALLED`, which already implies a passed
    factory test exists, and its `scheduled_on` must fall on or after the
    `scheduled_on` of that passed factory test for the same order — a site test dated
    earlier is refused with `ERR_SAT_BEFORE_FAT`."

    Design: Corner/errors/sat_scheduled_before_fat_returns_422_sat_before_fat
    """
    env = setup_installed_machine(setup_reference_data(line={}))

    response = api_client.create_acceptance_test(
        create_acceptance_test_payload(
            env["order"]["id"],
            kind="SAT",
            scheduled_on="2026-08-25",
            required_operators_trained=2,
        ),
        INSPECTOR,
    )

    validate_error(response, ApiErrorId.ERR_SAT_BEFORE_FAT.value, 422)
    assert read_order(env["order"]["id"])["fulfillment_status"] == "INSTALLED"
    _rows, meta = validate_paginated(
        api_client.list_acceptance_tests(
            INSPECTOR, params={"machine_order_id": env["order"]["id"], "kind": "SAT"}
        )
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api_client.create_acceptance_test(
            create_acceptance_test_payload(
                env["order"]["id"],
                kind="SAT",
                scheduled_on="2026-08-26",
                required_operators_trained=2,
            ),
            INSPECTOR,
        ),
        201,
    )
    assert accepted["kind"] == "SAT"


def test_site_sign_off_is_gated_on_the_crew_and_not_on_the_machine():
    """A run that would comfortably meet the guarantee is still refused while the
    training log is one operator short, and nothing about the asset moves.

    PRD: "The site run's container minimum is 200 rather than 500, and the training
    log matters: `operators_trained_count` must be at least
    `required_operators_trained` or the finalize is refused with
    `ERR_OPERATOR_TRAINING_INCOMPLETE`."

    Design: Corner/errors/sat_finalize_with_untrained_crew_returns_422_operator_training_incomplete
    """
    env = setup_installed_machine(setup_reference_data(line={}))
    env = start_test(book_test(env, "SAT", required_operators_trained=2), "SAT")

    response = api_client.finalize_acceptance_test(
        env["sat"]["id"], finalize_acceptance_test_payload(570, 96.00, 1), INSPECTOR
    )

    validate_error(response, ApiErrorId.ERR_OPERATOR_TRAINING_INCOMPLETE.value, 422)
    assert read_test(env["sat"]["id"])["status"] == "IN_PROGRESS"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "INSTALLED"
    assert read_machine(env["machine"]["id"])["status"] == "INSTALLED"

    signed = validate_success(
        api_client.finalize_acceptance_test(
            env["sat"]["id"], finalize_acceptance_test_payload(570, 96.00, 2), INSPECTOR
        )
    )
    assert signed["status"] == "PASSED"


def test_an_asset_cannot_be_installed_against_a_customer_who_did_not_buy_it():
    """Both rows exist, so this is not a lookup failure: the ownership chain between
    the installation and the order that produced the machine is what breaks.

    PRD: "The cited order must be `SHIPPED`, and the ownership chain must be coherent:
    the installation's `machine_order_id` must be the order named in the request and
    its `customer_id` must equal that order's buyer, or the request is refused with
    `ERR_MACHINE_ORDER_CUSTOMER_MISMATCH`."

    Design: Corner/endpoints/installed_machine_create_with_foreign_customer_returns_422
    """
    env = setup_shipped_order(setup_reference_data(line={}))
    bystander = seed_customer(
        legal_name="Contoso Foods", region_code="EU", product_variation_pct=6.00
    )

    response = api_client.create_installed_machine(
        create_installed_machine_payload(
            env["order"]["id"], bystander["id"], serial_number="SN-2806-009"
        ),
        SERVICE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_MACHINE_ORDER_CUSTOMER_MISMATCH.value, 422)
    assert read_order(env["order"]["id"])["fulfillment_status"] == "SHIPPED"
    rows, meta = validate_paginated(
        api_client.list_installed_machines(
            SERVICE_MANAGER, params={"machine_order_id": env["order"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_final_acceptance_re_derives_the_customers_open_order_tally():
    """The tally is recomputed rather than incremented, so the moment the order reaches
    its terminal fulfillment state the customer has nothing in flight.

    PRD: "The order's `fulfillment_status` moves from `INSTALLED` to `ACCEPTED`, its
    terminal fulfillment state, and the buying customer's `open_order_count` is
    re-derived because the order has left the open set."

    Design: Corner/cross_cutting_complexity_layers/customer_open_order_count_drops_when_order_reaches_accepted
    """
    env = setup_installed_machine(setup_reference_data(line={}))
    env = start_test(book_test(env, "SAT", required_operators_trained=2), "SAT")
    assert read_customer(env["customer"]["id"])["open_order_count"] == 1

    data = validate_success(
        api_client.finalize_acceptance_test(
            env["sat"]["id"], finalize_acceptance_test_payload(570, 96.00, 2), INSPECTOR
        )
    )

    assert data["status"] == "PASSED"
    assert data["attainment_pct"] == pytest.approx(91.20, abs=0.01)
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ACCEPTED"
    assert read_machine(env["machine"]["id"])["status"] == "ACCEPTED"
    assert read_customer(env["customer"]["id"])["open_order_count"] == 0


def test_installed_machine_read_with_unknown_id_reports_the_asset_not_found_code():
    """The installed-base read reports the asset's own miss code.

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

    Design: Corner/errors/installed_machine_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_installed_machine(
        "88888888-8888-4888-8888-888888888888", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INSTALLED_MACHINE_NOT_FOUND.value, 404)
