"""
The endpoint surfaces themselves: a record that is only ever re-statused rather
than deleted, a self-loop that moves two dates and nothing else, a read that
computes a ranking and stores nothing, an action honoured at the closed edge of
its window, one sweep that reports each bucket separately, and a link row that
takes its filer from the header.
"""

from test_helpers import (
    BUSINESS_MANAGER,
    CLAIM_OUT_OF_ORDER_DISPATCH,
    DELINQUENT_TRUST_FUNDS,
    DISPATCHER,
    DISPATCH_LAID_OFF,
    DISPATCH_WORKING,
    DURATION_LONG_CALL,
    ERR_RECALL_WINDOW_CLOSED,
    ERR_REFERRAL_NOT_FOUND,
    ERR_REGISTRATION_NOT_ACTIVE,
    EVENT_REGISTRATION_RENEWED,
    GRIEVANCE_FILED,
    GROUP_1,
    HALL_ADMIN,
    LAYOFF_LACK_OF_WORK,
    NON_EXISTENT_UUID,
    RECALL_WINDOW_DAYS,
    REFERRAL_EXPIRED,
    REGISTRATION_EXPIRED,
    REGISTRATION_REGISTERED,
    REGISTRATION_REMOVED,
    REMOVAL_RENEWAL_LAPSED,
    REMOVAL_VOLUNTARY,
    RESIGN_INTERVAL_DAYS,
    SIGNATORY,
    SLOT_JOURNEYWORKER,
    TERMINATED,
    VARIANT_STRICT_GROUP_ORDER,
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

# ─── The contractor surface ───────────────────────────────────────────────────

SIGNATORY_NAME = "Aldridge Mechanical"
DELINQUENT_NAME = "Delinquent Drilling"
AGREEMENT_EXPIRES_AT = "2027-06-30T00:00:00.000Z"

# ─── The renewal self-loop ────────────────────────────────────────────────────

HEAD_MEMBER = "Bea Nowak"
HEAD_HOURS = 9000
SECOND_MEMBER = "Cal Rendon"
SECOND_HOURS = 8000
FIRST_DUE_AT = "2026-10-01T00:00:00.000Z"
RENEWAL_CLOCK = "2026-09-15T00:00:00.000Z"
SECOND_DUE_AT = "2026-10-15T00:00:00.000Z"

# ─── The dispatch-order projection ────────────────────────────────────────────

RANK_ONE_MEMBER = "Dee Salas"
RANK_ONE_HOURS = 5000
RANK_TWO_MEMBER = "Eze Nwosu"
RANK_TWO_HOURS = 12000
ORDER_JOB_SITE = "Long Outage"
ORDER_REPORT_AT = "2026-09-25T07:00:00.000Z"
ORDER_DURATION_DAYS = 30
ORDER_JOURNEYWORKERS = 2
ORDER_RATE_CENTS = 5000

# ─── The recall window's right edge ───────────────────────────────────────────

RECALLED_MEMBER = "Fay Mercer"
RECALLED_HOURS = 9000
LATE_MEMBER = "Gus Kaplan"
LATE_HOURS = 8000
RECALL_JOB_SITE = "Turbine Deck"
RECALL_REPORT_AT = "2026-09-10T07:00:00.000Z"
RECALL_JOURNEYWORKERS = 3
RECALL_DURATION_DAYS = 30
RECALL_RATE_CENTS = 5000
LAYOFF_CLOCK = "2026-09-20T07:00:00.000Z"
LAYOFF_HOURS = 80
WINDOW_ENDS_AT = "2026-09-27T07:00:00.000Z"
ONE_MILLISECOND_LATE = "2026-09-27T07:00:00.001Z"
NEW_REPORT_AT = "2026-09-28T07:00:00.000Z"

# ─── The sweep's per-bucket counts ────────────────────────────────────────────

UNANSWERED_MEMBER = "Hal Duarte"
UNANSWERED_HOURS = 9000
RENEWING_MEMBER = "Ines Vogel"
RENEWING_HOURS = 8000
LAPSING_MEMBER = "Juno Ashby"
LAPSING_HOURS = 7000
SWEEP_JOB_SITE = "Feedwater Skid"
SWEEP_REPORT_AT = "2026-10-25T07:00:00.000Z"
SWEEP_DURATION_DAYS = 20
SWEEP_RATE_CENTS = 5000
ACCEPTANCE_DEADLINE = "2026-09-02T00:00:00.000Z"
RESIGN_CLOCK = "2026-09-30T00:00:00.000Z"
MOVED_DUE_AT = "2026-10-30T00:00:00.000Z"
SWEEP_CLOCK = "2026-10-02T00:00:00.000Z"

# ─── The grievance link row ───────────────────────────────────────────────────

REFERRED_MEMBER = "Kit Larue"
REFERRED_HOURS = 9000
FILING_MEMBER = "Lev Osman"
FILING_HOURS = 8000
LINK_JOB_SITE = "Feedwater Skid"
LINK_REPORT_AT = "2026-09-25T07:00:00.000Z"
LINK_DURATION_DAYS = 20
LINK_JOURNEYWORKERS = 1
LINK_RATE_CENTS = 5000
MISSING_NARRATIVE = "No such referral."
LINK_NARRATIVE = "I stood ahead of this member on the list."


def _two_contractors_one_of_each_status(api):
    """One signatory employer and one already behind on its trust funds."""
    fx.set_clock(api, CLOCK)
    signatory = fx.add_contractor(
        api,
        name=SIGNATORY_NAME,
        agreement_expires_at=AGREEMENT_EXPIRES_AT,
        signatory_status=SIGNATORY,
    )
    delinquent = fx.add_contractor(
        api,
        name=DELINQUENT_NAME,
        agreement_expires_at=AGREEMENT_EXPIRES_AT,
        signatory_status=DELINQUENT_TRUST_FUNDS,
    )
    return {"signatory": signatory, "delinquent": delinquent}


def _signatory_contractors(api):
    return validate_list(
        api.list_contractors(DISPATCHER, {"signatory_status": SIGNATORY})
    )


class TestContractorSurfaceIsCreateReadListAndRestatus:
    """Create, read, filter, re-status — and no way at all to delete a record."""

    def test_the_created_employer_reads_back_field_for_field(self, api):
        """
        PRD §3.5: "A `Contractor` is a signatory employer, entered by a `HallAdmin` with
        a `name` of 1 to 120 characters, an `agreement_expires_at` instant recording when
        its collective bargaining agreement lapses, and a `signatory_status` that defaults
        to `SIGNATORY` and is otherwise `DELINQUENT_TRUST_FUNDS` or `TERMINATED`."

        Design: Corner/endpoints/contractor_create_read_list_and_status_update_all_work
        """
        scene = _two_contractors_one_of_each_status(api)
        assert scene["signatory"]["name"] == SIGNATORY_NAME
        assert scene["signatory"]["signatory_status"] == SIGNATORY
        assert scene["signatory"]["version"] == 1

        read_back = expect_ok(
            api.get_contractor(scene["signatory"]["id"], DISPATCHER)
        )

        assert read_back["name"] == SIGNATORY_NAME
        assert read_back["signatory_status"] == SIGNATORY
        assert_instant_equals(read_back["agreement_expires_at"], AGREEMENT_EXPIRES_AT)

    def test_the_list_filter_selects_on_signatory_status(self, api):
        """
        PRD §3.5: "Contractors may be listed and filtered by `signatory_status`."

        Design: Corner/endpoints/contractor_create_read_list_and_status_update_all_work
        """
        scene = _two_contractors_one_of_each_status(api)

        rows, meta = _signatory_contractors(api)

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [scene["signatory"]["id"]]

    def test_the_narrow_patch_moves_only_the_status_and_bumps_the_version(self, api):
        """
        PRD §3.5: "When a `HallAdmin` or `BusinessManager` changes a contractor's
        `signatory_status` to `DELINQUENT_TRUST_FUNDS` or `TERMINATED`, the first hop
        moves every `OPEN` or `PARTIALLY_FILLED` job request of that contractor to
        `SUSPENDED`, recording the status it held in `suspended_from_status` — a field
        that is null unless the request is suspended and otherwise holds `OPEN` or
        `PARTIALLY_FILLED` — and incrementing each request's `version`."

        PRD §3.5: "The contractor's own `version` increments by 1."

        Design: Corner/endpoints/contractor_create_read_list_and_status_update_all_work
        """
        scene = _two_contractors_one_of_each_status(api)

        patched = expect_ok(
            api.patch_contractor_signatory_status(
                scene["signatory"]["id"],
                f.signatory_status_payload(TERMINATED),
                BUSINESS_MANAGER,
            )
        )

        assert patched["signatory_status"] == TERMINATED
        assert patched["name"] == SIGNATORY_NAME
        assert patched["version"] == 2
        _, meta = _signatory_contractors(api)
        assert meta["total_count"] == 0


def _head_of_the_book_and_a_removed_neighbour(api):
    """
    Two signers a month ago, the second of them taken off the book, with the
    clock now standing two weeks into the renewal period.
    """
    hall = fx.standard_hall(api, clock=CLOCK, with_policy=False)
    head = fx.add_journeyworker(api, hall["home_local_id"], HEAD_MEMBER, HEAD_HOURS)
    neighbour = fx.add_journeyworker(
        api, hall["home_local_id"], SECOND_MEMBER, SECOND_HOURS
    )
    head_registration = fx.sign_book(api, head["id"], hall["group_1_id"])
    neighbour_registration = fx.sign_book(api, neighbour["id"], hall["group_1_id"])
    removed = expect_ok(
        api.remove_registration(
            neighbour_registration["id"],
            f.removal_payload(REMOVAL_VOLUNTARY),
            DISPATCHER,
        )
    )
    fx.set_clock(api, RENEWAL_CLOCK)
    return {
        "hall": hall,
        "head": head,
        "neighbour": neighbour,
        "head_registration": head_registration,
        "neighbour_registration": neighbour_registration,
        "removed": removed,
    }


def _renew(api, registration_id, headers):
    return api.renew_registration(registration_id, headers)


class TestRenewMovesTheDeadlineAndNothingElse:
    """A self-loop on the timing fields: the ordinal is not re-earned by renewing."""

    def test_re_signing_recomputes_both_timing_fields_from_the_clock(self, api):
        """
        PRD §3.4: "A registration's `renewal_due_at` is always its `last_renewed_at` plus
        30 days, and re-signing — available to the member itself, to a `Dispatcher`, or to
        a `HallAdmin`, and taking no request body at all — sets `last_renewed_at` to the
        current instant and recomputes `renewal_due_at` as that instant plus 30 days."

        Design: Corner/endpoints/renew_action_moves_the_deadline_without_disturbing_list_order
        """
        scene = _head_of_the_book_and_a_removed_neighbour(api)
        assert_instant_equals(
            scene["head_registration"]["renewal_due_at"], FIRST_DUE_AT
        )
        assert scene["head_registration"]["version"] == 1

        renewed = expect_ok(
            _renew(
                api,
                scene["head_registration"]["id"],
                make_member_headers(scene["head"]["id"]),
            )
        )

        assert renewed["status"] == REGISTRATION_REGISTERED
        assert_instant_equals(renewed["last_renewed_at"], RENEWAL_CLOCK)
        assert_instant_equals(renewed["renewal_due_at"], SECOND_DUE_AT)
        assert_instant_equals(
            SECOND_DUE_AT, plus_days(RENEWAL_CLOCK, RESIGN_INTERVAL_DAYS)
        )

    def test_the_ordinal_and_the_demotions_survive_the_renewal_untouched(self, api):
        """
        PRD §3.4: "`registered_at`, `credited_seniority_hours`, `demotion_count`,
        `priority_flag`, and `position_number` are all left exactly as they were — a
        monthly re-sign is a statement that the member is still looking for work, not a
        fresh signature."

        PRD §3.4: "The operation appends a `REGISTRATION_RENEWED` ledger entry and
        increments the registration's `version` by 1."

        Design: Corner/endpoints/renew_action_moves_the_deadline_without_disturbing_list_order
        """
        scene = _head_of_the_book_and_a_removed_neighbour(api)

        renewed = expect_ok(
            _renew(
                api,
                scene["head_registration"]["id"],
                make_member_headers(scene["head"]["id"]),
            )
        )

        assert_instant_equals(renewed["registered_at"], CLOCK)
        assert renewed["position_number"] == 1
        assert renewed["demotion_count"] == 0
        assert renewed["version"] == 2
        _, meta = validate_list(
            api.list_ledger_entries(
                HALL_ADMIN,
                {
                    "member_id": scene["head"]["id"],
                    "event_code": EVENT_REGISTRATION_RENEWED,
                },
            )
        )
        assert meta["total_count"] == 1

    def test_a_removed_registration_cannot_be_re_signed_at_all(self, api):
        """
        PRD §3.4: "Only a registration whose `status` is `REGISTERED` may be re-signed,
        and any other status is refused with `ERR_REGISTRATION_NOT_ACTIVE`."

        Design: Corner/endpoints/renew_action_moves_the_deadline_without_disturbing_list_order
        """
        scene = _head_of_the_book_and_a_removed_neighbour(api)
        assert scene["removed"]["status"] == REGISTRATION_REMOVED
        assert scene["removed"]["removal_reason"] == REMOVAL_VOLUNTARY

        response = _renew(api, scene["neighbour_registration"]["id"], DISPATCHER)

        expect_error(response, ERR_REGISTRATION_NOT_ACTIVE)


def _two_groups_and_a_long_call(api):
    """
    A high-hours registrant on the rank-2 group and a lower-hours registrant on
    the rank-1 group, with one long call open against both.
    """
    hall = fx.standard_hall(api, clock=CLOCK, groups=("GROUP_1", "GROUP_2"))
    rank_two = fx.add_journeyworker(
        api, hall["home_local_id"], RANK_TWO_MEMBER, RANK_TWO_HOURS
    )
    rank_one = fx.add_journeyworker(
        api, hall["home_local_id"], RANK_ONE_MEMBER, RANK_ONE_HOURS
    )
    rank_two_registration = fx.sign_book(api, rank_two["id"], hall["group_2_id"])
    rank_one_registration = fx.sign_book(api, rank_one["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=ORDER_JOB_SITE,
        journeyworkers_requested=ORDER_JOURNEYWORKERS,
        apprentices_requested=0,
        expected_duration_days=ORDER_DURATION_DAYS,
        report_at=ORDER_REPORT_AT,
        hourly_rate_cents=ORDER_RATE_CENTS,
    )
    return {
        "hall": hall,
        "rank_one": rank_one,
        "rank_two": rank_two,
        "rank_one_registration": rank_one_registration,
        "rank_two_registration": rank_two_registration,
        "contractor": contractor,
        "job_request": job_request,
    }


def _dispatch_order(api, job_request_id):
    return expect_ok(
        api.get_dispatch_order(
            job_request_id, BUSINESS_MANAGER, {"slot_kind": SLOT_JOURNEYWORKER}
        )
    )


class TestDispatchOrderReadIsALiveProjection:
    """The read computes the same ranking the write will use, and stores nothing."""

    def test_the_read_reports_the_governing_variant_and_the_pool_size(self, api):
        """
        PRD §3.2: "A `HallAdmin`, `Dispatcher`, or `BusinessManager` may inspect the
        computed pool for a job request's next open slot before committing to anything:
        supplying the `slot_kind` of interest returns the governing variant in `variant`,
        the size of the surviving pool in `candidate_count`, and a description of the
        top-ranked candidate in `top_registration_id`, `top_member_id`,
        `top_list_group_code`, `top_position_number`, and
        `top_credited_seniority_hours`."

        PRD §3.5: "The computed `duration_type` is `SHORT_CALL` when
        `expected_duration_days` is 5 or fewer, and `LONG_CALL` otherwise."

        Design: Corner/endpoints/dispatch_order_read_puts_the_higher_priority_group_first
        """
        scene = _two_groups_and_a_long_call(api)
        assert scene["job_request"]["duration_type"] == DURATION_LONG_CALL

        order = _dispatch_order(api, scene["job_request"]["id"])

        assert order["variant"] == VARIANT_STRICT_GROUP_ORDER
        assert order["candidate_count"] == 2

    def test_the_rank_one_group_beats_seniority_outright(self, api):
        """
        PRD §3.2: "For a long call, the *strict group order* variant applies, and it sorts
        the surviving candidates by five components in this exact sequence: first by the
        list group's `priority_rank` ascending, so that every eligible rank-1 registrant
        outranks every rank-4 registrant regardless of when either signed; then by
        `priority_flag`, with a flagged registration ahead of an unflagged one; then by
        `demotion_count` ascending, so a registration carrying fewer charged demotions
        ranks ahead of one carrying more; then by that group's own `ordering_policy` key,
        which is `credited_seniority_hours` descending under `SENIORITY` and
        `registered_at` ascending under `FIRST_REGISTERED`; then, as a tie-break, by
        `registered_at` ascending; and finally, as the last tie-break, by `created_at`
        ascending."

        Design: Corner/endpoints/dispatch_order_read_puts_the_higher_priority_group_first
        """
        scene = _two_groups_and_a_long_call(api)
        assert (
            scene["rank_two_registration"]["credited_seniority_hours"]
            == RANK_TWO_HOURS
        )

        order = _dispatch_order(api, scene["job_request"]["id"])

        assert order["top_member_id"] == scene["rank_one"]["id"]
        assert order["top_registration_id"] == scene["rank_one_registration"]["id"]
        assert order["top_list_group_code"] == GROUP_1
        assert order["top_position_number"] == 1
        assert order["top_credited_seniority_hours"] == RANK_ONE_HOURS

    def test_the_issuance_that_follows_selects_exactly_what_the_read_showed(self, api):
        """
        PRD §3.6: "A `LIST_ORDER` referral goes to the top-ranked candidate in the pool
        of §3.2, under the variant the job's `duration_type` selects."

        PRD §3.2: "That read is computed live and stores nothing, and it fails with
        `ERR_NO_ELIGIBLE_REGISTRANT` when the pool is empty, exactly as issuance would."

        Design: Corner/endpoints/dispatch_order_read_puts_the_higher_priority_group_first
        """
        scene = _two_groups_and_a_long_call(api)
        order = _dispatch_order(api, scene["job_request"]["id"])
        assert order["candidate_count"] == 2

        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert referral["member_id"] == scene["rank_one"]["id"]
        assert referral["list_position_at_issue"] == 1
        assert referral["variant_applied"] == VARIANT_STRICT_GROUP_ORDER


def _two_laid_off_journeyworkers(api):
    """
    Two members dispatched to the same never-filled call and laid off at one
    instant, so their recall windows close together.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    recalled = fx.add_journeyworker(
        api, hall["home_local_id"], RECALLED_MEMBER, RECALLED_HOURS
    )
    late = fx.add_journeyworker(api, hall["home_local_id"], LATE_MEMBER, LATE_HOURS)
    fx.sign_book(api, recalled["id"], hall["group_1_id"])
    fx.sign_book(api, late["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=RECALL_JOB_SITE,
        journeyworkers_requested=RECALL_JOURNEYWORKERS,
        apprentices_requested=0,
        expected_duration_days=RECALL_DURATION_DAYS,
        report_at=RECALL_REPORT_AT,
        hourly_rate_cents=RECALL_RATE_CENTS,
    )
    first_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    first_dispatch = fx.accept_referral(api, first_referral["id"], recalled["id"])
    second_referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    second_dispatch = fx.accept_referral(api, second_referral["id"], late["id"])
    fx.set_clock(api, LAYOFF_CLOCK)
    first_laid_off = fx.lay_off(
        api,
        first_dispatch["id"],
        contractor["id"],
        LAYOFF_HOURS,
        LAYOFF_LACK_OF_WORK,
    )
    second_laid_off = fx.lay_off(
        api,
        second_dispatch["id"],
        contractor["id"],
        LAYOFF_HOURS,
        LAYOFF_LACK_OF_WORK,
    )
    return {
        "contractor": contractor,
        "job_request": job_request,
        "recalled": recalled,
        "late": late,
        "first_dispatch": first_dispatch,
        "second_dispatch": second_dispatch,
        "first_laid_off": first_laid_off,
        "second_laid_off": second_laid_off,
    }


def _recall(api, dispatch_id, contractor_id, report_at=NEW_REPORT_AT):
    return api.recall_dispatch(
        dispatch_id,
        f.recall_payload(report_at),
        make_contractor_rep_headers(contractor_id),
    )


class TestRecallHonouredAtTheClosedEdgeOfItsWindow:
    """Inclusive at both ends, and one millisecond past the horizon is out."""

    def test_a_no_fault_layoff_opens_a_seven_day_window_on_both_records(self, api):
        """
        PRD §3.8: "`REDUCTION_IN_FORCE`, `JOB_COMPLETE`, and `LACK_OF_WORK` are all
        no-fault endings: the `status` becomes `LAID_OFF`, `ended_at` is set to the current
        instant, the reported `hours_worked` is recorded, and `recall_window_ends_at` is
        set to the current instant plus 7 days."

        Design: Corner/endpoints/recall_at_the_exact_window_end_succeeds_and_one_millisecond_later_is_closed
        """
        scene = _two_laid_off_journeyworkers(api)

        assert scene["first_laid_off"]["status"] == DISPATCH_LAID_OFF
        assert scene["second_laid_off"]["status"] == DISPATCH_LAID_OFF
        assert_instant_equals(
            scene["first_laid_off"]["recall_window_ends_at"], WINDOW_ENDS_AT
        )
        assert_instant_equals(
            scene["second_laid_off"]["recall_window_ends_at"], WINDOW_ENDS_AT
        )
        assert_instant_equals(
            WINDOW_ENDS_AT, plus_days(LAYOFF_CLOCK, RECALL_WINDOW_DAYS)
        )

    def test_a_recall_at_the_exact_horizon_creates_the_new_working_record(self, api):
        """
        PRD §3.8: "A successful recall leaves the laid-off record exactly where it is —
        that row stays `LAID_OFF` — and creates a **new** `Dispatch` in `WORKING` status
        whose `recall_of_dispatch_id` points back at the laid-off record, whose `start_at`
        is the supplied `report_at`, and whose `job_request_id` and `member_id` are carried
        over unchanged."

        Design: Corner/endpoints/recall_at_the_exact_window_end_succeeds_and_one_millisecond_later_is_closed
        """
        scene = _two_laid_off_journeyworkers(api)
        fx.set_clock(api, WINDOW_ENDS_AT)

        recalled = expect_created(
            _recall(
                api, scene["first_dispatch"]["id"], scene["contractor"]["id"]
            )
        )

        assert recalled["status"] == DISPATCH_WORKING
        assert recalled["recall_of_dispatch_id"] == scene["first_dispatch"]["id"]
        assert recalled["member_id"] == scene["recalled"]["id"]
        assert_instant_equals(recalled["start_at"], NEW_REPORT_AT)

    def test_one_millisecond_past_the_horizon_no_record_is_created(self, api):
        """
        PRD §3.8: "The recall window is the closed interval from the dispatch's `ended_at`
        through its `recall_window_ends_at`, inclusive at both ends; a recall arriving
        strictly after that horizon is refused with `ERR_RECALL_WINDOW_CLOSED`."

        PRD §3.8: "Dispatches may be read individually and listed with filters on
        `member_id`, `referral_id`, `job_request_id`, `recall_of_dispatch_id`, and
        `status`."

        Design: Corner/endpoints/recall_at_the_exact_window_end_succeeds_and_one_millisecond_later_is_closed
        """
        scene = _two_laid_off_journeyworkers(api)
        fx.set_clock(api, ONE_MILLISECOND_LATE)

        response = _recall(
            api, scene["second_dispatch"]["id"], scene["contractor"]["id"]
        )

        expect_error(response, ERR_RECALL_WINDOW_CLOSED)
        _, meta = validate_list(
            api.list_dispatches(
                DISPATCHER,
                {"recall_of_dispatch_id": scene["second_dispatch"]["id"]},
            )
        )
        assert meta["total_count"] == 0


def _hall_ready_for_one_sweep(api):
    """
    Three registrants a month past their signature, one unanswered referral, and
    one member who re-signed in time — with the clock now past every deadline.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    rows = fx.register_journeyworkers(
        api,
        hall["home_local_id"],
        hall["group_1_id"],
        (
            (UNANSWERED_MEMBER, UNANSWERED_HOURS),
            (RENEWING_MEMBER, RENEWING_HOURS),
            (LAPSING_MEMBER, LAPSING_HOURS),
        ),
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=SWEEP_JOB_SITE,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=SWEEP_DURATION_DAYS,
        report_at=SWEEP_REPORT_AT,
        hourly_rate_cents=SWEEP_RATE_CENTS,
    )
    referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    fx.set_clock(api, RESIGN_CLOCK)
    renewed = expect_ok(
        _renew(api, rows[1]["registration"]["id"], make_member_headers(rows[1]["member"]["id"]))
    )
    fx.set_clock(api, SWEEP_CLOCK)
    return {
        "hall": hall,
        "unanswered": rows[0],
        "renewing": rows[1],
        "lapsing": rows[2],
        "job_request": job_request,
        "referral": referral,
        "renewed": renewed,
    }


class TestSweepReportsEachBucketSeparately:
    """One call, five counters, and only the rows that actually qualify.

    The fixed order of the steps is visible in the outcome: the registration step
    one hands back to the book is expired by step three in the very same run.
    """

    def test_the_five_counters_report_their_own_buckets(self, api):
        """
        PRD §3.4: "The sweep reports what it did: `run_at` echoes the instant the run was
        evaluated against, `expired_referral_count` the number of referrals expired in step
        one, `demoted_registration_count` the number of registrations returned to the book
        with a demotion charged, `removed_registration_count` the number removed for a
        third strike, `expired_registration_count` the number expired for a lapsed
        re-sign, and `purged_ledger_entry_count` the number of ledger snapshots purged."

        Design: Corner/endpoints/dispatch_run_sweep_reports_per_bucket_counts_and_skips_current_rows
        """
        scene = _hall_ready_for_one_sweep(api)
        assert_instant_equals(
            scene["referral"]["acceptance_deadline"], ACCEPTANCE_DEADLINE
        )
        assert_instant_equals(scene["renewed"]["renewal_due_at"], MOVED_DUE_AT)

        report = fx.run_sweep(api)

        assert_instant_equals(report["run_at"], SWEEP_CLOCK)
        assert report["expired_referral_count"] == 1
        assert report["demoted_registration_count"] == 1
        assert report["expired_registration_count"] == 2
        assert report["removed_registration_count"] == 0
        assert report["purged_ledger_entry_count"] == 0

    def test_the_unanswered_referral_is_a_strike_and_its_row_leaves_the_book(self, api):
        """
        PRD §3.4: "The ordering of steps one and three has a consequence worth stating
        outright: because referral expiries are processed before renewal expiries, a
        registration that step one returns to `REGISTERED` is itself a candidate for
        renewal expiry in step three of the very same run, and can therefore leave the
        book as `EXPIRED` in the same sweep that brought it back."

        PRD §3.7: "When the housekeeping sweep of §3.4 finds a referral whose
        `acceptance_deadline` has strictly passed, the referral's `status` becomes
        `EXPIRED` and a `REFERRAL_EXPIRED` entry is appended."

        Design: Corner/endpoints/dispatch_run_sweep_reports_per_bucket_counts_and_skips_current_rows
        """
        scene = _hall_ready_for_one_sweep(api)

        fx.run_sweep(api)

        assert fx.read_referral(api, scene["referral"]["id"])["status"] == (
            REFERRAL_EXPIRED
        )
        assert (
            fx.read_member(api, scene["unanswered"]["member"]["id"])[
                "refusal_strike_count"
            ]
            == 1
        )
        registration = fx.read_registration(
            api, scene["unanswered"]["registration"]["id"]
        )
        assert registration["status"] == REGISTRATION_EXPIRED
        assert registration["demotion_count"] == 1
        assert registration["removal_reason"] == REMOVAL_RENEWAL_LAPSED

    def test_the_member_who_re_signed_in_time_is_skipped(self, api):
        """
        PRD §3.4: "Step three expires lapsed registrations: every registration whose
        `status` is `REGISTERED` and whose `renewal_due_at` is strictly earlier than the
        current instant becomes `EXPIRED` with `removal_reason` of `RENEWAL_LAPSED` and a
        null `position_number`, its list is renumbered, and the group's `registered_count`
        is decremented; these are processed in `renewal_due_at` ascending order with
        `created_at` ascending as the tie-break."

        Design: Corner/endpoints/dispatch_run_sweep_reports_per_bucket_counts_and_skips_current_rows
        """
        scene = _hall_ready_for_one_sweep(api)

        fx.run_sweep(api)

        lapsed = fx.read_registration(api, scene["lapsing"]["registration"]["id"])
        assert lapsed["status"] == REGISTRATION_EXPIRED
        assert lapsed["removal_reason"] == REMOVAL_RENEWAL_LAPSED
        assert lapsed["position_number"] is None
        survivor = fx.read_registration(api, scene["renewing"]["registration"]["id"])
        assert survivor["status"] == REGISTRATION_REGISTERED
        assert survivor["removal_reason"] is None


def _a_referral_held_by_somebody_else(api):
    """
    One single-slot call whose referral went to the senior registrant, leaving a
    second registrant with something to complain about.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    holder = fx.add_journeyworker(
        api, hall["home_local_id"], REFERRED_MEMBER, REFERRED_HOURS
    )
    filer = fx.add_journeyworker(
        api, hall["home_local_id"], FILING_MEMBER, FILING_HOURS
    )
    fx.sign_book(api, holder["id"], hall["group_1_id"])
    fx.sign_book(api, filer["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=LINK_JOB_SITE,
        journeyworkers_requested=LINK_JOURNEYWORKERS,
        apprentices_requested=0,
        expected_duration_days=LINK_DURATION_DAYS,
        report_at=LINK_REPORT_AT,
        hourly_rate_cents=LINK_RATE_CENTS,
    )
    referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return {
        "holder": holder,
        "filer": filer,
        "job_request": job_request,
        "referral": referral,
    }


def _file_against(api, referral_id, member_id, narrative):
    return api.create_grievance(
        f.grievance_payload(
            referral_id, claim_type=CLAIM_OUT_OF_ORDER_DISPATCH, narrative=narrative
        ),
        make_member_headers(member_id),
    )


class TestGrievanceLinksTheReferralAndItsFiler:
    """A link row whose target is resolved from the body and whose filer is the header."""

    def test_an_unknown_referral_id_in_the_body_is_a_not_found(self, api):
        """
        PRD §2.6: "Identifiers that arrive in a request body or a query string are checked
        the same way and with the same code family."

        PRD §2.6: "All existence failures carry HTTP 404, and the family of codes is one
        per resource type: `ERR_LOCAL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_LIST_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
        `ERR_JOB_REQUEST_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`,
        `ERR_GRIEVANCE_NOT_FOUND`, and `ERR_LEDGER_ENTRY_NOT_FOUND`."

        Design: Corner/endpoints/grievance_links_the_challenged_referral_and_the_filer
        """
        scene = _a_referral_held_by_somebody_else(api)

        response = _file_against(
            api, NON_EXISTENT_UUID, scene["filer"]["id"], MISSING_NARRATIVE
        )

        expect_error(response, ERR_REFERRAL_NOT_FOUND)

    def test_the_filing_takes_its_grievant_from_the_header_not_the_referral(self, api):
        """
        PRD §3.9: "Either the member or a `BusinessManager` filing on a member's behalf
        may open the grievance, and `grievant_member_id` is always taken from `X-User-ID`
        rather than from the body — which is also why no ownership check is applied here,
        since the whole point of the filing is to challenge somebody else's referral."

        Design: Corner/endpoints/grievance_links_the_challenged_referral_and_the_filer
        """
        scene = _a_referral_held_by_somebody_else(api)
        assert scene["referral"]["member_id"] == scene["holder"]["id"]

        grievance = expect_created(
            _file_against(
                api,
                scene["referral"]["id"],
                scene["filer"]["id"],
                LINK_NARRATIVE,
            )
        )

        assert grievance["referral_id"] == scene["referral"]["id"]
        assert grievance["grievant_member_id"] == scene["filer"]["id"]
        assert grievance["status"] == GRIEVANCE_FILED
        assert_instant_equals(grievance["filed_at"], CLOCK)

    def test_the_link_is_queryable_from_the_referral_side(self, api):
        """
        PRD §3.9: "Grievances may be read individually and listed with filters on
        `referral_id`, `grievant_member_id`, `status`, and `claim_type`."

        Design: Corner/endpoints/grievance_links_the_challenged_referral_and_the_filer
        """
        scene = _a_referral_held_by_somebody_else(api)
        grievance = expect_created(
            _file_against(
                api, scene["referral"]["id"], scene["filer"]["id"], LINK_NARRATIVE
            )
        )

        rows, meta = validate_list(
            api.list_grievances(
                BUSINESS_MANAGER, {"referral_id": scene["referral"]["id"]}
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [grievance["id"]]
