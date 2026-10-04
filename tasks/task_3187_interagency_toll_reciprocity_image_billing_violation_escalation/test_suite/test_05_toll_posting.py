"""Toll posting gates: idempotency, safety checks, priority pairs (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    fail_replenishments,
    get_account,
    get_success_data,
    make_account_holder_headers,
    setup_full_account,
    setup_agency_pair,
    setup_account_with_plan,
    validate_error,
)

AO = TEST_USERS["agency_ops_headers"]
SO = TEST_USERS["settlement_officer_headers"]


def test_duplicate_idempotency_key_rejected():
    """PRD §3.4: "A duplicate submission with the same away agency, plaza, trip
    timestamp, tag or plate, and `idempotency_key` is rejected with
    `ERR_DUPLICATE_TRANSACTION`."

    Design: Corner/endpoints/duplicate_idempotency_key_rejected
    """
    ctx = setup_full_account(tag_number="TAG-K", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    payload = {
        "tag_number": "TAG-K",
        "away_agency_id": ctx["away"]["id"],
        "plaza_code": "P1",
        "trip_timestamp": "2026-09-17T09:00:00Z",
        "is_peak": False,
        "idempotency_key": "dup-1",
    }
    get_success_data(api_client.post_toll_transaction(payload, AO))
    resp = api_client.post_toll_transaction(payload, AO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRANSACTION)
    assert get_account(ctx["account"]["id"])["balance_cents"] == 9200


def test_state_vs_referential_on_toll_post():
    """PRD §2.8: "Across all endpoints, validation runs in a fixed order.
    Header presence and well-formedness are checked first
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization
    (`ERR_FORBIDDEN_FOR_ROLE`), then path resource existence (`ERR_NOT_FOUND`),
    then whether the target resource's current state permits the requested
    transition (`ERR_INVALID_STATE_TRANSITION`). Only after those generic
    checks do business rules run, in the following order: account, transponder,
    and agency operational safety before a toll debit; rate-schedule existence
    and discount-plan applicability; plate-lookup agreement availability;
    notice-spacing timelines; idempotency and uniqueness constraints;
    settlement and suspension bookkeeping constraints; fiscal floor checks such
    as the reinstatement balance threshold and positive amounts; and finally
    general request-body well-formedness (`ERR_INVALID_REQUEST`)."
    PRD §3.4: "the billed account must not be `SUSPENDED`
    (`ERR_ACCOUNT_SUSPENDED`) or `CLOSED` (`ERR_ACCOUNT_CLOSED`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_referential_on_toll_post
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], plaza_code="P4", base_rate_cents=1200)
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=500)
    create_transponder(account["id"], tag_number="TAG-S", plate_number="SUS100")
    fail_replenishments(account["id"], 3)
    assert get_account(account["id"])["status"] == "SUSPENDED"

    # Plaza PX has NO schedule; account is SUSPENDED. Priority 5 wins.
    resp = api_client.post_toll_transaction(
        {
            "tag_number": "TAG-S",
            "away_agency_id": away["id"],
            "plaza_code": "PX",
            "trip_timestamp": "2026-09-08T09:00:00Z",
            "is_peak": False,
            "idempotency_key": "sx1",
        },
        AO,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


def test_transponder_post_gated_by_agency_suspend():
    """PRD §3.1: "While suspended, no new toll transaction may be posted at the
    agency's plazas: such attempts fail with `ERR_AGENCY_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/transponder_post_gated_by_agency_suspend
    """
    ctx = setup_full_account(tag_number="TAG-G", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    get_success_data(api_client.suspend_agency(ctx["away"]["id"], SO))

    resp = api_client.post_toll_transaction(
        {
            "tag_number": "TAG-G",
            "away_agency_id": ctx["away"]["id"],
            "plaza_code": "P1",
            "trip_timestamp": "2026-09-10T09:00:00Z",
            "is_peak": False,
            "idempotency_key": "g1",
        },
        AO,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_AGENCY_SUSPENDED)
    assert get_account(ctx["account"]["id"])["balance_cents"] == 10000


def test_account_holder_cannot_post_toll_transactions():
    """PRD §4: toll posting is listed under AgencyOperations only.
    PRD §2.1: "If the named role is not permitted to call the endpoint, the
    request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/roles/account_holder_cannot_post_toll_transactions
    """
    ctx = setup_full_account(tag_number="TAG-RB", account_overrides={"opening_balance_cents": 10000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    resp = api_client.post_toll_transaction(
        {
            "tag_number": "TAG-RB",
            "away_agency_id": ctx["away"]["id"],
            "plaza_code": "P1",
            "trip_timestamp": "2026-09-23T09:00:00Z",
            "is_peak": False,
            "idempotency_key": "rb1",
        },
        make_account_holder_headers(ctx["account"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_account(ctx["account"]["id"])["balance_cents"] == 10000


def test_rate_not_found_outside_schedule_window():
    """PRD §3.1: "The window is half-open: a schedule is usable at
    `effective_from` and stops being usable at `effective_to`."
    PRD §3.4: "The system locates the `ACTIVE` rate schedule of the away agency
    whose `plaza_code` matches, whose `vehicle_class` matches the class being
    billed, and whose half-open window from `effective_from` to `effective_to`
    contains the `trip_timestamp`; if no such schedule exists, the posting
    fails with `ERR_RATE_NOT_FOUND`."

    Design: Corner/cross_cutting_layers/rate_not_found_outside_schedule_window
    """
    home, away = setup_agency_pair()
    create_rate_schedule(
        away["id"],
        base_rate_cents=800,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    plan = create_discount_plan(
        home["id"], plan_code="STD", applies_to_agency_codes=[away["agency_code"]]
    )
    account = create_account(home["id"], plan["id"], opening_balance_cents=10000)
    create_transponder(account["id"], tag_number="TAG-WND", plate_number="WND100")

    resp = api_client.post_toll_transaction(
        {
            "tag_number": "TAG-WND",
            "away_agency_id": away["id"],
            "plaza_code": "P1",
            "trip_timestamp": "2026-10-01T00:00:00Z",
            "is_peak": False,
            "idempotency_key": "wnd1",
        },
        AO,
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_RATE_NOT_FOUND)
    assert get_account(account["id"])["balance_cents"] == 10000


def test_toll_transaction_computed_fields_ignore_client_input():
    """PRD §3.4: "If the tag resolves to an `ACTIVE` transponder, the trip is
    priced as a transponder toll with `detection_method` `TRANSPONDER`...
    Either way, the transaction itself starts in `POSTED`."

    Design: Corner/entities/toll_transaction_computed_fields_ignore_client_input
    """
    ctx = setup_full_account(tag_number="TAG-Z", account_overrides={"opening_balance_cents": 5000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    txn = get_success_data(
        api_client.post_toll_transaction(
            {
                "tag_number": "TAG-Z",
                "away_agency_id": ctx["away"]["id"],
                "plaza_code": "P1",
                "trip_timestamp": "2026-09-12T09:00:00Z",
                "is_peak": False,
                "idempotency_key": "z1",
            },
            AO,
        )
    )
    assert txn["detection_method"] == "TRANSPONDER"
    assert txn["charged_amount_cents"] == 800
    assert txn["status"] == "POSTED"


def test_toll_post_immediately_visible_in_account_read():
    """PRD §3.4: "Posting a transponder trip debits `charged_amount_cents` from
    the account's `balance_cents` and bumps the account's `version` by one."

    Design: Corner/consistency_model/toll_post_immediately_visible_in_account_read
    """
    ctx = setup_full_account(tag_number="TAG-IMM", account_overrides={"opening_balance_cents": 5000})
    create_rate_schedule(ctx["away"]["id"], base_rate_cents=800)
    resp = api_client.post_toll_transaction(
        {
            "tag_number": "TAG-IMM",
            "away_agency_id": ctx["away"]["id"],
            "plaza_code": "P1",
            "trip_timestamp": "2026-09-26T09:00:00Z",
            "is_peak": False,
            "idempotency_key": "im1",
        },
        AO,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["charged_amount_cents"] == 800
    assert get_account(ctx["account"]["id"])["balance_cents"] == 4200
