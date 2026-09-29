"""Two deep cascades: one down ownership, one across the money aggregates."""

from test_helpers import (
    AccessStatus,
    AssignmentStatus,
    BondPaymentPlan,
    CaseSeverity,
    CaseStatus,
    DuesStatus,
    FacilityPosture,
    FindingSeverity,
    GuardShiftStatus,
    HouseholdStanding,
    JobCode,
    MeetStatus,
    RegistrationStatus,
    ReservationStatus,
    SanctionType,
    ShiftRole,
    Squad,
    assertions as a,
    fixtures as fx,
)
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    BOARD_PRESIDENT_USER_ID,
    HEALTH_INSPECTOR,
    POOL_MANAGER,
)


def _staffed_meet_under_one_household(api):
    """A STAFFED meet whose two credits both come from one household."""
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-06T09:00:00Z",
        category="FAMILY",
        member_count=4,
        household_overrides={
            "primary_contact_name": "Alvarez Household",
            "address_line": "14 Poolside Lane",
            "prior_member": False,
        },
        join_date="2027-07-05",
        bond_payment_plan=BondPaymentPlan.INSTALLMENTS,
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])

    first = fx.setup_confirmed_registration(
        api, ctx, swimmer_name="Mateo Alvarez",
        swimmer_birthdate="2013-03-04", squad=Squad.SENIOR,
    )
    second = fx.setup_confirmed_registration(
        api, ctx, swimmer_name="Nina Alvarez",
        swimmer_birthdate="2015-06-11", squad=Squad.JUNIOR,
    )
    meet = fx.create_meet(
        api, ctx["season"]["id"], name="Twilight Invitational",
        start_iso="2027-07-20T09:00:00Z", end_iso="2027-07-20T15:00:00Z",
        expected_swimmers=40, volunteer_slots_required=2,
    )
    timer = fx.assign_volunteer(api, meet["id"], first["id"], JobCode.TIMER)
    marshal = fx.assign_volunteer(api, meet["id"], second["id"],
                                  JobCode.MARSHAL)
    meet = fx.close_roster(api, meet["id"])

    assert timer["credit_value"] == 1
    assert marshal["credit_value"] == 1
    assert meet["status"] == MeetStatus.STAFFED
    assert meet["volunteer_slots_filled"] == 2
    assert meet["understaffed_penalty_cents"] == 0

    ctx.update({
        "registrations": [first, second],
        "assignments": [timer, marshal],
        "meet": meet,
    })
    return ctx


def _sanction_with_suspension(api, household_id):
    case = fx.report_case(
        api, household_id, CaseSeverity.MAJOR, headers=POOL_MANAGER,
        subject_name="Guest of the Alvarez household",
    )
    fx.transition_case(api, case["id"], CaseStatus.UNDER_REVIEW,
                       BOARD_PRESIDENT)
    return fx.transition_case(
        api, case["id"], CaseStatus.SANCTIONED, BOARD_PRESIDENT,
        sanction_type=SanctionType.SUSPENSION,
    )


class TestConductSuspensionCascadeReachesTheMeetRoster:
    """ConductCase to Household to Membership to registration to job to meet."""

    def test_the_sanction_hop_records_four_points_and_its_decider(self, api):
        """A MAJOR incident is four points, below the suspension threshold.

        PRD §3.9: "The point values are two for a `MINOR` incident, four for a
        `MAJOR` one and eight for a `SEVERE` one, all integers, so a single
        severe incident sits one point below the expulsion line and two minor
        incidents sit two points below suspension."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_to_meet_understaffing
        """
        ctx = _staffed_meet_under_one_household(api)
        case = _sanction_with_suspension(api, ctx["household"]["id"])

        assert case["status"] == CaseStatus.SANCTIONED
        assert case["sanction_type"] == SanctionType.SUSPENSION
        assert case["points_assessed"] == 4
        assert case["decided_by_user_id"] == BOARD_PRESIDENT_USER_ID

    def test_the_standing_comes_from_the_sanction_not_the_point_total(self, api):
        """Four points is below six, so SUSPENDED is the sanction's own work.

        PRD §3.9: "The sanction just handed down maps directly: `WARNING` to
        `GOOD_STANDING`, `PROBATION` to `PROBATION`, `SUSPENSION` to `SUSPENDED`
        and `EXPULSION` to `EXPELLED`."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_to_meet_understaffing
        """
        ctx = _staffed_meet_under_one_household(api)
        _sanction_with_suspension(api, ctx["household"]["id"])

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["conduct_points"] == 4
        assert household["standing"] == HouseholdStanding.SUSPENDED

    def test_access_is_suspended_while_the_money_dimension_is_untouched(self, api):
        """The cascade moves access_status and leaves dues_status alone.

        PRD §3.9: "Every membership of that household whose `access_status` is
        `ACTIVE` moves to `SUSPENDED`, processed in `created_at` ascending order
        so the household's oldest membership is dealt with first."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_to_meet_understaffing
        """
        ctx = _staffed_meet_under_one_household(api)
        _sanction_with_suspension(api, ctx["household"]["id"])

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["access_status"] == AccessStatus.SUSPENDED
        assert membership["dues_status"] == DuesStatus.INVOICED

    def test_both_registrations_are_revoked_and_their_jobs_released(self, api):
        """Hops three and four: registrations to REVOKED, assignments RELEASED.

        PRD §3.9: "Each such membership then takes every swim-team registration
        beneath it that is in `PENDING`, `CONFIRMED` or `WAITLISTED` to
        `REVOKED`, again in `created_at` ascending order, and each revoked
        registration releases its volunteer assignments, which lowers the
        affected meets' `volunteer_slots_filled` and can slide a meet `STAFFED →
        UNDERSTAFFED` exactly as described in §3.6."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_to_meet_understaffing
        """
        ctx = _staffed_meet_under_one_household(api)
        _sanction_with_suspension(api, ctx["household"]["id"])

        for registration in ctx["registrations"]:
            fresh = fx.read_registration(api, registration["id"])
            assert fresh["status"] == RegistrationStatus.REVOKED
        for assignment in ctx["assignments"]:
            fresh = fx.read_assignment(api, assignment["id"])
            assert fresh["status"] == AssignmentStatus.RELEASED

    def test_the_meet_slides_back_and_the_roster_stays_closed(self, api):
        """Nobody touched the meet, and the meet regressed anyway.

        PRD §3.6: "In either case, when the meet was `STAFFED` and the
        recomputed `volunteer_slots_filled` falls strictly below
        `volunteer_slots_required`, the meet slides back `STAFFED →
        UNDERSTAFFED` and `understaffed_penalty_cents` is recomputed from the
        new shortfall."

        PRD §3.6: "`roster_closed_at` is **not** cleared on that slide — the
        roster stays closed, so no replacement volunteer may be assigned."

        The penalty *amount* left behind by two successive releases is not
        asserted: the recompute above is gated on "when the meet was `STAFFED`",
        and the cascade releases the two assignments one registration at a time
        (PRD §3.9 processes them "in `created_at` ascending order"). The second
        release therefore finds a meet that is already `UNDERSTAFFED`, and PRD
        does not say whether the penalty tracks that further shortfall or keeps
        the figure the slide stamped.

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_to_meet_understaffing
        """
        ctx = _staffed_meet_under_one_household(api)
        _sanction_with_suspension(api, ctx["household"]["id"])

        meet = fx.read_meet(api, ctx["meet"]["id"])
        assert meet["volunteer_slots_filled"] == 0
        assert meet["status"] == MeetStatus.UNDERSTAFFED
        assert meet["roster_closed_at"] is not None

    def test_the_volunteer_obligation_falls_to_zero_credits(self, api):
        """No registration remains CONFIRMED, so nothing is required.

        PRD §3.6: "A membership's `volunteer_credits_required` is not a fixed
        number but a derived one: the category's `volunteer_credits_required`
        multiplied by the count of that membership's registrations whose
        `status` is `CONFIRMED` or `COMPLETED`, with the product capped at ten
        credits."

        Design: Difficulty/transitive_cascade/conduct_suspension_cascade_to_meet_understaffing
        """
        ctx = _staffed_meet_under_one_household(api)
        before = fx.read_membership(api, ctx["membership"]["id"])
        assert before["volunteer_credits_required"] == 8

        _sanction_with_suspension(api, ctx["household"]["id"])

        after = fx.read_membership(api, ctx["membership"]["id"])
        assert after["volunteer_credits_required"] == 0


def _confirmed_party_with_full_coverage(api):
    """A COUPLE household holding a CONFIRMED whole-facility party.

    The clock sits at 2027-07-08T09:00:00Z, before every shift and before the
    party, so the closure cascade's future-window preconditions all hold.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-08T09:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Bhatt Household",
            "address_line": "9 Cabana Court",
            "prior_member": False,
        },
        join_date="2027-05-22",
        bond_payment_plan=BondPaymentPlan.FULL,
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    assert ctx["membership"]["invoice_total_cents"] == 31050
    assert ctx["membership"]["balance_due_cents"] == 31050

    roles = [ShiftRole.PRIMARY, ShiftRole.SECONDARY, ShiftRole.SECONDARY]
    shifts = []
    for index, role in enumerate(roles):
        guard = fx.setup_certified_guard(
            api, full_name=f"Deck Guard {index + 1}", expires_on="2027-12-31",
        )
        shift = fx.schedule_shift(
            api, guard["lifeguard"]["id"], ctx["season"]["id"],
            "2027-07-10T13:30:00Z", "2027-07-10T19:00:00Z", shift_role=role,
        )
        shifts.append(fx.transition_shift(api, shift["id"], "CONFIRMED"))

    reservation = fx.request_party(
        api, ctx["membership"]["id"], zone="WHOLE_FACILITY",
        start_iso="2027-07-10T14:00:00Z", end_iso="2027-07-10T18:30:00Z",
        guest_count=26, host_party_size=5,
    )
    assert reservation["total_charge_cents"] == 54570
    reservation = fx.transition_party(api, reservation["id"], "CONFIRMED")
    assert reservation["status"] == ReservationStatus.CONFIRMED

    ctx["shifts"] = shifts
    ctx["reservation"] = reservation
    ctx["household"] = fx.read_household(api, ctx["household"]["id"])
    assert ctx["household"]["party_charges_owed_cents"] == 54570
    return ctx


def _file_critical_finding(api, season_id):
    return fx.file_finding(
        api, season_id, FindingSeverity.CRITICAL, headers=HEALTH_INSPECTOR,
        inspected_on="2027-07-08", finding_code="PH-FECAL-INCIDENT",
        narrative="Confirmed fecal contamination; immediate closure required.",
    )


class TestCriticalFindingClosureCascadeSettlesAMembership:
    """A health citation that ends up paying somebody's dues."""

    def test_filing_the_citation_closes_the_facility_on_the_same_request(
        self, api
    ):
        """One open critical finding shuts the pool and stamps the closure.

        PRD §3.1: "The moment the derivation lands on `CLOSED` while the
        season's previous posture was something else, `closure_started_at` is
        stamped with the logical clock and a two-hop cascade fires."

        Design: Difficulty/transitive_cascade/critical_finding_closure_cascade_to_membership_settlement
        """
        ctx = _confirmed_party_with_full_coverage(api)
        assert ctx["season"]["facility_posture"] == FacilityPosture.OPEN
        assert ctx["season"]["reserve_contributions_cents"] == 0

        _file_critical_finding(api, ctx["season"]["id"])

        season = fx.read_season(api, ctx["season"]["id"])
        assert season["open_critical_finding_count"] == 1
        assert season["facility_posture"] == FacilityPosture.CLOSED
        assert season["closure_started_at"] is not None

    def test_the_closure_cancels_the_party_in_full_and_every_shift(self, api):
        """A club-caused cancellation refunds the whole charge, two days out.

        PRD §3.7: "A closure-driven cancellation, which the posture cascade of
        §3.1 produces for every `CONFIRMED` reservation whose `end_iso` is still
        in the future, always refunds the whole `total_charge_cents` no matter
        how close to the party it lands, because the club caused it."

        Design: Difficulty/transitive_cascade/critical_finding_closure_cascade_to_membership_settlement
        """
        ctx = _confirmed_party_with_full_coverage(api)
        _file_critical_finding(api, ctx["season"]["id"])

        reservation = fx.read_reservation(api, ctx["reservation"]["id"])
        assert reservation["status"] == ReservationStatus.CANCELLED_BY_CLOSURE
        assert reservation["refunded_cents"] == 54570

        for shift in ctx["shifts"]:
            fresh = fx.read_shift(api, shift["id"])
            assert fresh["status"] == GuardShiftStatus.CANCELLED_BY_CLOSURE

    def test_the_refund_becomes_credit_and_settles_the_open_balance(self, api):
        """Credit of 54570 covers a balance of 31050, so it all applies.

        PRD §3.4: "if the household holds a membership in that reservation's
        season whose `dues_status` is `INVOICED` or `DELINQUENT`, and
        `account_credit_cents` is greater than or equal to that membership's
        `balance_due_cents`, then the whole balance is settled from the credit."

        Design: Difficulty/transitive_cascade/critical_finding_closure_cascade_to_membership_settlement
        """
        ctx = _confirmed_party_with_full_coverage(api)
        _file_critical_finding(api, ctx["season"]["id"])

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["party_charges_owed_cents"] == 0
        assert household["account_credit_cents"] == 23520

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["dues_status"] == DuesStatus.PAID
        assert membership["amount_paid_cents"] == 31050
        assert membership["balance_due_cents"] == 0
        assert membership["access_status"] == AccessStatus.ACTIVE

    def test_the_terminal_hop_books_the_capital_reserve_contribution(self, api):
        """Reaching PAID for the first time books fifty dollars of reserve.

        PRD §3.10: "the first time a membership's `dues_status` reaches `PAID`,
        five thousand cents — fifty dollars of every fully-paid membership — is
        booked to the season's reserve, raising both counters by that amount, as
        described in §3.4."

        Design: Difficulty/transitive_cascade/critical_finding_closure_cascade_to_membership_settlement
        """
        ctx = _confirmed_party_with_full_coverage(api)
        _file_critical_finding(api, ctx["season"]["id"])

        season = fx.read_season(api, ctx["season"]["id"])
        assert season["reserve_contributions_cents"] == 5000
        assert season["reserve_unallocated_cents"] == 5000
        a.assert_reserve_identity(season, [])
