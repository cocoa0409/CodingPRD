"""Overlap windows, account close cascade, void invariant, misc (PRD §3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_account,
    create_discount_plan,
    create_home_agency,
    create_rate_schedule,
    create_transponder,
    create_away_agency,
    get_account,
    get_success_data,
    make_account_holder_headers,
    setup_agency_pair,
    setup_full_account,
    validate_error,
)
from test_helpers.factories import (
    create_plate_data_agreement_payload,
    create_rate_schedule_payload,
)

SO = TEST_USERS["settlement_officer_headers"]
AO = TEST_USERS["agency_ops_headers"]


def test_rate_schedule_window_half_open_overlap():
    """PRD §3.1: "The window is half-open: a schedule is usable at
    `effective_from` and stops being usable at `effective_to`. Schedules are
    created in `ACTIVE` status; if the requested window overlaps the window of
    any existing `ACTIVE` schedule for the same agency, plaza, and class,
    creation is rejected with `ERR_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_schedule_window_half_open_overlap
    """
    away = create_away_agency()
    create_rate_schedule(
        away["id"], base_rate_cents=800,
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-10-01T00:00:00Z",
    )
    # Adjacent (starts exactly at the previous effective_to): accepted.
    resp_adj = api_client.create_rate_schedule(
        away["id"],
        create_rate_schedule_payload(
            base_rate_cents=850,
            effective_from="2026-10-01T00:00:00Z",
            effective_to="2026-11-01T00:00:00Z",
        ),
        AO,
    )
    assert resp_adj.status_code == 201
    assert resp_adj.json()["data"]["id"]

    # One second earlier: overlaps the first window -> rejected.
    resp_ovl = api_client.create_rate_schedule(
        away["id"],
        create_rate_schedule_payload(
            base_rate_cents=860,
            effective_from="2026-09-30T23:59:59Z",
            effective_to="2026-11-01T00:00:00Z",
        ),
        AO,
    )
    validate_error(resp_ovl, ApiErrorId.ERR_SCHEDULE_OVERLAP)


def test_plate_agreement_shared_state_overlap():
    """PRD §3.9: "Agreements are created `ACTIVE`; if an existing `ACTIVE`
    agreement for the same requesting-providing pair already covers any shared
    state with an overlapping validity window, creation is rejected with
    `ERR_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/plate_agreement_shared_state_overlap
    """
    away = create_away_agency()
    prov = create_home_agency(agency_code="PROV", name="Prov DMV Proxy", home_state="CT")
    resp1 = api_client.create_plate_data_agreement(
        create_plate_data_agreement_payload(
            requesting_agency_id=away["id"],
            providing_agency_id=prov["id"],
            covers_states=["NY", "NJ"],
        ),
        SO,
    )
    assert resp1.status_code == 201

    # Disjoint state set with fully overlapping time: accepted.
    resp2 = api_client.create_plate_data_agreement(
        create_plate_data_agreement_payload(
            requesting_agency_id=away["id"],
            providing_agency_id=prov["id"],
            effective_from="2026-10-01T00:00:00Z",
            effective_to="2027-10-01T00:00:00Z",
            covers_states=["PA", "CT"],
        ),
        SO,
    )
    assert resp2.status_code == 201
    assert resp2.json()["data"]["id"]

    # Shared state (NY) with overlapping time: rejected.
    resp3 = api_client.create_plate_data_agreement(
        create_plate_data_agreement_payload(
            requesting_agency_id=away["id"],
            providing_agency_id=prov["id"],
            effective_from="2026-10-01T00:00:00Z",
            effective_to="2027-10-01T00:00:00Z",
            covers_states=["NY"],
        ),
        SO,
    )
    validate_error(resp3, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_account_close_cascades_transponder_retirement():
    """PRD §3.5: "On closure the account moves from `ACTIVE` to `CLOSED`, the
    remaining `balance_cents` is paid out to the holder and set to zero, and
    every transponder on the account transitions from `ACTIVE` to `RETIRED`."

    Design: Corner/state_machines/account_close_cascades_transponder_retirement
    """
    home = create_home_agency()
    plan = create_discount_plan(home["id"])
    account = create_account(
        home["id"], plan["id"], holder_name="Cleo Close",
        holder_email="cleo@example.com", opening_balance_cents=0,
    )
    tg1 = create_transponder(account["id"], tag_number="TAG-C1", plate_number="CLS101")
    tg2 = create_transponder(account["id"], tag_number="TAG-C2", plate_number="CLS102")
    holder = make_account_holder_headers(account["id"])
    get_success_data(api_client.report_lost(tg2["id"], holder))

    resp = api_client.close_account(account["id"], holder)
    assert resp.status_code == 200
    closed = get_account(account["id"])
    assert closed["status"] == "CLOSED"
    assert closed["balance_cents"] == 0

    assert get_success_data(api_client.get_transponder(tg1["id"], AO))["status"] == "RETIRED"
    assert get_success_data(api_client.get_transponder(tg2["id"], AO))["status"] == "REPORTED_LOST"


def test_toll_void_restores_balance_exactly():
    """PRD §3.4: "the cap is never redistributed retroactively, so an earlier
    trip keeps its full discount even if a later trip is voided — voiding does
    not restore `discount_used_today_cents`."
    PRD §4: "Void a posted transaction and credit the account"

    Design: Difficulty/compensating_invariant/toll_void_restores_balance_exactly
    """
    home, away = setup_agency_pair()
    create_rate_schedule(away["id"], base_rate_cents=800)
    plan = create_discount_plan(
        home["id"], plan_code="PROMO20", discount_pct=0.20,
        daily_discount_cap_cents=0, applies_to_agency_codes=[away["agency_code"]],
    )
    account = create_account(
        home["id"], plan["id"], holder_name="Ivy Void",
        holder_email="ivy@example.com", opening_balance_cents=5000,
    )
    create_transponder(account["id"], tag_number="TAG-I", plate_number="VOID01")
    txn = get_success_data(
        api_client.post_toll_transaction(
            {"tag_number": "TAG-I", "away_agency_id": away["id"], "plaza_code": "P1",
             "trip_timestamp": "2026-09-11T09:00:00Z", "is_peak": False,
             "idempotency_key": "i1"}, AO,
        )
    )
    assert txn["charged_amount_cents"] == 640

    resp = api_client.void_toll_transaction(txn["id"], AO)
    assert resp.status_code == 200
    assert get_success_data(api_client.get_toll_transaction(txn["id"], AO))["status"] == "VOIDED"

    acct = get_account(account["id"])
    assert acct["balance_cents"] == 5000
    assert acct["discount_used_today_cents"] == 160


def test_existence_precedes_state_on_nested_path():
    """PRD §2.8: "Endpoints whose paths nest resources (for example, a rate
    schedule created beneath an agency, or a transponder beneath an account)
    validate path identifiers strictly left to right: each identifier must name
    an existing resource before the next is examined, and the first
    non-existent identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/existence_precedes_state_on_nested_path
    """
    resp = api_client.void_toll_transaction(NON_EXISTENT_UUID, AO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
