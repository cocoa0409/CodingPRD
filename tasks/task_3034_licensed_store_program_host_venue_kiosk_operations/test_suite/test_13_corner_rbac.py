"""Corner design — section: rbac."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_loyalty_member_payload,
    create_product_item_payload,
)
from test_helpers.fixtures import (
    activate_agreement,
    add_assortment_item,
    create_approved_distributor,
    create_draft_agreement,
    create_licensee,
    create_product,
    create_store,
    create_supply_order,
    create_venue,
    drive_order_to_submitted,
)
from test_helpers.test_users import (
    make_distributor_agent_headers,
    make_licensee_manager_headers,
    make_loyalty_member_headers,
)


def test_licensee_manager_cannot_create_product():
    """PRD §2.1: "Once authentication succeeds, every endpoint enforces its
    authorized-role list; an authenticated user whose role is not on the list
    receives `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/licensee_manager_cannot_create_product
    """
    licensee = create_licensee()
    resp = api_client.create_product_item(
        create_product_item_payload(sku="SKU-X", name="X", unit_cost_cents=100),
        make_licensee_manager_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_licensee_manager_cannot_touch_other_licensees_store():
    """PRD §2.1: "When `X-User-Role` is `LicenseeManager`, `X-User-ID` is the
    `id` of the acting `Licensee`; ownership checks on any resource traceable
    to a licensee — a store reached through its agreement, an employee, a
    supply order reached through its store and agreement, a sales report
    through its store, an assortment item through its store, or a certification
    through its employee — compare that chain's `licensee_id` to `X-User-ID`,
    and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/licensee_manager_cannot_touch_other_licensees_store
    """
    set_clock()
    licensee_a = create_licensee()
    licensee_b = create_licensee()
    venue = create_venue()
    agreement = activate_agreement(
        create_draft_agreement(licensee_b["id"], venue["id"]))
    store = create_store(agreement["id"], licensee_b["id"],
                         store_code="ST1", equipment_footprint_units=40)
    resp = api_client.request_store_certification(
        store["id"], make_licensee_manager_headers(licensee_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    store = validate_success(api_client.get_store(store["id"], ADMIN))
    assert store["operating_status"] == "PROVISIONING"


def test_distributor_agent_cannot_act_on_other_distributors_order():
    """PRD §2.1: "When `X-User-Role` is `DistributorAgent`, `X-User-ID` is the
    `id` of the acting `Distributor`; order-side operations compare it against
    the order's `distributor_id` and a mismatch is rejected with
    `ERR_DISTRIBUTOR_MISMATCH`."

    Design: Corner/rbac/distributor_agent_cannot_act_on_other_distributors_order
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product()
    add_assortment_item(store_id, lic_id, product["id"], par_level=50)
    distributor_1 = create_approved_distributor()
    distributor_2 = create_approved_distributor()
    order = create_supply_order(
        store_id, lic_id, distributor_1["id"],
        lines=[{"product_item_id": product["id"], "quantity": 10}])
    order = drive_order_to_submitted(order, lic_id)
    resp = api_client.approve_supply_order(
        order["id"], make_distributor_agent_headers(distributor_2["id"]))
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_MISMATCH.value)
    order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
    assert order["status"] == "SUBMITTED"


def test_loyalty_member_reads_only_self():
    """PRD §2.1: "When `X-User-Role` is `LoyaltyMember`, `X-User-ID` is the
    `id` of the acting `LoyaltyMember`; members may read only their own record
    and their own events."

    Design: Corner/rbac/loyalty_member_reads_only_self
    """
    member_a = validate_success(api_client.create_loyalty_member(
        create_loyalty_member_payload(email="self@x.com"), ADMIN), expected_status=201)
    member_b = validate_success(api_client.create_loyalty_member(
        create_loyalty_member_payload(email="other@x.com"), ADMIN), expected_status=201)
    resp = api_client.get_loyalty_member(
        member_b["id"], make_loyalty_member_headers(member_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    own = validate_success(api_client.get_loyalty_member(
        member_a["id"], make_loyalty_member_headers(member_a["id"])))
    assert own["email"] == "self@x.com"
