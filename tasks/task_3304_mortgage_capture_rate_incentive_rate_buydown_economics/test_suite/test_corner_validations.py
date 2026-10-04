"""Corner coverage - role gates, existence gates, aggregate limits and clock windows."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, CLOSING_HEADERS, SALES_HEADERS
from test_helpers import NON_EXISTENT_UUID


def pending_contract_world(api):
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})
    return world


def test_cancellation_is_refused_to_a_role_outside_its_operation_set(api):
    """Cancelling is exclusive to the sales office, so the banker is refused.

    PRD §2.1: "A request whose role is valid but is not listed among the roles
    authorized for the target operation is rejected with `ERR_FORBIDDEN` and an HTTP 403."
    PRD §3.4: "A `SalesCounselor` may cancel a contract that is currently `PENDING` or
    `LOCKED` by supplying a `cancellation_reason`".
    Design: Corner/validations/forbidden_role_cannot_cancel_a_contract
    """
    world = pending_contract_world(api)

    refused = api.cancel_contract(world["ct1"], "RATE_SHOCK", BANKER_HEADERS)
    validate_error(refused, "ERR_FORBIDDEN", 403)


def test_the_refused_cancellation_leaves_the_deal_untouched(api):
    """No settlement is proposed and the home stays reserved when the role is wrong.

    PRD §3.4: "The buyer's `total_incentive_received_cents` and the community's
    `forward_units_committed` are recomputed, and a deposit settlement is created in
    `PROPOSED` status with its `statute_class` chosen by the statute selector".
    PRD §3.2: "The reverse move, back to `AVAILABLE`, happens automatically when the
    contract written against that home is cancelled".
    Design: Corner/validations/forbidden_role_cannot_cancel_a_contract
    """
    world = pending_contract_world(api)
    api.cancel_contract(world["ct1"], "RATE_SHOCK", BANKER_HEADERS)

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "PENDING", contract["contract_status"]

    site = fixtures.read_home_site(api, world["hs1"])
    assert site["home_site_status"] == "UNDER_CONTRACT", (
        f"a refused cancellation must not free the home, got {site['home_site_status']}"
    )

    settlements, _ = fixtures.rows(
        api.list_contract_deposit_forfeitures(world["ct1"], world["closing_headers"])
    )
    assert settlements == [], f"no settlement was proposed, got {settlements}"


def test_qualifying_an_application_that_does_not_exist_is_a_not_found(api):
    """The path identifier is resolved before any scoring rule runs.

    PRD §2.12: "The request is abandoned at the first identifier along that chain that
    resolves to no row, returning `ERR_RESOURCE_NOT_FOUND` at HTTP 404".
    PRD §2.10: "Priority 3 requires that every path identifier and every body foreign key
    resolve to an existing row, validated left-to-right along the path".
    Design: Corner/validations/cross_entity_qualify_requires_an_existing_application_row
    """
    world = pending_contract_world(api)

    refused = api.qualify_loan_application(NON_EXISTENT_UUID, BANKER_HEADERS)
    validate_error(refused, "ERR_RESOURCE_NOT_FOUND", 404)

    assert world["ct1"] is not None


def test_the_unknown_application_identifier_created_no_application_row(api):
    """No side row appears when the existence rung aborts the request.

    PRD §2.10: "Authentication is settled before authorization, authorization before
    existence, existence before state, state before the business rules".
    PRD §3.3: "Underwriting begins when a `MortgageBanker` or `SalesCounselor` files a
    loan application against a contract".
    Design: Corner/validations/cross_entity_qualify_requires_an_existing_application_row
    """
    world = pending_contract_world(api)
    api.qualify_loan_application(NON_EXISTENT_UUID, BANKER_HEADERS)

    rows, _ = fixtures.rows(
        api.list_contract_loan_applications(world["ct1"], world["banker_headers"])
    )
    assert rows == [], f"the aborted call added nothing, got {rows}"


def buydown_capped_deal(api):
    """A LOCKED contract holding a reserved rate-buydown allocation of the full cap."""
    return fixtures.setup_contract_with_rate_buydown(
        api, buydown_cents=6_000_000, target_state="LOCKED"
    )


def test_a_gross_buydown_above_the_granted_allocation_is_refused(api):
    """A legal gross amount is still refused when it exceeds what the bucket granted.

    PRD §2.10: "Priority 20 requires that a buydown record's `gross_buydown_cents` not
    exceed the `allocation_total_cents` of its linked rate-buydown allocation; failure
    yields `ERR_BUYDOWN_EXCEEDS_ALLOCATION` at HTTP 422."
    PRD §3.7: "creation is refused with `ERR_BUYDOWN_EXCEEDS_ALLOCATION` at HTTP 422 when
    the gross buydown exceeds the linked allocation's `allocation_total_cents`".
    Design: Corner/validations/aggregate_buydown_exceeding_the_linked_allocation_is_rejected
    """
    world = buydown_capped_deal(api)
    allocation = fixtures.read_allocation(api, world["al1"])
    assert allocation["allocation_total_cents"] == 6_000_000, allocation["allocation_total_cents"]

    contract = fixtures.read_contract(api, world["ct1"])
    refused = api.create_buydown_record(
        world["ct1"],
        f.buydown_record_payload(world["al1"], 7_000_000, contract["version"]),
        CLOSING_HEADERS,
    )
    validate_error(refused, "ERR_BUYDOWN_EXCEEDS_ALLOCATION", 422)


def test_the_granted_allocation_total_is_unchanged_by_the_refused_record(api):
    """The linked allocation keeps its granted total and no record row appears.

    PRD §3.7: "The first bucket that absorbs any overflow is recorded in the
    `spill_to_bucket` field, and the total granted across the target bucket and its
    downstream spill becomes `allocation_total_cents`."
    PRD §3.7: "The record opens in `DRAFT` status".
    Design: Corner/validations/aggregate_buydown_exceeding_the_linked_allocation_is_rejected
    """
    world = buydown_capped_deal(api)
    contract = fixtures.read_contract(api, world["ct1"])
    api.create_buydown_record(
        world["ct1"],
        f.buydown_record_payload(world["al1"], 7_000_000, contract["version"]),
        CLOSING_HEADERS,
    )

    allocation = fixtures.read_allocation(api, world["al1"])
    assert allocation["allocation_total_cents"] == 6_000_000, allocation["allocation_total_cents"]

    records, _ = fixtures.rows(
        api.list_contract_buydown_records(world["ct1"], world["closing_headers"])
    )
    assert records == [], f"the refused creation wrote no record, got {records}"


def test_extending_a_lock_after_its_expiry_is_refused(api):
    """A clock advance past the expiry takes both the extension and the void away.

    PRD §3.5: "Extending or voiding a lock that is no longer `ACTIVE`, or whose
    `lock_expires_iso` has already passed, is refused with `ERR_RATE_LOCK_EXPIRED` at
    HTTP 409."
    PRD §2.10: "Priority 14 requires that the target lock be `ACTIVE` and that the clock
    not exceed its `lock_expires_iso`; failure yields `ERR_RATE_LOCK_EXPIRED` at HTTP 409".
    Design: Corner/validations/temporal_lock_extension_refused_once_the_lock_has_expired
    """
    world = fixtures.build_deal(api)
    fixtures.give_lock(api, world, lock_days=30)
    fixtures.set_clock(api, "2026-10-05T00:00:00Z")

    refused = api.extend_rate_lock(world["lk1"], 90, BANKER_HEADERS)
    validate_error(refused, "ERR_RATE_LOCK_EXPIRED", 409)


def test_the_expired_lock_refuses_voiding_and_keeps_its_original_term(api):
    """The void is refused on the same rung and the rejected extension changed nothing.

    PRD §3.5: "A `MortgageBanker` may void a lock that is currently `ACTIVE`; the lock
    moves to `VOIDED`".
    PRD §2.13: "a rate lock whose `lock_expires_iso` has passed moves from `ACTIVE` to
    `EXPIRED`".
    Design: Corner/validations/temporal_lock_extension_refused_once_the_lock_has_expired
    """
    world = fixtures.build_deal(api)
    fixtures.give_lock(api, world, lock_days=30)
    fixtures.set_clock(api, "2026-10-05T00:00:00Z")

    api.extend_rate_lock(world["lk1"], 90, BANKER_HEADERS)
    refused = api.void_rate_lock(world["lk1"], BANKER_HEADERS)
    validate_error(refused, "ERR_RATE_LOCK_EXPIRED", 409)

    lock = fixtures.read_rate_lock(api, world["lk1"])
    assert lock["lock_status"] == "EXPIRED", lock["lock_status"]
    assert lock["lock_days"] == 30, (
        f"the refused extension left the original term, got {lock['lock_days']}"
    )


def two_contract_steering_world(api):
    """Two pending contracts, one of which already carries a rate-buydown allocation.

    The affiliated-business disclosure is delivered and acknowledged on the second
    contract before its rate-buydown allocation, per PRD section 3.7.
    """
    world = fixtures.seed_reference_data(api)
    site1 = fixtures.create_home_site(api, world["cm1"], lot_number="L1", address="1 Elm")
    site2 = fixtures.create_home_site(api, world["cm1"], lot_number="L2", address="2 Elm")
    contract1 = fixtures.create_contract(api, site1["id"], world["b1"])
    contract2 = fixtures.create_contract(api, site2["id"], world["b1"])
    world.update({
        "hs1": site1["id"], "hs2": site2["id"],
        "ct1": contract1["id"], "ct2": contract2["id"],
        "ct2_v": contract2["version"],
    })
    aba = fixtures.deliver_disclosure(api, world["ct2"])
    world["d2"] = aba["id"]
    fixtures.acknowledge(api, world["d2"], world["b1"])
    allocation = fixtures.allocate(api, world["ct2"], "RATE_BUYDOWN", 6_000_000)
    world.update({"al2": allocation["id"]})
    return world


def test_an_affiliated_application_is_accepted_when_no_rate_buydown_is_on_the_deal(api):
    """The steering prohibition only bites once the deal carries a rate-buydown allocation.

    PRD §2.10: "Priority 7 forbids conditioning an incentive on lender choice: filing a
    loan application with `lender_entity_code` equal to `AFFILIATED_LENDER` is refused
    when the contract already carries an allocation whose `bucket` is `RATE_BUYDOWN` and
    the contract has no `ACKNOWLEDGED` `STEERING_PROHIBITION` disclosure".
    PRD §3.3: "Filing with the affiliated lender flips the buyer's
    `affiliated_lender_selected` to true."
    Design: Corner/validations/conditional_steering_prohibition_applies_only_with_a_rate_buydown_allocation
    """
    world = two_contract_steering_world(api)

    accepted = fixtures.create_application(
        api, world["ct1"], application_number="APP-OK"
    )
    assert accepted["application_status"] == "SUBMITTED", accepted["application_status"]

    buyer = fixtures.read_buyer(api, world["b1"])
    assert buyer["affiliated_lender_selected"] is True, (
        f"the accepted affiliated application is what sets the flag, "
        f"got {buyer['affiliated_lender_selected']}"
    )


def test_the_same_affiliated_application_is_refused_on_the_rate_buydown_contract(api):
    """The sibling deal's allocation makes the identical request a steering violation.

    PRD §2.10: "Priority 7 forbids conditioning an incentive on lender choice: filing a
    loan application with `lender_entity_code` equal to `AFFILIATED_LENDER` is refused
    when the contract already carries an allocation whose `bucket` is `RATE_BUYDOWN` and
    the contract has no `ACKNOWLEDGED` `STEERING_PROHIBITION` disclosure; failure yields
    `ERR_STEERING_PROHIBITED` at HTTP 403".
    Design: Corner/validations/conditional_steering_prohibition_applies_only_with_a_rate_buydown_allocation
    """
    world = two_contract_steering_world(api)

    refused = api.create_loan_application(
        world["ct2"],
        f.loan_application_payload(application_number="APP-BAD"),
        BANKER_HEADERS,
    )
    validate_error(refused, "ERR_STEERING_PROHIBITED", 403)

    rows, _ = fixtures.rows(
        api.list_contract_loan_applications(world["ct2"], world["banker_headers"])
    )
    assert rows == [], f"the refused filing left no application, got {rows}"