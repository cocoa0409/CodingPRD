"""Composite setup builders shared by the test suite.

Every builder drives the public API only and uses ``get_success_data`` so a
failed setup step surfaces as a clear "Setup failed" assertion rather than a
confusing downstream error. The logical clock reads 2026-09-01T00:00:00Z at
startup (PRD §2.5), so builders that do not move the clock implicitly run on
that date; builders that need another instant call ``set_clock`` explicitly.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from . import factories as f
from .constants import (
    CLOCK_INITIAL_INSTANT,
    EVENT_EARN,
    FORMAT_LICENSED,
    INSPECTOR_P,
    INSPECTOR_Q,
    INSPECTOR_A,
)
from .test_users import (
    TEST_USERS,
    make_licensee_manager_headers,
    make_host_venue_manager_headers,
    make_distributor_agent_headers,
    make_loyalty_member_headers,  # noqa: F401  (re-exported for tests)
    make_inspector_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_fail(step, response):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {response.status_code}: {response.text}"
    )


def _ok(response, step):
    if response.status_code // 100 != 2:
        _setup_fail(step, response)
    return get_success_data(response)


# ─── logical clock ────────────────────────────────────────────────────────


def set_clock(to_iso8601=CLOCK_INITIAL_INSTANT):
    """Move the logical clock; returns the instant it now reads."""
    _ok(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), "set_clock")
    return to_iso8601


# ─── participant registration ─────────────────────────────────────────────


def create_licensee(**overrides):
    return _ok(api_client.create_licensee(f.create_licensee_payload(**overrides), ADMIN),
               "create_licensee")


def create_venue(**overrides):
    return _ok(api_client.create_host_venue(f.create_host_venue_payload(**overrides), ADMIN),
               "create_venue")


# ─── agreement lifecycle ──────────────────────────────────────────────────


def create_draft_agreement(licensee_id, venue_id, **overrides):
    """Create an agreement in DRAFT. Returns the agreement dict."""
    payload = f.create_license_agreement_payload(licensee_id, venue_id, **overrides)
    return _ok(api_client.create_license_agreement(payload, ADMIN), "create_agreement")


def activate_agreement(agreement):
    """DRAFT -> PENDING_ACCEPTANCE -> ACTIVE. Returns the refreshed agreement."""
    _ok(api_client.submit_license_agreement(agreement["id"], ADMIN), "submit_agreement")
    venue_headers = make_host_venue_manager_headers(agreement["venue_id"])
    _ok(api_client.accept_license_agreement(agreement["id"], venue_headers),
        "accept_agreement")
    return _ok(api_client.get_license_agreement(agreement["id"], ADMIN), "get_agreement")


def create_active_agreement(licensee_id=None, venue_id=None, **overrides):
    """Licensee + venue (created when not supplied) + ACTIVE agreement.

    Returns a dict with licensee, venue, and agreement entries.
    """
    licensee = create_licensee() if licensee_id is None else None
    lic_id = licensee["id"] if licensee else licensee_id
    venue = create_venue() if venue_id is None else None
    ven_id = venue["id"] if venue else venue_id
    agreement = create_draft_agreement(lic_id, ven_id, **overrides)
    agreement = activate_agreement(agreement)
    return {"licensee_id": lic_id, "venue_id": ven_id, "agreement": agreement,
            "licensee": licensee, "venue": venue}


# Alias kept for readability at call sites that only need the bundle.
setup_active_agreement = create_active_agreement

# Payload factories re-exported here so tests may import them from either
# test_helpers.factories or test_helpers.fixtures.
from .factories import (  # noqa: E402,F401
    create_sales_report_payload,
    create_royalty_statement_payload,
)


# ─── staffing and certification ───────────────────────────────────────────


def create_employee(licensee_id, **overrides):
    headers = make_licensee_manager_headers(licensee_id)
    return _ok(api_client.create_employee(licensee_id, f.create_employee_payload(**overrides),
                                          headers), "create_employee")


def certify_employee(licensee_id, employee_id, exam_score=90, proctor=INSPECTOR_P,
                     auditor=INSPECTOR_Q):
    """Enroll + record a passing exam + audit-verify. Requires an ACTIVE
    agreement to exist for the employee's licensee. Returns the certification."""
    headers = make_licensee_manager_headers(licensee_id)
    cert = _ok(api_client.create_certification(employee_id, f.create_certification_payload(),
                                               headers), "create_certification")
    _ok(api_client.record_certification_exam(
        cert["id"], {"exam_score": exam_score, "proctor_anomaly": False},
        make_inspector_headers(proctor)), "record_exam")
    _ok(api_client.audit_verify_certification(cert["id"], make_inspector_headers(auditor)),
        "audit_verify")
    return _ok(api_client.get_certification(cert["id"], ADMIN), "get_certification")


def certify_baristas(licensee_id, count=2, **kwargs):
    """Hire and fully certify ``count`` BARISTA employees. Returns their ids."""
    employee_ids = []
    for _ in range(count):
        emp = create_employee(licensee_id, role_tag="BARISTA")
        certify_employee(licensee_id, emp["id"], **kwargs)
        employee_ids.append(emp["id"])
    return employee_ids


# ─── stores ───────────────────────────────────────────────────────────────


def create_store(agreement_id, licensee_id, **overrides):
    headers = make_licensee_manager_headers(licensee_id)
    return _ok(api_client.create_store(agreement_id, f.create_store_payload(**overrides),
                                       headers), "create_store")


def open_store(store, licensee_id):
    """PROVISIONING -> CERT_PENDING -> OPERATING. Assumes the staffing floor is
    already met. Returns the refreshed store."""
    headers = make_licensee_manager_headers(licensee_id)
    _ok(api_client.request_store_certification(store["id"], headers), "request_certification")
    _ok(api_client.begin_store_operations(store["id"], headers), "begin_operations")
    return _ok(api_client.get_store(store["id"], ADMIN), "get_store")


def setup_operating_store(**overrides):
    """The workhorse fixture: ACTIVE agreement + one OPERATING store with two
    CERTIFIED baristas.

    Returns a dict: licensee_id, venue_id, agreement, store.
    """
    bundle = create_active_agreement(**overrides.pop("agreement_overrides", {}))
    lic_id = bundle["licensee_id"]
    certify_baristas(lic_id, count=2)
    store = create_store(bundle["agreement"]["id"], lic_id, **overrides)
    store = open_store(store, lic_id)
    return {
        "licensee_id": lic_id,
        "venue_id": bundle["venue_id"],
        "agreement": bundle["agreement"],
        "store": store,
    }


def setup_cert_pending_store(**overrides):
    """ACTIVE agreement + store walked to CERT_PENDING only (staffing floor not
    met; begin-operations NOT called). Returns dict: licensee_id, venue_id,
    agreement, store."""
    bundle = create_active_agreement(**overrides.pop("agreement_overrides", {}))
    lic_id = bundle["licensee_id"]
    store = create_store(bundle["agreement"]["id"], lic_id, **overrides)
    headers = make_licensee_manager_headers(lic_id)
    _ok(api_client.request_store_certification(store["id"], headers), "request_certification")
    store = _ok(api_client.get_store(store["id"], ADMIN), "get_store")
    return {
        "licensee_id": lic_id,
        "venue_id": bundle["venue_id"],
        "agreement": bundle["agreement"],
        "store": store,
    }


# ─── catalog, assortment, distributors ────────────────────────────────────


def create_product(**overrides):
    return _ok(api_client.create_product_item(f.create_product_item_payload(**overrides),
                                              ADMIN), "create_product")


def add_assortment_item(store_id, licensee_id, product_item_id, **overrides):
    headers = make_licensee_manager_headers(licensee_id)
    payload = f.create_assortment_item_payload(product_item_id, **overrides)
    return _ok(api_client.create_assortment_item(store_id, payload, headers),
               "create_assortment_item")


def create_approved_distributor(**overrides):
    distributor = _ok(api_client.create_distributor(f.create_distributor_payload(**overrides),
                                                    ADMIN), "create_distributor")
    _ok(api_client.update_distributor(distributor["id"], {"approved": True}, ADMIN),
        "approve_distributor")
    return _ok(api_client.get_distributor(distributor["id"], ADMIN), "get_distributor")


# ─── supply orders ────────────────────────────────────────────────────────


def create_supply_order(store_id, licensee_id, distributor_id, lines=None, **overrides):
    """Create a DRAFT supply order with explicit lines by default."""
    headers = make_licensee_manager_headers(licensee_id)
    payload = f.create_supply_order_payload(distributor_id, **overrides)
    if lines is not None:
        payload["lines"] = lines
    return _ok(api_client.create_supply_order(store_id, payload, headers),
               "create_supply_order")


def drive_order_to_submitted(order, licensee_id):
    headers = make_licensee_manager_headers(licensee_id)
    _ok(api_client.submit_supply_order(order["id"], headers), "submit_order")
    return _ok(api_client.get_supply_order(order["id"], ADMIN), "get_order")


def drive_order_to_in_transit(order, licensee_id):
    """DRAFT -> SUBMITTED -> APPROVED -> IN_TRANSIT."""
    order = drive_order_to_submitted(order, licensee_id)
    agent = make_distributor_agent_headers(order["distributor_id"])
    _ok(api_client.approve_supply_order(order["id"], agent), "approve_order")
    _ok(api_client.ship_supply_order(order["id"], agent), "ship_order")
    return _ok(api_client.get_supply_order(order["id"], ADMIN), "get_order")


def drive_order_to_received(order, licensee_id, received_lines):
    """... -> IN_TRANSIT -> RECEIVED with the given received quantities."""
    order = drive_order_to_in_transit(order, licensee_id)
    headers = make_licensee_manager_headers(licensee_id)
    _ok(api_client.receive_supply_order(order["id"], {"received_lines": received_lines},
                                        headers), "receive_order")
    return _ok(api_client.get_supply_order(order["id"], ADMIN), "get_order")


def drive_order_to_disputed(order, licensee_id, received_lines, reason="shortage"):
    order = drive_order_to_received(order, licensee_id, received_lines)
    headers = make_licensee_manager_headers(licensee_id)
    _ok(api_client.dispute_supply_order(order["id"], {"reason": reason}, headers),
        "dispute_order")
    return _ok(api_client.get_supply_order(order["id"], ADMIN), "get_order")


def setup_store_with_supply(order_qty=10, unit_cost_cents=500, case_pack_units=1,
                            par_level=50, footprint_units=0):
    """OPERATING store + one assorted product + approved distributor + one
    DRAFT order of ``order_qty`` units. Returns a dict with all pieces."""
    bundle = setup_operating_store()
    product = create_product(unit_cost_cents=unit_cost_cents,
                             case_pack_units=case_pack_units,
                             footprint_units=footprint_units)
    assortment = add_assortment_item(bundle["store"]["id"], bundle["licensee_id"],
                                     product["id"], par_level=par_level)
    distributor = create_approved_distributor()
    order = create_supply_order(bundle["store"]["id"], bundle["licensee_id"],
                                distributor["id"],
                                lines=[{"product_item_id": product["id"],
                                        "quantity": order_qty}])
    bundle.update({"product": product, "assortment": assortment,
                   "distributor": distributor, "order": order})
    return bundle


def list_order_lines(order_id):
    """List the lines of one order (admin view). Returns (rows, meta)."""
    return validate_paginated(
        api_client.list_supply_order_lines(ADMIN, params={"supply_order_id": order_id}))


# ─── inspections and corrective actions ───────────────────────────────────


def schedule_inspection(store_id, inspector=INSPECTOR_A, start="2026-09-02T10:00:00Z",
                        end="2026-09-02T11:00:00Z"):
    payload = f.create_inspection_payload(scheduled_start_utc=start, scheduled_end_utc=end)
    return _ok(api_client.create_inspection(store_id, payload,
                                            make_inspector_headers(inspector)),
               "schedule_inspection")


def complete_inspection(inspection_id, scores, critical_fail=False,
                        inspector=INSPECTOR_A):
    """Complete a SCHEDULED inspection. ``scores`` maps category -> score;
    the PRD's `category_scores` is an object keyed by category name."""
    return _ok(api_client.complete_inspection(
        inspection_id, {"category_scores": dict(scores), "critical_fail": critical_fail},
        make_inspector_headers(inspector)), "complete_inspection")


def list_corrective_actions_for_inspection(inspection_id):
    response = api_client.list_corrective_actions(ADMIN, params={"inspection_id": inspection_id})
    body = response.json()
    assert response.status_code == 200, f"Setup failed listing corrective actions: {response.text}"
    return body["data"]


def setup_failed_inspection(failing_categories, non_failing_score=90, failing_score=60):
    """OPERATING store + one inspection completed FAILED (no critical flag)
    with exactly ``len(failing_categories)`` categories below 70.

    Returns (bundle, inspection, corrective_actions).
    """
    scores = {cat: non_failing_score for cat in
              ("BEVERAGE_QUALITY", "FOOD_SAFETY", "BRAND_PRESENTATION", "SERVICE_SPEED")}
    for cat in failing_categories:
        scores[cat] = failing_score
    bundle = setup_operating_store()
    inspection = schedule_inspection(bundle["store"]["id"])
    complete_inspection(inspection["id"], scores, critical_fail=False)
    inspection = _ok(api_client.get_inspection(inspection["id"], ADMIN), "get_inspection")
    actions = list_corrective_actions_for_inspection(inspection["id"])
    return bundle, inspection, actions


# ─── loyalty ──────────────────────────────────────────────────────────────


def create_member(**overrides):
    return _ok(api_client.create_loyalty_member(f.create_loyalty_member_payload(**overrides),
                                                ADMIN), "create_member")


def post_loyalty_event(member_id, caller_headers, **payload):
    return api_client.create_loyalty_event(member_id, payload, caller_headers)


def earn_at_store(member_id, store_id, licensee_id, purchase_cents):
    """Post a LICENSED EARN event as the licensee; returns the event data."""
    response = post_loyalty_event(
        member_id, make_licensee_manager_headers(licensee_id),
        event_type=EVENT_EARN, store_format=FORMAT_LICENSED,
        store_id=store_id, purchase_cents=purchase_cents)
    return _ok(response, "earn_event")


# ─── sales reports and royalty statements ─────────────────────────────────


def create_sales_report(store_id, licensee_id, **overrides):
    headers = make_licensee_manager_headers(licensee_id)
    return _ok(api_client.create_sales_report(store_id, f.create_sales_report_payload(**overrides),
                                              headers), "create_sales_report")


def finalize_sales_report(report_id, licensee_id):
    headers = make_licensee_manager_headers(licensee_id)
    _ok(api_client.finalize_sales_report(report_id, headers), "finalize_sales_report")
    return _ok(api_client.get_sales_report(report_id, ADMIN), "get_sales_report")


def agreement_version(agreement_id):
    return _ok(api_client.get_license_agreement(agreement_id, ADMIN), "get_agreement")["version"]


def generate_statement(agreement_id, **overrides):
    """Generate a DRAFT royalty statement with the agreement's CURRENT version."""
    payload = f.create_royalty_statement_payload(agreement_version(agreement_id), **overrides)
    return _ok(api_client.create_royalty_statement(agreement_id, payload, ADMIN),
               "generate_statement")


# ─── campaigns ────────────────────────────────────────────────────────────


def create_campaign(store_id, **overrides):
    return _ok(api_client.create_promotion_campaign(
        store_id, f.create_promotion_campaign_payload(**overrides), ADMIN), "create_campaign")
