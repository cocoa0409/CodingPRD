"""Recording offers, the submission gates, the counter/revise loop, and the
four-hop chain a servicer rejection fires."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_offer,
    counter_offer,
    create_offer,
    create_offer_payload,
    package_decision_payload,
    prepare_net_sheet,
    price_reduction_payload,
    reject_offer,
    revise_offer_payload,
    run_counter_revise_rounds,
    servicer_decision_payload,
    set_clock,
    setup_case_after_two_rejected_offers,
    setup_case_with_submitted_offer,
    setup_countered_offer,
    setup_marketed_case,
    setup_submitted_package,
    submit_offer,
    validate_error,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
AGENT = TEST_USERS["listing_agent_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]


def test_recorded_offer_is_born_in_draft_at_round_one(api):
    """PRD §3.5: "The offer is born in `DRAFT` with `round_index` at 1, `submitted_at`
    null and `servicer_counter_price_cents` null."

    Design: Corner/entities/offer_default_round_index_is_one
    """
    set_clock("2026-08-05T00:00:00Z")
    scenario = setup_marketed_case()

    offer = validate_success(
        api.create_offer(scenario["case"]["id"], create_offer_payload(), AGENT), 201
    )

    assert offer["round_index"] == 1
    assert offer["status"] == "DRAFT"
    assert offer["servicer_counter_price_cents"] is None
    assert offer["submitted_at"] is None
    assert_offer(offer)


def test_submitting_an_already_submitted_offer_is_not_actionable(api):
    """PRD §3.5: "An offer may be submitted only from `DRAFT` or from `REVISED`; from
    anywhere else the attempt is refused with `ERR_OFFER_NOT_ACTIONABLE`."
    PRD §3.5: "Re-submitting from `REVISED` additionally raises `round_index` by one; a
    first submission from `DRAFT` leaves it at 1."

    Design: Corner/state_machines/submit_offer_twice_second_returns_offer_not_actionable
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]

    validate_error(
        api.submit_offer(offer_id, NEG), ApiErrorId.ERR_OFFER_NOT_ACTIONABLE.value
    )

    stored = validate_success(api.get_offer(offer_id, NEG), 200)
    assert stored["status"] == "SUBMITTED"
    assert stored["round_index"] == 1
    assert stored["submitted_at"].startswith("2026-08-24T00:00:00"), (
        "a refused submit must not restamp submitted_at"
    )


def test_revising_a_countered_offer_stales_its_current_sheets(api):
    """PRD §3.5: "The offer moves to `REVISED`, the price is replaced, and **every**
    settlement sheet on that offer whose status is `CURRENT` — of either variant — is
    demoted to `STALE`, because the price the sheets were computed against no longer
    holds."

    Design: Corner/state_machines/revise_offer_stales_current_net_sheets
    """
    scenario = setup_countered_offer()
    offer_id = scenario["offer"]["id"]
    sheet = prepare_net_sheet(offer_id, "PRELIMINARY")
    assert sheet["status"] == "CURRENT"

    revised = validate_success(
        api.revise_offer(offer_id, revise_offer_payload(25_100_000), AGENT), 200
    )

    assert revised["status"] == "REVISED"
    assert revised["offer_price_cents"] == 25_100_000

    sheets = validate_success(api.list_offer_net_sheets(offer_id, NEG), 200)
    assert sheets[0]["id"] == sheet["id"]
    assert sheets[0]["status"] == "STALE"

    current = validate_success(
        api.list_offer_net_sheets(offer_id, NEG, params={"status": "CURRENT"}), 200
    )
    assert len(current) == 0, "no sheet on the offer is CURRENT once the price moved"


def test_negotiation_cycle_returns_the_offer_to_submitted_at_round_two(api):
    """PRD §3.5: "A `COUNTER` requires a `counter_price_cents` of at least 1; the server
    stamps it into `servicer_counter_price_cents` and moves the offer to `COUNTERED`."
    PRD §3.5: "Re-submitting from `REVISED` additionally raises `round_index` by one; a
    first submission from `DRAFT` leaves it at 1."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_returns_to_submitted_with_next_round
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]

    countered = validate_success(
        api.servicer_decision_on_offer(
            offer_id,
            servicer_decision_payload(
                "COUNTER", counter_price_cents=25_400_000,
                note="Value supports a higher price",
            ),
            ANALYST,
        ),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["servicer_counter_price_cents"] == 25_400_000

    revised = validate_success(
        api.revise_offer(offer_id, revise_offer_payload(25_100_000), AGENT), 200
    )
    assert revised["status"] == "REVISED"

    resubmitted = validate_success(api.submit_offer(offer_id, NEG), 200)

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["round_index"] == 2
    assert resubmitted["offer_price_cents"] == 25_100_000
    assert resubmitted["servicer_counter_price_cents"] == 25_400_000


def test_negotiation_cycle_drives_the_listing_back_under_contract(api):
    """PRD §3.5: "A successful submission moves the offer to `SUBMITTED`, stamps
    `submitted_at` with the current logical-clock instant, moves the controlling listing
    from `ACTIVE` to `UNDER_CONTRACT`, and carries the case's negotiation dimension to
    `OFFER_UNDER_REVIEW` — from `MARKETED` on a first pass, or from `RENEGOTIATION` when
    the file has come back around after an approval was voided."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_returns_to_submitted_with_next_round
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]
    counter_offer(offer_id, 25_400_000)
    validate_success(api.revise_offer(offer_id, revise_offer_payload(25_100_000), AGENT), 200)
    submit_offer(offer_id)

    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "UNDER_CONTRACT"

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "OFFER_UNDER_REVIEW"
    assert case_after["failed_offer_count"] == 0, (
        "a countered and revised offer never counts as a failure"
    )


def test_submission_is_refused_while_the_package_is_only_submitted(api):
    """PRD §3.5: "First, the case's hardship package must exist and be `ACCEPTED` — this
    is the real gate, and the case's negotiation dimension reading `MARKETED` or
    `RENEGOTIATION` is a consequence of that acceptance rather than a second, separate
    check; a case without an accepted package is refused with
    `ERR_HARDSHIP_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/offer_submission_gated_on_hardship_package_state
    """
    case, package, _ = setup_submitted_package()
    validate_success(
        api.create_listing(
            case["id"],
            {
                "list_price_cents": 25_900_000,
                "commission_pct": 0.06,
                "listed_at": "2026-08-05T00:00:00Z",
            },
            AGENT,
        ),
        201,
    )
    set_clock("2026-08-24T00:00:00Z")
    offer = create_offer(case["id"])

    validate_error(
        api.submit_offer(offer["id"], NEG), ApiErrorId.ERR_HARDSHIP_NOT_ACCEPTED.value
    )

    stored_offer = validate_success(api.get_offer(offer["id"], NEG), 200)
    assert stored_offer["status"] == "DRAFT"
    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "ACTIVE", (
        "the refused submission must not put the listing under contract"
    )


def test_the_same_submission_succeeds_once_the_package_is_accepted(api):
    """PRD §3.5: "First, the case's hardship package must exist and be `ACCEPTED` — this
    is the real gate, and the case's negotiation dimension reading `MARKETED` or
    `RENEGOTIATION` is a consequence of that acceptance rather than a second, separate
    check; a case without an accepted package is refused with
    `ERR_HARDSHIP_NOT_ACCEPTED`."
    PRD §3.3: "A successful `ACCEPT` moves the package to `ACCEPTED` and carries the
    case's negotiation dimension from `PACKAGE_REVIEW` to `MARKETED`."

    Design: Difficulty/cross_entity_state_dependency/offer_submission_gated_on_hardship_package_state
    """
    case, package, _ = setup_submitted_package()
    validate_success(
        api.create_listing(
            case["id"],
            {
                "list_price_cents": 25_900_000,
                "commission_pct": 0.06,
                "listed_at": "2026-08-05T00:00:00Z",
            },
            AGENT,
        ),
        201,
    )
    set_clock("2026-08-24T00:00:00Z")
    offer = create_offer(case["id"])
    validate_error(
        api.submit_offer(offer["id"], NEG), ApiErrorId.ERR_HARDSHIP_NOT_ACCEPTED.value
    )

    accepted = validate_success(
        api.decide_hardship_package(package["id"], package_decision_payload("ACCEPT"), ANALYST),
        200,
    )
    assert accepted["status"] == "ACCEPTED"

    submitted = validate_success(api.submit_offer(offer["id"], NEG), 200)

    assert submitted["status"] == "SUBMITTED"
    listings = validate_success(api.list_case_listings(case["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "UNDER_CONTRACT"
    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["negotiation_status"] == "OFFER_UNDER_REVIEW"


def test_second_rejection_raises_the_price_reduction_gate(api):
    """PRD §3.5: "The second hop, caused by the first, returns the controlling listing
    from `UNDER_CONTRACT` to `ACTIVE` and raises the case's `failed_offer_count` by one;
    the case's negotiation dimension falls back from `OFFER_UNDER_REVIEW` to `MARKETED`
    and the property is on the market again."
    PRD §3.5: "The third hop, caused by the second, fires only when the case's
    `failed_offer_count` has now reached **2 or more** — that is, on the second rejection
    and on every rejection after it — and sets `price_reduction_required` to true, which
    blocks any further offer submission until the brokerage records a price reduction."

    Design: Difficulty/transitive_cascade/second_offer_rejection_forces_price_reduction_and_package_revalidation
    """
    scenario = setup_case_with_submitted_offer()
    case_id = scenario["case"]["id"]

    reject_offer(scenario["offer"]["id"])
    after_first = validate_success(api.get_case(case_id, NEG), 200)
    assert after_first["failed_offer_count"] == 1
    assert after_first["price_reduction_required"] is False, (
        "the third hop does not fire on the first rejection"
    )

    second = create_offer(case_id, buyer_name="Second Buyer", offer_price_cents=24_300_000)
    submit_offer(second["id"])
    rejected = validate_success(
        api.servicer_decision_on_offer(
            second["id"], servicer_decision_payload("REJECT", note="Still below floor"), ANALYST
        ),
        200,
    )

    assert rejected["status"] == "REJECTED"
    listings = validate_success(api.list_case_listings(case_id, NEG), 200)
    assert listings[0]["marketing_status"] == "ACTIVE"

    after_second = validate_success(api.get_case(case_id, NEG), 200)
    assert after_second["failed_offer_count"] == 2
    assert after_second["price_reduction_required"] is True
    assert after_second["negotiation_status"] == "MARKETED"


def test_second_rejection_invalidates_the_hardship_file(api):
    """PRD §3.5: "The fourth hop, caused by the third and therefore firing only when the
    third fired, invalidates the hardship file: the case's hardship package moves from
    `ACCEPTED` to `REVALIDATION_REQUIRED`, its `hardship_score_audit` is cleared back to
    null, and the case's documentation dimension moves from `DOC_COMPLETE` to
    `DOC_STALE`."

    Design: Difficulty/transitive_cascade/second_offer_rejection_forces_price_reduction_and_package_revalidation
    """
    scenario = setup_case_after_two_rejected_offers()

    package = validate_success(
        api.get_hardship_package(scenario["package"]["id"], NEG), 200
    )
    assert package["status"] == "REVALIDATION_REQUIRED"
    assert package["hardship_score_audit"] is None

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["documentation_status"] == "DOC_STALE"
    assert case_after["negotiation_status"] == "MARKETED"


def test_price_reduction_gate_blocks_then_clears_the_next_submission(api):
    """PRD §3.5: "Third, the case's `price_reduction_required` gate must be clear; a case
    carrying an outstanding price-reduction obligation is refused with
    `ERR_PRICE_REDUCTION_REQUIRED` until the brokerage records a reduction."
    PRD §3.4: "The agent supplies `new_list_price_cents`; the server replaces
    `list_price_cents` with it, raises `price_reduction_count` by one, and — this is the
    part that matters upstream — clears the owning case's `price_reduction_required` gate
    back to false."

    Design: Corner/validations/price_reduction_gate_blocks_then_clears_submission
    """
    scenario = setup_case_after_two_rejected_offers()
    case_id = scenario["case"]["id"]
    package_id = scenario["package"]["id"]
    listing_id = scenario["listing"]["id"]

    # Clear the hardship gate first so the price-reduction gate is the live one.
    validate_success(api.submit_hardship_package(package_id, NEG), 200)
    validate_success(
        api.decide_hardship_package(package_id, package_decision_payload("ACCEPT"), ANALYST), 200
    )
    third = create_offer(case_id, buyer_name="Third Buyer", offer_price_cents=24_100_000)

    validate_error(
        api.submit_offer(third["id"], NEG), ApiErrorId.ERR_PRICE_REDUCTION_REQUIRED.value
    )

    reduced = validate_success(
        api.record_price_reduction(listing_id, price_reduction_payload(24_900_000), AGENT), 200
    )
    assert reduced["list_price_cents"] == 24_900_000
    assert reduced["price_reduction_count"] == 1

    cleared_case = validate_success(api.get_case(case_id, NEG), 200)
    assert cleared_case["price_reduction_required"] is False

    submitted = validate_success(api.submit_offer(third["id"], NEG), 200)
    assert submitted["status"] == "SUBMITTED"

    final_case = validate_success(api.get_case(case_id, NEG), 200)
    assert final_case["failed_offer_count"] == 2, (
        "a price reduction does not rewrite the failed-offer tally"
    )


def test_fourth_negotiation_round_exhausts_the_budget(api):
    """PRD §3.5: "Fourth, when the offer being submitted is a `REVISED` one, the round
    budget must accommodate another round: the offer's `round_index` incremented by one
    must be no greater than **3**, and a fourth round is refused with
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Corner/validations/negotiation_rounds_exhausted_on_fourth_submission
    """
    scenario = setup_case_with_submitted_offer()
    offer_id = scenario["offer"]["id"]

    offer = run_counter_revise_rounds(
        offer_id,
        [
            (25_400_000, 25_100_000),
            (25_600_000, 25_300_000),
            (25_800_000, 25_500_000),
        ],
    )
    assert offer["status"] == "REVISED"
    assert offer["round_index"] == 3

    validate_error(
        api.submit_offer(offer_id, NEG),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
    )

    stored = validate_success(api.get_offer(offer_id, NEG), 200)
    assert stored["status"] == "REVISED"
    assert stored["round_index"] == 3
    assert stored["offer_price_cents"] == 25_500_000

    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "UNDER_CONTRACT"
