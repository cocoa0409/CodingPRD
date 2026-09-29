"""Composite setup helpers.

Each test starts against an empty database, so every helper here builds its
preconditions from scratch using only endpoints the PRD declares. Setup calls
go through the lenient validator so a broken precondition reports itself as a
setup failure rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    ANALYST_HEADERS,
    OPERATOR_HEADERS,
    make_member_headers,
    make_resort_manager_headers,
)

# ----------------------------------------------------------------- reads

def read_member(member_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_member(member_id, headers or OPERATOR_HEADERS)
    )


def read_resort(resort_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_resort(resort_id, headers or OPERATOR_HEADERS)
    )


def read_deposit(deposit_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_deposit(deposit_id, headers or OPERATOR_HEADERS)
    )


def read_deposit_valuation(deposit_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_deposit_valuation(deposit_id, headers or OPERATOR_HEADERS)
    )


def read_exchange_request(request_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_exchange_request(request_id, headers or OPERATOR_HEADERS)
    )


def read_confirmation(confirmation_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_confirmation(confirmation_id, headers or OPERATOR_HEADERS)
    )


def read_getaway_offer(offer_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_getaway_offer(offer_id, headers or OPERATOR_HEADERS)
    )


def read_dispute(dispute_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_dispute(dispute_id, headers or ANALYST_HEADERS)
    )


def read_compliance(resort_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_resort_compliance(resort_id, headers or OPERATOR_HEADERS)
    )


def list_page(response) -> tuple:
    """Return (rows, meta) from a 200 list response during setup."""
    body = response.json()
    assert response.status_code == 200, (
        f"Setup list call failed with HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]


def list_ledger_entries(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_ledger_entries(headers or OPERATOR_HEADERS, params=params or None)
    )


def list_deposits(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_deposits(headers or OPERATOR_HEADERS, params=params or None)
    )


def list_exchange_requests(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_exchange_requests(
            headers or OPERATOR_HEADERS, params=params or None
        )
    )


def list_getaway_offers(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_getaway_offers(headers or OPERATOR_HEADERS, params=params or None)
    )


def list_quality_reviews(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_quality_reviews(
            headers or OPERATOR_HEADERS, params=params or None
        )
    )


def list_matching_runs(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_matching_runs(headers or OPERATOR_HEADERS, params=params or None)
    )


def list_confirmations(headers=None, **params) -> tuple:
    return list_page(
        api_client.list_confirmations(headers or OPERATOR_HEADERS, params=params or None)
    )


# --------------------------------------------------------- primitive writes

def create_tier(**overrides) -> dict:
    """Create a membership tier; defaults to the PLUS fee schedule."""
    return get_success_data(
        api_client.create_membership_tier(
            factories.membership_tier_payload(**overrides), OPERATOR_HEADERS
        )
    )


def create_resort(**overrides) -> dict:
    """Register a resort; it opens as PENDING_AFFILIATION."""
    return get_success_data(
        api_client.create_resort(factories.resort_payload(**overrides), OPERATOR_HEADERS)
    )


def create_season_band(resort_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_season_band(
            factories.season_band_payload(resort_id, **overrides), OPERATOR_HEADERS
        )
    )


def grant_affiliation(resort_id) -> dict:
    return get_success_data(
        api_client.grant_resort_affiliation(resort_id, OPERATOR_HEADERS)
    )


def change_resort_status(resort_id, to_status, reason=None) -> dict:
    return get_success_data(
        api_client.change_resort_status(
            resort_id,
            factories.resort_status_change_payload(to_status, reason),
            OPERATOR_HEADERS,
        )
    )


def setup_affiliated_resort(
    band_code="GOLD",
    band_start_month_day="04-01",
    band_end_month_day="06-30",
    extra_bands=(),
    **resort_overrides,
) -> dict:
    """Register a resort, publish its season calendar and grant affiliation."""
    resort = create_resort(**resort_overrides)
    create_season_band(
        resort["id"],
        band_code=band_code,
        start_month_day=band_start_month_day,
        end_month_day=band_end_month_day,
    )
    for band in extra_bands:
        create_season_band(resort["id"], **band)
    return grant_affiliation(resort["id"])


def create_member(tier_id, **overrides) -> dict:
    """Enrol a member; it opens as PENDING_PAYMENT with zero balances."""
    return get_success_data(
        api_client.create_member(
            factories.member_payload(tier_id, **overrides), OPERATOR_HEADERS
        )
    )


def pay_dues(member, amount_cents=100000, paid_through_date="2030-12-31") -> dict:
    """Record a dues payment using the member's currently observed version."""
    return get_success_data(
        api_client.create_dues_payment(
            member["id"],
            factories.dues_payment_payload(
                member["version"],
                amount_cents=amount_cents,
                paid_through_date=paid_through_date,
            ),
            make_member_headers(member["id"]),
        )
    )


def create_active_member(
    tier_id,
    email="m1@example.com",
    full_name="Dana Oyelaran",
    amount_cents=100000,
    paid_through_date="2030-12-31",
    **overrides,
) -> dict:
    """Enrol a member and activate it with one dues payment."""
    member = create_member(tier_id, email=email, full_name=full_name, **overrides)
    return pay_dues(
        member, amount_cents=amount_cents, paid_through_date=paid_through_date
    )


def bank_deposit(
    member_id, resort_id, unit_size="ONE_BR", check_in_date="2027-06-15", **overrides
) -> dict:
    return get_success_data(
        api_client.create_deposit(
            factories.deposit_payload(
                member_id,
                resort_id,
                unit_size=unit_size,
                check_in_date=check_in_date,
                **overrides,
            ),
            make_member_headers(member_id),
        )
    )


def file_exchange_request(
    member_id,
    requested_resort_id,
    requested_unit_size="ONE_BR",
    window_start_date="2027-06-01",
    window_end_date="2027-06-30",
    deposit_id=None,
) -> dict:
    payload = factories.exchange_request_payload(
        member_id,
        requested_resort_id,
        requested_unit_size=requested_unit_size,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
    )
    if deposit_id is not None:
        payload["deposit_id"] = deposit_id
    return get_success_data(
        api_client.create_exchange_request(payload, make_member_headers(member_id))
    )


def attach_funding(request_id, member_id, deposit_id) -> dict:
    return get_success_data(
        api_client.attach_request_funding(
            request_id, {"deposit_id": deposit_id}, make_member_headers(member_id)
        )
    )


def run_matching(note="operations run") -> dict:
    return get_success_data(
        api_client.create_matching_run(
            factories.matching_run_payload(note), OPERATOR_HEADERS
        )
    )


def set_clock(to_iso8601) -> dict:
    return get_success_data(
        api_client.set_clock(factories.clock_payload(to_iso8601), OPERATOR_HEADERS)
    )


def confirm_request(member_id, request_id) -> dict:
    return get_success_data(
        api_client.create_confirmation(
            factories.confirmation_payload(request_id), make_member_headers(member_id)
        )
    )


def cancel_confirmation(confirmation_id, member_id) -> dict:
    return get_success_data(
        api_client.cancel_confirmation(
            confirmation_id, make_member_headers(member_id)
        )
    )


def reinstate_confirmation(confirmation_id, member_id) -> dict:
    return get_success_data(
        api_client.reinstate_confirmation(
            confirmation_id, make_member_headers(member_id)
        )
    )


def cancel_request(request_id, member_id) -> dict:
    return get_success_data(
        api_client.cancel_exchange_request(request_id, make_member_headers(member_id))
    )


def decline_match(request_id, member_id) -> dict:
    return get_success_data(
        api_client.decline_match(request_id, make_member_headers(member_id))
    )


def withdraw_deposit(deposit_id, member_id) -> dict:
    return get_success_data(
        api_client.withdraw_deposit(deposit_id, make_member_headers(member_id))
    )


def buy_extension(deposit_id, member_id, months, expected_deposit_version) -> dict:
    return get_success_data(
        api_client.create_deposit_extension(
            deposit_id,
            factories.extension_payload(months, expected_deposit_version),
            make_member_headers(member_id),
        )
    )


def book_getaway(offer_id, member_id) -> dict:
    return get_success_data(
        api_client.book_getaway_offer(
            offer_id,
            factories.getaway_booking_payload(member_id),
            make_member_headers(member_id),
        )
    )


def withdraw_getaway(offer_id) -> dict:
    return get_success_data(
        api_client.withdraw_getaway_offer(offer_id, OPERATOR_HEADERS)
    )


def file_quality_review(
    resort_id,
    member_id,
    confirmation_id,
    expected_resort_version,
    cleanliness_score=9,
    service_score=8,
    amenities_score=7,
) -> dict:
    return get_success_data(
        api_client.create_quality_review(
            resort_id,
            factories.quality_review_payload(
                confirmation_id,
                expected_resort_version,
                cleanliness_score=cleanliness_score,
                service_score=service_score,
                amenities_score=amenities_score,
            ),
            make_member_headers(member_id),
        )
    )


def file_trading_power_dispute(member_id, deposit_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_dispute(
            factories.trading_power_dispute_payload(
                member_id, deposit_id, **overrides
            ),
            make_member_headers(member_id),
        )
    )


def file_resort_quality_dispute(member_id, resort_id, confirmation_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_dispute(
            factories.resort_quality_dispute_payload(
                member_id, resort_id, confirmation_id, **overrides
            ),
            make_member_headers(member_id),
        )
    )


def open_dispute_review(dispute_id) -> dict:
    return get_success_data(api_client.review_dispute(dispute_id, ANALYST_HEADERS))


def request_dispute_info(dispute_id, question="Please send the arrival photographs.") -> dict:
    return get_success_data(
        api_client.request_dispute_info(
            dispute_id, factories.dispute_info_request_payload(question), ANALYST_HEADERS
        )
    )


def respond_to_dispute(dispute_id, member_id, answer="Photographs attached.") -> dict:
    return get_success_data(
        api_client.respond_to_dispute(
            dispute_id,
            factories.dispute_response_payload(answer),
            make_member_headers(member_id),
        )
    )


def resolve_dispute(dispute_id, outcome, resolution_note, **overrides) -> dict:
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id,
            factories.dispute_resolution_payload(outcome, resolution_note, **overrides),
            ANALYST_HEADERS,
        )
    )


# ------------------------------------------------------- composite scenarios

MEMBER_PROFILES = (
    ("m1@example.com", "Dana Oyelaran"),
    ("m2@example.com", "Ravi Bergqvist"),
    ("m3@example.com", "Ines Kowalczyk"),
    ("m4@example.com", "Yara Mbeki"),
    ("m5@example.com", "Piotr Sandoval"),
)


def setup_market(
    member_count=1,
    tier_overrides=None,
    resort_overrides=None,
    band_code="GOLD",
    band_start_month_day="04-01",
    band_end_month_day="06-30",
    extra_bands=(),
    dues_amount_cents=100000,
    paid_through_date="2030-12-31",
) -> dict:
    """A tier, one affiliated resort with a season calendar, and N active members.

    Each member pays 100000 against the PLUS annual dues of 19900, so every
    member opens with a wallet of 80100 and a trading power balance of 0.
    """
    tier = create_tier(**(tier_overrides or {}))
    resort = setup_affiliated_resort(
        band_code=band_code,
        band_start_month_day=band_start_month_day,
        band_end_month_day=band_end_month_day,
        extra_bands=extra_bands,
        **(resort_overrides or {}),
    )
    members = []
    for index in range(member_count):
        email, full_name = MEMBER_PROFILES[index]
        members.append(
            create_active_member(
                tier["id"],
                email=email,
                full_name=full_name,
                amount_cents=dues_amount_cents,
                paid_through_date=paid_through_date,
            )
        )
    return {"tier": tier, "resort": resort, "members": members}


def setup_banked_week(
    unit_size="ONE_BR", check_in_date="2027-06-15", **market_kwargs
) -> dict:
    """One active member holding one banked week at an affiliated resort."""
    market = setup_market(member_count=1, **market_kwargs)
    member = market["members"][0]
    deposit = bank_deposit(
        member["id"], market["resort"]["id"], unit_size=unit_size,
        check_in_date=check_in_date,
    )
    market["member"] = member
    market["deposit"] = deposit
    return market


def setup_two_sided_inventory(member_count=2, **market_kwargs) -> dict:
    """Two active members, each with one banked week of a different unit size.

    M1 banks a ONE_BR week checking in 2027-06-15 and M2 banks a TWO_BR week
    checking in 2027-05-10, so the two occupancy intervals never overlap.
    """
    market = setup_market(member_count=member_count, **market_kwargs)
    m1, m2 = market["members"][0], market["members"][1]
    dep_m1 = bank_deposit(
        m1["id"], market["resort"]["id"], unit_size="ONE_BR",
        check_in_date="2027-06-15",
    )
    dep_m2 = bank_deposit(
        m2["id"], market["resort"]["id"], unit_size="TWO_BR",
        check_in_date="2027-05-10",
    )
    market.update({"m1": m1, "m2": m2, "dep_m1": dep_m1, "dep_m2": dep_m2})
    return market


def setup_matched_exchange(
    window_start_date="2027-06-15",
    window_end_date="2027-06-15",
    member_count=2,
    **market_kwargs,
) -> dict:
    """M2 files a DEPOSIT_FIRST request that a run matches to M1's ONE_BR week."""
    scenario = setup_two_sided_inventory(member_count=member_count, **market_kwargs)
    request = file_exchange_request(
        scenario["m2"]["id"],
        scenario["resort"]["id"],
        requested_unit_size="ONE_BR",
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        deposit_id=scenario["dep_m2"]["id"],
    )
    run = run_matching("match the pinned window")
    scenario["request"] = read_exchange_request(request["id"])
    scenario["run"] = run
    return scenario


def setup_confirmed_exchange(**kwargs) -> dict:
    """A matched request converted into a CONFIRMED confirmation by its member."""
    scenario = setup_matched_exchange(**kwargs)
    confirmation = confirm_request(scenario["m2"]["id"], scenario["request"]["id"])
    scenario["confirmation"] = confirmation
    return scenario


def setup_completed_stay(completion_clock="2027-06-22T00:00:00Z", **kwargs) -> dict:
    """A confirmed exchange carried through to COMPLETED by a later run."""
    scenario = setup_confirmed_exchange(**kwargs)
    set_clock(completion_clock)
    scenario["completion_run"] = run_matching("complete the stay")
    scenario["confirmation"] = read_confirmation(scenario["confirmation"]["id"])
    return scenario


def setup_prorated_cancellation(
    cancellation_clock="2027-05-17T00:00:00Z", member_count=3, **kwargs
) -> dict:
    """A confirmation cancelled fewer than 30 days before the awarded arrival.

    The awarded week is M1's ONE_BR week checking in 2027-06-15, so cancelling
    at 2027-05-17 leaves 29 whole days and takes the prorated branch, which
    lists the returned week on the getaway market.
    """
    scenario = setup_confirmed_exchange(member_count=member_count, **kwargs)
    set_clock(cancellation_clock)
    scenario["cancelled_confirmation"] = cancel_confirmation(
        scenario["confirmation"]["id"], scenario["m2"]["id"]
    )
    offers, _ = list_getaway_offers(deposit_id=scenario["dep_m1"]["id"])
    scenario["offer"] = offers[0] if offers else None
    return scenario


def setup_full_restore_cancellation(
    cancellation_clock="2027-05-16T00:00:00Z", member_count=2, **kwargs
) -> dict:
    """A confirmation cancelled exactly 30 days before the awarded arrival."""
    scenario = setup_confirmed_exchange(member_count=member_count, **kwargs)
    set_clock(cancellation_clock)
    scenario["cancelled_confirmation"] = cancel_confirmation(
        scenario["confirmation"]["id"], scenario["m2"]["id"]
    )
    return scenario


def setup_dispute_under_review(**kwargs) -> dict:
    """A trading-power dispute taken into analyst review."""
    scenario = setup_banked_week(**kwargs)
    dispute = file_trading_power_dispute(
        scenario["member"]["id"], scenario["deposit"]["id"]
    )
    scenario["dispute"] = open_dispute_review(dispute["id"])
    return scenario
