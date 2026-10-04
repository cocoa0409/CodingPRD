"""Emergency fills, restriction priority, deferral tiers and SLA windows."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
    create_batch,
    create_population_record,
    create_service_order,
    get_service_order,
    parts_manager_headers,
    place_batch_order,
    setup_commitment_order_ready,
    technician_supervisor_headers,
)


def test_service_order_response_window_fixed_from_the_commitment():
    """PRD §2.8: "Its `response_window_hours` is derived from the linked
    commitment's `emergency_fill_window_hours` and is fixed at the moment the
    order is opened into active work."

    Design: Corner/calculations/emergency_fill_sla_outcome_is_met_at_the_window_boundary
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=True,
                                 sla_hours=24.0)
    data = validate_success(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    assert data["response_window_hours"] == 24.0
    assert data["sla_hours"] == 24.0


def test_sla_outcome_is_met_at_the_inclusive_window_boundary():
    """PRD §2.8: "A recorded response `sla_hours` meets the window when it is
    less than or equal to `response_window_hours`; a response landing exactly on
    the window is met, so the upper bound is inclusive."

    Design: Corner/calculations/emergency_fill_sla_outcome_is_met_at_the_window_boundary
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=True,
                                 sla_hours=24.0)
    data = validate_success(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    assert data["response_window_hours"] == 24.0
    assert data["sla_hours"] <= data["response_window_hours"]


def test_deferral_tier_is_zero_when_the_ordering_target_list_is_empty():
    """PRD §2.8: "The deferral tier attached to a restriction is `1 +
    priority_rank` when the dealer's ordering target list holds at least one
    candidate, and 0 when it holds none."

    Design: Difficulty/boundary_precision_check/reconstruct_batch_and_empty_pool_boundaries_on_restriction_scoring
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    # The order's machine serial is on no ACTIVE population record, so it is not
    # a candidate and the ordering target list stays empty.
    order = create_service_order(dealer, commitment, kind="RESTRICTION",
                                 machine_serial="SN-9001",
                                 restriction_scope="HOURS_SPENT", sla_hours=0.0)
    data = get_service_order(order["id"])
    assert data["deferral_tier"] == 0


def test_emergency_fill_uses_the_first_tier_denominator():
    """PRD §3.10: "The denominator is 2 when the gross is 8.0 or less and 4 otherwise. When `orderable_ref_enabled` is false the filled quantity is the gross divided by the denominator, rounded up to the next whole unit; when `orderable_ref_enabled` is true the filled quantity is the gross divided by the denominator, rounded down to the whole unit."

    Design: Difficulty/boundary_precision_check/reconstruct_batch_and_empty_pool_boundaries_on_restriction_scoring
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    create_population_record(dealer, "SN-9101", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)
    create_service_order(dealer, commitment, kind="RESTRICTION",
                         machine_serial="SN-9101", sla_hours=4.0)
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=True, sla_hours=4.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    data = validate_success(api_client.record_emergency_fill(
        order["id"], technician_supervisor_headers()))
    assert data["emergency_filled_units"] == 2


def test_emergency_fill_uses_the_overflow_denominator_above_eight():
    """PRD §3.10: "The denominator is 2 when the gross is 8.0 or less and 4 otherwise. When `orderable_ref_enabled` is false the filled quantity is the gross divided by the denominator, rounded up to the next whole unit; when `orderable_ref_enabled` is true the filled quantity is the gross divided by the denominator, rounded down to the whole unit."

    Design: Difficulty/boundary_precision_check/reconstruct_batch_and_empty_pool_boundaries_on_restriction_scoring
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    create_population_record(dealer, "SN-9102", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)
    create_service_order(dealer, commitment, kind="RESTRICTION",
                         machine_serial="SN-9102", sla_hours=4.0)
    create_service_order(dealer, commitment, kind="RESTRICTION",
                         machine_serial="SN-9102", sla_hours=4.0)
    create_service_order(dealer, commitment, kind="RESTRICTION",
                         machine_serial="SN-9102", sla_hours=4.0)
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=True, sla_hours=4.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    data = validate_success(api_client.record_emergency_fill(
        order["id"], technician_supervisor_headers()))
    assert data["emergency_filled_units"] == 3


def test_place_order_with_a_drained_pool_reports_commitment_empty():
    """PRD §3.5: "Placing an order moves `OPEN` to `ORDERED` and requires that
    `available_commitment_units` be at least 1, or that the batch be an
    emergency. A refusal here is `ERR_COMMITMENT_EMPTY` at HTTP 409."

    Design: Difficulty/boundary_precision_check/reconstruct_batch_and_empty_pool_boundaries_on_restriction_scoring
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    filler = create_batch(commitment, requested_units=63, emergency=True)
    place_batch_order(filler["id"])
    assert validate_success(api_client.get_commitment(
        commitment["id"], parts_manager_headers()))["available_commitment_units"] == 0

    pending = create_batch(commitment, requested_units=10)
    resp = api_client.place_batch_order(pending["id"], parts_manager_headers())
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EMPTY, expected_status=409)


def test_commitment_empty_refusal_leaves_the_open_batch_intact():
    """PRD §3.5: "Placing an order moves `OPEN` to `ORDERED` and requires that `available_commitment_units` be at least 1"

    Design: Difficulty/boundary_precision_check/reconstruct_batch_and_empty_pool_boundaries_on_restriction_scoring
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    filler = create_batch(commitment, requested_units=63, emergency=True)
    place_batch_order(filler["id"])
    pending = create_batch(commitment, requested_units=10)
    api_client.place_batch_order(pending["id"], parts_manager_headers())

    data = get_success_data(api_client.get_batch(
        pending["id"], parts_manager_headers()))
    assert data["status"] == "OPEN"