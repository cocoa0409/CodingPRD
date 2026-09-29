"""Transitions refused because of another row's state, not their own."""

from test_helpers import (
    AccessStatus,
    ApiErrorId,
    CertType,
    CertificationStatus,
    DuesStatus,
    EmploymentStatus,
    GuardShiftStatus,
    RegistrationStatus,
    ShiftRole,
    Squad,
    assertions as a,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.factories import transition_payload
from test_helpers.test_users import POOL_MANAGER, SWIM_TEAM_COACH


def _pending_registration_on_an_uninvoiced_membership(api):
    """A PENDING swimmer hanging off an UNBILLED, PENDING-access membership."""
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
        bond_payment_plan="INSTALLMENTS",
    )
    assert ctx["membership"]["dues_status"] == DuesStatus.UNBILLED
    assert ctx["membership"]["access_status"] == AccessStatus.PENDING

    ctx["registration"] = fx.register_swimmer(
        api, ctx["membership"]["id"], ctx["season"]["id"],
        swimmer_name="Nina Alvarez", swimmer_birthdate="2015-06-11",
        squad=Squad.JUNIOR,
    )
    return ctx


def _attempt_confirm_registration(api, registration_id):
    return api.transition_registration(
        registration_id, transition_payload(RegistrationStatus.CONFIRMED),
        SWIM_TEAM_COACH,
    )


class TestRegistrationConfirmDependsOnTheParentMembership:
    """SwimTeamRegistration to Membership, on both parallel dimensions at once."""

    def test_a_swimmer_may_be_registered_before_the_invoice_is_cut(self, api):
        """Creation is looser than confirmation, deliberately.

        PRD §3.6: "The access-posture rule is deliberately looser here than
        anywhere else: registration accepts a membership whose `access_status` is
        `PENDING` **or** `ACTIVE`, because swimmers must be on the roster before
        the invoice is cut."

        Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_membership_access_active_and_dues_invoiced
        """
        ctx = _pending_registration_on_an_uninvoiced_membership(api)

        registration = ctx["registration"]
        assert registration["status"] == RegistrationStatus.PENDING
        assert registration["squad_seq"] == 1
        assert registration["assessed_fee_cents"] == 14500

    def test_confirmation_is_refused_for_the_other_row_s_state(self, api):
        """The registration's own status is legal and the move still fails.

        PRD §3.6: "Confirming a swimmer onto a squad is the coach's act, and it
        tightens the posture rules again: the membership must be `access_status`
        `ACTIVE` **and** `dues_status` `INVOICED` or `PAID`, and the season must
        still be `OPEN`, so no swimmer is confirmed from an uninvoiced or
        suspended membership."

        Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_membership_access_active_and_dues_invoiced
        """
        ctx = _pending_registration_on_an_uninvoiced_membership(api)

        body = validate_error(
            _attempt_confirm_registration(api, ctx["registration"]["id"]),
            ApiErrorId.MEMBERSHIP_NOT_IN_GOOD_STANDING, 409,
        )
        assert body["error_id"] != ApiErrorId.INVALID_TRANSITION
        assert fx.read_registration(
            api, ctx["registration"]["id"]
        )["status"] == RegistrationStatus.PENDING

    def test_invoicing_the_membership_makes_the_identical_move_legal(self, api):
        """A third endpoint moves the other entity and the edge opens.

        PRD §3.4: "it is the only edge from `UNBILLED` to `INVOICED`, it takes no
        payload at all, and it is available only while the membership is still
        `UNBILLED` and its season's `status` is `PLANNED` or `OPEN`. It is also
        what flips the access dimension `PENDING → ACTIVE`, provided the owning
        household's `standing` is `GOOD_STANDING` at that instant"

        Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_membership_access_active_and_dues_invoiced
        """
        ctx = _pending_registration_on_an_uninvoiced_membership(api)
        validate_error(
            _attempt_confirm_registration(api, ctx["registration"]["id"]),
            ApiErrorId.MEMBERSHIP_NOT_IN_GOOD_STANDING, 409,
        )

        invoiced = fx.invoice_membership(api, ctx["membership"]["id"])
        assert invoiced["dues_status"] == DuesStatus.INVOICED
        assert invoiced["access_status"] == AccessStatus.ACTIVE

        confirmed = validate_success(
            _attempt_confirm_registration(api, ctx["registration"]["id"]), 200
        )
        assert confirmed["status"] == RegistrationStatus.CONFIRMED

    def test_the_confirmation_writes_back_along_the_same_link(self, api):
        """Four credits become due on the parent membership.

        PRD §3.6: "Either confirmation recomputes the membership's
        `volunteer_credits_required` and its `swim_team_fee_cents`."

        Design: Difficulty/cross_entity_state_dependency/registration_confirm_requires_membership_access_active_and_dues_invoiced
        """
        ctx = _pending_registration_on_an_uninvoiced_membership(api)
        fx.invoice_membership(api, ctx["membership"]["id"])
        _attempt_confirm_registration(api, ctx["registration"]["id"])

        membership = fx.read_membership(api, ctx["membership"]["id"])
        assert membership["volunteer_credits_required"] == 4
        assert membership["swim_team_fee_cents"] == 14500


def _scheduled_shift_whose_lifeguard_card_lapses(api):
    """A SCHEDULED shift whose guard loses their LIFEGUARD card to expiry.

    Expiry happens only in step one of the billing checkpoint, which leaves the
    shift itself untouched while flipping the guard to INACTIVE.
    """
    season = fx.setup_open_season(api, clock_iso="2027-07-06T09:00:00Z")
    guard = fx.create_lifeguard(api, full_name="Ivy Okafor",
                                hire_date="2027-05-01")
    lifeguard_cert = fx.certify(api, guard["id"], CertType.LIFEGUARD,
                                issued_on="2027-01-10", expires_on="2027-07-25")
    cpr_cert = fx.certify(api, guard["id"], CertType.CPR_AED,
                          issued_on="2027-01-10", expires_on="2027-12-31")
    shift = fx.schedule_shift(
        api, guard["id"], season["id"],
        "2027-07-20T09:00:00Z", "2027-07-20T13:00:00Z",
        shift_role=ShiftRole.PRIMARY,
    )
    assert shift["status"] == GuardShiftStatus.SCHEDULED
    assert shift["counts_toward_ratio"] is True
    assert fx.read_lifeguard(api, guard["id"])["scheduled_hours"] == 4

    fx.run_billing_run(api, season["id"], as_of_date="2027-07-26")

    return {
        "season": season,
        "lifeguard_id": guard["id"],
        "lifeguard_cert": lifeguard_cert,
        "cpr_cert": cpr_cert,
        "shift": shift,
    }


def _attempt_confirm_shift(api, shift_id):
    return api.transition_guard_shift(
        shift_id, transition_payload(GuardShiftStatus.CONFIRMED), POOL_MANAGER
    )


class TestShiftConfirmDependsOnTheCertificationWall:
    """GuardShift to Certification, mediated by the guard's employment status."""

    def test_one_expiry_breaks_both_preconditions_at_once(self, api):
        """The card lapses and the guard goes inactive in the same step.

        PRD §3.8: "Expiry itself is never spontaneous — it happens only in step
        one of the billing checkpoint described in §3.1, which moves every
        `VALID` certification whose `expires_on` is strictly earlier than the
        effective date to `EXPIRED` and recomputes the affected guard's flags,
        and which can therefore drive a guard `ACTIVE → INACTIVE` by the same
        last-lifeguard-certification rule."

        Design: Difficulty/cross_entity_state_dependency/guard_shift_confirm_requires_valid_lifeguard_and_cpr_certifications
        """
        ctx = _scheduled_shift_whose_lifeguard_card_lapses(api)

        assert fx.read_certification(
            api, ctx["lifeguard_cert"]["id"]
        )["status"] == CertificationStatus.EXPIRED
        guard = fx.read_lifeguard(api, ctx["lifeguard_id"])
        assert guard["has_valid_lifeguard_cert"] is False
        assert guard["has_valid_cpr_cert"] is True
        assert guard["employment_status"] == EmploymentStatus.INACTIVE

    def test_the_shift_cannot_be_confirmed_and_is_not_written(self, api):
        """The shift stores no certification data and is refused anyway.

        PRD §3.8: "`SCHEDULED → CONFIRMED` requires the guard's
        `employment_status` to be `ACTIVE` and re-runs the whole certification
        wall against the date of `end_iso`, because a certification may have
        expired between scheduling and confirmation."

        Design: Difficulty/cross_entity_state_dependency/guard_shift_confirm_requires_valid_lifeguard_and_cpr_certifications
        """
        ctx = _scheduled_shift_whose_lifeguard_card_lapses(api)

        validate_error(
            _attempt_confirm_shift(api, ctx["shift"]["id"]),
            ApiErrorId.CERT_NOT_VALID_FOR_SHIFT, 422,
        )
        assert fx.read_shift(
            api, ctx["shift"]["id"]
        )["status"] == GuardShiftStatus.SCHEDULED

    def test_a_replacement_card_repairs_both_preconditions(self, api):
        """One certification write returns the guard to the deck.

        PRD §3.8: "Both certification flags are recomputed after every such
        write — `has_valid_lifeguard_cert` is true when at least one of the
        guard's certifications has `cert_type` `LIFEGUARD` and `status` `VALID`,
        and `has_valid_cpr_cert` is the same test for `CPR_AED` — and a guard
        sitting at `INACTIVE` returns to `ACTIVE` the moment a valid lifeguard
        certification exists for them again."

        Design: Difficulty/cross_entity_state_dependency/guard_shift_confirm_requires_valid_lifeguard_and_cpr_certifications
        """
        ctx = _scheduled_shift_whose_lifeguard_card_lapses(api)
        validate_error(
            _attempt_confirm_shift(api, ctx["shift"]["id"]),
            ApiErrorId.CERT_NOT_VALID_FOR_SHIFT, 422,
        )

        replacement = fx.certify(
            api, ctx["lifeguard_id"], CertType.LIFEGUARD,
            issued_on="2027-07-15", expires_on="2028-07-14",
        )
        assert replacement["status"] == CertificationStatus.VALID
        guard = fx.read_lifeguard(api, ctx["lifeguard_id"])
        assert guard["employment_status"] == EmploymentStatus.ACTIVE
        assert guard["has_valid_lifeguard_cert"] is True

        confirmed = validate_success(
            _attempt_confirm_shift(api, ctx["shift"]["id"]), 200
        )
        assert confirmed["status"] == GuardShiftStatus.CONFIRMED

    def test_the_confirmed_guard_is_counted_at_the_handover_instant(self, api):
        """A shift's interval is closed, so the end instant still counts.

        PRD §3.8: "Coverage counts the distinct `lifeguard_id` values over the
        season's shifts that are in `CONFIRMED`, that have `counts_toward_ratio`
        true, and whose interval contains the instant, where a shift's interval
        is **closed**: it includes both `start_iso` and `end_iso`, so a guard
        standing at the exact instant of handover is counted."

        Design: Difficulty/cross_entity_state_dependency/guard_shift_confirm_requires_valid_lifeguard_and_cpr_certifications
        """
        ctx = _scheduled_shift_whose_lifeguard_card_lapses(api)
        fx.certify(api, ctx["lifeguard_id"], CertType.LIFEGUARD,
                   issued_on="2027-07-15", expires_on="2028-07-14")
        _attempt_confirm_shift(api, ctx["shift"]["id"])

        window = validate_success(
            api.get_staffing_window(
                ctx["season"]["id"], POOL_MANAGER,
                {"at_iso": "2027-07-20T13:00:00Z"},
            ),
            200,
        )
        a.assert_staffing_window(
            window, bather_load=0, required_guard_count=1,
            scheduled_guard_count=1, compliant=True,
        )
