"""Second assertions for difficulty instances whose depth needs a companion test."""
from test_helpers import (
    ApiErrorId,
    validate_error_is_one_of,
    TEST_USERS,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    create_agreement,
    create_inventory,
    create_plan,
    create_subscriber,
    current_agreement_version,
    get_activation,
    get_inventory,
    get_summary,
    next_msisdn,
    offer_plan,
    provision_activation,
    purchase_term,
    quote_term,
    request_activation,
    set_clock,
    setup_active_agreement,
    setup_activated_subscriber,
    submit_port,
)


def test_the_marginal_reading_is_strictly_the_more_expensive_above_the_breakpoint(api):
    """PRD §3.1: "so the blended figure is lower than the marginal
    figure by the 500,000-megabyte band's rate saving and identical to it below the breakpoint."

    Design: Difficulty/dual_variant_calc/tier_marginal_breakpoint_vs_retroactive
    """
    set_clock()
    agreement = setup_active_agreement(
        host_network_name="Over Breakpoint Host", committed_data_mb=620000
    )
    resolved = api.resolve_purchase(
        agreement["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    summary = get_summary(agreement["id"])

    assert resolved["data_volume_cost_microcents"] > summary[
        "retroactive_volume_cost_microcents"
    ]
    assert resolved["data_volume_cost_microcents"] - summary[
        "retroactive_volume_cost_microcents"
    ] == 500000 * (1237 - 1139)
    assert resolved["data_volume_cost_microcents"] == 500000 * 1237 + 120000 * 1139
    assert summary["retroactive_volume_cost_microcents"] == 620000 * 1139


def test_the_retroactive_branch_reprises_every_megabyte(api):
    """PRD §3.1: "the first `TIER1_DATA_MB`, 500,000 megabytes of
    `committed_data_mb` are charged at `data_rate_microcents_per_mb`, and every megabyte above that breakpoint is
    charged at `tier2_rate`".

    Design: Difficulty/combinatorial_formula/wholesale_cost_nested_rounding_order_marginal_vs_retroactive
    """
    set_clock()
    agreement = setup_active_agreement(
        host_network_name="Over Breakpoint Host", committed_data_mb=620000
    )
    resolved = api.resolve_purchase(
        agreement["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    summary = get_summary(agreement["id"])

    assert resolved["marginal_tier_rate_microcents"] == 1139
    assert summary["retroactive_volume_cost_microcents"] == 620000 * 1139
    assert resolved["data_volume_cost_microcents"] == 500000 * 1237 + 120000 * 1139
    assert resolved["data_volume_cost_microcents"] != summary[
        "retroactive_volume_cost_microcents"
    ]


def test_a_two_subscriber_agreement_holds_six_thousand_megabytes(api):
    """PRD §3.1: "`allocated_data_mb`, the sum of the allotments promised to subscribers".

    Design: Difficulty/cross_entity_state_dependency/term_void_requires_sim_media_exhaustion
    """
    set_clock()
    agreement = setup_active_agreement()
    block = create_inventory(state_code="CA", unit_count=1)
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    holders = []
    for _ in range(2):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        holders.append((subscriber, request_activation(subscriber["id"], term["id"])))

    provision_activation(holders[0][1]["id"])
    assert get_inventory(block["id"])["reserved_count"] == 1
    assert get_inventory(block["id"])["inventory_status"] == "DEPLETED"

    resp = api.provision_activation(holders[1][1]["id"], TEST_USERS["planner_headers"])
    # PRD 3.8 names two refusals whose boundary is genuinely ambiguous once the
    # state's only block is reserved full: "a reservation attempted against a block
    # with no free unit" (ERR_SIM_INVENTORY_DEPLETED) and "a provisioning request that
    # cannot find any block in the subscriber's state with a free unit"
    # (ERR_NO_ACTIVATABLE_SIM_MEDIA). Both readings are faithful here.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_SIM_INVENTORY_DEPLETED, ApiErrorId.ERR_NO_ACTIVATABLE_SIM_MEDIA],
    )
    assert get_activation(holders[1][1]["id"])["activation_status"] == "REQUESTED"

    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 6000
    assert summary["congestion_index"] == 38
    assert summary["congestion_active"] is False


def test_media_exhaustion_does_not_void_the_second_term_while_one_unit_remains(api):
    """PRD §3.5: "a term still awaiting activation
    whose state has no reservable SIM media at all moves to `VOIDED` with `void_reason` `SPARE_INVENTORY`".

    Design: Difficulty/cross_entity_state_dependency/term_void_requires_sim_media_exhaustion
    """
    set_clock()
    agreement = setup_active_agreement()
    create_inventory(state_code="CA", unit_count=2)
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    holders = []
    for _ in range(2):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        holders.append((subscriber, request_activation(subscriber["id"], term["id"])))

    for subscriber, activation in holders:
        provision_activation(activation["id"])
    assert get_summary(agreement["id"])["allocated_data_mb"] == 6000

    for subscriber, activation in holders:
        assert get_activation(activation["id"])["activation_status"] == "PROVISIONED"
        term = api.get_term(
            activation["prepaid_term_id"], TEST_USERS["planner_headers"]
        ).json()["data"]
        assert term["term_status"] == "AWAITING_ACTIVATION"
        assert term["void_reason"] is None


def test_a_fifth_reservation_exactly_fills_the_block(api):
    """PRD §3.8: "once every unit has shipped, that is once `unit_count` minus `reserved_count` equals 0".

    Design: Difficulty/boundary_precision_check/sim_inventory_aggregate_capacity_boundary
    """
    set_clock()
    agreement = setup_active_agreement()
    block = create_inventory(state_code="CA", unit_count=5)
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    activations = []
    for _ in range(5):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        activations.append(request_activation(subscriber["id"], term["id"]))

    for activation in activations:
        provision_activation(activation["id"])

    block_state = get_inventory(block["id"])
    assert block_state["reserved_count"] == 5
    assert block_state["unit_count"] == 5
    assert block_state["inventory_status"] == "DEPLETED"


def test_state_scoping_isolates_the_nv_pool_from_the_ca_pool(api):
    """PRD §3.8: "A block is registered with the `state_code` it is scoped to, a
    `sim_media_type` of `PHYSICAL_SIM` or `ESIM_PROFILE`, and a `unit_count` of at least 1 unit or profile".

    Design: Difficulty/resource_temporal_overlap/client_pipeline_backlog_aggregate_capacity_on_sim_state
    """
    set_clock()
    agreement = setup_active_agreement()
    ca_block = create_inventory(state_code="CA", unit_count=2)
    nv_block = create_inventory(state_code="NV", unit_count=10)
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    ca_activations = []
    for _ in range(3):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(
            subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
        )
        purchase_term(term["id"], subscriber["id"])
        ca_activations.append(request_activation(subscriber["id"], term["id"]))

    provision_activation(ca_activations[0]["id"])
    provision_activation(ca_activations[1]["id"])
    assert get_inventory(ca_block["id"])["reserved_count"] == 2

    resp = api.provision_activation(
        ca_activations[2]["id"], TEST_USERS["planner_headers"]
    )
    # The CA block is reserved full; PRD 3.8's two media refusals are both faithful
    # readings of that state, so either is accepted here.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_SIM_INVENTORY_DEPLETED, ApiErrorId.ERR_NO_ACTIVATABLE_SIM_MEDIA],
    )
    assert get_inventory(nv_block["id"])["reserved_count"] == 0


def test_a_grace_subscriber_with_a_submitted_port_reports_the_port_error(api):
    """PRD §3.7: "when the
    activation has not yet gone live (`PROVISIONED`), rejection sends the subscriber to `GRACE` with
    `allocation_status` `NONE`".

    Design: Difficulty/priority_pair_validation_conflict/subscriber_cancel_while_port_in_flight_beats_budget_overrun
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    submit_port(activation_id, subscriber_id, "13055550001", last4="9901")

    assert get_activation(activation_id)["port_status"] == "SUBMITTED"

    resp = api.cancel_subscriber(subscriber_id, make_subscriber_headers(subscriber_id))
    error_data = validate_error(resp, ApiErrorId.ERR_PORT_IN_FLIGHT)
    assert error_data["error_id"] != "ERR_SUBSCRIBER_NOT_ACTIVE"

    # Cancelling the port is what makes the churn reachable.
    from test_helpers.fixtures import cancel_port

    cancel_port(activation_id, subscriber_id)
    current = api.get_subscriber(
        subscriber_id, TEST_USERS["planner_headers"]
    ).json()["data"]
    retried = api.cancel_subscriber(
        subscriber_id,
        make_subscriber_headers(subscriber_id),
        {"expected_Subscriber_version": current["version"]},
    )
    validate_success(retried)
    assert api.get_subscriber(
        subscriber_id, TEST_USERS["planner_headers"]
    ).json()["data"]["subscriber_status"] == "CHURNED"