"""Optimistic concurrency, payload shape and entity-specific not-found codes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_subscriber_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers.fixtures import (
    cancel_port,
    create_addon,
    create_plan,
    create_subscriber,
    current_agreement_version,
    get_activation,
    get_agreement,
    get_subscriber,
    get_summary,
    next_msisdn,
    offer_plan,
    purchase_term,
    quote_term,
    set_clock,
    setup_activated_subscriber,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
    submit_port,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_a_stale_agreement_version_on_term_create_is_rejected(api):
    """PRD §3.5: "The agreement version expectation is mandatory here: if the agreement's
    `version` has advanced since the subscriber last read it — because another writer has just quoted or
    purchased a term and thereby recomputed the agreement's allocation — the quote is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/validations/stale_agreement_version_on_term_create_is_rejected
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    first = create_subscriber()
    stale = create_subscriber(msisdn="13055550071", full_name="Stale Writer")
    stale_version = current_agreement_version(agreement["id"])

    advance = quote_term(first["id"], plan["id"], stale_version)
    assert advance["term_status"] == "QUOTED"
    assert current_agreement_version(agreement["id"]) > stale_version

    resp = api.create_term(
        {
            "subscriber_id": stale["id"],
            "plan_id": plan["id"],
            "expected_CapacityAgreement_version": stale_version,
        },
        make_subscriber_headers(stale["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    terms = api.list_terms(
        TEST_USERS["planner_headers"], {"subscriber_id": stale["id"]}
    ).json()["data"]
    assert terms == []

    retried = api.create_term(
        {
            "subscriber_id": stale["id"],
            "plan_id": plan["id"],
            "expected_CapacityAgreement_version": current_agreement_version(
                agreement["id"]
            ),
        },
        make_subscriber_headers(stale["id"]),
    )
    validate_success(retried, expected_status=201)


def test_a_stale_subscriber_version_on_cancel_is_rejected(api):
    """PRD §3.3: "Cancelling a subscriber
    requires the acting `Subscriber` to own the resource — `X-User-ID` must equal the subscriber's `id` — and to
    carry `expected_Subscriber_version` matching the subscriber's current `version`; a stale expectation is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_subscriber_version_on_cancel_is_rejected
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    stale_version = get_subscriber(subscriber_id)["version"]

    api.run_cycle(subscriber_id, TEST_USERS["planner_headers"])
    assert get_subscriber(subscriber_id)["version"] > stale_version

    resp = api.cancel_subscriber(
        subscriber_id,
        make_subscriber_headers(subscriber_id),
        {"expected_Subscriber_version": stale_version},
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_subscriber(subscriber_id)["subscriber_status"] == "ACTIVE"

    current = get_subscriber(subscriber_id)
    retried = api.cancel_subscriber(
        subscriber_id,
        make_subscriber_headers(subscriber_id),
        {"expected_Subscriber_version": current["version"]},
    )
    validate_success(retried)
    assert get_subscriber(subscriber_id)["subscriber_status"] == "CHURNED"


def test_stale_version_uses_412_while_state_failures_use_409(api):
    """PRD §2.7: "When a client's expected value no longer matches the parent's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/errors/stale_version_code_is_412_not_409
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    first = create_subscriber()
    stale_version = current_agreement_version(agreement["id"])
    quote_term(first["id"], plan["id"], stale_version)

    second = create_subscriber(msisdn="13055550101", full_name="Stale Second")
    resp = api.create_term(
        {
            "subscriber_id": second["id"],
            "plan_id": plan["id"],
            "expected_CapacityAgreement_version": stale_version,
        },
        make_subscriber_headers(second["id"]),
    )
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.json()["data"].get("message")
    assert current_agreement_version(agreement["id"]) == stale_version + 1


def test_cancelling_an_already_cancelled_port_is_refused(api):
    """PRD §3.7: "a `Subscriber` may withdraw a submitted port: cancelling it sets `port_status` to `CANCELLED` and clears
    `held_data_mb`".

    Design: Corner/validations/cancel_on_an_already_cancelled_port_is_rejected
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    activation_id = setup["activation"]["id"]
    submit_port(activation_id, subscriber_id, "13055550001", last4="6001")
    cancel_port(activation_id, subscriber_id)

    first = get_activation(activation_id)
    assert first["port_status"] == "CANCELLED"
    assert first["held_data_mb"] == 0
    before = get_summary(setup["agreement"]["id"])["allocated_data_mb"]

    resp = api.cancel_port(activation_id, make_subscriber_headers(subscriber_id))
    assert resp.status_code == 409
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_PORT_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
    )
    assert get_summary(setup["agreement"]["id"])["allocated_data_mb"] == before


def test_an_unknown_field_and_a_missing_field_are_both_invalid_request(api):
    """PRD §2.11: "a request that supplies an unknown field, or omits a required one, is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/undefined_and_missing_payload_fields_are_rejected
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    missing_days = api.create_addon(
        {
            "subscriber_id": subscriber_id,
            "addon_type": "ROAMING",
            "per_day_allotment_mb": 500,
        },
        make_subscriber_headers(subscriber_id),
    )
    validate_error(missing_days, ApiErrorId.ERR_INVALID_REQUEST)

    unknown_field = api.create_addon(
        {
            "subscriber_id": subscriber_id,
            "addon_type": "ROAMING",
            "addon_days": 7,
            "per_day_allotment_mb": 500,
            "promotional_tier": "GOLD",
        },
        make_subscriber_headers(subscriber_id),
    )
    validate_error(unknown_field, ApiErrorId.ERR_INVALID_REQUEST)

    good = create_addon(subscriber_id, addon_type="ROAMING", addon_days=7,
                        per_day_allotment_mb=500)
    assert good["addon_status"] == "REQUESTED"


def test_every_resource_path_resolves_to_its_own_not_found_code(api):
    """PRD §2.9: "The same
    left-to-right discipline applies to foreign keys carried in a request body: those are checked in the order the
    fields appear in the endpoint's input list."

    Design: Corner/errors/not_found_codes_are_entity_specific
    """
    set_clock()
    pairs = [
        (api.get_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
        (api.get_subscriber, ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND),
        (api.get_term, ApiErrorId.ERR_TERM_NOT_FOUND),
        (api.get_activation, ApiErrorId.ERR_ACTIVATION_NOT_FOUND),
        (api.get_partner, ApiErrorId.ERR_PARTNER_NOT_FOUND),
    ]
    codes = []
    for call, expected in pairs:
        resp = call(MISSING_ID, TEST_USERS["planner_headers"])
        data = validate_error(resp, expected)
        codes.append(data["error_id"])
    assert len(set(codes)) == len(codes)


def test_lookups_of_unknown_media_and_case_shapes_are_distinct(api):
    """PRD §2.9: "a missing
    SIM inventory block `ERR_SIM_INVENTORY_NOT_FOUND`, a missing support case `ERR_CASE_NOT_FOUND`".

    Design: Corner/validations/fulfillment_lookup_of_an_unknown_shipment_shape_returns_not_found
    """
    set_clock()
    inventory_resp = api.get_inventory(MISSING_ID, TEST_USERS["fulfillment_headers"])
    validate_error(inventory_resp, ApiErrorId.ERR_SIM_INVENTORY_NOT_FOUND)

    case_resp = api.get_case(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(case_resp, ApiErrorId.ERR_CASE_NOT_FOUND)

    assert inventory_resp.json()["data"]["error_id"] != case_resp.json()["data"]["error_id"]


def test_a_body_foreign_key_resolves_left_to_right(api):
    """PRD §2.9: "Requests that address a resource through an identifier resolve that identifier strictly left to right, and
    the *first* identifier that does not name an existing resource decides the error returned."

    Design: Corner/errors/not_found_codes_are_entity_specific
    """
    set_clock()
    subscriber = create_subscriber()
    resp = api.create_term(
        {
            "subscriber_id": subscriber["id"],
            "plan_id": MISSING_ID,
            "expected_CapacityAgreement_version": 1,
        },
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)


def test_the_agreement_version_does_not_move_on_a_refused_quote(api):
    """PRD §3.5: "Quoting bumps the agreement's `version` by 1."

    Design: Corner/errors/stale_version_code_is_412_not_409
    """
    set_clock()
    agreement = setup_active_agreement()
    plan = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    subscriber = create_subscriber()
    version_before = current_agreement_version(agreement["id"])

    resp = api.create_term(
        {
            "subscriber_id": subscriber["id"],
            "plan_id": MISSING_ID,
            "expected_CapacityAgreement_version": version_before,
        },
        make_subscriber_headers(subscriber["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)
    assert current_agreement_version(agreement["id"]) == version_before