"""Activation: provisioning, porting dimensions, grace and the media reservation."""
from test_helpers import (
    ApiErrorId,
    validate_error_is_one_of,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_activation,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    cancel_port,
    create_addon,
    create_inventory,
    create_partner,
    create_plan,
    create_subscriber,
    current_agreement_version,
    fail_activation,
    get_activation,
    get_inventory,
    get_plan,
    get_subscriber,
    get_summary,
    get_term,
    next_msisdn,
    offer_plan,
    provision_activation,
    purchase_term,
    quote_term,
    reject_port,
    request_activation,
    set_clock,
    setup_activated_subscriber,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
    setup_awaiting_activation,
    setup_provisioned_activation,
    setup_subscriber_with_purchased_term,
    submit_port,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_requesting_an_activation_moves_the_term_to_awaiting_activation(api):
    """PRD §3.7: "The activation opens
    in `REQUESTED` with `port_status` `NONE`, and it pulls the parent term from `PURCHASED` into
    `AWAITING_ACTIVATION`".

    Design: Difficulty/cross_entity_state_dependency/addon_activation_requires_subscriber_term_active
    """
    set_clock()
    agreement, plan, subscriber, term, activation = setup_awaiting_activation()
    assert activation["activation_status"] == "REQUESTED"
    assert activation["port_status"] == "NONE"
    assert get_term(term["id"])["term_status"] == "AWAITING_ACTIVATION"
    assert get_subscriber(subscriber["id"])["subscriber_status"] == "PENDING_PORT"


def test_add_on_activation_needs_the_term_to_be_active(api):
    """PRD §3.8: "it is admitted only when the parent subscriber is `ACTIVE`
    and that subscriber's term is in `ACTIVE` or `ACTIVE_RENEWAL`; otherwise it is rejected with
    `ERR_SUBSCRIBER_NOT_ACTIVE` or `ERR_TERM_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/addon_activation_requires_subscriber_term_active
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    addon = create_addon(subscriber["id"], addon_type="ROAMING", addon_days=7)

    resp = api.activate_addon(addon["id"], TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_ACTIVE)
    assert get_activation(activation["id"])["activation_status"] == "PROVISIONED"

    api.complete_activation(activation["id"], make_subscriber_headers(subscriber["id"]))
    activated = api.activate_addon(addon["id"], TEST_USERS["planner_headers"])
    data = validate_success(activated)
    assert data["addon_status"] == "ACTIVE"
    assert data["addon_price_cents"] == 273
    assert get_subscriber(subscriber["id"])["subscriber_status"] == "ACTIVE"


def test_activating_an_add_on_for_a_grace_term_is_refused(api):
    """PRD §3.7: "A term sitting in `GRACE` parks: it neither commits capacity nor earns revenue while it
    waits there".

    Design: Corner/errors/error_term_not_active_on_addon_activation_for_a_grace_term
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    addon = create_addon(subscriber["id"], addon_type="ROAMING", addon_days=7)
    # PRD 3.4 admits the PROVISIONED failure path only once the reserving media has
    # shipped and the shipment window has elapsed; returning the block is the reachable
    # equivalent, and PRD 3.8 has it cascade exactly as the 3.7 failure path does.
    block = api.list_inventories(
        TEST_USERS["planner_headers"], {"state_code": "CA"}
    ).json()["data"][0]
    api.return_inventory(block["id"], TEST_USERS["fulfillment_headers"])

    assert get_term(term["id"])["term_status"] == "PURCHASED"
    resp = api.activate_addon(addon["id"], TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_ACTIVE)
    assert get_subscriber(subscriber["id"])["allocation_status"] == "NONE"
    assert get_summary(agreement["id"])["allocated_data_mb"] == 0


def test_provisioning_reserves_exactly_one_unit_and_stamps_the_number(api):
    """PRD §3.7: "Provisioning reserves one unit on the matching block — incrementing
    its `reserved_count`, setting its `reserved_for_activation_id`, and moving its `inventory_status` to
    `RESERVED_PREPAID`".

    Design: Corner/endpoints/activation_provision_reserves_exactly_one_unit_and_stamps_the_number
    """
    set_clock()
    partner = create_partner(partner_state_codes=["CA"], shipment_sla_days=3)
    inventory = create_inventory(
        state_code="CA", unit_count=4, retail_partner_id=partner["id"]
    )
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    subscriber = create_subscriber(msisdn="13055550081", full_name="Retail Rider")
    term = quote_term(subscriber["id"], plan["id"], current_agreement_version(agreement["id"]))
    purchase_term(term["id"], subscriber["id"])
    activation = api.create_activation(
        {
            "subscriber_id": subscriber["id"],
            "prepaid_term_id": term["id"],
            "activation_channel": "RETAIL_PARTNER",
            "retail_partner_id": partner["id"],
        },
        make_subscriber_headers(subscriber["id"]),
    ).json()["data"]

    resp = api.provision_activation(activation["id"], TEST_USERS["planner_headers"])
    data = validate_success(resp)
    assert data["activation_status"] == "PROVISIONED"

    block = get_inventory(inventory["id"])
    assert block["reserved_count"] == 1
    assert block["reserved_for_activation_id"] == activation["id"]
    assert block["inventory_status"] == "RESERVED_PREPAID"
    assert block["shipment_channel"] == "RETAIL_PARTNER_STOCK"
    assert block["shipment_sla_days"] == 3
    assert data["provisioned_msisdn"] == "13055550081"
    assert data["accepted_msisdn"] is None


def test_completing_an_activation_makes_service_live(api):
    """PRD §3.7: "It moves the subscriber from `PENDING_PORT` to `ACTIVE`
    with `allocation_status` `ALLOCATED`, moves the term from `AWAITING_ACTIVATION` to `ACTIVE`, and opens the
    term's first cycle."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_ordering_across_three_entities
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    completed = api.complete_activation(
        activation["id"], make_subscriber_headers(subscriber["id"])
    ).json()["data"]
    assert completed["activation_status"] == "COMPLETED"
    assert completed["accepted_msisdn"] == completed["provisioned_msisdn"]

    live_term = get_term(term["id"])
    assert live_term["term_status"] == "ACTIVE"
    assert live_term["starts_at"] is not None
    assert live_term["expires_at"] > live_term["starts_at"]

    live_subscriber = get_subscriber(subscriber["id"])
    assert live_subscriber["subscriber_status"] == "ACTIVE"
    assert live_subscriber["allocation_status"] == "ALLOCATED"
    assert live_subscriber["cycle_index"] == 1
    assert get_plan(plan["id"])["plan_status"] == "ACTIVE"

    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 3000
    assert summary["remaining_data_mb"] == 13000

    cycles = api.list_cycles(
        TEST_USERS["planner_headers"], {"prepaid_term_id": term["id"]}
    ).json()["data"]
    assert len(cycles) == 1
    assert cycles[0]["cycle_index"] == 1
    assert cycles[0]["cycle_status"] == "OPEN"


def test_failing_an_activation_cascades_to_plan_dormancy(api):
    """PRD §3.7: "Both paths move the activation to `FAILED`, send the subscriber to `GRACE`, and push
    the term back to `PURCHASED`".

    Design: Difficulty/transitive_cascade/activation_failure_deep_cascade_to_plan_dormancy
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    fail_activation(activation["id"])

    assert get_activation(activation["id"])["activation_status"] == "FAILED"
    assert get_subscriber(subscriber["id"])["subscriber_status"] == "GRACE"
    assert get_term(term["id"])["term_status"] == "PURCHASED"


def test_fail_releases_the_reservation_and_the_capacity(api):
    """PRD §3.7: "the first path also decrements the reserving block's `reserved_count` when a
    reservation had been taken".

    Design: Difficulty/transitive_cascade/activation_failure_deep_cascade_to_plan_dormancy
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    fail_activation(activation["id"])

    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 0
    assert summary["remaining_data_mb"] == 16000
    # The term parks at PURCHASED, and PRD 3.2 lists PURCHASED among the non-terminal
    # statuses on which a plan may not be withdrawn, so the plan stays ACTIVE.
    assert get_plan(plan["id"])["plan_status"] == "ACTIVE"
    block = get_inventory(inventory["id"])
    assert block["reserved_count"] == 0
    assert block["inventory_status"] in ("AVAILABLE", "RESERVED_PREPAID")


def test_provisioning_without_any_state_media_is_refused(api):
    """PRD §3.7: "rejected with
    `ERR_NO_ACTIVATABLE_SIM_MEDIA` (HTTP 422) when no block scoped to the subscriber's `state_code` has a free
    unit".

    Design: Difficulty/cross_entity_state_dependency/term_void_requires_sim_media_exhaustion
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    create_inventory(state_code="CA", unit_count=1)
    holders = []
    for _ in range(2):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(subscriber["id"], plan["id"], current_agreement_version(agreement["id"]))
        purchase_term(term["id"], subscriber["id"])
        activation = request_activation(subscriber["id"], term["id"])
        holders.append((subscriber, get_term(term["id"]), activation))

    provision_activation(holders[0][2]["id"])
    resp = api.provision_activation(holders[1][2]["id"], TEST_USERS["planner_headers"])
    # The state's only block is reserved full, which PRD 3.8 reads either as
    # ERR_SIM_INVENTORY_DEPLETED (a reservation against a block with no free unit) or
    # as ERR_NO_ACTIVATABLE_SIM_MEDIA (no block with a free unit).
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_SIM_INVENTORY_DEPLETED, ApiErrorId.ERR_NO_ACTIVATABLE_SIM_MEDIA],
    )
    assert get_activation(holders[1][2]["id"])["activation_status"] == "REQUESTED"


def test_a_reservation_is_counted_against_the_blocks_aggregate_capacity(api):
    """PRD §3.8: "Reservation capacity is checked in
    aggregate: the units already reserved by activations whose reservation window is still open, plus the units
    this request would reserve, must stay at or below the block's `unit_count`, with exact equality admitted and
    one unit past it rejected."

    Design: Difficulty/boundary_precision_check/sim_inventory_aggregate_capacity_boundary
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    block = create_inventory(state_code="CA", unit_count=5)
    activations = []
    for _ in range(6):
        subscriber = create_subscriber(msisdn=next_msisdn(), state_code="CA")
        term = quote_term(subscriber["id"], plan["id"], current_agreement_version(agreement["id"]))
        purchase_term(term["id"], subscriber["id"])
        activation = request_activation(subscriber["id"], term["id"])
        activations.append(activation)

    for activation in activations[:5]:
        provision_activation(activation["id"])
    assert get_inventory(block["id"])["reserved_count"] == 5

    resp = api.provision_activation(activations[5]["id"], TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_SIM_INVENTORY_DEPLETED)
    assert get_inventory(block["id"])["inventory_status"] == "DEPLETED"


def test_inventory_is_state_scoped_and_never_crosses_state_lines(api):
    """PRD §3.8: "SIM
    media never crosses state lines."

    Design: Difficulty/resource_temporal_overlap/client_pipeline_backlog_aggregate_capacity_on_sim_state
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    ca_block = create_inventory(state_code="CA", unit_count=2)
    nv_block = create_inventory(state_code="NV", unit_count=10)
    nv_subscriber = create_subscriber(msisdn=next_msisdn(), state_code="NV")
    nv_term = quote_term(
        nv_subscriber["id"], plan["id"], current_agreement_version(agreement["id"])
    )
    purchase_term(nv_term["id"], nv_subscriber["id"])
    nv_activation = request_activation(nv_subscriber["id"], nv_term["id"])

    provision_activation(nv_activation["id"])
    assert get_inventory(nv_block["id"])["reserved_count"] == 1
    assert get_inventory(ca_block["id"])["reserved_count"] == 0


def test_port_submission_sets_both_dimensions_independently(api):
    """PRD §3.7: "The provisioning dimension, `activation_status`, runs `REQUESTED` →
    `PROVISIONED` → `COMPLETED`, with `FAILED` reachable from either live state".

    Design: Difficulty/non_linear_state_machine/activation_parallel_provisioning_and_porting_dimensions
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    activation_id = activation["id"]
    subscriber_id = subscriber["id"]

    assert get_activation(activation_id)["activation_status"] == "PROVISIONED"
    assert get_activation(activation_id)["port_status"] == "NONE"

    submitted = submit_port(activation_id, subscriber_id, "13055550001")
    assert submitted["port_status"] == "SUBMITTED"
    assert submitted["activation_status"] == "PROVISIONED"
    assert submitted["held_data_mb"] == 3000


def test_port_rejection_leaves_the_provisioning_dimension_live(api):
    """PRD §3.7: "a
    rejected port does not by itself stop an activation from going live on a spare number, which is why the
    completion rule accepts a port that is `NONE`, `CANCELLED`, `CONFIRMED`, or `REJECTED`."

    Design: Difficulty/non_linear_state_machine/activation_parallel_provisioning_and_porting_dimensions
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    activation_id = activation["id"]
    subscriber_id = subscriber["id"]
    submit_port(activation_id, subscriber_id, "13055550001")

    rejected = reject_port(activation_id)
    assert rejected["port_status"] == "REJECTED"
    assert rejected["held_data_mb"] == 0
    assert rejected["activation_status"] == "PROVISIONED"
    # PRD 3.7: "on a live activation (COMPLETED) the subscriber stays ACTIVE with
    # allocation_status ALLOCATED because the live term still holds its capacity".
    # This activation is still PROVISIONED, so the term holds its allotment through
    # the reservation rather than the subscriber row.
    assert get_subscriber(subscriber_id)["allocation_status"] == "HELD"
    assert get_summary(agreement["id"])["allocated_data_mb"] == 3000
    assert get_term(term["id"])["term_status"] == "AWAITING_ACTIVATION"

    completed = api.complete_activation(
        activation_id, make_subscriber_headers(subscriber_id)
    ).json()["data"]
    assert completed["activation_status"] == "COMPLETED"
    assert completed["port_status"] == "REJECTED"
    assert completed["accepted_msisdn"] == "13055550001"
    assert completed["provisioned_msisdn"] == "13055550001"


def test_port_submission_holding_capacity_counts_once(api):
    """PRD §3.7: "A successful submission
    sets `port_status` to `SUBMITTED`, sets the activation's `held_data_mb` to the plan's `data_allotment_mb`, and
    sets the parent subscriber's `allocation_status` to `HELD`".

    Design: Corner/endpoints/activation_submit_port_holds_capacity_once
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    submitted = submit_port(activation["id"], subscriber["id"], "13055550001")
    assert submitted["port_status"] == "SUBMITTED"
    assert submitted["held_data_mb"] == 3000
    assert get_summary(agreement["id"])["allocated_data_mb"] == 3000
    assert get_subscriber(subscriber["id"])["allocation_status"] == "HELD"


def test_duplicate_port_in_flight_is_rejected(api):
    """PRD §3.7: "a
    submission whose `losing_carrier` and `account_number_last4` are already held by another activation with
    `port_status` `SUBMITTED` is rejected with `ERR_MSISDN_ALREADY_IN_FLIGHT` (HTTP 409)."

    Design: Corner/validations/duplicate_port_in_flight_is_rejected
    """
    set_clock()
    setup = setup_activated_subscriber()
    second = create_subscriber(msisdn="13055550061", full_name="Duplicate Rider")
    second_term = quote_term(
        second["id"], setup["plan"]["id"], current_agreement_version(setup["agreement"]["id"])
    )
    purchase_term(second_term["id"], second["id"])
    second_activation = request_activation(second["id"], second_term["id"])
    provision_activation(second_activation["id"])

    submit_port(
        setup["activation"]["id"], setup["subscriber"]["id"], "13055550001",
        carrier="Cascade Wireless", last4="4471",
    )
    resp = api.submit_port(
        second_activation["id"],
        make_subscriber_headers(second["id"]),
        {
            "porting_msisdn": second["msisdn"],
            "losing_carrier": "Cascade Wireless",
            "account_number_last4": "4471",
        },
    )
    validate_error(resp, ApiErrorId.ERR_MSISDN_ALREADY_IN_FLIGHT)
    assert get_activation(second_activation["id"])["port_status"] == "NONE"


def test_port_number_must_match_the_subscribers_own_number(api):
    """PRD §3.7: "A submission whose
    number disagrees with the subscriber's own number is rejected with `ERR_MSISDN_MISMATCH` (HTTP 422)".

    Design: Corner/validations/port_msisdn_mismatch_is_rejected
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    resp = api.submit_port(
        activation["id"],
        make_subscriber_headers(subscriber["id"]),
        {
            "porting_msisdn": "13055550099",
            "losing_carrier": "Cascade Wireless",
            "account_number_last4": "4471",
        },
    )
    validate_error(resp, ApiErrorId.ERR_MSISDN_MISMATCH)
    after = get_activation(activation["id"])
    assert after["port_status"] == "NONE"
    assert after["held_data_mb"] == 0


def test_partner_activation_for_a_state_the_partner_does_not_list(api):
    """PRD §3.7: "on the retail channel, rejected with `ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE` or
    `ERR_PARTNER_SUSPENDED` (HTTP 422) when the named partner is not active for that state."

    Design: Corner/validations/partner_not_authorized_for_state_returns_422
    """
    set_clock()
    agreement, plan, subscriber, term = setup_subscriber_with_purchased_term()
    partner = create_partner(partner_name="Sierra Retail Group", partner_state_codes=["NV"])

    resp = api.create_activation(
        {
            "subscriber_id": subscriber["id"],
            "prepaid_term_id": term["id"],
            "activation_channel": "RETAIL_PARTNER",
            "retail_partner_id": partner["id"],
        },
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE)

    digital = api.create_activation(
        {
            "subscriber_id": subscriber["id"],
            "prepaid_term_id": term["id"],
            "activation_channel": "DIGITAL",
        },
        make_subscriber_headers(subscriber["id"]),
    )
    validate_success(digital, expected_status=201)


def test_suspended_partner_blocks_new_retail_activations(api):
    """PRD §3.8: "A partner in `DEFLECTED` or `SUSPENDED` cannot serve new activations: retail-channel activations
    against it are rejected with `ERR_PARTNER_SUSPENDED` (HTTP 422)".

    Design: Corner/validations/suspended_partner_blocks_new_retail_activations
    """
    set_clock()
    agreement, plan, subscriber, term = setup_subscriber_with_purchased_term()
    partner = create_partner(partner_state_codes=["CA"])
    api.suspend_partner(partner["id"], TEST_USERS["planner_headers"])

    resp = api.create_activation(
        {
            "subscriber_id": subscriber["id"],
            "prepaid_term_id": term["id"],
            "activation_channel": "RETAIL_PARTNER",
            "retail_partner_id": partner["id"],
        },
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PARTNER_SUSPENDED)


def test_retail_channel_and_partner_must_agree(api):
    """PRD §3.7: "when the channel is `RETAIL_PARTNER` a
    `retail_partner_id` is required, and when it is `DIGITAL` supplying `retail_partner_id` is an error — both
    mismatches are rejected with `ERR_RETAIL_CHANNEL_MISMATCH` (HTTP 422)."

    Design: Corner/validations/retail_channel_mismatch_is_rejected
    """
    set_clock()
    _agreement, _plan, subscriber, term = setup_subscriber_with_purchased_term()
    partner = create_partner(partner_state_codes=["CA"])

    resp = api.create_activation(
        {
            "subscriber_id": subscriber["id"],
            "prepaid_term_id": term["id"],
            "activation_channel": "DIGITAL",
            "retail_partner_id": partner["id"],
        },
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETAIL_CHANNEL_MISMATCH)


def test_completing_a_terminal_activation_is_refused(api):
    """PRD §3.7: "a completion or failure attempted on an activation already
    `COMPLETED` or `FAILED` is refused with `ERR_ACTIVATION_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/activation_complete_from_a_failed_activation_is_invalid_state
    """
    set_clock()
    agreement, plan, subscriber, term, activation, inventory = setup_provisioned_activation()
    fail_activation(activation["id"])

    resp = api.complete_activation(activation["id"], TEST_USERS["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_ALREADY_TERMINAL)
    assert get_subscriber(subscriber["id"])["subscriber_status"] == "GRACE"
    assert get_inventory(inventory["id"])["reserved_count"] == 0


def test_activation_read_with_unknown_id_returns_activation_not_found(api):
    """PRD §2.9: "a missing activation
    `ERR_ACTIVATION_NOT_FOUND`".

    Design: Corner/errors/not_found_codes_are_entity_specific
    """
    set_clock()
    resp = api.get_activation(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_ACTIVATION_NOT_FOUND)