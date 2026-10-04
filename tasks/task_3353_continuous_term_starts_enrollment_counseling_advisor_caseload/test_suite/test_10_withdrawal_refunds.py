"""Withdrawal: dual refund variants, cascade links, dollar conservation."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, setup_registered_enrollment,
    setup_in_session_disbursing, create_section, open_zero_gap_section,
    create_aid_package, certify_aid_package,
    set_clock, assert_aid_package, assert_section_seat_invariant,
)

REGISTRAR = TEST_USERS["registrar_headers"]
FAO1 = TEST_USERS["fao1_headers"]
FAO2 = TEST_USERS["fao2_headers"]


def _read_package(enrollment_id):
    return get_success_data(
        api_client.list_aid_packages(enrollment_id, FAO1))[0]


class TestWithdrawalR2t4VsInstitutionalRefund:
    """Term 2026-10-05..2026-12-13 (70 inclusive days); withdrawal
    2026-10-25 completes 21 days (earned 21/70 = 0.30). Only entry 1
    (369750) has disbursed at census-day session start."""

    def test_title_iv_return_is_prorata_on_disbursed(self):
        """PRD §3.8: "The federal return, recorded as the package's
        `returned_cents`, is pro-rata on disbursed aid with an earned-aid
        cliff. The term's total length is the inclusive day count from
        `start_date` through `end_date`; the days completed run from
        `start_date` through the `withdrawal_date`, again counting both
        endpoints; the earned share is the exact ratio of days completed to
        total days. If that earned share is strictly greater than 0.60, no
        federal funds are returned — and note the boundary is strict, so an
        earned share of exactly 0.60 still triggers a return. Otherwise
        `returned_cents` is `disbursed_cents` multiplied by one minus the
        earned share, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/withdrawal_r2t4_vs_institutional_refund
        """
        ctx = setup_in_session_disbursing(intensity="FULL_TIME",
                                          tuition_cents=500000, efc_cents=0)
        assert ctx["package"]["disbursed_cents"] == 369750
        validate_success(api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], REGISTRAR,
            withdrawal_date="2026-10-25"), expected_status=200)
        package = _read_package(ctx["enrollment"]["id"])
        assert_aid_package(package)
        # earned = 21/70 = 0.30 -> return = round_half_up(369750 * 0.70).
        assert package["returned_cents"] == 258825, (
            f"TITLE_IV return must be 369750 * 0.7 = 258825; got "
            f"{package['returned_cents']}")
        assert package["retained_cents"] == 110925, (
            f"retained = 369750 - 258825 = 110925; got "
            f"{package['retained_cents']}")
        assert package["disbursed_cents"] == 369750
        assert package["status"] == "RETURNED"

    def test_institutional_refund_is_half_step_on_tuition(self):
        """PRD §3.8: "The institutional refund is a separate step function on
        `tuition_cents`, independent of how much aid has been disbursed, and
        it lands on the enrollment as `institutional_refund_cents`. A
        withdrawal on or before the term's `census_date` refunds the full
        `tuition_cents`; a withdrawal after census but on or before fourteen
        days past the `census_date` refunds half of `tuition_cents`, rounded
        half-up to whole cents; any later withdrawal refunds nothing."
        PRD §3.8: "Because the two variants measure different bases —
        disbursed aid versus tuition — the same withdrawal date generally
        yields different amounts for `returned_cents` and
        `institutional_refund_cents`."

        Design: Difficulty/dual_variant_calc/withdrawal_r2t4_vs_institutional_refund
        """
        ctx = setup_in_session_disbursing(intensity="FULL_TIME",
                                          tuition_cents=500000, efc_cents=0)
        resp = api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], REGISTRAR,
            withdrawal_date="2026-10-25")
        enrollment = validate_success(resp, expected_status=200)
        # 2026-10-25 is after census 2026-10-19 but within census + 14 days.
        assert enrollment["institutional_refund_cents"] == 250000, (
            f"half of 500000 tuition must be refunded; got "
            f"{enrollment['institutional_refund_cents']}")
        package = _read_package(ctx["enrollment"]["id"])
        assert enrollment["institutional_refund_cents"] != \
            package["returned_cents"], (
                "the two variants measure different bases over the same "
                "withdrawal event and must diverge here")


class TestWithdrawCascadePackageReturnScheduleCancelSectionReopen:
    def _setup_locked_section_in_session(self):
        ctx = setup_registered_enrollment(intensity="FULL_TIME",
                                          tuition_cents=500000)
        section = create_section(ctx["term"]["id"], capacity=1,
                                 forecast_enrollment=1)
        open_zero_gap_section(section["id"])
        validate_success(api_client.add_to_roster(
            section["id"], ctx["enrollment"]["id"], REGISTRAR),
            expected_status=200)
        package = create_aid_package(ctx["enrollment"]["id"], 0, FAO1)
        certify_aid_package(package["id"], ctx["enrollment"]["version"],
                            FAO2)
        set_clock("2026-10-19T00:00:00Z")
        validate_success(api_client.advance_term(
            ctx["term"]["id"], "IN_SESSION", REGISTRAR), expected_status=200)
        ctx["section"] = section
        return ctx

    def test_withdrawal_reopens_locked_section_and_resets_applicant(self):
        """PRD §3.8: "every section of the term whose roster includes the
        enrollment decrements `enrolled_count` by 1 and increments
        `seats_available` by 1, reopening `LOCKED` → `OPEN` if the freed seat
        was in a full section, each with its own `version` bump".
        PRD §3.8: "the applicant returns `ENROLLED` → `ADMITTED` with a
        `version` bump, leaving the door open to re-enrollment".

        Design: Difficulty/transitive_cascade/withdraw_cascades_package_return_schedule_cancel_section_reopen
        """
        ctx = self._setup_locked_section_in_session()
        validate_success(api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], REGISTRAR,
            withdrawal_date="2026-10-25"), expected_status=200)
        sections = get_success_data(
            api_client.list_sections_of_term(ctx["term"]["id"], REGISTRAR))
        section = [s for s in sections if s["id"] == ctx["section"]["id"]][0]
        assert_section_seat_invariant(section)
        assert section["enrolled_count"] == 0
        assert section["seats_available"] == 1
        assert section["status"] == "OPEN", (
            f"the freed seat must reopen LOCKED -> OPEN; got "
            f"{section['status']}")
        applicant = get_success_data(
            api_client.get_applicant(ctx["applicant"]["id"], REGISTRAR))
        assert applicant["status"] == "ADMITTED", (
            f"withdrawal returns the applicant ENROLLED -> ADMITTED; got "
            f"{applicant['status']}")

    def test_withdrawal_returns_package_and_cancels_schedule(self):
        """PRD §3.8: "an aid package in `CERTIFIED` or `DISBURSING`
        transitions to terminal `RETURNED` with a `version` bump".
        PRD §3.8: "Within the same cascade, every schedule entry still
        `SCHEDULED` transitions to `CANCELLED` with its amount added to
        `cancelled_cents`, every `DISBURSED` entry transitions to `RETURNED`,
        and `retained_cents` is recomputed from the new `disbursed_cents` and
        `returned_cents`."

        Design: Difficulty/transitive_cascade/withdraw_cascades_package_return_schedule_cancel_section_reopen
        """
        ctx = self._setup_locked_section_in_session()
        validate_success(api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], REGISTRAR,
            withdrawal_date="2026-10-25"), expected_status=200)
        package = _read_package(ctx["enrollment"]["id"])
        assert package["status"] == "RETURNED"
        first, second = package["disbursement_schedule"]
        assert first["entry_status"] == "RETURNED", (
            f"the DISBURSED entry must become RETURNED; got "
            f"{first['entry_status']}")
        assert second["entry_status"] == "CANCELLED", (
            f"the SCHEDULED entry must become CANCELLED; got "
            f"{second['entry_status']}")
        assert package["cancelled_cents"] == 369750
        assert package["returned_cents"] == 258825


class TestAidDollarConservationAcrossCertifyDisburseReturn:
    def _withdraw(self):
        ctx = setup_in_session_disbursing(intensity="FULL_TIME",
                                          tuition_cents=500000, efc_cents=0)
        validate_success(api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], REGISTRAR,
            withdrawal_date="2026-10-25"), expected_status=200)
        return _read_package(ctx["enrollment"]["id"])

    def test_certified_equals_disbursed_plus_cancelled(self):
        """PRD §3.8: "At all times `disbursed_cents` is the gross sum of the
        entries in `DISBURSED` or `RETURNED`, `cancelled_cents` is the sum of
        the entries in `CANCELLED`, and `retained_cents` is `disbursed_cents`
        minus `returned_cents`; once every entry is terminal,
        `certified_award_cents` equals `disbursed_cents` plus
        `cancelled_cents` exactly."

        Design: Difficulty/compensating_invariant/aid_dollar_conservation_across_certify_disburse_return
        """
        package = self._withdraw()
        assert package["certified_award_cents"] == 739500
        assert package["disbursed_cents"] == 369750
        assert package["cancelled_cents"] == 369750
        assert package["disbursed_cents"] + package["cancelled_cents"] == \
            package["certified_award_cents"], (
                "the return cascade must conserve aid dollars: "
                "369750 + 369750 == 739500")

    def test_disbursed_equals_retained_plus_returned(self):
        """PRD §3.8: "At all times `disbursed_cents` is the gross sum of the
        entries in `DISBURSED` or `RETURNED`, `cancelled_cents` is the sum of
        the entries in `CANCELLED`, and `retained_cents` is `disbursed_cents`
        minus `returned_cents`; once every entry is terminal,
        `certified_award_cents` equals `disbursed_cents` plus
        `cancelled_cents` exactly."

        Design: Difficulty/compensating_invariant/aid_dollar_conservation_across_certify_disburse_return
        """
        package = self._withdraw()
        assert package["returned_cents"] == 258825
        assert package["retained_cents"] == 110925
        assert package["retained_cents"] + package["returned_cents"] == \
            package["disbursed_cents"], (
                "110925 + 258825 == 369750: the split of disbursed aid "
                "introduces zero drift")


def test_r2t4_earned_cliff_at_exactly_sixty_percent():
    """PRD §3.8: "If that earned share is strictly greater than 0.60, no
    federal funds are returned — and note the boundary is strict, so an
    earned share of exactly 0.60 still triggers a return. Otherwise
    `returned_cents` is `disbursed_cents` multiplied by one minus the earned
    share, rounded half-up to whole cents."
    PRD §3.8: "Release itself is lazy: whenever the package is read or
    mutated, entries still `SCHEDULED` whose `release_date` is on or before
    the current logical date transition to `DISBURSED` while the term is
    `IN_SESSION`, each adding its amount into `disbursed_cents`."

    Design: Corner/calculations/r2t4_earned_cliff_at_exactly_sixty_percent
    """
    ctx = setup_in_session_disbursing(intensity="FULL_TIME",
                                      tuition_cents=500000, efc_cents=0)
    # Withdrawal on 2026-11-15 completes 42 of 70 days: earned == 0.60
    # exactly, so the strict cliff does NOT fire. The withdrawal mutates the
    # package, so entry 2 (release 2026-11-09 <= now) lazily releases first.
    set_clock("2026-11-15T00:00:00Z")
    validate_success(api_client.withdraw_enrollment(
        ctx["enrollment"]["id"], REGISTRAR, withdrawal_date="2026-11-15"),
        expected_status=200)
    package = _read_package(ctx["enrollment"]["id"])
    assert package["disbursed_cents"] == 739500, (
        f"both entries disbursed before the return is computed; got "
        f"{package['disbursed_cents']}")
    assert package["returned_cents"] == 295800, (
        f"739500 * (1 - 0.60) = 295800 must still be returned at exactly "
        f"the cliff; got {package['returned_cents']}")
    assert package["retained_cents"] == 443700


def test_withdrawal_after_term_end_rejected():
    """PRD §3.8: "The effective withdrawal date must fall on or before the
    term's `end_date`, and a later date is rejected with
    `ERR_WITHDRAWAL_WINDOW_CLOSED`."

    Design: Corner/validations/withdrawal_after_term_end_rejected
    """
    ctx = setup_registered_enrollment(tuition_cents=100000)
    resp = api_client.withdraw_enrollment(
        ctx["enrollment"]["id"], REGISTRAR, withdrawal_date="2026-12-14")
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_WINDOW_CLOSED)
    enrollment = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    assert enrollment["status"] == "REGISTERED", (
        f"a rejected withdrawal must not move the enrollment; got "
        f"{enrollment['status']}")
