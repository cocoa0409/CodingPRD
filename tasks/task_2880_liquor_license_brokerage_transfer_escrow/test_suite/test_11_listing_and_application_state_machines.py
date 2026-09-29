"""Initial states, refused repeats, terminal lockdown and the cascades of a transition.

The listing and the transfer application are the two records a client drives
through several states, and each transition either fires a documented cascade or
is refused by the exact code its priority owns.
"""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_draft_listing,
    assert_instant_equals,
    assert_protest,
    create_brokerage,
    create_county,
    create_license,
    create_listing,
    create_protest_payload,
    create_seller,
    read_agreement,
    read_application,
    read_county,
    read_disclosure,
    read_license,
    read_listing,
    read_protest,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_new_listing_is_draft_with_no_valuation_snapshot():
    """market_price_cents, valuation_basis and both snapshots stay null until activation.

    PRD: "A draft listing carries `open_offer_count` of 0 and has `valuation_basis`,
    `market_price_cents`, `scarcity_bps_at_activation`, `comp_count_at_activation`
    and `activated_at` all null; no valuation is computed while the listing is a
    draft."

    PRD: "The `status` enumeration for a listing is `DRAFT`, `ACTIVE`,
    `UNDER_CONTRACT`, `WITHDRAWN` and `SOLD`, of which `WITHDRAWN` and `SOLD` are
    terminal."

    Design: Corner/state_machines/listing_starts_in_draft_with_no_valuation_snapshot
    """
    county = create_county()
    seller = create_seller()
    brokerage = create_brokerage()
    license_row = create_license(county["id"], seller["id"], license_number="INIT-1")

    listing = create_listing(license_row["id"], brokerage["id"])

    assert listing["status"] == "DRAFT"
    assert listing["market_price_cents"] is None
    assert listing["valuation_basis"] is None
    assert listing["scarcity_bps_at_activation"] is None
    assert listing["comp_count_at_activation"] is None
    assert listing["activated_at"] is None
    assert listing["open_offer_count"] == 0
    assert listing["version"] == 1
    assert_draft_listing(listing)
    assert read_license(license_row["id"])["status"] == "ACTIVE"


def test_activating_an_already_active_listing_is_refused_not_repeated():
    """The second activation neither re-snapshots the valuation nor bumps the version.

    PRD: "And no other listing on the same license may already be `ACTIVE` or
    `UNDER_CONTRACT`, a collision reported as `ERR_INVALID_LISTING_STATE`."

    PRD: "When the count is zero, the comparable median is taken to be a statutory
    floor of 4500000 cents — forty-five thousand dollars — and a reported comparable
    count of zero is precisely the signal that this fallback was applied."

    PRD: "Activation then snapshots the county scarcity uplift onto
    `scarcity_bps_at_activation`, runs the valuation in the selected variant to
    write `market_price_cents` and `comp_count_at_activation`, records `activated_at`
    as the current logical instant, and advances the listing's `version` by one."

    Design: Corner/state_machines/activate_listing_twice_returns_invalid_listing_state
    """
    scenario = setup_scenario(stage="listing_active")
    first = scenario["listing"]
    assert first["version"] == 2
    assert first["market_price_cents"] == 4500000

    refused = api_client.activate_listing(
        scenario["listing_id"], scenario["broker_headers"], {}
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_LISTING_STATE.value, 409)

    unchanged = read_listing(scenario["listing_id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == 2
    assert unchanged["market_price_cents"] == 4500000
    assert_instant_equals(
        unchanged["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
    )


def test_activating_a_withdrawn_listing_reports_the_terminal_code():
    """WITHDRAWN is terminal, and step 11 owns terminal rows rather than step 10.

    PRD: "**Terminal record.** A record already in a terminal state accepts no
    further transition: a `License` at `TRANSFERRED`, a `Listing` at `SOLD` or
    `WITHDRAWN`, an agreement whose contract dimension is `CLOSED` or `TERMINATED`,
    an application at `APPROVED` or `DENIED`, a protest at `SUSTAINED` or
    `OVERRULED`, a filing at `GRANTED` or `DENIED` — `ERR_ALREADY_TERMINAL` (409)."

    PRD: "Records that are already in a terminal state are deliberately out of
    scope for this check and are handled by the next one instead, so this step never
    answers with `ERR_ALREADY_TERMINAL` and the next step is always reachable."

    Design: Corner/state_machines/activate_withdrawn_listing_returns_already_terminal
    """
    scenario = setup_scenario(stage="listing_active")
    withdrawn = validate_success(
        api_client.withdraw_listing(
            scenario["listing_id"], scenario["broker_headers"],
            {"reason": "seller retained the licence"},
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    refused = api_client.activate_listing(
        scenario["listing_id"], scenario["broker_headers"], {}
    )
    error = validate_error(refused, ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_LISTING_STATE.value

    still_withdrawn = read_listing(scenario["listing_id"])
    assert still_withdrawn["status"] == "WITHDRAWN"
    assert still_withdrawn["version"] == withdrawn["version"]
    assert read_license(scenario["license_id"])["status"] == "ACTIVE"


def test_terminating_a_funded_draft_demands_settlement_first():
    """The contract dimension is DRAFT but the money dimension bars the exit.

    PRD: "This is permitted only while `escrow_status` is `AWAITING_DEPOSIT`, since
    nothing is held and no settlement is owed; an attempt while funds are still
    `HELD` is refused with `ERR_ESCROW_MUST_BE_SETTLED_FIRST`, and an attempt after
    the escrow has already reached `RELEASED`, `REFUNDED` or `FORFEITED` is refused
    with `ERR_ESCROW_ALREADY_SETTLED`."

    PRD: "Termination writes the supplied text to `termination_reason`, moves every
    agency disclosure on that agreement that is `PENDING_ACKS` or `FULLY_ACKED` to
    `VOID`, recomputes the parent listing's `open_offer_count` — which therefore
    falls by one — advancing the listing's `version`, and advances the agreement's
    own `version`."

    Design: Corner/state_machines/terminate_after_deposit_returns_escrow_must_be_settled_first
    """
    scenario = setup_scenario(stage="escrow_held")
    funded = scenario["agreement"]
    assert funded["agreement_status"] == "DRAFT"
    assert funded["escrow_status"] == "HELD"

    refused = api_client.terminate_agreement(
        scenario["agreement_id"],
        {"reason": "buyer changed mind after funding"},
        scenario["broker_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_ESCROW_MUST_BE_SETTLED_FIRST.value, 409)

    unchanged = read_agreement(scenario["agreement_id"])
    assert unchanged["agreement_status"] == "DRAFT"
    assert unchanged["escrow_status"] == "HELD"
    assert unchanged["version"] == funded["version"]
    assert unchanged["termination_reason"] is None
    assert read_listing(scenario["listing_id"])["open_offer_count"] == 1


def test_a_decision_on_a_submitted_application_is_the_wrong_state():
    """The state precondition fires before the posting-elapsed rule can be evaluated.

    PRD: "The decision is the analyst's final act on the application, supplying a
    `decision` of either `APPROVED` or `DENIED` and optionally a `decision_note`,
    and it is reachable from `POSTED` or from `PROTESTED`."

    PRD: "The publication period must have fully elapsed: the logical clock must be
    **strictly later** than `posting_ends_at`, and equality is explicitly not
    elapsed, so a decision at the exact posting end instant is refused with
    `ERR_POSTING_PERIOD_NOT_ELAPSED`."

    The application is still `SUBMITTED`, so `posting_ends_at` is null and the
    elapsed test has nothing to compare against.

    Design: Corner/state_machines/decision_on_submitted_application_returns_invalid_application_state
    """
    scenario = setup_scenario(stage="application_filed")
    submitted = scenario["application"]
    assert submitted["status"] == "SUBMITTED"
    assert submitted["accepted_by_analyst_id"] is None

    refused = api_client.decide_application(
        scenario["application_id"],
        {"decision": "APPROVED", "decision_note": "skipping the queue"},
        scenario["analyst_two_headers"],
    )
    error = validate_error(refused, ApiErrorId.ERR_INVALID_APPLICATION_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_POSTING_PERIOD_NOT_ELAPSED.value

    unchanged = read_application(scenario["application_id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["decision"] is None
    assert unchanged["decided_at"] is None
    assert unchanged["version"] == 1
    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"
    assert read_listing(scenario["listing_id"])["status"] == "UNDER_CONTRACT"


def test_execution_cascades_the_license_and_the_listing_in_one_request():
    """One call moves the agreement, the licence, the listing and the county counters.

    PRD: "The agreement moves `DRAFT → EXECUTED`. The license moves `ACTIVE →
    IN_ESCROW` or `SAFEKEEPING → IN_ESCROW` as appropriate; when it comes from
    `SAFEKEEPING`, its `safekeeping_expires_at` is deliberately retained unchanged
    so that the window can be restored if the transfer later fails. The listing
    moves `ACTIVE → UNDER_CONTRACT`. The county's counters are recomputed, so
    `escrow_committed_count` rises by one for a counted license, and the county's
    `version` advances. The agreement, the license and the listing each have their
    own `version` advanced by one."

    PRD: "On success, `executed_at` is stamped with the current logical instant and
    `commission_mode` is frozen from the `FULLY_ACKED` disclosure: it becomes
    `DUAL_AGENCY` when that disclosure asserts both `represents_seller` and
    `represents_buyer`, and `SINGLE_AGENCY` in every other case."

    Design: Corner/state_machines/execute_cascades_license_in_escrow_and_listing_under_contract
    """
    scenario = setup_scenario(stage="executed")
    executed = scenario["agreement"]

    assert executed["agreement_status"] == "EXECUTED"
    assert executed["escrow_status"] == "HELD"
    assert_instant_equals(executed["executed_at"], "2026-08-01T00:00:00Z", "executed_at")
    assert executed["commission_mode"] == "SINGLE_AGENCY"
    assert executed["escrow_balance_cents"] == 2405001

    license_row = read_license(scenario["license_id"])
    assert license_row["status"] == "IN_ESCROW"
    assert license_row["version"] == 2

    listing = read_listing(scenario["listing_id"])
    assert listing["status"] == "UNDER_CONTRACT"
    assert listing["version"] == 4

    county = read_county(scenario["county_id"])
    assert county["escrow_committed_count"] == 1
    assert county["quota_licenses_counted"] == 1

    assert read_disclosure(scenario["disclosure_id"])["status"] == "FULLY_ACKED"


def test_protest_intake_is_the_only_route_to_the_protested_state():
    """Intake opens the protest and cascades the application, touching nothing else.

    PRD: "The accepted protest carries `status` of `OPEN` — its enumeration being
    `OPEN`, `RESPONDED`, `SUSTAINED` and `OVERRULED`, of which the last two are
    terminal — with `filed_at` set to the current logical instant, `response_due_at`
    set to `filed_at` advanced by `response_due_days` days, and `response_text_ref`
    and `response_submitted_at` both null."

    PRD: "An optional `response_due_days` sets how long the broker has to answer and
    defaults to 15 days."

    PRD: "Accepting a protest also cascades onto the application, moving it `POSTED →
    PROTESTED` and advancing the application's `version` by one."

    Design: Corner/state_machines/protest_intake_cascades_application_posted_to_protested
    """
    scenario = setup_scenario(
        stage="application_posted",
        county_overrides={"protest_window_days": 15},
    )
    posted = scenario["application"]
    assert posted["status"] == "POSTED"
    assert_instant_equals(
        posted["protest_deadline_at"], "2026-08-16T00:00:00Z", "protest_deadline_at"
    )

    protest = validate_success(
        api_client.create_protest(
            create_protest_payload(
                scenario["application_id"],
                protestant_name="Neighbourhood Council",
                grounds="UNDUE_CONCENTRATION",
            ),
            scenario["analyst_headers"],
        ),
        201,
    )
    assert_protest(protest)
    assert protest["status"] == "OPEN"
    assert protest["grounds"] == "UNDUE_CONCENTRATION"
    assert protest["response_text_ref"] is None
    assert protest["response_submitted_at"] is None
    assert_instant_equals(protest["filed_at"], "2026-08-01T00:00:00Z", "filed_at")
    assert_instant_equals(
        protest["response_due_at"], "2026-08-16T00:00:00Z", "response_due_at"
    )

    protested = read_application(scenario["application_id"])
    assert protested["status"] == "PROTESTED"
    assert protested["version"] == posted["version"] + 1
    assert_instant_equals(
        protested["protest_deadline_at"], "2026-08-16T00:00:00Z", "protest_deadline_at"
    )

    rows, meta = validate_paginated(
        api_client.list_protests(
            ADMIN, {"application_id": scenario["application_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == read_protest(protest["id"])["id"]

    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"
    assert read_agreement(scenario["agreement_id"])["escrow_status"] == "HELD"
