"""The reachable surface of the error catalogue, code by code.

Covers the scoped uniqueness keys of PRD sections 3.1 and 3.4, the body-shape
family of PRD sections 2.7, 2.8 and 3.4, the identity and scope rules of PRD
sections 2.1 and 2.12, the allowance lifecycle codes of PRD section 3.6, the
wrong-state action codes of PRD sections 3.4, 3.2 and 3.7, and the month-end
tie-out limits of PRD section 3.9.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_empty,
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_null_fields,
    assert_page_meta,
    assert_row_count,
    single,
)
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_the_three_duplication_codes_are_scoped_rather_than_global(api):
    """Each uniqueness key names its own scope, so every near-miss outside it is accepted.

    PRD section 3.1 makes `business_date` unique per property (ERR_DUPLICATE_BUSINESS_DATE,
    HTTP 409) and `outlet_code` unique per property (ERR_DUPLICATE_OUTLET_CODE, HTTP 409),
    and PRD section 3.4 makes `ticket_number` unique for one outlet on one operating day
    (ERR_DUPLICATE_TICKET_NUMBER, HTTP 409). PRD section 2.4 starts every record's
    `version` at 1, so a rejected duplicate must leave the row it collided with untouched.

    Design: Corner/errors/error_triggerable_uniqueness_codes_are_scoped_not_global
    """
    fx.set_clock(api, "2026-08-01T18:00:00.000Z")
    prop_a = fx.create_property(api)
    prop_b = fx.create_property(api, name="Harbor Annex")
    lounge = fx.create_outlet(
        api,
        prop_a["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    grill = fx.create_outlet(
        api,
        prop_a["id"],
        outlet_code="GRILL",
        outlet_name="Harbor Grill",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd1 = fx.create_business_date(api, prop_a["id"], "2026-08-01", out_of_order_room_count=4)
    bd2 = fx.create_business_date(api, prop_a["id"], "2026-08-02", out_of_order_room_count=4)
    ticket = fx.create_outlet_ticket(
        api,
        lounge["id"],
        bd1["id"],
        100.00,
        ticket_number="T-U-1",
        settlement_type="CASH",
        opened_at="2026-08-01T18:00:00.000Z",
    )

    validate_error(
        api.create_business_date(
            f.build_business_date_payload(prop_a["id"], "2026-08-01"), AUDITOR
        ),
        E.ERR_DUPLICATE_BUSINESS_DATE,
    )
    rows, meta = validate_paginated(
        api.list_business_dates(AUDITOR, property_id=prop_a["id"])
    )
    assert_page_meta(meta, total_count=2)
    assert_row_count(rows, 2, "operating days of the first property")

    validate_success(
        api.create_business_date(
            f.build_business_date_payload(prop_b["id"], "2026-08-01"), AUDITOR
        ),
        expected_status=201,
    )

    validate_error(
        api.create_outlet(
            f.build_outlet_payload(
                prop_a["id"],
                outlet_code="LOBBY",
                outlet_name="Second Lobby Lounge",
                outlet_type="FB_OUTLET",
            ),
            ADMIN,
        ),
        E.ERR_DUPLICATE_OUTLET_CODE,
    )
    validate_success(
        api.create_outlet(
            f.build_outlet_payload(
                prop_b["id"],
                outlet_code="LOBBY",
                outlet_name="Annex Lobby Lounge",
                outlet_type="FB_OUTLET",
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    def open_check(outlet_id, business_date_id):
        return api.create_outlet_ticket(
            f.build_outlet_ticket_payload(
                outlet_id,
                business_date_id,
                100.00,
                ticket_number="T-U-1",
                settlement_type="CASH",
                opened_at="2026-08-01T18:00:00.000Z",
            ),
            AUDITOR,
        )

    validate_error(open_check(lounge["id"], bd1["id"]), E.ERR_DUPLICATE_TICKET_NUMBER)
    validate_success(open_check(grill["id"], bd1["id"]), expected_status=201)
    validate_success(open_check(lounge["id"], bd2["id"]), expected_status=201)

    untouched = fx.read_ticket(api, ticket["id"])
    assert_fields(untouched, {"version": 1, "status": "OPEN", "ticket_number": "T-U-1"})


def test_the_body_shape_family_separates_bad_enums_from_reserved_values(api):
    """A reserved enum member, a conditional field, two properties and a non-object body.

    PRD section 2.8 lets a client hand-post only MISC_CHARGE, PAYMENT, LEDGER_TRANSFER
    and DEPOSIT_APPLIED and rejects every other declared member with
    ERR_CHARGE_TYPE_NOT_POSTABLE (HTTP 422), while PRD section 2.12 rejects a value
    outside the declared set — and a body that is not an object at all — with
    ERR_INVALID_REQUEST (HTTP 400) and ignores unknown field names rather than
    rejecting them. PRD section 3.4 requires `room_charge_folio_id` on a ROOM_CHARGE
    check and forbids it on a CASH or CREDIT_CARD one, both being
    ERR_TICKET_FOLIO_REQUIRED (HTTP 422). PRD section 2.7 refuses a request whose
    records resolve to different properties with ERR_CROSS_PROPERTY_REFERENCE (HTTP 422).

    Design: Corner/errors/error_triggerable_body_shape_and_target_codes
    """
    fx.set_clock(api, "2026-08-01T18:00:00.000Z")
    prop_a = fx.create_property(api)
    prop_b = fx.create_property(api, name="Harbor Annex")
    lounge = fx.create_outlet(
        api,
        prop_a["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd_a = fx.create_business_date(api, prop_a["id"], "2026-08-01", out_of_order_room_count=4)
    bd_b = fx.create_business_date(api, prop_b["id"], "2026-08-01", out_of_order_room_count=4)
    folio_a = fx.create_folio(
        api, prop_a["id"], bd_a["id"], confirmation_code="CF-BS1", guest_name="Iva Renn"
    )
    fx.check_in(api, folio_a["id"])
    folio_b = fx.create_folio(
        api, prop_b["id"], bd_b["id"], confirmation_code="CF-BS2", guest_name="Odd Nesse"
    )
    ledger = fx.create_ledger_account(api, prop_a["id"])

    def hand_post(charge_type, amount, **overrides):
        return api.create_journal_posting(
            f.build_journal_posting_payload(bd_a["id"], charge_type, amount, **overrides),
            AUDITOR,
        )

    validate_error(
        hand_post("ROOM", 200.00, folio_id=folio_a["id"]), E.ERR_CHARGE_TYPE_NOT_POSTABLE
    )
    for reserved in [
        "OCCUPANCY_TAX",
        "TAX_TRUE_UP",
        "NO_SHOW",
        "LATE_CHECKOUT",
        "OUTLET_TRANSFER",
        "CITY_LEDGER_FEE",
        "ALLOWANCE",
    ]:
        validate_error(
            hand_post(reserved, 25.00, folio_id=folio_a["id"]),
            E.ERR_CHARGE_TYPE_NOT_POSTABLE,
        )

    validate_success(hand_post("MISC_CHARGE", 25.00, folio_id=folio_a["id"]), expected_status=201)
    validate_success(hand_post("PAYMENT", -25.00, folio_id=folio_a["id"]), expected_status=201)
    validate_success(
        hand_post("DEPOSIT_APPLIED", -10.00, folio_id=folio_a["id"]), expected_status=201
    )
    validate_success(
        hand_post("LEDGER_TRANSFER", 40.00, ledger_account_id=ledger["id"]),
        expected_status=201,
    )

    validate_error(
        hand_post("SPA_CHARGE", 25.00, folio_id=folio_a["id"]), E.ERR_INVALID_REQUEST
    )

    def open_check(**overrides):
        payload = f.build_outlet_ticket_payload(lounge["id"], bd_a["id"], 100.00)
        payload.update(overrides)
        return api.create_outlet_ticket(payload, AUDITOR)

    validate_error(
        open_check(settlement_type="ROOM_CHARGE"), E.ERR_TICKET_FOLIO_REQUIRED
    )
    validate_error(
        open_check(settlement_type="CASH", room_charge_folio_id=folio_a["id"]),
        E.ERR_TICKET_FOLIO_REQUIRED,
    )

    validate_error(
        open_check(business_date_id=bd_b["id"]), E.ERR_CROSS_PROPERTY_REFERENCE
    )
    validate_error(
        open_check(settlement_type="ROOM_CHARGE", room_charge_folio_id=folio_b["id"]),
        E.ERR_CROSS_PROPERTY_REFERENCE,
    )

    validate_error(
        api.raw_post(
            "/night-audit/journal-postings",
            [f.build_journal_posting_payload(bd_a["id"], "MISC_CHARGE", 15.00)],
            AUDITOR,
        ),
        E.ERR_INVALID_REQUEST,
    )

    tolerated = validate_success(
        hand_post("MISC_CHARGE", 15.00, folio_id=folio_a["id"], undeclared_extra_key="ignored"),
        expected_status=201,
    )
    assert "undeclared_extra_key" not in tolerated, (
        "expected an unknown field to be ignored rather than echoed, got "
        f"{sorted(tolerated)}"
    )
    assert_money(tolerated["amount"], 15.00, "amount")


def test_four_identity_failures_collapse_into_two_codes_and_then_a_third(api):
    """An unparseable identity is 401 even on an endpoint the caller could never reach.

    PRD section 2.12 evaluates authentication first — a missing header, an empty header
    value and a role outside the six declared roles are all ERR_UNAUTHENTICATED
    (HTTP 401) — then authorization, where a role absent from the endpoint's list and an
    OutletManager whose `X-User-ID` resolves to no outlet are both ERR_UNAUTHORIZED
    (HTTP 403). PRD section 3.4 then refuses a well-formed manager reaching another
    outlet's check with ERR_OUTLET_SCOPE_VIOLATION (HTTP 403). PRD section 2.4 leaves a
    rejected request's records untouched.

    Design: Corner/errors/error_triggerable_identity_and_scope_codes
    """
    fx.set_clock(api, "2026-08-01T18:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    grill = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="GRILL",
        outlet_name="Harbor Grill",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    ticket = fx.create_outlet_ticket(
        api,
        lounge["id"],
        bd["id"],
        100.00,
        ticket_number="T-ID-1",
        settlement_type="CASH",
        opened_at="2026-08-01T18:00:00.000Z",
    )

    validate_error(
        api.post_room_and_tax(bd["id"], {"X-User-Role": "NightAuditor"}),
        E.ERR_UNAUTHENTICATED,
    )
    untouched = fx.read_business_date(api, bd["id"])
    assert_fields(untouched, {"status": "OPEN", "version": 1})

    validate_error(
        api.post_room_and_tax(
            bd["id"], {"X-User-Role": "NightAuditor", "X-User-ID": ""}
        ),
        E.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.post_room_and_tax(bd["id"], {"X-User-Role": "Auditor", "X-User-ID": "u_na_1"}),
        E.ERR_UNAUTHENTICATED,
    )
    validate_error(
        api.post_room_and_tax(bd["id"], {"X-User-Role": "Auditor", "X-User-ID": "u_fd_1"}),
        E.ERR_UNAUTHENTICATED,
    )
    validate_error(api.post_room_and_tax(bd["id"], FRONT_DESK), E.ERR_UNAUTHORIZED)

    closing = f.build_close_ticket_payload("2026-08-01T20:00:00.000Z")
    validate_error(
        api.close_outlet_ticket(
            ticket["id"], {"X-User-Role": "OutletManager", "X-User-ID": "u_om_1"}, closing
        ),
        E.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.close_outlet_ticket(
            ticket["id"], make_outlet_manager_headers(grill["id"]), closing
        ),
        E.ERR_OUTLET_SCOPE_VIOLATION,
    )
    closed = validate_success(
        api.close_outlet_ticket(
            ticket["id"], make_outlet_manager_headers(lounge["id"]), closing
        )
    )
    assert_fields(closed, {"status": "CLOSED"})


def test_one_allowance_walked_to_reversed_trips_seven_lifecycle_codes(api):
    """Each code is pinned to exactly one state or one field along the same walk.

    PRD section 3.6 fires ERR_REASON_CODE_REQUIRED and ERR_SUPPORTING_DOCUMENT_REQUIRED
    (both HTTP 422) at submit time and nowhere else, refuses a submit from any state
    other than DRAFT or RETURNED_FOR_REVISION with ERR_ALLOWANCE_NOT_SUBMITTABLE
    (HTTP 409), refuses an approval of a non-SUBMITTED allowance with
    ERR_ALLOWANCE_NOT_PENDING (HTTP 409), requires `approved_amount` to be above zero
    and no greater than `requested_amount` else ERR_APPROVED_AMOUNT_EXCEEDS_REQUEST
    (HTTP 422), carries an approval straight through APPROVED to POSTED in the same
    request, refuses a reversal of anything not POSTED with ERR_ALLOWANCE_NOT_POSTED
    (HTTP 409), and refuses to reverse the compensating allowance a reversal mints with
    ERR_ALREADY_A_REVERSAL (HTTP 409). PRD section 2.10 keeps the requester out of the
    approval.

    Design: Corner/errors/error_triggerable_allowance_lifecycle_codes
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-AL1",
        guest_name="Bo Karlsen",
        room_number="1201",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])

    plain = get_success_data(
        api.create_allowance(
            f.without(
                f.build_allowance_payload(folio["id"], bd["id"], 200.00), "reason_code"
            ),
            FRONT_DESK,
        )
    )
    assert_null_fields(plain, ["reason_code"])
    rate = fx.create_allowance(
        api, folio["id"], bd["id"], 200.00, reason_code="RATE_ERROR"
    )

    validate_error(
        api.submit_allowance(plain["id"], FRONT_DESK), E.ERR_REASON_CODE_REQUIRED
    )
    still_draft = fx.read_allowance(api, plain["id"])
    assert_fields(still_draft, {"status": "DRAFT", "version": 1})
    assert_null_fields(still_draft, ["reason_code"])

    validate_error(
        api.submit_allowance(rate["id"], FRONT_DESK), E.ERR_SUPPORTING_DOCUMENT_REQUIRED
    )
    validate_error(
        api.submit_allowance(
            rate["id"], FRONT_DESK, {"supporting_document_reference": ""}
        ),
        E.ERR_SUPPORTING_DOCUMENT_REQUIRED,
    )
    validate_error(
        api.approve_allowance(rate["id"], f.build_approve_payload(200.00), AUDITOR),
        E.ERR_ALLOWANCE_NOT_PENDING,
    )
    validate_success(
        api.submit_allowance(
            rate["id"], FRONT_DESK, {"supporting_document_reference": "SCAN-2026-77"}
        )
    )

    submitted = validate_success(
        api.submit_allowance(
            plain["id"], FRONT_DESK, {"reason_code": "MANAGER_DISCRETION"}
        )
    )
    assert_fields(
        submitted,
        {
            "status": "SUBMITTED",
            "reason_code": "MANAGER_DISCRETION",
            "required_approval_role": "NightAuditor",
        },
    )
    validate_error(
        api.submit_allowance(plain["id"], FRONT_DESK), E.ERR_ALLOWANCE_NOT_SUBMITTABLE
    )

    validate_error(
        api.approve_allowance(plain["id"], f.build_approve_payload(0.00), AUDITOR),
        E.ERR_APPROVED_AMOUNT_EXCEEDS_REQUEST,
    )
    validate_error(
        api.approve_allowance(plain["id"], f.build_approve_payload(200.01), AUDITOR),
        E.ERR_APPROVED_AMOUNT_EXCEEDS_REQUEST,
    )
    validate_error(
        api.reverse_allowance(plain["id"], REVENUE_MANAGER), E.ERR_ALLOWANCE_NOT_POSTED
    )

    posted = validate_success(
        api.approve_allowance(plain["id"], f.build_approve_payload(200.00), AUDITOR)
    )
    assert_fields(posted, {"status": "POSTED"})
    assert_money(posted["approved_amount"], 200.00, "approved_amount")

    get_success_data(api.reverse_allowance(plain["id"], REVENUE_MANAGER))
    assert_fields(fx.read_allowance(api, plain["id"]), {"status": "REVERSED"})
    compensating = single(
        validate_success(
            api.list_allowances(AUDITOR, reverses_allowance_id=plain["id"])
        ),
        "the compensating allowance",
    )
    assert_fields(
        compensating,
        {"status": "POSTED", "reverses_allowance_id": plain["id"], "reason_code": "MANAGER_DISCRETION"},
    )
    validate_error(
        api.reverse_allowance(compensating["id"], REVENUE_MANAGER), E.ERR_ALREADY_A_REVERSAL
    )


def test_three_entities_refuse_the_right_verb_one_beat_early_or_late(api):
    """Each pair of actions is legal in opposite states, and the follow-up code is about the account.

    PRD section 3.4 refuses a void of a check that is not CLOSED with
    ERR_TICKET_NOT_CLOSED and a close of a check that is not OPEN with
    ERR_TICKET_NOT_OPEN (both HTTP 409). PRD section 3.2 refuses a review of a document
    that is not PENDING with ERR_DOCUMENT_NOT_PENDING and a revocation of one that is
    not ACTIVE with ERR_DOCUMENT_NOT_ACTIVE (both HTTP 409). PRD section 3.7 requires a
    capture to be above zero and no greater than `authorized_amount` else
    ERR_CAPTURE_EXCEEDS_AUTHORIZATION (HTTP 422), drives the follow-up dimension
    PENDING to CONTACTED to RESOLVED with ERR_FOLLOW_UP_NOT_PENDING and
    ERR_FOLLOW_UP_NOT_CONTACTED guarding the two hops, and refuses a resolution until
    the owning account carries at least one PAYMENT line with
    ERR_FOLLOW_UP_NO_REPLACEMENT_TENDER (all HTTP 409).

    Design: Corner/errors/error_triggerable_wrong_state_action_codes_on_tickets_documents_and_cards
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    lounge = fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio_1 = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-WS1",
        guest_name="Imke Dolan",
        room_number="1801",
        settlement_method="CREDIT_CARD",
        credit_limit_amount=5000.00,
    )
    folio_2 = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-WS2",
        guest_name="Onur Bataille",
        room_number="1802",
        settlement_method="CREDIT_CARD",
        credit_limit_amount=5000.00,
    )
    ticket = fx.create_outlet_ticket(
        api,
        lounge["id"],
        bd["id"],
        100.00,
        ticket_number="T-WS-1",
        settlement_type="CASH",
        opened_at="2026-08-01T08:30:00.000Z",
    )
    document = fx.create_authorization_document(
        api,
        prop["id"],
        doc_type="COMP_ROOM",
        folio_id=folio_1["id"],
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-02",
    )
    auth_a = fx.create_card_authorization(api, folio_1["id"], 400.00)
    auth_b = fx.create_card_authorization(api, folio_2["id"], 300.00)
    manager = make_outlet_manager_headers(lounge["id"])

    validate_error(api.void_outlet_ticket(ticket["id"], manager), E.ERR_TICKET_NOT_CLOSED)
    assert_fields(fx.read_ticket(api, ticket["id"]), {"status": "OPEN", "version": 1})

    closing = f.build_close_ticket_payload("2026-08-01T09:00:00.000Z")
    validate_success(api.close_outlet_ticket(ticket["id"], manager, closing))
    validate_error(
        api.close_outlet_ticket(ticket["id"], manager, closing), E.ERR_TICKET_NOT_OPEN
    )
    voided = validate_success(api.void_outlet_ticket(ticket["id"], manager))
    assert_fields(voided, {"status": "VOID"})
    validate_error(api.void_outlet_ticket(ticket["id"], manager), E.ERR_TICKET_NOT_CLOSED)

    validate_error(
        api.revoke_authorization_document(document["id"], CONTROLLER),
        E.ERR_DOCUMENT_NOT_ACTIVE,
    )
    active = validate_success(
        api.review_authorization_document(
            document["id"], f.build_review_payload("APPROVE"), REVENUE_MANAGER
        )
    )
    assert_fields(active, {"status": "ACTIVE"})
    validate_error(
        api.review_authorization_document(
            document["id"], f.build_review_payload("APPROVE"), REVENUE_MANAGER
        ),
        E.ERR_DOCUMENT_NOT_PENDING,
    )
    revoked = validate_success(
        api.revoke_authorization_document(document["id"], CONTROLLER)
    )
    assert_fields(revoked, {"status": "REVOKED"})
    validate_error(
        api.revoke_authorization_document(document["id"], CONTROLLER),
        E.ERR_DOCUMENT_NOT_ACTIVE,
    )

    validate_error(
        api.capture_card_authorization(
            auth_a["id"], f.build_capture_payload(400.01, bd["id"]), AUDITOR
        ),
        E.ERR_CAPTURE_EXCEEDS_AUTHORIZATION,
    )
    validate_error(
        api.capture_card_authorization(
            auth_a["id"], f.build_capture_payload(0.00, bd["id"]), AUDITOR
        ),
        E.ERR_CAPTURE_EXCEEDS_AUTHORIZATION,
    )
    captured = validate_success(
        api.capture_card_authorization(
            auth_a["id"], f.build_capture_payload(400.00, bd["id"]), AUDITOR
        )
    )
    assert_fields(captured, {"status": "CAPTURED"})
    assert_money(captured["captured_amount"], 400.00, "captured_amount")

    declined = validate_success(
        api.decline_card_authorization(
            auth_b["id"], f.build_decline_payload("INSUFFICIENT_FUNDS"), FRONT_DESK
        )
    )
    assert_fields(declined, {"status": "DECLINED", "follow_up_status": "PENDING"})

    def follow_up(action):
        return api.follow_up_card_authorization(
            auth_b["id"], f.build_follow_up_payload(action), FRONT_DESK
        )

    validate_error(follow_up("RESOLVE"), E.ERR_FOLLOW_UP_NOT_CONTACTED)
    contacted = validate_success(follow_up("CONTACT"))
    assert_fields(contacted, {"follow_up_status": "CONTACTED"})
    validate_error(follow_up("CONTACT"), E.ERR_FOLLOW_UP_NOT_PENDING)
    validate_error(follow_up("RESOLVE"), E.ERR_FOLLOW_UP_NO_REPLACEMENT_TENDER)

    validate_success(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"], "PAYMENT", -300.00, folio_id=folio_2["id"]
            ),
            AUDITOR,
        ),
        expected_status=201,
    )
    resolved = validate_success(follow_up("RESOLVE"))
    assert_fields(resolved, {"follow_up_status": "RESOLVED", "status": "DECLINED"})
    assert_fields(fx.read_folio(api, folio_2["id"]), {"settlement_hold": False})
    validate_error(follow_up("ESCALATE"), E.ERR_FOLLOW_UP_NOT_CONTACTED)


def test_a_zero_tolerance_tie_out_wedges_the_month_after_three_attempts(api):
    """One cent fails the assertion, and the retry counter is the only thing that ends the loop.

    PRD section 3.9 computes `tie_out_variance_amount` as `gl_control_total_amount`
    minus the `subsystem_total_amount` summed over the period's CLOSED and ARCHIVED
    days, passes only an absolute variance of exactly 0.00, and on failure sets
    TIE_OUT_FAILED, raises `tie_out_attempt_count` by one, archives nothing and leaves
    `audit_trail_retention_until_date` null. An attempt made once that counter has
    reached three is refused with ERR_TIE_OUT_ATTEMPT_LIMIT_REACHED (HTTP 409) — before
    the arithmetic is consulted, so even the exactly-correct total is refused. PRD
    section 3.8 refuses a reopen whose owning period is no longer OPEN with
    ERR_PERIOD_NOT_OPEN (HTTP 409).

    Design: Corner/errors/error_triggerable_tie_out_failure_and_attempt_limit_codes
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-TO1",
        guest_name="Lea Brunel",
        room_number="1601",
        contracted_rate_amount=200.00,
    )
    fx.check_in(api, folio["id"])
    closed = fx.drive_to_closed(api, bd["id"])
    assert_fields(closed, {"status": "CLOSED"})
    assert_money(closed["total_revenue_amount"], 217.75, "total_revenue_amount")
    period_id = bd["accounting_period_id"]

    def attempt(gl_total):
        return api.tie_out_period(period_id, f.build_tie_out_payload(gl_total), CONTROLLER)

    first = validate_success(attempt(217.76))
    assert_fields(first, {"status": "TIE_OUT_FAILED"})
    assert_money_fields(
        first,
        {
            "subsystem_total_amount": 217.75,
            "gl_control_total_amount": 217.76,
            "tie_out_variance_amount": 0.01,
        },
    )
    assert_int(first["tie_out_attempt_count"], 1, "tie_out_attempt_count")
    assert_null_fields(first, ["tied_out_at", "audit_trail_retention_until_date"])
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "CLOSED"})

    validate_error(
        api.reopen_business_date(bd["id"], CONTROLLER), E.ERR_PERIOD_NOT_OPEN
    )

    second = validate_success(attempt(220.00))
    assert_money(second["tie_out_variance_amount"], 2.25, "tie_out_variance_amount")
    assert_int(second["tie_out_attempt_count"], 2, "tie_out_attempt_count")

    third = validate_success(attempt(217.00))
    assert_money(third["tie_out_variance_amount"], -0.75, "tie_out_variance_amount")
    assert_int(third["tie_out_attempt_count"], 3, "tie_out_attempt_count")

    validate_error(attempt(217.75), E.ERR_TIE_OUT_ATTEMPT_LIMIT_REACHED)

    wedged = fx.read_period(api, period_id)
    assert_fields(wedged, {"status": "TIE_OUT_FAILED"})
    assert_int(wedged["tie_out_attempt_count"], 3, "tie_out_attempt_count")
    assert_money(wedged["gl_control_total_amount"], 217.00, "gl_control_total_amount")
    assert_null_fields(wedged, ["audit_trail_retention_until_date"])
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "CLOSED"})


def test_thirteen_collections_own_thirteen_not_found_codes_in_a_fixed_order(api):
    """When one body names several unknown ids the declared order decides the single code.

    PRD section 2.12 resolves body references in a fixed order — `property_id`, then
    `business_date_id`, then `folio_id`, then `outlet_id`, then `ledger_account_id`,
    then `allowance_id` — and gives every collection its own 404 code rather than a
    shared one. It also runs the role check before any lookup, so a caller who may not
    use an endpoint learns nothing about what lies behind it. PRD section 2.3 makes a
    filter that matches nothing an empty page rather than a not-found.

    Design: Corner/errors/error_triggerable_not_found_codes_are_one_per_collection_and_ordered
    """
    fx.set_clock(api, "2026-08-01T18:00:00.000Z")
    prop = fx.create_property(api)
    fx.create_outlet(
        api,
        prop["id"],
        outlet_code="LOBBY",
        outlet_name="Lobby Lounge",
        outlet_type="FB_OUTLET",
        requires_shift_settlement=False,
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)

    validate_error(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(
                MISSING_UUID,
                MISSING_UUID,
                100.00,
                ticket_number="T-NF-1",
                settlement_type="CASH",
                opened_at="2026-08-01T18:00:00.000Z",
            ),
            AUDITOR,
        ),
        E.ERR_BUSINESS_DATE_NOT_FOUND,
    )
    validate_error(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(
                MISSING_UUID,
                bd["id"],
                100.00,
                ticket_number="T-NF-2",
                settlement_type="CASH",
                opened_at="2026-08-01T18:00:00.000Z",
            ),
            AUDITOR,
        ),
        E.ERR_OUTLET_NOT_FOUND,
    )

    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                MISSING_UUID, "MISC_CHARGE", 25.00, folio_id=MISSING_UUID
            ),
            AUDITOR,
        ),
        E.ERR_BUSINESS_DATE_NOT_FOUND,
    )
    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"],
                "MISC_CHARGE",
                25.00,
                folio_id=MISSING_UUID,
                ledger_account_id=MISSING_UUID,
            ),
            AUDITOR,
        ),
        E.ERR_FOLIO_NOT_FOUND,
    )

    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                MISSING_UUID, "COMP_ROOM", folio_id=MISSING_UUID
            ),
            FRONT_DESK,
        ),
        E.ERR_PROPERTY_NOT_FOUND,
    )
    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"], "ALLOWANCE_APPROVAL", allowance_id=MISSING_UUID
            ),
            FRONT_DESK,
        ),
        E.ERR_ALLOWANCE_NOT_FOUND,
    )

    per_collection = [
        (api.get_property, E.ERR_PROPERTY_NOT_FOUND),
        (api.get_business_date, E.ERR_BUSINESS_DATE_NOT_FOUND),
        (api.get_folio, E.ERR_FOLIO_NOT_FOUND),
        (api.get_journal_posting, E.ERR_POSTING_NOT_FOUND),
        (api.get_outlet_ticket, E.ERR_TICKET_NOT_FOUND),
        (api.get_settlement_batch, E.ERR_BATCH_NOT_FOUND),
        (api.get_ledger_account, E.ERR_LEDGER_ACCOUNT_NOT_FOUND),
        (api.get_allowance, E.ERR_ALLOWANCE_NOT_FOUND),
        (api.get_authorization_document, E.ERR_DOCUMENT_NOT_FOUND),
        (api.get_card_authorization, E.ERR_AUTHORIZATION_NOT_FOUND),
        (api.get_revenue_report, E.ERR_REPORT_NOT_FOUND),
        (api.get_outlet, E.ERR_OUTLET_NOT_FOUND),
        (api.get_accounting_period, E.ERR_PERIOD_NOT_FOUND),
    ]
    for read, expected in per_collection:
        validate_error(read(MISSING_UUID, AUDITOR), expected)

    validate_error(
        api.post_room_and_tax(MISSING_UUID, FRONT_DESK), E.ERR_UNAUTHORIZED
    )

    rows, meta = validate_paginated(
        api.list_business_dates(AUDITOR, property_id=MISSING_UUID)
    )
    assert_empty(rows, "operating days of a property that does not exist")
    assert_page_meta(meta, total_count=0)
    assert_fields(fx.read_business_date(api, bd["id"]), {"status": "OPEN"})
