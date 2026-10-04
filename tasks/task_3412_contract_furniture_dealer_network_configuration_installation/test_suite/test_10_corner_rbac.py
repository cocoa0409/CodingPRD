"""RBAC corners: role-list denials and ownership-scope denials
(PRD §2.1, §3.2, §3.8, §4 role columns)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_configuration,
    create_dealer,
    create_end_user,
    create_order,
    create_volume_agreement,
    file_punch,
    make_configuration_payload,
    make_dealer_headers,
    make_dealer_payload,
    make_end_user_headers,
    make_submit_payload,
    resolve_punch,
    setup_locked_world,
    setup_phase_in_progress,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_dealerrep_cannot_create_dealer(api):
    """PRD §2.1: "If the role is known but is not in the endpoint's
    authorized role list, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." §4: POST /dealers is authorized for
    `ManufacturerAdmin` only.

    Design: Corner/rbac/rbac_dealerrep_cannot_create_dealer
    """
    dealer = create_dealer(api, name="Dealer Alpha")
    resp = api.create_dealer(
        make_dealer_payload(name="Dealer Beta", territory_codes=["OH"],
                            service_capability_level=2),
        make_dealer_headers(dealer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_enduserrep_cannot_create_configuration(api):
    """PRD §2.1: "If the role is known but is not in the endpoint's
    authorized role list, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." §4: POST /configurations is
    authorized for `DealerRep` only.

    Design: Corner/rbac/rbac_enduserrep_cannot_create_configuration
    """
    end_user = create_end_user(api, name="MegaCorp")
    resp = api.create_configuration(
        make_configuration_payload(name="Nope"),
        make_end_user_headers(end_user["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_manufactureradmin_cannot_submit_order(api):
    """PRD §2.1: "If the role is known but is not in the endpoint's
    authorized role list, the request is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." §4: POST
    /project-orders/{orderId}/submit is authorized for `DealerRep` only —
    the manufacturer acknowledges, the dealer submits.

    Design: Corner/rbac/rbac_manufactureradmin_cannot_submit_order
    """
    ctx = setup_locked_world(api)
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"],
    )
    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_dealerrep_cannot_read_other_dealers_configuration(api):
    """PRD §2.1: "a `DealerRep` may only touch resources whose `dealer_id`
    equals `X-User-ID`" and "Acting on a resource outside that scope is
    rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/rbac_dealerrep_cannot_read_other_dealers_configuration
    """
    dealer_a = create_dealer(api, name="Dealer A")
    dealer_b = create_dealer(api, name="Dealer B", territory_codes=["OH"])
    spec = create_configuration(api, dealer_a["id"], name="A spec")

    resp = api.get_configuration(
        spec["id"], make_dealer_headers(dealer_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_enduserrep_cannot_verify_other_endusers_punch(api):
    """PRD §2.1: "an `EndUserRep` may only touch resources belonging to
    orders whose agreement's `end_user_id` equals `X-User-ID`" and "Acting
    on a resource outside that scope is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/rbac_enduserrep_cannot_verify_other_endusers_punch
    """
    ctx = setup_phase_in_progress(api)
    dealer_id = ctx["dealer"]["id"]
    eu_a = ctx["end_user"]["id"]
    other_eu = create_end_user(api, name="GigaCorp", industry="finance")

    ticket = file_punch(
        api, ctx["phase"]["id"], make_end_user_headers(eu_a),
        severity="MINOR", description="Scuff",
    )
    resolve_punch(api, ticket["id"], dealer_id, resolution_note="Polished")

    resp = api.verify_punch_ticket(
        ticket["id"], {"outcome": "CONFIRMED"},
        make_end_user_headers(other_eu["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

    reread = validate_success(
        api.get_punch_ticket(ticket["id"], make_dealer_headers(dealer_id)), 200
    )
    assert reread["status"] == "RESOLVED"


def test_enduserrep_agreement_read_forbidden_for_others(api):
    """PRD §3.2: "an `EndUserRep` sees only the agreements whose
    `end_user_id` matches their own identity" and §2.1: "Acting on a
    resource outside that scope is rejected with `ERR_FORBIDDEN_OWNERSHIP`
    (HTTP 403)."

    Design: Corner/rbac/rbac_enduserrep_agreement_read_forbidden_for_others
    """
    eu_a = create_end_user(api, name="MegaCorp")
    eu_b = create_end_user(api, name="GigaCorp", industry="finance")
    agreement = create_volume_agreement(api, eu_a["id"])

    own = validate_success(
        api.get_volume_agreement(
            agreement["id"], make_end_user_headers(eu_a["id"])
        ),
        200,
    )
    assert own["id"] == agreement["id"]

    resp = api.get_volume_agreement(
        agreement["id"], make_end_user_headers(eu_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
