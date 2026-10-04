"""Section adjunct forecasting, staffing transitions, and roster seats."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_term, open_term, create_section,
    open_zero_gap_section, open_section_with_gap,
    setup_open_term_scenario, setup_registered_enrollment,
    create_applicant, create_submitted_application, admit_application,
    create_completed_tce, create_enrollment, create_advisor, set_clock,
    assert_section, assert_section_seat_invariant,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestAdjunctForecastPerSectionCeilThenSum:
    def test_per_section_ceil_values(self):
        """PRD §3.7: "For each section, `adjuncts_required` is the shortfall
        of `forecast_enrollment` over `capacity` — never below zero — divided
        by 30 students per adjunct section and rounded up to a whole adjunct.
        The rounding order is pinned and matters: the ceiling is applied per
        section first, and the term-level hiring plan is the sum of the
        per-section requirements. Summing the shortfalls first and rounding
        once is wrong and under-hires — with two sections short by 35 and 1
        student respectively, the per-section ceilings are 2 and 1 for a plan
        of 3, whereas summing first would yield 2."

        Design: Difficulty/combinatorial_formula/adjunct_forecast_per_section_ceil_then_sum
        """
        term = create_term()
        s1 = create_section(term["id"], course_code="CS-101", capacity=60,
                            forecast_enrollment=95)
        s2 = create_section(term["id"], course_code="CS-102", capacity=30,
                            forecast_enrollment=31)
        assert s1["adjuncts_required"] == 2, (
            f"shortfall 35 -> ceil(35/30) = 2; got {s1['adjuncts_required']}")
        assert s2["adjuncts_required"] == 1, (
            f"shortfall 1 -> ceil(1/30) = 1; got {s2['adjuncts_required']}")
        assert s1["adjuncts_required"] + s2["adjuncts_required"] == 3, (
            "per-section ceilings sum to 3; sum-then-ceil would wrongly "
            "yield 2")

    def test_staffed_requires_hires_meeting_requirement(self):
        """PRD §3.7: "From `STAFFING`, the advance to `STAFFED` carries an
        `adjunct_hires` payload recording how many adjuncts were actually
        hired; the payload must be at least `adjuncts_required`, an
        insufficient hire count is rejected with `ERR_INVALID_STATE`, and a
        successful advance stores the payload value on the section as its
        `adjunct_hires`."

        Design: Difficulty/combinatorial_formula/adjunct_forecast_per_section_ceil_then_sum
        """
        term = create_term()
        s1 = create_section(term["id"], course_code="CS-101", capacity=60,
                            forecast_enrollment=95)
        assert s1["adjuncts_required"] == 2
        get_success_data(api_client.advance_section(
            s1["id"], "STAFFING", REGISTRAR))
        resp = api_client.advance_section(
            s1["id"], "STAFFED", REGISTRAR, adjunct_hires=1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        resp = api_client.advance_section(
            s1["id"], "STAFFED", REGISTRAR, adjunct_hires=2)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "STAFFED"
        assert data["adjunct_hires"] == 2, (
            f"the hires payload must be stored; got {data['adjunct_hires']}")


def test_section_planned_to_staffed_requires_zero_adjunct_gap():
    """PRD §3.7: "Symmetrically, a section with no gap moves directly
    `PLANNED` → `STAFFED`, defined only when `adjuncts_required` is exactly
    zero, with an unfilled gap again rejected as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/section_planned_to_staffed_requires_zero_adjunct_gap
    """
    term = create_term()
    open_term(term["id"])
    section = create_section(term["id"], capacity=30, forecast_enrollment=31)
    assert section["adjuncts_required"] == 1
    resp = api_client.advance_section(section["id"], "STAFFED", REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    section = open_section_with_gap(section["id"], adjunct_hires=1)
    assert section["status"] == "OPEN"


def test_roster_on_planned_section_rejected_then_open_then_full():
    """PRD §3.7: "The section must be `OPEN`: a section in `PLANNED`,
    `STAFFING`, or `STAFFED` rejects the add with `ERR_SECTION_NOT_OPEN`,
    while a `LOCKED` section rejects it with `ERR_SECTION_FULL`."
    PRD §3.7: "When an add brings `seats_available` to exactly zero, the
    section transitions itself `OPEN` → `LOCKED` in the same operation."

    Design: Corner/state_machines/roster_on_planned_section_rejected_then_open_then_full
    """
    ctx = setup_open_term_scenario()
    section = create_section(ctx["term"]["id"], capacity=1,
                             forecast_enrollment=1)
    # Two REGISTERED enrollments in the open term.
    advisor = create_advisor()
    enrollments = []
    for name in ("P1", "P2"):
        applicant = create_applicant(full_name=name)
        application = create_submitted_application(
            applicant["id"], ctx["term"]["id"], ctx["program"]["id"])
        application = admit_application(application["id"])
        create_completed_tce(application["id"])
        enrollment = create_enrollment(application, advisor["id"],
                                       tuition_cents=100000)
        enrollments.append(enrollment)
    e1, e2 = enrollments

    # PLANNED section rejects the add.
    resp = api_client.add_to_roster(section["id"], e1["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_OPEN)

    # Zero-gap section staffs directly, then opens.
    section = open_zero_gap_section(section["id"])
    assert section["status"] == "OPEN"

    # Fill the single seat; the section locks itself.
    resp = api_client.add_to_roster(section["id"], e1["id"], REGISTRAR)
    data = validate_success(resp, expected_status=200)
    assert_section(data)
    assert data["seats_available"] == 0
    assert data["status"] == "LOCKED", (
        f"add bringing seats to zero must LOCK the section; got "
        f"{data['status']}")

    # A further add on the LOCKED section reports full.
    resp = api_client.add_to_roster(section["id"], e2["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_SECTION_FULL)


class TestSectionSeatConservationAcrossRosterAndWithdraw:
    def _setup_locked_section(self):
        ctx = setup_registered_enrollment()
        section = create_section(ctx["term"]["id"], capacity=1,
                                 forecast_enrollment=1)
        section = open_zero_gap_section(section["id"])
        return ctx, section

    def _read_section(self, term_id, section_id):
        sections = get_success_data(
            api_client.list_sections_of_term(term_id, REGISTRAR))
        match = [s for s in sections if s["id"] == section_id]
        assert len(match) == 1
        return match[0]

    def test_roster_add_consumes_seat_and_locks(self):
        """PRD §3.7: "A successful add increments `enrolled_count` by 1,
        decrements `seats_available` by 1 — the two are stored counters
        maintaining the invariant that `enrolled_count` plus
        `seats_available` always equals `capacity` — and bumps the section's
        `version`. When an add brings `seats_available` to exactly zero, the
        section transitions itself `OPEN` → `LOCKED` in the same operation."

        Design: Difficulty/compensating_invariant/section_seat_conservation_across_roster_and_withdraw
        """
        ctx, section = self._setup_locked_section()
        resp = api_client.add_to_roster(
            section["id"], ctx["enrollment"]["id"], REGISTRAR)
        data = validate_success(resp, expected_status=200)
        assert_section_seat_invariant(data)
        assert data["enrolled_count"] == 1
        assert data["seats_available"] == 0
        assert data["status"] == "LOCKED"

    def test_withdrawal_returns_seat_and_reopens(self):
        """PRD §3.8: "every section of the term whose roster includes the
        enrollment decrements `enrolled_count` by 1 and increments
        `seats_available` by 1, reopening `LOCKED` → `OPEN` if the freed seat
        was in a full section, each with its own `version` bump".
        PRD §3.7: "the two are stored counters maintaining the invariant that
        `enrolled_count` plus `seats_available` always equals `capacity`".

        Design: Difficulty/compensating_invariant/section_seat_conservation_across_roster_and_withdraw
        """
        ctx, section = self._setup_locked_section()
        validate_success(api_client.add_to_roster(
            section["id"], ctx["enrollment"]["id"], REGISTRAR),
            expected_status=200)
        resp = api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], REGISTRAR, withdrawal_date="2026-09-10")
        validate_success(resp, expected_status=200)
        after = self._read_section(ctx["term"]["id"], section["id"])
        assert_section_seat_invariant(after)
        assert after["enrolled_count"] == 0
        assert after["seats_available"] == 1
        assert after["status"] == "OPEN", (
            f"freeing the only seat must reopen LOCKED -> OPEN; got "
            f"{after['status']}")


def test_roster_after_add_drop_closed():
    """PRD §3.7: "Independently, the current logical date must be on or
    before the term's `add_drop_end_date`; a later add is rejected with
    `ERR_ADD_DROP_CLOSED`."

    Design: Corner/validations/roster_after_add_drop_closed
    """
    ctx = setup_registered_enrollment()
    section = create_section(ctx["term"]["id"], capacity=5,
                             forecast_enrollment=5)
    open_zero_gap_section(section["id"])
    # On the add_drop_end_date itself the add is allowed.
    set_clock("2026-10-12T23:59:59Z")
    resp = api_client.add_to_roster(
        section["id"], ctx["enrollment"]["id"], REGISTRAR)
    data = validate_success(resp, expected_status=200)
    assert data["enrolled_count"] == 1
    # One instant into the following day the window is closed.
    set_clock("2026-10-13T00:00:00Z")
    resp = api_client.add_to_roster(
        section["id"], ctx["enrollment"]["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ADD_DROP_CLOSED)
