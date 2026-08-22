"""The demo round: pitching, the revision cycle, shortlisting and the selection cascade."""
from test_helpers import (
    ApiErrorId,
    add_shortlisted_demo,
    assert_demo,
    assert_instant_equals,
    assert_ledger,
    create_composer,
    get_demo,
    get_project,
    make_client_rep_headers,
    make_composer_headers,
    pitch_demo,
    request_demo_revision,
    set_clock,
    setup_engagement_in_demo,
    setup_engagement_in_production,
    submit_demo,
    validate_error,
    validate_success,
)


def _demo_at_revision_limit(budget_cents=230_000, demo_fee_cents=150_000):
    """An engagement whose only demo has already used all three revision rounds."""
    env = setup_engagement_in_demo(budget_cents=budget_cents)
    composer = create_composer(index=0)
    demo = pitch_demo(env["project"]["id"], composer["id"],
                      title="Sunrise Pop", demo_fee_cents=demo_fee_cents,
                      submitted_length_seconds=60)
    submit_demo(demo["id"], composer["id"])
    for note in ("round one", "round two", "round three"):
        request_demo_revision(demo["id"], env["client"]["id"], revision_note=note)
        submit_demo(demo["id"], composer["id"])
    env["composer"] = composer
    env["demo"] = get_demo(demo["id"])
    return env


def test_demo_returns_to_submitted_after_two_revision_rounds(api):
    """PRD §3.3: "Submission moves a demo `DRAFT → SUBMITTED`, and the same operation
    moves a demo `REVISION_REQUESTED → SUBMITTED`, closing the revision cycle."
    PRD §3.3: "Each request increases `revision_count` by one, records the supplied note
    in `last_revision_note`, and books a **flat surcharge** equal to the demo's original
    `demo_fee_cents` multiplied by 15 percent and rounded half-up to whole cents."

    Design: Difficulty/non_linear_state_machine/demo_revision_cycle_survives_two_full_rounds
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    composer, demo = add_shortlisted_demo(env, title="Sunrise Pop", demo_fee_cents=150_000,
                                          submitted_length_seconds=60)
    assert demo["status"] == "SHORTLISTED"

    first = validate_success(api.request_demo_revision(
        demo["id"], {"revision_note": "brighter chorus"},
        make_client_rep_headers(env["client"]["id"])))
    assert first["status"] == "REVISION_REQUESTED", (
        f"Expected REVISION_REQUESTED, got {first['status']}")
    assert first["revision_count"] == 1
    resubmitted = validate_success(api.submit_demo(
        demo["id"], make_composer_headers(composer["id"])))
    assert resubmitted["status"] == "SUBMITTED", (
        f"The revision cycle must close back into SUBMITTED; got {resubmitted['status']}")

    validate_success(api.shortlist_demo(demo["id"], make_client_rep_headers(env["client"]["id"])))
    validate_success(api.request_demo_revision(
        demo["id"], {"revision_note": "softer outro"},
        make_client_rep_headers(env["client"]["id"])))
    final = validate_success(api.submit_demo(demo["id"], make_composer_headers(composer["id"])))
    assert_demo(final)
    assert final["status"] == "SUBMITTED", f"Expected SUBMITTED, got {final['status']}"
    assert final["revision_count"] == 2, f"Expected revision_count 2, got {final['revision_count']}"
    assert final["last_revision_note"] == "softer outro", (
        f"Expected the most recent note, got {final['last_revision_note']}")


def test_each_revision_round_books_a_flat_surcharge(api):
    """PRD §3.3: "The surcharge is always keyed to the original `demo_fee_cents` and
    never to the already-grown `accrued_fee_cents`, so three revision rounds cost
    exactly three identical surcharges rather than compounding."
    PRD §3.3: "The surcharge is added to the demo's `accrued_fee_cents`, added to the
    engagement's `committed_cents` and subtracted from its `available_cents`, after
    which the posture is recomputed and — if the posture value changes — the
    session-call sweep of §2.7 runs."

    Design: Difficulty/non_linear_state_machine/demo_revision_cycle_survives_two_full_rounds
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    composer, demo = add_shortlisted_demo(env, title="Sunrise Pop", demo_fee_cents=150_000,
                                          submitted_length_seconds=60)
    request_demo_revision(demo["id"], env["client"]["id"], revision_note="brighter chorus")
    submit_demo(demo["id"], composer["id"])
    validate_success(api.shortlist_demo(demo["id"], make_client_rep_headers(env["client"]["id"])))
    request_demo_revision(demo["id"], env["client"]["id"], revision_note="softer outro")
    submit_demo(demo["id"], composer["id"])

    settled = get_demo(demo["id"])
    assert settled["accrued_fee_cents"] == 195_000, (
        "Two flat 22500-cent surcharges on a 150000-cent fee give 195000; "
        f"got {settled['accrued_fee_cents']}")
    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=195_000, available=3_805_000, spent=0)
    assert project["budget_posture"] == "HEALTHY", (
        f"Expected HEALTHY, got {project['budget_posture']}")


def test_demo_selection_archives_the_losing_sibling_and_advances_the_engagement(api):
    """PRD §3.3: "First, the demo moves `SHORTLISTED → SELECTED`, its `selected_at` is
    stamped from the logical clock, and its `accrued_fee_cents` leaves the engagement's
    `committed_cents` and enters `spent_cents` — this pitch is now paid for."
    PRD §3.3: "Second, because a demo of this engagement reached `SELECTED`, the
    engagement advances `IN_DEMO → IN_PRODUCTION`."
    PRD §3.3: "Third, because the engagement left `IN_DEMO`, every sibling demo of that
    engagement whose status is `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED` or
    `SHORTLISTED` is moved to `ARCHIVED` — the four edges `DRAFT → ARCHIVED`,
    `SUBMITTED → ARCHIVED`, `REVISION_REQUESTED → ARCHIVED` and
    `SHORTLISTED → ARCHIVED` — processed in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/demo_selection_five_hop_release_lifts_posture_back_to_healthy
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=500_000)
    winner_composer = create_composer(index=0)
    loser_composer = create_composer(index=1)
    winner = pitch_demo(env["project"]["id"], winner_composer["id"],
                        title="Sunrise Pop", demo_fee_cents=150_000, submitted_length_seconds=60)
    loser = pitch_demo(env["project"]["id"], loser_composer["id"],
                       title="Night Drive", demo_fee_cents=230_000, submitted_length_seconds=60)
    submit_demo(winner["id"], winner_composer["id"])
    submit_demo(loser["id"], loser_composer["id"])
    validate_success(api.shortlist_demo(winner["id"], make_client_rep_headers(env["client"]["id"])))

    selected = validate_success(api.select_demo(
        winner["id"], make_client_rep_headers(env["client"]["id"])))
    assert selected["status"] == "SELECTED", f"Expected SELECTED, got {selected['status']}"
    assert_instant_equals(selected["selected_at"], "2026-09-01T00:00:00Z", "selected_at")

    project = get_project(env["project"]["id"])
    assert project["status"] == "IN_PRODUCTION", (
        f"Selection must advance the engagement to IN_PRODUCTION; got {project['status']}")
    archived = get_demo(loser["id"])
    assert archived["status"] == "ARCHIVED", (
        f"The losing sibling must be ARCHIVED; got {archived['status']}")


def test_released_sibling_reservation_lifts_the_posture_back_to_healthy(api):
    """PRD §3.3: "Fourth, because those siblings were archived, each one's
    `accrued_fee_cents` is released — for every archived sibling the engagement's
    `committed_cents` falls and its `available_cents` rises by that sibling's accrued
    amount."
    PRD §3.3: "Fifth, because `available_cents` changed, `budget_posture` is recomputed;
    if it becomes `HEALTHY`, every session call of the engagement sitting in
    `SUSPENDED_BUDGET` returns to `SCHEDULED`."
    PRD §2.7: "**These three buckets must sum to exactly `budget_cents` after every
    single request, with no drift.**"

    Design: Difficulty/transitive_cascade/demo_selection_five_hop_release_lifts_posture_back_to_healthy
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=500_000)
    winner_composer = create_composer(index=0)
    loser_composer = create_composer(index=1)
    winner = pitch_demo(env["project"]["id"], winner_composer["id"],
                        title="Sunrise Pop", demo_fee_cents=150_000, submitted_length_seconds=60)
    loser = pitch_demo(env["project"]["id"], loser_composer["id"],
                       title="Night Drive", demo_fee_cents=230_000, submitted_length_seconds=60)
    submit_demo(winner["id"], winner_composer["id"])
    submit_demo(loser["id"], loser_composer["id"])
    validate_success(api.shortlist_demo(winner["id"], make_client_rep_headers(env["client"]["id"])))

    before = get_project(env["project"]["id"])
    assert_ledger(before, committed=380_000, available=120_000, spent=0)
    assert before["budget_posture"] == "CONSTRAINED", (
        f"120000 * 100 is below 25 * 500000, so the posture starts CONSTRAINED; "
        f"got {before['budget_posture']}")

    validate_success(api.select_demo(winner["id"], make_client_rep_headers(env["client"]["id"])))

    after = get_project(env["project"]["id"])
    assert_ledger(after, committed=0, available=350_000, spent=150_000)
    assert after["budget_posture"] == "HEALTHY", (
        "Releasing the archived sibling's 230000 cents must lift the posture to HEALTHY; "
        f"got {after['budget_posture']}")
    assert get_demo(loser["id"])["status"] == "ARCHIVED"


def test_fourth_revision_request_reports_the_revision_ceiling(api):
    """PRD §3.3: "Two guards apply before any of that: a demo whose `revision_count` has
    already reached three rounds is refused with `ERR_DEMO_REVISION_LIMIT_REACHED`, and
    an engagement whose `available_cents` is below the surcharge is refused with
    `ERR_PROJECT_BUDGET_EXCEEDED`."
    PRD §2.5: "Checks are evaluated in the following fixed order, and the first one that
    fails ends the request; later checks are never reached."
    PRD §2.5: "**Revision ceiling.** On a client revision request, the demo's
    `revision_count` is still below the three-round cap — otherwise
    `ERR_DEMO_REVISION_LIMIT_REACHED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/revision_cap_business_constraint_outranks_budget_shortfall_business_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    env = _demo_at_revision_limit()
    before = get_project(env["project"]["id"])
    assert_ledger(before, committed=217_500, available=12_500, spent=0)
    assert before["available_cents"] < 22_500, (
        "The fixture must also be short of the 22500-cent surcharge so both guards fail")

    response = api.request_demo_revision(
        env["demo"]["id"], {"revision_note": "round four"},
        make_client_rep_headers(env["client"]["id"]))
    error = validate_error(response, ApiErrorId.ERR_DEMO_REVISION_LIMIT_REACHED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_PROJECT_BUDGET_EXCEEDED.value, (
        "The revision ceiling is judged before the funds check, so the budget error "
        "must never surface here")


def test_revision_ceiling_leaves_the_demo_and_the_ledger_untouched(api):
    """PRD §3.3: "Two guards apply before any of that: a demo whose `revision_count` has
    already reached three rounds is refused with `ERR_DEMO_REVISION_LIMIT_REACHED`, and
    an engagement whose `available_cents` is below the surcharge is refused with
    `ERR_PROJECT_BUDGET_EXCEEDED`."
    PRD §2.7: "**These three buckets must sum to exactly `budget_cents` after every
    single request, with no drift.**"

    Design: Difficulty/priority_pair_validation_conflict/revision_cap_business_constraint_outranks_budget_shortfall_business_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    env = _demo_at_revision_limit()

    validate_error(
        api.request_demo_revision(env["demo"]["id"], {"revision_note": "round four"},
                                  make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_DEMO_REVISION_LIMIT_REACHED.value, 422)

    demo = get_demo(env["demo"]["id"])
    assert demo["revision_count"] == 3, (
        f"The refused round must not increment the counter; got {demo['revision_count']}")
    assert demo["status"] == "SUBMITTED", f"Expected SUBMITTED, got {demo['status']}"
    assert demo["accrued_fee_cents"] == 217_500, (
        "Three flat 22500-cent surcharges on a 150000-cent fee give 217500; "
        f"got {demo['accrued_fee_cents']}")
    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=217_500, available=12_500, spent=0)


def test_resubmitting_an_already_submitted_demo_is_rejected(api):
    """PRD §3.3: "Submitting from any other status is refused with
    `ERR_DEMO_INVALID_STATE`."

    Design: Corner/state_machines/corner_submitting_an_already_submitted_demo_is_rejected
    """
    env = setup_engagement_in_demo(target_markets=["US_LOCAL"])
    composer = create_composer(index=0)
    demo = pitch_demo(env["project"]["id"], composer["id"], title="Cut One",
                      demo_fee_cents=100_000, submitted_length_seconds=30)
    submit_demo(demo["id"], composer["id"])

    validate_error(
        api.submit_demo(demo["id"], make_composer_headers(composer["id"])),
        ApiErrorId.ERR_DEMO_INVALID_STATE.value, 409)

    after = get_demo(demo["id"])
    assert after["status"] == "SUBMITTED", f"Expected SUBMITTED, got {after['status']}"
    assert after["revision_count"] == 0, (
        f"A refused re-submission must not touch revision_count; got {after['revision_count']}")


def test_selection_requires_a_shortlisted_demo(api):
    """PRD §3.3: "A `ClientRep` owning the engagement selects a demo that is
    `SHORTLISTED` while the engagement is `IN_DEMO`; selecting from any other demo
    status is refused with `ERR_DEMO_INVALID_STATE`."

    Design: Corner/state_machines/corner_select_requires_shortlisted_not_merely_submitted
    """
    env = setup_engagement_in_demo(budget_cents=4_000_000, target_markets=["US_LOCAL"])
    composer = create_composer(index=0)
    demo = pitch_demo(env["project"]["id"], composer["id"], title="Cut One",
                      demo_fee_cents=100_000, submitted_length_seconds=30)
    submit_demo(demo["id"], composer["id"])

    validate_error(
        api.select_demo(demo["id"], make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_DEMO_INVALID_STATE.value, 409)

    assert get_demo(demo["id"])["status"] == "SUBMITTED"
    project = get_project(env["project"]["id"])
    assert project["status"] == "IN_DEMO", f"Expected IN_DEMO, got {project['status']}"
    assert_ledger(project, committed=100_000, available=3_900_000, spent=0)


def test_selected_demo_cannot_be_sent_back_for_revision(api):
    """PRD §3.3: "The advertiser's representative may send a demo back from either
    `SUBMITTED → REVISION_REQUESTED` or `SHORTLISTED → REVISION_REQUESTED`, supplying a
    `revision_note`."
    PRD §2.5: "**Target state.** On every state-changing operation, the resource named
    in the path is in a status from which the requested transition is defined —
    otherwise `ERR_PROJECT_NOT_IN_BRIEFING`, `ERR_PROJECT_NOT_IN_DEMO`,
    `ERR_PROJECT_NOT_HOLDABLE`, `ERR_PROJECT_NOT_ON_HOLD`, `ERR_BRIEF_NOT_DRAFT`,
    `ERR_DEMO_INVALID_STATE`, `ERR_SESSION_CALL_INVALID_STATE`,
    `ERR_LICENSE_DEAL_INVALID_STATE`, `ERR_LICENSE_NOT_ACTIVE`,
    `ERR_LICENSE_NOT_RENEWABLE`, `ERR_DELIVERABLE_INVALID_STATE` or
    `ERR_CUE_ENTRY_ALREADY_VOIDED` (409)."

    Design: Corner/state_machines/corner_terminal_selected_demo_cannot_be_sent_back_for_revision
    """
    env = setup_engagement_in_production(target_markets=["US_LOCAL"], demo_fee_cents=100_000)

    validate_error(
        api.request_demo_revision(env["demo"]["id"], {"revision_note": "one more pass please"},
                                  make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_DEMO_INVALID_STATE.value, 409)

    demo = get_demo(env["demo"]["id"])
    assert demo["status"] == "SELECTED", f"Expected SELECTED, got {demo['status']}"
    assert demo["revision_count"] == 0
    assert demo["accrued_fee_cents"] == 100_000
    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=0, available=3_900_000, spent=100_000)
