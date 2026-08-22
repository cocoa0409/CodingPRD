"""Referral intake, the revision cycle, adjudication and the quota identity."""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    allocate,
    create_agency,
    create_approved_referral,
    create_client,
    create_referral,
    issue_voucher,
    list_waitlist,
    make_case_manager_headers,
    review_payload,
    review_referral,
    run_cycle,
    set_clock,
    setup_agency_and_household,
    setup_suspended_agency,
    submit_referral,
    validate_error,
    validate_success,
    voucher_line_payload,
)
from test_helpers.assertions import assert_quota_conservation, assert_referral


def _referral_through_two_revision_rounds():
    """Submit / return three times so revision_count reaches 2 and the referral
    sits in RETURNED, the state the third resubmission attacks."""
    set_clock("2026-08-04T09:00:00Z")
    base = setup_agency_and_household(
        agency_county="CENTRAL", quota=5, household_size=4,
        client_county="CENTRAL", agency_name="Lakeside Neighbors",
    )
    agency_id = base["agency"]["id"]
    referral = create_referral(
        agency_id, base["client"]["id"], requested_categories=["BED"],
        urgency="ROUTINE", home_visit_completed=False,
    )
    lap0 = submit_referral(referral["id"], agency_id)
    review_referral(referral["id"], "RETURN", "Missing home visit")
    lap1 = submit_referral(referral["id"], agency_id)
    review_referral(referral["id"], "RETURN", "Category list still wrong")
    lap2 = submit_referral(referral["id"], agency_id)
    review_referral(referral["id"], "RETURN", "Final return")
    return {
        "agency": base["agency"], "client": base["client"], "referral": referral,
        "lap0": lap0, "lap1": lap1, "lap2": lap2,
    }


def _waitlisted_priority_scenario():
    """A PRIORITY referral whose voucher finds an empty warehouse, so its single
    BED line lands on the waitlist with tenure still at zero."""
    set_clock("2026-08-04T09:00:00Z")
    base = setup_agency_and_household(
        agency_county="CENTRAL", quota=5, household_size=4,
        client_county="CENTRAL", agency_name="Hillcrest Outreach",
    )
    agency_id = base["agency"]["id"]
    referral = create_referral(agency_id, base["client"]["id"],
                               requested_categories=["BED"], urgency="PRIORITY")
    submitted = submit_referral(referral["id"], agency_id)
    approved = review_referral(referral["id"], "APPROVE")
    voucher = issue_voucher(agency_id, referral["id"],
                            [voucher_line_payload("BED", 1, "B")])
    allocate(voucher["id"], voucher["version"])
    entries = list_waitlist(client_id=base["client"]["id"], status="WAITING")
    base.update({
        "referral": approved, "submitted": submitted, "voucher": voucher,
        "waitlist": entries,
    })
    return base


# ─── Difficulty: the SUBMITTED -> RETURNED -> SUBMITTED revision cycle ──

def test_each_revision_round_raises_the_count_and_shaves_six_points(api):
    """PRD §3.2: "A revision round raises `revision_count` by 1, then recomputes
    `priority_score` with the intake variant — and because the raised revision
    count feeds the penalty term, each round lowers the score by six points."
    PRD §3.2: "Urgency contributes 10 points for `ROUTINE`, 25 for `PRIORITY`,
    and 40 for `EMERGENCY`. Household size contributes 5 points per person,
    counting at most six people even in a larger household — so a household of
    nine contributes 30 points, the same as a household of six."
    PRD §3.2: "In the **intake variant**, written to `Referral.priority_score`
    when a referral is submitted (including every revision round), the tenure
    input is zero — the queue clock has not started — and the strike weight is 8
    points per strike."

    Design: Difficulty/non_linear_state_machine/referral_submitted_returned_submitted_revision_cycle
    """
    scenario = _referral_through_two_revision_rounds()

    assert scenario["lap0"]["priority_score"] == pytest.approx(30.0, abs=0.01), (
        "ROUTINE 10 + four people at 5 points each = 30.0 on the first submission"
    )
    assert scenario["lap1"]["revision_count"] == 1
    assert scenario["lap1"]["priority_score"] == pytest.approx(24.0, abs=0.01), (
        "one revision round subtracts six points"
    )
    assert scenario["lap2"]["revision_count"] == 2
    assert scenario["lap2"]["priority_score"] == pytest.approx(18.0, abs=0.01), (
        "two revision rounds subtract twelve points"
    )

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert_referral(referral_now)
    assert referral_now["status"] == "RETURNED"
    assert referral_now["revision_count"] == 2
    assert referral_now["priority_score"] == pytest.approx(18.0, abs=0.01)


def test_third_resubmission_of_a_returned_referral_hits_the_revision_limit(api):
    """PRD §3.2: "A third resubmission attempt, where `revision_count` already
    equals 2, is rejected with `ERR_REVISION_LIMIT_REACHED`."
    PRD §3.2: "That edge requires the referral to be in `RETURNED`, requires
    `revision_count` to be strictly less than 2, and requires the same household
    and agency conditions as a first submission: household `status` `ACTIVE`,
    household `bed_bug_status` not `CONFIRMED`, `bed_bug_attestation` true,
    agency `standing` not `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/referral_submitted_returned_submitted_revision_cycle
    """
    scenario = _referral_through_two_revision_rounds()
    agency_id = scenario["agency"]["id"]

    response = api.submit_referral(
        scenario["referral"]["id"], make_case_manager_headers(agency_id)
    )
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["status"] == "RETURNED", "the refused round leaves the state"
    assert referral_now["revision_count"] == 2, "the refused round adds no revision"
    assert referral_now["priority_score"] == pytest.approx(18.0, abs=0.01)


# ─── Difficulty: approval gated by the agency's quota row ──────────────

def test_approval_is_refused_once_the_agency_quota_is_spent(api):
    """PRD §3.2: "An `APPROVE` decision moves the referral `SUBMITTED →
    APPROVED`. It requires the referral to be in `SUBMITTED`, requires the
    agency's `standing` not to be `SUSPENDED`, requires `quota_used` to be
    strictly less than `quarterly_voucher_quota` (otherwise
    `ERR_AGENCY_QUOTA_EXHAUSTED`), and requires the household's `bed_bug_status`
    not to be `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/referral_approval_gated_by_partner_agency_quota_state
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Ridgeline Neighborhood Trust", county="CENTRAL",
                           quarterly_voucher_quota=1)
    household_a = create_client(agency["id"], household_size=2, county="CENTRAL")
    household_b = create_client(agency["id"], household_size=5, county="CENTRAL",
                                has_infant=True)

    create_approved_referral(agency["id"], household_a["id"],
                             requested_categories=["BED"])
    referral_b = create_referral(agency["id"], household_b["id"],
                                 requested_categories=["CRIB"], urgency="EMERGENCY")
    submit_referral(referral_b["id"], agency["id"])

    response = api.review_referral(referral_b["id"], review_payload("APPROVE"), ADMIN)
    validate_error(response, ApiErrorId.ERR_AGENCY_QUOTA_EXHAUSTED.value, 409)


def test_quota_exhausted_approval_stamps_nothing_on_the_referral(api):
    """PRD §3.2: "Approval stamps `approved_at` with the current instant and
    `expires_at` with that instant plus 45 days, captures the agency's current
    `quota_epoch` into the referral's `approved_epoch`, raises the agency's
    `quota_used` by 1, and bumps both the referral's and the agency's `version`
    by 1."
    PRD §2.10: "`PartnerAgency.quota_used` must always equal the number of that
    agency's referrals whose `status` is `APPROVED` or `FULFILLED` and whose
    `approved_epoch` equals the agency's current `quota_epoch`."

    Design: Difficulty/cross_entity_state_dependency/referral_approval_gated_by_partner_agency_quota_state
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Ridgeline Neighborhood Trust", county="CENTRAL",
                           quarterly_voucher_quota=1)
    household_a = create_client(agency["id"], household_size=2, county="CENTRAL")
    household_b = create_client(agency["id"], household_size=5, county="CENTRAL",
                                has_infant=True)

    referral_a = create_approved_referral(agency["id"], household_a["id"],
                                          requested_categories=["BED"])
    referral_b = create_referral(agency["id"], household_b["id"],
                                 requested_categories=["CRIB"], urgency="EMERGENCY")
    submit_referral(referral_b["id"], agency["id"])

    api.review_referral(referral_b["id"], review_payload("APPROVE"), ADMIN)

    referral_b_now = validate_success(api.get_referral(referral_b["id"], ADMIN))
    assert referral_b_now["status"] == "SUBMITTED", "the refused approval keeps the state"
    assert referral_b_now["approved_at"] is None, "no approval instant is stamped"
    assert referral_b_now["approved_epoch"] is None, "no quota epoch is captured"

    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == 1, "the spent slot count does not move"
    referral_a_now = validate_success(api.get_referral(referral_a["id"], ADMIN))
    assert_quota_conservation(agency_now, [referral_a_now, referral_b_now])


# ─── Difficulty: state gate ahead of the fiscal quota gate ─────────────

def test_state_gate_outranks_the_quota_gate_on_referral_review(api):
    """PRD §2.9: "When a request would fail several checks at once, exactly one
    identifier comes back, and which one is fixed. Checks are evaluated top to
    bottom in the order below and the first failure wins."
    PRD §2.9: "11. The target resource is in a state that has an outgoing
    transition for this trigger — otherwise one of `ERR_REFERRAL_NOT_SUBMITTED`,
    `ERR_REFERRAL_NOT_APPROVED`, `ERR_VOUCHER_INVALID_STATE`,
    `ERR_FEE_STATE_INVALID`, `ERR_OFFER_INVALID_STATE`, `ERR_RUN_INVALID_STATE`,
    `ERR_STOP_INVALID_STATE` or `ERR_CREW_ASSIGNMENT_INVALID_STATE` (409).
    Applies to every action endpoint."
    PRD §2.9: "28. The agency's `quota_used` is strictly less than its
    `quarterly_voucher_quota` — otherwise `ERR_AGENCY_QUOTA_EXHAUSTED` (409), on
    referral approval (the approve decision only)."

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_fiscal_quota_check_on_referral_review
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Quarry Road Partners", county="CENTRAL",
                           quarterly_voucher_quota=1)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")
    referral = create_approved_referral(agency["id"], household["id"],
                                        requested_categories=["BED"])

    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == agency_now["quarterly_voucher_quota"], (
        "the quota is fully consumed, so both gates would fail"
    )

    response = api.review_referral(referral["id"], review_payload("APPROVE"), ADMIN)
    validate_error(response, ApiErrorId.ERR_REFERRAL_NOT_SUBMITTED.value, 409)


def test_refused_re_review_of_an_approved_referral_mutates_nothing(api):
    """PRD §3.2: "Attempting a review from a status that has no matching
    outgoing edge is rejected with `ERR_REFERRAL_NOT_SUBMITTED`."
    PRD §2.10: "Approving a referral is the forward action and raises
    `quota_used` by 1 while stamping `approved_epoch`; expiring an approved
    referral in the operational cycle is the compensating action and lowers
    `quota_used` by 1."

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_fiscal_quota_check_on_referral_review
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Quarry Road Partners", county="CENTRAL",
                           quarterly_voucher_quota=1)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")
    referral = create_approved_referral(agency["id"], household["id"],
                                        requested_categories=["BED"])

    api.review_referral(referral["id"], review_payload("APPROVE"), ADMIN)

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "APPROVED", "the refused review leaves the state"

    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == 1, "the refused review consumes no second slot"
    assert agency_now["quarterly_voucher_quota"] == 1
    assert_quota_conservation(agency_now, [referral_now])


# ─── Difficulty: quota slots conserved across approve then expiry ──────

def test_approval_consumes_a_quota_slot_and_stamps_the_epoch_and_expiry(api):
    """PRD §3.2: "Approval stamps `approved_at` with the current instant and
    `expires_at` with that instant plus 45 days, captures the agency's current
    `quota_epoch` into the referral's `approved_epoch`, raises the agency's
    `quota_used` by 1, and bumps both the referral's and the agency's `version`
    by 1."
    PRD §3.1: "A newly registered agency opens with `quota_used` at 0,
    `quota_epoch` at 1, `standing` at `GOOD`, and `no_show_credits_owed_cents`
    at 0."

    Design: Difficulty/compensating_invariant/agency_quota_slots_conserved_across_approve_then_expiry
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Stonebridge Relief", county="CENTRAL",
                           quarterly_voucher_quota=3)
    assert agency["quota_used"] == 0, "a fresh agency has spent no slot"

    household = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED"])
    submit_referral(referral["id"], agency["id"])
    approved = review_referral(referral["id"], "APPROVE")

    assert approved["approved_epoch"] == 1, "approval captures the agency's epoch"
    assert approved["expires_at"] == "2026-09-18T09:00:00.000Z", (
        "expires_at is the approval instant plus 45 days"
    )
    assert approved["approved_at"] == "2026-08-04T09:00:00.000Z"

    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == 1, "approval raises quota_used by 1"
    assert_quota_conservation(agency_now, [approved])


def test_operational_cycle_expiry_returns_the_consumed_quota_slot(api):
    """PRD §3.2: "During the expiry pass of the operational cycle, a referral in
    `APPROVED` whose `expires_at` is strictly earlier than now moves `APPROVED →
    EXPIRED`, lowers the agency's `quota_used` by 1 as the compensating half of
    the quota identity, and bumps both the referral's and the agency's
    `version`."
    PRD §2.6: "The cycle answers with a summary object rather than an entity:
    `expired_referral_count`, `expired_voucher_count`, `released_inventory_count`,
    `promoted_waitlist_count`, `restanding_count`, `reinstated_client_count`, and
    the boolean `quota_epoch_advanced`."

    Design: Difficulty/compensating_invariant/agency_quota_slots_conserved_across_approve_then_expiry
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Stonebridge Relief", county="CENTRAL",
                           quarterly_voucher_quota=3)
    household = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral = create_approved_referral(agency["id"], household["id"],
                                        requested_categories=["BED"])

    set_clock("2026-09-20T09:00:00Z")
    summary = run_cycle(advance_quota_epoch=False)

    assert summary["expired_referral_count"] == 1, "the lapsed referral expires"
    assert summary["quota_epoch_advanced"] is False, "the epoch was not asked to advance"

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "EXPIRED"

    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == 0, "the compensating action returns the slot"
    assert agency_now["quota_epoch"] == 1, "expiry never moves the epoch counter"
    assert agency_now["quarterly_voucher_quota"] == 3
    assert_quota_conservation(agency_now, [referral_now])


# ─── Difficulty: the two need-score variants ───────────────────────────

def test_intake_variant_scores_the_referral_with_tenure_held_at_zero(api):
    """PRD §3.2: "In the **intake variant**, written to
    `Referral.priority_score` when a referral is submitted (including every
    revision round), the tenure input is zero — the queue clock has not started
    — and the strike weight is 8 points per strike."
    PRD §3.6: "A waitlist entry carries the `voucher_line_id` of the line, the
    `client_id` of the waiting household, a `category` and a `county` copied
    from the line and from the household respectively, a `quantity_unmet` equal
    to the units still short, a `priority_score` computed with the waitlist
    variant of the need score evaluated at that moment (tenure is zero at
    creation and is later recomputed by the operational cycle's scoring pass),
    and a `waiting_since` that is set to the current instant on first creation
    and is **never** reset by a later top-up."

    Design: Difficulty/dual_variant_calc/priority_intake_score_vs_waitlist_score_tenure
    """
    scenario = _waitlisted_priority_scenario()

    assert scenario["submitted"]["priority_score"] == pytest.approx(45.0, abs=0.01), (
        "PRIORITY 25 plus four people at 5 points each is 45.0 with zero tenure"
    )
    assert len(scenario["waitlist"]) == 1, "the empty warehouse waitlists the line"
    entry = scenario["waitlist"][0]
    assert entry["priority_score"] == pytest.approx(45.0, abs=0.01), (
        "tenure is zero at creation, so the waitlist score matches the intake score"
    )
    assert entry["quantity_unmet"] == 1
    assert entry["waiting_since"] == "2026-08-04T09:00:00.000Z"

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ISSUED", "a zero-yield round is a successful 200"


def test_waitlist_variant_adds_tenure_points_on_the_scoring_pass(api):
    """PRD §3.2: "In the **waitlist variant**, written to
    `WaitlistEntry.priority_score` during the scoring pass of the operational
    cycle over every `WAITING` entry, the tenure input is the number of whole
    24-hour days elapsed between the entry's `waiting_since` and now, rounded
    down, and the strike weight is 16 points per strike."
    PRD §3.2: "Tenure contributes 4 points for each whole 30-day month waited,
    capped at 20 points, which is reached after five whole months."
    PRD §2.6: "4. **Waitlist rescoring.** Every `WaitlistEntry` in status
    `WAITING` has its `priority_score` recomputed using the waitlist variant of
    the need score."

    Design: Difficulty/dual_variant_calc/priority_intake_score_vs_waitlist_score_tenure
    """
    scenario = _waitlisted_priority_scenario()
    entry_id = scenario["waitlist"][0]["id"]

    set_clock("2026-09-04T09:00:00Z")
    summary = run_cycle(advance_quota_epoch=False)

    assert summary["expired_referral_count"] == 0, "the referral is still live"
    assert summary["promoted_waitlist_count"] == 0, "no stock exists to promote against"

    entry_now = validate_success(api.get_waitlist_entry(entry_id, ADMIN))
    assert entry_now["priority_score"] == pytest.approx(49.0, abs=0.01), (
        "31 whole days is one whole 30-day month, adding 4 points to 45.0"
    )
    assert entry_now["status"] == "WAITING"
    assert entry_now["quantity_unmet"] == 1

    referral_now = validate_success(api.get_referral(scenario["referral"]["id"], ADMIN))
    assert referral_now["priority_score"] == pytest.approx(45.0, abs=0.01), (
        "the referral keeps its intake score; only the waitlist entry is rescored"
    )
    assert referral_now["status"] == "APPROVED"


# ─── Corner: draft state, invalid review, terminal denial, suspension ──

def test_fresh_referral_opens_in_draft_with_no_score_and_no_stamps(api):
    """PRD §3.2: "A fresh referral is created in `status` `DRAFT` with
    `revision_count` at 0, `priority_score` at 0.0, and `approved_at`,
    `expires_at`, `approved_epoch` and `review_note` all null."

    Design: Corner/state_machines/corner_referral_starts_in_draft_with_zero_score
    """
    agency = create_agency(name="Ironwood Family Center", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=5, county="CENTRAL",
                              has_infant=True)

    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED", "CRIB"],
                               urgency="EMERGENCY")

    assert_referral(referral)
    assert referral["status"] == "DRAFT"
    assert referral["revision_count"] == 0
    assert referral["priority_score"] == pytest.approx(0.0, abs=0.01), (
        "the score is only computed at submit"
    )
    assert referral["approved_at"] is None
    assert referral["expires_at"] is None
    assert referral["approved_epoch"] is None


def test_review_of_a_draft_referral_is_refused(api):
    """PRD §3.2: "Attempting a review from a status that has no matching
    outgoing edge is rejected with `ERR_REFERRAL_NOT_SUBMITTED`."

    Design: Corner/state_machines/corner_review_of_draft_referral_rejected
    """
    agency = create_agency(name="Juniper Way Services", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")
    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED"])

    response = api.review_referral(referral["id"], review_payload("APPROVE"), ADMIN)
    validate_error(response, ApiErrorId.ERR_REFERRAL_NOT_SUBMITTED.value, 409)

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "DRAFT"
    agency_now = validate_success(api.get_agency(agency["id"], ADMIN))
    assert agency_now["quota_used"] == 0


def test_denied_referral_cannot_be_resubmitted(api):
    """PRD §3.2: "Submitting from any status other than `DRAFT` or `RETURNED` is
    rejected with `ERR_REFERRAL_NOT_SUBMITTED`."
    PRD §3.2: "A `DENY` decision is accepted from either of the two live review
    states — `SUBMITTED → DENIED` and `RETURNED → DENIED` — and likewise stores
    `review_note` and bumps `version`."

    Design: Corner/state_machines/corner_denied_referral_is_terminal_and_cannot_be_resubmitted
    """
    agency = create_agency(name="Kestrel Outreach", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")
    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED"])
    submit_referral(referral["id"], agency["id"])
    denied = review_referral(referral["id"], "DENY",
                             "Household already served this quarter")
    assert denied["review_note"] == "Household already served this quarter"

    response = api.submit_referral(
        referral["id"], make_case_manager_headers(agency["id"])
    )
    validate_error(response, ApiErrorId.ERR_REFERRAL_NOT_SUBMITTED.value, 409)

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "DENIED", "DENIED is terminal"
    assert referral_now["revision_count"] == 0


def test_suspended_agency_cannot_submit_a_new_referral(api):
    """PRD §3.1: "Otherwise the system takes the count of `NO_SHOW` stops in the
    window divided by the total count of stops in the window, as an exact
    rational value with no rounding, and sets `standing` to `SUSPENDED` when
    that share is at least one half, otherwise to `PROBATION` when it is at
    least one quarter, otherwise to `GOOD`."
    PRD §3.1: "A `SUSPENDED` agency cannot submit a referral and cannot have one
    approved, both rejected with `ERR_AGENCY_SUSPENDED`."

    Design: Corner/validations/corner_suspended_agency_standing_blocks_new_referral_submit
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_suspended_agency()
    agency_id = scenario["agency"]["id"]

    assert scenario["no_show_chargeback"] == 428, (
        "DRESSER 950 cents times one unit at the 0.45 no-show rate rounds to 428"
    )
    agency_now = validate_success(api.get_agency(agency_id, ADMIN))
    assert agency_now["standing"] == "SUSPENDED", (
        "one NO_SHOW out of two terminal stops is an exact 0.50 share"
    )
    assert agency_now["no_show_credits_owed_cents"] == 428

    third = create_referral(agency_id, scenario["clients"][0]["id"],
                            requested_categories=["LINENS"])
    response = api.submit_referral(third["id"], make_case_manager_headers(agency_id))
    validate_error(response, ApiErrorId.ERR_AGENCY_SUSPENDED.value, 409)

    third_now = validate_success(api.get_referral(third["id"], ADMIN))
    assert third_now["status"] == "DRAFT", "the refused submission keeps the draft"
    assert third_now["priority_score"] == pytest.approx(0.0, abs=0.01)

    household_b = validate_success(api.get_client(scenario["clients"][1]["id"], ADMIN))
    assert household_b["no_show_strikes"] == 1
    assert household_b["status"] == "ACTIVE"
