"""Wrapping an accepted machine in coverage, and the two ways out of it.

Activation funds the goodwill pot and is bounded by the contract term; leaving
ACTIVE early is blocked while any claim is unresolved.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SERVICE_MANAGER,
    ApiErrorId,
    api_client,
    create_pm_visit_payload,
    draft_contract,
    move_clock,
    open_claim,
    read_claim,
    read_contract,
    read_machine,
    seed_field_engineer,
    setup_accepted_machine,
    setup_active_contract,
    setup_reference_data,
)

SILVER_TERM = {
    "tier": "SILVER",
    "start_date": "2026-08-01",
    "end_date": "2027-07-31",
    "pm_visits_included": 2,
    "goodwill_budget_initial_cents": 350_000,
}


def _accepted_machine():
    return setup_accepted_machine(setup_reference_data(line={}))


def test_a_live_contract_cannot_be_activated_again_and_the_pot_is_not_re_seeded():
    """Activation funds the pot exactly once: the second attempt is refused rather than
    topping the goodwill budget back up.

    PRD: "`EXPIRED` and `TERMINATED` are terminal, and any contract transition
    requested from the wrong state is refused with `ERR_INVALID_CONTRACT_STATE`."

    Design: Corner/errors/service_contract_activate_twice_returns_409_invalid_contract_state
    """
    env = setup_active_contract(_accepted_machine(), contract_overrides=dict(SILVER_TERM))

    response = api_client.activate_service_contract(env["contract"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_INVALID_CONTRACT_STATE.value, 409)
    contract = read_contract(env["contract"]["id"])
    assert contract["status"] == "ACTIVE"
    assert contract["goodwill_budget_cents"] == 350_000
    assert contract["pm_visits_used"] == 0


def test_a_contract_cannot_be_activated_before_its_term_opens():
    """The clock must stand inside the term, so a contract sold for next month stays in
    draft with an unfunded pot until the term arrives.

    PRD: "The covered machine must be `ACCEPTED`, and the logical clock's UTC date must
    fall inside the contract term — on or after `start_date` and on or before
    `end_date` — or activation is refused with `ERR_CONTRACT_WINDOW_INVALID`."

    Design: Corner/errors/service_contract_activate_outside_window_returns_422_contract_window_invalid
    """
    env = draft_contract(
        _accepted_machine(),
        **dict(SILVER_TERM, start_date="2026-09-01", end_date="2027-08-31"),
    )

    response = api_client.activate_service_contract(env["contract"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID.value, 422)
    contract = read_contract(env["contract"]["id"])
    assert contract["status"] == "DRAFT"
    assert contract["goodwill_budget_cents"] == 0

    move_clock("2026-09-01T00:00:00.000Z")
    activated = validate_success(
        api_client.activate_service_contract(env["contract"]["id"], SERVICE_MANAGER)
    )
    assert activated["status"] == "ACTIVE"


def test_a_contract_cannot_expire_while_its_last_covered_day_is_still_ahead():
    """Expiry is a calendar fact, not a decision: it becomes available only once the
    clock is strictly past the last covered day.

    PRD: "Expiring a contract requires the logical clock's UTC date to be strictly
    after the contract's `end_date`; an early expiry is refused with
    `ERR_CONTRACT_NOT_EXPIRABLE`."

    Design: Corner/errors/service_contract_expire_before_end_date_returns_422_contract_not_expirable
    """
    env = setup_active_contract(_accepted_machine(), contract_overrides=dict(SILVER_TERM))

    response = api_client.expire_service_contract(env["contract"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_EXPIRABLE.value, 422)
    assert read_contract(env["contract"]["id"])["status"] == "ACTIVE"

    move_clock("2027-08-01T00:00:00.000Z")
    expired = validate_success(
        api_client.expire_service_contract(env["contract"]["id"], SERVICE_MANAGER)
    )
    assert expired["status"] == "EXPIRED"


def test_an_unresolved_claim_blocks_early_termination_of_the_contract():
    """The customer cannot be walked off coverage while the OEM still owes them an
    answer on a claim, and the claim itself is left untouched.

    PRD: "Terminating a contract early requires that no warranty claim on it is still
    in `SUBMITTED`, `PRODUCT_VARIATION_REVIEW` or `DEFECT_REVIEW` — an unresolved claim
    blocks termination with `ERR_CLAIM_STILL_OPEN`."

    Design: Corner/errors/service_contract_terminate_with_open_claim_returns_409_claim_still_open
    """
    env = open_claim(
        setup_active_contract(_accepted_machine(), contract_overrides=dict(SILVER_TERM)),
        failure_summary="Nozzle block cracked during production",
    )

    response = api_client.terminate_service_contract(env["contract"]["id"], SERVICE_MANAGER)

    validate_error(response, ApiErrorId.ERR_CLAIM_STILL_OPEN.value, 409)
    assert read_contract(env["contract"]["id"])["status"] == "ACTIVE"
    assert read_claim(env["claim"]["id"])["status"] == "SUBMITTED"
    assert read_machine(env["machine"]["id"])["open_claim_count"] == 1


def test_service_work_cannot_be_booked_under_a_contract_that_was_never_activated():
    """A drafted contract funds nothing and covers nothing, so the visit is refused and
    the calendar stays empty.

    PRD: "The contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`)."

    Design: Corner/errors/pm_visit_create_on_draft_contract_returns_409_contract_not_active
    """
    env = draft_contract(_accepted_machine(), **dict(SILVER_TERM))
    engineer = seed_field_engineer()

    response = api_client.create_pm_visit(
        create_pm_visit_payload(
            env["contract"]["id"],
            field_engineer_id=engineer["id"],
            visit_type="PM",
            start_ts="2026-08-10T08:00:00.000Z",
            end_ts="2026-08-10T12:00:00.000Z",
        ),
        SERVICE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)
    contract = read_contract(env["contract"]["id"])
    assert contract["status"] == "DRAFT"
    assert contract["pm_visits_used"] == 0
    _rows, meta = validate_paginated(
        api_client.list_pm_visits(
            SERVICE_MANAGER, params={"service_contract_id": env["contract"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_service_contract_read_with_unknown_id_reports_the_contract_not_found_code():
    """The coverage read reports the contract's own miss code.

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

    Design: Corner/errors/service_contract_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_service_contract(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", SERVICE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_SERVICE_CONTRACT_NOT_FOUND.value, 404)
