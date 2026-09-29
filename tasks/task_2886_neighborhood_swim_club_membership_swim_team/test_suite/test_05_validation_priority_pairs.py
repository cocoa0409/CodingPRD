"""Two competing-violation pairs, each falsifiable in both directions.

PRD §2.9: "Checks are evaluated strictly in the following order, and the first
one that fails determines the response."
"""

from test_helpers import (
    ApiErrorId,
    CertType,
    CertificationStatus,
    EmploymentStatus,
    FacilityPosture,
    FindingSeverity,
    GuardShiftStatus,
    ShiftRole,
    Zone,
    fixtures as fx,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    guard_shift_payload,
    party_reservation_payload,
)
from test_helpers.test_users import HEALTH_INSPECTOR, POOL_MANAGER, TREASURER

PARTY_PAYLOAD_KWARGS = dict(
    zone=Zone.PAVILION,
    start_iso="2027-07-25T14:00:00Z",
    end_iso="2027-07-25T17:00:00Z",
    guest_count=8,
    host_party_size=2,
)


def _household_owing_guest_fees(api):
    """An otherwise-clean COUPLE membership owing 1000 cents of guest fees.

    The COUPLE category's bond_cents is 0, so PRD §3.7's bond gate passes on the
    bond_paid_cents >= category.bond_cents branch and never competes.
    """
    ctx = fx.setup_club(
        api,
        clock_iso="2027-07-20T12:00:00Z",
        category="COUPLE",
        member_count=2,
        household_overrides={
            "primary_contact_name": "Bhatt Household",
            "address_line": "9 Cabana Court",
            "prior_member": False,
        },
        join_date="2027-05-22",
    )
    ctx["membership"] = fx.invoice_membership(api, ctx["membership"]["id"])
    visit = fx.record_visit(
        api, ctx["membership"]["id"], ctx["household"]["id"],
        guest_count=4, visit_start_iso="2027-07-20T11:00:00Z",
        sponsor_name="Ravi Bhatt",
    )
    ctx["visit"] = visit
    ctx["household"] = fx.read_household(api, ctx["household"]["id"])
    return ctx


def _attempt_party(api, ctx):
    payload = party_reservation_payload(
        membership_id=ctx["membership"]["id"], **PARTY_PAYLOAD_KWARGS
    )
    return api.create_party_reservation(payload, POOL_MANAGER)


class TestFacilityClosedOutranksDuesDelinquent:
    """Resource state at band eleven beats the fiscal band at the bottom."""

    def test_the_weekday_visit_leaves_exactly_1000_cents_owing(self, api):
        """Two passes burned, two guests charged at the weekday rate.

        PRD §3.5: "The billable guest count is `guest_count` less `passes_used`,
        and `fee_charged_cents` is that billable count multiplied by the unit
        fee; every term is an integer, so no rounding arises."

        Design: Difficulty/priority_pair_validation_conflict/facility_closed_outranks_dues_delinquent_on_party_reservation
        """
        ctx = _household_owing_guest_fees(api)

        assert ctx["visit"]["passes_used"] == 2
        assert ctx["visit"]["fee_charged_cents"] == 1000
        assert ctx["household"]["guest_fee_owed_cents"] == 1000

    def test_while_the_pool_is_open_the_only_violation_is_the_money(self, api):
        """Every check above the fiscal band passes, so 402 is the answer.

        PRD §2.9: "**Fiscal, last of all**, in this internal order: household
        delinquency (`ERR_DUES_DELINQUENT`, 402), an unsettled bond before a
        party may be booked (`ERR_BOND_NOT_PAID`, 402)."

        Design: Difficulty/priority_pair_validation_conflict/facility_closed_outranks_dues_delinquent_on_party_reservation
        """
        ctx = _household_owing_guest_fees(api)

        response = _attempt_party(api, ctx)
        validate_error(response, ApiErrorId.DUES_DELINQUENT, 402)

    def test_shutting_the_pool_changes_the_answer_to_facility_closed(self, api):
        """A byte-identical request now reports the higher-ranked violation.

        PRD §2.9: "**Resource state**, in this internal order: the referenced
        season is `OPEN` (`ERR_SEASON_NOT_OPEN`, 409); the season's facility
        posture is not `CLOSED` (`ERR_FACILITY_CLOSED`, 409)."

        Design: Difficulty/priority_pair_validation_conflict/facility_closed_outranks_dues_delinquent_on_party_reservation
        """
        ctx = _household_owing_guest_fees(api)
        validate_error(_attempt_party(api, ctx), ApiErrorId.DUES_DELINQUENT, 402)

        fx.file_finding(
            api, ctx["season"]["id"], FindingSeverity.CRITICAL,
            headers=HEALTH_INSPECTOR, inspected_on="2027-07-20",
            finding_code="PH-FECAL-INCIDENT",
            narrative="Confirmed fecal contamination; closure required.",
        )
        season = fx.read_season(api, ctx["season"]["id"])
        assert season["facility_posture"] == FacilityPosture.CLOSED
        assert season["open_critical_finding_count"] == 1

        body = validate_error(
            _attempt_party(api, ctx), ApiErrorId.FACILITY_CLOSED, 409
        )
        assert body["error_id"] != ApiErrorId.DUES_DELINQUENT
        assert body["error_id"] != ApiErrorId.BOND_NOT_PAID

    def test_neither_rejected_request_books_a_reservation_or_a_charge(self, api):
        """A rejected booking leaves no row and no money behind.

        PRD §3.7: "A new reservation is born `REQUESTED` with `refunded_cents`
        at 0, and its `total_charge_cents` is booked onto the household
        immediately: `party_charges_owed_cents` rises by that amount and the
        household's `version` advances."

        Design: Difficulty/priority_pair_validation_conflict/facility_closed_outranks_dues_delinquent_on_party_reservation
        """
        ctx = _household_owing_guest_fees(api)
        _attempt_party(api, ctx)
        fx.file_finding(
            api, ctx["season"]["id"], FindingSeverity.CRITICAL,
            headers=HEALTH_INSPECTOR, inspected_on="2027-07-20",
            finding_code="PH-FECAL-INCIDENT",
            narrative="Confirmed fecal contamination; closure required.",
        )
        _attempt_party(api, ctx)

        rows, _ = validate_paginated(
            api.list_party_reservations(
                TREASURER, {"membership_id": ctx["membership"]["id"]}
            )
        )
        assert rows == []
        household = fx.read_household(api, ctx["household"]["id"])
        assert household["party_charges_owed_cents"] == 0


SECOND_SHIFT = dict(
    shift_role=ShiftRole.SECONDARY,
    start_iso="2027-07-20T13:00:00Z",
    end_iso="2027-07-21T01:00:00Z",
)


def _guard_with_a_touching_shift_and_a_short_cpr_card(api):
    """A guard whose CPR card runs out the day the standing shift ends.

    The standing 09:00-13:00 shift on 2027-07-20 is inside the card's validity,
    so it schedules cleanly and stays in ``SCHEDULED``; the requested follow-on
    shift runs past midnight into 2027-07-21, which the same card no longer
    covers, so the certification wall and the rest buffer are broken at once.
    """
    season = fx.setup_open_season(api, clock_iso="2027-07-06T09:00:00Z")
    guard = fx.create_lifeguard(api, full_name="Ivy Okafor",
                                hire_date="2027-05-01")
    lifeguard_cert = fx.certify(api, guard["id"], CertType.LIFEGUARD,
                                issued_on="2027-01-10", expires_on="2027-12-31")
    cpr_cert = fx.certify(api, guard["id"], CertType.CPR_AED,
                          issued_on="2027-01-10", expires_on="2027-07-20")
    first_shift = fx.schedule_shift(
        api, guard["id"], season["id"],
        "2027-07-20T09:00:00Z", "2027-07-20T13:00:00Z",
        shift_role=ShiftRole.PRIMARY,
    )
    assert first_shift["status"] == GuardShiftStatus.SCHEDULED
    assert first_shift["duration_hours"] == 4

    return {
        "season": season,
        "lifeguard_id": guard["id"],
        "lifeguard_cert": lifeguard_cert,
        "cpr_cert": cpr_cert,
        "first_shift": first_shift,
    }


def _attempt_second_shift(api, ctx):
    payload = guard_shift_payload(
        lifeguard_id=ctx["lifeguard_id"], season_id=ctx["season"]["id"],
        **SECOND_SHIFT
    )
    return api.create_guard_shift(payload, POOL_MANAGER)


class TestCertificationWallOutranksTheRestBuffer:
    """Public-health compliance at band twelve beats scheduling at band fourteen."""

    def test_the_certification_wall_is_reported_while_both_rules_are_broken(
        self, api
    ):
        """The guard is employed and holds two live cards, and is still refused.

        PRD §3.8: "That check is evaluated ahead of every scheduling and fiscal
        check, so an uncertified guard is always reported as a compliance failure
        and never as a scheduling conflict."

        Design: Difficulty/priority_pair_validation_conflict/cert_wall_outranks_shift_rest_buffer_on_guard_shift_create
        """
        ctx = _guard_with_a_touching_shift_and_a_short_cpr_card(api)

        guard = fx.read_lifeguard(api, ctx["lifeguard_id"])
        assert guard["employment_status"] == EmploymentStatus.ACTIVE
        assert guard["has_valid_lifeguard_cert"] is True
        assert guard["has_valid_cpr_cert"] is True
        assert ctx["cpr_cert"]["status"] == CertificationStatus.VALID

        validate_error(
            _attempt_second_shift(api, ctx),
            ApiErrorId.CERT_NOT_VALID_FOR_SHIFT, 422,
        )

    def test_a_renewed_card_reveals_the_rest_buffer_violation_underneath(
        self, api
    ):
        """The identical request now reports the scheduling conflict instead.

        PRD §2.9: "**Constraint satisfaction**, in this internal order: the
        guard rest buffer (`ERR_SHIFT_REST_BUFFER_VIOLATION`, 409), zone
        double-booking (`ERR_ZONE_DOUBLE_BOOKED`, 409)."

        Design: Difficulty/priority_pair_validation_conflict/cert_wall_outranks_shift_rest_buffer_on_guard_shift_create
        """
        ctx = _guard_with_a_touching_shift_and_a_short_cpr_card(api)
        validate_error(
            _attempt_second_shift(api, ctx),
            ApiErrorId.CERT_NOT_VALID_FOR_SHIFT, 422,
        )

        renewal = fx.certify(
            api, ctx["lifeguard_id"], CertType.CPR_AED,
            issued_on="2027-07-06", expires_on="2028-07-05",
        )
        assert renewal["status"] == CertificationStatus.VALID

        body = validate_error(
            _attempt_second_shift(api, ctx),
            ApiErrorId.SHIFT_REST_BUFFER_VIOLATION, 409,
        )
        assert body["error_id"] != ApiErrorId.CERT_NOT_VALID_FOR_SHIFT

    def test_the_renewal_supersedes_the_old_card_and_no_shift_is_created(
        self, api
    ):
        """Two rejected requests leave one shift and four scheduled hours.

        PRD §3.8: "Recording a second certification of the same `cert_type` for
        the same guard is the renewal path: an existing row of that type in
        `VALID` moves to `SUPERSEDED`, and so does an existing row of that type
        in `EXPIRED`, in both cases advancing the superseded row's own `version`
        while the new row stands as the live one."

        Design: Difficulty/priority_pair_validation_conflict/cert_wall_outranks_shift_rest_buffer_on_guard_shift_create
        """
        ctx = _guard_with_a_touching_shift_and_a_short_cpr_card(api)
        _attempt_second_shift(api, ctx)
        fx.certify(api, ctx["lifeguard_id"], CertType.CPR_AED,
                   issued_on="2027-07-06", expires_on="2028-07-05")
        _attempt_second_shift(api, ctx)

        assert fx.read_certification(
            api, ctx["cpr_cert"]["id"]
        )["status"] == CertificationStatus.SUPERSEDED

        shifts, _ = validate_paginated(
            api.list_guard_shifts(
                POOL_MANAGER, {"lifeguard_id": ctx["lifeguard_id"]}
            )
        )
        assert len(shifts) == 1
        assert fx.read_lifeguard(api, ctx["lifeguard_id"])["scheduled_hours"] == 4
