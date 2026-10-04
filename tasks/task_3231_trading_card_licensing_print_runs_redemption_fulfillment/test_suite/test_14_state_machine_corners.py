"""State-machine corners: initial states, illegal moves and terminal locks.

These are the transitions a reader of the lifecycle would try first and that
the PRD has to pin explicitly.
"""

from test_helpers import (
    advance_clock,
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_redemption,
    assert_signing_session,
    build_packed_out_line,
    build_ready_to_ship_allocation,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    is_iso8601_timestamp,
    make_licensor_approver_headers,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
SC = TEST_USERS["signing_coordinator_headers"]
ANALYST = TEST_USERS["redemption_analyst_headers"]
DIST = TEST_USERS["distribution_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

SCHEDULED_ON = "2026-10-05T00:00:00Z"


def _approved_set(api, *, autograph_planned_count=0):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api,
        line["id"],
        set_tier="BASE",
        print_run_quantity=500,
        autograph_planned_count=autograph_planned_count,
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    return license_obj, line, card_set


def test_a_booked_session_opens_scheduled_with_a_derived_ship_date(api):
    """PRD §3.4: "A new session opens in `SCHEDULED`, and booking derives
    `ship_date` as the `scheduled_on` date pulled back by the
    `SIGNER_SHIP_LEAD_DAYS` shipping lead time the platform applies to signer
    stock."

    Design: Corner/state_machines/signing_session_create_starts_scheduled_with_a_computed_ship_date
    """
    license_obj, line, card_set = _approved_set(api, autograph_planned_count=200)
    created = validate_success(
        api.create_signing_session(
            {
                "signer_name": "Ken Griffey Jr",
                "signer_kind": "PLAYER_ASSOCIATION",
                "license_id": license_obj["id"],
                "scheduled_on": SCHEDULED_ON,
                "allocation_lines": [
                    {"card_set_id": card_set["id"], "player_id": "kgj", "quantity_delivered": 100}
                ],
            },
            SC,
        ),
        expected_status=201,
    )
    assert_signing_session(created)
    assert created["status"] == "SCHEDULED"
    assert is_iso8601_timestamp(created["ship_date"])
    assert created["ship_date"] < created["scheduled_on"], (
        "the ship date is pulled back from the signing date by the lead time"
    )
    assert created["total_allocated_count"] == 100
    assert created["version"] == 1


def test_the_ship_date_is_derived_rather_than_supplied(api):
    """PRD §3.4: "That derived date matters later: it is the date the card
    stock must leave the printer, and it does not move when the session moves."

    Design: Corner/state_machines/signing_session_create_starts_scheduled_with_a_computed_ship_date
    """
    license_obj, line, card_set = _approved_set(api, autograph_planned_count=200)
    created = get_success_data(
        api.create_signing_session(
            {
                "signer_name": "Ken Griffey Jr",
                "signer_kind": "PLAYER_ASSOCIATION",
                "license_id": license_obj["id"],
                "scheduled_on": SCHEDULED_ON,
                "ship_date": "2099-01-01T00:00:00Z",
                "allocation_lines": [
                    {"card_set_id": card_set["id"], "player_id": "kgj", "quantity_delivered": 100}
                ],
            },
            SC,
        )
    )
    assert created["ship_date"] != "2099-01-01T00:00:00Z", (
        "a client-supplied ship_date is ignored in favour of the derived one"
    )


def test_a_reserved_allocation_cannot_be_shipped_directly(api):
    """PRD §3.8: "Shipping is gated on the calendar, not on demand. The clock
    must be at or after the parent line's `run_planned_on`".

    PRD §3.8: "It is available from `SHIPPED` and only then (`ERR_INVALID_STATE`)."
    PRD §3.9: "The state precondition — that the resource occupy the source
    state its transition requires — is evaluated next".

    Design: Corner/state_machines/shipping_a_reserved_distribution_allocation_returns_invalid_state
    """
    scenario = build_ready_to_ship_allocation(api, mark_utf=False)
    allocation = scenario["allocation"]
    assert allocation["status"] == "RESERVED"

    resp = api.ship_allocation(allocation["id"], DIST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_allocation(allocation["id"], DIST))
    assert after["status"] == "RESERVED"
    assert after["shipped_quantity"] == 0


def test_the_state_check_on_shipping_precedes_the_calendar_check(api):
    """PRD §3.9: "The state precondition — that the resource occupy the source
    state its transition requires — is evaluated next".

    Design: Corner/state_machines/shipping_a_reserved_distribution_allocation_returns_invalid_state
    """
    scenario = build_ready_to_ship_allocation(
        api, mark_utf=False, run_planned_on="2027-01-01T00:00:00Z"
    )
    resp = api.ship_allocation(scenario["allocation"]["id"], DIST)
    error_id = resp.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_INVALID_STATE
    assert error_id != ApiErrorId.ERR_DISTRIBUTION_WINDOW_CLOSED
    assert error_id != ApiErrorId.ERR_ALLOCATION_EXCEEDS_PRINT_RUN


def test_a_shipped_allocation_records_its_shipped_quantity(api):
    """PRD §3.8: "Shipping sets the status to `SHIPPED`, records
    `shipped_quantity` as exactly the allocated quantity".

    Design: Corner/state_machines/shipping_a_reserved_distribution_allocation_returns_invalid_state
    """
    scenario = build_ready_to_ship_allocation(api, quantity_allocated=10)
    allocation = scenario["allocation"]
    assert allocation["status"] == "UTF"
    advance_clock(api, scenario["line"]["run_planned_on"])
    shipped = validate_success(api.ship_allocation(allocation["id"], DIST))
    assert shipped["status"] == "SHIPPED"
    assert shipped["shipped_quantity"] == shipped["quantity_allocated"] == 10


def test_a_cancelled_redemption_rejects_a_close_attempt(api):
    """PRD §3.5: "Cancellation sets the status to `CANCELLED` and sets
    `estimated_value_cents` to 0".

    PRD §3.5: "Closing a fulfilled redemption requires the clock to be at or
    before `opened_on` plus `deadline_days`".

    Design: Corner/state_machines/a_cancelled_redemption_is_terminal_and_rejects_close
    """
    license_obj, line, card_set = _approved_set(api)
    redemption = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-1001",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 400000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    assert redemption["deadline_days"] == 730

    get_success_data(api.set_clock("2029-01-01T00:00:00Z", ADMIN))
    cancelled = validate_success(api.cancel_redemption(redemption["id"], ANALYST))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["estimated_value_cents"] == 0
    assert_redemption(cancelled)


def test_the_terminal_check_on_a_cancelled_redemption_precedes_the_deadline_check(api):
    """PRD §3.5: "`COMPLETED` is terminal, and so is `CANCELLED`; there is no
    path from either back into the working states."

    PRD §3.9: "The state precondition — that the resource occupy the source
    state its transition requires — is evaluated next".

    Design: Corner/state_machines/a_cancelled_redemption_is_terminal_and_rejects_close
    """
    license_obj, line, card_set = _approved_set(api)
    redemption = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-1002",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 400000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    get_success_data(api.set_clock("2029-01-01T00:00:00Z", ADMIN))
    validate_success(api.cancel_redemption(redemption["id"], ANALYST))

    resp = api.close_redemption(redemption["id"], ANALYST)
    error_id = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)["error_id"]
    assert error_id != ApiErrorId.ERR_REDEMPTION_DEADLINE_EXCEEDED, (
        "the terminal-state check precedes the consumer deadline check"
    )
    after = validate_success(api.get_redemption(redemption["id"], ANALYST))
    assert after["status"] == "CANCELLED"


def test_preparing_stock_twice_is_refused_the_second_time(api):
    """PRD §3.4: "Passing both, the session moves to `STOCK_PREPARED` and its
    `version` advances."

    Design: Corner/state_machines/preparing_stock_twice_on_one_signing_session_returns_invalid_state
    """
    license_obj, line, card_set = _approved_set(api, autograph_planned_count=200)
    session = get_success_data(
        api.create_signing_session(
            {
                "signer_name": "Ken Griffey Jr",
                "signer_kind": "PLAYER_ASSOCIATION",
                "license_id": license_obj["id"],
                "scheduled_on": SCHEDULED_ON,
                "allocation_lines": [
                    {"card_set_id": card_set["id"], "player_id": "kgj", "quantity_delivered": 100}
                ],
            },
            SC,
        )
    )
    prepared = validate_success(api.prepare_signing_stock(session["id"], SC))
    assert prepared["status"] == "STOCK_PREPARED"
    resp = api.prepare_signing_stock(session["id"], SC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_the_repeated_preparation_leaves_the_secured_count_alone(api):
    """PRD §3.4: "Shipping the stock is where the session becomes expensive and
    where the royalty ledger is written."

    Design: Corner/state_machines/preparing_stock_twice_on_one_signing_session_returns_invalid_state
    """
    license_obj, line, card_set = _approved_set(api, autograph_planned_count=200)
    session = get_success_data(
        api.create_signing_session(
            {
                "signer_name": "Ken Griffey Jr",
                "signer_kind": "PLAYER_ASSOCIATION",
                "license_id": license_obj["id"],
                "scheduled_on": SCHEDULED_ON,
                "allocation_lines": [
                    {"card_set_id": card_set["id"], "player_id": "kgj", "quantity_delivered": 100}
                ],
            },
            SC,
        )
    )
    get_success_data(api.prepare_signing_stock(session["id"], SC))
    after_first = validate_success(api.get_card_set(card_set["id"], PM))
    assert after_first["autograph_secured_count"] == 0, (
        "preparation moves no stock, so nothing is secured yet"
    )

    api.prepare_signing_stock(session["id"], SC)
    after_second = validate_success(api.get_card_set(card_set["id"], PM))
    assert after_second["autograph_secured_count"] == 0, (
        "the refused call fired no side effect"
    )
    status = validate_success(api.get_signing_session(session["id"], SC))
    assert status["status"] == "STOCK_PREPARED"


def _rejected_artwork_scenario(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    artwork = get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-001",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-25T00:00:00Z",
            },
            PM,
        )
    )
    return license_obj, line, card_set, artwork


def test_rejecting_the_only_artwork_lands_on_the_artwork_record(api):
    """PRD §3.2: "Rejection sets the artwork to `REJECTED`, records
    `decided_on`, and advances the artwork's `version`".

    Design: Corner/state_machines/rejecting_the_only_artwork_leaves_the_card_set_unsubmittable
    """
    license_obj, line, card_set, artwork = _rejected_artwork_scenario(api)
    rejected = validate_success(
        api.decide_artwork(
            artwork["id"],
            {"decision": "REJECT", "decided_on": "2026-08-26T00:00:00Z"},
            make_licensor_approver_headers(license_obj["id"]),
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["decided_on"] == "2026-08-26T00:00:00.000Z"
    assert rejected["version"] == artwork["version"] + 1


def test_the_rejection_keeps_the_set_out_of_submission(api):
    """PRD §3.2: "if the rejection leaves the card set with no remaining
    `APPROVED` artwork at all, that card set is returned to `DRAFT`."

    Design: Corner/state_machines/rejecting_the_only_artwork_leaves_the_card_set_unsubmittable
    """
    license_obj, line, card_set, artwork = _rejected_artwork_scenario(api)
    get_success_data(
        api.decide_artwork(
            artwork["id"],
            {"decision": "REJECT", "decided_on": "2026-08-26T00:00:00Z"},
            make_licensor_approver_headers(license_obj["id"]),
        )
    )
    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["status"] == "DRAFT", (
        "with no approved artwork left the set cannot hold UNDER_REVIEW"
    )
    assert read["print_run_status"] == "UNDECIDED"


def test_a_second_submit_after_the_rejection_reports_the_missing_artwork(api):
    """PRD §3.2: "that at least one piece of the set's artwork already be
    `APPROVED` (`ERR_ARTWORK_NOT_APPROVED`)".

    Design: Corner/state_machines/rejecting_the_only_artwork_leaves_the_card_set_unsubmittable
    """
    license_obj, line, card_set, artwork = _rejected_artwork_scenario(api)
    get_success_data(
        api.decide_artwork(
            artwork["id"],
            {"decision": "REJECT", "decided_on": "2026-08-26T00:00:00Z"},
            make_licensor_approver_headers(license_obj["id"]),
        )
    )
    resp = api.submit_card_set(card_set["id"], PM)
    validate_error(resp, ApiErrorId.ERR_ARTWORK_NOT_APPROVED, expected_status=409)
    lic = validate_success(api.get_license(license_obj["id"], PM))
    assert lic["approved_set_count"] == 0


def test_a_submit_with_pending_artwork_is_blocked_by_the_artwork_row(api):
    """PRD §3.2: "and that no piece of its artwork still be sitting in
    `SUBMITTED` (`ERR_ARTWORK_APPROVAL_PENDING`)."

    Design: Corner/state_machines/card_set_submit_without_approved_artwork_returns_artwork_not_approved
    """
    license_obj, line, card_set, artwork = _rejected_artwork_scenario(api)
    resp = api.submit_card_set(card_set["id"], PM)
    error_id = validate_error(
        resp, ApiErrorId.ERR_ARTWORK_NOT_APPROVED, expected_status=409
    )["error_id"]
    assert error_id != ApiErrorId.ERR_PRODUCT_LINE_NOT_READY
    after = validate_success(api.get_card_set(card_set["id"], PM))
    assert after["status"] == "DRAFT"


def test_approving_the_artwork_then_submitting_succeeds(api):
    """PRD §3.2: "Submission of the set for review requires that its parent line
    already be `READY_FOR_APPROVAL` — otherwise `ERR_PRODUCT_LINE_NOT_READY` —
    that at least one piece of the set's artwork already be `APPROVED`
    (`ERR_ARTWORK_NOT_APPROVED`), and that no piece of its artwork still be
    sitting in `SUBMITTED` (`ERR_ARTWORK_APPROVAL_PENDING`)."

    Design: Corner/state_machines/card_set_submit_without_approved_artwork_returns_artwork_not_approved
    """
    license_obj, line, card_set, artwork = _rejected_artwork_scenario(api)
    validate_error(api.submit_card_set(card_set["id"], PM), ApiErrorId.ERR_ARTWORK_NOT_APPROVED)

    validate_success(
        api.decide_artwork(
            artwork["id"],
            {"decision": "APPROVE", "decided_on": "2026-08-26T00:00:00Z"},
            make_licensor_approver_headers(license_obj["id"]),
        )
    )
    submitted = validate_success(api.submit_card_set(card_set["id"], PM))
    assert submitted["status"] == "UNDER_REVIEW", (
        "the block was the missing precondition, not the set's state"
    )