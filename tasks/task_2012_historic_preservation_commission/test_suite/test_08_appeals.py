"""Appeals to the city council: the thirty-day filing window, one pending
appeal per application, denial finalization, and the SUSTAIN cascade into the
linked violation and property (PRD §3.6, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    assert_instant_equal,
    begin_review,
    create_district,
    create_meeting,
    create_notice_issued_violation,
    create_owner,
    create_property,
    decide_by_commissioner,
    get_application,
    get_property,
    get_success_data,
    get_violation,
    make_applicant_headers,
    schedule_hearing,
    set_clock,
    setup_staff_denied,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    verified_item,
    work_item,
)

STAFF = TEST_USERS["staff_headers"]
COMMISSIONER = TEST_USERS["commissioner_headers"]
COUNCIL = TEST_USERS["council_headers"]


class TestAppealWindowExactDayThirty:
    def test_appeal_at_exactly_thirty_days_accepted(self, api):
        """PRD §3.6: "The appeal must land within thirty days of the
        application's `decided_at` — a filing that would be later than
        `decided_at` plus thirty days is rejected with
        `ERR_APPEAL_WINDOW_LAPSED` — and only one appeal per application may be
        pending at a time: a second filing while an appeal for the same
        application is `FILED` is rejected with `ERR_APPEAL_ALREADY_PENDING`."

        Design: Difficulty/boundary_precision_check/appeal_window_exact_day_30
        """
        ctx = setup_staff_denied(decide_clock="2026-08-10T00:00:00Z")
        assert_instant_equal(ctx["application"]["decided_at"], "2026-08-10T00:00:00Z", "decided_at")

        # Exactly decided_at + 30 days: the boundary is inclusive.
        set_clock("2026-09-09T00:00:00Z")
        appeal = validate_success(
            api.create_appeal(
                {"application_id": ctx["application"]["id"], "grounds": "Procedural error"},
                make_applicant_headers(ctx["owner"]["id"]),
            ),
            201,
        )
        assert appeal["status"] == "FILED"

    def test_appeal_at_day_thirty_records_filed_at(self, api):
        """PRD §3.6: "The owning applicant appeals a `DENIED` application by
        submitting the `application_id` and the `grounds` for appeal; the
        system stamps `filed_at` with the logical clock."

        Design: Difficulty/boundary_precision_check/appeal_window_exact_day_30
        """
        ctx = setup_staff_denied(decide_clock="2026-08-10T00:00:00Z")
        set_clock("2026-09-09T00:00:00Z")
        appeal = validate_success(
            api.create_appeal(
                {"application_id": ctx["application"]["id"], "grounds": "Procedural error"},
                make_applicant_headers(ctx["owner"]["id"]),
            ),
            201,
        )
        assert_instant_equal(appeal["filed_at"], "2026-09-09T00:00:00Z", "filed_at")

        fetched = validate_success(api.get_appeal(appeal["id"], STAFF))
        assert fetched["status"] == "FILED"
        appeals, meta = validate_paginated(
            api.list_appeals(STAFF, params={"application_id": ctx["application"]["id"]})
        )
        assert meta["total_count"] == 1
        assert appeals[0]["id"] == appeal["id"]


def test_appeal_day_thirty_one_lapsed(api):
    """PRD §3.6: "The appeal must land within thirty days of the application's
    `decided_at` — a filing that would be later than `decided_at` plus thirty
    days is rejected with `ERR_APPEAL_WINDOW_LAPSED` — and only one appeal per
    application may be pending at a time: a second filing while an appeal for
    the same application is `FILED` is rejected with
    `ERR_APPEAL_ALREADY_PENDING`."

    Design: Corner/validations/appeal_day_31_lapsed
    """
    ctx = setup_staff_denied(decide_clock="2026-08-10T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")  # decided_at + 31 days
    response = api.create_appeal(
        {"application_id": ctx["application"]["id"], "grounds": "Too late"},
        make_applicant_headers(ctx["owner"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_LAPSED)


def test_second_pending_appeal_rejected(api):
    """PRD §3.6: "The appeal must land within thirty days of the application's
    `decided_at` — a filing that would be later than `decided_at` plus thirty
    days is rejected with `ERR_APPEAL_WINDOW_LAPSED` — and only one appeal per
    application may be pending at a time: a second filing while an appeal for
    the same application is `FILED` is rejected with
    `ERR_APPEAL_ALREADY_PENDING`."

    Design: Corner/endpoints/appeal_second_pending_rejected
    """
    ctx = setup_staff_denied(decide_clock="2026-08-10T00:00:00Z")
    owner_headers = make_applicant_headers(ctx["owner"]["id"])
    validate_success(
        api.create_appeal(
            {"application_id": ctx["application"]["id"], "grounds": "First appeal"},
            owner_headers,
        ),
        201,
    )
    response = api.create_appeal(
        {"application_id": ctx["application"]["id"], "grounds": "Second appeal"},
        owner_headers,
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_ALREADY_PENDING)


def test_finalize_denial_window_boundary(api):
    """PRD §3.6: "Finalization is permitted only when no appeal for the
    application is in `FILED` status and the logical clock has passed
    `decided_at` plus thirty days; attempting it while an appeal is pending, or
    while the appeal window is still open, is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/finalize_denial_window_boundary
    """
    ctx = setup_staff_denied(decide_clock="2026-08-10T00:00:00Z")
    app_id = ctx["application"]["id"]

    # At exactly decided_at + 30 days the clock has not passed the window.
    set_clock("2026-09-09T00:00:00Z")
    response = api.finalize_denial(app_id, STAFF)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_application(app_id)["status"] == "DENIED"

    # One day later the window has passed.
    set_clock("2026-09-10T00:00:00Z")
    finalized = validate_success(api.finalize_denial(app_id, STAFF))
    assert finalized["status"] == "DENIED_FINAL"


class TestAppealSustainCascade:
    def _setup_sustained_appeal(self, api):
        """After-the-fact application denied at an opened commission hearing,
        then appealed and SUSTAINED. Violation notice was issued at
        2026-08-01; the appeal decision lands at 2026-08-03."""
        set_clock("2026-08-01T00:00:00Z")
        district = create_district(name="Old Town", significance_tier="LOCAL")
        owner = create_owner()
        prop = create_property(
            owner["id"], district_id=district["id"], assessed_value_cents=20_000_000
        )
        violation = create_notice_issued_violation(prop["id"])
        submitted = submit_application(
            prop["id"],
            owner["id"],
            application_type="ADDITION",
            is_visible_from_public_way=True,
            after_the_fact=True,
            violation_id=violation["id"],
            work_items=[work_item("ADDITION", "rear addition as built", 1500000)],
        )
        begin_review(submitted["id"])
        accepted = accept_application(
            submitted["id"], [verified_item("ADDITION", 1500000)], "staff-1"
        )
        meeting = create_meeting()
        hearing = schedule_hearing(accepted["id"], meeting["id"])
        validate_success(api.open_hearing(hearing["id"], COMMISSIONER))
        decide_by_commissioner(
            accepted["id"], {"outcome": "DENY", "denial_rationale_sections": ["S1"]}
        )
        set_clock("2026-08-02T00:00:00Z")
        appeal = get_success_data(
            api.create_appeal(
                {"application_id": accepted["id"], "grounds": "Guideline S1 misapplied"},
                make_applicant_headers(owner["id"]),
            ),
            201,
        )
        set_clock("2026-08-03T00:00:00Z")
        decided_appeal = validate_success(
            api.decide_appeal(
                appeal["id"],
                {"outcome": "SUSTAIN", "council_findings": "Commission misread S1"},
                COUNCIL,
            )
        )
        return {
            "district": district,
            "owner": owner,
            "property": prop,
            "violation": violation,
            "application": accepted,
            "appeal": decided_appeal,
        }

    def test_appeal_sustain_moves_application_to_approved_on_appeal(self, api):
        """PRD §3.6: "`SUSTAIN` overturns the denial: the appeal moves to
        `DECIDED_SUSTAINED`, the application moves from `DENIED` to
        `APPROVED_ON_APPEAL`, and if the application was an after-the-fact
        legalization, the linked violation — whether still `NOTICE_ISSUED` or
        already `AFTER_THE_FACT_PENDING` — moves to `COMPLIANCE_VERIFIED` with
        its `compliance_verified_at` set to the appeal's `decided_at`, its
        `final_penalty_cents` computed with that same instant as the accrual
        stop, and the property's `open_violation_count` decremented by one with
        `compliance_posture` recomputed."

        Design: Difficulty/transitive_cascade/appeal_sustain_four_hop_chain
        """
        ctx = self._setup_sustained_appeal(api)
        assert ctx["appeal"]["status"] == "DECIDED_SUSTAINED"
        assert_instant_equal(
            ctx["appeal"]["decided_at"], "2026-08-03T00:00:00Z", "appeal decided_at"
        )
        application = get_application(ctx["application"]["id"])
        assert application["status"] == "APPROVED_ON_APPEAL"

    def test_appeal_sustain_resolves_violation_and_property_posture(self, api):
        """PRD §3.6: "`SUSTAIN` overturns the denial: the appeal moves to
        `DECIDED_SUSTAINED`, the application moves from `DENIED` to
        `APPROVED_ON_APPEAL`, and if the application was an after-the-fact
        legalization, the linked violation — whether still `NOTICE_ISSUED` or
        already `AFTER_THE_FACT_PENDING` — moves to `COMPLIANCE_VERIFIED` with
        its `compliance_verified_at` set to the appeal's `decided_at`, its
        `final_penalty_cents` computed with that same instant as the accrual
        stop, and the property's `open_violation_count` decremented by one with
        `compliance_posture` recomputed."
        PRD §3.8: "The first thirty days accrue at 10,000 cents per day; days
        thirty-one through sixty accrue at 20,000 cents per day; and every day
        from the sixty-first onward accrues at 50,000 cents per day."

        Design: Difficulty/transitive_cascade/appeal_sustain_four_hop_chain
        """
        ctx = self._setup_sustained_appeal(api)

        violation = get_violation(ctx["violation"]["id"])
        assert violation["status"] == "COMPLIANCE_VERIFIED"
        # Accrual stops at the appeal's decided_at, not the original denial.
        assert_instant_equal(
            violation["compliance_verified_at"], "2026-08-03T00:00:00Z",
            "compliance_verified_at",
        )
        # 2 elapsed days x 10000 cents; cap (10% of 20000000) not reached.
        assert violation["final_penalty_cents"] == 20000

        prop = get_property(ctx["property"]["id"])
        assert prop["open_violation_count"] == 0
        assert prop["compliance_posture"] == "CLEAR"
