"""The subscriber book: registration, suspension, churn and its cascade."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_subscriber,
    create_subscriber_payload,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    create_addon,
    create_case,
    create_subscriber,
    current_agreement_version,
    get_addon,
    get_case,
    get_subscriber,
    get_summary,
    get_term,
    next_msisdn,
    purchase_term,
    quote_term,
    set_clock,
    setup_activated_subscriber,
    setup_agreement_with_offered_plan,
    setup_awaiting_activation,
    setup_churned_subscriber,
    setup_subscriber_with_purchased_term,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_new_subscriber_lands_in_pending_port_with_zeroed_counters(api):
    """PRD §3.3: "A newly registered subscriber sits in `PENDING_PORT` with
    `allocation_status` `NONE` — nothing is yet promised to them out of the agreement — and with all cycle
    counters reset: `cycle_index` is 0, `cycles_rolled` is 0, `data_used_mb_cycle` is 0,
    `deprioritized_this_cycle` is `false`, and `cycle_deprioritization_days` is 0."

    Design: Corner/state_machines/create_subscriber_lands_in_pending_port
    """
    set_clock()
    resp = api.create_subscriber(
        create_subscriber_payload(), TEST_USERS["planner_headers"]
    )
    subscriber = validate_success(resp, expected_status=201)
    assert_subscriber(subscriber)
    assert subscriber["subscriber_status"] == "PENDING_PORT"
    assert subscriber["allocation_status"] == "NONE"
    assert subscriber["version"] == 1
    assert subscriber["cycle_index"] == 0
    assert subscriber["cycles_rolled"] == 0
    assert subscriber["data_used_mb_cycle"] == 0
    assert subscriber["deprioritized_this_cycle"] is False
    assert subscriber["cycle_deprioritization_days"] == 0

    listed = api.list_subscribers(
        TEST_USERS["planner_headers"], {"subscriber_status": "PENDING_PORT"}
    ).json()["data"]
    assert subscriber["id"] in [row["id"] for row in listed]


def test_new_subscriber_subscriber_status_is_not_client_supplied(api):
    """PRD §3.3: "Their outsourced support
    budget opens at 600 agent seconds — `DEFAULT_SUPPORT_BUDGET_SECONDS`, ten minutes of agent handling — recorded as `support_seconds_budget`,
    with `support_seconds_used` at 0 and `self_service_deflection_count` at 0".

    Design: Corner/entities/subscriber_activation_status_and_version_are_system_fields
    """
    set_clock()
    subscriber = create_subscriber()
    assert subscriber["subscriber_status"] == "PENDING_PORT"
    assert subscriber["support_seconds_budget"] == 600
    assert subscriber["support_seconds_used"] == 0
    assert subscriber["self_service_deflection_count"] == 0

    resp = api.create_subscriber(
        create_subscriber_payload(msisdn=next_msisdn(), subscriber_status="ACTIVE"),
        TEST_USERS["planner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_subscriber_read_with_unknown_id_returns_subscriber_not_found(api):
    """PRD §2.9: "a missing subscriber
    `ERR_SUBSCRIBER_NOT_FOUND`".

    Design: Corner/state_machines/create_subscriber_lands_in_pending_port
    """
    set_clock()
    resp = api.get_subscriber(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND)


def test_suspending_a_subscriber_keeps_its_capacity_committed(api):
    """PRD §3.3: "A `SupportAgent` suspends an `ACTIVE` subscriber into
    `SUSPENDED`, and the important economic consequence is that the agreement's `allocated_data_mb` is left
    unchanged: the prepaid term is still committed capacity the operator has sold".

    Design: Corner/errors/error_subscriber_not_active_on_consume_data
    """
    set_clock()
    setup = setup_activated_subscriber()
    api.suspend_subscriber(setup["subscriber"]["id"], TEST_USERS["agent_headers"])

    suspended = get_subscriber(setup["subscriber"]["id"])
    assert suspended["subscriber_status"] == "SUSPENDED"
    assert get_summary(setup["agreement"]["id"])["allocated_data_mb"] == 3000


def test_consume_data_for_a_suspended_subscriber_is_refused(api):
    """PRD §3.3: "While suspended, the subscriber cannot take new add-ons — the attempt is rejected with
    `ERR_SUBSCRIBER_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/error_subscriber_not_active_on_consume_data
    """
    set_clock()
    setup = setup_activated_subscriber()
    api.suspend_subscriber(setup["subscriber"]["id"], TEST_USERS["agent_headers"])

    resp = api.consume_data(
        setup["subscriber"]["id"], TEST_USERS["planner_headers"], {"data_mb": 100}
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIBER_NOT_ACTIVE)
    assert get_subscriber(setup["subscriber"]["id"])["data_used_mb_cycle"] == 0

    api.resume_subscriber(setup["subscriber"]["id"], TEST_USERS["agent_headers"])
    resumed = api.consume_data(
        setup["subscriber"]["id"], TEST_USERS["planner_headers"], {"data_mb": 100}
    ).json()["data"]
    assert resumed["data_used_mb_cycle"] == 100


def test_churn_closes_support_cases_and_voids_the_add_on(api):
    """PRD §3.3: "it voids every add-on for the subscriber whose `addon_status` is
    `REQUESTED` or `ACTIVE`, setting `addon_status` to `VOIDED` and recording the number actually deprovisioned in
    `deprovisioned_msisdn`; it closes every support case for the subscriber that is `OPEN`, `ASSIGNED` or
    `ESCALATED` as `CLOSED`".

    Design: Difficulty/transitive_cascade/subscriber_churn_shallow_cascade_closing_support_work
    """
    set_clock()
    setup = setup_churned_subscriber(
        addon=True,
        cases=(("PORT_STATUS", False), ("ROAMING_SETUP", True)),
        msisdn="13055550001",
    )
    assert setup["subscriber"]["subscriber_status"] == "CHURNED"

    open_case = get_case(setup["cases"][0]["id"])
    assigned_case = get_case(setup["cases"][1]["id"])
    assert open_case["case_status"] == "CLOSED"
    assert assigned_case["case_status"] == "CLOSED"
    assert assigned_case["handling_seconds"] == 180

    addon = get_addon(setup["addon"]["id"])
    assert addon["addon_status"] == "VOIDED"
    assert addon["deprovisioned_msisdn"] == "13055550001"
    assert addon["addon_price_cents"] == 0


def test_churn_releases_the_agreement_capacity(api):
    """PRD §3.3: "it recomputes the agreement's
    `allocated_data_mb`, `remaining_data_mb` and `congestion_index`."

    Design: Difficulty/transitive_cascade/subscriber_churn_shallow_cascade_closing_support_work
    """
    set_clock()
    setup = setup_churned_subscriber(addon=False, cases=())
    summary = get_summary(setup["agreement"]["id"])
    assert summary["allocated_data_mb"] == 0
    assert summary["remaining_data_mb"] == 16000


def test_churning_a_started_term_writes_breakage_into_earned_revenue(api):
    """PRD §3.3: "It writes the subscriber's prepaid term to `EXPIRED` and writes
    `breakage_days`, `breakage_cents_recognized`, `earned_revenue_cents` and `deferred_revenue_cents` through the
    early-churn recognition described in §3.6".

    Design: Difficulty/transitive_cascade/subscriber_churn_shallow_cascade_closing_support_work
    """
    set_clock()
    setup = setup_churned_subscriber(addon=False, cases=())
    term = get_term(setup["term"]["id"])
    assert term["term_status"] == "EXPIRED"
    assert term["breakage_days"] == 30
    assert term["earned_revenue_cents"] + term["deferred_revenue_cents"] == 1999


def test_subscriber_cancel_requires_ownership(api):
    """PRD §2.1: "A `Subscriber` acting on a row belonging to a
    different subscriber, or a `RetailPartner` acting on a block belonging to a different partner, is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/state_machines/subscriber_cancel_is_forbidden_for_another_subscriber
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    acting = create_subscriber()
    other = create_subscriber(msisdn="13055550041", full_name="Other Holder")

    resp = api.cancel_subscriber(
        other["id"],
        make_subscriber_headers(acting["id"]),
        {"expected_Subscriber_version": other["version"]},
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_subscriber(other["id"])["subscriber_status"] == "PENDING_PORT"
    assert get_subscriber(acting["id"])["subscriber_status"] == "PENDING_PORT"


def test_cancelling_a_subscriber_with_a_port_in_flight_is_refused(api):
    """PRD §3.3: "A subscriber with a port request still in flight cannot churn:
    while any activation for them holds a submitted port, both the subscriber cancel and a term cancel are
    rejected with `ERR_PORT_IN_FLIGHT` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/churn_requires_no_port_in_flight_on_a_different_pair
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    from test_helpers.fixtures import submit_port

    submit_port(activation_id, subscriber_id, "13055550001", last4="9001")

    current = get_subscriber(subscriber_id)
    resp = api.cancel_subscriber(
        subscriber_id,
        make_subscriber_headers(subscriber_id),
        {"expected_Subscriber_version": current["version"]},
    )
    validate_error(resp, ApiErrorId.ERR_PORT_IN_FLIGHT)
    assert get_subscriber(subscriber_id)["subscriber_status"] == "ACTIVE"


def test_cancelling_the_port_makes_the_churn_reachable(api):
    """PRD §3.7: "Finally
    a `Subscriber` may withdraw a submitted port: cancelling it sets `port_status` to `CANCELLED` and clears
    `held_data_mb`".

    Design: Difficulty/cross_entity_state_dependency/churn_requires_no_port_in_flight_on_a_different_pair
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    from test_helpers.fixtures import cancel_port, get_activation, submit_port

    submit_port(activation_id, subscriber_id, "13055550001", last4="9001")
    cancel_port(activation_id, subscriber_id)

    activation = get_activation(activation_id)
    assert activation["port_status"] == "CANCELLED"
    assert activation["held_data_mb"] == 0
    assert get_subscriber(subscriber_id)["allocation_status"] == "ALLOCATED"

    current = get_subscriber(subscriber_id)
    resp = api.cancel_subscriber(
        subscriber_id,
        make_subscriber_headers(subscriber_id),
        {"expected_Subscriber_version": current["version"]},
    )
    validate_success(resp)
    assert get_subscriber(subscriber_id)["subscriber_status"] == "CHURNED"
    assert get_term(setup["term"]["id"])["term_status"] == "EXPIRED"


def test_subscriber_cancel_while_port_in_flight_reports_the_port_error(api):
    """PRD §2.10: "(25) an in-flight port blocking churn, yielding `ERR_PORT_IN_FLIGHT`;".

    Design: Difficulty/priority_pair_validation_conflict/subscriber_cancel_while_port_in_flight_beats_budget_overrun
    """
    set_clock()
    from test_helpers.fixtures import get_activation, submit_port

    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    submit_port(activation_id, subscriber_id, "13055550001", last4="7712")

    assert get_activation(activation_id)["port_status"] == "SUBMITTED"
    resp = api.cancel_subscriber(subscriber_id, make_subscriber_headers(subscriber_id))
    validate_error(resp, ApiErrorId.ERR_PORT_IN_FLIGHT)
    assert resp.json()["data"]["error_id"] != "ERR_PORT_ALREADY_TERMINAL"


def test_a_held_port_never_double_counts_the_allotment(api):
    """PRD §3.7: "A successful submission
    sets `port_status` to `SUBMITTED`, sets the activation's `held_data_mb` to the plan's `data_allotment_mb`, and
    sets the parent subscriber's `allocation_status` to `HELD`".

    Design: Difficulty/compensating_invariant/port_rejection_releases_exactly_the_held_megabytes
    """
    set_clock()
    from test_helpers.fixtures import get_activation, submit_port

    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    submit_port(activation_id, subscriber_id, "13055550001", last4="7712")

    activation = get_activation(activation_id)
    assert activation["held_data_mb"] == 3000
    summary = get_summary(setup["agreement"]["id"])
    assert summary["allocated_data_mb"] == 3000
    assert summary["allocated_data_mb"] != 6000
    assert summary["allocated_data_mb"] + summary["remaining_data_mb"] == 16000
    assert get_subscriber(subscriber_id)["allocation_status"] == "HELD"


def test_port_rejection_releases_exactly_the_held_megabytes(api):
    """PRD §3.7: "either way `held_data_mb` is
    cleared and the agreement's balance and congestion index are recomputed."

    Design: Difficulty/compensating_invariant/port_rejection_releases_exactly_the_held_megabytes
    """
    set_clock()
    from test_helpers.fixtures import get_activation, reject_port, submit_port

    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    submit_port(activation_id, subscriber_id, "13055550001", last4="7712")

    reject_port(activation_id)
    activation = get_activation(activation_id)
    assert activation["held_data_mb"] == 0
    assert activation["port_status"] == "REJECTED"

    summary = get_summary(setup["agreement"]["id"])
    # PRD 3.7: on a live activation (COMPLETED) the subscriber "stays ACTIVE with
    # allocation_status ALLOCATED because the live term still holds its capacity" —
    # the denied port clears only the in-flight hold, never the term's own allotment.
    assert summary["allocated_data_mb"] == 3000
    assert summary["remaining_data_mb"] == 13000
    assert summary["allocated_data_mb"] + summary["remaining_data_mb"] == 16000
    assert get_subscriber(subscriber_id)["allocation_status"] == "ALLOCATED"
    assert get_term(setup["term"]["id"])["term_status"] == "ACTIVE"


def test_subscriber_list_filters_by_state_and_status(api):
    """PRD §3.3: "the collection can be filtered by `state_code`
    and `subscriber_status`."

    Design: Corner/entities/subscriber_activation_status_and_version_are_system_fields
    """
    set_clock()
    create_subscriber()
    create_subscriber(msisdn=next_msisdn(), state_code="NV")

    ca_only = api.list_subscribers(
        TEST_USERS["planner_headers"], {"state_code": "CA"}
    ).json()["data"]
    assert len(ca_only) == 1
    assert ca_only[0]["state_code"] == "CA"

    pending = api.list_subscribers(
        TEST_USERS["planner_headers"], {"subscriber_status": "PENDING_PORT"}
    ).json()["data"]
    assert len(pending) == 2