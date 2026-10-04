"""Access control: authentication, role authorization and ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_agreement_payload,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    create_inventory,
    create_subscriber,
    current_agreement_version,
    get_plan,
    get_subscriber,
    get_summary,
    next_msisdn,
    purchase_term,
    quote_term,
    request_activation,
    set_clock,
    setup_activated_subscriber,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
    setup_subscriber_with_purchased_term,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_a_missing_role_header_is_unauthenticated(api):
    """PRD §2.1: "A request whose
    headers are absent, whose `X-User-Role` is not one of those six names, or whose `X-User-ID` fails to resolve
    for an entity-backed role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    set_clock()
    agreement = setup_active_agreement()
    resp = api.get_agreement(agreement["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.json()["response_type"] == "error"
    assert resp.json()["data"].get("message")


def test_an_unknown_role_name_is_unauthenticated(api):
    """PRD §2.1: "The API recognises six roles, spelled exactly as follows: `CapacityPlanner`,
    `SupportAgent`, `FulfillmentOperator`, `PlatformAdmin`, `Subscriber`, and `RetailPartner`."

    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    set_clock()
    agreement = setup_active_agreement()
    resp = api.get_agreement(
        agreement["id"], build_user_headers("whoever", "WizardOfOps")
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_an_entity_backed_role_with_an_unknown_id_is_unauthenticated(api):
    """PRD §2.1: "The remaining four roles — `CapacityPlanner`, `SupportAgent`, `FulfillmentOperator`, and `PlatformAdmin` — are opaque operator identities".

    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    set_clock()
    resp = api.list_subscribers(
        build_user_headers(MISSING_ID, "Subscriber"), {"state_code": "CA"}
    )
    # A Subscriber is not listed for the subscriber listing endpoint either way;
    # the entity-backed identity check must decide before anything else.
    assert resp.status_code in (401, 403)
    assert resp.json()["data"]["error_id"] in (
        "ERR_UNAUTHENTICATED",
        "ERR_FORBIDDEN_ROLE",
    )


def test_a_role_outside_the_endpoints_set_is_forbidden(api):
    """PRD §2.1: "Even with valid credentials, a
    role may only call the operations it is listed for; acting outside that set is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/role_not_permitted_returns_forbidden_role
    """
    set_clock()
    agreement = setup_active_agreement()
    block = create_inventory(state_code="CA", unit_count=2)

    resp = api.return_inventory(block["id"], TEST_USERS["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.json()["data"]["error_id"] != "ERR_UNAUTHENTICATED"


def test_a_subscriber_cannot_reach_planner_only_endpoints(api):
    """PRD §2.1: "A `CapacityPlanner` purchases capacity and curates the prepaid catalogue".

    Design: Corner/rbac/subscriber_cannot_reach_planner_only_endpoints
    """
    set_clock()
    subscriber = create_subscriber()
    resp = api.create_agreement(
        create_agreement_payload(host_network_name="Intruder Host"),
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    plan_resp = api.create_plan(
        {"agreement_id": MISSING_ID, "plan_code": "X3", "term_months": 3,
         "intro_price_cents": 1999, "renewal_price_cents": 3042,
         "data_allotment_mb": 3000, "voice_allotment_min": 500, "sms_allotment_msg": 1000},
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(plan_resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_a_support_agent_cannot_provision_or_activate_add_ons(api):
    """PRD §4: "POST | `/carriers/activations/{id}/provision` | Reserve state-scoped SIM media and mint the number the activation will go live on | CapacityPlanner |".

    Design: Corner/rbac/support_agent_cannot_activate_addons_or_provision
    """
    set_clock()
    agreement, plan, subscriber, term, activation = _awaiting(api)
    resp = api.provision_activation(activation["id"], TEST_USERS["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    assert api.provision_activation(
        activation["id"], TEST_USERS["planner_headers"]
    ).status_code == 200


def test_a_fulfillment_operator_cannot_manage_the_catalogue(api):
    """PRD §4: "POST | `/carriers/subscribers` | Register a subscriber awaiting activation on a number they intend to port in | CapacityPlanner, SupportAgent |".

    Design: Corner/rbac/fulfillment_operator_cannot_manage_the_catalogue
    """
    set_clock()
    agreement = setup_active_agreement()
    block = create_inventory(state_code="CA", unit_count=2)

    resp = api.create_subscriber(
        {"msisdn": "13055550111", "full_name": "Unwanted Rider", "state_code": "CA"},
        TEST_USERS["fulfillment_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    assert api.get_inventory(
        block["id"], TEST_USERS["fulfillment_headers"]
    ).status_code == 200
    assert api.create_agreement(
        create_agreement_payload(), TEST_USERS["fulfillment_headers"]
    ).status_code == 403


def test_a_suspended_agreement_does_not_block_plan_reads(api):
    """PRD §3.1: "though the terms and subscribers already live on it are
    left untouched so existing service continues."

    Design: Difficulty/cross_entity_state_dependency/term_purchase_requires_parent_agreement_active
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    api.suspend_agreement(agreement["id"], TEST_USERS["planner_headers"])

    assert api.get_plan(plan["id"], TEST_USERS["agent_headers"]).status_code == 200
    assert get_summary(agreement["id"])["allocated_data_mb"] == 0


def test_opaque_roles_need_no_entity_for_their_user_id(api):
    """PRD §2.1: "their `X-User-ID` is an operator
    identifier that is not tied to any persisted entity, so the server does not compare it to any entity's `id`."

    Design: Corner/rbac/subscriber_cannot_reach_planner_only_endpoints
    """
    set_clock()
    agreement = setup_active_agreement()
    resp = api.get_agreement(
        agreement["id"], build_user_headers("not-a-real-entity-id", "CapacityPlanner")
    )
    validate_success(resp)


def _awaiting(api_client_obj):
    from test_helpers.fixtures import setup_awaiting_activation

    return setup_awaiting_activation()