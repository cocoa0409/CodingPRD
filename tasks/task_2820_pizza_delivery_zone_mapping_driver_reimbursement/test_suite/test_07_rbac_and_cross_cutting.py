"""Identity, authorization and stacked-refusal compliance for the Store Operations API.

The first group of tests pins the three distinct ways a caller is turned away
before any business rule is reached: a role that the endpoint's authorized-role
list does not name (`ERR_UNAUTHORIZED`), a `StoreManager` whose `X-User-ID` is
not the owning store (`ERR_FORBIDDEN_STORE_SCOPE`), and a `Driver` who does not
own the route in hand (`ERR_FORBIDDEN_DRIVER_SCOPE`) — each paired with the
mirror-image proof that a role or an owner the specification does permit
succeeds on the very same call, and with the proof that a refused call applied
no side effect of any kind.

The second group walks scenarios in which several mechanisms bite in one
request: the two expected-parent-version guards on delivery-area publication and
insurance filing, each followed by the retry with the re-read version, and the
cash-on-hand gate that blocks a departure at HTTP 402 until the pouch has been
dropped into the safe.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ADDRESS_COORDS,
    DEFAULT_CLOCK,
    INSURANCE_MIN_LIABILITY_CENTS,
    NOON_CLOCK,
    STORE_DEFAULTS,
)
from test_helpers.test_users import (
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    DISPATCHER_HEADERS,
    make_driver_headers,
    make_manager_headers,
)


def test_five_exclusive_operations_are_each_refused_to_a_role_the_table_does_not_name():
    """Each of the five roles is refused one operation the endpoint table reserves to another role, and none of the five refusals writes anything.

    PRD: "Once both headers are accepted, the presented role must appear in the target endpoint's authorized-role list, which §4 tabulates; otherwise the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation
    """
    delivered_order, world = fx.setup_delivered_order(clock=NOON_CLOCK)
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    address_id = world["addresses"]["A"]["id"]

    ready_order = fx.add_ready_order(store_id, address_id)
    draft_route = fx.open_dispatch(driver_id, "2026-08-05T13:30:00Z")
    complaint = fx.log_complaint(delivered_order["id"], "QUALITY")
    driver_version_before = fx.read_driver(driver_id)["version"]

    # Store registration is reserved to the StoreManager.
    validate_error(
        api_client.create_store(
            f.create_store_payload(store_number="9999", name="Rogue"), DISPATCHER_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    # Stacking an order onto a route is reserved to the Dispatcher.
    validate_error(
        api_client.create_dispatch_stop(
            draft_route["id"],
            {"order_id": ready_order["id"], "hot_bag_slots": 1},
            COMPLIANCE_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    # The make line is reserved to the Dispatcher, and the role gate is evaluated
    # ahead of the order-state check, so a START on a READY order still reports
    # the authorization failure.
    validate_error(
        api_client.production(ready_order["id"], {"action": "START"}, CARE_HEADERS),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    # Pulling a motor-vehicle record is reserved to the ComplianceOfficer.
    validate_error(
        api_client.create_mvr_check(
            driver_id,
            f.create_mvr_check_payload(checked_on="2026-08-05T00:00:00Z"),
            make_driver_headers(driver_id),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    # The manager owns remedy approval but may not author the proposal.
    validate_error(
        api_client.propose_remedy(complaint["id"], make_manager_headers(store_id)),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    # No side effect of any kind was applied. Store numbers are globally unique,
    # so 9999 being free proves the refused registration stored nothing.
    freed = fx.register_store(store_number="9999", name="Rogue")
    assert freed["store_number"] == "9999"
    refused_route = fx.read_dispatch(draft_route["id"])
    assert refused_route["stop_count"] == 0, "the refused insertion created no stop"
    assert refused_route["status"] == "DRAFT"
    assert refused_route["committed_hot_bag_slots"] == 0
    assert fx.read_order(ready_order["id"])["fulfillment_status"] == "READY"
    _pulls, pull_meta = validate_paginated(
        api_client.list_mvr_checks(COMPLIANCE_HEADERS, {"driver_id": driver_id})
    )
    assert pull_meta["total_count"] == 1, "the refused pull was never recorded"
    assert fx.read_driver(driver_id)["version"] == driver_version_before
    refused_complaint = validate_success(
        api_client.get_complaint(complaint["id"], CARE_HEADERS), 200
    )
    assert refused_complaint["status"] == "OPEN"
    assert refused_complaint["proposed_remedy_cents"] is None


def test_the_care_agent_succeeds_on_the_very_proposal_the_manager_was_refused():
    """The manager who will approve a remedy may not author the proposal, while the care agent's identical call on the same OPEN complaint succeeds and sizes the credit.

    PRD: "A **`CustomerCareAgent`** takes phone and web orders, makes the fee-versus-tip disclosure, files and withdraws edge-address disputes, and proposes complaint remedies — but never approves one, which is the manager's decision alone."
    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation
    """
    delivered_order, world = fx.setup_delivered_order(clock=NOON_CLOCK)
    complaint = fx.log_complaint(delivered_order["id"], "QUALITY")

    validate_error(
        api_client.propose_remedy(complaint["id"], make_manager_headers(world["store"]["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )
    refused = validate_success(api_client.get_complaint(complaint["id"], CARE_HEADERS), 200)
    assert refused["status"] == "OPEN"
    assert refused["proposed_remedy_cents"] is None
    assert refused["remedy_basis"] is None

    proposed = validate_success(api_client.propose_remedy(complaint["id"], CARE_HEADERS), 200)
    a.assert_complaint(proposed)
    assert proposed["status"] == "REMEDY_PROPOSED"
    expected_cents, expected_basis = a.expected_remedy(delivered_order, "QUALITY")
    assert proposed["proposed_remedy_cents"] == 1100 == expected_cents
    assert proposed["remedy_basis"] == "QUALITY_HALF" == expected_basis


def test_a_manager_of_another_store_may_neither_read_nor_edit_the_store_it_does_not_own():
    """A StoreManager whose X-User-ID is a different store is refused both the cash-reconciliation read and the policy edit on the store it does not own, yet the same identity works on its own store.

    PRD: "A `StoreManager` whose `X-User-ID` is not the owning store is rejected with `ERR_FORBIDDEN_STORE_SCOPE` (HTTP 403), so the manager of one store can never read or write another store's resources."
    Design: Corner/rbac/a_foreign_manager_and_a_foreign_driver_cannot_touch_what_they_do_not_own
    """
    fx.set_clock(NOON_CLOCK)
    store_a = fx.register_store(store_number="7421", name="Riverside")
    store_b = fx.register_store(store_number="7422", name="Northside")
    foreign_headers = make_manager_headers(store_b["id"])

    validate_error(
        api_client.get_cash_reconciliation(store_a["id"], foreign_headers),
        ApiErrorId.ERR_FORBIDDEN_STORE_SCOPE.value,
    )
    validate_error(
        api_client.update_store(store_a["id"], {"delivery_fee_cents": 999}, foreign_headers),
        ApiErrorId.ERR_FORBIDDEN_STORE_SCOPE.value,
    )

    untouched = validate_success(
        api_client.get_store(store_a["id"], make_manager_headers(store_a["id"])), 200
    )
    assert untouched["delivery_fee_cents"] == STORE_DEFAULTS["delivery_fee_cents"] == 399
    assert untouched["version"] == store_a["version"], "the refused edit moved no version"

    # The same identity is in scope for its own store, so the refusals above are a
    # scope decision rather than a blanket denial of the role.
    own = validate_success(api_client.get_cash_reconciliation(store_b["id"], foreign_headers), 200)
    assert own["store_id"] == store_b["id"]
    assert own["cash_collected_total_cents"] == 0
    a.assert_cash_conservation(own)


def test_a_second_driver_can_neither_depart_nor_knock_on_a_route_owned_by_another_driver():
    """A driver who does not own a locked route is refused both its departure and its door arrival on scope grounds, and the owning driver then departs the untouched route.

    PRD: "One driver may not depart another driver's route, may not record a door arrival on it, may not check it back in, and may not drop cash against another driver's pouch."
    Design: Corner/rbac/a_foreign_manager_and_a_foreign_driver_cannot_touch_what_they_do_not_own
    """
    world = fx.setup_locked_route(
        ("A",), clock=NOON_CLOCK, planned_depart_at="2026-08-05T12:05:00Z"
    )
    route_id = world["dispatch"]["id"]
    stop_id = world["stops"][0]["id"]
    owner_id = world["driver"]["id"]
    intruder = fx.hire_driver(
        world["store"]["id"], full_name="Rex Vale", license_number="DL-1002"
    )
    intruder_headers = make_driver_headers(intruder["id"])

    # The driver-scope check is decided ahead of the qualification check and ahead
    # of every route-state check, so an unqualified intruder is refused on scope.
    validate_error(
        api_client.depart_dispatch(route_id, intruder_headers),
        ApiErrorId.ERR_FORBIDDEN_DRIVER_SCOPE.value,
    )
    validate_error(
        api_client.door_arrival(route_id, stop_id, f.door_arrival_payload(3.40), intruder_headers),
        ApiErrorId.ERR_FORBIDDEN_DRIVER_SCOPE.value,
    )

    still_locked = fx.read_dispatch(route_id)
    assert still_locked["status"] == "LOCKED"
    assert still_locked["departed_at"] is None
    assert still_locked["version"] == world["dispatch"]["version"]
    untouched_stop = fx.read_stop(stop_id)
    assert untouched_stop["status"] == "PENDING"
    assert untouched_stop["arrived_at"] is None
    assert untouched_stop["actual_miles"] is None

    departed = validate_success(
        api_client.depart_dispatch(route_id, make_driver_headers(owner_id)), 200
    )
    a.assert_dispatch(departed)
    assert departed["status"] == "EN_ROUTE"
    a.assert_iso_millis(departed["departed_at"], "departed_at")
    assert a.parse_instant(departed["departed_at"]) == a.parse_instant(NOON_CLOCK)


def test_order_intake_succeeds_for_the_dispatcher_and_for_the_customer_care_agent_alike():
    """Both roles the intake endpoint names can take a ticket against the same address, and each order prices from the store's published policy.

    PRD: "A `Dispatcher` or a `CustomerCareAgent` takes a delivery order."
    Design: Corner/rbac/shared_operations_succeed_for_every_role_the_matrix_lists
    """
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    store_id = store["id"]
    address = fx.add_address(store_id, "A")

    by_dispatcher = validate_success(
        api_client.create_order(
            f.create_order_payload(
                store_id,
                address["id"],
                customer_name="Ann Reed",
                food_subtotal_cents=2200,
                tip_cents=500,
                payment_method="CARD",
            ),
            DISPATCHER_HEADERS,
        ),
        201,
    )
    by_care_agent = validate_success(
        api_client.create_order(
            f.create_order_payload(
                store_id,
                address["id"],
                customer_name="Bo Chen",
                food_subtotal_cents=1500,
                tip_cents=0,
                payment_method="CARD",
            ),
            CARE_HEADERS,
        ),
        201,
    )

    a.assert_order(by_dispatcher)
    a.assert_order(by_care_agent)
    assert by_dispatcher["id"] != by_care_agent["id"]
    assert by_dispatcher["fulfillment_status"] == "PLACED"
    assert by_care_agent["fulfillment_status"] == "PLACED"
    # A 15-minute address sits in the BASE tier for both tickets; 2200 cents of
    # food earns the half waiver while 1500 cents earns none.
    assert by_dispatcher["fee_tier"] == "BASE"
    assert by_dispatcher["fee_waiver_pct"] == 50
    assert by_dispatcher["delivery_fee_cents"] == 200
    assert by_dispatcher["total_charge_cents"] == 2900
    assert by_care_agent["fee_tier"] == "BASE"
    assert by_care_agent["fee_waiver_pct"] == 0
    assert by_care_agent["delivery_fee_cents"] == 399
    assert by_care_agent["total_charge_cents"] == 1899

    _orders, meta = validate_paginated(
        api_client.list_orders(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert meta["total_count"] == 2, "both roles' tickets are on the store's book"


def test_address_filing_succeeds_for_the_manager_and_the_care_agent_beside_the_dispatcher():
    """All three roles the address endpoint names can file an address, and two filings sharing one set of coordinates are each stored in their own right.

    PRD: "Filing an address is open to a `Dispatcher`, a `CustomerCareAgent` or a `StoreManager`, and requires the owning `store_id`, the street line as `line1`, and the geocoded `latitude_micro` and `longitude_micro`."
    Design: Corner/rbac/shared_operations_succeed_for_every_role_the_matrix_lists
    """
    store, _zone_version = fx.bootstrap(NOON_CLOCK)
    store_id = store["id"]
    latitude_micro, longitude_micro = ADDRESS_COORDS["A"]
    by_dispatcher = fx.add_address(store_id, "A")

    by_manager = validate_success(
        api_client.create_service_address(
            f.create_service_address_payload(
                store_id, latitude_micro, longitude_micro, line1="44 Elm St"
            ),
            make_manager_headers(store_id),
        ),
        201,
    )
    by_care_agent = validate_success(
        api_client.create_service_address(
            f.create_service_address_payload(
                store_id, latitude_micro, longitude_micro, line1="45 Elm St"
            ),
            CARE_HEADERS,
        ),
        201,
    )

    a.assert_service_address(by_manager)
    a.assert_service_address(by_care_agent)
    assert len({by_dispatcher["id"], by_manager["id"], by_care_agent["id"]}) == 3
    assert by_manager["line1"] == "44 Elm St"
    assert by_manager["grid_miles"] == 3.00
    assert by_manager["zone_state"] == "IN_ZONE"
    assert by_manager["effective_zone_state"] == "IN_ZONE"
    assert by_care_agent["line1"] == "45 Elm St"
    assert by_care_agent["grid_miles"] == 3.00
    assert by_care_agent["zone_state"] == "IN_ZONE"
    assert by_care_agent["effective_zone_state"] == "IN_ZONE"

    _addresses, meta = validate_paginated(
        api_client.list_service_addresses(DISPATCHER_HEADERS, {"store_id": store_id})
    )
    assert meta["total_count"] == 3


def test_the_clock_capability_is_open_to_a_driver_identity_and_takes_effect():
    """A Driver identity may move the logical clock, the call echoes the instant now in force, and the next record created is stamped from it.

    PRD: "A test-driving capability, available to every role, sets the clock to a supplied `current_utc` instant and echoes back the value now in force."
    Design: Corner/rbac/shared_operations_succeed_for_every_role_the_matrix_lists
    """
    fx.set_clock(NOON_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    assert a.parse_instant(driver["created_at"]) == a.parse_instant(NOON_CLOCK)

    echoed = validate_success(
        api_client.set_clock("2026-08-05T13:00:00Z", make_driver_headers(driver["id"])), 200
    )
    a.assert_iso_millis(echoed["current_utc"], "current_utc")
    assert a.parse_instant(echoed["current_utc"]) == a.parse_instant("2026-08-05T13:00:00Z")

    later = fx.hire_driver(store["id"], full_name="Rex Vale", license_number="DL-1002")
    assert a.parse_instant(later["created_at"]) == a.parse_instant("2026-08-05T13:00:00Z")


def test_publishing_against_the_store_version_read_before_activation_is_refused_as_stale():
    """The registration-time store version is two writes behind once the first delivery area has been published and put in force, so a second publication presented with it is refused and stores nothing.

    PRD: "If that value does not equal the store's current `version`, the request is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/publishing_a_zone_version_against_the_pre_activation_store_version_is_stale
    """
    store, active_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)
    version_at_registration = store["version"]

    validate_error(
        api_client.create_zone_version(
            f.create_zone_version_payload(
                store_id,
                version_at_registration,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_STALE_STORE_VERSION.value,
    )

    # Publishing the first area bumped the store once and putting it in force
    # bumped it again, which is exactly why the registration-time token is stale.
    current = validate_success(api_client.get_store(store_id, manager_headers), 200)
    assert current["version"] == version_at_registration + 2

    _versions, meta = validate_paginated(
        api_client.list_zone_versions(manager_headers, {"store_id": store_id})
    )
    assert meta["total_count"] == 1, "the refused publication stored no delivery-area version"
    incumbent = validate_success(
        api_client.get_zone_version(active_version["id"], manager_headers), 200
    )
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["version_number"] == 1
    assert current["active_zone_version_number"] == 1


def test_the_retry_with_the_re_read_store_version_publishes_the_second_draft():
    """Re-reading the store hands back a usable guard, and the retried publication lands as the second draft while the version in force is left alone.

    PRD: "A newly published version is stamped with a `version_number` equal to the count of that store's pre-existing delivery-area versions plus 1, so the first is 1 and numbering is per store rather than global."
    Design: Corner/cross_cutting_complexity_layers/publishing_a_zone_version_against_the_pre_activation_store_version_is_stale
    """
    store, active_version = fx.bootstrap(DEFAULT_CLOCK)
    store_id = store["id"]
    manager_headers = make_manager_headers(store_id)

    validate_error(
        api_client.create_zone_version(
            f.create_zone_version_payload(
                store_id,
                store["version"],
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            manager_headers,
        ),
        ApiErrorId.ERR_STALE_STORE_VERSION.value,
    )

    fresh_version = validate_success(api_client.get_store(store_id, manager_headers), 200)["version"]
    published = validate_success(
        api_client.create_zone_version(
            f.create_zone_version_payload(
                store_id,
                fresh_version,
                effective_from="2026-09-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            manager_headers,
        ),
        201,
    )
    a.assert_zone_version(published)
    assert published["status"] == "DRAFT"
    assert published["version_number"] == 2
    assert published["activated_at"] is None
    assert published["supersedes_zone_version_id"] is None

    # A draft displaces nothing: the first area is still the one in force.
    incumbent = validate_success(
        api_client.get_zone_version(active_version["id"], manager_headers), 200
    )
    assert incumbent["status"] == "ACTIVE"
    store_after = validate_success(api_client.get_store(store_id, manager_headers), 200)
    assert store_after["active_zone_version_number"] == 1
    _versions, meta = validate_paginated(
        api_client.list_zone_versions(manager_headers, {"store_id": store_id})
    )
    assert meta["total_count"] == 2


def test_filing_a_second_certificate_with_the_pre_filing_driver_version_is_refused_as_stale():
    """The first filing bumps the driver, so a renewal presented with the version read before it is refused and neither supersedes the incumbent certificate nor changes the insurance standing.

    PRD: "If that value does not equal the driver's current `version`, the request is rejected with `ERR_STALE_DRIVER_VERSION` (HTTP 412)."
    Design: Corner/cross_cutting_complexity_layers/filing_a_second_insurance_certificate_with_the_pre_filing_driver_version_is_stale
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    fx.record_mvr_check(
        driver["id"], result="CLEAR", violation_points=0, checked_on="2026-08-01T00:00:00Z"
    )
    version_before_filing = fx.read_driver(driver["id"])["version"]

    incumbent = fx.file_insurance(
        driver["id"],
        policy_number="POL-9001",
        coverage_from="2026-07-01T00:00:00Z",
        coverage_to="2026-12-01T00:00:00Z",
        liability_limit_cents=INSURANCE_MIN_LIABILITY_CENTS,
    )
    assert incumbent["status"] == "VERIFIED"
    assert incumbent["policy_number"] == "POL-9001"

    validate_error(
        api_client.create_insurance_verification(
            driver["id"],
            f.create_insurance_verification_payload(
                version_before_filing,
                policy_number="POL-9002",
                coverage_from="2026-08-01T00:00:00Z",
                coverage_to="2027-08-01T00:00:00Z",
                liability_limit_cents=INSURANCE_MIN_LIABILITY_CENTS,
            ),
            COMPLIANCE_HEADERS,
        ),
        ApiErrorId.ERR_STALE_DRIVER_VERSION.value,
    )

    after = fx.read_driver(driver["id"])
    assert after["version"] == version_before_filing + 1, "only the accepted filing moved the driver"
    assert after["insurance_status"] == "VERIFIED"
    untouched = validate_success(
        api_client.get_insurance_verification(incumbent["id"], COMPLIANCE_HEADERS), 200
    )
    assert untouched["status"] == "VERIFIED"
    assert untouched["version"] == incumbent["version"]
    _certificates, meta = validate_paginated(
        api_client.list_insurance_verifications(COMPLIANCE_HEADERS, {"driver_id": driver["id"]})
    )
    assert meta["total_count"] == 1, "the refused filing stored no certificate"


def test_the_renewal_retried_with_the_re_read_driver_version_supersedes_the_first_certificate():
    """Re-reading the driver after the refusal yields a usable guard, and the accepted renewal moves the earlier certificate to SUPERSEDED while the driver stays insured.

    PRD: "Filing a new certificate moves any previous certificate of that driver to `SUPERSEDED`."
    Design: Corner/cross_cutting_complexity_layers/filing_a_second_insurance_certificate_with_the_pre_filing_driver_version_is_stale
    """
    fx.set_clock(DEFAULT_CLOCK)
    store = fx.register_store()
    driver = fx.hire_driver(store["id"])
    fx.record_mvr_check(
        driver["id"], result="CLEAR", violation_points=0, checked_on="2026-08-01T00:00:00Z"
    )
    version_before_filing = fx.read_driver(driver["id"])["version"]
    incumbent = fx.file_insurance(
        driver["id"],
        policy_number="POL-9001",
        coverage_from="2026-07-01T00:00:00Z",
        coverage_to="2026-12-01T00:00:00Z",
        liability_limit_cents=INSURANCE_MIN_LIABILITY_CENTS,
    )

    renewal_payload = f.create_insurance_verification_payload(
        version_before_filing,
        policy_number="POL-9002",
        coverage_from="2026-08-01T00:00:00Z",
        coverage_to="2027-08-01T00:00:00Z",
        liability_limit_cents=INSURANCE_MIN_LIABILITY_CENTS,
    )
    validate_error(
        api_client.create_insurance_verification(
            driver["id"], renewal_payload, COMPLIANCE_HEADERS
        ),
        ApiErrorId.ERR_STALE_DRIVER_VERSION.value,
    )

    renewal_payload["expected_driver_version"] = fx.read_driver(driver["id"])["version"]
    renewal = validate_success(
        api_client.create_insurance_verification(
            driver["id"], renewal_payload, COMPLIANCE_HEADERS
        ),
        201,
    )
    a.assert_insurance_verification(renewal)
    assert renewal["status"] == "VERIFIED"
    assert renewal["policy_number"] == "POL-9002"

    superseded = validate_success(
        api_client.get_insurance_verification(incumbent["id"], COMPLIANCE_HEADERS), 200
    )
    assert superseded["status"] == "SUPERSEDED"
    assert fx.read_driver(driver["id"])["insurance_status"] == "VERIFIED"
    _certificates, meta = validate_paginated(
        api_client.list_insurance_verifications(COMPLIANCE_HEADERS, {"driver_id": driver["id"]})
    )
    assert meta["total_count"] == 2


def _driver_with_a_loaded_pouch_and_a_second_committed_route():
    """One cash ticket delivered and checked back in against a 2000-cent cash limit,
    followed by a second committed route for the same driver at 13:00.

    The returned mapping is the route mapping with the second committed route
    added under ``second_route``.
    """
    world = fx.setup_returned_route(
        ("A",),
        clock=NOON_CLOCK,
        planned_depart_at="2026-08-05T12:05:00Z",
        store_overrides={"cash_limit_cents": 2000},
        order_overrides={
            "payment_method": "CASH",
            "food_subtotal_cents": 2200,
            "tip_cents": 500,
        },
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    fx.set_clock("2026-08-05T13:00:00Z")
    next_order = fx.add_ready_order(
        store_id,
        world["addresses"]["A"]["id"],
        payment_method="CARD",
        food_subtotal_cents=2200,
        tip_cents=500,
    )
    next_route = fx.open_dispatch(driver_id, "2026-08-05T13:00:00Z")
    fx.stack_stop(next_route["id"], next_order["id"], 1)
    world["second_route"] = fx.lock_route(next_route["id"])
    return world


def test_a_departure_is_refused_at_402_while_the_pouch_is_at_or_over_the_cash_limit():
    """A driver carrying 2900 cents against a 2000-cent limit is already blocked, so the committed route's departure is refused and the route keeps every figure the commitment computed.

    PRD: "A driver holding exactly the limit is already blocked and must visit the safe first; the refusal is `ERR_CASH_LIMIT_REACHED` and it carries HTTP 402."
    Design: Corner/cross_cutting_complexity_layers/a_safe_drop_resets_the_cash_posture_and_unblocks_the_next_departure
    """
    world = _driver_with_a_loaded_pouch_and_a_second_committed_route()
    driver_id = world["driver"]["id"]
    route_id = world["second_route"]["id"]

    before = fx.read_driver(driver_id)
    assert before["cash_on_hand_cents"] == 2900
    assert before["cash_posture"] == "DROP_REQUIRED"

    validate_error(
        api_client.depart_dispatch(route_id, make_driver_headers(driver_id)),
        ApiErrorId.ERR_CASH_LIMIT_REACHED.value,
    )

    refused = fx.read_dispatch(route_id)
    assert refused["status"] == "LOCKED"
    assert refused["departed_at"] is None
    assert refused["version"] == world["second_route"]["version"]
    assert (
        refused["estimated_reimbursement_cents"]
        == world["second_route"]["estimated_reimbursement_cents"]
    )
    after = fx.read_driver(driver_id)
    assert after["cash_on_hand_cents"] == 2900, "a refused departure moves no cash"
    assert after["cash_posture"] == "DROP_REQUIRED"


def test_a_safe_drop_clears_the_posture_and_the_same_route_then_departs():
    """Dropping the whole pouch into the safe empties the driver's cash, re-derives the posture to CLEAR and unblocks the very departure that was refused, while the store's safe total absorbs the money.

    PRD: "It lowers the driver's `cash_on_hand_cents` and raises the store's `safe_deposit_total_cents` by `amount_cents`, re-derives the driver's `cash_posture` — which is how a `DROP_REQUIRED` driver becomes `CLEAR` again and is unblocked to depart — and increments both the driver's `version` and the store's `version` by 1 each."
    Design: Corner/cross_cutting_complexity_layers/a_safe_drop_resets_the_cash_posture_and_unblocks_the_next_departure
    """
    world = _driver_with_a_loaded_pouch_and_a_second_committed_route()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    route_id = world["second_route"]["id"]
    driver_headers = make_driver_headers(driver_id)
    driver_version_before = fx.read_driver(driver_id)["version"]
    store_version_before = fx.read_store(store_id)["version"]

    validate_error(
        api_client.depart_dispatch(route_id, driver_headers),
        ApiErrorId.ERR_CASH_LIMIT_REACHED.value,
    )

    drop = validate_success(
        api_client.create_safe_drop(
            driver_id, f.create_safe_drop_payload(2900, envelope_number="ENV-021"), driver_headers
        ),
        201,
    )
    a.assert_safe_drop(drop)
    assert drop["status"] == "RECORDED"
    assert drop["amount_cents"] == 2900
    assert drop["envelope_number"] == "ENV-021"

    dropped_driver = fx.read_driver(driver_id)
    assert dropped_driver["cash_on_hand_cents"] == 0
    assert dropped_driver["cash_posture"] == "CLEAR"
    assert dropped_driver["version"] == driver_version_before + 1

    departed = validate_success(api_client.depart_dispatch(route_id, driver_headers), 200)
    a.assert_dispatch(departed)
    assert departed["status"] == "EN_ROUTE"
    a.assert_iso_millis(departed["departed_at"], "departed_at")
    assert a.parse_instant(departed["departed_at"]) == a.parse_instant("2026-08-05T13:00:00Z")

    store_after = fx.read_store(store_id)
    assert store_after["safe_deposit_total_cents"] == 2900
    assert store_after["cash_collected_total_cents"] == 2900
    assert store_after["version"] == store_version_before + 1
    reconciliation = fx.read_cash_reconciliation(store_id)
    a.assert_cash_conservation(reconciliation)
    assert reconciliation["driver_cash_on_hand_total_cents"] == 0
