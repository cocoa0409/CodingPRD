"""Performance reviews, market share, agreement representation and stages."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
    create_agreement,
    create_agreement_for_family,
    create_batch,
    create_certification_record,
    create_dealer,
    create_observation,
    create_population_record,
    create_review,
    create_service_order,
    get_agreement,
    get_dealer,
    get_review,
    network_manager_headers,
    parts_manager_headers,
    place_batch_order,
    register_technician,
    register_technicians,
    reviewer_headers,
    set_clock,
    setup_active_agreement_order_ready_commitment,
    setup_commitment_order_ready,
    submit_agreement,
    technician_supervisor_headers,
)


def test_performance_ratio_saturates_at_one_hundred():
    """PRD §3.6: "The ratio saturates: once the reported share reaches 100, the
    ratio is capped at 100.0, so a plan of 20 percent with a reported share of
    120 yields a ratio of 100.0 rather than 600.0."
    PRD §3.6: "`actual_market_share_pct` is 100 multiplied by
    `actual_territory_machine_units` and divided by `territory_market_machine_units`,
    stored exactly as reported to four decimal places half-up."

    Design: Difficulty/dual_variant_calc/performance_ratio_reported_basis_vs_uncapped_plan_basis
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    review = create_review(
        dealer, agreement,
        actual_territory_machine_units=120, territory_market_machine_units=100,
        sampled_service_orders=10, met_sla_service_orders=10,
    )
    # PRD §3.6: evaluation is reached from `RESULTS_RECORDED` or
    # `CIRCUMSTANCE_PENDING`, so the results must be recorded first.
    get_success_data(api_client.record_review_results(review["id"], reviewer_headers()))
    data = validate_success(api_client.evaluate_review(
        review["id"], reviewer_headers()))

    assert data["actual_market_share_pct"] == 120.0000
    assert data["performance_ratio_pct"] == 100.0
    assert data["performance_ratio_pct"] != 600.0


def test_performance_ratio_reported_basis_loyalty_score():
    """PRD §3.6: "`loyalty_score` is `performance_ratio_pct` plus the
    lifetime-value bonus plus a customer-satisfaction bonus of 3.0 when
    `performance_ratio_pct` is at least 100.0 and 0.0 otherwise, recorded to two
    decimal places half-up."

    Design: Difficulty/dual_variant_calc/performance_ratio_reported_basis_vs_uncapped_plan_basis
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    review = create_review(
        dealer, agreement,
        actual_territory_machine_units=120, territory_market_machine_units=100,
        sampled_service_orders=10, met_sla_service_orders=10,
    )
    # PRD §3.6: "Evaluation moves `RESULTS_RECORDED` or `CIRCUMSTANCE_PENDING`
    # to `EVALUATED`", so recording the results is the required step first.
    get_success_data(api_client.record_review_results(review["id"], reviewer_headers()))
    data = validate_success(api_client.evaluate_review(
        review["id"], reviewer_headers()))

    # PRD §3.6: the lifetime-value bonus is zero when no rebuild claim exists for
    # the machine, so loyalty_score is the ratio plus the 3.0 satisfaction bonus.
    assert data["loyalty_score"] == 103.0


def test_review_carries_no_version_field():
    """PRD §2.5: "`PerformanceReview` is the one resource declared without the
    common field set, and this must be handled explicitly. A performance review
    carries only `id` and `created_at`. It has no `updated_at` and no `version`
    field at all."

    Design: Corner/entities/performance_review_is_immutable_and_carries_no_version_field
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    resp = api_client.create_review({
        "dealer_id": dealer["id"],
        "agreement_id": agreement["id"],
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "actual_territory_machine_units": 6,
        "territory_market_machine_units": 30,
        "sampled_service_orders": 10,
        "met_sla_service_orders": 9,
        "expected_dealeragreement_version": get_agreement(
            agreement["id"])["version"],
    }, reviewer_headers())
    data = validate_success(resp, expected_status=201)

    assert data.get("id")
    assert data.get("created_at")
    assert "version" not in data


def test_review_is_created_draft_with_share_recorded():
    """PRD §3.6: "A `DealerPerformanceReviewer` opens a `PerformanceReview` in
    `DRAFT` for a `dealer_id` and an `agreement_id`, declaring an inclusive
    `period_start`, an exclusive `period_end` that must be strictly after the
    start, the dealer's own `actual_territory_machine_units`, the
    `territory_market_machine_units` placed by all sellers in the territory
    during the period, a `sampled_service_orders` count, a `met_sla_service_orders`
    count that must not exceed the sampled count, and an optional
    `circumstance_note` explaining a missed plan." PRD §3.6:
    "`actual_market_share_pct` is 100 multiplied by `actual_territory_machine_units`
    and divided by `territory_market_machine_units`, stored exactly as reported to
    four decimal places half-up."

    Design: Corner/entities/performance_review_is_immutable_and_carries_no_version_field
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    review = create_review(
        dealer, agreement,
        actual_territory_machine_units=6, territory_market_machine_units=30,
        sampled_service_orders=10, met_sla_service_orders=9,
    )
    assert review["status"] == "DRAFT"
    assert review["actual_market_share_pct"] == 20.0000


def test_observed_share_uses_the_kind_weight_table():
    """PRD §3.6: "The `kind` is a weight and not a label: an observation of kind
    `MACHINE` weighs 1.0 and one of kind `LIGHT` weighs 0.5 when the share is
    aggregated. `observed_share_pct` is 100 multiplied by `observed_machine_units`
    and divided by `territory_machine_units`, recomputed from the summed
    observation values of the dealer and family, to four decimal places half-up."

    Design: Corner/calculations/observed_share_pct_uses_the_kind_weight_table
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    machine = create_observation(dealer, observed_machine_units=5,
                                 territory_machine_units=10, kind="MACHINE",
                                 recorded_at="2026-03-01T00:00:00Z")
    light = create_observation(dealer, observed_machine_units=0,
                               territory_machine_units=1, kind="LIGHT",
                               recorded_at="2026-03-02T00:00:00Z")

    machine_data = get_success_data(api_client.get_observation(
        machine["id"], reviewer_headers()))
    assert machine_data["observed_share_pct"] == 47.6190
    assert machine_data["observed_share_pct"] != 45.4545

    light_data = get_success_data(api_client.get_observation(
        light["id"], reviewer_headers()))
    # PRD §3.6 sums the reading over the dealer and family's rows, so the later
    # LIGHT row serves the same aggregate the first row does.
    assert light_data["observed_share_pct"] == 47.6190


def test_observation_list_returns_both_weighted_rows():
    """PRD §3.6: "Rider observations are recorded by a `DealerPerformanceReviewer` as `MarketShareObservation` rows"

    Design: Corner/calculations/observed_share_pct_uses_the_kind_weight_table
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_observation(dealer, observed_machine_units=5, territory_machine_units=10,
                       kind="MACHINE", recorded_at="2026-03-01T00:00:00Z")
    create_observation(dealer, observed_machine_units=0, territory_machine_units=1,
                       kind="LIGHT", recorded_at="2026-03-02T00:00:00Z")

    rows = get_success_data(api_client.list_observations(
        reviewer_headers(), params={"dealer_id": dealer["id"]}))
    assert len(rows) == 2


def test_exclusive_adjacent_intervals_are_accepted_and_overlap_refused():
    """PRD §3.2: "First, an `EXCLUSIVE` submission is refused with
    `ERR_TERRITORY_OVERLAP` at HTTP 409 when another agreement with the same
    `territory_code` and the same `product_family` and an `exclusivity_level` of
    `EXCLUSIVE` is already in `SUBMITTED` or `ACTIVE` over an interval that
    overlaps the submission's interval."
    PRD §3.2: "an exclusive `end_at` that must be strictly after `start_at`"

    Design: Difficulty/resource_temporal_overlap/exclusive_territory_interval_overlap_half_open_back_to_back
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-220")
    first = create_agreement(dealer, start_at="2026-09-01T00:00:00Z",
                             end_at="2027-09-01T00:00:00Z")
    adjacent = create_agreement(dealer, start_at="2027-09-01T00:00:00Z",
                                end_at="2028-09-01T00:00:00Z")
    register_technicians(dealer, ("T-01", "T-02"))

    assert validate_success(api_client.submit_agreement(
        first["id"], network_manager_headers()))["status"] == "SUBMITTED"
    assert validate_success(api_client.submit_agreement(
        adjacent["id"], network_manager_headers()))["status"] == "SUBMITTED"


def test_exclusive_overlapping_interval_is_refused():
    """PRD §3.2: "First, an `EXCLUSIVE` submission is refused with
    `ERR_TERRITORY_OVERLAP` at HTTP 409 when another agreement with the same
    `territory_code` and the same `product_family` and an `exclusivity_level` of
    `EXCLUSIVE` is already in `SUBMITTED` or `ACTIVE` over an interval that
    overlaps the submission's interval."

    Design: Difficulty/resource_temporal_overlap/exclusive_territory_interval_overlap_half_open_back_to_back
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-220")
    first = create_agreement(dealer, start_at="2026-09-01T00:00:00Z",
                             end_at="2027-09-01T00:00:00Z")
    overlapping = create_agreement(dealer, start_at="2026-12-31T00:00:00Z",
                                   end_at="2028-01-01T00:00:00Z")
    register_technicians(dealer, ("T-01", "T-02"))
    get_success_data(api_client.submit_agreement(first["id"], network_manager_headers()))

    resp = api_client.submit_agreement(overlapping["id"], network_manager_headers())
    validate_error(resp, ApiErrorId.ERR_TERRITORY_OVERLAP, expected_status=409)
    assert get_agreement(overlapping["id"])["status"] == "DRAFT"


def test_credential_recurrence_inside_the_twelve_month_window_keeps_active():
    """PRD §3.3: "A credential's `recurrence_within_period` is true when another
    certification record that is not `REVOKED` exists for the same dealer, the
    same product family and the same technician name with a `certified_at` inside
    the interval running from this record's `certified_at` up to but not
    including twelve months after it. Such a recurrence keeps the credential
    `ACTIVE` past its nominal expiry while it is in force."

    Design: Difficulty/resource_temporal_overlap/certified_credential_recurrence_buffer_semantics
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-220")
    edge = create_certification_record(dealer, "T-09", "2024-09-01T00:00:00Z")
    create_certification_record(dealer, "T-09", "2025-08-31T23:59:59Z")

    data = get_success_data(api_client.get_certification(
        edge["id"], parts_manager_headers()))
    assert data["recurrence_within_period"] is True
    assert data["status"] == "ACTIVE"


def test_credential_recurrence_outside_the_window_leaves_it_expired():
    """PRD §3.3: "A credential's `recurrence_within_period` is true when another certification record that is not `REVOKED` exists for the same dealer, the same product family and the same technician name with a `certified_at` inside the interval running from this record's `certified_at` up to but not including twelve months after it."

    Design: Difficulty/resource_temporal_overlap/certified_credential_recurrence_buffer_semantics
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-220")
    late = create_certification_record(dealer, "T-08", "2024-09-01T00:00:00Z")
    create_certification_record(dealer, "T-08", "2025-09-01T00:00:00Z")

    data = get_success_data(api_client.get_certification(
        late["id"], parts_manager_headers()))
    assert data["recurrence_within_period"] is False
    assert data["status"] == "EXPIRED"


def test_stale_dealer_version_on_agreement_create_is_refused():
    """PRD §2.5.1: "The supplied value must match the target dealer's current
    `version`. When another writer has advanced that dealer's version since the
    client last read it, the create is refused with `ERR_STALE_VERSION` at HTTP
    412."

    Design: Corner/errors/stale_dealer_version_on_agreement_create_returns_stale_version
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    stale_version = dealer["version"]

    # Advance the dealer's version by creating one agreement.
    create_agreement(dealer, product_family="EARTHMOVING",
                     performance_plan_share_pct=15)

    resp = api_client.create_agreement({
        "dealer_id": dealer["id"], "product_family": "EXCAVATION",
        "territory_code": "T-410", "exclusivity_level": "SHARED",
        "start_at": "2026-09-01T00:00:00Z", "end_at": "2027-09-01T00:00:00Z",
        "performance_plan_share_pct": 20, "expected_dealer_version": stale_version,
    }, network_manager_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_fresh_dealer_version_on_agreement_create_succeeds():
    """PRD §2.5.1: "The supplied value must match the target dealer's current
    `version`." PRD §2.5.1: "Creation of the agreement also increments `Dealer.version` by 1"

    Design: Corner/errors/stale_dealer_version_on_agreement_create_returns_stale_version
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_agreement(dealer, product_family="EARTHMOVING", performance_plan_share_pct=15)
    current = get_dealer(dealer["id"])["version"]

    agreement = create_agreement(dealer, product_family="EXCAVATION",
                                 performance_plan_share_pct=20)
    assert agreement["product_family"] == "EXCAVATION"
    assert get_dealer(dealer["id"])["version"] == current + 1


def test_review_create_with_a_stale_agreement_version_is_refused():
    """PRD §2.5.1: "Creating a `PerformanceReview` requires `expected_dealeragreement_version` alongside `dealer_id`, `agreement_id`, `period_start`, `period_end`, `actual_territory_machine_units`, `territory_market_machine_units`, `sampled_service_orders`, `met_sla_service_orders` and the optional `circumstance_note`. The value must match the target agreement's current `version`. When another writer has advanced the agreement's version — for instance by having just opened a review for the same period — the create is refused with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/review_create_with_a_stale_agreement_version_returns_stale_version
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    stale_version = get_agreement(agreement["id"])["version"]
    create_review(dealer, agreement, period_start="2026-01-01T00:00:00Z",
                  period_end="2026-07-01T00:00:00Z",
                  expected_agreement_version=stale_version)

    resp = api_client.create_review({
        "dealer_id": dealer["id"], "agreement_id": agreement["id"],
        "period_start": "2026-07-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z",
        "actual_territory_machine_units": 7, "territory_market_machine_units": 30,
        "sampled_service_orders": 10, "met_sla_service_orders": 10,
        "expected_dealeragreement_version": stale_version,
    }, reviewer_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_stale_review_create_is_not_persisted():
    """PRD §2.5.1: "When another writer has advanced the agreement's version —
    for instance by having just opened a review for the same period — the create
    is refused with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/review_create_with_a_stale_agreement_version_returns_stale_version
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    stale_version = get_agreement(agreement["id"])["version"]
    create_review(dealer, agreement, period_start="2026-01-01T00:00:00Z",
                  period_end="2026-07-01T00:00:00Z",
                  expected_agreement_version=stale_version)
    api_client.create_review({
        "dealer_id": dealer["id"], "agreement_id": agreement["id"],
        "period_start": "2026-07-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z",
        "actual_territory_machine_units": 7, "territory_market_machine_units": 30,
        "sampled_service_orders": 10, "met_sla_service_orders": 10,
        "expected_dealeragreement_version": stale_version,
    }, reviewer_headers())

    rows = get_success_data(api_client.list_agreement_reviews(
        agreement["id"], reviewer_headers()))
    assert len(rows) == 1


def test_agreement_compliance_fields_advance_with_credentials():
    """PRD §3.2: "`tooling_compliance_status` is `NOT_SUBMITTED` while the agreement holds no certification record at all, `PARTIAL` while `certified_technician_count` is below the product family minimum of 2, and `COMPLIANT` once it reaches 2"
    PRD §3.2: "`certified_technician_count` counts the distinct
    `technician_name` values among certification records with `status` `ACTIVE`
    that match this dealer and this product family."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_advances_on_every_mutating_call
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    agreement = create_agreement(dealer, product_family="EXCAVATION")

    register_technician(dealer, "T-01")
    after_first = get_agreement(agreement["id"])
    assert after_first["certified_technician_count"] == 1
    assert after_first["tooling_compliance_status"] == "PARTIAL"

    register_technician(dealer, "T-02")
    after_second = get_agreement(agreement["id"])
    assert after_second["certified_technician_count"] == 2
    assert after_second["tooling_compliance_status"] == "COMPLIANT"


def test_dealer_certified_family_count_advances_with_credentials():
    """PRD §3.1: "`certified_family_count` counts the distinct product family
    values for which the dealer holds a certification record whose `status` is
    `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_advances_on_every_mutating_call
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    agreement = create_agreement(dealer, product_family="EXCAVATION")
    register_technician(dealer, "T-01")
    register_technician(dealer, "T-02")

    assert get_dealer(dealer["id"])["certified_family_count"] == 1
    assert get_agreement(agreement["id"])["version"] > agreement["version"]


def test_performance_deficient_agreement_drives_the_commitment():
    """PRD §3.6: "A `DealerPerformanceReviewer` moves `ACTIVE` to `PERFORMANCE_DEFICIENT` only once every review of the agreement is `EVALUATED`" PRD §3.6: "That move sets the agreement's commitments to `PERFORMANCE_DEFICIENT` for every commitment not already in a terminal condition"

    Design: Difficulty/non_linear_state_machine/parts_commitment_cycle_over_order_ready_core_pending_performance_deficient
    """
    dealer, agreement, commitment = setup_active_agreement_order_ready_commitment()
    review = create_review(dealer, agreement,
                           actual_territory_machine_units=19,
                           territory_market_machine_units=100,
                           sampled_service_orders=10, met_sla_service_orders=9)
    get_success_data(api_client.record_review_results(review["id"], reviewer_headers()))
    validate_success(api_client.evaluate_review(
        review["id"], reviewer_headers()))

    resp = api_client.mark_agreement_underperforming(
        agreement["id"], reviewer_headers())
    validate_success(resp)
    assert get_commitment_copy(commitment["id"])["status"] == "PERFORMANCE_DEFICIENT"


def test_commitment_returns_to_order_ready_without_passing_complete():
    """PRD §3.4: "The commitment can be returned to `ORDER_READY` by a
    `PartsManager` once `available_commitment_units` is at least the final
    variant minus `committed_units`; that reinstatement reactivates the rule and
    clears `backorder_opened_at`."

    Design: Difficulty/non_linear_state_machine/parts_commitment_cycle_over_order_ready_core_pending_performance_deficient
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(
        _dealer, commitment, kind="EMERGENCY_FILL",
        orderable_ref_enabled=False, sla_hours=6.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    get_success_data(api_client.escalate_service_order(
        order["id"], technician_supervisor_headers()))
    assert get_commitment_copy(commitment["id"])["status"] == "PERFORMANCE_DEFICIENT"

    validate_success(api_client.reinstate_commitment(
        commitment["id"], parts_manager_headers()))
    assert get_commitment_copy(commitment["id"])["status"] == "ORDER_READY"


def test_commitment_reinstate_clears_the_backorder_stamp():
    """PRD §3.4: "The commitment can be returned to `ORDER_READY` by a `PartsManager` once `available_commitment_units` is at least the final variant minus `committed_units`; that reinstatement reactivates the rule and clears `backorder_opened_at`."

    Design: Difficulty/non_linear_state_machine/parts_commitment_cycle_over_order_ready_core_pending_performance_deficient
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(
        _dealer, commitment, kind="EMERGENCY_FILL",
        orderable_ref_enabled=False, sla_hours=6.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    get_success_data(api_client.escalate_service_order(
        order["id"], technician_supervisor_headers()))
    validate_success(api_client.reinstate_commitment(
        commitment["id"], parts_manager_headers()))

    assert get_commitment_copy(commitment["id"])["backorder_opened_at"] is None


def test_commitment_enters_core_pending_from_order_ready():
    """PRD §3.5: "Moving `ORDER_READY` to `CORE_PENDING` requires `credit_balance_cents` to be exactly 0 — a non-zero balance is refused with `ERR_CREDIT_ALREADY_APPLIED` at HTTP 409 — and requires that no batch of the commitment be `OPEN` or `ORDERED`"

    Design: Difficulty/non_linear_state_machine/parts_commitment_cycle_over_order_ready_core_pending_performance_deficient
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    assert get_commitment_copy(commitment["id"])["credit_balance_cents"] == 0

    data = validate_success(api_client.suspend_commitment_core_credit(
        commitment["id"], parts_manager_headers()))
    assert data["status"] == "CORE_PENDING"


def test_reinstating_a_suspended_commitment_requires_a_live_agreement():
    """PRD §3.4: "Reinstating out of `SUSPENDED` instead requires the owning
    agreement to be `ACTIVE` and reactivates the rule without touching the
    stamp."

    Design: Difficulty/non_linear_state_machine/parts_commitment_cycle_over_order_ready_core_pending_performance_deficient
    """
    # PRD §3.4: "Reinstating out of `SUSPENDED` instead requires the owning
    # agreement to be `ACTIVE`", so the fixture must carry it to ACTIVe.
    _dealer, _agreement, commitment = setup_active_agreement_order_ready_commitment()
    validate_success(api_client.suspend_commitment(
        commitment["id"], parts_manager_headers()))
    assert get_commitment_copy(commitment["id"])["status"] == "SUSPENDED"

    data = validate_success(api_client.reinstate_commitment(
        commitment["id"], parts_manager_headers()))
    assert data["status"] == "ORDER_READY"


def test_commitment_suspension_requires_no_open_batch():
    """PRD §3.4: "Suspension moves `ORDER_READY` to `SUSPENDED` and is refused
    with `ERR_COMMITMENT_BATCH_OPEN` at HTTP 409 while any parts-order batch of
    the commitment is `OPEN` or `ORDERED`."

    Design: Corner/errors/restore_claim_denies_the_agreement_terminate_when_a_batch_is_open
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10)
    place_batch_order(batch["id"])

    resp = api_client.suspend_commitment(commitment["id"], parts_manager_headers())
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_BATCH_OPEN, expected_status=409)


def test_agreement_terminate_from_active_with_an_ordered_batch_is_refused():
    """PRD §3.2: "Every commitment of the agreement must be either `COMPLETE` or `CORE_PENDING` with a `credit_balance_cents` of 0, and no batch of the agreement's commitments may be `OPEN` or `ORDERED`; that second condition is refused with `ERR_AGREEMENT_COMMITMENT_OPEN` at HTTP 409."

    Design: Corner/errors/restore_claim_denies_the_agreement_terminate_when_a_batch_is_open
    """
    dealer, agreement, commitment = setup_active_agreement_order_ready_commitment()
    batch = create_batch(commitment, requested_units=10)
    place_batch_order(batch["id"])

    resp = api_client.terminate_agreement(agreement["id"], network_manager_headers())
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_COMMITMENT_OPEN, expected_status=409)
    assert get_agreement(agreement["id"])["status"] == "ACTIVE"


def test_agreement_terminate_from_draft_reports_invalid_state():
    """PRD §3.2: "The lifecycle of an agreement runs `DRAFT`, `SUBMITTED`,
    `ACTIVE`, and then either `SUSPENDED` or `PERFORMANCE_DEFICIENT`, with
    `TERMINATED` as the single terminal state reachable from either `ACTIVE` or
    `SUSPENDED`."

    Design: Corner/errors/restore_claim_denies_the_agreement_terminate_when_a_batch_is_open
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    draft = create_agreement(dealer, product_family="EARTHMOVING")

    resp = api_client.terminate_agreement(draft["id"], network_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def get_commitment_copy(commitment_id):
    return get_success_data(api_client.get_commitment(
        commitment_id, parts_manager_headers()))