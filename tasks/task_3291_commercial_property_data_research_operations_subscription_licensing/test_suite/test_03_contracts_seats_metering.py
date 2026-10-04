"""Subscription contracts, license seats, metering and usage monitoring."""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    set_logical_clock,
    setup_active_contract,
    setup_brokerage_org,
    setup_subscriber_org,
    validate_error,
    validate_success,
)


def test_metered_overage_is_zero_at_the_included_day_boundary(api):
    """PRD §3.10: "The subscription includes the first 2 active days in a cycle, the `INCLUDED_ACTIVE_DAYS` constant, so the chargeable quantity is the number of active days that exceed that allowance: the seat's `monthly_active_days` minus 2, floored at zero so a seat that never exceeds the allowance carries no charge."

    PRD §3.9: "`monthly_active_days` counts the distinct calendar days, in UTC, on which the seat recorded at least one event — several events on one day count once, and the logical clock's date defines \"today\"."

    Design: Difficulty/boundary_precision_check/seat_active_day_count_crosses_the_overage_inclusion_boundary
    """
    set_logical_clock("2026-04-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, last_usage_cycle="2026-04-01T00:00:00Z",
    )
    headers = active["occupant_headers"]
    for occurred in ("2026-04-01T09:00:00Z", "2026-04-02T09:00:00Z"):
        validate_success(
            api.create_usage_event(
                active["seat"]["id"],
                {"market": "TX-DALLAS", "event_type": "API_QUERY", "record_count": 4,
                 "distinguishing_ip": "203.0.113.7", "occurred_at": occurred},
                headers,
            ),
            201,
        )
    seat = get_success_data(
        api.get_seat(active["seat"]["id"], active["admin_headers"])
    )
    # Two distinct UTC calendar days: exactly the INCLUDED_ACTIVE_DAYS allowance.
    assert seat["monthly_active_days"] == 2
    assert seat["overage_fee_cents"] == 0


def test_metered_overage_is_charged_one_day_past_the_boundary(api):
    """PRD §3.10: "A `TIER_2` seat is charged 900 cents, the `TIER_2_DAILY_RATE_CENTS` constant."

    PRD §3.10: "The seat's `overage_fee_cents` is then the lesser of the uncapped overage and the cap, and the cap is inclusive: an overage exactly equal to the cap is charged at the cap rather than above it."

    Design: Difficulty/boundary_precision_check/seat_active_day_count_crosses_the_overage_inclusion_boundary
    """
    set_logical_clock("2026-04-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, last_usage_cycle="2026-04-01T00:00:00Z",
    )
    headers = active["occupant_headers"]
    for occurred in ("2026-04-01T09:00:00Z", "2026-04-02T09:00:00Z"):
        validate_success(
            api.create_usage_event(
                active["seat"]["id"],
                {"market": "TX-DALLAS", "event_type": "API_QUERY", "record_count": 4,
                 "distinguishing_ip": "203.0.113.7", "occurred_at": occurred},
                headers,
            ),
            201,
        )
    validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    at_boundary = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    assert at_boundary["monthly_active_days"] == 2
    assert at_boundary["overage_fee_cents"] == 0

    validate_success(
        api.create_usage_event(
            active["seat"]["id"],
            {"market": "TX-DALLAS", "event_type": "API_QUERY", "record_count": 4,
             "distinguishing_ip": "203.0.113.7", "occurred_at": "2026-04-03T09:00:00Z"},
            headers,
        ),
        201,
    )
    validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    past_boundary = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    assert past_boundary["monthly_active_days"] == 3
    # one chargeable day (3 - 2) at the TIER_2 daily rate of 900 cents.
    assert past_boundary["overage_fee_cents"] == 900


def test_metered_overage_is_capped_at_the_share_of_the_annual_fee(api):
    """PRD §3.10: "A seat with no unauthorized-market observations is capped at 250 basis points — 2.50 percent — of the contract's `annual_fee_cents`, the `LICENSED_MARKET_USAGE_LIMIT_BPS` constant."

    PRD §3.10: "And a clean `TIER_1` seat with five active days on a contract whose annual fee is 100,000 cents — the `no_violation_cycle` case — is capped early: its uncapped overage would be 3,750 cents, but the 250-basis-point cap binds it to 2,500 cents, exactly 2.50 percent of the contract fee."

    Design: Difficulty/boundary_precision_check/seat_active_day_count_crosses_the_overage_inclusion_boundary
    """
    set_logical_clock("2026-04-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, index_tier="TIER_1",
        last_usage_cycle="2026-04-01T00:00:00Z",
    )
    headers = active["occupant_headers"]
    for day in range(1, 6):
        validate_success(
            api.create_usage_event(
                active["seat"]["id"],
                {"market": "TX-DALLAS", "event_type": "API_QUERY", "record_count": 4,
                 "distinguishing_ip": "203.0.113.7",
                 "occurred_at": f"2026-04-0{day}T09:00:00Z"},
                headers,
            ),
            201,
        )
    seat = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    assert seat["monthly_active_days"] == 5
    assert seat["overage_fee_cents"] == 2500


def test_seat_occupancy_and_access_axes_diverge_on_one_row(api):
    """PRD §3.6: "The third movement out of `ASSIGNED` is to the terminal state `REVOKED`, which is never requested directly: the server revokes a seat automatically when its contract reaches `LAPSED` or `TERMINATED`, and when a litigation escalation targets the seat's contract."

    PRD §3.6: "Revocation sets `access_revoked` to true and clears `shared_flag` back to false."

    Design: Difficulty/non_linear_state_machine/seat_parallel_dimensions_assignment_and_access_on_one_row
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, term_start="2025-09-10T00:00:00Z",
        term_end="2026-09-10T00:00:00Z", renewal_notice_days=31,
        last_usage_cycle="2026-08-15T00:00:00Z",
    )
    set_logical_clock("2026-09-15T00:00:00Z")
    validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    seat = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    contract = get_success_data(
        api.get_contract(active["contract"]["id"], active["admin_headers"])
    )
    assert contract["status"] == "LAPSED"
    assert contract["renewal_decision"] == "FAILED"
    assert seat["access_revoked"] is True
    assert seat["occupant_user_id"] == active["occupant"]["id"]


def test_revoked_seat_occupancy_axis_remains_mutable(api):
    """PRD §3.6: "Releasing an occupant moves a seat from `ASSIGNED` back to `UNASSIGNED` and requires only that the seat currently have a non-null occupant — anything else is refused with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/seat_parallel_dimensions_assignment_and_access_on_one_row
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, term_start="2025-09-10T00:00:00Z",
        term_end="2026-09-10T00:00:00Z", renewal_notice_days=31,
        last_usage_cycle="2026-08-15T00:00:00Z",
    )
    set_logical_clock("2026-09-15T00:00:00Z")
    validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    released = validate_success(
        api.unassign_seat(
            active["contract"]["id"], active["seat"]["id"],
            {"expected_contract_version": get_success_data(
                api.get_contract(active["contract"]["id"], active["admin_headers"])
            )["version"]},
            active["admin_headers"],
        ),
        200,
    )
    assert released["occupant_user_id"] is None
    assert released["access_revoked"] is True


def test_seat_deactivation_is_archival_and_blocks_reassignment(api):
    """PRD §3.11: "A deactivated user remains readable and continues to be named on the historical records they touched — attributes they created, verdicts they reached and cases they filed all keep their reference — and any seat whose `occupant_user_id` equals that user keeps its occupant but may never be reassigned to them."

    PRD §3.6: "the nominated user's `status` must be `ACTIVE`, or the request is refused with `ERR_USER_INACTIVE` (HTTP 409)"

    Design: Corner/cross_cutting_complexity_layers/soft_delete_seat_deactivation_keeps_history_visible
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    target = subscriber["seat_users"][0]
    active = setup_active_contract(subscriber, assign_occupant=False, annual_fee_cents=100_000)
    deactivated = validate_success(
        api.deactivate_user(target["id"], active["admin_headers"]), 200
    )
    assert deactivated["status"] == "INACTIVE"
    still_readable = get_success_data(api.get_user(target["id"], active["admin_headers"]))
    assert still_readable["status"] == "INACTIVE"

    resp = api.assign_seat(
        active["contract"]["id"], active["seat"]["id"],
        {"occupant_user_id": target["id"],
         "expected_contract_version": get_success_data(
             api.get_contract(active["contract"]["id"], active["admin_headers"])
         )["version"]},
        active["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_USER_INACTIVE)
    assert resp.status_code == 409
    seat = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    assert seat["occupant_user_id"] is None


def test_contract_activation_with_no_seats_returns_no_seats(api):
    """PRD §3.6: "At least one `LicenseSeat` must exist on the contract, or the request is refused with `ERR_NO_SEATS` (HTTP 409)."

    Design: Corner/errors/contract_activation_with_no_seats_returns_no_seats
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    from test_helpers import create_contract

    contract = create_contract(subscriber["org"]["id"], subscriber["admin_headers"])
    resp = api.activate_contract(
        contract["id"],
        {"expected_contract_version": contract["version"]},
        subscriber["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NO_SEATS)
    assert resp.status_code == 409
    assert get_success_data(
        api.get_contract(contract["id"], subscriber["admin_headers"])
    )["status"] == "PENDING"


def test_broker_publisher_cannot_activate_a_licensing_contract_returns_unauthorized(api):
    """PRD §2.1: "A request whose acting role is not permitted for the operation being attempted is rejected with `ERR_UNAUTHORIZED` and carries HTTP status 403."

    Design: Corner/rbac/broker_publisher_cannot_activate_a_licensing_contract_returns_unauthorized
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    brokerage = setup_brokerage_org(with_admin=True)
    from test_helpers import create_contract, create_seat

    contract = create_contract(
        brokerage["org"]["id"], brokerage["admin_headers"], product="LISTING_SERVICE",
        licensed_markets=["TX-DALLAS"], seat_count=3, annual_fee_cents=50_000,
    )
    create_seat(contract["id"], brokerage["admin_headers"], market="TX-DALLAS",
                last_usage_cycle="2026-09-01T00:00:00Z")
    resp = api.activate_contract(
        contract["id"],
        {"expected_contract_version": contract["version"]},
        brokerage["publisher_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    assert get_success_data(
        api.get_contract(contract["id"], brokerage["admin_headers"])
    )["status"] == "PENDING"
    # Creating the seat incremented the contract's version, so the successful
    # activation must carry the version the client has actually observed.
    current_version = get_success_data(
        api.get_contract(contract["id"], brokerage["admin_headers"])
    )["version"]
    validate_success(
        api.activate_contract(
            contract["id"],
            {"expected_contract_version": current_version},
            brokerage["admin_headers"],
        ),
        200,
    )


def test_market_addition_fee_applies_the_product_factor_and_the_service_tier(api):
    """PRD §3.10: "The first stage takes 8 percent of the contract's current `annual_fee_cents` — the `MARKET_ADD_BASE_PCT` constant — and rounds half up to a whole cent."

    PRD §3.10: "The third stage multiplies that gross figure by a factor drawn from the subscriber organization's `service_tier`: 0.80 for `ENTERPRISE`, 1.00 for `MID_MARKET`, and 1.15 for `SMB`, the fall-through case"

    PRD §3.10: "The clearest illustration of the tier stage is the `enterprise_discount` variant, in which an `ENTERPRISE` `CORE_MARKET_DATA` contract applies the 0.80 factor after the product factor so that an added market costs eighty percent of the gross addition."

    Design: Difficulty/combinatorial_formula/market_addition_fee_nested_product_and_tier_branching
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    enterprise = setup_subscriber_org(
        org_name="Enterprise Subscriber Inc", service_tier="ENTERPRISE",
    )
    ent_active = setup_active_contract(
        enterprise, annual_fee_cents=100_000, licensed_markets=["TX-DALLAS"],
    )
    ent_resp = validate_success(
        api.add_contract_market(
            ent_active["contract"]["id"],
            {"market": "TX-HOUSTON", "expected_contract_version": get_success_data(
                api.get_contract(ent_active["contract"]["id"], ent_active["admin_headers"])
            )["version"]},
            ent_active["admin_headers"],
        ),
        200,
    )
    # 8% of 100,000 = 8,000; CORE_MARKET_DATA factor 1.25 -> 10,000; ENTERPRISE 0.80 -> 8,000.
    assert ent_resp["annual_fee_cents"] == 108_000

    mid_market = setup_subscriber_org(
        org_name="Mid Market Subscriber Inc", service_tier="MID_MARKET",
    )
    mid_active = setup_active_contract(
        mid_market, annual_fee_cents=100_000, licensed_markets=["TX-DALLAS"],
    )
    mid_resp = validate_success(
        api.add_contract_market(
            mid_active["contract"]["id"],
            {"market": "TX-HOUSTON", "expected_contract_version": get_success_data(
                api.get_contract(mid_active["contract"]["id"], mid_active["admin_headers"])
            )["version"]},
            mid_active["admin_headers"],
        ),
        200,
    )
    # The only differing input is Organization.service_tier: 10,000 at the 1.00 factor.
    assert mid_resp["annual_fee_cents"] == 110_000
    assert ent_resp["annual_fee_cents"] - 100_000 == 8_000
    assert mid_resp["annual_fee_cents"] - 100_000 == 10_000


def test_market_addition_rejects_a_stale_contract_version_and_a_duplicate_market(api):
    """PRD §3.6: "The contract's status must be current and the client's `expected_contract_version` must match, or the request is refused as `ERR_STALE_VERSION` (HTTP 412)."

    PRD §3.6: "The request supplies a `market` that must not already be present in `licensed_markets` — a duplicate is refused with `ERR_MARKET_ALREADY_LICENSED` (HTTP 409)"

    Design: Difficulty/combinatorial_formula/market_addition_fee_nested_product_and_tier_branching
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, licensed_markets=["TX-DALLAS"],
    )
    contract_id = active["contract"]["id"]
    headers = active["admin_headers"]
    stale_version = get_success_data(api.get_contract(contract_id, headers))["version"]

    validate_success(
        api.add_contract_market(
            contract_id, {"market": "TX-HOUSTON", "expected_contract_version": stale_version},
            headers,
        ),
        200,
    )
    stale = api.add_contract_market(
        contract_id, {"market": "TX-AUSTIN", "expected_contract_version": stale_version}, headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    duplicate = api.add_contract_market(
        contract_id,
        {"market": "TX-HOUSTON", "expected_contract_version": get_success_data(
            api.get_contract(contract_id, headers)
        )["version"]},
        headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_MARKET_ALREADY_LICENSED)
    assert duplicate.status_code == 409


def test_market_addition_is_visible_in_the_same_response_it_mutates(api):
    """PRD §2.8: "Both are response-visible attributes of the `Organization` resource, so a client that activates, renews, terminates or lapses a contract will see them move."

    PRD §3.6: "On success the market is appended to `licensed_markets` and the contract's `annual_fee_cents` is increased by the market-addition fee computed in §3.8, the subscriber organization's `authorized_market_count` is recomputed, and the contract's `version` increments."

    Design: Corner/consistency_model/market_addition_is_visible_in_the_same_response_it_mutates
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org(service_tier="ENTERPRISE")
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, licensed_markets=["TX-DALLAS"],
    )
    contract_id = active["contract"]["id"]
    headers = active["admin_headers"]
    version_before = get_success_data(api.get_contract(contract_id, headers))["version"]

    data = validate_success(
        api.add_contract_market(
            contract_id, {"market": "TX-HOUSTON", "expected_contract_version": version_before},
            headers,
        ),
        200,
    )
    assert data["licensed_markets"] == ["TX-DALLAS", "TX-HOUSTON"]
    # 8% of 100,000 = 8,000; CORE_MARKET_DATA factor 1.25 -> 10,000; ENTERPRISE 0.80 -> 8,000.
    assert data["annual_fee_cents"] == 108_000
    assert data["version"] == version_before + 1

    reread = get_success_data(api.get_contract(contract_id, headers))
    assert reread["licensed_markets"] == data["licensed_markets"]
    assert reread["annual_fee_cents"] == data["annual_fee_cents"]


def test_market_addition_cascade_recomputes_the_organizations_market_count(api):
    """PRD §2.8: "`authorized_market_count` counts the distinct markets taken across this organization's licensing contracts whose status is `PENDING`, `ACTIVE`, `GRACE` or `RENEWED`, reading each contract's `licensed_markets` array."

    Design: Corner/cross_cutting_complexity_layers/market_addition_cascade_recomputes_the_organizations_market_count
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, licensed_markets=["TX-DALLAS"],
    )
    before = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert before["authorized_market_count"] == 1
    validate_success(
        api.add_contract_market(
            active["contract"]["id"],
            {"market": "TX-HOUSTON", "expected_contract_version": get_success_data(
                api.get_contract(active["contract"]["id"], active["admin_headers"])
            )["version"]},
            active["admin_headers"],
        ),
        200,
    )
    after = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert after["authorized_market_count"] == 2


def test_stale_contract_version_on_renewal_returns_stale_version(api):
    """PRD §2.13: "Recording a renewal against a licensing contract requires `expected_contract_version`; this guard exists because a market addition changes both the contract's `licensed_markets` list and its `annual_fee_cents`, so a renewal priced from a stale view would be priced from terms that no longer hold."

    Design: Corner/cross_cutting_complexity_layers/stale_contract_version_on_renewal_returns_stale_version
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, licensed_markets=["TX-DALLAS"],
        term_start="2026-09-01T00:00:00Z", term_end="2027-09-01T00:00:00Z",
    )
    contract_id = active["contract"]["id"]
    headers = active["admin_headers"]
    stale_version = get_success_data(api.get_contract(contract_id, headers))["version"]

    added = validate_success(
        api.add_contract_market(
            contract_id, {"market": "TX-HOUSTON", "expected_contract_version": stale_version},
            headers,
        ),
        200,
    )
    fresh_version = added["version"]

    rejected = api.renew_contract(
        contract_id,
        {"new_term_end": "2028-09-01T00:00:00Z", "new_annual_fee_cents": 200_000,
         "expected_contract_version": stale_version},
        headers,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION)
    assert rejected.status_code == 412

    renewed = validate_success(
        api.renew_contract(
            contract_id,
            {"new_term_end": "2028-09-01T00:00:00Z", "new_annual_fee_cents": 200_000,
             "expected_contract_version": fresh_version},
            headers,
        ),
        200,
    )
    assert renewed["status"] == "RENEWED"
    assert renewed["annual_fee_cents"] == 200_000
    assert renewed["version"] == fresh_version + 1