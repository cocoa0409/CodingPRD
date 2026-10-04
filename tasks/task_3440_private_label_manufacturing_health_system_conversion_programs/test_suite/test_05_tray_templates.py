"""Tray templates: change-management cycle, SoD, ownership, OCC, gate order."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_tray_template,
    create_facility,
    create_product,
    create_tray_template,
    decide_tray_approval,
    get_success_data,
    make_admin_headers,
    make_facility_director_headers,
    propose_tray_change,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _components(product_id, qty=1):
    return [{"product_id": product_id, "quantity": qty}]


def test_tray_approval_from_draft_409(api):
    """PRD §3.4: "A `SupplyChainAdmin` records the approval decision on a
    `PENDING_APPROVAL` template — any other state is `ERR_INVALID_STATE`".
    PRD §3.4: "A new template starts in `DRAFT` status with `proposed_by`,
    `approved_version`, and `approved_by` all null."

    Design: Corner/state_machines/tray_approval_decision_from_draft_rejected
    """
    facility = create_facility()
    comp = create_product(sku="AD-1", sterile=True, category="SURGICAL_INSTRUMENTS",
                          device_class="CLASS_II")
    tray = create_tray_template(facility["id"], _components(comp["id"]))
    assert tray["status"] == "DRAFT"
    resp = api.record_approval_decision(
        tray["id"], {"decision": "APPROVE"}, make_admin_headers("admin-2")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = get_success_data(api.get_tray_template(tray["id"], ADMIN))
    assert reread["status"] == "DRAFT"
    assert reread.get("approved_version") is None


def test_duplicate_tray_component_409(api):
    """PRD §3.4: "no `product_id` may repeat within the `components` array (a
    duplicate is rejected with `ERR_DUPLICATE_COMPONENT`, HTTP 409)".

    Design: Corner/validations/duplicate_tray_component_rejected
    """
    facility = create_facility()
    comp = create_product(sku="DC-1", sterile=True, category="SURGICAL_INSTRUMENTS",
                          device_class="CLASS_II")
    resp = api.create_tray_template(
        {
            "facility_id": facility["id"],
            "name": "Dup tray",
            "procedure_type": "GENERAL",
            "sterile_assembly": False,
            "components": [
                {"product_id": comp["id"], "quantity": 1},
                {"product_id": comp["id"], "quantity": 2},
            ],
        },
        headers=make_admin_headers("admin-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMPONENT.value, 409)


def test_sod_tray_self_approval_403(api):
    """PRD §3.4: "segregation of duties forbids self-approval: the acting admin's
    `X-User-ID` must differ from `proposed_by`, otherwise `ERR_SOD_SELF_APPROVAL`
    (HTTP 403)".

    Design: Corner/rbac/sod_tray_self_approval_rejected
    """
    facility = create_facility()
    comp = create_product(sku="RB4-C", sterile=True, category="SURGICAL_INSTRUMENTS",
                          device_class="CLASS_II")
    tray = create_tray_template(facility["id"], _components(comp["id"]), creator_id="admin-1")
    proposed = propose_tray_change(
        tray["id"], _components(comp["id"], 2), tray["version"], user_id="admin-1"
    )
    assert proposed["status"] == "PENDING_APPROVAL"
    resp = api.record_approval_decision(
        tray["id"], {"decision": "APPROVE"}, make_admin_headers("admin-1")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_SELF_APPROVAL.value, 403)
    approved = decide_tray_approval(tray["id"], "APPROVE", admin_id="admin-2")
    assert approved["status"] == "ACTIVE"


def test_facility_director_other_facility_tray_403(api):
    """PRD §2.1: "ownership checks on any resource that references a facility
    compare the resource's `facility_id` field to `X-User-ID`, and a mismatch is
    rejected with `ERR_FACILITY_MISMATCH` (HTTP 403)." PRD §3.4: "a proposing
    `FacilitySupplyDirector` passes the same facility-ownership check as at
    creation."

    Design: Corner/rbac/facility_director_cannot_touch_other_facility_tray
    """
    facility_a = create_facility(name="Fac A5")
    facility_b = create_facility(name="Fac B5")
    comp = create_product(sku="RB5-C", sterile=True, category="SURGICAL_INSTRUMENTS",
                          device_class="CLASS_II")
    tray_b = create_tray_template(facility_b["id"], _components(comp["id"]))
    resp = api.propose_tray_change(
        tray_b["id"],
        {
            "components": _components(comp["id"], 5),
            "expected_template_version": tray_b["version"],
        },
        headers=make_facility_director_headers(facility_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_MISMATCH.value, 403)
    reread = get_success_data(api.get_tray_template(tray_b["id"], ADMIN))
    assert reread["status"] == "DRAFT"
    assert reread["version"] == 1


def test_occ_tray_propose_stale_version_412(api):
    """PRD §3.4: "Proposals are optimistic-concurrency guarded by
    `expected_template_version` exactly as §2.7 describes — a stale version is
    rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/complexity_layers/occ_tray_propose_stale_version_rejected
    """
    facility = create_facility()
    comp = create_product(sku="OC-1", sterile=True, category="SURGICAL_INSTRUMENTS",
                          device_class="CLASS_II")
    tray = create_tray_template(facility["id"], _components(comp["id"]))
    proposed = propose_tray_change(
        tray["id"], _components(comp["id"], 2), tray["version"], user_id="admin-1"
    )
    assert proposed["version"] == 2
    resp = api.propose_tray_change(
        tray["id"],
        {
            "components": _components(comp["id"], 3),
            "expected_template_version": tray["version"],  # stale: version is 2
        },
        headers=make_admin_headers("admin-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
    reread = get_success_data(api.get_tray_template(tray["id"], ADMIN))
    assert reread["version"] == 2
    assert reread["components"] == [{"product_id": comp["id"], "quantity": 2}]


def test_tray_cycle_under_change_to_first_approval(api):
    """PRD §3.4: "A `REJECT` decision routes the template to `UNDER_CHANGE`,
    incrementing `version` by 1, from which a corrected proposal can be
    submitted to restart the cycle." PRD §3.4: "An `APPROVE` decision increments
    the template's `version` by 1 first, then sets `status` to `ACTIVE` and pins
    `approved_version` to that post-increment version — so `approved_version`
    records exactly which component set was approved".

    Design: Difficulty/non_linear_state_machine/tray_template_change_management_cycle
    """
    facility = create_facility()
    c1 = create_product(sku="TC-1", name="Scalpel", sterile=True,
                        category="SURGICAL_INSTRUMENTS", device_class="CLASS_II",
                        each_price_cents=500)
    c2 = create_product(sku="TC-2", name="Forceps", sterile=True,
                        category="SURGICAL_INSTRUMENTS", device_class="CLASS_II",
                        each_price_cents=300)
    tray = create_tray_template(
        facility["id"], _components(c1["id"]), creator_id="admin-1",
        name="Laceration tray", procedure_type="LACERATION_REPAIR",
        sterile_assembly=True,
    )
    assert tray["version"] == 1 and tray["status"] == "DRAFT"
    proposed = propose_tray_change(
        tray["id"],
        [
            {"product_id": c1["id"], "quantity": 1},
            {"product_id": c2["id"], "quantity": 2},
        ],
        1,
        user_id="admin-1",
    )
    assert proposed["version"] == 2 and proposed["status"] == "PENDING_APPROVAL"
    rejected = decide_tray_approval(tray["id"], "REJECT", admin_id="admin-2")
    assert rejected["version"] == 3 and rejected["status"] == "UNDER_CHANGE"
    reproposed = propose_tray_change(
        tray["id"], _components(c2["id"], 3), 3, user_id="admin-1"
    )
    assert reproposed["version"] == 4 and reproposed["status"] == "PENDING_APPROVAL"
    approved = decide_tray_approval(tray["id"], "APPROVE", admin_id="admin-2")
    assert approved["version"] == 5
    assert approved["status"] == "ACTIVE"
    assert approved["approved_version"] == 5
    assert approved["approved_by"] == "admin-2"


def test_tray_cycle_second_approval_pins_version(api):
    """PRD §3.4: "Proposing a change — the same capability from `DRAFT`,
    `PENDING_APPROVAL`, `ACTIVE`, or `UNDER_CHANGE`, and invalid from any other
    state (`ERR_INVALID_STATE`) — replaces the template's `components` wholesale
    with the payload array and lands the template on `PENDING_APPROVAL`".
    PRD §3.4: "pins `approved_version` to that post-increment version".

    Design: Difficulty/non_linear_state_machine/tray_template_change_management_cycle
    """
    facility = create_facility()
    c1 = create_product(sku="TC-3", sterile=True, category="SURGICAL_INSTRUMENTS",
                        device_class="CLASS_II")
    c2 = create_product(sku="TC-4", sterile=True, category="SURGICAL_INSTRUMENTS",
                        device_class="CLASS_II")
    tray = create_tray_template(
        facility["id"], _components(c1["id"]), creator_id="admin-1",
        sterile_assembly=True,
    )
    propose_tray_change(
        tray["id"],
        [
            {"product_id": c1["id"], "quantity": 1},
            {"product_id": c2["id"], "quantity": 2},
        ],
        1,
        user_id="admin-1",
    )
    decide_tray_approval(tray["id"], "REJECT", admin_id="admin-2")
    propose_tray_change(tray["id"], _components(c2["id"], 3), 3, user_id="admin-1")
    first = decide_tray_approval(tray["id"], "APPROVE", admin_id="admin-2")
    assert first["version"] == 5 and first["approved_version"] == 5
    # Second change-management cycle: ACTIVE -> PENDING_APPROVAL -> ACTIVE.
    second_proposal = propose_tray_change(
        tray["id"], _components(c1["id"], 2), 5, user_id="admin-1"
    )
    assert second_proposal["version"] == 6
    assert second_proposal["status"] == "PENDING_APPROVAL"
    second = decide_tray_approval(tray["id"], "APPROVE", admin_id="admin-2")
    assert second["version"] == 7
    assert second["approved_version"] == 7
    reread = get_success_data(api.get_tray_template(tray["id"], ADMIN))
    assert_tray_template(reread)
    assert reread["status"] == "ACTIVE"
    assert reread["version"] == 7
    assert reread["approved_version"] == 7


def test_tray_safety_gate_beats_referential_gate(api):
    """PRD §2.6: "The server evaluates validation rules in a fixed priority order
    and reports only the first failure: the rule with the lower priority number
    wins." — safety and segregation guards (band 6) precede referential product
    rules (band 9). PRD §3.4: "when `sterile_assembly` is true, every component
    product must itself have `sterile` true (a non-sterile component is rejected
    with `ERR_STERILE_COMPONENT_REQUIRED`, HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/tray_safety_gate_beats_referential_gate
    """
    facility = create_facility()
    non_sterile = create_product(sku="NS-1", name="Basin", sterile=False,
                                 category="SURGICAL_INSTRUMENTS")
    discontinued = create_product(sku="DS-1", name="Retired kit", sterile=True,
                                  category="SURGICAL_INSTRUMENTS",
                                  availability="DISCONTINUED")
    resp = api.create_tray_template(
        {
            "facility_id": facility["id"],
            "name": "Mixed tray",
            "procedure_type": "GENERAL",
            "sterile_assembly": True,
            "components": [
                {"product_id": non_sterile["id"], "quantity": 1},
                {"product_id": discontinued["id"], "quantity": 1},
            ],
        },
        headers=make_admin_headers("admin-9"),
    )
    validate_error(resp, ApiErrorId.ERR_STERILE_COMPONENT_REQUIRED.value, 422)


def test_tray_safety_gate_does_not_report_orderability(api):
    """PRD §2.6: "The server evaluates validation rules in a fixed priority order
    and reports only the first failure: the rule with the lower priority number
    wins." PRD §3.4: "every referenced product's `availability` must be `ACTIVE`
    (a discontinued component is rejected with `ERR_PRODUCT_NOT_ORDERABLE`,
    HTTP 422)" — but the safety error outranks it when both fail.

    Design: Difficulty/priority_pair_validation_conflict/tray_safety_gate_beats_referential_gate
    """
    facility = create_facility()
    non_sterile = create_product(sku="NS-2", sterile=False,
                                 category="SURGICAL_INSTRUMENTS")
    discontinued = create_product(sku="DS-2", sterile=True,
                                  category="SURGICAL_INSTRUMENTS",
                                  availability="DISCONTINUED")
    resp = api.create_tray_template(
        {
            "facility_id": facility["id"],
            "name": "Mixed tray",
            "procedure_type": "GENERAL",
            "sterile_assembly": True,
            "components": [
                {"product_id": non_sterile["id"], "quantity": 1},
                {"product_id": discontinued["id"], "quantity": 1},
            ],
        },
        headers=make_admin_headers("admin-9"),
    )
    err = validate_error(resp, ApiErrorId.ERR_STERILE_COMPONENT_REQUIRED.value, 422)
    assert err["error_id"] != ApiErrorId.ERR_PRODUCT_NOT_ORDERABLE.value
