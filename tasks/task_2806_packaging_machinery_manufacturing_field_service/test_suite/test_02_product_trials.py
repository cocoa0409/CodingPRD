"""Application engineering: the rig trial cycle and the configuration verdict.

Every machine sold starts as a trial, so this file covers the trial's own
non-linear lifecycle, the diameter window enforced when a product goes onto the
rig, the recommendation arithmetic and the ownership rule that lets a plant open
its own trial.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    APP_ENGINEER,
    ApiErrorId,
    api_client,
    assert_product_trial,
    create_product_trial_payload,
    make_customer_contact_headers,
    read_trial,
    record_trial_result_payload,
    seed_customer,
    seed_machine_model,
    setup_reference_data,
    setup_submitted_trial,
)


def test_moving_an_in_range_product_onto_the_rig_opens_the_first_test_run():
    """Starting the first run is not a retest: the trial reaches TESTING with the
    retest counter untouched and the verdict still pending.

    PRD: "Moving a trial onto the rig advances it from `SUBMITTED` to `TESTING`.
    Four conditions must hold: the trial is in `SUBMITTED`, the owning customer is
    `ACTIVE`, the candidate model is `ACTIVE`, and the trialled container fits the
    base machine — that is, `container_diameter_mm` is at least the model's
    `min_container_diameter_mm` and at most its `max_container_diameter_mm`, both
    bounds inclusive."

    Design: Corner/state_machines/product_trial_start_testing_moves_submitted_to_testing
    """
    env = setup_submitted_trial()

    data = validate_success(
        api_client.start_testing_product_trial(env["trial"]["id"], APP_ENGINEER)
    )

    assert data["status"] == "TESTING"
    assert data["retest_count"] == 0
    assert data["config_recommendation"] == "PENDING"
    assert data["version"] == 2
    assert_product_trial(data)


def test_recording_a_result_on_a_trial_never_started_is_refused():
    """There is no result-recording edge out of SUBMITTED, so the measured rate is
    never written.

    PRD: "The outcome then decides the trial's own state, and the state it may
    move from is checked before anything else about the trial is evaluated
    (`ERR_INVALID_TRIAL_STATE`)."

    Design: Corner/state_machines/product_trial_record_result_from_submitted_returns_invalid_trial_state
    """
    env = setup_submitted_trial()

    response = api_client.record_result_product_trial(
        env["trial"]["id"], record_trial_result_payload(570, "PASS"), APP_ENGINEER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_TRIAL_STATE.value, 409)
    after = read_trial(env["trial"]["id"])
    assert after["status"] == "SUBMITTED"
    assert after["config_recommendation"] == "PENDING"


def test_a_rejected_trial_cannot_be_put_back_on_the_rig():
    """REJECTED is terminal, so unlike a trial parked in RETEST_REQUIRED it has no
    way back into testing and its infeasible verdict stands.

    PRD: "`PASSED` and `REJECTED` are both terminal — no further trial transition
    is available from either."

    Design: Corner/state_machines/product_trial_start_testing_from_rejected_terminal_is_rejected
    """
    env = setup_submitted_trial()
    trial_id = env["trial"]["id"]
    validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))
    validate_success(
        api_client.record_result_product_trial(
            trial_id, record_trial_result_payload(120, "REJECT"), APP_ENGINEER
        )
    )

    response = api_client.start_testing_product_trial(trial_id, APP_ENGINEER)

    validate_error(response, ApiErrorId.ERR_INVALID_TRIAL_STATE.value, 409)
    after = read_trial(trial_id)
    assert after["status"] == "REJECTED"
    assert after["config_recommendation"] == "NOT_FEASIBLE"
    assert after["retest_count"] == 0


def test_a_container_outside_the_model_window_is_only_refused_at_the_rig():
    """The diameter window lives on the model and is checked when the product goes
    onto the rig, so the oversized trial is accepted at creation and only the
    start is refused.

    PRD: "A container outside that band is rejected with
    `ERR_CONTAINER_OUT_OF_RANGE`; note that this is a hard rejection at trial time
    only, because a later aftermarket kit for an out-of-band container is priced
    with a surcharge rather than refused."

    Design: Corner/validations/start_testing_with_container_outside_model_window_returns_422
    """
    env = setup_reference_data(line=None, engineer=None)
    created = validate_success(
        api_client.create_product_trial(
            create_product_trial_payload(
                env["customer"]["id"],
                env["model"]["id"],
                product_name="Growler 2L",
                container_family="GLASS_ROUND",
                container_diameter_mm=130,
            ),
            APP_ENGINEER,
        ),
        201,
    )

    response = api_client.start_testing_product_trial(created["id"], APP_ENGINEER)

    validate_error(response, ApiErrorId.ERR_CONTAINER_OUT_OF_RANGE.value, 422)
    assert read_trial(created["id"])["status"] == "SUBMITTED"


def test_effective_ratio_exactly_on_the_heavy_duty_floor_selects_heavy_duty():
    """The customer's product variation is subtracted before the band lookup, so
    480 of 600 nameplate lands exactly on the inclusive HEAVY_DUTY floor rather
    than in the STANDARD band an implementation that skips the subtraction would
    report.

    PRD: "Otherwise, an effective ratio of at least 90.00 selects `STANDARD`, an
    effective ratio below that but at least 75.00 selects `HEAVY_DUTY`, and
    anything below 75.00 selects `NOT_FEASIBLE`. Both floors are inclusive:
    exactly 90.00 is `STANDARD` and exactly 75.00 is `HEAVY_DUTY`."

    Design: Corner/calculations/trial_effective_ratio_exactly_at_heavy_duty_floor_is_heavy_duty
    """
    env = setup_submitted_trial(
        setup_reference_data(
            customer={
                "legal_name": "Meridian Dairy",
                "region_code": "EU",
                "product_variation_pct": 5.00,
            }
        ),
        product_name="Whole Milk 1L",
        container_family="HDPE_ROUND",
        container_diameter_mm=95,
    )
    validate_success(api_client.start_testing_product_trial(env["trial"]["id"], APP_ENGINEER))

    data = validate_success(
        api_client.record_result_product_trial(
            env["trial"]["id"], record_trial_result_payload(480, "PASS"), APP_ENGINEER
        )
    )

    assert data["status"] == "PASSED"
    assert data["measured_rate_cpm"] == 480
    assert data["rate_ratio_pct"] == pytest.approx(80.00, abs=0.01)
    assert data["config_recommendation"] == "HEAVY_DUTY"


def test_trial_listing_reports_the_unpaginated_total_alongside_a_short_page():
    """A two-row page out of three matching trials reports the pre-pagination
    total and flags that rows remain.

    PRD: "The `meta` block of a list response carries `limit` and `offset` as they
    were applied, `total_count` as the number of rows matching the filters before
    pagination was applied, and `has_more` as a boolean that is true exactly when
    rows remain beyond the current page."

    Design: Corner/entities/product_trial_list_paginates_with_total_count_and_has_more
    """
    env = setup_reference_data()
    for name, diameter in (("Cider 500", 82), ("Cider 750", 84), ("Cider 1000", 86)):
        validate_success(
            api_client.create_product_trial(
                create_product_trial_payload(
                    env["customer"]["id"],
                    env["model"]["id"],
                    product_name=name,
                    container_diameter_mm=diameter,
                ),
                APP_ENGINEER,
            ),
            201,
        )

    response = api_client.list_product_trials(
        ADMIN, params={"customer_id": env["customer"]["id"], "limit": 2, "offset": 0}
    )

    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_trial_for_an_unknown_customer_reports_the_customer_miss_not_the_model():
    """Both foreign keys are resolved independently, so a valid model reference
    does not mask an unknown customer reference.

    PRD: "The existence family — every referenced resource exists. Resolution is
    strictly left to right: path identifiers first in the order they appear in the
    path, then body foreign keys in the order they are listed for that endpoint in
    §4."

    Design: Corner/entities/product_trial_create_with_unknown_customer_returns_customer_not_found
    """
    model = seed_machine_model()

    response = api_client.create_product_trial(
        create_product_trial_payload(
            "00000000-0000-0000-0000-0000000000aa", model["id"]
        ),
        APP_ENGINEER,
    )

    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)


def test_a_trial_request_without_a_declared_role_is_unauthenticated():
    """The role header is mandatory on every endpoint and its absence is checked
    before anything else, so no trial row is created.

    PRD: "Every request to every endpoint must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, declaring the capacity the caller is
    acting in. If either header is absent or blank, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) — this check precedes all others, including
    the check that the route's resources exist."

    Design: Corner/errors/product_trial_create_without_role_header_returns_401_unauthenticated
    """
    env = setup_reference_data()
    roleless = {"X-User-ID": "test-application-engineer-1", "Content-Type": "application/json"}

    response = api_client.create_product_trial(
        create_product_trial_payload(env["customer"]["id"], env["model"]["id"]), roleless
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    _, meta = validate_paginated(api_client.list_product_trials(ADMIN))
    assert meta["total_count"] == 0


def test_trial_read_with_unknown_id_reports_the_trial_not_found_code():
    """The rig read reports the trial's own miss code.

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

    Design: Corner/errors/product_trial_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_product_trial(
        "22222222-2222-4222-8222-222222222222", APP_ENGINEER
    )

    validate_error(response, ApiErrorId.ERR_PRODUCT_TRIAL_NOT_FOUND.value, 404)


def test_a_third_retest_result_is_refused_and_leaves_the_trial_on_the_rig():
    """The retest counter is cumulative, so once two retests have been consumed a
    further retest outcome is refused and the trial stays in testing with its
    previous measured rate.

    PRD: "From `TESTING`, a retest outcome moves the trial to `RETEST_REQUIRED`,
    and is itself subject to the retest ceiling: with `retest_count` already at 2
    the request is refused with `ERR_TRIAL_RETEST_LIMIT`."

    Design: Corner/errors/product_trial_third_retest_returns_409_retest_limit
    """
    env = setup_submitted_trial()
    trial_id = env["trial"]["id"]
    for rate in (520, 530):
        validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))
        validate_success(
            api_client.record_result_product_trial(
                trial_id, record_trial_result_payload(rate, "RETEST"), APP_ENGINEER
            )
        )
    validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))

    response = api_client.record_result_product_trial(
        trial_id, record_trial_result_payload(540, "RETEST"), APP_ENGINEER
    )

    validate_error(response, ApiErrorId.ERR_TRIAL_RETEST_LIMIT.value, 409)
    after = read_trial(trial_id)
    assert after["status"] == "TESTING"
    assert after["retest_count"] == 2
    assert after["measured_rate_cpm"] == 530


def test_a_plant_contact_may_open_a_trial_against_its_own_customer_record():
    """The customer's own contact gets the identical result an application
    engineer would: a submitted trial, no retests, and the caller's customer on
    the row.

    PRD: "A trial is opened either by an `ApplicationEngineer` or by the
    customer's own `CustomerContact` — in the latter case only for their own
    customer record, since the payload names the `customer_id` that the trial is
    run for and a mismatch against `X-User-ID` yields `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_contact_creates_trial_for_own_customer_succeeds
    """
    customer = seed_customer()
    model = seed_machine_model()

    data = validate_success(
        api_client.create_product_trial(
            create_product_trial_payload(customer["id"], model["id"]),
            make_customer_contact_headers(customer["id"]),
        ),
        201,
    )

    assert data["status"] == "SUBMITTED"
    assert data["retest_count"] == 0
    assert data["customer_id"] == customer["id"]


def test_a_retest_required_trial_returns_to_the_rig_and_consumes_one_retest():
    """The back edge out of RETEST_REQUIRED is the same start-testing capability
    used for the first run, and taking it charges the retest counter.

    PRD: "A trial sitting in `RETEST_REQUIRED` returns to `TESTING` when its
    `retest_count` is strictly less than 2, and that return increments
    `retest_count` by 1 and the trial's `version` by 1."

    Design: Difficulty/non_linear_state_machine/product_trial_retest_cycle_reenters_testing_then_passes
    """
    env = setup_submitted_trial()
    trial_id = env["trial"]["id"]
    validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))
    parked = validate_success(
        api_client.record_result_product_trial(
            trial_id, record_trial_result_payload(400, "RETEST"), APP_ENGINEER
        )
    )
    assert parked["status"] == "RETEST_REQUIRED"
    assert parked["retest_count"] == 0

    data = validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))

    assert data["status"] == "TESTING"
    assert data["retest_count"] == 1
    assert data["version"] == parked["version"] + 1


def test_a_trial_that_passes_after_one_retest_ends_standard_with_the_retest_recorded():
    """A second pass through the rig can lift the verdict from infeasible to
    standard, so the recommendation is recut on every result rather than being
    latched by the first run.

    PRD: "In all three cases the measured rate is stored on the trial and the
    derived figures are re-cut. First, `rate_ratio_pct` is the measured rate
    divided by the model's `nameplate_rate_cpm`, multiplied by 100, rounded half up
    to two decimal places."

    Design: Difficulty/non_linear_state_machine/product_trial_retest_cycle_reenters_testing_then_passes
    """
    env = setup_submitted_trial()
    trial_id = env["trial"]["id"]
    validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))
    first = validate_success(
        api_client.record_result_product_trial(
            trial_id, record_trial_result_payload(400, "RETEST"), APP_ENGINEER
        )
    )
    assert first["config_recommendation"] == "NOT_FEASIBLE"
    validate_success(api_client.start_testing_product_trial(trial_id, APP_ENGINEER))

    data = validate_success(
        api_client.record_result_product_trial(
            trial_id, record_trial_result_payload(570, "PASS"), APP_ENGINEER
        )
    )

    assert data["status"] == "PASSED"
    assert data["retest_count"] == 1
    assert data["rate_ratio_pct"] == pytest.approx(95.00, abs=0.01)
    assert data["config_recommendation"] == "STANDARD"
    assert data["measured_rate_cpm"] == 570
