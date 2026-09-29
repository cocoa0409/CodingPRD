"""
The two cross-cutting guarantees, exercised end to end: the version pin that is
the only thing standing between a repeatable write and a double-issue, and the
promise that an acceptance's every declared consequence is already in place on
the reads that follow it.
"""

from test_helpers import (
    DISPATCHER,
    DISPATCH_WORKING,
    ERR_STALE_JOB_REQUEST_VERSION,
    EVENT_REFERRAL_ACCEPTED,
    HALL_ADMIN,
    JOB_REQUEST_OPEN,
    JOB_REQUEST_PARTIALLY_FILLED,
    REFERRAL_ACCEPTED,
    REFERRAL_ISSUED,
    REGISTRATION_DISPATCHED_OUT,
    REGISTRATION_REFERRED,
    SLOT_JOURNEYWORKER,
    assert_instant_equals,
    expect_created,
    expect_error,
    factories as f,
    fixtures as fx,
    make_member_headers,
    validate_list,
)

CLOCK = "2026-09-01T00:00:00.000Z"
REPORT_AT = "2026-09-25T07:00:00.000Z"

# ─── The version-pinned issuance (§2.8) ───────────────────────────────────────

OCC_SIGNERS = (("Tova Lindgren", 9000), ("Uri Peled", 8000), ("Vale Moreno", 7000))
OCC_JOB_SITE = "Unit 3 Outage"
OCC_JOURNEYWORKERS = 3
OCC_DURATION_DAYS = 30
OCC_RATE_CENTS = 5000

# ─── The immediately visible acceptance (§3.7) ────────────────────────────────

ACCEPT_SIGNERS = (("Wren Castellan", 9000), ("Yuki Ferrante", 8000))
ACCEPT_JOB_SITE = "Unit 4 Outage"
ACCEPT_JOURNEYWORKERS = 2
ACCEPT_DURATION_DAYS = 30
ACCEPT_RATE_CENTS = 5000


def _three_ranked_registrants_and_a_three_slot_call(api):
    """
    Three journeyworkers on the seniority-ordered rank-1 group and one long call
    for three of them, so a second issuance is legitimately open.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api, hall["home_local_id"], hall["group_1_id"], list(OCC_SIGNERS)
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=OCC_JOB_SITE,
        journeyworkers_requested=OCC_JOURNEYWORKERS,
        expected_duration_days=OCC_DURATION_DAYS,
        report_at=REPORT_AT,
        hourly_rate_cents=OCC_RATE_CENTS,
    )
    return {
        "hall": hall,
        "signed": signed,
        "contractor": contractor,
        "job_request": job_request,
    }


def _issue_pinned_to(api, job_request_id, version):
    """One journeyworker issuance carrying whatever version the caller pins."""
    return api.create_referral(
        job_request_id,
        f.referral_payload(version, slot_kind=SLOT_JOURNEYWORKER),
        DISPATCHER,
    )


class TestTheVersionPinIsTheOnlyGuardOnARepeatableIssuance:
    """
    Nothing about a three-slot call's state stops a second issuance, so the
    replayed snapshot is refused by the version pin alone — and the refusal
    leaves the request exactly as the first issuance left it.
    """

    def test_the_first_issuance_advances_the_version_and_reserves_a_slot(self, api):
        """
        The pinned version is the one the contractor's intake produced, and the write
        that consumes it both reserves a slot and moves the version on.

        PRD §3.5: "Thereafter `open_journeyworker_slots` is always the journeyworkers
        requested minus the number of journeyworker referrals whose `status` is `ISSUED`
        or `ACCEPTED`, and `open_apprentice_slots` is the apprentices requested minus the
        number of apprentice referrals whose `status` is `ISSUED` or `ACCEPTED`; slots are
        reserved at issuance, not at acceptance."

        Design: Corner/cross_cutting_complexity_layers/stale_job_request_version_is_rejected_and_the_refreshed_version_succeeds
        """
        scene = _three_ranked_registrants_and_a_three_slot_call(api)
        assert scene["job_request"]["version"] == 1
        assert scene["job_request"]["open_journeyworker_slots"] == OCC_JOURNEYWORKERS

        issued = expect_created(
            _issue_pinned_to(api, scene["job_request"]["id"], 1)
        )

        assert issued["member_id"] == scene["signed"][0]["member"]["id"]
        assert issued["status"] == REFERRAL_ISSUED

        after = fx.read_job_request(api, scene["job_request"]["id"])
        assert after["version"] == 2
        assert after["open_journeyworker_slots"] == OCC_JOURNEYWORKERS - 1
        assert after["status"] == JOB_REQUEST_OPEN

    def test_replaying_the_consumed_version_is_refused_and_writes_nothing(self, api):
        """
        The same body that succeeded a moment ago is now stale, and the 412 leaves the
        version, the reserved slot and the referral count all untouched.

        PRD §2.8: "If that value does not equal the job request's current `version` —
        because any other writer has advanced it since the client last read the request —
        the issuance is rejected with `ERR_STALE_JOB_REQUEST_VERSION` and HTTP 412, and
        nothing is written."

        Design: Corner/cross_cutting_complexity_layers/stale_job_request_version_is_rejected_and_the_refreshed_version_succeeds
        """
        scene = _three_ranked_registrants_and_a_three_slot_call(api)
        first = expect_created(_issue_pinned_to(api, scene["job_request"]["id"], 1))

        replayed = _issue_pinned_to(api, scene["job_request"]["id"], 1)
        expect_error(replayed, ERR_STALE_JOB_REQUEST_VERSION, status=412)

        after = fx.read_job_request(api, scene["job_request"]["id"])
        assert after["version"] == 2
        assert after["open_journeyworker_slots"] == OCC_JOURNEYWORKERS - 1
        rows = fx.referrals_on(api, scene["job_request"]["id"])
        assert [row["id"] for row in rows] == [first["id"]]

    def test_the_refreshed_version_issues_to_the_next_registrant(self, api):
        """
        Re-reading the request is all the dispatcher has to do: the refreshed pin issues,
        and it issues to the member the first referral left at the head of the list.

        PRD §2.8: "Because so many operations bump a job request's `version` — acceptance,
        refusal, withdrawal, expiry during the sweep, suspension, reinstatement,
        cancellation, and each prior issuance — a dispatcher working a large call must
        re-read the request between issuances."

        Design: Corner/cross_cutting_complexity_layers/stale_job_request_version_is_rejected_and_the_refreshed_version_succeeds
        """
        scene = _three_ranked_registrants_and_a_three_slot_call(api)
        first = expect_created(_issue_pinned_to(api, scene["job_request"]["id"], 1))
        expect_error(
            _issue_pinned_to(api, scene["job_request"]["id"], 1),
            ERR_STALE_JOB_REQUEST_VERSION,
            status=412,
        )

        refreshed = fx.read_job_request(api, scene["job_request"]["id"])
        second = expect_created(
            _issue_pinned_to(api, scene["job_request"]["id"], refreshed["version"])
        )

        assert second["member_id"] == scene["signed"][1]["member"]["id"]
        final = fx.read_job_request(api, scene["job_request"]["id"])
        assert final["version"] == 3
        assert final["open_journeyworker_slots"] == OCC_JOURNEYWORKERS - 2
        rows, meta = validate_list(
            api.list_referrals(DISPATCHER, {"job_request_id": scene["job_request"]["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


def _one_issued_referral_on_a_two_slot_call(api):
    """
    Two journeyworkers signed on the rank-1 group and a two-journeyworker long
    call whose first list-order referral is outstanding, waiting to be answered.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api, hall["home_local_id"], hall["group_1_id"], list(ACCEPT_SIGNERS)
    )
    group_before = fx.read_list_group(api, hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=ACCEPT_JOB_SITE,
        journeyworkers_requested=ACCEPT_JOURNEYWORKERS,
        expected_duration_days=ACCEPT_DURATION_DAYS,
        report_at=REPORT_AT,
        hourly_rate_cents=ACCEPT_RATE_CENTS,
    )
    referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    return {
        "hall": hall,
        "taker": signed[0]["member"],
        "taker_registration": signed[0]["registration"],
        "waiting": signed[1]["member"],
        "group_before": group_before,
        "contractor": contractor,
        "job_request": job_request,
        "referral": referral,
    }


def _accept(api, scene):
    """The member answers their own outstanding referral."""
    return api.accept_referral(
        scene["referral"]["id"], make_member_headers(scene["taker"]["id"])
    )


class TestAnAcceptanceIsVisibleInEveryPlaceAtOnce:
    """
    One accept, then a plain read of each record it touched — the referral, the
    registration, the list group, the request and the dispatch record — with no
    settling step anywhere between the write and the reads.
    """

    def test_the_accept_response_already_carries_the_finished_dispatch(self, api):
        """
        The employment record comes back from the accept call itself, complete with the
        reporting instant it inherits and the four fields that begin null.

        PRD §3.7: "**Accepting** moves the referral from `ISSUED` to `ACCEPTED` and the
        registration from `REFERRED` to the terminal `DISPATCHED_OUT`, and it creates the
        employment record: a `Dispatch` in `WORKING` status whose `start_at` is the job
        request's `report_at`, whose `hours_worked` begins at 0, and whose `ended_at`,
        `layoff_reason`, `recall_of_dispatch_id`, and `recall_window_ends_at` all begin
        null."

        Design: Corner/consistency_model/every_effect_of_an_acceptance_is_visible_immediately
        """
        scene = _one_issued_referral_on_a_two_slot_call(api)

        dispatch = expect_created(_accept(api, scene))

        assert dispatch["status"] == DISPATCH_WORKING
        assert dispatch["member_id"] == scene["taker"]["id"]
        assert dispatch["job_request_id"] == scene["job_request"]["id"]
        assert dispatch["referral_id"] == scene["referral"]["id"]
        assert_instant_equals(dispatch["start_at"], REPORT_AT, "start_at")
        assert dispatch["hours_worked"] == 0
        assert dispatch["ended_at"] is None
        assert dispatch["layoff_reason"] is None
        assert dispatch["recall_of_dispatch_id"] is None
        assert dispatch["recall_window_ends_at"] is None

    def test_the_referral_and_the_registration_read_back_already_moved(self, api):
        """
        Both sides of the transition are settled on the very next reads: the offer is
        accepted and the registration has gone terminal.

        PRD §3.7: "**Accepting** moves the referral from `ISSUED` to `ACCEPTED` and the
        registration from `REFERRED` to the terminal `DISPATCHED_OUT`, and it creates the
        employment record: a `Dispatch` in `WORKING` status whose `start_at` is the job
        request's `report_at`, whose `hours_worked` begins at 0, and whose `ended_at`,
        `layoff_reason`, `recall_of_dispatch_id`, and `recall_window_ends_at` all begin
        null."

        Design: Corner/consistency_model/every_effect_of_an_acceptance_is_visible_immediately
        """
        scene = _one_issued_referral_on_a_two_slot_call(api)
        assert scene["referral"]["status"] == REFERRAL_ISSUED
        assert (
            fx.read_registration(api, scene["taker_registration"]["id"])["status"]
            == REGISTRATION_REFERRED
        )

        expect_created(_accept(api, scene))

        assert fx.read_referral(api, scene["referral"]["id"])["status"] == (
            REFERRAL_ACCEPTED
        )
        assert (
            fx.read_registration(api, scene["taker_registration"]["id"])["status"]
            == REGISTRATION_DISPATCHED_OUT
        )

    def test_the_group_count_reads_back_without_the_dispatched_member(self, api):
        """
        The list group's computed headcount, read straight after the acceptance, counts
        only the member still waiting.

        PRD §3.2: "A group's `registered_count` is computed as the number of registrations
        currently on it whose `status` is `REGISTERED`."

        Design: Corner/consistency_model/every_effect_of_an_acceptance_is_visible_immediately
        """
        scene = _one_issued_referral_on_a_two_slot_call(api)
        assert scene["group_before"]["registered_count"] == len(ACCEPT_SIGNERS)

        expect_created(_accept(api, scene))

        group_after = fx.read_list_group(api, scene["hall"]["group_1_id"])
        assert group_after["registered_count"] == 1
        remaining = fx.registrations_on(
            api, scene["hall"]["group_1_id"], status="REGISTERED"
        )
        assert [row["member_id"] for row in remaining] == [scene["waiting"]["id"]]

    def test_the_request_counters_and_status_are_already_re_derived(self, api):
        """
        The parent request needs no second look: its acceptance count, its open slots, its
        derived status and its version have all moved by the time the read returns.

        PRD §3.7: "And on the request side, the matching acceptance counter is incremented,
        `max_apprentices_allowed` is re-derived from the new accepted journeyworker count,
        the open-slot counters are recomputed, the group's `registered_count` is
        decremented, the request's `status` is re-derived from the acceptance counts, and
        the request's `version` increments by 1."

        PRD §3.5: "When an acceptance leaves the accepted headcount — journeyworkers plus
        apprentices — greater than zero but still short of the total requested, an `OPEN`
        request advances to `PARTIALLY_FILLED`."

        Design: Corner/consistency_model/every_effect_of_an_acceptance_is_visible_immediately
        """
        scene = _one_issued_referral_on_a_two_slot_call(api)
        before = fx.read_job_request(api, scene["job_request"]["id"])
        assert before["version"] == 2
        assert before["accepted_journeyworker_count"] == 0
        assert before["status"] == JOB_REQUEST_OPEN

        expect_created(_accept(api, scene))

        after = fx.read_job_request(api, scene["job_request"]["id"])
        assert after["accepted_journeyworker_count"] == 1
        assert after["open_journeyworker_slots"] == 1
        assert after["status"] == JOB_REQUEST_PARTIALLY_FILLED
        assert after["version"] == 3

    def test_the_audit_row_is_written_in_the_same_breath(self, api):
        """
        The dispatch record carries the acceptance at once, stamped with the instant the
        event fired rather than with a later settling time.

        PRD §3.7: "A `REFERRAL_ACCEPTED` entry is appended to the dispatch record."

        PRD §2.10: "Every consequential event in the hall appends a row to an append-only
        dispatch record: a retention-ledger entry carrying an `event_code`, the `member_id`
        the record is about, an optional `referral_id`, the instant it fired in
        `recorded_at`, a computed `retention_until` horizon, a `purge_state`, a
        `snapshot_json` payload holding the ranked candidate list and decision inputs that
        were live at the time, and an `hours_delta` that is zero on every event except a
        make-whole credit."

        Design: Corner/consistency_model/every_effect_of_an_acceptance_is_visible_immediately
        """
        scene = _one_issued_referral_on_a_two_slot_call(api)

        expect_created(_accept(api, scene))

        rows, meta = validate_list(
            api.list_ledger_entries(
                HALL_ADMIN,
                {
                    "referral_id": scene["referral"]["id"],
                    "event_code": EVENT_REFERRAL_ACCEPTED,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["member_id"] == scene["taker"]["id"]
        assert_instant_equals(rows[0]["recorded_at"], CLOCK, "recorded_at")
        assert rows[0]["hours_delta"] == 0
