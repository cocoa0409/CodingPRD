"""
The lifecycles themselves: where each record begins, what one legal transition
must carry with it, which triggers a machine simply does not declare from the
state it is in, and which guards a declared transition still has to clear.
"""

from test_helpers import (
    BACK_PAY_NOT_APPLICABLE,
    BUSINESS_MANAGER,
    BUSINESS_MANAGER_USER_ID,
    CLAIM_RATIO_VIOLATION,
    DECISION_DENIED,
    DISPATCHER,
    DISPATCH_LAID_OFF,
    DISPATCH_WORKING,
    ERR_DISPATCH_NOT_WORKING,
    ERR_GRIEVANCE_NOT_UNDER_REVIEW,
    ERR_HOURS_EXCEED_ELAPSED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OVERLAPPING_DISPATCH,
    ERR_RECALL_NOT_ELIGIBLE,
    ERR_REFERRAL_NOT_PENDING,
    EVENT_DISPATCH_LAID_OFF,
    EVENT_REFERRAL_ACCEPTED,
    GOOD_CAUSE_MEDICAL,
    GRIEVANCE_DENIED,
    GRIEVANCE_FILED,
    GRIEVANCE_UNDER_REVIEW,
    JOB_REQUEST_CANCELLED,
    JOB_REQUEST_CLOSED,
    JOB_REQUEST_FILLED,
    JOB_REQUEST_OPEN,
    JOB_REQUEST_PARTIALLY_FILLED,
    LAYOFF_JOB_COMPLETE,
    LAYOFF_LACK_OF_WORK,
    MAX_HOURS_PER_ELAPSED_DAY,
    PURGE_RETAINED,
    RECALL_WINDOW_DAYS,
    REFERRAL_ACCEPTED,
    REFERRAL_ISSUED,
    REFERRAL_REFUSED,
    REFERRAL_WITHDRAWN,
    REGISTRATION_DISPATCHED_OUT,
    REGISTRATION_REGISTERED,
    REMEDY_NONE,
    RETENTION_DAYS,
    SLOT_JOURNEYWORKER,
    STANDING_DELINQUENT,
    assert_instant_equals,
    expect_created,
    expect_error,
    expect_ok,
    factories as f,
    fixtures as fx,
    make_contractor_rep_headers,
    make_member_headers,
    plus_days,
    validate_list,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The single-slot call every scenario opens ─────────────────────────────────

JOB_SITE = "Feedwater Skid"
REPORT_AT = "2026-09-25T07:00:00.000Z"
RATE_CENTS = 5000
DURATION_DAYS = 20
CONTRACTOR_A = "Northline Mechanical"
CONTRACTOR_B = "Kestrel Piping"
SENIOR_HOURS = 9000
JUNIOR_HOURS = 8000

# ─── Layoff, its hour cap and its recall horizon ──────────────────────────────

LAYOFF_CLOCK = "2026-10-05T07:00:00.000Z"
RECALL_HORIZON = "2026-10-12T07:00:00.000Z"
RETENTION_HORIZON = "2031-10-04T07:00:00.000Z"
LAYOFF_HOURS = 80
ELAPSED_DAYS = 10

# ─── The grievance that is decided and then stays decided ─────────────────────

GRIEVANCE_CLOCK = "2026-09-02T00:00:00.000Z"
NARRATIVE = "Apprentice ratio was not observed on this call."
DENIAL_NOTE = "No ratio breach found."

# ─── The two-contractor recall guard ──────────────────────────────────────────

FIRST_JOB_SITE = "Boiler A"
FIRST_REPORT_AT = "2026-09-10T07:00:00.000Z"
FIRST_LAYOFF_CLOCK = "2026-09-20T07:00:00.000Z"
FIRST_RECALL_HORIZON = "2026-09-27T07:00:00.000Z"
SECOND_JOB_SITE = "Boiler B"
SECOND_REPORT_AT = "2026-09-22T07:00:00.000Z"
SECOND_LAYOFF_CLOCK = "2026-09-24T07:00:00.000Z"
SECOND_LAYOFF_HOURS = 16
RECALL_REPORT_AT = "2026-09-25T07:00:00.000Z"

# ─── The crew call whose recalls treat the list differently ───────────────────

CREW_JOB_SITE = "Turbine Deck"
CREW_JOURNEYWORKERS = 3
CREW_DURATION_DAYS = 30
CREW_RECALL_REPORT_AT = "2026-09-22T07:00:00.000Z"

# ─── The people ───────────────────────────────────────────────────────────────

INITIAL_MEMBER = "Ada Frey"
LAYOFF_MEMBER = "Bo Reyes"
HOLDER_MEMBER = "Cy Marlowe"
OTHER_MEMBER = "Dot Ellery"
GUARDED_MEMBER = "Eve Trask"
GRIEVANT_MEMBER = "Finn Oyelaran"
REFUSING_MEMBER = "Gio Halim"
ACCEPTING_MEMBER = "Hana Ozturk"
WAITING_MEMBER = "Ivo Brand"
TWO_JOB_MEMBER = "Jae Lundqvist"
CASCADE_SENIOR = "Kai Osei"
CASCADE_JUNIOR = "Lia Duarte"
SOLE_MEMBER = "Mira Vogel"
LEDGER_MEMBER = "Noor Aziz"
CANCELLED_MEMBER = "Omar Reis"
RECALLED_MEMBER = "Pilar Nunes"
UNREGISTERED_MEMBER = "Quinn Barr"


def _call(api, contractor_id, **overrides):
    """One long call for a single journeyworker, with room for variation."""
    fields = {
        "job_site": JOB_SITE,
        "journeyworkers_requested": 1,
        "apprentices_requested": 0,
        "expected_duration_days": DURATION_DAYS,
        "report_at": REPORT_AT,
        "hourly_rate_cents": RATE_CENTS,
    }
    fields.update(overrides)
    return fx.open_job_request(api, contractor_id, **fields)


def _one_registrant_and_one_call(api, full_name, **call_overrides):
    """The hall, one journeyworker on the rank-one book, and one open call."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], full_name, SENIOR_HOURS)
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name=CONTRACTOR_A)
    job_request = _call(api, contractor["id"], **call_overrides)
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "contractor": contractor,
        "job_request": job_request,
    }


def _member_at_work(api, full_name, **call_overrides):
    """The same scene carried through issuance and acceptance to a WORKING row."""
    scene = _one_registrant_and_one_call(api, full_name, **call_overrides)
    scene["referral"] = fx.issue_referral(
        api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    scene["dispatch"] = fx.accept_referral(
        api, scene["referral"]["id"], scene["member"]["id"]
    )
    return scene


def _two_registrants_and_one_call(api, people, **call_overrides):
    """A run of registrants in signing order against one call."""
    hall = fx.standard_hall(api, clock=CLOCK)
    rows = fx.register_journeyworkers(
        api, hall["home_local_id"], hall["group_1_id"], people
    )
    contractor = fx.add_contractor(api, name=CONTRACTOR_A)
    job_request = _call(api, contractor["id"], **call_overrides)
    return {
        "hall": hall,
        "rows": rows,
        "contractor": contractor,
        "job_request": job_request,
    }


def _layoff(api, dispatch_id, contractor_id, hours, reason):
    """The raw layoff call, for the legs that expect a refusal."""
    return api.layoff_dispatch(
        dispatch_id,
        f.layoff_payload(hours, reason),
        make_contractor_rep_headers(contractor_id),
    )


def _recall(api, dispatch_id, contractor_id, report_at):
    """The raw recall call, for the legs that expect a refusal."""
    return api.recall_dispatch(
        dispatch_id,
        f.recall_payload(report_at),
        make_contractor_rep_headers(contractor_id),
    )


def _read_dispatch(api, dispatch_id):
    return expect_ok(api.get_dispatch(dispatch_id, DISPATCHER))


def _read_grievance(api, grievance_id):
    return expect_ok(api.get_grievance(grievance_id, BUSINESS_MANAGER))


def _registered_rows_for(api, member_id):
    rows, _ = validate_list(
        api.list_registrations(
            DISPATCHER, {"member_id": member_id, "status": REGISTRATION_REGISTERED}
        )
    )
    return rows


class TestDeclaredInitialStates:
    """Every record enters the world in the one state its machine declares."""

    def test_a_registration_and_its_job_request_begin_registered_and_open(self, api):
        """
        PRD §3.3: "A registration's `status` takes one of five values — `REGISTERED`,
        `REFERRED`, `DISPATCHED_OUT`, `REMOVED`, or `EXPIRED` — beginning at
        `REGISTERED`, with the last three terminal."

        PRD §3.5: "A request's `status` begins at `OPEN` and is derived from its
        children's acceptances rather than set by hand."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        scene = _one_registrant_and_one_call(api, INITIAL_MEMBER)

        assert scene["registration"]["status"] == REGISTRATION_REGISTERED
        assert scene["registration"]["position_number"] == 1
        assert scene["registration"]["demotion_count"] == 0
        assert scene["job_request"]["status"] == JOB_REQUEST_OPEN
        assert scene["job_request"]["accepted_journeyworker_count"] == 0
        assert scene["job_request"]["version"] == 1

    def test_a_referral_begins_issued_and_its_dispatch_begins_working(self, api):
        """
        PRD §3.6: "A referral's `status` runs over five values — `ISSUED`, `ACCEPTED`,
        `REFUSED`, `EXPIRED`, `WITHDRAWN` — beginning at `ISSUED`, with the other four
        terminal."

        PRD §3.7: "**Accepting** moves the referral from `ISSUED` to `ACCEPTED` and the
        registration from `REFERRED` to the terminal `DISPATCHED_OUT`, and it creates
        the employment record: a `Dispatch` in `WORKING` status whose `start_at` is the
        job request's `report_at`, whose `hours_worked` begins at 0, and whose
        `ended_at`, `layoff_reason`, `recall_of_dispatch_id`, and
        `recall_window_ends_at` all begin null."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        scene = _one_registrant_and_one_call(api, INITIAL_MEMBER)

        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        assert referral["status"] == REFERRAL_ISSUED

        dispatch = fx.accept_referral(api, referral["id"], scene["member"]["id"])

        assert dispatch["status"] == DISPATCH_WORKING
        assert dispatch["hours_worked"] == 0
        assert dispatch["ended_at"] is None
        assert dispatch["layoff_reason"] is None
        assert dispatch["recall_of_dispatch_id"] is None
        assert dispatch["recall_window_ends_at"] is None
        assert_instant_equals(dispatch["start_at"], REPORT_AT)

    def test_a_grievance_begins_filed_and_undecided(self, api):
        """
        PRD §3.9: "A grievance's `decided_by_user_id` and `decided_at` are both null
        until it is adjudicated."

        PRD §3.9: "The grievance's `filed_at` is the current instant, and filing is only
        open while that instant is at or before the challenged referral's `issued_at`
        plus 10 days; a later filing is refused with `ERR_GRIEVANCE_WINDOW_EXPIRED`."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        scene = _one_registrant_and_one_call(api, GRIEVANT_MEMBER)
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.set_clock(api, GRIEVANCE_CLOCK)

        grievance = fx.file_grievance(
            api,
            referral["id"],
            scene["member"]["id"],
            claim_type=CLAIM_RATIO_VIOLATION,
            narrative=NARRATIVE,
        )

        assert grievance["status"] == GRIEVANCE_FILED
        assert grievance["decided_by_user_id"] is None
        assert grievance["decided_at"] is None
        assert grievance["version"] == 1
        assert_instant_equals(grievance["filed_at"], GRIEVANCE_CLOCK)


class TestLayoffClosesTheRecordAndOpensRecall:
    """One no-fault ending, and the recall window it opens behind it."""

    def test_the_layoff_records_the_ending_and_a_seven_day_recall_window(self, api):
        """
        PRD §3.8: "`REDUCTION_IN_FORCE`, `JOB_COMPLETE`, and `LACK_OF_WORK` are all
        no-fault endings: the `status` becomes `LAID_OFF`, `ended_at` is set to the
        current instant, the reported `hours_worked` is recorded, and
        `recall_window_ends_at` is set to the current instant plus 7 days."

        Design: Corner/state_machines/layoff_moves_dispatch_to_laid_off_and_opens_the_recall_window
        """
        scene = _member_at_work(api, LAYOFF_MEMBER)
        fx.set_clock(api, LAYOFF_CLOCK)

        laid_off = fx.lay_off(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )

        assert laid_off["status"] == DISPATCH_LAID_OFF
        assert laid_off["hours_worked"] == LAYOFF_HOURS
        assert laid_off["layoff_reason"] == LAYOFF_LACK_OF_WORK
        assert_instant_equals(laid_off["start_at"], REPORT_AT)
        assert_instant_equals(laid_off["ended_at"], LAYOFF_CLOCK)
        assert_instant_equals(
            laid_off["recall_window_ends_at"],
            plus_days(LAYOFF_CLOCK, RECALL_WINDOW_DAYS),
        )
        assert_instant_equals(laid_off["recall_window_ends_at"], RECALL_HORIZON)

    def test_the_reported_hours_are_capped_by_the_elapsed_days(self, api):
        """
        PRD §3.8: "Reported hours are sanity-checked against elapsed time:
        `hours_worked` may not exceed twelve hours for each elapsed calendar day since
        the dispatch began, where the number of elapsed days is the difference between
        the current instant and `start_at` divided by twenty-four hours and rounded up
        to a whole day."

        Design: Corner/state_machines/layoff_moves_dispatch_to_laid_off_and_opens_the_recall_window
        """
        scene = _member_at_work(api, LAYOFF_MEMBER)
        fx.set_clock(api, LAYOFF_CLOCK)
        cap = MAX_HOURS_PER_ELAPSED_DAY * ELAPSED_DAYS

        over_the_cap = _layoff(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            cap + 1,
            LAYOFF_LACK_OF_WORK,
        )
        expect_error(over_the_cap, ERR_HOURS_EXCEED_ELAPSED)

        assert _read_dispatch(api, scene["dispatch"]["id"])["status"] == DISPATCH_WORKING

        at_the_cap = expect_ok(
            _layoff(
                api,
                scene["dispatch"]["id"],
                scene["contractor"]["id"],
                cap,
                LAYOFF_LACK_OF_WORK,
            )
        )

        assert at_the_cap["status"] == DISPATCH_LAID_OFF
        assert at_the_cap["hours_worked"] == cap


class TestOnlyTheHolderMayAcceptTheReferral:
    """The acceptance trigger belongs to the member the referral names, alone."""

    def test_a_member_answering_someone_elses_referral_is_refused(self, api):
        """
        PRD §3.7: "Either the member themselves or a `Dispatcher` taking a phoned-in
        answer may respond, but a member acting for someone else is refused with
        `ERR_NOT_RESOURCE_OWNER`, and any referral not in `ISSUED` status is refused
        with `ERR_REFERRAL_NOT_PENDING`."

        Design: Corner/state_machines/accept_by_a_member_who_does_not_hold_the_referral_rejected
        """
        scene = _two_registrants_and_one_call(
            api, ((HOLDER_MEMBER, SENIOR_HOURS), (OTHER_MEMBER, JUNIOR_HOURS))
        )
        holder, other = scene["rows"]
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        assert referral["member_id"] == holder["member"]["id"]

        response = api.accept_referral(
            referral["id"], make_member_headers(other["member"]["id"])
        )

        expect_error(response, ERR_NOT_RESOURCE_OWNER)

    def test_the_refused_attempt_leaves_the_referral_answerable_by_its_holder(
        self, api
    ):
        """
        PRD §3.6: "A referral's `status` runs over five values — `ISSUED`, `ACCEPTED`,
        `REFUSED`, `EXPIRED`, `WITHDRAWN` — beginning at `ISSUED`, with the other four
        terminal."

        Design: Corner/state_machines/accept_by_a_member_who_does_not_hold_the_referral_rejected
        """
        scene = _two_registrants_and_one_call(
            api, ((HOLDER_MEMBER, SENIOR_HOURS), (OTHER_MEMBER, JUNIOR_HOURS))
        )
        holder, other = scene["rows"]
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        expect_error(
            api.accept_referral(
                referral["id"], make_member_headers(other["member"]["id"])
            ),
            ERR_NOT_RESOURCE_OWNER,
        )

        assert fx.read_referral(api, referral["id"])["status"] == REFERRAL_ISSUED

        dispatch = fx.accept_referral(api, referral["id"], holder["member"]["id"])

        assert dispatch["status"] == DISPATCH_WORKING
        assert dispatch["member_id"] == holder["member"]["id"]
        assert fx.read_referral(api, referral["id"])["status"] == REFERRAL_ACCEPTED


class TestTriggersAbsentFromTheDispatchMachine:
    """Recall needs a laid-off record; layoff needs a working one."""

    def test_recalling_a_working_dispatch_is_refused(self, api):
        """
        PRD §3.8: "Only the contractor's own representative may recall, and only a
        dispatch whose `status` is `LAID_OFF` is recallable — a `WORKING`,
        `TERMINATED_FOR_CAUSE`, or `QUIT` record is refused with
        `ERR_RECALL_NOT_ELIGIBLE`."

        Design: Corner/state_machines/recall_on_a_working_dispatch_and_second_layoff_both_rejected
        """
        scene = _member_at_work(api, GUARDED_MEMBER)

        response = _recall(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            plus_days(REPORT_AT, 30),
        )

        expect_error(response, ERR_RECALL_NOT_ELIGIBLE)
        assert _read_dispatch(api, scene["dispatch"]["id"])["status"] == DISPATCH_WORKING

    def test_a_second_layoff_is_refused_and_changes_nothing(self, api):
        """
        PRD §3.8: "Only a dispatch whose `status` is `WORKING` may be closed, and any
        other status is refused with `ERR_DISPATCH_NOT_WORKING`; the caller must be the
        representative of the contractor behind the dispatch's job request, and any
        other `X-User-ID` is refused with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/state_machines/recall_on_a_working_dispatch_and_second_layoff_both_rejected
        """
        scene = _member_at_work(api, GUARDED_MEMBER)
        fx.set_clock(api, LAYOFF_CLOCK)
        fx.lay_off(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )

        response = _layoff(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            8,
            LAYOFF_JOB_COMPLETE,
        )

        expect_error(response, ERR_DISPATCH_NOT_WORKING)
        unchanged = _read_dispatch(api, scene["dispatch"]["id"])
        assert unchanged["status"] == DISPATCH_LAID_OFF
        assert unchanged["hours_worked"] == LAYOFF_HOURS
        assert unchanged["layoff_reason"] == LAYOFF_LACK_OF_WORK
        assert_instant_equals(unchanged["recall_window_ends_at"], RECALL_HORIZON)


def _denied_grievance(api):
    """A ratio grievance carried all the way to a denial, the inert decision."""
    scene = _one_registrant_and_one_call(api, GRIEVANT_MEMBER)
    scene["referral"] = fx.issue_referral(
        api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    fx.set_clock(api, GRIEVANCE_CLOCK)
    scene["grievance"] = fx.grievance_under_review(
        api,
        scene["referral"]["id"],
        scene["member"]["id"],
        claim_type=CLAIM_RATIO_VIOLATION,
        narrative=NARRATIVE,
    )
    scene["decided"] = expect_ok(
        api.adjudicate_grievance(
            scene["grievance"]["id"],
            f.adjudication_payload(DECISION_DENIED, REMEDY_NONE, note=DENIAL_NOTE),
            BUSINESS_MANAGER,
        )
    )
    return scene


class TestDecidedGrievanceStaysDecided:
    """A denial is terminal: neither review nor adjudication is offered again."""

    def test_the_denial_records_the_decider_and_leaves_the_award_at_zero(self, api):
        """
        PRD §3.9: "Denying is deliberately inert. `status` becomes `DENIED`,
        `decided_by_user_id` and `decided_at` are recorded, `back_pay_variant` stays
        `NOT_APPLICABLE`, and `back_pay_hours` and `back_pay_amount_cents` both stay 0."

        Design: Corner/state_machines/decided_grievance_accepts_no_further_review_or_adjudication
        """
        scene = _denied_grievance(api)

        assert scene["grievance"]["status"] == GRIEVANCE_UNDER_REVIEW
        decided = scene["decided"]
        assert decided["status"] == GRIEVANCE_DENIED
        assert decided["decided_by_user_id"] == BUSINESS_MANAGER_USER_ID
        assert_instant_equals(decided["decided_at"], GRIEVANCE_CLOCK)
        assert decided["back_pay_variant"] == BACK_PAY_NOT_APPLICABLE
        assert decided["back_pay_hours"] == 0
        assert decided["back_pay_amount_cents"] == 0
        assert decided["version"] == 3

    def test_neither_review_nor_adjudication_may_be_replayed(self, api):
        """
        PRD §3.9: "Only a `FILED` grievance may be opened this way and only an
        `UNDER_REVIEW` grievance may be decided; either mismatch is refused with
        `ERR_GRIEVANCE_NOT_UNDER_REVIEW`."

        Design: Corner/state_machines/decided_grievance_accepts_no_further_review_or_adjudication
        """
        scene = _denied_grievance(api)
        grievance_id = scene["grievance"]["id"]

        expect_error(
            api.review_grievance(grievance_id, BUSINESS_MANAGER),
            ERR_GRIEVANCE_NOT_UNDER_REVIEW,
        )
        expect_error(
            api.adjudicate_grievance(
                grievance_id,
                f.adjudication_payload(DECISION_DENIED, REMEDY_NONE),
                BUSINESS_MANAGER,
            ),
            ERR_GRIEVANCE_NOT_UNDER_REVIEW,
        )

        unchanged = _read_grievance(api, grievance_id)
        assert unchanged["status"] == GRIEVANCE_DENIED
        assert unchanged["version"] == 3
        assert unchanged["decided_by_user_id"] == BUSINESS_MANAGER_USER_ID


class TestRefusalHappensOnlyOnce:
    """The referral leaves ISSUED for good, so the same answer cannot be repeated."""

    def test_a_good_cause_refusal_costs_the_member_nothing(self, api):
        """
        PRD §3.7: "**Refusing with good cause costs the member nothing.** The refusal
        declares a `refusal_good_cause_code` of `MEDICAL`, `TEMPORARILY_EMPLOYED`, or
        `OUT_OF_AREA_TRAVEL`; the referral becomes `REFUSED` with that code recorded,
        and the registration returns from `REFERRED` to `REGISTERED` with its
        `registered_at`, `credited_seniority_hours`, `demotion_count`, and
        `priority_flag` every one of them unchanged."

        Design: Corner/state_machines/second_refusal_of_the_same_referral_rejected
        """
        scene = _two_registrants_and_one_call(
            api, ((REFUSING_MEMBER, SENIOR_HOURS), (OTHER_MEMBER, JUNIOR_HOURS))
        )
        refuser = scene["rows"][0]
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        refused = fx.refuse_referral(
            api, referral["id"], refuser["member"]["id"], GOOD_CAUSE_MEDICAL
        )

        assert refused["status"] == REFERRAL_REFUSED
        assert refused["refusal_good_cause_code"] == GOOD_CAUSE_MEDICAL
        registration = fx.read_registration(api, refuser["registration"]["id"])
        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["demotion_count"] == 0
        assert registration["position_number"] == 1
        assert fx.read_member(api, refuser["member"]["id"])["refusal_strike_count"] == 0

    def test_the_same_referral_cannot_be_refused_twice(self, api):
        """
        PRD §3.7: "Either the member themselves or a `Dispatcher` taking a phoned-in
        answer may respond, but a member acting for someone else is refused with
        `ERR_NOT_RESOURCE_OWNER`, and any referral not in `ISSUED` status is refused
        with `ERR_REFERRAL_NOT_PENDING`."

        Design: Corner/state_machines/second_refusal_of_the_same_referral_rejected
        """
        scene = _two_registrants_and_one_call(
            api, ((REFUSING_MEMBER, SENIOR_HOURS), (OTHER_MEMBER, JUNIOR_HOURS))
        )
        refuser = scene["rows"][0]
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.refuse_referral(
            api, referral["id"], refuser["member"]["id"], GOOD_CAUSE_MEDICAL
        )

        response = api.refuse_referral(
            referral["id"],
            f.refusal_payload(GOOD_CAUSE_MEDICAL),
            make_member_headers(refuser["member"]["id"]),
        )

        expect_error(response, ERR_REFERRAL_NOT_PENDING)
        assert fx.read_referral(api, referral["id"])["status"] == REFERRAL_REFUSED
        assert fx.read_member(api, refuser["member"]["id"])["refusal_strike_count"] == 0


def _two_registrants_on_a_two_slot_call(api):
    """Two on the book, a call for two journeyworkers, and one acceptance taken."""
    scene = _two_registrants_and_one_call(
        api,
        ((ACCEPTING_MEMBER, SENIOR_HOURS), (WAITING_MEMBER, JUNIOR_HOURS)),
        journeyworkers_requested=2,
    )
    scene["accepter"], scene["waiter"] = scene["rows"]
    scene["referral"] = fx.issue_referral(
        api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    scene["dispatch"] = fx.accept_referral(
        api, scene["referral"]["id"], scene["accepter"]["member"]["id"]
    )
    return scene


class TestAcceptanceAppliesEveryDeclaredSideEffect:
    """One acceptance moves three records and re-derives the parent in one response."""

    def test_the_three_records_move_together(self, api):
        """
        PRD §3.7: "**Accepting** moves the referral from `ISSUED` to `ACCEPTED` and the
        registration from `REFERRED` to the terminal `DISPATCHED_OUT`, and it creates
        the employment record: a `Dispatch` in `WORKING` status whose `start_at` is the
        job request's `report_at`, whose `hours_worked` begins at 0, and whose
        `ended_at`, `layoff_reason`, `recall_of_dispatch_id`, and
        `recall_window_ends_at` all begin null."

        Design: Corner/state_machines/acceptance_applies_every_declared_side_effect_in_one_response
        """
        scene = _two_registrants_on_a_two_slot_call(api)

        assert (
            fx.read_referral(api, scene["referral"]["id"])["status"]
            == REFERRAL_ACCEPTED
        )
        assert (
            fx.read_registration(api, scene["accepter"]["registration"]["id"])["status"]
            == REGISTRATION_DISPATCHED_OUT
        )
        assert scene["dispatch"]["status"] == DISPATCH_WORKING
        assert scene["dispatch"]["hours_worked"] == 0
        assert_instant_equals(scene["dispatch"]["start_at"], REPORT_AT)

    def test_the_parent_request_is_re_derived_from_the_acceptance_counts(self, api):
        """
        PRD §3.7: "And on the request side, the matching acceptance counter is
        incremented, `max_apprentices_allowed` is re-derived from the new accepted
        journeyworker count, the open-slot counters are recomputed, the group's
        `registered_count` is decremented, the request's `status` is re-derived from the
        acceptance counts, and the request's `version` increments by 1."

        PRD §3.5: "When an acceptance leaves the accepted headcount — journeyworkers
        plus apprentices — greater than zero but still short of the total requested, an
        `OPEN` request advances to `PARTIALLY_FILLED`."

        Design: Corner/state_machines/acceptance_applies_every_declared_side_effect_in_one_response
        """
        scene = _two_registrants_on_a_two_slot_call(api)

        request = fx.read_job_request(api, scene["job_request"]["id"])
        assert request["status"] == JOB_REQUEST_PARTIALLY_FILLED
        assert request["accepted_journeyworker_count"] == 1
        assert request["accepted_apprentice_count"] == 0
        assert request["open_journeyworker_slots"] == 1
        assert request["version"] == 3

    def test_the_group_count_reflects_only_the_registrations_still_standing(self, api):
        """
        PRD §3.2: "A group's `registered_count` is computed as the number of
        registrations currently on it whose `status` is `REGISTERED`."

        Design: Corner/state_machines/acceptance_applies_every_declared_side_effect_in_one_response
        """
        scene = _two_registrants_on_a_two_slot_call(api)

        group = fx.read_list_group(api, scene["hall"]["group_1_id"])
        assert group["registered_count"] == 1

        standing = fx.registrations_on(
            api, scene["hall"]["group_1_id"], status=REGISTRATION_REGISTERED
        )
        assert [row["member_id"] for row in standing] == [
            scene["waiter"]["member"]["id"]
        ]
        assert standing[0]["position_number"] == 1

    def test_one_referral_accepted_entry_is_appended_for_the_accepting_member(
        self, api
    ):
        """
        PRD §3.7: "A `REFERRAL_ACCEPTED` entry is appended to the dispatch record."

        Design: Corner/state_machines/acceptance_applies_every_declared_side_effect_in_one_response
        """
        scene = _two_registrants_on_a_two_slot_call(api)

        rows = fx.ledger_rows(api, event_code=EVENT_REFERRAL_ACCEPTED)

        assert len(rows) == 1
        assert rows[0]["member_id"] == scene["accepter"]["member"]["id"]
        assert rows[0]["referral_id"] == scene["referral"]["id"]
        assert rows[0]["hours_delta"] == 0


def _member_working_for_a_second_contractor(api):
    """
    One journeyworker laid off by the first contractor, back on the book, and then
    dispatched to a second contractor's call — so the laid-off record is recallable
    while the member is demonstrably at work somewhere else.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], TWO_JOB_MEMBER, SENIOR_HOURS)
    fx.sign_book(api, member["id"], hall["group_1_id"])
    first_contractor = fx.add_contractor(api, name=CONTRACTOR_A)
    first_call = _call(
        api,
        first_contractor["id"],
        job_site=FIRST_JOB_SITE,
        report_at=FIRST_REPORT_AT,
    )
    first_referral = fx.issue_referral(
        api, first_call["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    first_dispatch = fx.accept_referral(api, first_referral["id"], member["id"])

    fx.set_clock(api, FIRST_LAYOFF_CLOCK)
    laid_off = fx.lay_off(
        api,
        first_dispatch["id"],
        first_contractor["id"],
        LAYOFF_HOURS,
        LAYOFF_LACK_OF_WORK,
    )
    fx.sign_book(
        api,
        member["id"],
        hall["group_1_id"],
        headers=make_member_headers(member["id"]),
    )
    second_contractor = fx.add_contractor(api, name=CONTRACTOR_B)
    second_call = _call(
        api,
        second_contractor["id"],
        job_site=SECOND_JOB_SITE,
        report_at=SECOND_REPORT_AT,
    )
    second_referral = fx.issue_referral(
        api, second_call["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    second_dispatch = fx.accept_referral(api, second_referral["id"], member["id"])
    return {
        "hall": hall,
        "member": member,
        "first_contractor": first_contractor,
        "second_contractor": second_contractor,
        "first_call": first_call,
        "laid_off": laid_off,
        "second_dispatch": second_dispatch,
    }


class TestRecallGuardedByAnotherWorkingDispatch:
    """The laid-off record is recallable, but only once the member is free."""

    def test_the_recall_is_refused_while_the_member_works_elsewhere(self, api):
        """
        PRD §3.8: "The member must hold no dispatch whose `status` is `WORKING`, and the
        supplied `report_at` must not fall inside any existing employment interval of
        that member, failing with `ERR_OVERLAPPING_DISPATCH`."

        Design: Corner/state_machines/recall_is_guarded_by_the_members_other_working_dispatch
        """
        scene = _member_working_for_a_second_contractor(api)
        assert scene["laid_off"]["status"] == DISPATCH_LAID_OFF
        assert_instant_equals(
            scene["laid_off"]["recall_window_ends_at"], FIRST_RECALL_HORIZON
        )
        assert scene["second_dispatch"]["status"] == DISPATCH_WORKING

        response = _recall(
            api,
            scene["laid_off"]["id"],
            scene["first_contractor"]["id"],
            RECALL_REPORT_AT,
        )

        expect_error(response, ERR_OVERLAPPING_DISPATCH)
        assert _read_dispatch(api, scene["laid_off"]["id"])["status"] == DISPATCH_LAID_OFF

    def test_the_same_recall_succeeds_once_the_other_job_ends(self, api):
        """
        PRD §3.8: "A successful recall leaves the laid-off record exactly where it is —
        that row stays `LAID_OFF` — and creates a **new** `Dispatch` in `WORKING` status
        whose `recall_of_dispatch_id` points back at the laid-off record, whose
        `start_at` is the supplied `report_at`, and whose `job_request_id` and
        `member_id` are carried over unchanged."

        Design: Corner/state_machines/recall_is_guarded_by_the_members_other_working_dispatch
        """
        scene = _member_working_for_a_second_contractor(api)
        fx.set_clock(api, SECOND_LAYOFF_CLOCK)
        fx.lay_off(
            api,
            scene["second_dispatch"]["id"],
            scene["second_contractor"]["id"],
            SECOND_LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )

        recalled = expect_created(
            _recall(
                api,
                scene["laid_off"]["id"],
                scene["first_contractor"]["id"],
                RECALL_REPORT_AT,
            )
        )

        assert recalled["status"] == DISPATCH_WORKING
        assert recalled["recall_of_dispatch_id"] == scene["laid_off"]["id"]
        assert recalled["job_request_id"] == scene["first_call"]["id"]
        assert recalled["member_id"] == scene["member"]["id"]
        assert recalled["hours_worked"] == 0
        assert_instant_equals(recalled["start_at"], RECALL_REPORT_AT)
        assert _read_dispatch(api, scene["laid_off"]["id"])["status"] == DISPATCH_LAID_OFF


def _senior_member_with_a_refused_and_a_live_referral(api):
    """
    One member holding two referrals on the same call: the first already refused
    with good cause and therefore terminal, the second still outstanding.
    """
    scene = _two_registrants_and_one_call(
        api, ((CASCADE_SENIOR, SENIOR_HOURS), (CASCADE_JUNIOR, JUNIOR_HOURS))
    )
    scene["senior"], scene["junior"] = scene["rows"]
    scene["first_referral"] = fx.issue_referral(
        api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    fx.refuse_referral(
        api,
        scene["first_referral"]["id"],
        scene["senior"]["member"]["id"],
        GOOD_CAUSE_MEDICAL,
    )
    scene["second_referral"] = fx.issue_referral(
        api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return scene


class TestDelinquencyCascadesOnlyToLiveReferrals:
    """The cascade reaches the outstanding referral and leaves the terminal one be."""

    def test_only_the_issued_referral_is_withdrawn(self, api):
        """
        PRD §3.1: "a change to `DELINQUENT` reaches into work already in flight: every
        referral of that member still in `ISSUED` status becomes `WITHDRAWN`, and each
        linked registration returns from `REFERRED` to `REGISTERED` with its original
        ordinal and its accrued `demotion_count` restored and no refusal strike charged,
        exactly as if the hall had withdrawn the referral itself."

        Design: Corner/state_machines/member_delinquency_cascades_only_to_the_non_terminal_referral
        """
        scene = _senior_member_with_a_refused_and_a_live_referral(api)
        senior_id = scene["senior"]["member"]["id"]
        # The good-cause refusal left the senior member at ordinal one with no
        # demotion charged, so the second list-order issuance reaches them again.
        assert scene["second_referral"]["member_id"] == senior_id
        assert scene["second_referral"]["status"] == REFERRAL_ISSUED

        fx.set_standing(api, senior_id, STANDING_DELINQUENT)

        member = fx.read_member(api, senior_id)
        assert member["standing"] == STANDING_DELINQUENT
        assert member["dispatch_eligible"] is False
        assert (
            fx.read_referral(api, scene["second_referral"]["id"])["status"]
            == REFERRAL_WITHDRAWN
        )
        assert (
            fx.read_referral(api, scene["first_referral"]["id"])["status"]
            == REFERRAL_REFUSED
        )

    def test_the_released_registration_reoccupies_its_original_ordinal(self, api):
        """
        PRD §3.3: "Its `position_number` is the one-based rank of the registration
        within its own list among the rows whose `status` is `REGISTERED`, computed
        under the same intra-list key the strict-group-order variant uses, and it is
        null whenever the `status` is anything other than `REGISTERED`."

        Design: Corner/state_machines/member_delinquency_cascades_only_to_the_non_terminal_referral
        """
        scene = _senior_member_with_a_refused_and_a_live_referral(api)
        fx.set_standing(api, scene["senior"]["member"]["id"], STANDING_DELINQUENT)

        senior = fx.read_registration(api, scene["senior"]["registration"]["id"])
        junior = fx.read_registration(api, scene["junior"]["registration"]["id"])

        assert senior["status"] == REGISTRATION_REGISTERED
        assert senior["position_number"] == 1
        assert senior["demotion_count"] == 0
        assert junior["status"] == REGISTRATION_REGISTERED
        assert junior["position_number"] == 2
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 2


class TestRequestStatusDerivedFromItsChildren:
    """The parent request is never set by hand: it is inferred, twice over."""

    def test_the_only_acceptance_fills_the_request(self, api):
        """
        PRD §3.5: "When an acceptance brings the accepted headcount level with the total
        requested, the request advances to `FILLED`, whether it was `OPEN` or already
        `PARTIALLY_FILLED` beforehand."

        Design: Corner/state_machines/job_request_closes_when_every_dispatch_leaves_working
        """
        scene = _member_at_work(api, SOLE_MEMBER)

        filled = fx.read_job_request(api, scene["job_request"]["id"])

        assert filled["status"] == JOB_REQUEST_FILLED
        assert filled["accepted_journeyworker_count"] == 1
        assert filled["open_journeyworker_slots"] == 0
        assert filled["version"] == 3

    def test_the_last_dispatch_leaving_working_closes_the_request(self, api):
        """
        PRD §3.5: "Once a request is `FILLED` and every dispatch belonging to it has
        left `WORKING` status, the request bubbles up to the terminal `CLOSED` state with
        its `version` incremented — a parent's completion inferred from the aggregate
        condition of its children, re-evaluated after every dispatch status change on
        the request."

        Design: Corner/state_machines/job_request_closes_when_every_dispatch_leaves_working
        """
        scene = _member_at_work(api, SOLE_MEMBER)
        fx.set_clock(api, LAYOFF_CLOCK)

        laid_off = fx.lay_off(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )

        assert laid_off["status"] == DISPATCH_LAID_OFF
        closed = fx.read_job_request(api, scene["job_request"]["id"])
        assert closed["status"] == JOB_REQUEST_CLOSED
        assert closed["version"] == 4


class TestLayoffReconcilesLedgerAndHourBank:
    """The same reported hours land in two places: the record, and the hour bank."""

    def test_one_dispatch_laid_off_entry_carries_the_reported_hours(self, api):
        """
        PRD §3.8: "A `DISPATCH_LAID_OFF` ledger entry is appended carrying `hours_delta`
        equal to the reported hours, with the reason recorded in its `snapshot_json`, and
        the dispatch's `version` increments by 1."

        PRD §2.10: "Each entry's `retention_until` is its `recorded_at` plus 1,825 days,
        and its `purge_state` is `RETAINED` until the housekeeping sweep flips it to
        `PURGED` and clears `snapshot_json` to null."

        Design: Corner/state_machines/layoff_reconciles_the_ledger_and_the_members_hour_bank
        """
        scene = _member_at_work(api, LEDGER_MEMBER)
        fx.set_clock(api, LAYOFF_CLOCK)
        fx.lay_off(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )

        rows = fx.ledger_rows(api, event_code=EVENT_DISPATCH_LAID_OFF)

        assert len(rows) == 1
        entry = rows[0]
        assert entry["hours_delta"] == LAYOFF_HOURS
        assert entry["member_id"] == scene["member"]["id"]
        assert entry["referral_id"] == scene["referral"]["id"]
        assert entry["purge_state"] == PURGE_RETAINED
        assert_instant_equals(entry["recorded_at"], LAYOFF_CLOCK)
        assert_instant_equals(
            entry["retention_until"], plus_days(LAYOFF_CLOCK, RETENTION_DAYS)
        )
        assert_instant_equals(entry["retention_until"], RETENTION_HORIZON)

    def test_the_reported_hours_are_added_to_the_members_hour_bank(self, api):
        """
        PRD §3.8: "Whichever ending applies, the reported `hours_worked` is added to the
        member's `local_hours_in_trade`, which is how work under the home local's
        agreement accumulates toward the higher list groups and toward seniority on the
        next registration."

        Design: Corner/state_machines/layoff_reconciles_the_ledger_and_the_members_hour_bank
        """
        scene = _member_at_work(api, LEDGER_MEMBER)
        assert fx.read_member(api, scene["member"]["id"])["local_hours_in_trade"] == (
            SENIOR_HOURS
        )
        fx.set_clock(api, LAYOFF_CLOCK)

        laid_off = fx.lay_off(
            api,
            scene["dispatch"]["id"],
            scene["contractor"]["id"],
            LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )

        assert laid_off["hours_worked"] == LAYOFF_HOURS
        assert fx.read_member(api, scene["member"]["id"])["local_hours_in_trade"] == (
            SENIOR_HOURS + LAYOFF_HOURS
        )


def _cancelled_call_and_a_second_chance(api):
    """One registrant, a referral on the first call, and a second call in reserve."""
    scene = _one_registrant_and_one_call(api, CANCELLED_MEMBER)
    scene["second_call"] = _call(
        api, scene["contractor"]["id"], job_site=SECOND_JOB_SITE
    )
    scene["referral"] = fx.issue_referral(
        api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return scene


class TestCancellationReleasesOutstandingReferrals:
    """Cancelling the parent hands the member's ordinal straight back."""

    def test_the_cancellation_withdraws_the_referral_and_restores_the_ordinal(
        self, api
    ):
        """
        PRD §3.5: "The request's `status` becomes the terminal `CANCELLED` and its
        `version` increments; every referral on it whose `status` is `ISSUED` becomes
        `WITHDRAWN`, and each affected registration returns to `REGISTERED` with its
        ordinal and `demotion_count` restored and no strike charged, appending a
        `REFERRAL_WITHDRAWN` and a `POSITION_RESTORED` entry per affected registration —
        the same third and fourth hops the delinquency cascade performs."

        Design: Corner/state_machines/job_request_cancellation_releases_its_outstanding_referrals
        """
        scene = _cancelled_call_and_a_second_chance(api)

        cancelled = expect_ok(
            api.cancel_job_request(
                scene["job_request"]["id"],
                f.cancel_payload(),
                make_contractor_rep_headers(scene["contractor"]["id"]),
            )
        )

        assert cancelled["status"] == JOB_REQUEST_CANCELLED
        assert (
            fx.read_referral(api, scene["referral"]["id"])["status"]
            == REFERRAL_WITHDRAWN
        )
        registration = fx.read_registration(api, scene["registration"]["id"])
        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["position_number"] == 1
        assert registration["demotion_count"] == 0

    def test_the_released_registration_can_be_referred_to_the_other_call(self, api):
        """
        PRD §3.6: "The member must hold no outstanding referral — no referral of any of
        that member's registrations may have `status` of `ISSUED` with an
        `acceptance_deadline` at or after the current instant — failing with
        `ERR_REFERRAL_ALREADY_OUTSTANDING`."

        Design: Corner/state_machines/job_request_cancellation_releases_its_outstanding_referrals
        """
        scene = _cancelled_call_and_a_second_chance(api)
        expect_ok(
            api.cancel_job_request(
                scene["job_request"]["id"],
                f.cancel_payload(),
                make_contractor_rep_headers(scene["contractor"]["id"]),
            )
        )

        reissued = fx.issue_referral(
            api, scene["second_call"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert reissued["status"] == REFERRAL_ISSUED
        assert reissued["member_id"] == scene["member"]["id"]
        assert reissued["registration_id"] == scene["registration"]["id"]
        assert reissued["list_position_at_issue"] == 1


def _two_members_laid_off_from_one_call(api):
    """
    Two journeyworkers off the same under-filled crew call, both laid off, with only
    one of them signing the book again afterwards.
    """
    scene = _two_registrants_and_one_call(
        api,
        ((RECALLED_MEMBER, SENIOR_HOURS), (UNREGISTERED_MEMBER, JUNIOR_HOURS)),
        job_site=CREW_JOB_SITE,
        journeyworkers_requested=CREW_JOURNEYWORKERS,
        expected_duration_days=CREW_DURATION_DAYS,
        report_at=FIRST_REPORT_AT,
    )
    scene["returner"], scene["stayer"] = scene["rows"]
    dispatches = {}
    for row in (scene["returner"], scene["stayer"]):
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        dispatches[row["member"]["id"]] = fx.accept_referral(
            api, referral["id"], row["member"]["id"]
        )

    fx.set_clock(api, FIRST_LAYOFF_CLOCK)
    for member_id, dispatch in dispatches.items():
        fx.lay_off(
            api,
            dispatch["id"],
            scene["contractor"]["id"],
            LAYOFF_HOURS,
            LAYOFF_LACK_OF_WORK,
        )
    scene["dispatches"] = dispatches
    scene["new_registration"] = fx.sign_book(
        api,
        scene["returner"]["member"]["id"],
        scene["hall"]["group_1_id"],
        headers=make_member_headers(scene["returner"]["member"]["id"]),
    )
    return scene


class TestRecallTouchesTheListOnlyWhenThereIsOne:
    """A recall consumes a re-registration if one exists, and nothing if none does."""

    def test_the_recall_consumes_the_members_new_registration(self, api):
        """
        PRD §3.8: "If the member had signed the book again in the meantime and holds a
        registration whose `status` is `REGISTERED`, that registration becomes
        `DISPATCHED_OUT` and its list is renumbered."

        Design: Corner/state_machines/recall_touches_the_list_only_for_a_member_who_re_registered
        """
        scene = _two_members_laid_off_from_one_call(api)
        returner_id = scene["returner"]["member"]["id"]
        assert scene["new_registration"]["status"] == REGISTRATION_REGISTERED
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 1

        recalled = expect_created(
            _recall(
                api,
                scene["dispatches"][returner_id]["id"],
                scene["contractor"]["id"],
                CREW_RECALL_REPORT_AT,
            )
        )

        assert recalled["status"] == DISPATCH_WORKING
        assert (
            fx.read_registration(api, scene["new_registration"]["id"])["status"]
            == REGISTRATION_DISPATCHED_OUT
        )
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 0

    def test_a_recall_without_a_registration_leaves_the_book_alone(self, api):
        """
        PRD §3.8: "Otherwise the member's out-of-work position is untouched: a recall
        consumes no list ordinal and no named-call allowance."

        Design: Corner/state_machines/recall_touches_the_list_only_for_a_member_who_re_registered
        """
        scene = _two_members_laid_off_from_one_call(api)
        stayer_id = scene["stayer"]["member"]["id"]
        assert _registered_rows_for(api, stayer_id) == []
        before = fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ]

        recalled = expect_created(
            _recall(
                api,
                scene["dispatches"][stayer_id]["id"],
                scene["contractor"]["id"],
                CREW_RECALL_REPORT_AT,
            )
        )

        assert recalled["status"] == DISPATCH_WORKING
        assert recalled["member_id"] == stayer_id
        assert _registered_rows_for(api, stayer_id) == []
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == before
