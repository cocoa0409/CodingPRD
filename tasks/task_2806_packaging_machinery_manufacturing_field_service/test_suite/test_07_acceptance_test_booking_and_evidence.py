"""Booking a factory run and putting the customer's evidence on the floor.

A test is only bookable once per kind while it is live, and the OEM refuses to
score any machine that has not run the customer's own product in sufficient
quantity.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    INSPECTOR,
    ApiErrorId,
    api_client,
    book_test,
    create_acceptance_test_payload,
    finalize_acceptance_test_payload,
    read_order,
    read_test,
    setup_order_in_build,
    setup_reference_data,
    start_acceptance_test_payload,
)


def test_a_scheduled_run_cannot_be_scored_before_it_has_started():
    """Finalize is legal only from IN_PROGRESS, so a scheduled run keeps its zeroed
    scoreboard and the order stays on the shop floor.

    PRD: "A finalize addressed to a test that is not `IN_PROGRESS` is refused with
    `ERR_INVALID_TEST_STATE`, and a site run whose `operators_trained_count` is
    below its `required_operators_trained` is refused with
    `ERR_OPERATOR_TRAINING_INCOMPLETE` — the OEM will not sign off a site with an
    untrained crew."

    Design: Corner/errors/acceptance_test_finalize_before_start_returns_409_invalid_test_state
    """
    env = book_test(setup_order_in_build(setup_reference_data(line={})), "FAT")

    response = api_client.finalize_acceptance_test(
        env["fat"]["id"], finalize_acceptance_test_payload(570, 96.00), INSPECTOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_TEST_STATE.value, 409)
    test = read_test(env["fat"]["id"])
    assert test["status"] == "SCHEDULED"
    assert test["attainment_pct"] == 0
    assert test["guarantee_met"] is False
    assert read_order(env["order"]["id"])["fulfillment_status"] == "IN_BUILD"


def test_only_one_live_factory_run_may_exist_per_order():
    """A second booking on a different date does not queue behind the first: it is
    refused outright and exactly one factory run survives.

    PRD: "Only one live test of a given kind may exist per order at a time: if
    another test of the same kind on the same order is already `SCHEDULED` or
    `IN_PROGRESS`, the booking is refused with `ERR_DUPLICATE_ACCEPTANCE_TEST`."

    Design: Corner/errors/second_fat_while_first_scheduled_returns_409_duplicate_acceptance_test
    """
    env = book_test(setup_order_in_build(setup_reference_data(line={})), "FAT")

    response = api_client.create_acceptance_test(
        create_acceptance_test_payload(env["order"]["id"], kind="FAT", scheduled_on="2026-08-28"),
        INSPECTOR,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACCEPTANCE_TEST.value, 409)
    assert read_test(env["fat"]["id"])["scheduled_on"] == "2026-08-26"
    rows, meta = validate_paginated(
        api_client.list_acceptance_tests(
            INSPECTOR, params={"machine_order_id": env["order"]["id"], "kind": "FAT"}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_no_machine_is_scored_on_surrogate_product_however_many_containers_arrive():
    """A generous container count cannot substitute for the customer's own product,
    and the refused start leaves the evidence fields untouched.

    PRD: "A run started without the customer's product is refused with
    `ERR_CUSTOMER_PRODUCT_REQUIRED`."

    Design: Corner/errors/fat_start_without_customer_product_returns_422_customer_product_required
    """
    env = book_test(setup_order_in_build(setup_reference_data(line={})), "FAT")

    response = api_client.start_acceptance_test(
        env["fat"]["id"], start_acceptance_test_payload(False, 900), INSPECTOR
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_PRODUCT_REQUIRED.value, 422)
    test = read_test(env["fat"]["id"])
    assert test["status"] == "SCHEDULED"
    assert test["containers_supplied_count"] == 0
    assert test["customer_product_supplied"] is False


def test_the_factory_container_floor_of_five_hundred_is_inclusive():
    """One container short of the factory minimum is refused; the identical call at
    the floor itself puts the run on the rig.

    PRD: "The container minimum differs by kind: a factory run needs at least 500
    supplied containers and a site run needs at least 200, and a shortfall is
    refused with `ERR_INSUFFICIENT_CONTAINERS`."

    Design: Corner/errors/fat_start_with_499_containers_returns_422_insufficient_containers
    """
    env = book_test(setup_order_in_build(setup_reference_data(line={})), "FAT")

    short = api_client.start_acceptance_test(
        env["fat"]["id"], start_acceptance_test_payload(True, 499), INSPECTOR
    )

    validate_error(short, ApiErrorId.ERR_INSUFFICIENT_CONTAINERS.value, 422)
    assert read_test(env["fat"]["id"])["status"] == "SCHEDULED"

    data = validate_success(
        api_client.start_acceptance_test(
            env["fat"]["id"], start_acceptance_test_payload(True, 500), INSPECTOR
        )
    )
    assert data["status"] == "IN_PROGRESS"
    assert data["containers_supplied_count"] == 500


def test_acceptance_test_read_with_unknown_id_reports_the_test_not_found_code():
    """The quality read reports the acceptance test's own miss code.

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

    Design: Corner/errors/acceptance_test_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_acceptance_test(
        "77777777-7777-4777-8777-777777777777", INSPECTOR
    )

    validate_error(response, ApiErrorId.ERR_ACCEPTANCE_TEST_NOT_FOUND.value, 404)
