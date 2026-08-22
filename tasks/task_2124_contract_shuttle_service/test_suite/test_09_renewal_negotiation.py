"""Renewal: the escalation keyed on a frozen report, and the negotiation cycle."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_renewal_offer,
    create_active_contract,
    create_renewal_offer,
    get_contract,
    set_clock,
    setup_approved_report_for_renewal,
    setup_countered_offer,
    setup_renewal_pending_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contract_admin_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]


# ─── The escalation, keyed on the frozen approved report ──────────────────────

def test_proposed_rate_is_keyed_on_the_frozen_approved_report(api):
    """PRD §3.9: "`volume_pct` rewards ridership: it is 0.0 when there is no basis
    report, 0.0 when the basis report's `total_boardings` is below 2,000, 1.5 when
    `total_boardings` is at least 2,000 but below 5,000, and 3.0 when
    `total_boardings` is 5,000 or more. `clawback_pct` punishes underperformance: it
    is 0.0 when there is no basis report, 2.0 when the basis report's `on_time_pct`
    is strictly below the contract's `sla_on_time_threshold_pct`, and 0.0
    otherwise."
    PRD §3.9: "The raw escalation is the contract's `escalation_index_pct` plus
    `volume_pct` minus `clawback_pct`. That raw figure is then clamped into the band
    from 0.0 to 6.0 inclusive — anything below 0.0 becomes 0.0 and anything above
    6.0 becomes 6.0 — and the clamped result is stored as `applied_escalation_pct`.
    Finally, `proposed_rate_cents_per_service_hour` is the contract's
    `base_rate_cents_per_service_hour` multiplied by one plus
    `applied_escalation_pct` divided by 100, rounded half up to a whole number of
    cents."

    Design: Difficulty/combinatorial_formula/renewal_rate_escalation_evaluation_order
    """
    scenario = setup_approved_report_for_renewal()
    current_version = get_contract(scenario["contract"]["id"])["version"]

    offer = validate_success(
        api.create_renewal_offer(
            {
                "contract_id": scenario["contract"]["id"],
                "proposed_term_months": 12,
                "expected_contract_version": current_version,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert_renewal_offer(offer)

    assert offer["volume_pct"] == pytest.approx(0.0, abs=0.001), "40 boardings is below 2,000"
    assert offer["clawback_pct"] == pytest.approx(2.0, abs=0.001), (
        "0.00 on-time delivered against a 92.00 promise"
    )
    assert offer["applied_escalation_pct"] == pytest.approx(1.5, abs=0.001), (
        "3.5 plus 0.0 minus 2.0, inside the 0.0 to 6.0 band"
    )
    assert offer["proposed_rate_cents_per_service_hour"] == 9_135
    assert offer["basis_report_id"] == scenario["report"]["id"]
    assert offer["round_index"] == 1
    assert offer["status"] == "OPEN"


def test_new_offer_never_feeds_back_into_the_basis_report(api):
    """PRD §3.9: "Because the escalation is keyed on a frozen approved report, whose
    own `effective_rate_cents_per_service_hour` was itself snapshotted at submission
    time, the new rate never feeds back into the basis report and the apparent
    circularity of "rate depends on report, report depends on rate" is broken at the
    freeze."
    PRD §3.9: "Opening an offer against a contract that is `ACTIVE` moves it
    `ACTIVE` → `RENEWAL_PENDING`."

    Design: Difficulty/combinatorial_formula/renewal_rate_escalation_evaluation_order
    """
    scenario = setup_approved_report_for_renewal()
    create_renewal_offer(scenario["contract"]["id"], proposed_term_months=12)

    report = validate_success(api.get_report(scenario["report"]["id"], ADMIN))
    assert report["effective_rate_cents_per_service_hour"] == 9_000, (
        "the rate frozen at submission never moves"
    )
    assert report["on_time_pct"] == pytest.approx(0.00, abs=0.001)
    assert report["total_boardings"] == 40

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["status"] == "RENEWAL_PENDING"
    assert contract["base_rate_cents_per_service_hour"] == 9_000, (
        "the contract's own rate is untouched by the offer"
    )


# ─── The counter / reopen cycle ───────────────────────────────────────────────

def test_reopen_returns_the_offer_to_open_and_advances_the_round(api):
    """PRD §3.9: "A `REOPEN` decision is the return leg of the negotiation cycle:
    the offer moves `COUNTERED` → `OPEN`, `round_index` increments by one,
    `counter_rate_cents_per_service_hour` is cleared, and the offer's `version`
    increments by one."

    Design: Difficulty/non_linear_state_machine/renewal_offer_counter_reopen_cycle
    """
    scenario = setup_countered_offer(
        counter_rate_cents_per_service_hour=9_100,
        contract_overrides={"client_name": "Negotiation Campus", "site_type": "CAMPUS"},
    )
    assert scenario["offer"]["status"] == "COUNTERED"
    assert scenario["offer"]["round_index"] == 1

    reopened = validate_success(
        api.respond_renewal_offer(scenario["offer"]["id"], {"decision": "REOPEN"}, ADMIN)
    )
    assert reopened["status"] == "OPEN"
    assert reopened["round_index"] == 2
    assert reopened.get("counter_rate_cents_per_service_hour") is None

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["status"] == "RENEWAL_PENDING", "the contract stays in the loop"


def test_second_counter_reenters_countered_at_the_advanced_round(api):
    """PRD §3.9: "The counter rate is stored, the offer moves `OPEN` → `COUNTERED`,
    and its `version` increments by one."
    PRD §3.9: "The contract stays in `RENEWAL_PENDING`, and the client may counter
    again — each lap advancing `round_index`."

    Design: Difficulty/non_linear_state_machine/renewal_offer_counter_reopen_cycle
    """
    scenario = setup_countered_offer(
        counter_rate_cents_per_service_hour=9_100,
        contract_overrides={"client_name": "Negotiation Campus", "site_type": "CAMPUS"},
    )
    assert scenario["offer"]["proposed_rate_cents_per_service_hour"] == 9_315, (
        "with no approved report the escalation is the bare 3.5 index"
    )
    validate_success(
        api.respond_renewal_offer(scenario["offer"]["id"], {"decision": "REOPEN"}, ADMIN)
    )

    countered_again = validate_success(
        api.counter_renewal_offer(
            scenario["offer"]["id"], {"counter_rate_cents_per_service_hour": 9_250}, LIAISON
        )
    )
    assert countered_again["status"] == "COUNTERED"
    assert countered_again["round_index"] == 2
    assert countered_again["counter_rate_cents_per_service_hour"] == 9_250
    assert countered_again["proposed_rate_cents_per_service_hour"] == 9_315


# ─── Accepting mints the successor ────────────────────────────────────────────

def test_accepted_offer_mints_the_successor_contract(api):
    """PRD §3.9: "Third, because the contract became `RENEWED`, a successor contract
    is minted in `DRAFT`: its `predecessor_contract_id` is the id of the contract
    just renewed, its `base_rate_cents_per_service_hour` is the offer's
    `agreed_rate_cents_per_service_hour`, its `term_start_date` is the day after the
    renewed contract's `term_end_date`, and its `term_end_date` is that new start
    date advanced by `proposed_term_months` whole months and then pulled back by one
    day — a twelve-month renewal starting on 2027-01-01 therefore ends on
    2027-12-31."
    PRD §3.9: "First, the offer moves `COUNTERED` → `ACCEPTED`, terminal, and
    `agreed_rate_cents_per_service_hour` is set to the offer's
    `counter_rate_cents_per_service_hour`."

    Design: Corner/entities/contract_renewal_chain_is_reachable_through_predecessor_filter
    """
    scenario = setup_countered_offer(
        counter_rate_cents_per_service_hour=9_100,
        contract_overrides={"client_name": "Chain Hotel"},
    )

    accepted = validate_success(
        api.respond_renewal_offer(scenario["offer"]["id"], {"decision": "ACCEPT"}, ADMIN)
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["agreed_rate_cents_per_service_hour"] == 9_100
    successor_id = accepted["successor_contract_id"]
    assert successor_id, "the accept cascade writes the successor id back onto the offer"

    renewed = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert renewed["status"] == "RENEWED"

    successor = validate_success(api.get_contract(successor_id, ADMIN))
    assert successor["status"] == "DRAFT"
    assert successor["base_rate_cents_per_service_hour"] == 9_100
    assert successor["predecessor_contract_id"] == scenario["contract"]["id"]
    assert successor["term_start_date"] == "2027-09-01"
    assert successor["term_end_date"] == "2028-08-31"

    chain, chain_meta = validate_paginated(
        api.list_contracts(
            ADMIN, params={"predecessor_contract_id": scenario["contract"]["id"]}
        )
    )
    assert chain_meta["total_count"] == 1
    assert chain[0]["id"] == successor_id

    offers, offer_meta = validate_paginated(
        api.list_renewal_offers(ADMIN, params={"successor_contract_id": successor_id})
    )
    assert offer_meta["total_count"] == 1
    assert offers[0]["id"] == scenario["offer"]["id"]


def test_responding_to_an_open_offer_is_rejected(api):
    """PRD §3.9: "Responding is permitted only while the offer is `COUNTERED`, and
    is otherwise rejected with `ERR_OFFER_NOT_COUNTERED`."

    Design: Corner/state_machines/respond_to_an_open_offer_returns_offer_not_countered
    """
    scenario = setup_renewal_pending_contract(
        proposed_term_months=24,
        contract_overrides={"client_name": "Respond Guard"},
    )

    response = api.respond_renewal_offer(
        scenario["offer"]["id"], {"decision": "ACCEPT"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_COUNTERED.value, 409)

    offer = validate_success(api.get_renewal_offer(scenario["offer"]["id"], ADMIN))
    assert offer["status"] == "OPEN"
    assert offer.get("successor_contract_id") is None
    assert offer.get("agreed_rate_cents_per_service_hour") is None

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["status"] == "RENEWAL_PENDING"


# ─── Counter bounds ───────────────────────────────────────────────────────────

def test_counter_rate_below_the_base_rate_is_rejected(api):
    """PRD §3.9: "A `ClientLiaison` supplies `counter_rate_cents_per_service_hour`,
    which must sit between the contract's current `base_rate_cents_per_service_hour`
    and the offer's `proposed_rate_cents_per_service_hour` inclusive at both ends; a
    value below the base rate or above the proposed rate is rejected with
    `ERR_COUNTER_RATE_OUT_OF_BOUNDS` and HTTP 422. Countering is permitted only
    while the offer is `OPEN`, and is otherwise rejected with `ERR_OFFER_NOT_OPEN`;
    the contract must be in `RENEWAL_PENDING`."

    Design: Corner/validations/counter_rate_below_base_is_rejected_and_countered_offer_cannot_be_countered_again
    """
    scenario = setup_renewal_pending_contract(
        contract_overrides={"client_name": "Counter Bounds Hotel"}
    )
    offer_id = scenario["offer"]["id"]

    too_low = api.counter_renewal_offer(
        offer_id, {"counter_rate_cents_per_service_hour": 8_900}, LIAISON
    )
    validate_error(too_low, ApiErrorId.ERR_COUNTER_RATE_OUT_OF_BOUNDS.value, 422)

    accepted = validate_success(
        api.counter_renewal_offer(
            offer_id, {"counter_rate_cents_per_service_hour": 9_100}, LIAISON
        )
    )
    assert accepted["status"] == "COUNTERED"

    third = api.counter_renewal_offer(
        offer_id, {"counter_rate_cents_per_service_hour": 9_200}, LIAISON
    )
    validate_error(third, ApiErrorId.ERR_OFFER_NOT_OPEN.value, 409)

    offer = validate_success(api.get_renewal_offer(offer_id, ADMIN))
    assert offer["counter_rate_cents_per_service_hour"] == 9_100
    assert offer["round_index"] == 1


# ─── The renewal window ───────────────────────────────────────────────────────

def test_renewal_window_opens_exactly_sixty_days_before_term_end(api):
    """PRD §3.9: "The renewal window is the sixty days that close on the contract's
    `term_end_date`: the logical clock's current UTC date must lie inside the closed
    range that begins sixty days before `term_end_date` and ends on `term_end_date`,
    and the opening day itself passes. A clock sitting outside that window is
    rejected with `ERR_RENEWAL_WINDOW_CLOSED` and HTTP 422."

    Design: Corner/validations/renewal_window_opens_exactly_sixty_days_before_term_end
    """
    set_clock("2027-07-01T12:00:00Z")
    contract = create_active_contract(
        client_name="Window Boundary Hotel",
        term_start_date="2026-09-01", term_end_date="2027-08-31",
    )
    observed_version = contract["version"]

    too_early = api.create_renewal_offer(
        {
            "contract_id": contract["id"],
            "proposed_term_months": 12,
            "expected_contract_version": observed_version,
        },
        ADMIN,
    )
    validate_error(too_early, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value, 422)

    unchanged = validate_success(api.get_contract(contract["id"], ADMIN))
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == observed_version

    set_clock("2027-07-02T00:00:00Z")
    offer = validate_success(
        api.create_renewal_offer(
            {
                "contract_id": contract["id"],
                "proposed_term_months": 12,
                "expected_contract_version": observed_version,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert offer["proposed_rate_cents_per_service_hour"] == 9_315
    assert offer["applied_escalation_pct"] == pytest.approx(3.5, abs=0.001)
    assert offer.get("basis_report_id") is None

    reread = validate_success(api.get_contract(contract["id"], ADMIN))
    assert reread["status"] == "RENEWAL_PENDING"


# ─── Optimistic concurrency on the contract ───────────────────────────────────

def test_offer_create_with_a_stale_contract_version_is_rejected(api):
    """PRD §2.8: "The request body must carry `expected_contract_version`, a
    required field holding the `version` of the target `ServiceContract` as the
    client last observed it. If that value does not equal the contract's current
    `version` at the moment of the write, the request is rejected with
    `ERR_STALE_CONTRACT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_contract_version_on_offer_create
    """
    scenario = setup_renewal_pending_contract(contract_overrides={"client_name": "OCC Hotel"})
    stale_version = scenario["activated_version"]

    response = api.create_renewal_offer(
        {
            "contract_id": scenario["contract"]["id"],
            "proposed_term_months": 24,
            "expected_contract_version": stale_version,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STALE_CONTRACT_VERSION.value, 412)

    offers, meta = validate_paginated(
        api.list_renewal_offers(ADMIN, params={"contract_id": scenario["contract"]["id"]})
    )
    assert meta["total_count"] == 1, "no second offer row is created"
    assert offers[0]["id"] == scenario["offer"]["id"]
    assert offers[0]["status"] == "OPEN"

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["status"] == "RENEWAL_PENDING"


def test_fresh_contract_version_supersedes_the_standing_offer(api):
    """PRD §3.9: "Opening a further offer against a contract already in
    `RENEWAL_PENDING` leaves it in `RENEWAL_PENDING`, and in either case any
    standing offer for that contract whose `status` is `OPEN` or `COUNTERED` moves
    to `SUPERSEDED` — a terminal state — with its own `version` incremented by one.
    The contract's `version` increments by one on every offer creation. The new
    offer is born `OPEN` with `round_index` at 1,
    `counter_rate_cents_per_service_hour`, `agreed_rate_cents_per_service_hour` and
    `successor_contract_id` all null."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_fresh_contract_version_supersedes_standing_offer
    """
    scenario = setup_renewal_pending_contract(
        contract_overrides={"client_name": "Supersede Campus", "site_type": "CAMPUS"}
    )
    activated_version = scenario["activated_version"]
    fresh = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert fresh["version"] == activated_version + 1, (
        "creating the first offer moved the contract's version by one"
    )

    second = validate_success(
        api.create_renewal_offer(
            {
                "contract_id": scenario["contract"]["id"],
                "proposed_term_months": 24,
                "expected_contract_version": fresh["version"],
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert second["status"] == "OPEN"
    assert second["proposed_term_months"] == 24
    assert second["round_index"] == 1

    superseded = validate_success(api.get_renewal_offer(scenario["offer"]["id"], ADMIN))
    assert superseded["status"] == "SUPERSEDED"

    _, meta = validate_paginated(
        api.list_renewal_offers(ADMIN, params={"contract_id": scenario["contract"]["id"]})
    )
    assert meta["total_count"] == 2

    after = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert after["version"] == fresh["version"] + 1
    assert after["status"] == "RENEWAL_PENDING"
