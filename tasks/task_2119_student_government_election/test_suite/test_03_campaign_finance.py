"""Campaign finance: the two spending assessments, the poster ceiling, the
pre-poll blackout and the campus-venue calendar."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_campaign_expense,
    assert_spend_ledger_conserved,
    change_slate_membership,
    create_campaign_expense_payload,
    file_candidacy,
    make_candidate_headers,
    open_polls,
    publish_round_one_ballot,
    read_candidacy,
    read_expense,
    register_student,
    report_expense,
    run_tally,
    setup_petitioning_election,
    setup_single_candidate_election,
    setup_slate_rounding_scenario,
    setup_slate_spend_dual_variant_scenario,
    setup_three_member_slate,
    setup_two_reported_expenses,
    setup_venue_booking_scenario,
    slate_membership_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]


# ─── Reporting a line ─────────────────────────────────────────────────────────

def test_expense_optional_attributes_take_their_declared_defaults(api):
    """PRD §3.4: "Three optional attributes shape what the line means: `quantity`, a
    non-negative physical unit count defaulting to 0, of which only `POSTER` lines matter;
    `shared_with_slate`, a boolean defaulting to false that pools the line across the
    slate; and, for `EVENT` lines only, a `venue_code` naming the campus venue booked,
    together with `event_starts_at` and `event_ends_at` bounding the occupation."
    PRD §3.4: "An `EVENT` line must supply all three venue attributes; a line of any other
    category leaves them empty. Lines enter in `status` `REPORTED` with
    `approved_by_user_id` empty."

    Design: Corner/entities/campaign_expense_quantity_and_shared_flag_default
    """
    scenario = setup_single_candidate_election(
        election_overrides={"spending_cap_cents": 500_000, "poster_cap": 100},
        office_overrides={"eligible_class_years": ["SENIOR"]},
        approve=False,
    )
    candidacy = scenario["candidacies"][0]

    expense = validate_success(
        api.create_campaign_expense(
            {
                "candidacy_id": candidacy["id"],
                "category": "DIGITAL",
                "amount_cents": 3000,
                "incurred_at": "2026-08-05T00:00:00Z",
            },
            make_candidate_headers(candidacy["student_id"]),
        ),
        201,
    )

    assert_campaign_expense(expense)
    assert expense["quantity"] == 0, f"quantity defaults to 0, got {expense['quantity']}"
    assert expense["shared_with_slate"] is False
    assert expense["status"] == "REPORTED"
    assert expense["venue_code"] is None
    assert expense["approved_by_user_id"] is None

    owner = read_candidacy(candidacy["id"])
    assert owner["poster_count"] == 0, "a DIGITAL line never feeds the poster ceiling"
    assert owner["spending_committed_cents"] == 3000


def test_a_line_that_breaches_the_spending_cap_is_refused(api):
    """PRD §3.4: "The cap check is deliberately narrower than the assessment it reads.
    Only the candidacy named in the incoming expense request is tested: its
    `spending_committed_cents` after the new line must be at most the election's
    `spending_cap_cents`."
    PRD §2.5: "Spending cap — `ERR_SPENDING_CAP_EXCEEDED` (422), on campaign-expense
    reporting."

    Design: Corner/validations/expense_above_cap_returns_spending_cap_exceeded
    """
    scenario = setup_single_candidate_election(
        office_overrides={"eligible_class_years": ["SENIOR"]}, approve=False
    )
    candidacy = scenario["candidacies"][0]

    validate_error(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                candidacy["id"], category="DIGITAL", amount_cents=60_000
            ),
            make_candidate_headers(candidacy["student_id"]),
        ),
        ApiErrorId.ERR_SPENDING_CAP_EXCEEDED.value,
        422,
    )

    assert read_candidacy(candidacy["id"])["spending_committed_cents"] == 0
    _, meta = validate_paginated(
        api.list_campaign_expenses(COMMISSIONER, params={"candidacy_id": candidacy["id"]})
    )
    assert meta["total_count"] == 0, "the refused line was never written"


def test_the_poster_ceiling_blocks_a_line_until_a_reversal_frees_the_allowance(api):
    """PRD §3.4: "Third, the poster ceiling: `poster_count`, the sum of `quantity` across
    the candidacy's `POSTER` lines in `REPORTED` or `APPROVED` status, may not exceed the
    election's `poster_cap` once the new line is included, and an overshoot is
    `ERR_POSTER_CAP_EXCEEDED`."
    PRD §3.4: "Reversal recomputes `spending_committed_cents` and
    `spending_reversed_cents` for every slate member, and additionally recomputes
    `poster_count` when the reversed line's `category` was `POSTER`."

    Design: Corner/calculations/poster_cap_blocks_line_then_reversal_frees_the_allowance
    """
    scenario = setup_single_candidate_election(
        election_overrides={"spending_cap_cents": 500_000, "poster_cap": 50},
        office_overrides={"eligible_class_years": ["SENIOR"]},
        approve=False,
    )
    candidacy = scenario["candidacies"][0]
    headers = make_candidate_headers(candidacy["student_id"])
    first = report_expense(
        candidacy, category="POSTER", amount_cents=8_000,
        incurred_at="2026-08-05T00:00:00Z", quantity=40,
    )

    second_payload = create_campaign_expense_payload(
        candidacy["id"], category="POSTER", amount_cents=4_000,
        incurred_at="2026-08-06T00:00:00Z", quantity=20,
    )
    validate_error(
        api.create_campaign_expense(second_payload, headers),
        ApiErrorId.ERR_POSTER_CAP_EXCEEDED.value,
        422,
    )

    validate_success(
        api.reverse_expense(
            first["id"], COMMISSIONER, {"reason": "Print shop cancelled the run"}
        )
    )
    accepted = validate_success(api.create_campaign_expense(second_payload, headers), 201)

    assert read_expense(first["id"])["status"] == "REVERSED"
    owner = read_candidacy(candidacy["id"])
    assert owner["poster_count"] == 20, (
        f"only the surviving 20-poster line counts, got {owner['poster_count']}"
    )
    assert owner["spending_committed_cents"] == 4_000
    assert owner["spending_reversed_cents"] == 8_000
    assert owner["spending_reported_cents"] == 12_000
    assert_spend_ledger_conserved(owner, accepted["amount_cents"])


def test_spending_inside_the_pre_poll_blackout_is_refused(api):
    """PRD §3.4: "First, the **pre-poll blackout**: `incurred_at` must fall outside the
    quiet period, which begins `quiet_period_hours` before the election's
    `voting_opens_at` and runs through `voting_closes_at`; spending inside that window is
    `ERR_QUIET_PERIOD_ACTIVE`."

    Design: Corner/validations/expense_incurred_inside_quiet_period_returns_error
    """
    scenario = setup_single_candidate_election(
        election_overrides={
            "spending_cap_cents": 500_000,
            "poster_cap": 100,
            "quiet_period_hours": 24,
        },
        office_overrides={"eligible_class_years": ["SENIOR"]},
        approve=True,
    )
    publish_round_one_ballot(scenario)
    open_polls(scenario)
    candidacy = scenario["candidacies"][0]
    headers = make_candidate_headers(candidacy["student_id"])

    validate_error(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                candidacy["id"], category="DIGITAL", amount_cents=1_000,
                incurred_at="2026-09-14T12:00:00Z",
            ),
            headers,
        ),
        ApiErrorId.ERR_QUIET_PERIOD_ACTIVE.value,
        422,
    )

    accepted = validate_success(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                candidacy["id"], category="DIGITAL", amount_cents=1_000,
                incurred_at="2026-09-14T08:00:00Z",
            ),
            headers,
        ),
        201,
    )
    assert accepted["status"] == "REPORTED"

    _, meta = validate_paginated(
        api.list_campaign_expenses(COMMISSIONER, params={"candidacy_id": candidacy["id"]})
    )
    assert meta["total_count"] == 1, "only the line outside the blackout survived"
    assert read_candidacy(candidacy["id"])["spending_committed_cents"] == 1_000


# ─── The campus-venue calendar ────────────────────────────────────────────────

def test_a_rally_starting_thirty_minutes_after_another_ends_is_double_booked(api):
    """PRD §2.10: "Each booking's interval from `event_starts_at` to `event_ends_at` is
    extended thirty minutes earlier and thirty minutes later before comparison; two
    widened intervals collide when the new interval's start is at or before the existing
    interval's end **and** the existing interval's start is at or before the new
    interval's end."
    PRD §2.10: "Because both comparisons are inclusive, widened intervals that merely
    touch **do** collide, and back-to-back rallies at the same venue are refused."

    Design: Difficulty/resource_temporal_overlap/venue_booking_buffered_closed_interval_rejects_back_to_back
    """
    scenario = setup_venue_booking_scenario()
    rival = scenario["second_candidacy"]

    validate_error(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                rival["id"], category="EVENT", amount_cents=5_000,
                incurred_at="2026-08-10T00:00:00Z", venue_code="QUAD-A",
                event_starts_at="2026-08-20T20:30:00Z",
                event_ends_at="2026-08-20T22:00:00Z",
            ),
            make_candidate_headers(rival["student_id"]),
        ),
        ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_campaign_expenses(COMMISSIONER, params={"candidacy_id": rival["id"]})
    )
    assert meta["total_count"] == 0, "the collided booking was never written"
    assert read_candidacy(rival["id"])["spending_committed_cents"] == 0
    assert read_candidacy(scenario["first_candidacy"]["id"])["spending_committed_cents"] == 5_000


def test_a_rally_clearing_the_teardown_buffer_by_one_minute_is_accepted(api):
    """PRD §2.10: "A **campus venue** is occupied by campaign events and uses closed
    intervals widened by a teardown buffer of thirty minutes on both sides, so adjacency
    is rejected."
    PRD §2.10: "Each booking's interval from `event_starts_at` to `event_ends_at` is
    extended thirty minutes earlier and thirty minutes later before comparison; two
    widened intervals collide when the new interval's start is at or before the existing
    interval's end **and** the existing interval's start is at or before the new
    interval's end."

    Design: Difficulty/resource_temporal_overlap/venue_booking_buffered_closed_interval_rejects_back_to_back
    """
    scenario = setup_venue_booking_scenario()
    rival = scenario["second_candidacy"]
    headers = make_candidate_headers(rival["student_id"])

    validate_error(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                rival["id"], category="EVENT", amount_cents=5_000,
                incurred_at="2026-08-10T00:00:00Z", venue_code="QUAD-A",
                event_starts_at="2026-08-20T20:30:00Z",
                event_ends_at="2026-08-20T22:00:00Z",
            ),
            headers,
        ),
        ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value,
        409,
    )

    accepted = validate_success(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                rival["id"], category="EVENT", amount_cents=5_000,
                incurred_at="2026-08-10T00:00:00Z", venue_code="QUAD-A",
                event_starts_at="2026-08-20T21:01:00Z",
                event_ends_at="2026-08-20T22:00:00Z",
            ),
            headers,
        ),
        201,
    )

    assert_campaign_expense(accepted)
    assert accepted["venue_code"] == "QUAD-A"
    _, meta = validate_paginated(
        api.list_campaign_expenses(COMMISSIONER, params={"candidacy_id": rival["id"]})
    )
    assert meta["total_count"] == 1, "exactly one booking survived for the rival"
    assert read_candidacy(rival["id"])["spending_committed_cents"] == 5_000
    assert read_candidacy(scenario["first_candidacy"]["id"])["spending_committed_cents"] == 5_000


# ─── The spend ledger ─────────────────────────────────────────────────────────

def test_approving_a_line_leaves_the_committed_and_reported_totals_untouched(api):
    """PRD §3.4: "Approving a line moves it `REPORTED → APPROVED`, stamps
    `approved_by_user_id`, and recomputes `spending_committed_cents` for every live slate
    member; it is refused when the owning candidacy is `WITHDRAWN`, `DISQUALIFIED` or
    `VACATED`."
    PRD §3.4: "The **provisional** assessment, held in `spending_committed_cents`, is
    joint-and-several and is recomputed live every time an expense is reported, approved
    or reversed, and every time the cap is checked."

    Design: Difficulty/compensating_invariant/expense_approve_then_reverse_restores_committed_cents
    """
    scenario = setup_two_reported_expenses()
    candidacy = scenario["candidacy"]

    before = read_candidacy(candidacy["id"])
    assert before["spending_committed_cents"] == 19_500
    assert before["spending_reported_cents"] == 19_500
    assert before["spending_reversed_cents"] == 0

    approved = validate_success(
        api.approve_expense(scenario["merch_expense"]["id"], COMMISSIONER)
    )
    assert approved["status"] == "APPROVED"

    after = read_candidacy(candidacy["id"])
    assert after["spending_committed_cents"] == 19_500, (
        "the provisional figure counts REPORTED and APPROVED lines alike, got "
        f"{after['spending_committed_cents']}"
    )
    assert after["spending_reported_cents"] == 19_500
    assert after["spending_reversed_cents"] == 0
    assert_spend_ledger_conserved(after, 19_500)


def test_reversing_an_approved_line_moves_the_cents_without_touching_the_total(api):
    """PRD §2.9: "If an expense line is approved and then reversed,
    `spending_committed_cents` falls by exactly that line's `amount_cents` relative to its
    value before the approval, `spending_reversed_cents` rises by exactly that amount, and
    `spending_reported_cents` does not move at all."
    PRD §3.4: "Reversal moves a line to the terminal `REVERSED` from either `REPORTED` or
    `APPROVED`, carries an optional `reason`, and has no state precondition of its own — a
    candidacy in any posture may have its ledger corrected."

    Design: Difficulty/compensating_invariant/expense_approve_then_reverse_restores_committed_cents
    """
    scenario = setup_two_reported_expenses()
    candidacy = scenario["candidacy"]
    merch = scenario["merch_expense"]

    validate_success(api.approve_expense(merch["id"], COMMISSIONER))
    intermediate = read_candidacy(candidacy["id"])
    assert intermediate["spending_committed_cents"] == 19_500

    reversed_line = validate_success(
        api.reverse_expense(
            merch["id"], COMMISSIONER, {"reason": "Vendor refunded the order"}
        )
    )
    assert reversed_line["status"] == "REVERSED"

    after = read_candidacy(candidacy["id"])
    assert after["spending_committed_cents"] == 12_500, (
        f"the reversed 7000 cents leave the committed figure, got "
        f"{after['spending_committed_cents']}"
    )
    assert after["spending_reversed_cents"] == 7_000
    assert after["spending_reported_cents"] == 19_500, (
        "the reported ledger does not move at all"
    )
    assert after["spending_committed_cents"] + after["spending_reversed_cents"] == 19_500
    assert after["poster_count"] == 30, "the untouched poster line still holds its quantity"
    assert_spend_ledger_conserved(after, 12_500)


# ─── Slate membership ─────────────────────────────────────────────────────────

def test_naming_a_leader_that_already_belongs_to_a_slate_is_refused(api):
    """PRD §3.2: "And if a slate leader is named, that leader must belong to the same
    election, must not be the filing candidacy itself, and must have no slate leader of
    its own — slates are exactly one level deep — with any violation reported as
    `ERR_INVALID_SLATE`."
    PRD §3.2: "the same one-level-deep, same-election, not-itself rules apply and the same
    `ERR_INVALID_SLATE` reports their violation"

    Design: Corner/validations/slate_leader_that_already_belongs_to_a_slate_returns_invalid_slate
    """
    scenario = setup_three_member_slate()
    member_one = scenario["member_one"]
    independent_student = register_student(
        full_name="Omar Diaz", class_year="SENIOR", gpa=3.30, credits_completed=88
    )
    independent = file_candidacy(
        scenario["election"]["id"], scenario["office"]["id"], independent_student["id"]
    )
    current_version = read_candidacy(independent["id"])["version"]

    validate_error(
        api.change_slate_membership(
            independent["id"],
            slate_membership_payload(member_one["id"], current_version),
            make_candidate_headers(independent_student["id"]),
        ),
        ApiErrorId.ERR_INVALID_SLATE.value,
        422,
    )

    unchanged = read_candidacy(independent["id"])
    assert unchanged["slate_leader_candidacy_id"] is None, (
        "the refused change leaves the run independent"
    )
    assert unchanged["version"] == current_version, "a refused change mutates nothing"


def test_slate_membership_with_a_stale_candidacy_version_is_refused(api):
    """PRD §2.8: "A slate-membership change (`POST
    /candidacies/{candidacy_id}/slate-membership`) must carry
    `expected_candidacy_version` matching that candidacy's current `version`. A mismatch
    is rejected with `ERR_STALE_CANDIDACY_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/slate_membership_with_stale_candidacy_version_returns_412
    """
    scenario = setup_petitioning_election(
        election_overrides={"spending_cap_cents": 500_000, "poster_cap": 100},
        offices=[{"name": "Student Senate", "eligible_class_years": ["JUNIOR", "SENIOR"],
                  "seat_count": 3}],
        candidates=[
            {"student": {"full_name": "Lena Ortiz", "class_year": "SENIOR",
                         "gpa": 3.40, "credits_completed": 90}},
            {"student": {"full_name": "Omar Diaz", "class_year": "SENIOR",
                         "gpa": 3.30, "credits_completed": 88}},
            {"student": {"full_name": "Marco Reyes", "class_year": "JUNIOR",
                         "gpa": 3.10, "credits_completed": 62}},
        ],
        approve=False,
    )
    first_leader, second_leader, mover = scenario["candidacies"]
    stale_version = read_candidacy(mover["id"])["version"]
    change_slate_membership(mover, first_leader["id"], stale_version)

    validate_error(
        api.change_slate_membership(
            mover["id"],
            slate_membership_payload(second_leader["id"], stale_version),
            make_candidate_headers(mover["student_id"]),
        ),
        ApiErrorId.ERR_STALE_CANDIDACY_VERSION.value,
        412,
    )

    unchanged = read_candidacy(mover["id"])
    assert unchanged["slate_leader_candidacy_id"] == first_leader["id"], (
        "the stale write must not overwrite the membership it never read"
    )
    assert unchanged["version"] == stale_version + 1
    _, meta = validate_paginated(
        api.list_candidacies(
            COMMISSIONER, params={"slate_leader_candidacy_id": second_leader["id"]}
        )
    )
    assert meta["total_count"] == 0, "the second leader gained no member"


# ─── The two spending assessments ─────────────────────────────────────────────

def test_the_provisional_assessment_charges_the_whole_slate_pool_to_each_member(api):
    """PRD §3.4: "It reads *live* slate membership: the candidacy's slate root is its
    `slate_leader_candidacy_id` when set and otherwise its own identifier, the live
    membership is the root together with every candidacy pointing at that root, and each
    member's `spending_committed_cents` is the sum, across every live member, of that
    member's own `REPORTED` and `APPROVED` line amounts."
    PRD §3.4: "The whole pool is charged in full to each member — the same line counts once
    against every member of the slate, which is exactly what "joint and several" means
    here."
    PRD §3.4: "Two more counters are maintained unconditionally on every candidacy:
    `spending_reported_cents`, the sum of `amount_cents` over that candidacy's own lines in
    any status at all, and `spending_reversed_cents`, the same sum restricted to lines that
    have been reversed."

    Design: Difficulty/dual_variant_calc/slate_spend_provisional_versus_final_on_candidacy
    """
    scenario = setup_slate_spend_dual_variant_scenario()

    run_tally(scenario["election"]["id"])

    for key in ("leader", "member_one", "member_two"):
        member = read_candidacy(scenario[key]["id"])
        assert member["spending_committed_cents"] == 27_500, (
            f"{key} carries the whole joint-and-several pool, got "
            f"{member['spending_committed_cents']}"
        )

    member_one = read_candidacy(scenario["member_one"]["id"])
    assert member_one["spending_reported_cents"] == 4_000, (
        "the reported counter covers only that candidacy's own lines, got "
        f"{member_one['spending_reported_cents']}"
    )


def test_the_final_assessment_is_pro_rata_and_diverges_from_the_provisional(api):
    """PRD §3.4: "A candidacy's final figure is the sum of its own solo approved spending —
    `APPROVED` lines whose `shared_with_slate` is false — plus its share of the slate's
    shared pool."
    PRD §3.4: "Only `APPROVED` lines participate: `REPORTED` and `REVERSED` lines are
    excluded from the final figure entirely, which is the second reason the two assessments
    diverge."
    PRD §3.8: "**Step two — final spending.** For each of those candidacies,
    `spending_final_cents` is computed by the pro-rata method of Section 3.4, evaluated
    over that candidacy's frozen `slate_snapshot_member_ids` alone."

    Design: Difficulty/dual_variant_calc/slate_spend_provisional_versus_final_on_candidacy
    """
    scenario = setup_slate_spend_dual_variant_scenario()

    run_tally(scenario["election"]["id"])

    leader = read_candidacy(scenario["leader"]["id"])
    member_one = read_candidacy(scenario["member_one"]["id"])
    member_two = read_candidacy(scenario["member_two"]["id"])

    assert leader["spending_final_cents"] == 9_168, (
        f"2500 solo plus 6668 of the shared pool, got {leader['spending_final_cents']}"
    )
    assert member_one["spending_final_cents"] == 6_666, (
        "the unapproved 4000-cent line is excluded, got "
        f"{member_one['spending_final_cents']}"
    )
    assert member_two["spending_final_cents"] == 7_666, (
        f"1000 solo plus 6666 of the shared pool, got {member_two['spending_final_cents']}"
    )
    assert (
        leader["spending_final_cents"]
        + member_one["spending_final_cents"]
        + member_two["spending_final_cents"]
    ) == 23_500
    assert member_two["spending_committed_cents"] != member_two["spending_final_cents"], (
        "the two assessments disagree by design"
    )


def test_each_shared_line_is_rounded_once_before_the_charges_are_summed(api):
    """PRD §3.4: "That share is computed line by line, never pool-first."
    PRD §3.4: "For each line, divide its `amount_cents` by the member count and round half
    up to a whole number of cents to obtain the per-member charge; subtract the per-member
    charge multiplied by the member count from the line amount to obtain a remainder, which
    may be negative."
    PRD §3.4: "Every member is charged the per-member amount, and the remainder-bearer is
    charged the remainder in addition."

    Design: Difficulty/combinatorial_formula/slate_shared_line_rounding_order_pinned
    """
    scenario = setup_slate_rounding_scenario()

    run_tally(scenario["election"]["id"])

    leader = read_candidacy(scenario["leader"]["id"])
    member_one = read_candidacy(scenario["member_one"]["id"])
    member_two = read_candidacy(scenario["member_two"]["id"])

    assert leader["spending_final_cents"] == 6_668, (
        "3333 per line plus one cent of remainder per line, got "
        f"{leader['spending_final_cents']}"
    )
    assert member_one["spending_final_cents"] == 6_666
    assert member_two["spending_final_cents"] == 6_666
    assert (
        leader["spending_final_cents"]
        + member_one["spending_final_cents"]
        + member_two["spending_final_cents"]
    ) == 20_000, "the two shared lines are fully allocated"


def test_pool_first_rounding_is_not_the_specified_allocation(api):
    """PRD §3.4: "Rounding once per line and then summing the rounded charges is the
    specified behaviour; summing the pool first and rounding once at the end produces
    different cents and is wrong."
    PRD §3.4: "Take the frozen member list, count its members, and note which member has
    the earliest `created_at`; that member is the remainder-bearer."

    Design: Difficulty/combinatorial_formula/slate_shared_line_rounding_order_pinned
    """
    scenario = setup_slate_rounding_scenario()

    run_tally(scenario["election"]["id"])

    leader = read_candidacy(scenario["leader"]["id"])
    member_one = read_candidacy(scenario["member_one"]["id"])

    assert leader["spending_final_cents"] != 6_666, (
        "the earliest-created member bears the remainder of every line"
    )
    assert member_one["spending_final_cents"] != 6_667, (
        "summing the 20000-cent pool first and rounding once is not the specified method"
    )
    assert leader["spending_final_cents"] - member_one["spending_final_cents"] == 2, (
        "one cent of remainder per shared line lands on the remainder-bearer"
    )
