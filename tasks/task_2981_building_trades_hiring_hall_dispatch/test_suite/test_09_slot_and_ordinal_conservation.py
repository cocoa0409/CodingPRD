"""
Two quantities the hall may rearrange but never create or destroy: a job
request's journeyworker commitment, and the block of ordinals a list group hands
out to the registrations standing on it.
"""

from test_helpers import (
    DISPATCHER,
    GROUP_1,
    JOB_REQUEST_OPEN,
    REFERRAL_ISSUED,
    REFERRAL_REFUSED,
    REFERRAL_WITHDRAWN,
    REGISTRATION_REFERRED,
    REGISTRATION_REGISTERED,
    SLOT_JOURNEYWORKER,
    assert_ordinal_block,
    assert_slot_conservation,
    expect_ok,
    find_row,
    fixtures as fx,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The conserved slot commitment ────────────────────────────────────────────

SLOT_JOB_SITE = "Warehouse 12"
SLOT_REPORT_AT = "2026-09-28T07:00:00.000Z"
SLOT_RATE_CENTS = 5150
SLOT_DURATION_DAYS = 35
JOURNEYWORKERS_REQUESTED = 2
DEFERRAL_REASON = "Contractor deferred one slot"

# ─── The conserved ordinal block ──────────────────────────────────────────────

ORDINAL_JOB_SITE = "Transit Yard"
ORDINAL_REPORT_AT = "2026-09-28T07:00:00.000Z"
ORDINAL_RATE_CENTS = 5000
ORDINAL_DURATION_DAYS = 25
ORDINAL_SIGNERS = (("Jo Park", 9000), ("Kai Lin", 8000), ("Lex Ruiz", 7000))


def _two_slot_call(api):
    """Two registrants and one two-journeyworker call that nobody ever accepts."""
    hall = fx.standard_hall(api, clock=CLOCK)
    hal = fx.add_journeyworker(api, hall["home_local_id"], "Hal Reyes", 9000)
    ivy = fx.add_journeyworker(api, hall["home_local_id"], "Ivy Munoz", 8000)
    hal_registration = fx.sign_book(api, hal["id"], hall["group_1_id"])
    ivy_registration = fx.sign_book(api, ivy["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Perch Constructors")
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=SLOT_JOB_SITE,
        journeyworkers_requested=JOURNEYWORKERS_REQUESTED,
        apprentices_requested=0,
        expected_duration_days=SLOT_DURATION_DAYS,
        report_at=SLOT_REPORT_AT,
        hourly_rate_cents=SLOT_RATE_CENTS,
    )
    return {
        "hall": hall,
        "hal": hal,
        "ivy": ivy,
        "hal_registration": hal_registration,
        "ivy_registration": ivy_registration,
        "job_request": job_request,
    }


def _check_conservation(api, job_request_id):
    """Read both sides of the identity at one instant and assert they still sum."""
    job_request = fx.read_job_request(api, job_request_id)
    referrals = fx.referrals_on(api, job_request_id)
    assert_slot_conservation(
        job_request, referrals, SLOT_JOURNEYWORKER, JOURNEYWORKERS_REQUESTED
    )
    assert job_request["accepted_journeyworker_count"] == 0
    assert job_request["status"] == JOB_REQUEST_OPEN
    return job_request, referrals


def _three_signers_and_a_single_call(api):
    """Three registrations numbered one to three, and one single-slot long call."""
    hall = fx.standard_hall(api, clock=CLOCK)
    rows = fx.register_journeyworkers(
        api, hall["home_local_id"], hall["group_1_id"], ORDINAL_SIGNERS
    )
    contractor = fx.add_contractor(api, name="Ridgeway Mechanical")
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=ORDINAL_JOB_SITE,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=ORDINAL_DURATION_DAYS,
        report_at=ORDINAL_REPORT_AT,
        hourly_rate_cents=ORDINAL_RATE_CENTS,
    )
    return {"hall": hall, "rows": rows, "job_request": job_request}


def _book(api, list_id):
    """The numbered book: every registration still standing on the list."""
    return fx.registrations_on(api, list_id, status=REGISTRATION_REGISTERED)


class TestJourneyworkerSlotCommitmentConserved:
    """Open slots plus committed referrals always come to the headcount asked for."""

    def test_the_identity_holds_from_intake_through_the_second_issuance(self, api):
        """
        PRD §3.5: "Thereafter `open_journeyworker_slots` is always the journeyworkers
        requested minus the number of journeyworker referrals whose `status` is
        `ISSUED` or `ACCEPTED`, and `open_apprentice_slots` is the apprentices
        requested minus the number of apprentice referrals whose `status` is `ISSUED`
        or `ACCEPTED`; slots are reserved at issuance, not at acceptance."

        Design: Difficulty/compensating_invariant/journeyworker_slot_commitment_conserved_across_withdrawal
        """
        scene = _two_slot_call(api)

        at_intake, _ = _check_conservation(api, scene["job_request"]["id"])
        assert at_intake["open_journeyworker_slots"] == 2

        fx.issue_referral(api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER)
        after_one, _ = _check_conservation(api, scene["job_request"]["id"])
        assert after_one["open_journeyworker_slots"] == 1

        fx.issue_referral(api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER)
        after_two, referrals = _check_conservation(api, scene["job_request"]["id"])
        assert after_two["open_journeyworker_slots"] == 0
        assert len(referrals) == 2

    def test_a_withdrawal_restores_exactly_the_slot_it_releases(self, api):
        """
        PRD §3.7: "The referral's `status` becomes `WITHDRAWN`, and the registration
        returns from `REFERRED` to `REGISTERED` with its `registered_at`,
        `credited_seniority_hours`, `demotion_count`, and `priority_flag` all
        unchanged, reoccupying its pre-referral ordinal; the list is renumbered, the
        group's `registered_count` is incremented by 1, the matching open-slot count
        on the request is restored, any named-call or special-skill allowance the
        referral consumed is released, and the request's `version` increments by 1."

        Design: Difficulty/compensating_invariant/journeyworker_slot_commitment_conserved_across_withdrawal
        """
        scene = _two_slot_call(api)
        first = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.issue_referral(api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER)

        withdrawn = fx.withdraw_referral(api, first["id"], DEFERRAL_REASON)

        assert withdrawn["status"] == REFERRAL_WITHDRAWN
        after_withdrawal, _ = _check_conservation(api, scene["job_request"]["id"])
        assert after_withdrawal["open_journeyworker_slots"] == 1
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 1

    def test_reissuing_to_the_restored_registration_recommits_the_slot(self, api):
        """
        PRD §3.5: "On the request side, the matching open-slot counter is decremented
        to reserve the slot, the counters are recomputed, and the request's `version`
        increments by 1 — while its `status` is untouched, because status follows
        acceptances."

        Design: Difficulty/compensating_invariant/journeyworker_slot_commitment_conserved_across_withdrawal
        """
        scene = _two_slot_call(api)
        first = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.issue_referral(api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER)
        fx.withdraw_referral(api, first["id"], DEFERRAL_REASON)

        reissued = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        assert reissued["registration_id"] == scene["hal_registration"]["id"]
        after_reissue, referrals = _check_conservation(api, scene["job_request"]["id"])
        assert after_reissue["open_journeyworker_slots"] == 0
        assert len(referrals) == 3

    def test_the_referral_list_filters_down_to_the_two_live_commitments(self, api):
        """
        PRD §3.6: "Referrals may be read individually and listed with filters on
        `job_request_id`, `registration_id`, `member_id`, `status`, and
        `referral_kind`."

        Design: Difficulty/compensating_invariant/journeyworker_slot_commitment_conserved_across_withdrawal
        """
        scene = _two_slot_call(api)
        first = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        second = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.withdraw_referral(api, first["id"], DEFERRAL_REASON)
        third = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        live = fx.referrals_on(api, scene["job_request"]["id"])
        outstanding = [row for row in live if row["status"] == REFERRAL_ISSUED]

        assert {row["id"] for row in outstanding} == {second["id"], third["id"]}
        assert find_row(live, "id", first["id"])["status"] == REFERRAL_WITHDRAWN
        assert find_row(live, "id", third["id"])["status"] == REFERRAL_ISSUED


class TestListOrdinalBlockConserved:
    """The ordinals stay the block one through registered_count, only permuted."""

    def test_three_signers_take_the_first_three_ordinals_in_signing_order(self, api):
        """
        PRD §3.3: "The new registration's `position_number` is the preserved
        predecessor's ordinal when preservation applies, and otherwise the group's
        `registered_count` plus one — the tail of the queue."

        Design: Difficulty/compensating_invariant/list_ordinal_block_conserved_across_demotion
        """
        scene = _three_signers_and_a_single_call(api)

        rows = _book(api, scene["hall"]["group_1_id"])
        assert assert_ordinal_block(rows) == [1, 2, 3]
        positions = fx.positions_by_member(rows)
        assert [positions[row["member"]["id"]] for row in scene["rows"]] == [1, 2, 3]
        group = fx.read_list_group(api, scene["hall"]["group_1_id"])
        assert group["registered_count"] == 3
        assert group["group_code"] == GROUP_1

    def test_referring_the_head_of_the_book_closes_the_gap_behind_it(self, api):
        """
        PRD §3.4: "Step three expires lapsed registrations: every registration whose
        `status` is `REGISTERED` and whose `renewal_due_at` is strictly earlier than
        the current instant becomes `EXPIRED` with `removal_reason` of
        `RENEWAL_LAPSED` and a null `position_number`, its list is renumbered, and the
        group's `registered_count` is decremented; these are processed in
        `renewal_due_at` ascending order with `created_at` ascending as the
        tie-break."

        Design: Difficulty/compensating_invariant/list_ordinal_block_conserved_across_demotion
        """
        scene = _three_signers_and_a_single_call(api)
        head = scene["rows"][0]

        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        assert referral["registration_id"] == head["registration"]["id"]
        assert referral["list_position_at_issue"] == 1

        rows = _book(api, scene["hall"]["group_1_id"])
        assert assert_ordinal_block(rows) == [1, 2]
        positions = fx.positions_by_member(rows)
        assert positions[scene["rows"][1]["member"]["id"]] == 1
        assert positions[scene["rows"][2]["member"]["id"]] == 2
        assert (
            fx.read_registration(api, head["registration"]["id"])["position_number"]
            is None
        )
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 2

    def test_the_demoted_registration_reenters_the_block_at_its_tail(self, api):
        """
        PRD §3.4: "The ordering of steps one and three has a consequence worth stating
        outright: because referral expiries are processed before renewal expiries, a
        registration that step one returns to `REGISTERED` is itself a candidate for
        renewal expiry in step three of the very same run, and can therefore leave the
        book as `EXPIRED` in the same sweep that brought it back."

        Design: Difficulty/compensating_invariant/list_ordinal_block_conserved_across_demotion
        """
        scene = _three_signers_and_a_single_call(api)
        head = scene["rows"][0]
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )

        refused = fx.refuse_referral(api, referral["id"], head["member"]["id"])

        assert refused["status"] == REFERRAL_REFUSED
        rows = _book(api, scene["hall"]["group_1_id"])
        assert assert_ordinal_block(rows) == [1, 2, 3]
        positions = fx.positions_by_member(rows)
        assert positions[head["member"]["id"]] == 3
        assert positions[scene["rows"][1]["member"]["id"]] == 1
        assert positions[scene["rows"][2]["member"]["id"]] == 2
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 3

    def test_the_block_is_permuted_rather_than_renumbered_away(self, api):
        """
        PRD §3.6: "On the list side, the selected registration moves from `REGISTERED`
        to `REFERRED`, its own `position_number` becomes null, and every remaining
        `REGISTERED` registration on the same list is renumbered from 1 through the
        group's `registered_count` under the strict-group-order intra-list key; the
        group's `registered_count` is decremented by 1."

        Design: Difficulty/compensating_invariant/list_ordinal_block_conserved_across_demotion
        """
        scene = _three_signers_and_a_single_call(api)
        head = scene["rows"][0]
        before = fx.positions_by_member(_book(api, scene["hall"]["group_1_id"]))

        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        referred = fx.read_registration(api, head["registration"]["id"])
        assert referred["status"] == REGISTRATION_REFERRED
        fx.refuse_referral(api, referral["id"], head["member"]["id"])

        after = fx.positions_by_member(_book(api, scene["hall"]["group_1_id"]))

        assert sorted(before.values()) == sorted(after.values()) == [1, 2, 3]
        assert set(before) == set(after)
        assert after[head["member"]["id"]] != before[head["member"]["id"]]
        assert sum(after.values()) == sum(before.values()) == 6

    def test_the_returned_registration_carries_one_charged_demotion(self, api):
        """
        PRD §3.3: "In either case `last_renewed_at` is set to the current instant and
        is never inherited from a predecessor, and `renewal_due_at` is computed as
        `last_renewed_at` plus 30 days."

        Design: Difficulty/compensating_invariant/list_ordinal_block_conserved_across_demotion
        """
        scene = _three_signers_and_a_single_call(api)
        head = scene["rows"][0]
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        fx.refuse_referral(api, referral["id"], head["member"]["id"])

        returned = expect_ok(
            api.get_registration(head["registration"]["id"], DISPATCHER)
        )

        assert returned["status"] == REGISTRATION_REGISTERED
        assert returned["demotion_count"] == 1
        assert returned["position_number"] == 3
