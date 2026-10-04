"""Composite setup helpers.

Every test starts against an empty database and builds its preconditions from
scratch through PRD-declared endpoints. The helpers below encapsulate the
multi-step setup sequences so tests can focus on assertions.

All helpers use the lenient ``get_success_data`` validator internally, so a
setup failure surfaces as a clear "Setup failed" assertion rather than as a
confusing downstream mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .test_users import TEST_USERS, make_input_dealer_headers, make_sales_manager_headers


# ─── Role header shorthands ───────────────────────────

def network_manager_headers():
    return dict(TEST_USERS["network_manager_headers"])


def reviewer_headers():
    return dict(TEST_USERS["reviewer_headers"])


def parts_manager_headers():
    return dict(TEST_USERS["parts_manager_headers"])


def rebuild_specialist_headers():
    return dict(TEST_USERS["rebuild_specialist_headers"])


def technician_supervisor_headers():
    return dict(TEST_USERS["technician_supervisor_headers"])


def finance_partner_headers():
    return dict(TEST_USERS["finance_partner_headers"])


def _nm(h=None):
    return h if h is not None else network_manager_headers()


def _pm(h=None):
    return h if h is not None else parts_manager_headers()


def _rv(h=None):
    return h if h is not None else reviewer_headers()


def _rs(h=None):
    return h if h is not None else rebuild_specialist_headers()


def _ts(h=None):
    return h if h is not None else technician_supervisor_headers()


def _fp(h=None):
    return h if h is not None else finance_partner_headers()


# ─── Logical clock ────────────────────────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO, headers=None):
    """Set the logical clock. All STAFF roles may set it."""
    resp = api_client.set_current_utc(to_iso8601, _nm(headers))
    return get_success_data(resp)


# ─── Dealer ───────────────────────────────────────────

def create_dealer(legal_name="High Plains Machinery Co",
                  home_state_code="NE",
                  territory_code="T-410",
                  headers=None):
    resp = api_client.create_dealer(
        {
            "legal_name": legal_name,
            "home_state_code": home_state_code,
            "territory_code": territory_code,
        },
        _nm(headers),
    )
    return get_success_data(resp, expected_status=201)


def get_dealer(dealer_id, headers=None):
    resp = api_client.get_dealer(dealer_id, _nm(headers))
    return get_success_data(resp)


def dealer_version(dealer_id, headers=None):
    return get_dealer(dealer_id, headers)["version"]


# ─── Dealer agreement ─────────────────────────────────

def create_agreement(dealer,
                     product_family="EXCAVATION",
                     territory_code=None,
                     exclusivity_level="EXCLUSIVE",
                     start_at="2026-09-01T00:00:00Z",
                     end_at="2027-09-01T00:00:00Z",
                     performance_plan_share_pct=20,
                     headers=None):
    payload = {
        "dealer_id": dealer["id"],
        "product_family": product_family,
        "territory_code": territory_code or dealer["territory_code"],
        "exclusivity_level": exclusivity_level,
        "start_at": start_at,
        "end_at": end_at,
        "performance_plan_share_pct": performance_plan_share_pct,
        "expected_dealer_version": dealer_version(dealer["id"], headers),
    }
    resp = api_client.create_agreement(payload, _nm(headers))
    return get_success_data(resp, expected_status=201)


def get_agreement(agreement_id, headers=None):
    resp = api_client.get_agreement(agreement_id, _nm(headers))
    return get_success_data(resp)


def agreement_version(agreement_id, headers=None):
    return get_agreement(agreement_id, headers)["version"]


def submit_agreement(agreement_id, headers=None):
    resp = api_client.submit_agreement(agreement_id, _nm(headers))
    return get_success_data(resp)


def activate_agreement(agreement_id, headers=None):
    resp = api_client.activate_agreement(agreement_id, _nm(headers))
    return get_success_data(resp)


# ─── Certification records ────────────────────────────

def register_technician(dealer,
                        technician_name,
                        product_family="EXCAVATION",
                        credential_code="DEALER_MASTER",
                        certified_at="2026-08-01T00:00:00Z",
                        headers=None):
    resp = api_client.create_certification(
        {
            "dealer_id": dealer["id"],
            "technician_name": technician_name,
            "product_family": product_family,
            "credential_code": credential_code,
            "certified_at": certified_at,
        },
        _pm(headers),
    )
    return get_success_data(resp, expected_status=201)


def register_technicians(dealer, names=("T-01", "T-02"),
                         product_family="EXCAVATION", headers=None):
    return [
        register_technician(dealer, name, product_family=product_family, headers=headers)
        for name in names
    ]


# ─── Parts commitments ────────────────────────────────

def create_commitment(dealer,
                      agreement,
                      product_family=None,
                      machine_population_units=500,
                      machine_population_slope=1.0,
                      planned_annual_units=50000,
                      emergency_stocking_target_pct=50,
                      emergency_fill_window_hours=24,
                      headers=None):
    payload = {
        "agreement_id": agreement["id"],
        "dealer_id": dealer["id"],
        "product_family": product_family or agreement["product_family"],
        "machine_population_units": machine_population_units,
        "machine_population_slope": machine_population_slope,
        "planned_annual_units": planned_annual_units,
        "emergency_stocking_target_pct": emergency_stocking_target_pct,
        "emergency_fill_window_hours": emergency_fill_window_hours,
        "expected_dealer_version": dealer_version(dealer["id"], headers),
    }
    resp = api_client.create_commitment(payload, _pm(headers))
    return get_success_data(resp, expected_status=201)


def get_commitment(commitment_id, headers=None):
    resp = api_client.get_commitment(commitment_id, _pm(headers))
    return get_success_data(resp)


def submit_commitment(commitment_id, headers=None):
    resp = api_client.submit_commitment(commitment_id, _pm(headers))
    return get_success_data(resp)


def ready_commitment_for_orders(commitment_id, headers=None):
    resp = api_client.ready_commitment_for_orders(commitment_id, _pm(headers))
    return get_success_data(resp)


def reinstate_commitment(commitment_id, headers=None):
    resp = api_client.reinstate_commitment(commitment_id, _pm(headers))
    return get_success_data(resp)


def suspend_commitment(commitment_id, headers=None):
    resp = api_client.suspend_commitment(commitment_id, _pm(headers))
    return get_success_data(resp)


def suspend_commitment_core_credit(commitment_id, headers=None):
    resp = api_client.suspend_commitment_core_credit(commitment_id, _pm(headers))
    return get_success_data(resp)


def settle_commitment_core_credit(commitment_id, credit_settlement_cents, headers=None):
    resp = api_client.settle_commitment_core_credit(
        commitment_id, {"credit_settlement_cents": credit_settlement_cents}, _pm(headers),
    )
    return resp


# ─── Standalone agreements for a second product family ─

def create_agreement_for_family(dealer, product_family,
                                expected_dealer_version=None, headers=None):
    """Create a stand-alone agreement for another product family.

    A commitment's product family must equal its agreement's family, so tests
    that need two families side by side build one agreement per family.
    """
    payload = {
        "dealer_id": dealer["id"],
        "product_family": product_family,
        "territory_code": dealer["territory_code"],
        "exclusivity_level": "SHARED",
        "start_at": "2026-09-01T00:00:00Z",
        "end_at": "2027-09-01T00:00:00Z",
        "performance_plan_share_pct": 20,
        "expected_dealer_version": (
            expected_dealer_version
            if expected_dealer_version is not None
            else dealer_version(dealer["id"], headers)
        ),
    }
    resp = api_client.create_agreement(payload, _nm(headers))
    return get_success_data(resp, expected_status=201)


# ─── Composite setups ─────────────────────────────────

def setup_dealer_with_agreement(product_family="EXCAVATION",
                                performance_plan_share_pct=20,
                                territory_code="T-410",
                                legal_name="High Plains Machinery Co",
                                registered_technicians=2,
                                commit=True,
                                **commitment_kwargs):
    """Clock + dealer + agreement (DRAFT) + technicians + PLANNED commitment.

    Returns (dealer, agreement, commitment).

    The agreement is built by default with ``exclusivity_level`` left at its
    PRD default of ``SHARED`` so that it carries no territory-equality
    obligation; a PRD-faithful implementation is then free to accept its
    submission for any territory code the dealer happens to hold.
    """
    set_clock()
    dealer = create_dealer(legal_name=legal_name, territory_code=territory_code)
    agreement = create_agreement(
        dealer,
        product_family=product_family,
        exclusivity_level="SHARED",
        performance_plan_share_pct=performance_plan_share_pct,
    )
    if registered_technicians:
        register_technicians(
            dealer,
            names=tuple(f"T-{i:02d}" for i in range(1, registered_technicians + 1)),
            product_family=product_family,
        )
    commitment = None
    if commit:
        commitment = create_commitment(dealer, agreement, **commitment_kwargs)
    return dealer, agreement, commitment


def setup_submitted_commitment(**kwargs):
    """Dealer + agreement SUBMITTED + commitment SUBMITTED (dealer still PENDING_AGREEMENT).

    Returns (dealer, agreement, commitment).
    """
    for key in ("commit", "registered_technicians"):
        kwargs.pop(key, None)
    dealer, agreement, commitment = setup_dealer_with_agreement(**kwargs)
    submit_agreement(agreement["id"])
    submit_commitment(commitment["id"])
    return dealer, agreement, commitment


def setup_commitment_order_ready(**kwargs):
    """Full chain to a commitment in ORDER_READY.

    Clock -> dealer -> agreement -> two technicians -> commitment ->
    agreement submit -> commitment submit -> ready-for-orders.
    Returns (dealer, agreement, commitment).
    """
    deployed = dict(kwargs)
    deployed.pop("commit", None)
    deployed.pop("registered_technicians", None)
    dealer, agreement, commitment = setup_dealer_with_agreement(**deployed)
    submit_agreement(agreement["id"])
    submit_commitment(commitment["id"])
    ready_commitment_for_orders(commitment["id"])
    return dealer, agreement, commitment


def setup_active_agreement_order_ready_commitment(**kwargs):
    """Full chain to an ACTIVE agreement plus an ORDER_READY commitment.

    Returns (dealer, agreement, commitment).
    """
    dealer, agreement, commitment = setup_commitment_order_ready(**kwargs)
    activate_agreement(agreement["id"])
    return dealer, agreement, get_commitment(commitment["id"])


def setup_performance_deficient_commitment(**kwargs):
    """Chain to an agreement whose commitment is PERFORMANCE_DEFICIENT.

    Reached by escalating a non-orderable service order, which drives the
    commitment to PERFORMANCE_DEFICIENT and stamps its backorder instant.
    Returns (dealer, agreement, commitment, service_order).
    """
    dealer, agreement, commitment = setup_commitment_order_ready(**kwargs)
    # PRD §3.7: approval requires the dealer's agreement for the product family
    # to be ACTIVE, so the fixture activates it before the claim is raised.
    activate_agreement(agreement["id"])
    order = create_service_order(
        dealer, commitment, kind="EMERGENCY_FILL",
        orderable_ref_enabled=False, sla_hours=6.0,
    )
    resp = api_client.begin_service_order(order["id"], technician_supervisor_headers())
    get_success_data(resp)
    resp = api_client.escalate_service_order(order["id"], technician_supervisor_headers())
    order = get_success_data(resp)
    return dealer, agreement, get_commitment(commitment["id"]), order


# ─── Parts order batches ──────────────────────────────

def create_batch(commitment,
                 requested_units=10,
                 core_units=0,
                 core_return_required=False,
                 emergency=None,
                 requested_at="2026-08-28T00:00:00Z",
                 product_family=None,
                 headers=None):
    payload = {
        "commitment_id": commitment["id"],
        "product_family": product_family or commitment["product_family"],
        "requested_units": requested_units,
        "core_units": core_units,
        "core_return_required": core_return_required,
        "requested_at": requested_at,
    }
    if emergency is not None:
        payload["emergency"] = emergency
    resp = api_client.create_batch(payload, _pm(headers))
    return get_success_data(resp, expected_status=201)


def get_batch(batch_id, headers=None):
    resp = api_client.get_batch(batch_id, _pm(headers))
    return get_success_data(resp)


def place_batch_order(batch_id, headers=None):
    resp = api_client.place_batch_order(batch_id, _pm(headers))
    return get_success_data(resp)


def receive_batch(batch_id, ordered_ref="OEM-ORD-7001", headers=None):
    resp = api_client.receive_batch(batch_id, {"ordered_ref": ordered_ref}, _pm(headers))
    return get_success_data(resp)


def batch_core_return(batch_id, core_units=1, headers=None):
    resp = api_client.batch_core_return(batch_id, {"core_units": core_units}, _pm(headers))
    return get_success_data(resp)


def cancel_batch_core_return(batch_id, headers=None):
    resp = api_client.cancel_batch_core_return(batch_id, _pm(headers))
    return get_success_data(resp)


def return_batch_core(batch_id, core_units=1, headers=None):
    resp = api_client.return_batch_core(batch_id, {"core_units": core_units}, _pm(headers))
    return get_success_data(resp)


def create_received_batch(commitment, requested_units=10, core_units=1,
                          ordered_ref="OEM-ORD-7001", **kwargs):
    """Create -> place-order -> receive. Returns the received batch."""
    batch = create_batch(commitment, requested_units=requested_units,
                         core_units=core_units, **kwargs)
    place_batch_order(batch["id"])
    return receive_batch(batch["id"], ordered_ref=ordered_ref)


def link_certification_to_agreement(agreement_id, technician_name,
                                    certified_at="2026-08-01T00:00:00Z"):
    """Submit a nested certification row addressed through its parent agreement.

    Modification of an existing resource, including the creation of a nested row
    addressed through its parent, returns `200 OK`.
    """
    resp = api_client._request(
        "POST", f"/dealer-network/dealer-agreements/{agreement_id}/certification-records",
        {
            "technician_name": technician_name,
            "credential_code": "DEALER_MASTER",
            "certified_at": certified_at,
        },
        parts_manager_headers(),
    )
    return get_success_data(resp)


def setup_core_return_round_trip(agreement_credentialed=True,
                                 requested_units=10, core_units=0):
    """Setup for the core-return compensating pair.

    Order_ready commitment with a RECEIVED batch and a zero credit balance: the
    receipt writes no credit when the batch carries no cores (PRD §3.5), so the
    forward partial return is the first thing that prices one. When
    ``agreement_credentialed`` is set, two credentials are linked to the
    agreement so it reads COMPLIANT and the batch core-return's zero-balance
    commitment suspension lands on a legitimate state.

    Returns (dealer, agreement, commitment, batch).
    """
    dealer, agreement, commitment = setup_commitment_order_ready()
    if agreement_credentialed:
        for name in ("T-01", "T-02"):
            link_certification_to_agreement(agreement["id"], name)
    batch = create_batch(commitment, requested_units=requested_units,
                         core_units=core_units, core_return_required=True)
    place_batch_order(batch["id"])
    receive_batch(batch["id"], ordered_ref="OEM-ORD-7001")
    return dealer, agreement, commitment, batch


# ─── Machine population records ───────────────────────

def create_population_record(dealer,
                             machine_serial,
                             product_family="EXCAVATION",
                             machine_operating_weight_lb=50000,
                             meter_hours=1000,
                             headers=None):
    resp = api_client.create_population_record(
        {
            "dealer_id": dealer["id"],
            "product_family": product_family,
            "machine_serial": machine_serial,
            "machine_operating_weight_lb": machine_operating_weight_lb,
            "meter_hours": meter_hours,
        },
        _pm(headers),
    )
    return get_success_data(resp, expected_status=201)


def get_population_record(record_id, headers=None):
    resp = api_client.get_population_record(record_id, _pm(headers))
    return get_success_data(resp)


def retire_population_record(record_id, headers=None):
    resp = api_client.retire_population_record(record_id, _pm(headers))
    return get_success_data(resp)


def get_forecast(dealer_id, headers=None):
    resp = api_client.get_forecast(dealer_id, _pm(headers))
    return get_success_data(resp)


def get_sweep_metrics(dealer_id, headers=None):
    resp = api_client.get_sweep_metrics(_pm(headers), params={"dealer_id": dealer_id})
    return get_success_data(resp)


# ─── Support agreements ───────────────────────────────

def create_support_agreement(dealer, machine_serial, plan_tier="PREMIUM",
                             enrolled_at="2026-08-15T00:00:00Z", headers=None):
    resp = api_client.create_support_agreement(
        {
            "dealer_id": dealer["id"],
            "machine_serial": machine_serial,
            "plan_tier": plan_tier,
            "enrolled_at": enrolled_at,
        },
        _pm(headers),
    )
    return get_success_data(resp, expected_status=201)


def get_support_agreement(support_id, headers=None):
    resp = api_client.get_support_agreement(support_id, _pm(headers))
    return get_success_data(resp)


# ─── Service orders ───────────────────────────────────

def create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                         product_family=None,
                         machine_serial=None,
                         orderable_ref_enabled=False,
                         restriction_scope="HOURS_SPENT",
                         sla_hours=6.0,
                         headers=None):
    payload = {
        "dealer_id": dealer["id"],
        "commitment_id": commitment["id"],
        "kind": kind,
        "product_family": product_family or commitment["product_family"],
        "orderable_ref_enabled": orderable_ref_enabled,
        "restriction_scope": restriction_scope,
        "sla_hours": sla_hours,
    }
    if machine_serial is not None:
        payload["machine_serial"] = machine_serial
    resp = api_client.create_service_order(payload, _ts(headers))
    return get_success_data(resp, expected_status=201)


def get_service_order(service_order_id, headers=None):
    resp = api_client.get_service_order(service_order_id, _ts(headers))
    return get_success_data(resp)


# ─── Certification ────────────────────────────────────

def get_certification(certification_id, headers=None):
    resp = api_client.get_certification(certification_id, _pm(headers))
    return get_success_data(resp)


# ─── Performance reviews ──────────────────────────────

def create_review(dealer, agreement,
                  period_start="2026-01-01T00:00:00Z",
                  period_end="2026-07-01T00:00:00Z",
                  actual_territory_machine_units=6,
                  territory_market_machine_units=30,
                  sampled_service_orders=10,
                  met_sla_service_orders=9,
                  circumstance_note=None,
                  expected_agreement_version=None,
                  headers=None):
    payload = {
        "dealer_id": dealer["id"],
        "agreement_id": agreement["id"],
        "period_start": period_start,
        "period_end": period_end,
        "actual_territory_machine_units": actual_territory_machine_units,
        "territory_market_machine_units": territory_market_machine_units,
        "sampled_service_orders": sampled_service_orders,
        "met_sla_service_orders": met_sla_service_orders,
        "expected_dealeragreement_version": (
            expected_agreement_version
            if expected_agreement_version is not None
            else agreement_version(agreement["id"], headers)
        ),
    }
    if circumstance_note is not None:
        payload["circumstance_note"] = circumstance_note
    resp = api_client.create_review(payload, _rv(headers))
    return get_success_data(resp, expected_status=201)


def get_review(review_id, headers=None):
    resp = api_client.get_review(review_id, _rv(headers))
    return get_success_data(resp)


def record_review_results(review_id, headers=None):
    resp = api_client.record_review_results(review_id, _rv(headers))
    return get_success_data(resp)


# ─── Market-share observations ────────────────────────

def create_observation(dealer,
                       product_family="EXCAVATION",
                       observed_machine_units=5,
                       territory_machine_units=10,
                       recorded_at="2026-03-01T00:00:00Z",
                       kind="MACHINE",
                       headers=None):
    resp = api_client.create_observation(
        {
            "dealer_id": dealer["id"],
            "product_family": product_family,
            "observed_machine_units": observed_machine_units,
            "territory_machine_units": territory_machine_units,
            "recorded_at": recorded_at,
            "kind": kind,
        },
        _rv(headers),
    )
    return get_success_data(resp, expected_status=201)


# ─── Certification (record-returning spelling) ────────

def create_certification_record(dealer,
                                technician_name,
                                certified_at="2026-08-01T00:00:00Z",
                                product_family="EXCAVATION",
                                credential_code="DEALER_CERTIFIED",
                                headers=None):
    return register_technician(
        dealer, technician_name, product_family=product_family,
        credential_code=credential_code, certified_at=certified_at, headers=headers,
    )


def list_certifications(headers=None, params=None):
    resp = api_client.list_certifications(_pm(headers), params=params)
    return get_success_data(resp)


# ─── Equipment orders (entity-backed DealerSalesManager) ─

def create_equipment_order(dealer,
                           machine_serial="SN-6100",
                           product_family="EXCAVATION",
                           list_price_cents=50000000,
                           trade_in_serial=None,
                           requested_at="2026-08-20T00:00:00Z"):
    payload = {
        "dealer_id": dealer["id"],
        "product_family": product_family,
        "machine_serial": machine_serial,
        "list_price_cents": list_price_cents,
        "requested_at": requested_at,
    }
    if trade_in_serial is not None:
        payload["trade_in_serial"] = trade_in_serial
    resp = api_client.create_equipment_order(
        payload, make_sales_manager_headers(dealer["id"]),
    )
    return get_success_data(resp, expected_status=201)


def submit_equipment_order(dealer, order_id):
    resp = api_client.submit_equipment_order(
        order_id, make_sales_manager_headers(dealer["id"]),
    )
    return get_success_data(resp)


def approve_equipment_financing(order_id, reference="OEM-FIN-2201"):
    resp = api_client.approve_equipment_financing(
        order_id, {"financing_approval_reference": reference},
        finance_partner_headers(),
    )
    return get_success_data(resp)


# ─── Rebuild claims ───────────────────────────────────

def create_rebuild_claim(dealer,
                         dealer_id=None,
                         product_family="EXCAVATION",
                         machine_serial="SN-7001",
                         machine_operating_weight_lb=90000,
                         client_meter_hours=3000,
                         requested_at="2026-08-20T00:00:00Z",
                         core_purchase_value_cents=4000000,
                         rebuild_labor_hours=10.0,
                         rebuild_labor_rate_cents=14000,
                         certified_rebuild_spec_code="CAT_CERTIFIED_2",
                         ensure_population=True,
                         headers=None):
    # PRD §3.7: "The machine serial must be live in the dealer's active
    # population before a claim can be tied to it."  Every claim fixture must
    # therefore stand up the population row the PRD precondition requires.
    target_dealer_id = dealer_id or dealer["id"]
    if ensure_population:
        from prd_bench_local_runner.testing import get_success_data as _ok
        existing = _ok(api_client.list_population_records(
            _pm(headers),
            params={"dealer_id": target_dealer_id, "machine_serial": machine_serial},
        ))
        if not any(r["status"] == "ACTIVE" for r in existing):
            create_population_record(
                {"id": target_dealer_id},
                machine_serial,
                product_family=product_family,
                machine_operating_weight_lb=machine_operating_weight_lb,
                headers=headers,
            )
    payload = {
        "dealer_id": target_dealer_id,
        "product_family": product_family,
        "machine_serial": machine_serial,
        "machine_operating_weight_lb": machine_operating_weight_lb,
        "client_meter_hours": client_meter_hours,
        "requested_at": requested_at,
        "core_purchase_value_cents": core_purchase_value_cents,
        "rebuild_labor_hours": rebuild_labor_hours,
        "rebuild_labor_rate_cents": rebuild_labor_rate_cents,
        "certified_rebuild_spec_code": certified_rebuild_spec_code,
    }
    resp = api_client.create_rebuild_claim(payload, _rs(headers))
    return get_success_data(resp, expected_status=201)


def get_rebuild_claim(claim_id, headers=None):
    resp = api_client.get_rebuild_claim(claim_id, _rs(headers))
    return get_success_data(resp)


def deliver_equipment_order(dealer, order_id):
    resp = api_client.deliver_equipment_order(
        order_id, make_sales_manager_headers(dealer["id"]),
    )
    return get_success_data(resp)


def get_equipment_order(order_id):
    resp = api_client.get_equipment_order(order_id, network_manager_headers())
    return get_success_data(resp)


def setup_equipment_order_in_state(dealer, target_state, **kwargs):
    """Walk an equipment order to DRAFT, SUBMITTED or FINANCE_APPROVED."""
    order = create_equipment_order(dealer, **kwargs)
    if target_state == "DRAFT":
        return order
    order = submit_equipment_order(dealer, order["id"])
    if target_state == "SUBMITTED":
        return order
    approve_equipment_financing(order["id"])
    return get_equipment_order(order["id"])


# ─── Ownership-scoped reads ───────────────────────────

def input_dealer_headers(dealer_id):
    """The read-only dealer principal, scoped to the given dealer's own rows."""
    return make_input_dealer_headers(dealer_id)


def sales_manager_headers(dealer_id):
    return make_sales_manager_headers(dealer_id)


__all__ = [
    "network_manager_headers", "reviewer_headers", "parts_manager_headers",
    "rebuild_specialist_headers", "technician_supervisor_headers",
    "finance_partner_headers", "set_clock", "create_dealer", "get_dealer",
    "dealer_version", "create_agreement", "get_agreement", "agreement_version",
    "submit_agreement", "activate_agreement", "register_technician",
    "register_technicians", "create_commitment", "get_commitment",
    "submit_commitment", "ready_commitment_for_orders", "reinstate_commitment",
    "suspend_commitment", "suspend_commitment_core_credit",
    "settle_commitment_core_credit", "create_agreement_for_family",
    "setup_dealer_with_agreement", "setup_submitted_commitment",
    "setup_commitment_order_ready", "setup_active_agreement_order_ready_commitment",
    "setup_performance_deficient_commitment", "create_batch", "get_batch",
    "place_batch_order", "receive_batch", "batch_core_return",
    "cancel_batch_core_return", "return_batch_core", "create_received_batch",
    "create_population_record", "get_population_record", "retire_population_record",
    "get_forecast", "get_sweep_metrics", "create_support_agreement", "get_support_agreement",
    "create_service_order", "get_service_order", "get_certification",
    "list_certifications", "create_equipment_order", "submit_equipment_order",
    "approve_equipment_financing", "deliver_equipment_order", "get_equipment_order",
    "setup_equipment_order_in_state", "input_dealer_headers", "sales_manager_headers",
    "create_rebuild_claim", "get_rebuild_claim",
    "create_review", "get_review", "record_review_results", "create_observation",
    "create_certification_record", "link_certification_to_agreement",
    "setup_core_return_round_trip",
]