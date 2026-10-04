"""Validation corners: authentication, existence-vs-shape ordering, OCC
ordering, body-shape uniqueness, and the agreement gates (PRD §2.1, §2.5,
§2.9, §3.5, §3.6)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_and_lock_configuration,
    create_dealer,
    create_order,
    create_phase,
    get_order,
    make_dealer_headers,
    make_project_order_payload,
    make_submit_payload,
    set_logical_clock,
    setup_acknowledged_order,
    setup_dealer_world,
    setup_locked_world,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one
    of the known roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/val_missing_auth_header_returns_401
    """
    resp = api.list_project_orders({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_existence_beats_body_validation_returns_404(api):
    """PRD §2.9: "they are evaluated in a fixed order, and the first failing
    check determines the error returned" with "(3) resource existence" ahead
    of "(5) request body shape, else `ERR_VALIDATION`" — a submit against an
    unknown order id with an empty body returns ERR_ORDER_NOT_FOUND, not 400.

    Design: Corner/validations/val_existence_beats_body_validation_returns_404
    """
    dealer = create_dealer(api)
    resp = api.submit_project_order(
        NON_EXISTENT_UUID, {}, make_dealer_headers(dealer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_occ_beats_state_on_submit_returns_412(api):
    """PRD §2.9: "(7) optimistic concurrency, else `ERR_STALE_VERSION`; (8)
    generic state preconditions, else `ERR_INVALID_STATE`" and §2.5: "If the
    supplied value does not match the entity's current `version` — because a
    dealer-suspension cascade, a prior submission, a revision, or any other
    mutation has advanced the version since the client last read the
    resource — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    On an ACKNOWLEDGED order a stale expected_order_version fires OCC before
    the state check.

    Design: Corner/validations/val_occ_beats_state_on_submit_returns_412
    """
    ctx = setup_acknowledged_order(api)
    live = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    assert live["status"] == "ACKNOWLEDGED"
    stale_version = live["version"] - 1
    assert stale_version >= 1

    resp = api.submit_project_order(
        live["id"], make_submit_payload(stale_version),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_duplicate_phase_sequence_rejected(api):
    """PRD §3.6: "`phase_sequence` (at least 1 and unique within the order; a
    duplicate pair is `ERR_VALIDATION`)".

    Design: Corner/validations/val_duplicate_phase_sequence_rejected
    """
    ctx = setup_locked_world(api)
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"],
    )
    create_phase(api, order["id"], ctx["dealer"]["id"],
                 floor_number=1, phase_sequence=1)
    resp = api.create_phase(
        order["id"],
        {"floor_number": 2, "phase_sequence": 1,
         "building_zone_id": "Z1", "planned_units": 5},
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_order_create_rejects_draft_agreement(api):
    """PRD §3.5: "The referenced agreement must already be `ACTIVE` with the
    clock date on or after its `effective_start` and on or before its
    `effective_end` — an agreement that is `DRAFT`, `EXPIRED`, or outside
    its effective window rejects the create with
    `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Corner/validations/val_order_create_rejects_draft_agreement
    """
    ctx = setup_dealer_world(api, activate=False)
    spec = create_and_lock_configuration(api, ctx["dealer"]["id"])
    resp = api.create_project_order(
        make_project_order_payload(ctx["agreement"]["id"], spec["id"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_submit_rejects_expired_agreement(api):
    """PRD §3.5: "the referenced agreement must be `ACTIVE` and within its
    effective window at the submission clock date (else
    `ERR_AGREEMENT_NOT_ACTIVE`)"; §3.2: the agreement "moves `ACTIVE →
    EXPIRED`" once the clock is strictly after `effective_end`.

    Design: Corner/validations/val_submit_rejects_expired_agreement
    """
    ctx = setup_dealer_world(api, agreement_end="2026-10-01")
    spec = create_and_lock_configuration(api, ctx["dealer"]["id"])
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    # Past effective_end; the lead-time check would still pass
    # (2026-10-02 + 31 <= 2026-12-15), isolating the agreement gate.
    set_logical_clock(api, "2026-10-02T00:00:00Z")
    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_submit_rejects_unauthorized_territory(api):
    """PRD §3.5: "the order's `territory_code` must appear in the dealer's
    `territory_codes` (else `ERR_TERRITORY_NOT_AUTHORIZED`)".

    Design: Corner/validations/val_submit_rejects_unauthorized_territory
    """
    ctx = setup_locked_world(api)  # dealer territories MI/OH
    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"],
        ctx["dealer"]["id"], territory_code="TX",
    )
    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_AUTHORIZED)
