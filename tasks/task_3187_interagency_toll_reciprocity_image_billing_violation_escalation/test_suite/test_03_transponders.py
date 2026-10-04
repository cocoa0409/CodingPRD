"""Transponder lifecycle, uniqueness, and image-path rerouting (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_transponder,
    get_account,
    get_success_data,
    make_account_holder_headers,
    setup_full_account,
    setup_agency_pair,
    setup_account_with_plan,
    create_rate_schedule,
    create_plate_agreement,
    validate_error,
    find_pending_image_bill,
)
from test_helpers.factories import create_transponder_payload

AO = TEST_USERS["agency_ops_headers"]


def test_transponder_get_unknown_id_returns_not_found():
    """PRD §2.8: "each identifier must name an existing resource before the
    next is examined, and the first non-existent identifier yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/transponder_get_unknown_id_returns_not_found
    """
    resp = api_client.get_transponder(NON_EXISTENT_UUID, AO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_transponder_invalid_vehicle_class_enum_rejected():
    """PRD §3.3: "AgencyOperations issues a transponder on an account by
    supplying the physical `tag_number`, the declared `vehicle_class` of the
    vehicle the tag is mounted on (one of `CLASS_2`, `CLASS_5`, `CLASS_7`),
    and the primary vehicle's `plate_number` and `plate_state`."

    Design: Corner/entities/transponder_invalid_vehicle_class_enum_rejected
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(home["id"], plan["id"])
    resp = api_client.create_transponder(
        account["id"],
        create_transponder_payload(
            tag_number="TAG-9", vehicle_class="CLASS_9", plate_number="ENUM99"
        ),
        AO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_transponder_lost_found_cycle_and_terminal_retire():
    """PRD §3.3: "Reporting a tag lost moves it from `ACTIVE` to
    `REPORTED_LOST`... Reporting the tag found moves it back to `ACTIVE`.
    Retiring a tag moves it from `ACTIVE` to `RETIRED`, a terminal state."

    Design: Corner/state_machines/transponder_lost_found_cycle_and_terminal_retire
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(home["id"], plan["id"], opening_balance_cents=5000)
    tag = create_transponder(account["id"], tag_number="TAG-L")
    holder = make_account_holder_headers(account["id"])

    resp = api_client.report_lost(tag["id"], holder)
    assert resp.status_code == 200
    assert get_success_data(resp)["status"] == "REPORTED_LOST"

    resp = api_client.report_found(tag["id"], holder)
    assert resp.status_code == 200
    assert get_success_data(resp)["status"] == "ACTIVE"

    resp = api_client.retire_transponder(tag["id"], holder)
    assert resp.status_code == 200
    assert get_success_data(resp)["status"] == "RETIRED"


def test_retire_from_terminal_returns_invalid_state():
    """PRD §3.3: "Retiring a tag moves it from `ACTIVE` to `RETIRED`, a
    terminal state."

    Design: Corner/state_machines/retire_from_terminal_returns_invalid_state
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(home["id"], plan["id"], opening_balance_cents=5000)
    tag = create_transponder(account["id"], tag_number="TAG-T2")
    holder = make_account_holder_headers(account["id"])
    get_success_data(api_client.retire_transponder(tag["id"], holder))

    resp = api_client.retire_transponder(tag["id"], holder)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_success_data(api_client.get_transponder(tag["id"], AO))["status"] == "RETIRED"


def test_duplicate_tag_and_duplicate_plan_code_rejected():
    """PRD §2.10: "A `tag_number` is unique across all agencies and all
    accounts; re-issuing a tag serial already in the system is rejected with
    `ERR_DUPLICATE_TAG`. A `plan_code` is unique within its issuing agency;
    reusing one yields `ERR_DUPLICATE_PLAN_CODE`."

    Design: Corner/errors/duplicate_tag_and_duplicate_plan_code_rejected
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"], plan_code="STD")
    a1 = create_account(
        home["id"], plan["id"], holder_name="Uma One", holder_email="uma1@example.com"
    )
    a2 = create_account(
        home["id"], plan["id"], holder_name="Uma Two", holder_email="uma2@example.com"
    )
    create_transponder(a1["id"], tag_number="TAG-U")

    resp = api_client.create_transponder(
        a2["id"],
        create_transponder_payload(tag_number="TAG-U", plate_number="UNQ200"),
        AO,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAG)

    resp2 = api_client.create_discount_plan(
        home["id"],
        {
            "plan_code": "STD",
            "discount_pct": 0.10,
            "daily_discount_cap_cents": 0,
            "applies_to_agency_codes": [],
        },
        AO,
    )
    validate_error(resp2, ApiErrorId.ERR_DUPLICATE_PLAN_CODE)


def test_lost_transponder_trip_routes_to_image_billing():
    """PRD §3.3: "Reporting a tag lost moves it from `ACTIVE` to
    `REPORTED_LOST`; from that point on, trips whose `trip_timestamp` falls
    after the report and present this tag are routed to the image-billing path
    instead of debiting the account directly, protecting the holder from a
    stolen tag."

    Design: Corner/state_machines/lost_transponder_trip_routes_to_image_billing
    """
    ctx = setup_full_account(tag_number="TAG-LOST", account_overrides={"opening_balance_cents": 5000})
    account = ctx["account"]
    tag = ctx["transponder"]
    create_rate_schedule(
        ctx["away"]["id"], base_rate_cents=800, image_fee_cents=100
    )
    create_plate_agreement(ctx["away"]["id"], ctx["home"]["id"])
    get_success_data(
        api_client.report_lost(tag["id"], make_account_holder_headers(account["id"]))
    )

    resp = api_client.post_toll_transaction(
        {
            "tag_number": "TAG-LOST",
            "away_agency_id": ctx["away"]["id"],
            "plaza_code": "P1",
            "trip_timestamp": "2026-09-13T09:00:00Z",
            "is_peak": False,
            "idempotency_key": "rl1",
        },
        AO,
    )
    txn = get_success_data(resp)
    assert txn["detection_method"] == "IMAGE"
    assert txn["gross_amount_cents"] == 900

    bill = find_pending_image_bill()
    assert bill["toll_transaction_id"] == txn["id"]

    assert get_account(account["id"])["balance_cents"] == 5000
