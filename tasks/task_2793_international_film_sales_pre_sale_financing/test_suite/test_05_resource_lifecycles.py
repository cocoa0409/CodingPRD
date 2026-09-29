"""Resource lifecycle behaviour: valid transitions and their version bumps,
transition preconditions, initial states, the three independent contract axes,
market-close and wrap cascades, terminal-state lockdown, repeated triggers, the
delivery pass and cure branches, the reversible account lock, and tier status
derived from a banking facility.

Every test builds its own preconditions through the declared endpoints only and
pins the logical clock as its first call.
"""

from test_helpers import (
    AGREEMENT_TERM_END,
    CLOCK_DEFAULT,
    CONTRACT_HOLDBACK_RELEASE,
    CONTRACT_MG,
    FACILITY_ADVANCE_UNBONDED,
    FACILITY_COLLATERAL,
    HEAD_OF_SALES_USER,
    LENDER_APPROVER,
    MARKET_ROOMS,
    MARKET_TABLES,
    SALES_AGENT_USER,
    approve_facility,
    assert_account_counters,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_facility_figures,
    assert_film_counters,
    assert_instant,
    assert_money,
    assert_object_response,
    assert_tier,
    buyer_meeting_payload,
    execute_agreement,
    executed_contract,
    executed_contract_environment,
    make_account,
    make_agreement,
    make_buyer_headers,
    make_collection_agent_headers,
    make_delivery_manager_headers,
    make_facility,
    make_film,
    make_head_of_sales_headers,
    make_market,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_tiers,
    meeting_completion_payload,
    milestone_by_label,
    offered_contract,
    open_market,
    package_payload,
    pin_clock,
    post_receipt,
    qc_fail_payload,
    qc_pass_payload,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_film,
    read_milestones,
    read_tiers,
    read_valuation,
    receipt_payload,
    record_qc_fail,
    record_qc_pass,
    screening_slot_payload,
    slate_with_published_valuation,
    state_payload,
    submit_package,
    validate_error,
)

SLOT_START = "2026-11-06T09:00:00Z"
SLOT_END = "2026-11-06T11:00:00Z"
MEETING_START = "2026-11-06T14:00:00Z"
MEETING_END = "2026-11-06T15:00:00Z"


class TestMarketLifecycle:
    def test_opening_a_planned_market_advances_its_version_and_keeps_its_inventory(
        self, api
    ):
        """The opening edge is legal and its only side effect is the version bump.

        PRD: "A market's lifecycle is linear: `PLANNED → OPEN → CLOSED`, both edges reserved to `PlatformAdmin`. Opening requires only that `end_date` be strictly after `start_date`."

        PRD: "Whenever a row is mutated — whether the client targeted it directly or a cascade reached it — that row's `updated_at` is refreshed, and its `version` is incremented by 1 unless it is one of the three version-free resource types named in §2.4."

        Design: Corner/state_machines/market_planned_to_open_is_a_valid_transition_that_bumps_version
        """
        pin_clock(api, CLOCK_DEFAULT)
        created = make_market(api)
        assert created["status"] == "PLANNED"
        assert created["version"] == 1

        opened = assert_object_response(
            api.set_market_state(
                created["id"], state_payload("OPEN"), make_platform_admin_headers()
            )
        )

        assert opened["status"] == "OPEN"
        assert opened["version"] == 2
        assert opened["screening_room_count"] == MARKET_ROOMS
        assert opened["meeting_table_count"] == MARKET_TABLES

    def test_a_backward_and_a_post_terminal_market_move_are_both_rejected(self, api):
        """Neither OPEN back to PLANNED nor CLOSED back to OPEN is a declared edge.

        PRD: "A destination that no transition out of the current status permits is rejected with `ERR_INVALID_STATE`, as is a destination equal to the current status."

        Design: Corner/state_machines/market_backward_and_post_terminal_transitions_are_rejected
        """
        pin_clock(api, CLOCK_DEFAULT)
        market = make_market(api)
        open_market(api, market["id"])

        backward = api.set_market_state(
            market["id"], state_payload("PLANNED"), make_platform_admin_headers()
        )
        validate_error(backward, "ERR_INVALID_STATE", 409)
        still_open = assert_object_response(
            api.get_market(market["id"], make_platform_admin_headers())
        )
        assert still_open["status"] == "OPEN"
        assert still_open["version"] == 2

        assert_object_response(
            api.set_market_state(
                market["id"], state_payload("CLOSED"), make_platform_admin_headers()
            )
        )
        reopen = api.set_market_state(
            market["id"], state_payload("OPEN"), make_platform_admin_headers()
        )
        validate_error(reopen, "ERR_INVALID_STATE", 409)

        closed = assert_object_response(
            api.get_market(market["id"], make_platform_admin_headers())
        )
        assert closed["status"] == "CLOSED"
        assert closed["version"] == 3

    def test_closing_the_market_cancels_held_slots_and_no_shows_scheduled_meetings(
        self, api
    ):
        """One close request drives two child machines to two different states.

        PRD: "Closing has no precondition of its own but carries a conditional cascade: every screening slot of this market still in `HELD` moves to `CANCELLED`, and every buyer meeting still in `SCHEDULED` moves to `NO_SHOW`."

        PRD: "`SCHEDULED → NO_SHOW` has no precondition, may also arrive as the market-closing cascade, and likewise keeps consuming the buyer's minutes budget — a distributor who fails to appear does not get those minutes back."

        Design: Corner/state_machines/market_close_cascades_held_slots_to_cancelled_and_meetings_to_no_show
        """
        env = slate_with_published_valuation(api)
        market = make_market(api)
        open_market(api, market["id"])

        slot = assert_created(
            api.create_screening_slot(
                screening_slot_payload(
                    market["id"], env["film"]["id"], 1, SLOT_START, SLOT_END, capacity=60
                ),
                make_sales_agent_headers(),
            )
        )
        meeting = assert_created(
            api.create_buyer_meeting(
                buyer_meeting_payload(
                    market["id"],
                    env["buyer"]["id"],
                    env["film"]["id"],
                    1,
                    MEETING_START,
                    MEETING_END,
                ),
                make_sales_agent_headers(),
            )
        )
        assert slot["status"] == "HELD"
        assert meeting["status"] == "SCHEDULED"

        closed = assert_object_response(
            api.set_market_state(
                market["id"], state_payload("CLOSED"), make_platform_admin_headers()
            )
        )

        assert closed["status"] == "CLOSED"
        assert closed["version"] == 3
        cancelled_slot = assert_object_response(
            api.get_screening_slot(slot["id"], make_sales_agent_headers())
        )
        assert cancelled_slot["status"] == "CANCELLED"
        no_show = assert_object_response(
            api.get_buyer_meeting(meeting["id"], make_sales_agent_headers())
        )
        assert no_show["status"] == "NO_SHOW"
        assert no_show["duration_minutes"] == 60
        assert no_show["outcome"] is None


class TestFilmLifecyclePreconditions:
    def test_packaging_is_refused_while_the_only_agency_agreement_is_still_draft(
        self, api
    ):
        """Without an executed representation agreement the picture cannot package.

        PRD: "`DEVELOPMENT → PACKAGING` is available to `PlatformAdmin` and requires that at least one sales agency agreement for the picture already be `EXECUTED` — the agency must be formally engaged before the picture may be packaged."

        PRD: "Whether the row's own current status permits the requested transition, including a repeated trigger on a row already in the destination state or already in a terminal state, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/film_development_to_packaging_requires_an_executed_agency_agreement
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api)
        agreement = make_agreement(api, film["id"])
        assert agreement["status"] == "DRAFT"

        response = api.set_film_state(
            film["id"], state_payload("PACKAGING"), make_platform_admin_headers()
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        unchanged = read_film(api, film["id"])
        assert unchanged["sales_status"] == "DEVELOPMENT"
        assert unchanged["version"] == 1

    def test_executing_the_agreement_stamps_its_term_and_unblocks_packaging(self, api):
        """Execution records the signer and the computed term, and packaging then passes.

        PRD: "Execution records `executed_by_user_id` from `X-User-ID` and recomputes `term_end_date` from `term_start_date` and `term_months`."

        PRD: "The service computes `term_end_date` by adding `term_months` calendar months to `term_start_date`: calendar-month addition keeps the same day of month, and when the target month is shorter it clamps to that month's last day."

        PRD: "Both transitions increment the picture's `version` by 1."

        Design: Corner/state_machines/film_development_to_packaging_requires_an_executed_agency_agreement
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api)
        agreement = make_agreement(api, film["id"])
        execute_agreement(api, agreement["id"])

        stored = read_agreement(api, film["id"], agreement["id"])
        assert stored["status"] == "EXECUTED"
        assert stored["executed_by_user_id"] == HEAD_OF_SALES_USER
        assert_instant(stored["term_end_date"], AGREEMENT_TERM_END, "term_end_date")

        packaged = assert_object_response(
            api.set_film_state(
                film["id"], state_payload("PACKAGING"), make_platform_admin_headers()
            )
        )
        assert packaged["sales_status"] == "PACKAGING"
        assert packaged["version"] == 2


class TestContractAxes:
    def test_a_new_contract_opens_on_all_three_axes_at_once(self, api):
        """Creation seeds the negotiation, delivery and collection axes together.

        PRD: "A newly created contract sits at `negotiation_status` `OFFERED`, `delivery_status` `PENDING` and `collection_status` `UNPAID`, with `negotiation_round` at 1, `milestone_pct_total` at 0.0000, `counter_minimum_guarantee_usd` null and `offered_by_user_id` recorded from `X-User-ID`."

        PRD: "Its `license_start_date`, `license_end_date` and `holdback_release_date` are all left null; those are stamped only at countersigning."

        PRD: "The contract's `unpaid_amount_usd` is computed as the sum of `amount_usd` across its `SCHEDULED` and `INVOICED` payment milestones, and `received_amount_usd` as the sum of `received_amount_usd` across its `RECEIVED` milestones."

        Design: Corner/state_machines/contract_initial_state_is_offered_pending_unpaid_on_all_three_axes
        """
        env = offered_contract(api)
        contract = env["contract"]

        assert_contract_axes(
            contract, negotiation="OFFERED", delivery="PENDING", collection="UNPAID"
        )
        assert contract["negotiation_round"] == 1
        assert contract["milestone_pct_total"] == 0
        assert_money(contract["unpaid_amount_usd"], 0.00, "unpaid_amount_usd")
        assert_money(contract["received_amount_usd"], 0.00, "received_amount_usd")
        assert contract["counter_minimum_guarantee_usd"] is None
        assert contract["license_start_date"] is None
        assert contract["executed_by_user_id"] is None
        assert contract["offered_by_user_id"] == SALES_AGENT_USER

    def test_one_receipt_moves_only_the_collection_axis(self, api):
        """Cash advances on its own axis while the other two stand still.

        PRD: "`UNPAID → PARTIALLY_PAID` fires when, after the receipt, the contract's `received_amount_usd` is greater than zero **and** its `unpaid_amount_usd` is still greater than zero."

        PRD: "A contract may be `EXECUTED` and `REJECTED` and `PARTIALLY_PAID` all at once; no axis constrains another's enumerated values, and each advances on its own triggers."

        Design: Corner/state_machines/parallel_axes_collection_advances_while_negotiation_and_delivery_hold
        """
        env = executed_contract_environment(api)
        signature = milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE")

        post_receipt(api, signature, "2026-08-05T00:00:00Z")

        contract = read_contract(api, env["contract"]["id"])
        assert_contract_axes(
            contract, negotiation="EXECUTED", delivery="PENDING", collection="PARTIALLY_PAID"
        )
        assert_money(contract["received_amount_usd"], 900000.00, "received_amount_usd")
        assert_money(contract["unpaid_amount_usd"], 1100000.00, "unpaid_amount_usd")

        milestones = read_milestones(api, env["contract"]["id"])
        assert milestone_by_label(milestones, "ON_SIGNATURE")["status"] == "RECEIVED"
        for label in ("ON_DELIVERY", "ON_RELEASE", "ON_TERM_END"):
            assert milestone_by_label(milestones, label)["status"] == "SCHEDULED"

        account = read_account(api, env["account"]["id"])
        assert_account_counters(account, receipts=900000.00, balance=900000.00)


class TestWrapCascade:
    def test_wrapping_the_picture_closes_its_account_and_expires_its_agreement(self, api):
        """The terminal film move drives two other aggregates to terminal states.

        PRD: "The side effects: every collection account of the picture that is still `OPEN` moves to `CLOSED`, the picture's `EXECUTED` sales agency agreement moves to `EXPIRED`, and the picture's `version` increments by 1."

        PRD: "Wrapping the picture is the terminal move, available to `HeadOfSales` from either `IN_MARKET` or `SOLD_OUT`."

        Design: Corner/state_machines/film_wrapped_closes_the_collection_account_and_expires_the_agreement
        """
        env = slate_with_published_valuation(api)
        account = make_account(api, env["film"]["id"])
        version_before_wrap = read_film(api, env["film"]["id"])["version"]

        wrapped = assert_object_response(
            api.set_film_state(
                env["film"]["id"], state_payload("WRAPPED"), make_head_of_sales_headers()
            )
        )

        assert wrapped["sales_status"] == "WRAPPED"
        assert wrapped["version"] == version_before_wrap + 1
        closed_account = read_account(api, account["id"])
        assert closed_account["status"] == "CLOSED"
        assert_money(closed_account["balance_usd"], 0.00, "balance_usd")
        assert (
            read_agreement(api, env["film"]["id"], env["agreement"]["id"])["status"]
            == "EXPIRED"
        )
        assert read_valuation(api, env["valuation"]["id"])["status"] == "PUBLISHED"
        assert_film_counters(read_film(api, env["film"]["id"]), published_count=1)


class TestTerminalStates:
    def test_a_cancelled_screening_slot_cannot_later_be_confirmed(self, api):
        """Cancellation is terminal even while the market is still trading.

        PRD: "Cancellation is reachable from either of the slot's two live states: both `HELD → CANCELLED` and `CONFIRMED → CANCELLED` are legal, neither carries any precondition, and both have the same effect: the market-and-room interval is released so that a later slot may occupy it. `CANCELLED` is terminal."

        PRD: "Whether the row's own current status permits the requested transition, including a repeated trigger on a row already in the destination state or already in a terminal state, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/screening_slot_cancelled_is_terminal_and_rejects_a_later_confirm
        """
        env = slate_with_published_valuation(api)
        market = make_market(api)
        open_market(api, market["id"])
        slot = assert_created(
            api.create_screening_slot(
                screening_slot_payload(
                    market["id"], env["film"]["id"], 1, SLOT_START, SLOT_END, capacity=60
                ),
                make_sales_agent_headers(),
            )
        )
        cancelled = assert_object_response(
            api.set_screening_slot_state(
                slot["id"], state_payload("CANCELLED"), make_sales_agent_headers()
            )
        )
        assert cancelled["status"] == "CANCELLED"

        response = api.set_screening_slot_state(
            slot["id"], state_payload("CONFIRMED"), make_sales_agent_headers()
        )

        validate_error(response, "ERR_INVALID_STATE", 409)
        assert (
            assert_object_response(
                api.get_screening_slot(slot["id"], make_sales_agent_headers())
            )["status"]
            == "CANCELLED"
        )
        assert (
            assert_object_response(
                api.get_market(market["id"], make_platform_admin_headers())
            )["status"]
            == "OPEN"
        )


class TestEdgeSpecificPayloads:
    def test_completing_a_meeting_requires_the_outcome_the_edge_consumes(self, api):
        """The completion edge is the only one that consumes an outcome, and needs it.

        PRD: "`SCHEDULED → COMPLETED` requires an `outcome` in the payload, and that value must be one of `PASS`, `INTERESTED` or `OFFER_REQUESTED`; the supplied value is written to the meeting's `outcome` field, and the meeting's `duration_minutes` continues to count against the buyer's minutes budget."

        Design: Corner/state_machines/buyer_meeting_completed_without_the_outcome_field_is_invalid_request
        """
        env = slate_with_published_valuation(api)
        market = make_market(api)
        open_market(api, market["id"])
        meeting = assert_created(
            api.create_buyer_meeting(
                buyer_meeting_payload(
                    market["id"],
                    env["buyer"]["id"],
                    env["film"]["id"],
                    1,
                    MEETING_START,
                    MEETING_END,
                ),
                make_sales_agent_headers(),
            )
        )

        missing_outcome = api.set_buyer_meeting_state(
            meeting["id"], state_payload("COMPLETED"), make_sales_agent_headers()
        )

        validate_error(missing_outcome, "ERR_INVALID_REQUEST", 400)
        still_scheduled = assert_object_response(
            api.get_buyer_meeting(meeting["id"], make_sales_agent_headers())
        )
        assert still_scheduled["status"] == "SCHEDULED"
        assert still_scheduled["outcome"] is None

        completed = assert_object_response(
            api.set_buyer_meeting_state(
                meeting["id"],
                meeting_completion_payload("INTERESTED"),
                make_sales_agent_headers(),
            )
        )
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "INTERESTED"
        assert completed["duration_minutes"] == 60


class TestRepeatedTriggers:
    def test_accepting_the_same_offer_twice_fails_and_does_not_double_count_exposure(
        self, api
    ):
        """Acceptance is not idempotent and the second attempt changes nothing.

        PRD: "`OFFERED → ACCEPTED` is the buyer's other move, reserved to the `Buyer` role acting as the contract's own buyer, and takes no payload at all."

        PRD: "Acceptance recomputes the picture's `total_mg_committed_usd` and `financing_gap_usd` and increments the picture's `version`, and recomputes the buyer's gross pipeline exposure and increments the buyer's `version` — because an accepted contract is a commitment, and the financing gap the production is trying to close must reflect it immediately."

        Design: Corner/state_machines/contract_accept_twice_is_rejected_on_the_second_attempt
        """
        env = offered_contract(api)
        buyer_headers = make_buyer_headers(env["buyer"]["id"])

        first = assert_object_response(
            api.accept_contract(env["contract"]["id"], buyer_headers)
        )
        assert first["negotiation_status"] == "ACCEPTED"

        second = api.accept_contract(env["contract"]["id"], buyer_headers)

        validate_error(second, "ERR_INVALID_STATE", 409)
        assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=CONTRACT_MG)
        assert_film_counters(
            read_film(api, env["film"]["id"]), committed=2000000.00, gap=22000000.00
        )


class TestDeliveryPassBranch:
    def test_a_first_round_pass_accepts_the_delivery_axis_without_a_cure_deadline(
        self, api
    ):
        """A round-1 pass lands on ACCEPTED, never on CURED.

        PRD: "A submitted package has `status` `SUBMITTED`, `qc_result` `PENDING`, `rejection_reason` null, `cure_deadline` null, `submitted_at` stamped with the logical present instant and `submitted_by_user_id` recorded from `X-User-ID`."

        PRD: "A package at `revision_round` 1 drives the contract's `delivery_status` to `ACCEPTED`."

        Design: Corner/state_machines/deliverable_pass_on_round_one_accepts_delivery_and_invoices_on_delivery
        """
        env = executed_contract(api)
        pin_clock(api, CONTRACT_HOLDBACK_RELEASE)

        submitted = assert_created(
            api.create_deliverable_package(
                env["contract"]["id"],
                package_payload(14, 6),
                make_delivery_manager_headers(),
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["qc_result"] == "PENDING"
        assert submitted["revision_round"] == 1
        assert submitted["cure_deadline"] is None

        accepted = assert_object_response(
            api.post_qc_result(
                submitted["id"],
                qc_pass_payload(),
                make_buyer_headers(env["buyer"]["id"]),
            )
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["qc_result"] == "PASS"
        assert accepted["cure_deadline"] is None
        assert read_contract(api, env["contract"]["id"])["delivery_status"] == "ACCEPTED"

    def test_a_first_round_pass_invoices_on_delivery_and_leaves_on_release_alone(
        self, api
    ):
        """The no-cure branch invoices one milestone and pushes no due date.

        PRD: "Both branches move the milestone labelled `ON_DELIVERY` from `SCHEDULED` to `INVOICED`. The `CURED` branch carries one extra side effect the `ACCEPTED` branch does not: the milestone labelled `ON_RELEASE` has its `due_date` pushed out by 30 days."

        Design: Corner/state_machines/deliverable_pass_on_round_one_accepts_delivery_and_invoices_on_delivery
        """
        env = executed_contract(api)
        pin_clock(api, CONTRACT_HOLDBACK_RELEASE)
        package = submit_package(api, env["contract"]["id"])
        record_qc_pass(api, package["id"], env["buyer"]["id"])

        milestones = read_milestones(api, env["contract"]["id"])

        on_delivery = milestone_by_label(milestones, "ON_DELIVERY")
        assert on_delivery["status"] == "INVOICED"
        assert_money(on_delivery["amount_usd"], 400000.00, "amount_usd")
        on_release = milestone_by_label(milestones, "ON_RELEASE")
        assert_instant(on_release["due_date"], "2027-07-15T00:00:00Z", "due_date")
        assert_contract_axes(
            read_contract(api, env["contract"]["id"]),
            negotiation="EXECUTED",
            delivery="ACCEPTED",
            collection="UNPAID",
        )


class TestDeliveryCureBranch:
    def test_a_failing_verdict_rejects_the_package_and_opens_a_cure_window(self, api):
        """The failure stamps a cure deadline and the resubmission raises the round.

        PRD: "**A failing verdict below the revision limit** sets `qc_result` to `FAIL`, writes the supplied `rejection_reason`, moves the package `SUBMITTED → REJECTED`, stamps its `cure_deadline` as 30 days after the package's `submitted_at`, and drives the contract's `delivery_status` to `REJECTED`."

        PRD: "Resubmission creates a *new* package at one higher `revision_round`, moving the contract's delivery axis `REJECTED → SUBMITTED` again."

        Design: Corner/state_machines/deliverable_cure_round_pushes_the_on_release_due_date_by_the_cure_window
        """
        env = executed_contract(api)
        pin_clock(api, CONTRACT_HOLDBACK_RELEASE)
        first_package = submit_package(api, env["contract"]["id"])

        rejected = assert_object_response(
            api.post_qc_result(
                first_package["id"],
                qc_fail_payload("QC_FAIL"),
                make_buyer_headers(env["buyer"]["id"]),
            )
        )

        assert rejected["status"] == "REJECTED"
        assert rejected["qc_result"] == "FAIL"
        assert rejected["rejection_reason"] == "QC_FAIL"
        assert_instant(rejected["cure_deadline"], "2027-07-14T00:00:00Z", "cure_deadline")
        assert read_contract(api, env["contract"]["id"])["delivery_status"] == "REJECTED"

        pin_clock(api, "2027-06-20T00:00:00Z")
        second_package = assert_created(
            api.create_deliverable_package(
                env["contract"]["id"],
                package_payload(14, 6),
                make_delivery_manager_headers(),
            )
        )
        assert second_package["revision_round"] == 2
        assert second_package["status"] == "SUBMITTED"
        assert read_contract(api, env["contract"]["id"])["delivery_status"] == "SUBMITTED"

    def test_a_second_round_pass_cures_the_contract_and_pushes_on_release_out(self, api):
        """Only the cure branch moves the ON_RELEASE due date, and only by 30 days.

        PRD: "A package at `revision_round` 2 or above drives it to `CURED` instead."

        PRD: "The `CURED` branch carries one extra side effect the `ACCEPTED` branch does not: the milestone labelled `ON_RELEASE` has its `due_date` pushed out by 30 days."

        Design: Corner/state_machines/deliverable_cure_round_pushes_the_on_release_due_date_by_the_cure_window
        """
        env = executed_contract(api)
        pin_clock(api, CONTRACT_HOLDBACK_RELEASE)
        first_package = submit_package(api, env["contract"]["id"])
        record_qc_fail(api, first_package["id"], env["buyer"]["id"], "QC_FAIL")
        pin_clock(api, "2027-06-20T00:00:00Z")
        second_package = submit_package(api, env["contract"]["id"])

        cured = assert_object_response(
            api.post_qc_result(
                second_package["id"],
                qc_pass_payload(),
                make_buyer_headers(env["buyer"]["id"]),
            )
        )

        assert cured["status"] == "ACCEPTED"
        assert read_contract(api, env["contract"]["id"])["delivery_status"] == "CURED"
        milestones = read_milestones(api, env["contract"]["id"])
        on_delivery = milestone_by_label(milestones, "ON_DELIVERY")
        assert on_delivery["status"] == "INVOICED"
        assert_money(on_delivery["amount_usd"], 400000.00, "amount_usd")
        on_release = milestone_by_label(milestones, "ON_RELEASE")
        assert_instant(on_release["due_date"], "2027-08-14T00:00:00Z", "due_date")
        assert_money(on_release["amount_usd"], 200000.00, "amount_usd")


class TestAccountLockIsReversible:
    def test_a_locked_account_refuses_a_receipt_and_leaves_the_milestone_invoiced(
        self, api
    ):
        """The lock blocks cash without touching the milestone or the balance.

        PRD: "A `CollectionAgent` may lock and unlock the account at will: `OPEN → LOCKED` and `LOCKED → OPEN` carry no preconditions. While the account is `LOCKED`, no receipt, no reversal and no distribution may touch it."

        PRD: "Three operations require a collection account that exists and is `OPEN` for the relevant picture and report `ERR_COLLECTION_ACCOUNT_NOT_OPEN` when there is none: posting a receipt, reversing a receipt, and running a distribution."

        Design: Corner/state_machines/locking_the_collection_account_blocks_receipts_until_it_is_reopened
        """
        env = executed_contract_environment(api)
        locked = assert_object_response(
            api.set_account_state(
                env["account"]["id"],
                state_payload("LOCKED"),
                make_collection_agent_headers(),
            )
        )
        assert locked["status"] == "LOCKED"
        milestone = milestone_by_label(env, "ON_SIGNATURE")

        response = api.post_receipt(
            milestone["id"],
            receipt_payload(milestone["amount_usd"], "2026-08-05T00:00:00Z"),
            make_collection_agent_headers(),
        )

        validate_error(response, "ERR_COLLECTION_ACCOUNT_NOT_OPEN", 409)
        assert (
            milestone_by_label(
                read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE"
            )["status"]
            == "INVOICED"
        )
        assert_account_counters(
            read_account(api, env["account"]["id"]), receipts=0.00, balance=0.00
        )

    def test_reopening_the_account_makes_the_very_same_receipt_succeed(self, api):
        """LOCKED is a reversible pause, so the identical request then goes through.

        PRD: "A `CollectionAgent` may lock and unlock the account at will: `OPEN → LOCKED` and `LOCKED → OPEN` carry no preconditions."

        PRD: "A successful receipt sets the milestone's `status` to `RECEIVED`, writes `received_amount_usd` to the posted amount, writes `received_at` from the payload and `received_by_user_id` from `X-User-ID`. The account's `total_receipts_usd` grows by the amount and `balance_usd` is recomputed."

        Design: Corner/state_machines/locking_the_collection_account_blocks_receipts_until_it_is_reopened
        """
        env = executed_contract_environment(api)
        assert_object_response(
            api.set_account_state(
                env["account"]["id"],
                state_payload("LOCKED"),
                make_collection_agent_headers(),
            )
        )
        reopened = assert_object_response(
            api.set_account_state(
                env["account"]["id"],
                state_payload("OPEN"),
                make_collection_agent_headers(),
            )
        )
        assert reopened["status"] == "OPEN"
        milestone = milestone_by_label(env, "ON_SIGNATURE")

        assert_object_response(
            api.post_receipt(
                milestone["id"],
                receipt_payload(milestone["amount_usd"], "2026-08-05T00:00:00Z"),
                make_collection_agent_headers(),
            )
        )

        assert (
            milestone_by_label(
                read_milestones(api, env["contract"]["id"]), "ON_SIGNATURE"
            )["status"]
            == "RECEIVED"
        )
        assert_account_counters(
            read_account(api, env["account"]["id"]),
            receipts=900000.00,
            balance=900000.00,
        )


class TestTierStatusFollowsTheFacility:
    def test_the_bank_debt_tier_stays_suspended_until_a_facility_is_approved(self, api):
        """A tier's status is derived from another aggregate, and PROPOSED is not enough.

        PRD: "A tier is `SUSPENDED` when its `tier_type` is `BANK_DEBT` and no banking facility of the account's picture is in `APPROVED`, `DRAWN` or `MARGIN_CALL` — there is no bank to pay, so the tier absorbs nothing and the cash flows past it to equity."

        PRD: "Approval records `approved_by_user_id` from `X-User-ID`, recomputes `eligible_collateral_usd` and `advance_amount_usd`, and re-derives the picture's `BANK_DEBT` waterfall tier from `SUSPENDED` to `ACTIVE` — until a bank is actually on the hook, that tier absorbs nothing."

        Design: Corner/state_machines/bank_debt_tier_is_suspended_until_a_facility_reaches_approved
        """
        env = executed_contract_environment(api)
        make_tiers(api, env["account"]["id"], [(1, "BANK_DEBT", 1.00, None)])

        assert_tier(read_tiers(api, env["account"]["id"])[0], status="SUSPENDED")

        facility = make_facility(api, env["film"]["id"])
        assert facility["status"] == "PROPOSED"
        assert_tier(read_tiers(api, env["account"]["id"])[0], status="SUSPENDED")

        approve_facility(api, facility["id"])

        assert_tier(read_tiers(api, env["account"]["id"])[0], status="ACTIVE")

    def test_approval_publishes_the_unbonded_advance_and_activates_the_tier(self, api):
        """Approval stamps the approver and republishes both lending figures.

        PRD: "Approval records `approved_by_user_id` from `X-User-ID`, recomputes `eligible_collateral_usd` and `advance_amount_usd`, and re-derives the picture's `BANK_DEBT` waterfall tier from `SUSPENDED` to `ACTIVE` — until a bank is actually on the hook, that tier absorbs nothing."

        PRD: "A tier is `SATISFIED` when its `cap_usd` is not null and its `recouped_usd` has reached or passed that cap."

        Design: Corner/state_machines/bank_debt_tier_is_suspended_until_a_facility_reaches_approved
        """
        env = executed_contract_environment(api)
        make_tiers(api, env["account"]["id"], [(1, "BANK_DEBT", 1.00, None)])
        facility = make_facility(api, env["film"]["id"])

        approved = approve_facility(api, facility["id"])

        assert approved["approved_by_user_id"] == LENDER_APPROVER
        assert approved["completion_bond_required"] is True
        assert approved["completion_bond_posted"] is False
        assert_facility_figures(
            approved,
            collateral=FACILITY_COLLATERAL,
            advance=FACILITY_ADVANCE_UNBONDED,
            status="APPROVED",
        )
        tier = read_tiers(api, env["account"]["id"])[0]
        assert_tier(tier, recouped=0.00, status="ACTIVE")
        assert tier["cap_usd"] is None
