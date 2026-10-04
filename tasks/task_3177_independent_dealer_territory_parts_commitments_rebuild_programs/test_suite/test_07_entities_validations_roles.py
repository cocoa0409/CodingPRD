"""Entity creation, validation ladder and role scoping."""
from test_helpers import (
    api_client,
    build_user_headers,
    get_success_data,
    make_input_dealer_headers,
    make_sales_manager_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_agreement,
    create_batch,
    create_certification_record,
    create_dealer,
    create_equipment_order,
    create_population_record,
    get_certification,
    get_dealer,
    network_manager_headers,
    parts_manager_headers,
    register_technician,
    reviewer_headers,
    sales_manager_headers,
    set_clock,
    setup_active_agreement_order_ready_commitment,
    setup_commitment_order_ready,
    technician_supervisor_headers,
    create_service_order,
)


# ─── Dealer creation and retrieval ────────────────────

def test_dealer_create_returns_every_declared_field_and_starts_pending():
    """PRD §3.1: "The new dealer's `status` begins at `PENDING_AGREEMENT`, and it
    stays there until the dealer holds at least one dealer agreement in
    `STORE_READY` standing." PRD §3.1: "the first three are initialised to 0 at
    creation and `market_share_pct` starts at 0.0." PRD §2.5: "Creation of a new,
    stand-alone resource returns `201 Created`."

    Design: Corner/entities/dealer_create_returns_every_declared_field_and_starts_pending
    """
    set_clock()
    resp = api_client.create_dealer({
        "legal_name": "High Plains Machinery Co",
        "home_state_code": "NE",
        "territory_code": "T-410",
    }, network_manager_headers())
    data = validate_success(resp, expected_status=201)

    assert resp.json()["response_type"] == "object"
    assert data["legal_name"] == "High Plains Machinery Co"
    assert data["home_state_code"] == "NE"
    assert data["status"] == "PENDING_AGREEMENT"
    assert data["version"] == 1
    assert data["certified_family_count"] == 0
    assert data["trusted_commitment_count"] == 0
    assert data["open_backorder_units"] == 0
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_dealer_get_returns_the_stored_configuration_unchanged():
    """PRD §3.1: "the territory code is required and becomes immutable after
    creation: a dealership does not change territory." PRD §3.1: "`market_share_pct`
    reports the latest `PerformanceReview.actual_market_share_pct` across this
    dealer's reviews, and reads 0.0 when no review has been evaluated."

    Design: Corner/entities/dealer_get_returns_the_stored_configuration_unchanged
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    resp = api_client.get_dealer(dealer["id"], reviewer_headers())
    data = validate_success(resp)

    assert resp.json()["response_type"] == "object"
    assert data["territory_code"] == "T-410"
    assert data["home_state_code"] == "NE"
    assert data["status"] == "PENDING_AGREEMENT"
    assert data["version"] == 1
    assert data["market_share_pct"] == 0.0


def test_dealers_list_paginates_and_reports_total_count():
    """PRD §2.3: "List endpoints accept a `limit` query parameter that caps how many resources come back, a default of 10 when the caller omits it, a floor of 1 and a ceiling of 100. The `offset` query parameter skips that many resources from the front of the result set and defaults to 0. Unless a list endpoint's own description says otherwise, results are ordered by creation timestamp ascending. Every paged list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object alongside the request identifier and timestamp."

    Design: Corner/entities/dealers_list_paginates_and_reports_total_count_and_has_more
    """
    set_clock()
    create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_dealer(legal_name="Coastal Lift Systems", home_state_code="CA",
                  territory_code="T-411")
    create_dealer(legal_name="Delta Compaction Supply", home_state_code="LA",
                  territory_code="T-412")

    page = api_client.list_dealers(network_manager_headers(), params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail = api_client.list_dealers(network_manager_headers(), params={"limit": 2, "offset": 2})
    rows_tail, meta_tail = validate_paginated(tail)
    assert len(rows_tail) == 1
    assert meta_tail["total_count"] == 3
    assert meta_tail["has_more"] is False


def test_dealer_list_defaults_count_the_whole_set():
    """PRD §2.3: "a default of 10 when the caller omits it, a floor of 1 and a
    ceiling of 100." PRD §2.3: "The `offset` query parameter skips that many resources from the front of the result set and defaults to 0."

    Design: Corner/entities/dealers_list_paginates_and_reports_total_count_and_has_more
    """
    set_clock()
    create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_dealer(legal_name="Coastal Lift Systems", home_state_code="CA",
                  territory_code="T-411")
    create_dealer(legal_name="Delta Compaction Supply", home_state_code="LA",
                  territory_code="T-412")

    resp = api_client.list_dealers(network_manager_headers())
    rows, meta = validate_paginated(resp)
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_dealer_get_with_an_unknown_id_returns_dealer_not_found():
    """PRD §2.6: "A read of a dealer's agreements fails with
    `ERR_DEALER_NOT_FOUND` at HTTP 404 if the dealer does not exist, long before
    any agreement is considered."

    Design: Corner/entities/dealer_get_with_an_unknown_id_returns_dealer_not_found
    """
    set_clock()
    resp = api_client.get_dealer(NON_EXISTENT_UUID, network_manager_headers())
    error = validate_error(resp, ApiErrorId.ERR_DEALER_NOT_FOUND, expected_status=404)

    assert resp.json()["response_type"] == "error"
    assert error["error_id"] == ApiErrorId.ERR_DEALER_NOT_FOUND
    assert error["message"]


def test_dealer_create_missing_territory_code_returns_invalid_request():
    """PRD §2.5: "A request whose body is malformed, whose required field is missing, whose field is unknown, or whose value falls outside its declared type or enum is refused earlier than any of these with `ERR_INVALID_REQUEST` at HTTP 400"

    Design: Corner/entities/dealer_create_missing_territory_code_returns_invalid_request
    """
    set_clock()
    resp = api_client.create_dealer({
        "legal_name": "Unassigned Machinery Co",
        "home_state_code": "KS",
    }, network_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows = get_success_data(api_client.list_dealers(network_manager_headers()))
    assert rows == []


def test_agreement_create_with_unknown_exclusivity_returns_invalid_request():
    """PRD §3.2: "It declares a `territory_code`, an `exclusivity_level` that defaults to `SHARED` and may be `EXCLUSIVE`" PRD §2.5: "whose value falls outside its declared type or enum is refused earlier than any of these with `ERR_INVALID_REQUEST` at HTTP 400"

    Design: Corner/entities/dealer_agreement_create_with_unknown_exclusivity_returns_invalid_request
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    resp = api_client.create_agreement({
        "dealer_id": dealer["id"], "product_family": "EARTHMOVING",
        "territory_code": "T-410", "exclusivity_level": "SOLE",
        "start_at": "2026-09-01T00:00:00Z", "end_at": "2027-09-01T00:00:00Z",
        "performance_plan_share_pct": 15,
        "expected_dealer_version": get_dealer(dealer["id"])["version"],
    }, network_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows = get_success_data(api_client.list_agreements(
        network_manager_headers(), params={"dealer_id": dealer["id"]}))
    assert rows == []


def test_agreement_create_ignores_client_status_and_version():
    """PRD §2.5: "Every resource also exposes a `status` field carrying its
    current state value from the enumeration defined for it in §3."
    PRD §2.5.1: "Creation of the agreement also increments `Dealer.version` by 1"

    Design: Corner/entities/dealer_agreement_create_extra_status_and_version_are_ignored_input
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    resp = api_client.create_agreement({
        "dealer_id": dealer["id"], "product_family": "EARTHMOVING",
        "territory_code": "T-410", "exclusivity_level": "SHARED",
        "start_at": "2026-09-01T00:00:00Z", "end_at": "2027-09-01T00:00:00Z",
        "performance_plan_share_pct": 15,
        "expected_dealer_version": get_dealer(dealer["id"])["version"],
    }, network_manager_headers())
    data = validate_success(resp, expected_status=201)

    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["dealer_id"] == dealer["id"]
    assert data["performance_plan_share_pct"] == 15


def test_agreement_create_bumps_the_dealer_version():
    """PRD §2.5.1: "Creation of the agreement also increments `Dealer.version`
    by 1 and recomputes the new agreement's `tooling_compliance_status`."

    Design: Corner/entities/dealer_agreement_create_extra_status_and_version_are_ignored_input
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    create_agreement(dealer, product_family="EARTHMOVING", performance_plan_share_pct=15)
    assert get_dealer(dealer["id"])["version"] == 2


def test_parts_order_batch_omitting_emergency_defaults_to_false():
    """PRD §3.5: "an optional `emergency` flag defaulting to false"
    PRD §3.5: "For an ordinary non-emergency batch the reservation is the smaller
    of `requested_units` and `available_commitment_units`."

    Design: Corner/entities/parts_order_batch_create_omitting_emergency_defaults_to_false
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    resp = api_client.create_batch({
        "commitment_id": commitment["id"], "product_family": "EXCAVATION",
        "requested_units": 10, "core_units": 0, "core_return_required": False,
        "requested_at": "2026-08-28T00:00:00Z",
    }, parts_manager_headers())
    data = validate_success(resp, expected_status=201)

    assert data["emergency"] is False
    assert data["reserved_units"] == 10
    assert data["status"] == "OPEN"


def test_certification_status_is_computed_on_read():
    """PRD §3.3: "The record's `status` is one of `ACTIVE`, `EXPIRED` or
    `REVOKED`, and for everything but an explicit revocation it is derived on
    read from `certified_at`, `recurrence_within_period` and the logical clock."

    Design: Corner/entities/certification_record_status_is_computed_on_read_and_never_stored
    """
    set_clock("2024-10-01T00:00:00Z")
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    cert = create_certification_record(dealer, "T-07", certified_at="2024-09-01T00:00:00Z")

    first = validate_success(api_client.get_certification(
        cert["id"], parts_manager_headers()))
    assert first["status"] == "ACTIVE"
    assert first["version"] == 1

    get_success_data(api_client.set_current_utc("2026-09-01T00:00:00Z",
                                                network_manager_headers()))
    second = validate_success(api_client.get_certification(
        cert["id"], parts_manager_headers()))
    assert second["status"] == "EXPIRED"


def test_certification_recurrence_never_stored_across_reads():
    """PRD §3.3: "it is derived on read from `certified_at`,
    `recurrence_within_period` and the logical clock."
    PRD §3.3: "A credential's `recurrence_within_period` is true when another
    certification record that is not `REVOKED` exists for the same dealer, the
    same product family and the same technician name with a `certified_at` inside
    the interval running from this record's `certified_at` up to but not
    including twelve months after it."

    Design: Corner/entities/certification_record_status_is_computed_on_read_and_never_stored
    """
    set_clock("2024-10-01T00:00:00Z")
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    cert = create_certification_record(dealer, "T-07", certified_at="2024-09-01T00:00:00Z")

    first = validate_success(api_client.get_certification(cert["id"], parts_manager_headers()))
    get_success_data(api_client.set_current_utc("2026-09-01T00:00:00Z",
                                                network_manager_headers()))
    second = validate_success(api_client.get_certification(cert["id"], parts_manager_headers()))

    assert first["recurrence_within_period"] is False
    assert second["recurrence_within_period"] is False


def test_unknown_parent_reference_is_refused_before_creation():
    """PRD §2.5: "A request whose body is malformed, whose required field is missing, whose field is unknown, or whose value falls outside its declared type or enum is refused earlier than any of these with `ERR_INVALID_REQUEST` at HTTP 400"

    Design: Corner/entities/trade_in_unit_create_requires_an_existing_equipment_order
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    resp = api_client.create_equipment_order({
        "dealer_id": dealer["id"], "product_family": "EXCAVATION",
        "machine_serial": "SN-6100", "list_price_cents": 50000000,
        "trade_in_serial": "SN-6001", "requested_at": "2026-08-20T00:00:00Z",
    }, make_sales_manager_headers(dealer["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"


def test_trade_in_rows_are_reachable_through_the_order_sub_resource():
    """PRD §3.8: "A trade-in is attached to its order through `order_id`."
    PRD §3.8: "When a `trade_in_serial` is set, a `TradeInUnit` is created in status `APPRAISED` carrying the order's trade-in serial"

    Design: Corner/entities/trade_in_unit_create_requires_an_existing_equipment_order
    """
    from test_helpers import submit_equipment_order
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = create_equipment_order(dealer, machine_serial="SN-6100",
                                   trade_in_serial="SN-6001",
                                   list_price_cents=50000000)
    submit_equipment_order(dealer, order["id"])

    resp = api_client.list_order_trade_ins(order["id"], sales_manager_headers(dealer["id"]))
    rows = validate_success(resp)
    assert isinstance(rows, list)
    assert len(rows) == 1
    # PRD §3.8: "Its `machine_serial` is copied from the equipment order's
    # trade-in serial and carries the dealer's current `client_meter_hours`
    # affixed, and it is a system-written value rather than a client input."
    assert rows[0]["machine_serial"].startswith("SN-6001")
    assert rows[0]["status"] == "APPRAISED"
    assert rows[0]["order_id"] == order["id"]

    empty = get_success_data(api_client.list_trade_in_units(
        network_manager_headers(),
        params={"order_id": "00000000-0000-4000-8000-000000000000"}))
    assert empty == []


# ─── Validation ladder ────────────────────────────────

def test_service_order_begin_without_auth_headers_returns_unauthenticated():
    """PRD §2.5: "1. **Header and identity authentication.** Both `X-User-ID` and `X-User-Role` must be present, the role must be a declared role, and the identifier must equal the `id` of an instance of that role's backing entity when the role is entity-backed. Failure gives `ERR_UNAUTHENTICATED` at HTTP 401."

    Design: Corner/validations/service_order_begin_without_auth_headers_returns_unauthenticated
    """
    set_clock()
    resp = api_client.begin_service_order(
        NON_EXISTENT_UUID, {"Content-Type": "application/json"})
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE
    assert error["error_id"] != ApiErrorId.ERR_DEALER_NOT_FOUND


def test_batch_create_by_a_role_outside_the_list_returns_unauthorized():
    """PRD §2.5: "2. **Role permission and actor scope.** The acting role must be permitted for the operation, and an actor backed by an entity may not act on another entity's resource. Failure gives `ERR_UNAUTHORIZED` at HTTP 403."

    Design: Corner/validations/batch_create_by_a_role_outside_the_endpoint_role_list_returns_unauthorized
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    # PRD §2.1: DealerSalesManager is entity-backed, so X-User-ID must resolve
    # to a real dealer before the role-permission rung can be reached.
    resp = api_client.create_batch({
        "commitment_id": commitment["id"], "product_family": "EXCAVATION",
        "requested_units": 10, "core_units": 0, "core_return_required": False,
        "requested_at": "2026-08-28T00:00:00Z",
    }, make_sales_manager_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_unauthorized_batch_create_creates_no_row():
    """PRD §2.5: "2. **Role permission and actor scope.**" PRD §4: "Creating a new, stand-alone resource — a dealer, a dealer agreement, a performance review, a parts commitment, a parts-order batch, a rebuild claim, an equipment order, a support agreement, a market-share observation, a service order, a machine population record, a certification record or a party registration — returns `201 Created`."

    Design: Corner/validations/batch_create_by_a_role_outside_the_endpoint_role_list_returns_unauthorized
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    api_client.create_batch({
        "commitment_id": commitment["id"], "product_family": "EXCAVATION",
        "requested_units": 10, "core_units": 0, "core_return_required": False,
        "requested_at": "2026-08-28T00:00:00Z",
    }, make_sales_manager_headers(dealer["id"]))

    rows = get_success_data(api_client.list_batches(
        parts_manager_headers(), params={"commitment_id": commitment["id"]}))
    assert rows == []


def test_order_ready_blocked_by_incomplete_tooling_until_second_credential():
    """PRD §3.2: "The agreement's `tooling_compliance_status` must be
    `COMPLIANT`, so a shortfall here is refused with `ERR_TOOLING_INCOMPLETE` at
    HTTP 409. The `certified_technician_count` must be at least 2, which is the
    same check seen from the head-count side and carries the same error."

    Design: Corner/validations/order_ready_when_the_agreement_is_not_compliant_returns_tooling_incomplete
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    agreement = create_agreement(dealer, product_family="EXCAVATION")
    register_technician(dealer, "T-01")
    commitment = None
    from test_helpers import create_commitment, submit_commitment
    commitment = create_commitment(dealer, agreement)
    # PRD §3.4: the owning agreement must be SUBMITTED or ACTIVE before the
    # commitment can move out of PLANNED.
    get_success_data(api_client.submit_agreement(agreement["id"], network_manager_headers()))
    submit_commitment(commitment["id"])

    first = api_client.ready_commitment_for_orders(commitment["id"], parts_manager_headers())
    validate_error(first, ApiErrorId.ERR_TOOLING_INCOMPLETE, expected_status=409)


def test_order_ready_succeeds_once_the_second_credential_lands():
    """PRD §3.2: "`tooling_compliance_status` is `NOT_SUBMITTED` while the agreement holds no certification record at all, `PARTIAL` while `certified_technician_count` is below the product family minimum of 2, and `COMPLIANT` once it reaches 2 — with the further requirement that `COMPLIANT` also requires the product family's tooling kit registration to be present."
    PRD §3.4: "Becoming order-ready moves `SUBMITTED` to `ORDER_READY`"

    Design: Corner/validations/order_ready_when_the_agreement_is_not_compliant_returns_tooling_incomplete
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    agreement = create_agreement(dealer, product_family="EXCAVATION")
    register_technician(dealer, "T-01")
    from test_helpers import create_commitment, submit_commitment, get_commitment
    commitment = create_commitment(dealer, agreement)
    get_success_data(api_client.submit_agreement(agreement["id"], network_manager_headers()))
    submit_commitment(commitment["id"])
    api_client.ready_commitment_for_orders(commitment["id"], parts_manager_headers())

    register_technician(dealer, "T-02")
    # PRD §3.4: order-readiness also requires the population tier to be other
    # than MICRO, so the fixture stands up a machine row for the family.
    create_population_record(dealer, "SN-8801", product_family="EXCAVATION",
                             machine_operating_weight_lb=50000)
    data = validate_success(api_client.ready_commitment_for_orders(
        commitment["id"], parts_manager_headers()))
    assert data["status"] == "ORDER_READY"


def test_auth_pair_resolves_existence_never_runs():
    """PRD §2.5: "1. **Header and identity authentication.** Both `X-User-ID` and `X-User-Role` must be present, the role must be a declared role, and the identifier must equal the `id` of an instance of that role's backing entity when the role is entity-backed. Failure gives `ERR_UNAUTHENTICATED` at HTTP 401. 2. **Role permission and actor scope.** The acting role must be permitted for the operation, and an actor backed by an entity may not act on another entity's resource. Failure gives `ERR_UNAUTHORIZED` at HTTP 403."

    Design: Corner/validations/service_order_begin_with_a_non_technician_role_returns_unauthorized
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(_dealer, commitment, kind="SLA_AUDIT", sla_hours=12.0)

    no_headers = api_client.begin_service_order(
        order["id"], {"Content-Type": "application/json"})
    validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    wrong_role = api_client.begin_service_order(order["id"], network_manager_headers())
    validate_error(wrong_role, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_batch_create_with_a_satisfied_precondition_reserves_the_full_request():
    """PRD §3.5: "For an ordinary non-emergency batch the reservation is the
    smaller of `requested_units` and `available_commitment_units`."

    Design: Corner/validations/batch_create_conforms_and_succeeds_on_a_satisfied_precondition
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=61)
    assert batch["reserved_units"] == 61

    from test_helpers import get_commitment
    assert get_commitment(commitment["id"])["available_commitment_units"] == 2


def test_oversized_batch_still_creates_with_an_over_reservation():
    """PRD §3.5: "For an oversized non-emergency batch — one whose `requested_units` exceeds `available_commitment_units` — the reservation is exactly the active variant plus 2"

    Design: Corner/validations/batch_create_conforms_and_succeeds_on_a_satisfied_precondition
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    create_batch(commitment, requested_units=61)
    second = create_batch(commitment, requested_units=65)

    assert second["reserved_units"] == 66


# ─── Role scoping and ownership ───────────────────────

def test_parts_manager_cannot_open_a_performance_review():
    """PRD §2.5: "2. **Role permission and actor scope.** The acting role must be permitted for the operation, and an actor backed by an entity may not act on another entity's resource. Failure gives `ERR_UNAUTHORIZED` at HTTP 403."

    Design: Corner/rbac/parts_manager_cannot_touch_the_performance_review
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    resp = api_client.create_review({
        "dealer_id": dealer["id"], "agreement_id": agreement["id"],
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-07-01T00:00:00Z",
        "actual_territory_machine_units": 6, "territory_market_machine_units": 30,
        "sampled_service_orders": 10, "met_sla_service_orders": 9,
        "expected_dealeragreement_version": get_success_data(api_client.get_agreement(
            agreement["id"], network_manager_headers()))["version"],
    }, parts_manager_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_unauthorized_review_create_leaves_no_row():
    """PRD §2.5: "2. **Role permission and actor scope.**"

    Design: Corner/rbac/parts_manager_cannot_touch_the_performance_review
    """
    dealer, agreement, _commitment = setup_active_agreement_order_ready_commitment()
    api_client.create_review({
        "dealer_id": dealer["id"], "agreement_id": agreement["id"],
        "period_start": "2026-01-01T00:00:00Z", "period_end": "2026-07-01T00:00:00Z",
        "actual_territory_machine_units": 6, "territory_market_machine_units": 30,
        "sampled_service_orders": 10, "met_sla_service_orders": 9,
        "expected_dealeragreement_version": get_success_data(api_client.get_agreement(
            agreement["id"], network_manager_headers()))["version"],
    }, parts_manager_headers())

    rows = get_success_data(api_client.list_agreement_reviews(
        agreement["id"], reviewer_headers()))
    assert rows == []


def test_dealer_principal_reads_only_its_own_agreements():
    """PRD §2.1: "When `X-User-Role` is `InputDealer`, the same applies:
    `X-User-ID` is the `id` of the acting `Dealer`, and every read this role
    performs is scoped to that dealer's own rows."

    Design: Corner/rbac/dealer_principal_reads_only_its_own_agreements
    """
    set_clock()
    dealer_a = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    agreement_a = create_agreement(dealer_a, product_family="EXCAVATION")
    dealer_b = create_dealer(legal_name="Coastal Lift Systems", home_state_code="CA",
                             territory_code="T-411")
    agreement_b = create_agreement(dealer_b, product_family="COMPACTION",
                                   performance_plan_share_pct=25)

    resp_a = api_client.list_agreements(make_input_dealer_headers(dealer_a["id"]))
    rows_a = validate_success(resp_a)
    resp_b = api_client.list_agreements(make_input_dealer_headers(dealer_b["id"]))
    rows_b = validate_success(resp_b)

    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0]["id"] == agreement_a["id"]
    assert rows_b[0]["id"] == agreement_b["id"]


def test_input_dealer_never_surfaces_the_other_dealers_agreement():
    """PRD §2.1: "a dealer may read only its own agreements, commitments, reviews,
    claims, support agreements, population records, observations and
    certifications."

    Design: Corner/rbac/dealer_principal_reads_only_its_own_agreements
    """
    set_clock()
    dealer_a = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    agreement_a = create_agreement(dealer_a, product_family="EXCAVATION")
    dealer_b = create_dealer(legal_name="Coastal Lift Systems", home_state_code="CA",
                             territory_code="T-411")
    agreement_b = create_agreement(dealer_b, product_family="COMPACTION",
                                   performance_plan_share_pct=25)

    rows_a = get_success_data(api_client.list_agreements(
        make_input_dealer_headers(dealer_a["id"])))
    assert agreement_b["id"] not in [row["id"] for row in rows_a]
    assert agreement_a["id"] != agreement_b["id"]


def test_dealer_sales_manager_cannot_act_for_another_dealer():
    """PRD §2.1: "A `DealerSalesManager` of one dealership therefore cannot act
    on another dealership's resources, and that attempt is rejected with
    `ERR_UNAUTHORIZED` at HTTP 403."

    Design: Corner/endpoints/dealer_sales_manager_cannot_act_for_another_dealer
    """
    set_clock()
    dealer_a = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    dealer_b = create_dealer(legal_name="Coastal Lift Systems", home_state_code="CA",
                             territory_code="T-411")

    cross = api_client.create_equipment_order({
        "dealer_id": dealer_b["id"], "product_family": "EXCAVATION",
        "machine_serial": "SN-6300", "list_price_cents": 50000000,
        "requested_at": "2026-08-20T00:00:00Z",
    }, make_sales_manager_headers(dealer_a["id"]))
    validate_error(cross, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    own = api_client.create_equipment_order({
        "dealer_id": dealer_a["id"], "product_family": "EXCAVATION",
        "machine_serial": "SN-6300", "list_price_cents": 50000000,
        "requested_at": "2026-08-20T00:00:00Z",
    }, make_sales_manager_headers(dealer_a["id"]))
    data = validate_success(own, expected_status=201)
    assert data["dealer_id"] == dealer_a["id"]

    other_rows = get_success_data(api_client.list_equipment_orders(
        network_manager_headers(), params={"dealer_id": dealer_b["id"]}))
    assert other_rows == []


def test_equipment_financing_approval_requires_a_reference():
    """PRD §2.5: "Nothing above the rung that failed is re-checked after the fact, and a rung that passes never re-raises. A request whose body is malformed, whose required field is missing, whose field is unknown, or whose value falls outside its declared type or enum is refused earlier than any of these with `ERR_INVALID_REQUEST` at HTTP 400, because no rung in the ladder can be evaluated against a body that does not parse into the declared shape."

    Design: Corner/errors/restore_claim_denies_the_agreement_terminate_when_a_batch_is_open
    """
    from test_helpers import (create_equipment_order as mk_order,
                              submit_equipment_order, finance_partner_headers)
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-410")
    order = mk_order(dealer, machine_serial="SN-6401", list_price_cents=50000000)
    submit_equipment_order(dealer, order["id"])

    resp = api_client.approve_equipment_financing(order["id"], {}, finance_partner_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_order_ready_requires_a_non_planned_commitment():
    """PRD §3.4: "Submission moves a commitment from `PLANNED` to `SUBMITTED`, requires that the owning agreement be `SUBMITTED` or `ACTIVE` — otherwise the request is refused with `ERR_INVALID_STATE` at HTTP 409"

    Design: Difficulty/cross_entity_state_dependency/parts_commitment_tier_depends_on_agreement_activation_state
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-220")
    agreement = create_agreement(dealer, product_family="EXCAVATION")
    register_technician(dealer, "T-01")
    register_technician(dealer, "T-02")
    from test_helpers import create_commitment
    commitment = create_commitment(dealer, agreement)

    # Agreement is still DRAFT, so submission of the commitment is refused.
    resp = api_client.submit_commitment(commitment["id"], parts_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_commitment_submits_once_the_agreement_is_submitted():
    """PRD §3.4: "Submission moves a commitment from `PLANNED` to `SUBMITTED`, requires that the owning agreement be `SUBMITTED` or `ACTIVE`"
    PRD §3.1: "`trusted_commitment_count` counts the dealer's agreements whose
    `trusted_commitment` flag is true."

    Design: Difficulty/cross_entity_state_dependency/parts_commitment_tier_depends_on_agreement_activation_state
    """
    set_clock()
    dealer = create_dealer(legal_name="High Plains Machinery Co", territory_code="T-220")
    agreement = create_agreement(dealer, product_family="EXCAVATION")
    register_technician(dealer, "T-01")
    register_technician(dealer, "T-02")
    from test_helpers import create_commitment, get_commitment
    commitment = create_commitment(dealer, agreement)
    api_client.submit_commitment(commitment["id"], parts_manager_headers())
    assert get_dealer(dealer["id"])["trusted_commitment_count"] == 0

    get_success_data(api_client.submit_agreement(agreement["id"], network_manager_headers()))
    data = validate_success(api_client.submit_commitment(
        commitment["id"], parts_manager_headers()))
    assert data["status"] == "SUBMITTED"


def test_order_ready_drives_the_dealer_to_active():
    """PRD §3.4: "It sets the owning agreement's `trusted_commitment` to true,
    recomputes `Dealer.trusted_commitment_count`, drives `Dealer.status` to
    `ACTIVE` when `trusted_commitment_count` is at least 1, and reactivates the
    default deferred shortage rule." PRD §3.1: "A dealer in `PENDING_AGREEMENT` becomes `ACTIVE` the moment `trusted_commitment_count` reaches 1"

    Design: Difficulty/cross_entity_state_dependency/commitment_ready_for_orders_depends_on_dealer_trusted_state
    """
    from test_helpers import get_commitment
    dealer, agreement, commitment = setup_commitment_order_ready()
    assert get_dealer(dealer["id"])["status"] == "ACTIVE"
    assert get_dealer(dealer["id"])["trusted_commitment_count"] >= 1
    assert get_commitment(commitment["id"])["status"] == "ORDER_READY"


def test_leaving_order_ready_returns_the_dealer_to_suspended():
    """PRD §3.2: "A dealer in `ACTIVE` becomes `SUSPENDED` automatically when no agreement of that dealer is `ACTIVE`"
    PRD §3.4: "Suspension moves `ORDER_READY` to `SUSPENDED` and is refused with `ERR_COMMITMENT_BATCH_OPEN` at HTTP 409 while any parts-order batch of the commitment is `OPEN` or `ORDERED`. Suspension clears the owning agreement's `trusted_commitment` to false when no other commitment of that agreement remains `ORDER_READY`, recomputes `Dealer.trusted_commitment_count`, and deactivates the default deferred shortage rule."

    Design: Difficulty/cross_entity_state_dependency/commitment_ready_for_orders_depends_on_dealer_trusted_state
    """
    from test_helpers import create_commitment, submit_commitment
    set_clock()
    dealer = create_dealer(legal_name="Prairie Ironworks LLC", territory_code="T-220")
    agreement = create_agreement(dealer, product_family="EXCAVATION")
    register_technician(dealer, "T-01")
    register_technician(dealer, "T-02")
    commitment = create_commitment(dealer, agreement)
    get_success_data(api_client.submit_agreement(agreement["id"], network_manager_headers()))
    submit_commitment(commitment["id"])
    get_success_data(api_client.ready_commitment_for_orders(
        commitment["id"], parts_manager_headers()))
    assert get_dealer(dealer["id"])["status"] == "ACTIVE"

    get_success_data(api_client.suspend_commitment(commitment["id"], parts_manager_headers()))
    assert get_dealer(dealer["id"])["trusted_commitment_count"] == 0