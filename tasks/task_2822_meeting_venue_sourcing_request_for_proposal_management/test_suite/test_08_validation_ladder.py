"""Validation ladders of the venue sourcing API.

Each test drives one guard to its refusal and then repairs exactly the field the
guard names, so that the ordering between two guards on the same endpoint, the
open and closed ends of the temporal windows, and the snapshot the preferred
programme restriction reads are all pinned by the observed outcome.
"""

from test_helpers import (
    CLOCK_SOURCING_WINDOW,
    FINANCE_HEADERS,
    PLANNER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    make_venue_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as domain_assert
from test_helpers import factories, fixtures


def _installments_by_seq(world):
    return {
        installment["installment_seq"]: installment
        for installment in world["installments"]
    }


class TestDepositPaymentLadder:
    """The sequence guard, then the amount guard, then the accepted payment."""

    def test_paying_the_second_installment_first_is_refused(self):
        """The correct amount on the wrong installment is still refused.

        Every installment on the same contract with a lower `installment_seq` must already be `PAID`, otherwise `ERR_DEPOSIT_SEQUENCE_VIOLATION`; deposits are consumed strictly in order.

        Design: Corner/validations/deposit_payment_sequence_then_amount_then_success
        """
        world = fixtures.build_deposit_scheduled_contract()
        second = _installments_by_seq(world)[2]

        response = api_client.pay_deposit_installment(
            second["id"],
            factories.pay_installment_payload(
                42784.86, payment_reference="WIRE-2822-002"
            ),
            FINANCE_HEADERS,
        )

        validate_error(response, ApiErrorId.DEPOSIT_SEQUENCE_VIOLATION.value, 409)
        refused = validate_success(
            api_client.get_deposit_installment(second["id"], FINANCE_HEADERS)
        )
        domain_assert.assert_fields_equal(refused, {"status": "SCHEDULED"})
        domain_assert.assert_nulls(refused, ["paid_amount_usd"])

    def test_a_payment_one_cent_short_of_the_installment_is_refused(self):
        """Respecting the order is not enough: the amount must match to the cent.

        And `paid_amount_usd` must equal the installment's `amount_usd` to the cent, otherwise `ERR_DEPOSIT_AMOUNT_MISMATCH`; partial payments and overpayments are both refused, which is what keeps the deposit arithmetic exact.

        Design: Corner/validations/deposit_payment_sequence_then_amount_then_success
        """
        world = fixtures.build_deposit_scheduled_contract()
        first = _installments_by_seq(world)[1]
        domain_assert.assert_money_field(first, "amount_usd", 44081.37)

        response = api_client.pay_deposit_installment(
            first["id"],
            factories.pay_installment_payload(
                44081.36, payment_reference="WIRE-2822-001"
            ),
            FINANCE_HEADERS,
        )

        validate_error(response, ApiErrorId.DEPOSIT_AMOUNT_MISMATCH.value, 422)
        refused = validate_success(
            api_client.get_deposit_installment(first["id"], FINANCE_HEADERS)
        )
        domain_assert.assert_fields_equal(refused, {"status": "SCHEDULED"})

    def test_the_exact_payment_moves_the_installment_and_the_two_deposit_lines(self):
        """The accepted payment shifts the same amount from outstanding to paid.

        On success the installment moves `SCHEDULED → PAID`, `paid_amount_usd` and `payment_reference` are persisted, `paid_at` is stamped from the logical clock, the contract's `deposit_paid_usd` increases by the amount paid and its `deposit_outstanding_usd` decreases by the same amount.

        Design: Corner/validations/deposit_payment_sequence_then_amount_then_success
        """
        world = fixtures.build_deposit_scheduled_contract()
        first = _installments_by_seq(world)[1]

        paid = validate_success(
            api_client.pay_deposit_installment(
                first["id"],
                factories.pay_installment_payload(
                    44081.37, payment_reference="WIRE-2822-001"
                ),
                FINANCE_HEADERS,
            )
        )

        domain_assert.assert_fields_equal(
            paid,
            {
                "status": "PAID",
                "payment_reference": "WIRE-2822-001",
                "paid_at": CLOCK_SOURCING_WINDOW,
            },
        )
        domain_assert.assert_money_field(paid, "paid_amount_usd", 44081.37)
        contract = fixtures.read_contract(world["contract_id"])
        domain_assert.assert_money_field(contract, "deposit_paid_usd", 44081.37)
        domain_assert.assert_money_field(contract, "deposit_outstanding_usd", 85569.71)
        domain_assert.assert_money_field(contract, "deposit_total_usd", 129651.08)


# A second, wholly unrelated requirement: different name, programme type, dates,
# size and budget, so that only the sourcing code can be what collides.
_UNRELATED_REQUIREMENT = {
    "name": "Unrelated Training Week",
    "program_type": "TRAINING",
    "start_date": "2027-09-06",
    "end_date": "2027-09-09",
    "peak_attendees": 60,
    "requested_room_nights": 180,
    "largest_meeting_space_sqft": 3000,
    "budget_ceiling_usd": 90000.00,
}


class TestEventCodeUniqueness:
    """The sourcing code alone is the uniqueness key across meeting events."""

    def test_reusing_a_sourcing_code_is_refused_and_creates_nothing(self):
        """Everything else about the second requirement differs, and it is still a collision.

        The planner supplies `event_code`, a planner-assigned sourcing code between 3 and 32 characters that must be globally unique across meeting events — a collision is rejected with `ERR_EVENT_CODE_DUPLICATE`.

        Design: Corner/validations/duplicate_event_code_rejected_then_a_fresh_code_accepted
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        existing = fixtures.create_event(event_code="EVT-2822-A")

        response = api_client.create_event(
            factories.event_payload(event_code="EVT-2822-A", **_UNRELATED_REQUIREMENT),
            PLANNER_HEADERS,
        )

        validate_error(response, ApiErrorId.EVENT_CODE_DUPLICATE.value, 409)
        rows, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert len(rows) == 1, f"the refusal must not have created a row, got {len(rows)}"
        domain_assert.assert_integer(meta["total_count"], 1, "total_count")
        domain_assert.assert_fields_equal(
            fixtures.read_event(existing["id"]),
            {"name": "Global User Conference 2027"},
        )

    def test_the_same_requirement_under_a_fresh_code_is_accepted(self):
        """Only the code was in the way, so the identical body lands once it changes.

        From that pair the server computes `nights_span`, the number of whole days from `start_date` to `end_date`, which is the room-block night count the deposit and capacity arithmetic later divides by.

        Design: Corner/validations/duplicate_event_code_rejected_then_a_fresh_code_accepted
        """
        fixtures.set_clock(CLOCK_SOURCING_WINDOW)
        fixtures.create_event(event_code="EVT-2822-A")
        validate_error(
            api_client.create_event(
                factories.event_payload(
                    event_code="EVT-2822-A", **_UNRELATED_REQUIREMENT
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.EVENT_CODE_DUPLICATE.value,
            409,
        )

        created = validate_success(
            api_client.create_event(
                factories.event_payload(
                    event_code="EVT-2822-C", **_UNRELATED_REQUIREMENT
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        domain_assert.assert_fields_equal(
            created, {"event_code": "EVT-2822-C", "status": "DRAFT"}
        )
        domain_assert.assert_integer(created["nights_span"], 3, "nights_span")
        rows, meta = validate_paginated(api_client.list_events(PLANNER_HEADERS))
        assert len(rows) == 2, f"expected two meeting events on file, got {len(rows)}"
        domain_assert.assert_integer(meta["total_count"], 2, "total_count")


class TestResponseDeadlineWindow:
    """The drafted deadline must sit strictly inside the clock-to-arrival window."""

    def test_both_ends_of_the_window_are_refused(self):
        """A deadline on the clock and a deadline on the arrival instant are both outside.

        And `response_due_at` must lie strictly after the current logical clock and strictly before the event's `start_date` at `00:00:00.000Z`; a deadline at or before the clock, or at or after the arrival date, is rejected with `ERR_RESPONSE_DUE_OUT_OF_RANGE`.

        Design: Corner/validations/response_due_at_rejected_at_both_ends_of_the_open_interval
        """
        world = fixtures.build_sourcing_world()

        at_the_clock = api_client.create_rfp(
            world["event_id"],
            factories.rfp_payload(
                response_due_at=CLOCK_SOURCING_WINDOW,
                instructions="Deadline equal to now.",
            ),
            PLANNER_HEADERS,
        )
        at_the_arrival = api_client.create_rfp(
            world["event_id"],
            factories.rfp_payload(
                response_due_at="2027-03-15T00:00:00.000Z",
                instructions="Deadline equal to arrival.",
            ),
            PLANNER_HEADERS,
        )

        validate_error(at_the_clock, ApiErrorId.RESPONSE_DUE_OUT_OF_RANGE.value, 422)
        validate_error(at_the_arrival, ApiErrorId.RESPONSE_DUE_OUT_OF_RANGE.value, 422)
        rows, meta = validate_paginated(
            api_client.list_rfps(PLANNER_HEADERS, {"event_id": world["event_id"]})
        )
        assert rows == [], f"no round should have been drafted, got {len(rows)} rows"
        domain_assert.assert_integer(meta["total_count"], 0, "total_count")

    def test_an_interior_deadline_drafts_the_round(self):
        """A deadline strictly inside the window is accepted and the round lands in draft.

        A drafted round lands in `DRAFT` with `invited_count` at 0, `submitted_count` at 0, `issued_at` null and `closed_at` null.

        Design: Corner/validations/response_due_at_rejected_at_both_ends_of_the_open_interval
        """
        world = fixtures.build_sourcing_world()

        created = validate_success(
            api_client.create_rfp(
                world["event_id"],
                factories.rfp_payload(response_due_at="2026-09-30T17:00:00.000Z"),
                PLANNER_HEADERS,
            ),
            201,
        )

        domain_assert.assert_fields_equal(
            created,
            {
                "response_due_at": "2026-09-30T17:00:00.000Z",
                "status": "DRAFT",
                "round_number": 1,
            },
        )


class TestSubmissionDeadlineBoundary:
    """The response deadline is inclusive to the millisecond."""

    def test_a_bid_landing_exactly_on_the_deadline_is_on_time(self):
        """The clock standing on the deadline still admits the response.

        The current logical clock must be at or before the round's `response_due_at`; the deadline is **inclusive**, so a submission landing exactly on `response_due_at` is accepted and only a strictly later one is rejected with `ERR_RESPONSE_DEADLINE_PASSED`.

        Design: Corner/validations/submit_at_exactly_the_deadline_passes_one_millisecond_later_fails
        """
        world = fixtures.build_two_venue_round()
        fixtures.set_clock("2026-09-30T17:00:00.000Z")

        submitted = fixtures.submit_bid(world["proposal_id"], world["venue_id"])

        domain_assert.assert_fields_equal(
            submitted,
            {"status": "SUBMITTED", "submitted_at": "2026-09-30T17:00:00.000Z"},
        )
        domain_assert.assert_money_field(
            submitted, "total_cost_contracted_usd", 447844.84
        )

    def test_one_millisecond_later_the_response_is_late(self):
        """The late bid keeps its invited shell and never enters the round's counts.

        `submitted_count` is the number of this round's bids whose `status` is one of `SUBMITTED`, `UNDER_REVIEW`, `COUNTERED`, `REVISED` or `AWARDED`.

        Design: Corner/validations/submit_at_exactly_the_deadline_passes_one_millisecond_later_fails
        """
        world = fixtures.build_two_venue_round()
        fixtures.set_clock("2026-09-30T17:00:00.000Z")
        fixtures.submit_bid(world["proposal_id"], world["venue_id"])
        fixtures.set_clock("2026-09-30T17:00:00.001Z")

        response = api_client.submit_proposal(
            world["proposal_b_id"],
            factories.proposal_submission_payload(),
            make_venue_rep_headers(world["venue_b_id"]),
        )

        validate_error(response, ApiErrorId.RESPONSE_DEADLINE_PASSED.value, 422)
        late = fixtures.read_proposal(world["proposal_b_id"])
        domain_assert.assert_fields_equal(late, {"status": "INVITED"})
        domain_assert.assert_nulls(
            late, ["submitted_at", "total_cost_contracted_usd"]
        )
        rfp = fixtures.read_rfp(world["rfp_id"])
        domain_assert.assert_integer(rfp["submitted_count"], 1, "submitted_count")
        domain_assert.assert_integer(rfp["invited_count"], 2, "invited_count")
        domain_assert.assert_fields_equal(rfp, {"status": "ISSUED"})
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_money_field(event, "best_total_cost_usd", 447844.84)


def _build_preferred_program_only_event():
    """A programme-only event holding one in-programme and one out-of-programme candidate."""
    world = fixtures.build_sourcing_world(
        event_overrides={"preferred_program_only": True}, promote=False
    )
    outside = fixtures.create_venue(
        name=factories.next_venue_name("Novara Central"),
        guest_rooms_total=300,
        largest_space_sqft=13000,
        preferred_supplier_status="NONE",
    )
    entry_outside = fixtures.add_entry(world["event_id"], outside["id"], rank_seq=2)
    world.update(
        {
            "venue_outside": outside,
            "venue_outside_id": outside["id"],
            "entry_outside": entry_outside,
            "entry_outside_id": entry_outside["id"],
        }
    )
    return world


class TestPreferredProgramSnapshot:
    """The programme restriction reads the entry's snapshot, never the live venue."""

    def test_an_out_of_programme_candidate_cannot_be_committed(self):
        """The snapshot captured at entry creation is what the restriction tests.

        It requires the entry to be in `CANDIDATE`, and any other status is rejected with `ERR_SHORTLIST_ENTRY_STATE_INVALID`; it requires the parent event to be in `REQUIREMENTS_LOCKED`, `SOURCING` or `BID_REVIEW`; it re-checks that the venue's `preferred_supplier_status` is not `SUSPENDED`, rejecting with `ERR_VENUE_SUSPENDED` if it has been suspended since the entry was added; and when the event's `preferred_program_only` is `true` it requires the entry's `program_status_at_shortlist` to be `IN_PROGRAM`, rejecting with `ERR_PREFERRED_PROGRAM_REQUIRED` otherwise.

        Design: Corner/validations/preferred_program_only_event_reads_the_entry_snapshot_not_the_live_venue
        """
        world = _build_preferred_program_only_event()

        response = api_client.shortlist_entry(
            world["entry_outside_id"], PLANNER_HEADERS
        )

        validate_error(response, ApiErrorId.PREFERRED_PROGRAM_REQUIRED.value, 422)
        refused = fixtures.read_entry(world["entry_outside_id"])
        domain_assert.assert_fields_equal(
            refused,
            {"status": "CANDIDATE", "program_status_at_shortlist": "OUT_OF_PROGRAM"},
        )

    def test_promoting_the_venue_into_the_programme_does_not_rescue_the_entry(self):
        """The live standing changes, the frozen snapshot does not, and the refusal stands.

        Shortlist entries that already exist are **not** rewritten: each entry's `program_status_at_shortlist` snapshot keeps the value it captured at entry creation, so suspending a venue does not retroactively push its existing entries out of programme.

        Design: Corner/validations/preferred_program_only_event_reads_the_entry_snapshot_not_the_live_venue
        """
        world = _build_preferred_program_only_event()
        validate_error(
            api_client.shortlist_entry(world["entry_outside_id"], PLANNER_HEADERS),
            ApiErrorId.PREFERRED_PROGRAM_REQUIRED.value,
            422,
        )

        patched = validate_success(
            api_client.update_venue_preferred_status(
                world["venue_outside_id"],
                factories.preferred_status_payload("PREFERRED"),
                PROGRAM_ADMIN_HEADERS,
            )
        )

        domain_assert.assert_fields_equal(
            patched, {"preferred_supplier_status": "PREFERRED"}
        )
        validate_error(
            api_client.shortlist_entry(world["entry_outside_id"], PLANNER_HEADERS),
            ApiErrorId.PREFERRED_PROGRAM_REQUIRED.value,
            422,
        )
        domain_assert.assert_fields_equal(
            fixtures.read_entry(world["entry_outside_id"]),
            {"program_status_at_shortlist": "OUT_OF_PROGRAM"},
        )

    def test_the_in_programme_candidate_is_committed_normally(self):
        """The entry whose snapshot says in programme passes the same restriction.

        `program_status_at_shortlist` is set to `IN_PROGRAM` when the venue's `preferred_supplier_status` at that moment is `PREFERRED` or `CONDITIONAL`, and to `OUT_OF_PROGRAM` when it is anything else.

        Design: Corner/validations/preferred_program_only_event_reads_the_entry_snapshot_not_the_live_venue
        """
        world = _build_preferred_program_only_event()

        promoted = fixtures.promote_entry(world["entry_id"])

        domain_assert.assert_fields_equal(
            promoted,
            {"status": "SHORTLISTED", "program_status_at_shortlist": "IN_PROGRAM"},
        )
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_integer(
            event["shortlisted_venue_count"], 1, "shortlisted_venue_count"
        )


class TestAwardRequiresAContractedBasisEvaluation:
    """An actualized pricing pass clears the review gate but not the award gate."""

    def test_an_actualized_only_evaluation_does_not_satisfy_the_award(self):
        """The bid is under review, yet the award is still refused for want of the right basis.

        The winning bid must have at least one bid evaluation whose `basis` is `CONTRACTED_BASIS`, otherwise `ERR_BID_EVALUATION_REQUIRED` — the planner must have priced the bid on the contracted basis before committing to it, and an actualized-basis evaluation alone does not satisfy this.

        Design: Corner/validations/award_needs_a_contracted_basis_evaluation_not_merely_any_evaluation
        """
        world = fixtures.build_evaluated_bid(
            basis="ACTUALIZED_BASIS", close_round=True
        )

        response = api_client.award_event(
            world["event_id"],
            factories.award_payload(
                world["proposal_id"],
                fixtures.event_version(world["event_id"]),
                award_note="Attempted award.",
            ),
            PLANNER_HEADERS,
        )

        validate_error(response, ApiErrorId.BID_EVALUATION_REQUIRED.value, 422)
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_fields_equal(event, {"status": "BID_REVIEW"})
        domain_assert.assert_nulls(event, ["awarded_proposal_id"])
        domain_assert.assert_money_field(event, "committed_spend_usd", 0.00)

    def test_recording_the_contracted_basis_evaluation_unlocks_the_award(self):
        """A second evaluation on the contracted basis is added and the same award lands.

        The bid's `total_cost_contracted_usd` is **not** touched by evaluation; it changes only on submission and revision.

        Design: Corner/validations/award_needs_a_contracted_basis_evaluation_not_merely_any_evaluation
        """
        world = fixtures.build_evaluated_bid(
            basis="ACTUALIZED_BASIS", close_round=True
        )
        validate_error(
            api_client.award_event(
                world["event_id"],
                factories.award_payload(
                    world["proposal_id"],
                    fixtures.event_version(world["event_id"]),
                    award_note="Attempted award.",
                ),
                PLANNER_HEADERS,
            ),
            ApiErrorId.BID_EVALUATION_REQUIRED.value,
            422,
        )

        evaluation = fixtures.evaluate_bid(world["proposal_id"], "CONTRACTED_BASIS")

        domain_assert.assert_money_field(evaluation, "total_cost_usd", 447844.84)
        bid = fixtures.read_proposal(world["proposal_id"])
        domain_assert.assert_fields_equal(
            bid, {"last_evaluation_basis": "CONTRACTED_BASIS"}
        )
        domain_assert.assert_money_field(bid, "total_cost_contracted_usd", 447844.84)
        rows, _ = validate_paginated(
            api_client.list_bid_evaluations(world["proposal_id"], PLANNER_HEADERS)
        )
        assert len(rows) == 2, f"expected both pricing passes to be kept, got {len(rows)}"
        contract = fixtures.award_bid(world["event_id"], world["proposal_id"])
        domain_assert.assert_money_field(contract, "contracted_total_usd", 432170.27)
        event = fixtures.read_event(world["event_id"])
        domain_assert.assert_fields_equal(
            event,
            {"status": "AWARDED", "awarded_proposal_id": world["proposal_id"]},
        )
