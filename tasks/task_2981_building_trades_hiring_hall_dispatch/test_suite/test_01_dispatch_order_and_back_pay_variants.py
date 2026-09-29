"""
The two dual-variant computations: which registration stands rank one when the
next slot is filled, and what a sustained make-whole award is worth.
"""

from test_helpers import (
    BACK_PAY_ACTUAL_HOURS,
    BACK_PAY_SCHEDULED_HOURS,
    BP_SCALE,
    CLAIM_OUT_OF_ORDER_DISPATCH,
    DECISION_SUSTAINED,
    DISPATCH_LAID_OFF,
    DURATION_LONG_CALL,
    DURATION_SHORT_CALL,
    EVENT_MAKE_WHOLE_CREDITED,
    GRIEVANCE_SUSTAINED,
    GROUP_1,
    GROUP_4,
    LAYOFF_REDUCTION_IN_FORCE,
    OTHER_BUSINESS_MANAGER,
    REFERRAL_KIND_LIST_ORDER,
    REMEDY_MAKE_WHOLE_HOURS,
    SLOT_JOURNEYWORKER,
    STANDARD_DAY_HOURS,
    VARIANT_SHORT_CALL_INTERFILED,
    VARIANT_STRICT_GROUP_ORDER,
    DISPATCHER,
    assert_instant_equals,
    assert_integer_hours,
    assert_integer_money,
    expect_ok,
    factories as f,
    fixtures as fx,
    round_half_up_bp,
)

# ─── Scenario A: the ranking key the job's length selects ─────────────────────

# The traveler signs the book a full day before the local does, so the
# interfiled key (which orders on registered_at) and the strict key (which
# orders on the group's priority_rank) point at different rows.
TRAVELER_SIGNS_AT = "2026-09-01T00:00:00.000Z"
LOCAL_SIGNS_AT = "2026-09-02T00:00:00.000Z"
TRAVELER_RAW_HOURS = 1000
TRAVELER_CREDITED_HOURS = 500
LOCAL_CREDITED_HOURS = 9000
LONG_CALL_DAYS = 20
SHORT_CALL_DAYS = 3
RANKING_REPORT_AT = "2026-09-25T14:00:00.000Z"

# ─── Scenario B: the award the grievant's own dispatch condition selects ──────

BOOKS_AT = "2026-09-01T00:00:00.000Z"
INTAKE_AT = "2026-09-05T00:00:00.000Z"
FILING_AT = "2026-09-10T00:00:00.000Z"
LAYOFF_AT = "2026-09-14T00:00:00.000Z"
DECIDED_AT = "2026-09-15T00:00:00.000Z"
GRIEVED_RATE_CENTS = 5203
GRIEVED_REPORT_AT = "2026-09-08T14:00:00.000Z"
JOURNEYWORKER_FACTOR_BP = BP_SCALE
# Sep 8, 9, 10, 11 and 14 of 2026 are the Monday-to-Friday dates inside the
# half-open interval that starts on the dispatch date and stops short of the
# decision date; Sep 12 and 13 are the weekend.
SCHEDULED_WEEKDAYS = 5
SCHEDULED_HOURS = SCHEDULED_WEEKDAYS * STANDARD_DAY_HOURS
SCHEDULED_CENTS = 208120
ACTUAL_HOURS = 37
ACTUAL_CENTS = 192511
OVERRIDE_REASON = "dispatcher bypassed the rank-1 registrant"


def _two_group_hall(api):
    """
    A rank-one seniority group and a rank-four traveler-admitting group, each
    holding exactly one journeyworker, with the traveler the earlier signer.
    """
    fx.set_clock(api, TRAVELER_SIGNS_AT)
    home = fx.add_home_local(api)
    sister = fx.add_sister_local(api)
    group_one = fx.add_list_group(api, f.group_one_payload())
    group_four = fx.add_list_group(api, f.group_four_payload())
    fx.add_ratio_policy(api)

    local = fx.add_journeyworker(api, home["id"], "Ana Reyes", LOCAL_CREDITED_HOURS)
    traveler = fx.add_journeyworker(api, sister["id"], "Bo Chen", 0)

    traveler_registration = fx.sign_book(
        api,
        traveler["id"],
        group_four["id"],
        reciprocity_credits=[f.reciprocity_credit(sister["id"], TRAVELER_RAW_HOURS)],
    )

    fx.set_clock(api, LOCAL_SIGNS_AT)
    local_registration = fx.sign_book(api, local["id"], group_one["id"])

    contractor = fx.add_contractor(api, name="Acme Mechanical")
    return {
        "local": local,
        "local_registration": local_registration,
        "traveler": traveler,
        "traveler_registration": traveler_registration,
        "contractor": contractor,
    }


def _call_of_length(api, contractor_id, days, job_site):
    return fx.open_job_request(
        api,
        contractor_id,
        job_site=job_site,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=days,
        report_at=RANKING_REPORT_AT,
        hourly_rate_cents=5000,
    )


def _read_order(api, job_request_id):
    return expect_ok(
        api.get_dispatch_order(
            job_request_id, DISPATCHER, {"slot_kind": SLOT_JOURNEYWORKER}
        )
    )


def _two_grievances_under_review(api):
    """
    Two identical calls, each filled out of list order with a written
    justification, each grieved by the passed-over rank-one registrant, and only
    the second worker laid off before the manager rules.
    """
    fx.set_clock(api, BOOKS_AT)
    home = fx.add_home_local(api)
    group_one = fx.add_list_group(api, f.group_one_payload())
    fx.add_ratio_policy(api)

    grievant = fx.add_journeyworker(api, home["id"], "Mia Ford", 9000)
    nate = fx.add_journeyworker(api, home["id"], "Nate Ruiz", 8000)
    omar = fx.add_journeyworker(api, home["id"], "Omar Diaz", 7000)
    fx.sign_book(api, grievant["id"], group_one["id"])
    fx.sign_book(api, nate["id"], group_one["id"])
    fx.sign_book(api, omar["id"], group_one["id"])

    contractor = fx.add_contractor(api, name="Acme Mechanical")

    fx.set_clock(api, INTAKE_AT)
    calls = {}
    referrals = {}
    dispatches = {}
    for tag, job_site, taker in (
        ("a", "Cell 4 Boiler A", nate),
        ("b", "Cell 4 Boiler B", omar),
    ):
        calls[tag] = fx.open_job_request(
            api,
            contractor["id"],
            job_site=job_site,
            journeyworkers_requested=1,
            apprentices_requested=0,
            expected_duration_days=20,
            report_at=GRIEVED_REPORT_AT,
            hourly_rate_cents=GRIEVED_RATE_CENTS,
        )
        referrals[tag] = fx.issue_referral(
            api,
            calls[tag]["id"],
            slot_kind=SLOT_JOURNEYWORKER,
            referral_kind=REFERRAL_KIND_LIST_ORDER,
            member_id=taker["id"],
            override_reason=OVERRIDE_REASON,
        )
        dispatches[tag] = fx.accept_referral(api, referrals[tag]["id"], taker["id"])

    fx.set_clock(api, FILING_AT)
    grievances = {}
    for tag, narrative in (
        ("a", "I stood first on GROUP_1 and was passed over on Boiler A."),
        ("b", "I stood first on GROUP_1 and was passed over on Boiler B."),
    ):
        filed = fx.file_grievance(
            api,
            referrals[tag]["id"],
            grievant["id"],
            claim_type=CLAIM_OUT_OF_ORDER_DISPATCH,
            narrative=narrative,
        )
        grievances[tag] = fx.open_for_review(
            api, filed["id"], OTHER_BUSINESS_MANAGER
        )

    fx.set_clock(api, LAYOFF_AT)
    laid_off = fx.lay_off(
        api,
        dispatches["b"]["id"],
        contractor["id"],
        ACTUAL_HOURS,
        LAYOFF_REDUCTION_IN_FORCE,
    )

    fx.set_clock(api, DECIDED_AT)
    return {
        "grievant": grievant,
        "contractor": contractor,
        "calls": calls,
        "referrals": referrals,
        "dispatches": dispatches,
        "grievances": grievances,
        "laid_off": laid_off,
    }


def _sustain(api, grievance_id, note):
    return expect_ok(
        api.adjudicate_grievance(
            grievance_id,
            f.adjudication_payload(
                DECISION_SUSTAINED, REMEDY_MAKE_WHOLE_HOURS, note=note
            ),
            OTHER_BUSINESS_MANAGER,
        )
    )


class TestDispatchOrderVariantDivergence:
    """The ranking key is chosen by the length of the job, nothing else."""

    def test_long_call_order_puts_the_rank_one_group_ahead_of_the_earlier_traveler(
        self, api
    ):
        """
        PRD §3.2: "For a long call, the *strict group order* variant applies, and
        it sorts the surviving candidates by five components in this exact
        sequence: first by the list group's `priority_rank` ascending, so that
        every eligible rank-1 registrant outranks every rank-4 registrant
        regardless of when either signed"

        Design: Difficulty/dual_variant_calc/dispatch_order_variant_diverges_on_short_call
        """
        scene = _two_group_hall(api)
        long_call = _call_of_length(
            api, scene["contractor"]["id"], LONG_CALL_DAYS, "Riverbend Hospital"
        )
        assert long_call["duration_type"] == DURATION_LONG_CALL

        order = _read_order(api, long_call["id"])

        assert order["variant"] == VARIANT_STRICT_GROUP_ORDER
        assert order["candidate_count"] == 2
        assert order["top_registration_id"] == scene["local_registration"]["id"]
        assert order["top_member_id"] == scene["local"]["id"]
        assert order["top_list_group_code"] == GROUP_1
        assert order["top_credited_seniority_hours"] == LOCAL_CREDITED_HOURS

    def test_short_call_order_interfiles_the_groups_and_promotes_the_earlier_signer(
        self, api
    ):
        """
        PRD §3.2: "For a short call, the *short-call interfiled* variant applies
        instead, and it deliberately discards both the group precedence and the
        group's `ordering_policy`."

        Design: Difficulty/dual_variant_calc/dispatch_order_variant_diverges_on_short_call
        """
        scene = _two_group_hall(api)
        short_call = _call_of_length(
            api,
            scene["contractor"]["id"],
            SHORT_CALL_DAYS,
            "Riverbend Hospital shutdown",
        )
        assert short_call["duration_type"] == DURATION_SHORT_CALL

        order = _read_order(api, short_call["id"])

        assert order["variant"] == VARIANT_SHORT_CALL_INTERFILED
        assert order["candidate_count"] == 2
        assert order["top_registration_id"] == scene["traveler_registration"]["id"]
        assert order["top_member_id"] == scene["traveler"]["id"]
        assert order["top_list_group_code"] == GROUP_4
        assert order["top_credited_seniority_hours"] == TRAVELER_CREDITED_HOURS

    def test_the_same_two_registrations_yield_different_rank_one_rows(self, api):
        """
        PRD §3.2: "Identical registration data therefore yields a different
        top-ranked registration under the two variants, and the variant that was
        actually used is stamped onto every referral as `variant_applied`, taking
        the value `STRICT_GROUP_ORDER` or `SHORT_CALL_INTERFILED`."

        Design: Difficulty/dual_variant_calc/dispatch_order_variant_diverges_on_short_call
        """
        scene = _two_group_hall(api)
        assert scene["traveler"]["is_traveler"] is True
        assert (
            scene["traveler_registration"]["credited_seniority_hours"]
            == TRAVELER_CREDITED_HOURS
        )
        assert (
            scene["local_registration"]["credited_seniority_hours"]
            == LOCAL_CREDITED_HOURS
        )

        long_call = _call_of_length(
            api, scene["contractor"]["id"], LONG_CALL_DAYS, "Riverbend Hospital"
        )
        short_call = _call_of_length(
            api,
            scene["contractor"]["id"],
            SHORT_CALL_DAYS,
            "Riverbend Hospital shutdown",
        )

        long_order = _read_order(api, long_call["id"])
        short_order = _read_order(api, short_call["id"])

        assert long_order["candidate_count"] == short_order["candidate_count"] == 2
        assert long_order["top_registration_id"] != short_order["top_registration_id"]
        assert long_order["top_list_group_code"] == GROUP_1
        assert short_order["top_list_group_code"] == GROUP_4


class TestBackPayVariantDivergence:
    """The award is chosen by the grievant's own dispatch condition at decision."""

    def test_scheduled_hours_variant_projects_weekdays_and_rounds_each_day(self, api):
        """
        PRD §3.9: "If the improperly dispatched worker's dispatch is still
        `WORKING` at the moment of adjudication, the **scheduled-hours** variant
        applies and `back_pay_variant` records `SCHEDULED_HOURS`."

        Design: Difficulty/dual_variant_calc/back_pay_variant_diverges_on_dispatch_status
        """
        scene = _two_grievances_under_review(api)
        assert scene["referrals"]["a"]["out_of_order_override"] is True
        assert_instant_equals(scene["dispatches"]["a"]["start_at"], GRIEVED_REPORT_AT)

        decided = _sustain(
            api,
            scene["grievances"]["a"]["id"],
            "Out-of-order dispatch sustained; worker still on the job.",
        )

        per_day = round_half_up_bp(
            STANDARD_DAY_HOURS * GRIEVED_RATE_CENTS, JOURNEYWORKER_FACTOR_BP
        )
        assert decided["status"] == GRIEVANCE_SUSTAINED
        assert decided["back_pay_variant"] == BACK_PAY_SCHEDULED_HOURS
        assert decided["back_pay_hours"] == SCHEDULED_HOURS == 40
        assert decided["back_pay_amount_cents"] == per_day * SCHEDULED_WEEKDAYS
        assert decided["back_pay_amount_cents"] == SCHEDULED_CENTS
        assert_integer_hours(decided["back_pay_hours"])
        assert_integer_money(decided["back_pay_amount_cents"])

    def test_actual_hours_variant_pays_the_reported_hours_rounded_once(self, api):
        """
        PRD §3.9: "Then `back_pay_hours` is simply the contractor-reported
        `hours_worked` on that dispatch, and `back_pay_amount_cents` is that
        hours figure multiplied by `hourly_rate_cents` multiplied by the wage
        factor, divided by 10,000, and rounded half up to whole cents exactly
        once over the whole award rather than per day."

        Design: Difficulty/dual_variant_calc/back_pay_variant_diverges_on_dispatch_status
        """
        scene = _two_grievances_under_review(api)
        assert scene["laid_off"]["status"] == DISPATCH_LAID_OFF
        assert scene["laid_off"]["hours_worked"] == ACTUAL_HOURS

        decided = _sustain(
            api,
            scene["grievances"]["b"]["id"],
            "Out-of-order dispatch sustained; worker already laid off.",
        )

        assert decided["status"] == GRIEVANCE_SUSTAINED
        assert decided["back_pay_variant"] == BACK_PAY_ACTUAL_HOURS
        assert decided["back_pay_hours"] == ACTUAL_HOURS
        assert decided["back_pay_amount_cents"] == round_half_up_bp(
            ACTUAL_HOURS * GRIEVED_RATE_CENTS, JOURNEYWORKER_FACTOR_BP
        )
        assert decided["back_pay_amount_cents"] == ACTUAL_CENTS
        assert_integer_money(decided["back_pay_amount_cents"])

    def test_the_two_variants_disagree_on_both_hours_and_cents(self, api):
        """
        PRD §3.9: "The same grievance therefore yields both a different hours
        figure and a different cents figure depending on whether the improperly
        dispatched worker was still on the job when the manager ruled."

        Design: Difficulty/dual_variant_calc/back_pay_variant_diverges_on_dispatch_status
        """
        scene = _two_grievances_under_review(api)

        decided_a = _sustain(
            api, scene["grievances"]["a"]["id"], "Still on the job at decision."
        )
        decided_b = _sustain(
            api, scene["grievances"]["b"]["id"], "Off the job at decision."
        )

        # Both awards rest on the same hourly_rate_cents and the same dispatch
        # start_at, so only the variant can explain the difference.
        assert scene["calls"]["a"]["hourly_rate_cents"] == GRIEVED_RATE_CENTS
        assert scene["calls"]["b"]["hourly_rate_cents"] == GRIEVED_RATE_CENTS
        assert_instant_equals(
            scene["dispatches"]["a"]["start_at"], scene["dispatches"]["b"]["start_at"]
        )

        assert decided_a["back_pay_variant"] == BACK_PAY_SCHEDULED_HOURS
        assert decided_b["back_pay_variant"] == BACK_PAY_ACTUAL_HOURS
        assert decided_a["back_pay_hours"] != decided_b["back_pay_hours"]
        assert decided_a["back_pay_amount_cents"] != decided_b["back_pay_amount_cents"]
        assert (decided_a["back_pay_hours"], decided_b["back_pay_hours"]) == (
            SCHEDULED_HOURS,
            ACTUAL_HOURS,
        )
        assert (
            decided_a["back_pay_amount_cents"],
            decided_b["back_pay_amount_cents"],
        ) == (SCHEDULED_CENTS, ACTUAL_CENTS)

    def test_each_make_whole_award_appends_its_own_credited_hours_row(self, api):
        """
        PRD §3.9: "A `MAKE_WHOLE_CREDITED` ledger entry is appended with
        `hours_delta` equal to `back_pay_hours`."

        Design: Difficulty/dual_variant_calc/back_pay_variant_diverges_on_dispatch_status
        """
        scene = _two_grievances_under_review(api)
        _sustain(api, scene["grievances"]["a"]["id"], "Still on the job at decision.")
        _sustain(api, scene["grievances"]["b"]["id"], "Off the job at decision.")

        rows = fx.ledger_rows(
            api,
            member_id=scene["grievant"]["id"],
            event_code=EVENT_MAKE_WHOLE_CREDITED,
        )

        assert len(rows) == 2
        assert sorted(row["hours_delta"] for row in rows) == sorted(
            [SCHEDULED_HOURS, ACTUAL_HOURS]
        )
        for row in rows:
            assert row["event_code"] == EVENT_MAKE_WHOLE_CREDITED
            assert row["member_id"] == scene["grievant"]["id"]
