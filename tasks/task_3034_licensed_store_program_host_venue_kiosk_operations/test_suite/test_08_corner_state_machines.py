"""Corner design — section: state_machines."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_product,
    set_clock,
    setup_failed_inspection,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    activate_agreement,
    add_assortment_item,
    create_approved_distributor,
    create_draft_agreement,
    create_licensee,
    create_store,
    create_supply_order,
    create_venue,
    drive_order_to_submitted,
    schedule_inspection,
    complete_inspection,
    list_corrective_actions_for_inspection,
)
from test_helpers.test_users import make_licensee_manager_headers


def test_agreement_created_in_draft():
    """PRD §3.2: "The agreement is born with `status` `DRAFT` and
    `breach_strikes` at 0."

    Design: Corner/state_machines/agreement_created_in_draft
    """
    licensee = create_licensee()
    venue = create_venue()
    agreement = create_draft_agreement(licensee["id"], venue["id"])
    assert agreement["status"] == "DRAFT"
    assert agreement["breach_strikes"] == 0
    assert agreement["version"] == 1


def test_terminated_agreement_locks_all_transitions():
    """PRD §3.2: "`TERMINATED` and `EXPIRED` are terminal."

    Design: Corner/state_machines/terminated_agreement_locks_all_transitions
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue()
    agreement = activate_agreement(create_draft_agreement(licensee["id"], venue["id"]))
    validate_success(api_client.terminate_license_agreement(agreement["id"], ADMIN))
    resp = api_client.reinstate_license_agreement(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value)
    agreement = validate_success(api_client.get_license_agreement(agreement["id"], ADMIN))
    assert agreement["status"] == "TERMINATED"


def test_agreement_suspend_reinstate_cycle_resets_strikes():
    """PRD §3.2: "Reinstatement from `SUSPENDED` returns the agreement to
    `ACTIVE` and resets `breach_strikes` to 0, but pointedly does not wake the
    stores — each store stays `SUSPENDED` until the brand resumes it
    individually."

    Design: Corner/state_machines/agreement_suspend_reinstate_cycle_resets_strikes
    """
    set_clock()
    bundle = setup_operating_store()
    validate_success(api_client.suspend_license_agreement(bundle["agreement"]["id"], ADMIN))
    agreement = validate_success(
        api_client.reinstate_license_agreement(bundle["agreement"]["id"], ADMIN))
    assert agreement["status"] == "ACTIVE"
    assert agreement["breach_strikes"] == 0
    store = validate_success(api_client.get_store(bundle["store"]["id"], ADMIN))
    assert store["operating_status"] == "SUSPENDED"


def test_order_idempotent_second_submit_rejected():
    """PRD §3.5: "Any transition attempted from the wrong order state is
    `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/order_idempotent_second_submit_rejected
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product()
    add_assortment_item(store_id, lic_id, product["id"], par_level=50)
    distributor = create_approved_distributor()
    order = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 10}])
    order = drive_order_to_submitted(order, lic_id)
    assert order["status"] == "SUBMITTED"
    resp = api_client.submit_supply_order(order["id"], make_licensee_manager_headers(lic_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)
    order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
    assert order["status"] == "SUBMITTED"


def test_inspection_failed_creates_corrective_actions():
    """PRD §3.8: "It creates **CorrectiveActions**, each carrying its parent
    `inspection_id`: one with `finding_code` `CRITICAL` when the critical flag
    fired, otherwise one per category that scored below 70, each due exactly 14
    days after the completion timestamp."

    Design: Corner/state_machines/inspection_failed_creates_corrective_actions
    """
    set_clock()
    bundle = setup_operating_store()
    store_id = bundle["store"]["id"]
    inspection = schedule_inspection(store_id)
    completed = complete_inspection(
        inspection["id"],
        {"BEVERAGE_QUALITY": 60, "FOOD_SAFETY": 60,
         "BRAND_PRESENTATION": 90, "SERVICE_SPEED": 90},
    )
    # composite = (60*30 + 60*40 + 90*20 + 90*10)/100 = 6900/100 = 69
    assert completed["result"] == "FAILED"
    assert completed["total_score"] == 69
    actions = list_corrective_actions_for_inspection(inspection["id"])
    assert len(actions) == 2
    assert all(a["status"] == "OPEN" for a in actions)
    # PRD: due exactly 14 days after the completion timestamp; the logical
    # clock reads 2026-09-01T00:00:00Z (PRD §2.5), so due_at is 2026-09-15
    # 00:00:00 UTC regardless of how many fractional digits are rendered.
    assert all(a["due_at"].startswith("2026-09-15T00:00:00") for a in actions)
    store = validate_success(api_client.get_store(store_id, ADMIN))
    assert store["compliance_posture"] == "PROBATION"


def test_critical_fail_overrides_passing_score():
    """PRD §3.8: "The `result` is `FAILED` whenever `critical_fail` is set,
    regardless of score; otherwise `PASSED` when the composite reaches 85 — the
    boundary is inclusive, exactly 85 passes — else `FAILED`."

    Design: Corner/state_machines/critical_fail_overrides_passing_score
    """
    set_clock()
    bundle = setup_operating_store()
    store_id = bundle["store"]["id"]
    inspection = schedule_inspection(store_id)
    completed = complete_inspection(
        inspection["id"],
        {"BEVERAGE_QUALITY": 100, "FOOD_SAFETY": 100,
         "BRAND_PRESENTATION": 90, "SERVICE_SPEED": 80},
        critical_fail=True,
    )
    # composite = (100*30 + 100*40 + 90*20 + 80*10)/100 = 9600/100 = 96
    assert completed["total_score"] == 96
    assert completed["result"] == "FAILED"
    actions = list_corrective_actions_for_inspection(inspection["id"])
    assert len(actions) == 1
    assert actions[0]["finding_code"] == "CRITICAL"
