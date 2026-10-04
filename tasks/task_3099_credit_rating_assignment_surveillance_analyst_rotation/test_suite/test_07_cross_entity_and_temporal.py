"""Cross-entity state dependencies, occupancy geometry and conserved compensation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_compensation_conservation,
    compensation_payload,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]
COMP = TEST_USERS["compensation_committee_headers"]
PA = TEST_USERS["platform_admin_headers"]

EXEMPTION_REASON = "Sector continuity required for the ongoing refinancing review."


def test_screening_a_request_under_an_unactivated_letter_is_refused(api):
    """PRD §3.2: "First, it validates that the parent engagement is `ACTIVE` —
    otherwise `ERR_ENGAGEMENT_NOT_ACTIVE` (HTTP 409)"
    PRD §3.1: "Only an `ACTIVE` letter unlocks `RatingRequest` intake under that
    engagement."

    Design: Difficulty/cross_entity_state_dependency/request_screening_requires_engagement_active
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", PA))
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Mike Aerospace Inc")
    letter = get_success_data(api_client.create_engagement_letter(
        fixtures.engagement_letter_payload(entity["id"]), EM))
    letter = get_success_data(api_client.submit_engagement_letter(letter["id"], EM))
    assert letter["status"] == "SIGNED"
    get_success_data(api_client.set_clock("2026-12-15T00:00:00Z", PA))
    request = fixtures.create_request(letter["id"], entity["id"])

    response = api_client.open_screening(request["id"], CO)
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE, 409)


def test_screening_refusal_leaves_both_entities_in_their_prior_states(api):
    """PRD §3.1: "Only an `ACTIVE` letter unlocks `RatingRequest` intake under
    that engagement."
    PRD §3.2: "Opening the compliance screening stage moves the request from
    `SUBMITTED` to `SCREENING`"

    Design: Difficulty/cross_entity_state_dependency/request_screening_requires_engagement_active
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", PA))
    methodology = fixtures.create_published_methodology()
    entity = fixtures.create_entity(methodology["id"], legal_name="Mike Aerospace Inc")
    letter = get_success_data(api_client.create_engagement_letter(
        fixtures.engagement_letter_payload(entity["id"]), EM))
    letter = get_success_data(api_client.submit_engagement_letter(letter["id"], EM))
    get_success_data(api_client.set_clock("2026-12-15T00:00:00Z", PA))
    request = fixtures.create_request(letter["id"], entity["id"])

    api_client.open_screening(request["id"], CO)

    letter_after = get_success_data(api_client.get_engagement_letter(letter["id"], EM))
    request_after = get_success_data(api_client.get_rating_request(request["id"], EM))
    assert letter_after["status"] == "SIGNED"
    assert request_after["request_status"] == "SUBMITTED"
    assert request_after["allocated_fee_cents"] == 0

    activated = validate_success(api_client.activate_engagement_letter(letter["id"], EM), 200)
    assert activated["status"] == "ACTIVE"
    screened = validate_success(api_client.open_screening(request["id"], CO), 200)
    assert screened["request_status"] == "SCREENING"


def test_an_adjacent_window_does_not_collide_with_the_prior_half_open_window(api):
    """PRD §3.3: "`window_start` inclusive and `window_end` exclusive."
    PRD §3.3: "Confirmation also requires the lead's new window to overlap no
    other non-`REVOKED` assignment of that same analyst, or it is rejected with
    `ERR_ANALYST_ASSIGNMENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/analyst_assignment_half_open_window_adjacency
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED"]
    )
    lead = fixtures.onboard_lead()
    support = fixtures.onboard_support()

    first = fixtures.setup_screened_team(requests[0]["id"], lead["id"], support["id"],
                                         window_start="2021-09-01T00:00:00Z",
                                         window_end="2027-03-01T00:00:00Z")
    fixtures.confirm_team(first["id"], requests[0]["id"])

    second = fixtures.setup_screened_team(
        requests[1]["id"], lead["id"], support["id"],
        window_start="2027-03-01T00:00:00Z", window_end="2027-09-01T00:00:00Z",
        rotation_exemption_granted=True, rotation_exemption_reason=EXEMPTION_REASON,
    )
    confirmed = fixtures.confirm_team(second["id"], requests[1]["id"])
    assert confirmed["status"] == "CONFIRMED"


def test_a_window_starting_one_second_inside_the_prior_window_collides(api):
    """PRD §3.3: "`window_start` inclusive and `window_end` exclusive."
    PRD §3.3: "Confirmation also requires the lead's new window to overlap no
    other non-`REVOKED` assignment of that same analyst, or it is rejected with
    `ERR_ANALYST_ASSIGNMENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/analyst_assignment_half_open_window_adjacency
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED", "REVOLVER"]
    )
    lead = fixtures.onboard_lead()
    support = fixtures.onboard_support()

    first = fixtures.setup_screened_team(requests[0]["id"], lead["id"], support["id"],
                                         window_start="2021-09-01T00:00:00Z",
                                         window_end="2027-03-01T00:00:00Z")
    fixtures.confirm_team(first["id"], requests[0]["id"])

    third = fixtures.setup_screened_team(
        requests[2]["id"], lead["id"], support["id"],
        window_start="2027-02-28T23:59:59Z", window_end="2027-06-01T00:00:00Z",
        rotation_exemption_granted=True, rotation_exemption_reason=EXEMPTION_REASON,
    )
    version = get_success_data(api_client.get_rating_request(requests[2]["id"], EM))["version"]
    response = api_client.confirm_team_assignment(
        third["id"], {"expected_rating_request_version": version}, CC)
    validate_error(response, ApiErrorId.ERR_ANALYST_ASSIGNMENT_OVERLAP, 409)

    unchanged = get_success_data(api_client.get_team_assignment(third["id"], EM))
    assert unchanged["status"] == "SCREENED"


def test_a_booking_inside_the_post_buffer_is_rejected(api):
    """PRD §3.7: "Every slot reserves a fixed preparation buffer of 30 minutes
    before the booking and a fixed wrap-up buffer of 30 minutes after it,
    recorded as `pre_buffer_minutes` and `post_buffer_minutes`."
    PRD §3.7: "A new booking whose interval falls inside another `BOOKED` slot's
    buffered interval on the same analyst is rejected with `ERR_REVIEW_SLOT_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/review_slot_closed_interval_with_buffers
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    analyst = fixtures.onboard_lead()
    review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_due_at="2027-01-05T00:00:00Z")
    fixtures.book_slot(analyst, review["id"],
                       slot_start="2027-01-01T09:00:00Z", slot_end="2027-01-01T11:00:00Z")

    response = api_client.create_review_slot(
        fixtures.review_slot_payload(
            analyst["id"], review["id"],
            slot_start="2027-01-01T11:15:00Z", slot_end="2027-01-01T12:00:00Z",
        ),
        fixtures.make_rating_analyst_headers(analyst["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_SLOT_OVERLAP, 409)


def test_a_booking_beyond_the_post_buffer_is_admitted(api):
    """PRD §3.7: "Every slot reserves a fixed preparation buffer of 30 minutes
    before the booking and a fixed wrap-up buffer of 30 minutes after it"
    PRD §3.7: "A slot is `BOOKED` when created"

    Design: Difficulty/resource_temporal_overlap/review_slot_closed_interval_with_buffers
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    analyst = fixtures.onboard_lead()
    review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_due_at="2027-01-05T00:00:00Z")
    original = fixtures.book_slot(analyst, review["id"],
                                  slot_start="2027-01-01T09:00:00Z", slot_end="2027-01-01T11:00:00Z")

    response = api_client.create_review_slot(
        fixtures.review_slot_payload(
            analyst["id"], review["id"],
            slot_start="2027-01-01T12:00:00Z", slot_end="2027-01-01T13:00:00Z",
        ),
        fixtures.make_rating_analyst_headers(analyst["id"]),
    )
    booked = validate_success(response, 201)
    assert booked["status"] == "BOOKED"

    untouched = get_success_data(api_client.get_review_slot(original["id"], EM))
    assert untouched["status"] == "BOOKED"


def test_cancelling_a_slot_releases_its_buffered_interval_for_rebooking(api):
    """PRD §3.7: "A slot is `BOOKED` when created, can be cancelled from that
    state — a cancel against a non-`BOOKED` slot is rejected with
    `ERR_SLOT_NOT_BOOKED` (HTTP 409) — and moves to `CANCELLED` on cancellation,
    releasing its buffered interval so it no longer blocks new bookings."

    Design: Corner/endpoints/review_slot_cancel_releases_the_buffered_interval
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    analyst = fixtures.onboard_lead()
    review = fixtures.create_review_for_entity(
        entity["id"], analyst, review_due_at="2026-12-01T00:00:00Z")
    slot = fixtures.book_slot(analyst, review["id"],
                              slot_start="2026-12-01T09:00:00Z", slot_end="2026-12-01T11:00:00Z")

    cancelled = validate_success(
        api_client.cancel_review_slot(slot["id"], fixtures.make_rating_analyst_headers(analyst["id"])),
        200,
    )
    assert cancelled["status"] == "CANCELLED"

    rebooked = validate_success(
        api_client.create_review_slot(
            fixtures.review_slot_payload(
                analyst["id"], review["id"],
                slot_start="2026-12-01T09:00:00Z", slot_end="2026-12-01T11:00:00Z",
            ),
            fixtures.make_rating_analyst_headers(analyst["id"]),
        ),
        201,
    )
    assert rebooked["status"] == "BOOKED"


def test_compensation_total_before_revision_follows_the_accuracy_only_formula(api):
    """PRD §3.9: "The `accuracy_bonus_cents` is the base salary multiplied by the
    amount by which `rating_accuracy_score` exceeds a floor of 70 — floored at
    zero when the score is at or below 70 — and divided by 200, rounded half-up
    to whole cents"
    PRD §3.9: "Because the fee bonus is unconditionally zero, the
    `compensation_separation_pct` — the fraction of total compensation that is
    fee-independent — is always 1.0"

    Design: Difficulty/compensating_invariant/compensation_total_conserved_across_revision
    """
    methodology = fixtures.create_published_methodology()
    analyst = fixtures.onboard_lead()

    record = get_success_data(api_client.create_compensation_record(
        compensation_payload(analyst["id"], base_salary_cents=12_000_000,
                             rating_accuracy_score=80), COMP))
    approved = get_success_data(api_client.approve_compensation_record(record["id"], COMP))
    assert approved["accuracy_bonus_cents"] == 600_000
    assert approved["total_compensation_cents"] == 12_600_000
    assert approved["fee_generation_bonus_cents"] == 0
    assert approved["compensation_separation_pct"] == 1.0
    assert_compensation_conservation(approved)


def test_revising_an_approved_record_conserves_the_total(api):
    """PRD §3.9: "returning an approved record to `DRAFT` for revision recomputes
    the total with the same conserved formula"
    PRD §3.9: "the total is invariant under any change to the engagements the
    analyst touched"

    Design: Difficulty/compensating_invariant/compensation_total_conserved_across_revision
    """
    methodology = fixtures.create_published_methodology()
    analyst = fixtures.onboard_lead()

    record = get_success_data(api_client.create_compensation_record(
        compensation_payload(analyst["id"], base_salary_cents=12_000_000,
                             rating_accuracy_score=80), COMP))
    approved = get_success_data(api_client.approve_compensation_record(record["id"], COMP))
    total_before = approved["total_compensation_cents"]

    revised = get_success_data(api_client.revise_compensation_record(record["id"], COMP))
    assert revised["status"] == "DRAFT"
    assert revised["total_compensation_cents"] == total_before
    assert revised["accuracy_bonus_cents"] == 600_000
    assert revised["fee_generation_bonus_cents"] == 0
    assert_compensation_conservation(revised)


def test_a_sixty_month_lead_streak_blocks_the_next_team_confirmation(api):
    """PRD §3.3: "Confirmation is refused with `ERR_ANALYST_ROTATION_REQUIRED`
    (HTTP 409) when the lead's `consecutive_lead_months` has reached sixty months
    — the boundary is inclusive, so exactly sixty months is not eligible —
    unless the assignment carries a granted rotation exemption."
    PRD §3.3: "the end is the latest `window_start` among `CONFIRMED` rows, or
    the current instant when any `CONFIRMED` row is open-ended."

    Design: Difficulty/cross_entity_state_dependency/team_confirmation_gated_by_analyst_rotation_state
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED"]
    )
    lead = fixtures.onboard_lead()
    support = fixtures.onboard_support()

    # The streak's start bound is `assigned_at` — server-stamped at proposal
    # time on the logical clock (2026-12-15) — not the client-supplied
    # `window_start`; the end bound is the CONFIRMED row's `window_start`. The
    # occupancy windows below are therefore placed far enough ahead of the
    # proposal instant for the streak to reach the inclusive sixty-month gate.
    first = fixtures.setup_screened_team(requests[0]["id"], lead["id"], support["id"],
                                         window_start="2031-12-15T00:00:00Z",
                                         window_end="2032-06-15T00:00:00Z")
    fixtures.confirm_team(first["id"], requests[0]["id"])

    lead_after_first = get_success_data(api_client.get_analyst(lead["id"], EM))
    assert lead_after_first["consecutive_lead_months"] >= 60
    assert lead_after_first["rotation_eligible"] is False

    second = fixtures.setup_screened_team(requests[1]["id"], lead["id"], support["id"],
                                          window_start="2032-06-16T00:00:00Z",
                                          window_end="2032-12-01T00:00:00Z")
    version = get_success_data(api_client.get_rating_request(requests[1]["id"], EM))["version"]
    response = api_client.confirm_team_assignment(
        second["id"], {"expected_rating_request_version": version}, CC)
    validate_error(response, ApiErrorId.ERR_ANALYST_ROTATION_REQUIRED, 409)


def test_the_blocked_confirmation_does_not_advance_the_assignment(api):
    """PRD §3.3: "Confirmation is refused with `ERR_ANALYST_ROTATION_REQUIRED`
    (HTTP 409) when the lead's `consecutive_lead_months` has reached sixty months"
    PRD §3.3: "Confirmation by a `CommitteeChair` is the point at which rotation
    becomes real, and it takes the assignment from `SCREENED` to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/team_confirmation_gated_by_analyst_rotation_state
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED"]
    )
    lead = fixtures.onboard_lead()
    support = fixtures.onboard_support()

    first = fixtures.setup_screened_team(requests[0]["id"], lead["id"], support["id"],
                                         window_start="2031-12-15T00:00:00Z",
                                         window_end="2032-06-15T00:00:00Z")
    fixtures.confirm_team(first["id"], requests[0]["id"])
    second = fixtures.setup_screened_team(requests[1]["id"], lead["id"], support["id"],
                                          window_start="2032-06-16T00:00:00Z",
                                          window_end="2032-12-01T00:00:00Z")
    version = get_success_data(api_client.get_rating_request(requests[1]["id"], EM))["version"]
    api_client.confirm_team_assignment(second["id"], {"expected_rating_request_version": version}, CC)

    blocked = get_success_data(api_client.get_team_assignment(second["id"], EM))
    assert blocked["status"] == "SCREENED"