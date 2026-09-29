"""Machine corners: births, cycle edges, latches and refused shortcuts.

Every machine in this API is guarded in three separate places — its declared
edge set, its terminal set and the resource-state band of the rejection ladder —
and the cases here attack each of the three on its own so that a refusal can
only have come from the one under test.
"""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    AssignmentStatus,
    CaseSeverity,
    CaseStatus,
    DuesStatus,
    GuestSettlementPolicy,
    GuestVisitStatus,
    HouseholdStanding,
    JobCode,
    MeetStatus,
    PriorityTier,
    RegistrationStatus,
    ReservationStatus,
    SanctionType,
    Squad,
    WaitlistStatus,
    Zone,
    assertions as a,
    canonical_instant,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    transition_payload,
    void_visit_payload,
    volunteer_assignment_payload,
    waitlist_respond_payload,
)
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    POOL_MANAGER,
    SWIM_TEAM_COACH,
    make_member_headers,
)


def _two_meets_in_one_open_season(api):
    """An OPEN 2027 season holding a four-credit meet and a zero-credit meet.

    The zero-credit meet is the interesting one: its requirement is already
    satisfied by the empty assignment set, so if creation forked the machine at
    all it would fork here.
    """
    season = fx.setup_open_season(api, clock_iso="2027-06-01T09:00:00Z")
    demanding = fx.create_meet(
        api, season["id"], name="June Dual Meet",
        start_iso="2027-06-12T08:00:00Z", end_iso="2027-06-12T13:00:00Z",
        expected_swimmers=40, volunteer_slots_required=4,
    )
    satisfied = fx.create_meet(
        api, season["id"], name="Time Trial",
        start_iso="2027-06-19T08:00:00Z", end_iso="2027-06-19T11:00:00Z",
        expected_swimmers=20, volunteer_slots_required=0,
    )
    return {"season": season, "demanding": demanding, "satisfied": satisfied}


class TestNewMeetIsBornUnforked:
    """Creation never chooses a branch, whatever the requirement asks for."""

    def test_both_meets_are_born_scheduled_with_an_empty_roster(self, api):
        """Four credits required and none required agree on the birth state.

        PRD §3.6: "A new meet is `SCHEDULED`, with `volunteer_slots_filled` at 0,
        `roster_closed_at` null and `understaffed_penalty_cents` at 0."

        Design: Corner/state_machines/initial_state_new_meet_is_scheduled_with_an_empty_roster
        """
        ctx = _two_meets_in_one_open_season(api)

        for meet in (ctx["demanding"], ctx["satisfied"]):
            a.assert_meet(meet, MeetStatus.SCHEDULED)
            assert meet["volunteer_slots_filled"] == 0
            assert meet["roster_closed_at"] is None
            assert meet["understaffed_penalty_cents"] == 0
        assert ctx["demanding"]["volunteer_slots_required"] == 4
        assert ctx["satisfied"]["volunteer_slots_required"] == 0

    def test_a_re_read_has_not_lazily_advanced_either_machine(self, api):
        """The fork belongs to close-roster, so a read may not perform it.

        PRD §3.6: "Closing the roster is the fork in the meet's life, and both
        branches are reachable from `SCHEDULED` only."

        Design: Corner/state_machines/initial_state_new_meet_is_scheduled_with_an_empty_roster
        """
        ctx = _two_meets_in_one_open_season(api)

        for key in ("demanding", "satisfied"):
            reread = validate_success(
                api.get_meet(ctx[key]["id"], BOARD_PRESIDENT), 200
            )
            assert reread["status"] == MeetStatus.SCHEDULED
            assert reread["roster_closed_at"] is None
            assert reread["volunteer_slots_filled"] == 0
            assert reread["version"] == ctx[key]["version"]


PARTY_WINDOW = ("2027-07-20T14:00:00Z", "2027-07-20T18:00:00Z")


def _a_paid_household_holding_one_requested_party(api):
    """A settled COUPLE household with a 16200-cent PAVILION booking.

    The membership is deliberately paid in full: the account-credit auto-apply
    rule of PRD §3.4 only reaches a membership whose ``dues_status`` is
    ``INVOICED`` or ``DELINQUENT``, so a `PAID` membership leaves the refund
    parked where the test can see it.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-05-22T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Rejection Test Household",
            "address_line": "51 Cedar Court",
            "prior_member": False,
        },
        join_date="2027-05-22",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    ctx["membership"] = fx.pay_membership_in_full(api, ctx["membership"]["id"])
    start_iso, end_iso = PARTY_WINDOW
    ctx["reservation"] = fx.request_party(
        api, ctx["membership"]["id"], zone=Zone.PAVILION,
        start_iso=start_iso, end_iso=end_iso, guest_count=12, host_party_size=8,
    )
    ctx["household"] = fx.read_household(api, ctx["household"]["id"])
    return ctx


class TestPartyRejectionIsAFullReversal:
    """REQUESTED to REJECTED moves money sideways, never downwards."""

    def test_the_booking_charges_the_household_before_any_decision(self, api):
        """State zero: 16200 owed, no credit, and the dues already settled.

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents` at
        0, and its `total_charge_cents` is booked onto the household
        immediately: `party_charges_owed_cents` rises by that amount and the
        household's `version` advances."

        Design: Corner/state_machines/valid_transition_party_rejection_refunds_the_charge_in_full
        """
        ctx = _a_paid_household_holding_one_requested_party(api)

        reservation = ctx["reservation"]
        assert reservation["status"] == ReservationStatus.REQUESTED
        assert reservation["projected_bather_load"] == 20
        assert reservation["total_charge_cents"] == 16200
        assert reservation["refunded_cents"] == 0

        assert ctx["membership"]["invoice_total_cents"] == 31050
        assert ctx["membership"]["dues_status"] == DuesStatus.PAID
        assert ctx["membership"]["balance_due_cents"] == 0
        assert ctx["household"]["party_charges_owed_cents"] == 16200
        assert ctx["household"]["account_credit_cents"] == 0

    def test_the_rejection_records_the_reversal_without_rewriting_the_charge(
        self, api
    ):
        """The charge stands at 16200 and the refund stands beside it.

        PRD §3.7: "Rejecting — `REQUESTED → REJECTED` — refunds in full:
        `refunded_cents` is set to the reservation's `total_charge_cents`, the
        household's `party_charges_owed_cents` falls by that amount, and both the
        reservation's and the household's `version` advance."

        Design: Corner/state_machines/valid_transition_party_rejection_refunds_the_charge_in_full
        """
        ctx = _a_paid_household_holding_one_requested_party(api)

        rejected = fx.transition_party(
            api, ctx["reservation"]["id"], ReservationStatus.REJECTED
        )

        assert rejected["status"] == ReservationStatus.REJECTED
        assert rejected["total_charge_cents"] == 16200
        assert rejected["refunded_cents"] == 16200
        assert rejected["version"] > ctx["reservation"]["version"]

    def test_the_money_lands_on_the_household_account_rather_than_vanishing(
        self, api
    ):
        """Owed falls to zero and credit rises by the identical amount.

        PRD §3.7: "Every one of those refunds moves the same pair of household
        counters — `party_charges_owed_cents` falls by `refunded_cents` and
        `account_credit_cents` rises by the same amount — and advances both the
        reservation's `version` and the household's `version`."

        PRD §3.4: "Whenever a party refund raises a household's
        `account_credit_cents`, an auto-apply rule runs immediately: if the
        household holds a membership in that reservation's season whose
        `dues_status` is `INVOICED` or `DELINQUENT`, and `account_credit_cents`
        is greater than or equal to that membership's `balance_due_cents`, then
        the whole balance is settled from the credit"

        Design: Corner/state_machines/valid_transition_party_rejection_refunds_the_charge_in_full
        """
        ctx = _a_paid_household_holding_one_requested_party(api)
        fx.transition_party(
            api, ctx["reservation"]["id"], ReservationStatus.REJECTED
        )

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["party_charges_owed_cents"] == 0
        assert household["account_credit_cents"] == 16200
        assert household["version"] > ctx["household"]["version"]

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["dues_status"] == DuesStatus.PAID
        assert membership["balance_due_cents"] == 0
        assert membership["amount_paid_cents"] == 31050


def _a_scheduled_meet_and_a_pending_registration(api):
    """Two machines parked one hop short of the shortcut each invites.

    The clock is pushed past the meet's ``end_iso`` on purpose, so the hosting
    precondition on the clock cannot be what refuses the move.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-06-01T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Edge Test Household",
            "address_line": "61 Cedar Court",
            "prior_member": False,
        },
        join_date="2027-06-01",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    ctx["registration"] = fx.register_swimmer(
        api, ctx["membership"]["id"], ctx["season"]["id"],
        swimmer_name="Ines Vega", swimmer_birthdate="2014-06-01",
        squad=Squad.JUNIOR,
    )
    ctx["meet"] = fx.create_meet(
        api, ctx["season"]["id"], name="June Dual Meet",
        start_iso="2027-06-12T08:00:00Z", end_iso="2027-06-12T13:00:00Z",
        expected_swimmers=40, volunteer_slots_required=0,
    )
    assert ctx["meet"]["status"] == MeetStatus.SCHEDULED
    assert ctx["registration"]["status"] == RegistrationStatus.PENDING
    fx.set_clock(api, "2027-06-12T14:00:00Z")
    return ctx


class TestUndeclaredEdgesAreRefusedOnTwoMachines:
    """A legal enum token addressed at an edge that does not exist."""

    def test_a_meet_may_not_be_hosted_straight_out_of_scheduled(self, api):
        """Hosting is reachable from the fork's two branches and nowhere else.

        PRD §3.6: "Both fork branches join at `HOSTED`, and hosting is available
        only once the logical clock has reached or passed the meet's `end_iso`
        and only while the season's `facility_posture` is `OPEN`."

        PRD §2.9: "the requested `to_status` is a declared outgoing edge from the
        resource's current status (`ERR_INVALID_TRANSITION`, 409)"

        Design: Corner/state_machines/invalid_transitions_undeclared_edges_are_refused_on_two_machines
        """
        ctx = _a_scheduled_meet_and_a_pending_registration(api)

        body = validate_error(
            api.transition_meet(
                ctx["meet"]["id"], transition_payload(MeetStatus.HOSTED),
                SWIM_TEAM_COACH,
            ),
            ApiErrorId.INVALID_TRANSITION, 409,
        )
        assert body["error_id"] != ApiErrorId.INVALID_ENUM

        reread = fx.read_meet(api, ctx["meet"]["id"])
        assert reread["status"] == MeetStatus.SCHEDULED
        assert reread["version"] == ctx["meet"]["version"]

    def test_a_registration_may_not_complete_without_being_confirmed(self, api):
        """The only edge into COMPLETED is the season-close cascade's.

        PRD §3.6: "`COMPLETED` is reached only at season close."

        PRD §2.9: "the requested `to_status` is a declared outgoing edge from the
        resource's current status (`ERR_INVALID_TRANSITION`, 409)"

        Design: Corner/state_machines/invalid_transitions_undeclared_edges_are_refused_on_two_machines
        """
        ctx = _a_scheduled_meet_and_a_pending_registration(api)

        body = validate_error(
            api.transition_registration(
                ctx["registration"]["id"],
                transition_payload(RegistrationStatus.COMPLETED),
                SWIM_TEAM_COACH,
            ),
            ApiErrorId.INVALID_TRANSITION, 409,
        )
        assert body["error_id"] != ApiErrorId.INVALID_ENUM

        reread = fx.read_registration(api, ctx["registration"]["id"])
        assert reread["status"] == RegistrationStatus.PENDING
        assert reread["version"] == ctx["registration"]["version"]


VOID_REASON = "Guest never entered the facility; scan reversed at the gate."
SECOND_VOID_REASON = "Duplicate reversal attempt from a retried request."


def _one_recorded_visit_against_a_two_pass_household(api):
    """A COUPLE household holding two passes, one of them just spent.

    The clock sits an hour after the visit instant, so the visit is never
    recorded in the future and ``voided_at`` has a value distinct from the
    visit's own window.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-20T12:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Double Void Household",
            "address_line": "71 Cedar Court",
            "prior_member": False,
        },
        join_date="2027-06-01",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    ctx["household"] = fx.read_household(api, ctx["household"]["id"])
    ctx["visit"] = fx.record_visit(
        api, ctx["membership"]["id"], ctx["household"]["id"],
        guest_count=1, visit_start_iso="2027-07-20T11:00:00Z",
        sponsor_name="Nell Barrow",
    )
    return ctx


class TestAVoidedVisitRefusesASecondVoid:
    """One terminal state, one edge into it, and no second helping of passes."""

    def test_the_weekday_guest_costs_exactly_one_pass_and_no_money(self, api):
        """State zero for the ledger: two granted, one spent, nothing billed.

        PRD §3.5: "Under the `PASS_FIRST` variant, `passes_used` is the smaller of
        the household's current `guest_pass_balance` and the visit's
        `guest_count`, on every day of the week alike."

        Design: Corner/state_machines/terminal_state_lockdown_a_voided_guest_visit_refuses_a_second_void
        """
        ctx = _one_recorded_visit_against_a_two_pass_household(api)

        a.assert_guest_visit(ctx["visit"], GuestVisitStatus.RECORDED)
        a.assert_visit_settlement(
            ctx["visit"], passes_used=1, fee_charged_cents=0, is_weekend=False,
            settlement_variant=GuestSettlementPolicy.PASS_FIRST,
        )
        a.assert_household_pass_ledger(
            fx.read_household(api, ctx["household"]["id"]),
            granted=2, consumed=1, balance=1, fee_owed_cents=0,
        )

    def test_the_first_void_returns_the_pass_and_stamps_the_clock(self, api):
        """The single legal edge into the terminal state, taken once.

        PRD §3.5: "Voiding moves the visit `RECORDED → VOIDED`, stamps
        `voided_at` with the logical clock, and reverses the ledger exactly:
        because a `VOIDED` visit no longer sits inside the `RECORDED` filter,
        `guest_passes_consumed` falls by that visit's `passes_used` and
        `guest_pass_balance` rises by the same number, while
        `guest_fee_owed_cents` falls by that visit's `fee_charged_cents`."

        Design: Corner/state_machines/terminal_state_lockdown_a_voided_guest_visit_refuses_a_second_void
        """
        ctx = _one_recorded_visit_against_a_two_pass_household(api)

        voided = fx.void_visit(api, ctx["visit"]["id"], reason=VOID_REASON)

        assert voided["status"] == GuestVisitStatus.VOIDED
        assert canonical_instant(voided["voided_at"]) == "2027-07-20T12:00:00Z"
        a.assert_household_pass_ledger(
            fx.read_household(api, ctx["household"]["id"]),
            granted=2, consumed=0, balance=2, fee_owed_cents=0,
        )

    def test_the_second_void_is_refused_and_compensates_nothing(self, api):
        """A silent no-op would push the balance to three of two passes.

        PRD §3.5: "`VOIDED` is terminal; a voided visit cannot be un-voided, and
        settling the fee is not a reversal — cash owed at the gate is retired
        only by a household payment allocated to `GUEST_FEES`, as §3.2
        describes."

        PRD §2.9: "the resource is not already in a terminal state
        (`ERR_ALREADY_TERMINAL`, 409)"

        Design: Corner/state_machines/terminal_state_lockdown_a_voided_guest_visit_refuses_a_second_void
        """
        ctx = _one_recorded_visit_against_a_two_pass_household(api)
        fx.void_visit(api, ctx["visit"]["id"], reason=VOID_REASON)

        body = validate_error(
            api.void_guest_visit(
                ctx["visit"]["id"], void_visit_payload(SECOND_VOID_REASON),
                POOL_MANAGER,
            ),
            ApiErrorId.ALREADY_TERMINAL, 409,
        )
        assert body["error_id"] != ApiErrorId.INVALID_TRANSITION

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["guest_pass_balance"] == 2
        assert household["guest_passes_consumed"] == 0
        assert household["guest_pass_allotment_granted"] == 2
        visit = fx.read_visit(api, ctx["visit"]["id"])
        assert visit["status"] == GuestVisitStatus.VOIDED
        assert canonical_instant(visit["voided_at"]) == "2027-07-20T12:00:00Z"


def _a_meet_requiring_two_credits_with_nobody_signed_up(api):
    """A two-credit meet, an empty roster, and one registration standing by.

    The registration exists only so that the late-assignment attempt after the
    latch closes is a well-formed request rather than a 404.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-06-01T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Roster Latch Household",
            "address_line": "81 Cedar Court",
            "prior_member": False,
        },
        join_date="2027-06-01",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    ctx["registration"] = fx.register_swimmer(
        api, ctx["membership"]["id"], ctx["season"]["id"],
        swimmer_name="Omar Silva", swimmer_birthdate="2014-03-03",
        squad=Squad.JUNIOR,
    )
    ctx["meet"] = fx.create_meet(
        api, ctx["season"]["id"], name="June Dual Meet",
        start_iso="2027-06-12T08:00:00Z", end_iso="2027-06-12T13:00:00Z",
        expected_swimmers=40, volunteer_slots_required=2,
    )
    return ctx


def _attempt_late_assignment(api, ctx):
    payload = volunteer_assignment_payload(
        meet_id=ctx["meet"]["id"],
        swim_team_registration_id=ctx["registration"]["id"],
        job_code=JobCode.SCORER,
    )
    return api.create_volunteer_assignment(payload, SWIM_TEAM_COACH)


class TestClosingTheRosterIsAOneShotCheckpoint:
    """The latch is not a retryable computation, and it guards two endpoints."""

    def test_the_first_close_forks_the_meet_and_prices_the_shortfall(self, api):
        """Two credits short of two required costs fifteen thousand cents.

        PRD §3.6: "When `volunteer_slots_filled` is strictly below
        `volunteer_slots_required` the meet becomes `UNDERSTAFFED`;
        `roster_closed_at` is stamped identically, and
        `understaffed_penalty_cents` is set to the credit shortfall — the
        requirement less the filled count — multiplied by seven thousand five
        hundred cents per missing credit."

        Design: Corner/state_machines/idempotency_close_roster_is_a_one_shot_checkpoint
        """
        ctx = _a_meet_requiring_two_credits_with_nobody_signed_up(api)

        closed = fx.close_roster(api, ctx["meet"]["id"])

        a.assert_meet(closed, MeetStatus.UNDERSTAFFED)
        assert closed["volunteer_slots_filled"] == 0
        assert closed["understaffed_penalty_cents"] == 15000
        assert canonical_instant(closed["roster_closed_at"]) == \
            "2027-06-01T09:00:00Z"

    def test_the_retry_and_the_late_volunteer_share_one_refusal(self, api):
        """Two different endpoints, one latch, one error code.

        PRD §3.6: "The meet's roster must still be open, meaning its
        `roster_closed_at` is null; a closed roster accepts no further assignment
        and yields `ERR_ROSTER_ALREADY_CLOSED`."

        PRD §2.9: "the meet's roster is still open
        (`ERR_ROSTER_ALREADY_CLOSED`, 409)"

        Design: Corner/state_machines/idempotency_close_roster_is_a_one_shot_checkpoint
        """
        ctx = _a_meet_requiring_two_credits_with_nobody_signed_up(api)
        fx.close_roster(api, ctx["meet"]["id"])

        validate_error(
            api.close_meet_roster(ctx["meet"]["id"], SWIM_TEAM_COACH),
            ApiErrorId.ROSTER_ALREADY_CLOSED, 409,
        )
        body = validate_error(
            _attempt_late_assignment(api, ctx),
            ApiErrorId.ROSTER_ALREADY_CLOSED, 409,
        )
        assert body["error_id"] != ApiErrorId.VOLUNTEER_SLOTS_FULL

    def test_neither_refusal_recomputed_the_latch_or_the_penalty(self, api):
        """A recompute would have priced a roster that had since changed.

        PRD §3.6: "Either way the meet's `version` advances, and no further
        assignment may be created for it."

        Design: Corner/state_machines/idempotency_close_roster_is_a_one_shot_checkpoint
        """
        ctx = _a_meet_requiring_two_credits_with_nobody_signed_up(api)
        closed = fx.close_roster(api, ctx["meet"]["id"])
        api.close_meet_roster(ctx["meet"]["id"], SWIM_TEAM_COACH)
        _attempt_late_assignment(api, ctx)

        reread = fx.read_meet(api, ctx["meet"]["id"])
        assert reread["roster_closed_at"] == closed["roster_closed_at"]
        assert reread["understaffed_penalty_cents"] == 15000
        assert reread["volunteer_slots_filled"] == 0
        assert reread["version"] == closed["version"]
        assert closed["version"] > ctx["meet"]["version"]


OFFER_MADE_AT = "2027-06-01T09:00:00Z"
OFFER_EXPIRES_AT = "2027-06-15T09:00:00Z"
ONE_SECOND_LATE = "2027-06-15T09:00:01Z"


def _a_live_offer_on_a_gated_category(api):
    """One household holding the only offer a waitlist-gated category has made.

    No billing checkpoint is ever run in this scenario, which is what leaves the
    status column free to go stale.
    """
    fx.set_clock(api, OFFER_MADE_AT)
    category = fx.create_family_category(api, waitlist_required=True)
    household = fx.create_household(
        api, primary_contact_name="Expiry Test Household",
        address_line="91 Cedar Court", member_count=4, prior_member=False,
    )
    entry = fx.join_waitlist(api, household["id"], category["id"],
                             priority_tier=PriorityTier.STANDARD)
    offered = fx.extend_next_offer(api, category["id"])
    return {
        "category": category,
        "household": household,
        "entry": entry,
        "offered": offered,
    }


def _attempt_response(api, ctx, decision, requeue=Ellipsis):
    return api.respond_waitlist_entry(
        ctx["entry"]["id"],
        waitlist_respond_payload(decision=decision, requeue=requeue),
        make_member_headers(ctx["household"]["id"]),
    )


class TestOfferExpiryIsMeasuredByTheClock:
    """The window is enforced against the clock, not against the status column."""

    def test_the_offer_window_is_fourteen_days_wide(self, api):
        """The entry offered is the one that joined, and its window is stamped.

        PRD §3.2: "The winning entry moves `WAITING → OFFERED`, `offered_at` is
        stamped with the logical clock, and `offer_expires_at` is set to fourteen
        days after that instant."

        Design: Corner/state_machines/precondition_enforcement_offer_expiry_is_measured_by_the_clock_not_by_status
        """
        ctx = _a_live_offer_on_a_gated_category(api)

        offered = ctx["offered"]
        assert offered["id"] == ctx["entry"]["id"]
        a.assert_waitlist_entry(offered, WaitlistStatus.OFFERED)
        assert canonical_instant(offered["offered_at"]) == OFFER_MADE_AT
        assert canonical_instant(offered["offer_expires_at"]) == OFFER_EXPIRES_AT

    def test_a_response_at_exactly_the_expiry_instant_is_still_accepted(
        self, api
    ):
        """The comparison is inclusive, so the boundary instant belongs to the
        household.

        PRD §3.2: "The offer remains acceptable for as long as the logical clock
        is at or before `offer_expires_at` — the boundary instant itself is still
        live."

        Design: Corner/state_machines/precondition_enforcement_offer_expiry_is_measured_by_the_clock_not_by_status
        """
        ctx = _a_live_offer_on_a_gated_category(api)
        fx.set_clock(api, OFFER_EXPIRES_AT)

        assert fx.read_waitlist_entry(
            api, ctx["entry"]["id"]
        )["status"] == WaitlistStatus.OFFERED

        accepted = fx.respond_to_offer(
            api, ctx["entry"]["id"], ctx["household"]["id"], "ACCEPT"
        )
        assert accepted["status"] == WaitlistStatus.ACCEPTED

    def test_one_second_later_both_responses_are_refused(self, api):
        """Accepting and requeue-declining hit the same gate.

        PRD §3.2: "Accepting moves `OFFERED → ACCEPTED` and is the entry a
        membership creation later consumes; an acceptance attempted after the
        offer window has passed is rejected with `ERR_OFFER_EXPIRED`."

        PRD §2.9: "the waitlist offer is live (`ERR_OFFER_EXPIRED`, 409); the
        deferral budget is not exhausted (`ERR_MAX_DEFERRALS_REACHED`, 409)"

        Design: Corner/state_machines/precondition_enforcement_offer_expiry_is_measured_by_the_clock_not_by_status
        """
        ctx = _a_live_offer_on_a_gated_category(api)
        fx.set_clock(api, ONE_SECOND_LATE)

        validate_error(
            _attempt_response(api, ctx, "ACCEPT"),
            ApiErrorId.OFFER_EXPIRED, 409,
        )
        body = validate_error(
            _attempt_response(api, ctx, "DECLINE", requeue=True),
            ApiErrorId.OFFER_EXPIRED, 409,
        )
        assert body["error_id"] != ApiErrorId.MAX_DEFERRALS_REACHED

    def test_the_status_column_stays_stale_because_no_checkpoint_ran(self, api):
        """Nothing ages an offer by itself, so OFFERED survives its own window.

        PRD §3.1: "Step two expires stale waitlist offers: every entry in
        `OFFERED` whose `offer_expires_at` is earlier than the logical clock moves
        to `EXPIRED`."

        Design: Corner/state_machines/precondition_enforcement_offer_expiry_is_measured_by_the_clock_not_by_status
        """
        ctx = _a_live_offer_on_a_gated_category(api)
        fx.set_clock(api, ONE_SECOND_LATE)
        _attempt_response(api, ctx, "ACCEPT")
        _attempt_response(api, ctx, "DECLINE", requeue=True)

        entry = fx.read_waitlist_entry(api, ctx["entry"]["id"])
        assert entry["status"] == WaitlistStatus.OFFERED
        assert entry["deferral_count"] == 0
        assert entry["version"] == ctx["offered"]["version"]


QUEUE_KEY_A = "2027-06-01T09:00:00Z"
QUEUE_KEY_B = "2027-06-01T10:00:00Z"
FIRST_REQUEUE_AT = "2027-06-01T11:00:00Z"
SECOND_REQUEUE_AT = "2027-06-01T12:00:00Z"
FOURTH_OFFER_AT = "2027-06-01T13:00:00Z"


def _two_standard_entries_an_hour_apart(api):
    """Household A ahead of household B in the same tier, by one hour.

    Both entries are `STANDARD`, so `priority_tier_rank` cannot separate them and
    `queue_key_at` is the only key that decides who is served.
    """
    fx.set_clock(api, QUEUE_KEY_A)
    category = fx.create_family_category(api, waitlist_required=True)
    house_a = fx.create_household(
        api, primary_contact_name="Household A",
        address_line="101 Cedar Court", member_count=4, prior_member=False,
    )
    entry_a = fx.join_waitlist(api, house_a["id"], category["id"],
                               priority_tier=PriorityTier.STANDARD)
    fx.set_clock(api, QUEUE_KEY_B)
    house_b = fx.create_household(
        api, primary_contact_name="Household B",
        address_line="102 Cedar Court", member_count=4, prior_member=False,
    )
    entry_b = fx.join_waitlist(api, house_b["id"], category["id"],
                               priority_tier=PriorityTier.STANDARD)
    fx.set_clock(api, FIRST_REQUEUE_AT)
    return {
        "category": category,
        "house_a": house_a,
        "house_b": house_b,
        "entry_a": entry_a,
        "entry_b": entry_b,
    }


def _requeue_a(api, ctx):
    return fx.respond_to_offer(
        api, ctx["entry_a"]["id"], ctx["house_a"]["id"], "DECLINE", requeue=True
    )


def _attempt_requeue_a(api, ctx):
    return api.respond_waitlist_entry(
        ctx["entry_a"]["id"],
        waitlist_respond_payload(decision="DECLINE", requeue=True),
        make_member_headers(ctx["house_a"]["id"]),
    )


def _cycle_until_the_budget_is_spent(api, ctx):
    """Requeue A, let B decline terminally, then requeue A a second time."""
    fx.extend_next_offer(api, ctx["category"]["id"])
    first = _requeue_a(api, ctx)
    fx.extend_next_offer(api, ctx["category"]["id"])
    fx.respond_to_offer(api, ctx["entry_b"]["id"], ctx["house_b"]["id"],
                        "DECLINE")
    fx.set_clock(api, SECOND_REQUEUE_AT)
    fx.extend_next_offer(api, ctx["category"]["id"])
    second = _requeue_a(api, ctx)
    return first, second


class TestRequeueingDeclinesCycleUntilTheCapBites:
    """The cyclic edge costs a place each time and is bounded by a counter."""

    def test_the_first_requeue_returns_the_entry_to_waiting_and_loses_its_place(
        self, api
    ):
        """Every field of the cycle edge moves at once, and the key moves last.

        PRD §3.2: "Declining with `requeue` true is the queue's cycle edge: the
        entry returns `OFFERED → WAITING`, `deferral_count` rises by one,
        `requeued_at` is stamped with the logical clock — which makes the entry's
        `queue_key_at` later than every un-requeued sibling in the same tier, so
        the household keeps its tier but loses its place to later arrivals — and
        both `offered_at` and `offer_expires_at` are cleared to null."

        Design: Corner/state_machines/valid_transition_requeued_declines_cycle_until_the_deferral_cap_bites
        """
        ctx = _two_standard_entries_an_hour_apart(api)
        assert canonical_instant(ctx["entry_a"]["queue_key_at"]) == QUEUE_KEY_A
        assert canonical_instant(ctx["entry_b"]["queue_key_at"]) == QUEUE_KEY_B

        offer_one = fx.extend_next_offer(api, ctx["category"]["id"])
        assert offer_one["id"] == ctx["entry_a"]["id"]

        requeued = _requeue_a(api, ctx)

        a.assert_waitlist_entry(requeued, WaitlistStatus.WAITING)
        assert requeued["deferral_count"] == 1
        assert canonical_instant(requeued["requeued_at"]) == FIRST_REQUEUE_AT
        assert canonical_instant(requeued["queue_key_at"]) == FIRST_REQUEUE_AT
        assert requeued["offered_at"] is None
        assert requeued["offer_expires_at"] is None
        assert canonical_instant(requeued["queue_key_at"]) > QUEUE_KEY_B

    def test_the_later_arrival_then_outranks_the_requeued_entry(self, api):
        """B joined an hour behind A and is served ahead of it anyway.

        PRD §3.2: "Otherwise the winner is the candidate with the lowest
        `priority_tier_rank`; ties are broken by the earliest `queue_key_at`;
        remaining ties are broken by the earliest `created_at`, which is the final
        tie-break and is never the row's `id`."

        PRD §3.2: "Declining with `requeue` false or omitted moves
        `OFFERED → DECLINED` and leaves the queue for good."

        Design: Corner/state_machines/valid_transition_requeued_declines_cycle_until_the_deferral_cap_bites
        """
        ctx = _two_standard_entries_an_hour_apart(api)
        fx.extend_next_offer(api, ctx["category"]["id"])
        _requeue_a(api, ctx)

        offer_two = fx.extend_next_offer(api, ctx["category"]["id"])
        assert offer_two["id"] == ctx["entry_b"]["id"]

        declined = fx.respond_to_offer(
            api, ctx["entry_b"]["id"], ctx["house_b"]["id"], "DECLINE"
        )
        assert declined["status"] == WaitlistStatus.DECLINED
        assert declined["deferral_count"] == 0

    def test_the_second_requeue_spends_the_budget_without_ending_the_queue(
        self, api
    ):
        """Two loops are legal, and the entry is still offerable a third time.

        PRD §3.2: "A household may defer at most twice: a requeueing decline sent
        when `deferral_count` has already reached 2 is rejected with
        `ERR_MAX_DEFERRALS_REACHED`."

        Design: Corner/state_machines/valid_transition_requeued_declines_cycle_until_the_deferral_cap_bites
        """
        ctx = _two_standard_entries_an_hour_apart(api)

        first, second = _cycle_until_the_budget_is_spent(api, ctx)

        assert first["deferral_count"] == 1
        assert second["status"] == WaitlistStatus.WAITING
        assert second["deferral_count"] == 2
        assert canonical_instant(second["queue_key_at"]) == SECOND_REQUEUE_AT

        fx.set_clock(api, FOURTH_OFFER_AT)
        offer_four = fx.extend_next_offer(api, ctx["category"]["id"])
        assert offer_four["id"] == ctx["entry_a"]["id"]
        assert offer_four["status"] == WaitlistStatus.OFFERED

    def test_the_third_requeue_is_refused_while_a_plain_decline_still_works(
        self, api
    ):
        """The cap blocks the looping arm of the edge and only that arm.

        PRD §3.2: "A household may defer at most twice: a requeueing decline sent
        when `deferral_count` has already reached 2 is rejected with
        `ERR_MAX_DEFERRALS_REACHED`."

        Design: Corner/state_machines/valid_transition_requeued_declines_cycle_until_the_deferral_cap_bites
        """
        ctx = _two_standard_entries_an_hour_apart(api)
        _cycle_until_the_budget_is_spent(api, ctx)
        fx.set_clock(api, FOURTH_OFFER_AT)
        fx.extend_next_offer(api, ctx["category"]["id"])

        body = validate_error(
            _attempt_requeue_a(api, ctx),
            ApiErrorId.MAX_DEFERRALS_REACHED, 409,
        )
        assert body["error_id"] != ApiErrorId.INVALID_TRANSITION

        live = fx.read_waitlist_entry(api, ctx["entry_a"]["id"])
        assert live["status"] == WaitlistStatus.OFFERED
        assert live["deferral_count"] == 2

        declined = fx.respond_to_offer(
            api, ctx["entry_a"]["id"], ctx["house_a"]["id"], "DECLINE"
        )
        assert declined["status"] == WaitlistStatus.DECLINED
        assert declined["deferral_count"] == 2


def _a_suspended_household_with_a_revoked_swimmer(api):
    """One SEVERE sanction run all the way down the cascade.

    The meet requires four credits and holds a single `SCORER` worth two, so it
    is still `SCHEDULED` when the cascade reaches it and the roster is left open.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-06-01T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Reinstatement Household",
            "address_line": "111 Cedar Court",
            "prior_member": False,
        },
        join_date="2027-06-01",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    ctx["registration"] = fx.setup_confirmed_registration(
        api, ctx, swimmer_name="Rafi Cole", swimmer_birthdate="2014-08-08",
        squad=Squad.JUNIOR,
    )
    ctx["meet"] = fx.create_meet(
        api, ctx["season"]["id"], name="June Dual Meet",
        start_iso="2027-06-12T08:00:00Z", end_iso="2027-06-12T13:00:00Z",
        expected_swimmers=40, volunteer_slots_required=4,
    )
    ctx["assignment"] = fx.assign_volunteer(
        api, ctx["meet"]["id"], ctx["registration"]["id"], JobCode.SCORER
    )
    # The creation response above still reads volunteer_slots_filled 0 — PRD §3.6
    # says "A new meet is `SCHEDULED`, with `volunteer_slots_filled` at 0" — so
    # re-read the meet now that the SCORER's two credits have landed and before
    # the sanction takes them away again.
    ctx["meet"] = fx.read_meet(api, ctx["meet"]["id"])
    ctx["case"] = fx.sanction_household(
        api, ctx["household"]["id"], CaseSeverity.SEVERE,
        SanctionType.SUSPENSION,
    )
    return ctx


class TestReinstatementRestoresAccessButNotRevokedChildren:
    """The softening path is deliberately narrower than the hardening one."""

    def test_the_severe_sanction_suspends_the_household_and_its_access(
        self, api
    ):
        """Eight points, SUSPENDED standing, suspended access, dues untouched.

        PRD §3.9: "The point values are two for a `MINOR` incident, four for a
        `MAJOR` one and eight for a `SEVERE` one, all integers, so a single severe
        incident sits one point below the expulsion line and two minor incidents
        sit two points below suspension."

        PRD §3.9: "Every membership of that household whose `access_status` is
        `ACTIVE` moves to `SUSPENDED`, processed in `created_at` ascending order
        so the household's oldest membership is dealt with first."

        Design: Corner/state_machines/side_effect_execution_reinstatement_restores_access_but_not_revoked_children
        """
        ctx = _a_suspended_household_with_a_revoked_swimmer(api)

        a.assert_conduct_case(ctx["case"], CaseStatus.SANCTIONED)
        assert ctx["case"]["points_assessed"] == 8

        household = fx.read_household(api, ctx["household"]["id"])
        a.assert_household(household, HouseholdStanding.SUSPENDED)
        assert household["conduct_points"] == 8

        membership = fx.read_membership(api, ctx["membership"]["id"])
        a.assert_membership(membership, DuesStatus.INVOICED,
                            AccessStatus.SUSPENDED)

    def test_the_cascade_revokes_the_swimmer_and_empties_the_credit_count(
        self, api
    ):
        """Registration REVOKED, assignment RELEASED, two credits given back.

        PRD §3.9: "Each such membership then takes every swim-team registration
        beneath it that is in `PENDING`, `CONFIRMED` or `WAITLISTED` to
        `REVOKED`, again in `created_at` ascending order, and each revoked
        registration releases its volunteer assignments, which lowers the
        affected meets' `volunteer_slots_filled` and can slide a meet
        `STAFFED → UNDERSTAFFED` exactly as described in §3.6."

        PRD §3.6: "The suspension and withdrawal cascades produce `RELEASED`,
        which is never reachable by a direct request, and it lowers
        `volunteer_slots_filled` by the same rule."

        Design: Corner/state_machines/side_effect_execution_reinstatement_restores_access_but_not_revoked_children
        """
        ctx = _a_suspended_household_with_a_revoked_swimmer(api)
        assert ctx["assignment"]["status"] == AssignmentStatus.ASSIGNED
        assert ctx["assignment"]["credit_value"] == 2
        assert ctx["meet"]["volunteer_slots_filled"] == 2

        registration = fx.read_registration(api, ctx["registration"]["id"])
        a.assert_registration(registration, RegistrationStatus.REVOKED)

        assignment = fx.read_assignment(api, ctx["assignment"]["id"])
        a.assert_volunteer_assignment(assignment, AssignmentStatus.RELEASED)

        meet = fx.read_meet(api, ctx["meet"]["id"])
        a.assert_meet(meet, MeetStatus.SCHEDULED)
        assert meet["volunteer_slots_filled"] == 0
        assert meet["roster_closed_at"] is None

    def test_reinstatement_reopens_access_and_keeps_the_points(self, api):
        """Standing and access soften together; the points ledger does not.

        PRD §3.9: "When the transition takes, every membership of the household
        whose `access_status` is `SUSPENDED` returns to `ACTIVE`, processed in
        `created_at` ascending order, and the household's `version` advances."

        PRD §3.9: "though its conduct points, which live on the household and not
        the membership, follow it for two full years"

        Design: Corner/state_machines/side_effect_execution_reinstatement_restores_access_but_not_revoked_children
        """
        ctx = _a_suspended_household_with_a_revoked_swimmer(api)
        suspended = fx.read_household(api, ctx["household"]["id"])

        reinstated = fx.reinstate_household(api, ctx["household"]["id"])

        a.assert_household(reinstated, HouseholdStanding.GOOD_STANDING)
        assert reinstated["conduct_points"] == 8
        assert reinstated["version"] > suspended["version"]

        membership = fx.read_membership(api, ctx["membership"]["id"])
        a.assert_membership(membership, DuesStatus.INVOICED,
                            AccessStatus.ACTIVE)

    def test_the_revoked_children_stay_where_the_cascade_left_them(self, api):
        """Nothing beneath the membership is walked back, in either direction.

        PRD §3.9: "Reinstatement reopens facility access and nothing more:
        revoked swim-team registrations are **not** restored, released volunteer
        assignments are **not** restored, and cancelled party reservations are
        **not** revived."

        PRD §3.6: "A membership's `volunteer_credits_required` is not a fixed
        number but a derived one: the category's `volunteer_credits_required`
        multiplied by the count of that membership's registrations whose `status`
        is `CONFIRMED` or `COMPLETED`, with the product capped at ten credits."

        Design: Corner/state_machines/side_effect_execution_reinstatement_restores_access_but_not_revoked_children
        """
        ctx = _a_suspended_household_with_a_revoked_swimmer(api)
        fx.reinstate_household(api, ctx["household"]["id"])

        registration = fx.read_registration(api, ctx["registration"]["id"])
        assert registration["status"] == RegistrationStatus.REVOKED

        assignment = fx.read_assignment(api, ctx["assignment"]["id"])
        assert assignment["status"] == AssignmentStatus.RELEASED

        meet = fx.read_meet(api, ctx["meet"]["id"])
        assert meet["volunteer_slots_filled"] == 0
        assert meet["understaffed_penalty_cents"] == 0

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["volunteer_credits_required"] == 0
        assert membership["volunteer_credits_earned"] == 0
