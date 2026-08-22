"""Enrolling performers and driving permit applications through the review desk."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_performer, assert_application,
    create_performer_payload, create_application_payload, decision_payload,
    revision_payload,
    create_zone, create_performer, create_application, submit_application,
    review_application, decide_application, revise_application,
    read_application, application_version,
    make_officer_headers, make_performer_headers,
    OFFICER_ALPHA, OFFICER_BETA,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------

def test_enrolling_a_performer_without_email_is_rejected(api):
    """PRD §3.2: "A `PermitOfficer` performs the city ID check in person and
    then creates the performer record with a `legal_name` as printed on the
    identity document, a `stage_name` for the placard, a contact `email` and an
    `act_type`."
    PRD §2.6: "The request body is well formed, otherwise `ERR_INVALID_REQUEST`.
    Applies to every POST endpoint."

    Design: Corner/entities/corner_performer_missing_required_email_returns_invalid_request
    """
    resp = api.create_performer(
        {"legal_name": "Ada Vance", "stage_name": "Ada V",
         "act_type": "ACOUSTIC_MUSIC"},
        make_officer_headers())
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_computed_and_system_keys_on_enrolment_are_silently_ignored(api):
    """PRD §2.6: "Body keys that are not in an endpoint's declared input list —
    including any attempt to set a computed or system-owned field such as `id`,
    `version`, `status`, `conduct_score` or `amount_due_cents` — are silently
    ignored and never raise an error."
    PRD §2.4: "Every resource is identified by an `id` that the server mints as
    a UUID. Identifiers carry no type prefix and are never supplied by the
    client; a client that sends `id` in a request body has that key ignored
    rather than honoured."
    PRD §3.2: "A freshly enrolled performer starts clean: `conduct_score` 100,
    `renewal_conduct_score` 100, `standing` `GOOD`, `upheld_complaint_count` 0
    and `premium_wins_this_season` 0."

    Design: Corner/entities/corner_performer_computed_and_system_fields_input_ignored
    """
    resp = api.create_performer(
        {"legal_name": "Ada Vance", "stage_name": "Ada V",
         "email": "ada@example.org", "act_type": "ACOUSTIC_MUSIC",
         "conduct_score": 10, "standing": "BARRED", "id": "not-a-uuid"},
        make_officer_headers())
    performer = validate_success(resp, 201)
    assert_performer(performer)
    assert performer["conduct_score"] == 100
    assert performer["renewal_conduct_score"] == 100
    assert performer["standing"] == "GOOD"
    assert performer["upheld_complaint_count"] == 0
    assert performer["premium_wins_this_season"] == 0
    assert performer["id"] != "not-a-uuid", \
        "a client-supplied id must be ignored, not honoured"


def test_duplicate_performer_email_is_refused_case_insensitively(api):
    """PRD §3.2: "Email addresses are unique across all performers and are
    compared case-insensitively; a duplicate is refused with
    `ERR_PERFORMER_EMAIL_TAKEN`."

    Design: Corner/entities/corner_performer_email_uniqueness_enforced
    """
    first = create_performer(legal_name="Ada Vance", stage_name="Ada V",
                             email="ada@example.org", act_type="ACOUSTIC_MUSIC")
    resp = api.create_performer(
        create_performer_payload(legal_name="Ada Vance II", stage_name="Ada Two",
                                 email="ADA@example.org", act_type="VISUAL_ART"),
        make_officer_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PERFORMER_EMAIL_TAKEN)

    reread = validate_success(api.get_performer(first["id"], make_officer_headers()))
    assert reread["act_type"] == "ACOUSTIC_MUSIC", \
        "the incumbent performer must be untouched by the refused enrolment"


# ---------------------------------------------------------------------------
# Opening and lodging an application
# ---------------------------------------------------------------------------

def test_new_application_opens_in_draft_with_empty_counters(api):
    """PRD §3.2: "An application is opened in `DRAFT` by supplying
    `performer_id`, the `requested_zone_id` naming the district the applicant
    wants to work, the `season_year` the permit would cover (a calendar year
    between 2025 and 2035 inclusive), and the `requested_act_type` that will
    drive the fee."
    PRD §3.2: "A new application starts with `revision_count` 0,
    `requires_audition` false, `assessed_fee_cents` 0, and null values for
    `change_request_reason`, `reviewed_by_user_id`, `decided_by_user_id`,
    `submitted_at` and `decided_at`."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row, whether the
    mutation was requested directly by a client or produced as a side effect of
    an operation on another resource."

    Design: Corner/state_machines/corner_application_starts_in_draft
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    performer = create_performer(legal_name="Bo Kestrel", stage_name="Bo K",
                                 email="bo@example.org",
                                 act_type="AMPLIFIED_MUSIC")
    resp = api.create_application(
        create_application_payload(performer["id"], zone["id"], season_year=2026,
                                   requested_act_type="AMPLIFIED_MUSIC",
                                   amplification_requested=True),
        make_performer_headers(performer["id"]))
    application = validate_success(resp, 201)
    assert_application(application)
    assert application["status"] == "DRAFT"
    assert application["revision_count"] == 0
    assert application["requires_audition"] is False, \
        "requires_audition stays false until the application is lodged"
    assert application["submitted_at"] is None
    assert application["assessed_fee_cents"] == 0
    assert application["version"] == 1


def test_second_live_application_for_the_same_season_is_refused(api):
    """PRD §3.2: "A performer may hold only one live application per season: if
    that performer already has another application for the same `season_year`
    whose status is anything other than `REJECTED`, the new one is refused with
    `ERR_DUPLICATE_ACTIVE_APPLICATION`, and the same uniqueness condition is
    re-evaluated when the application is lodged."

    Design: Corner/validations/corner_second_active_application_for_the_same_season_rejected
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    performer = create_performer()
    create_application(performer["id"], zone["id"], season_year=2026,
                       requested_act_type="ACOUSTIC_MUSIC")

    dup = api.create_application(
        create_application_payload(performer["id"], zone["id"], season_year=2026,
                                   requested_act_type="VISUAL_ART"),
        make_performer_headers(performer["id"]))
    assert dup.status_code == 409, f"Expected 409, got {dup.status_code}"
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION)

    other_season = api.create_application(
        create_application_payload(performer["id"], zone["id"], season_year=2027,
                                   requested_act_type="VISUAL_ART"),
        make_performer_headers(performer["id"]))
    created = validate_success(other_season, 201)
    assert created["season_year"] == 2027, \
        "the uniqueness rule is scoped to one season_year"

    _, meta = validate_paginated(api.list_applications(
        make_officer_headers(), params={"performer_id": performer["id"]}))
    assert meta["total_count"] == 2


def test_review_of_a_draft_application_is_an_invalid_state(api):
    """PRD §3.2: "When an officer picks the application up, the same review
    action lands in two different places purely on that computed flag: an
    application whose `requires_audition` is false goes `SUBMITTED →
    UNDER_REVIEW` and may be decided directly, while one whose
    `requires_audition` is true goes `SUBMITTED → AUDITION_REQUIRED` and cannot
    be approved until a panel has passed it."
    PRD §2.6: "The target resource is in a state from which the requested
    transition is declared, otherwise `ERR_INVALID_STATE`. This applies to every
    action endpoint: submit, review, revise, decide, finalize, pay, renew,
    revoke, reinstate, enter a draw, execute a draw, cancel a booking, triage,
    adjudicate and activate a closure."

    Design: Corner/state_machines/corner_review_from_draft_rejected_as_invalid_state
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    performer = create_performer(legal_name="Bo Kestrel", stage_name="Bo K",
                                 email="bo@example.org",
                                 act_type="AMPLIFIED_MUSIC")
    application = create_application(performer["id"], zone["id"],
                                     requested_act_type="AMPLIFIED_MUSIC",
                                     amplification_requested=True)

    resp = api.review_application(application["id"], make_officer_headers())
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = read_application(application["id"])
    assert reread["status"] == "DRAFT"
    assert reread["reviewed_by_user_id"] is None


def test_second_submit_of_the_same_application_is_an_invalid_state(api):
    """PRD §3.2: "Lodging the application — the applicant's own act, permitted
    only to the `Performer` who owns it — moves it `DRAFT → SUBMITTED`, stamps
    `submitted_at` with the program clock, and recomputes the
    `requires_audition` flag."
    PRD §3.2: "That flag is true when any one of three things holds: the
    `requested_act_type` is `AMPLIFIED_MUSIC` or `CIRCUS_SKILL`, or
    `amplification_requested` is true, or the applicant's `standing` is
    currently `WATCH`."
    PRD §2.6: "The target resource is in a state from which the requested
    transition is declared, otherwise `ERR_INVALID_STATE`. This applies to every
    action endpoint: submit, review, revise, decide, finalize, pay, renew,
    revoke, reinstate, enter a draw, execute a draw, cancel a booking, triage,
    adjudicate and activate a closure."

    Design: Corner/state_machines/corner_second_submit_rejected_as_invalid_state
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    performer = create_performer(legal_name="Bo Kestrel", stage_name="Bo K",
                                 email="bo@example.org",
                                 act_type="AMPLIFIED_MUSIC")
    application = create_application(performer["id"], zone["id"],
                                     requested_act_type="AMPLIFIED_MUSIC",
                                     amplification_requested=True)
    submitted = submit_application(application["id"], performer["id"])
    version_after_submit = submitted["version"]

    resp = api.submit_application(application["id"],
                                  make_performer_headers(performer["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = read_application(application["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["version"] == version_after_submit, \
        "a refused submit must not advance the application's version"
    assert reread["requires_audition"] is True


def test_change_request_needs_a_note_while_approval_does_not(api):
    """PRD §3.4: "An officer resolves an application by supplying an `outcome`,
    which is `APPROVED`, `REJECTED` or `CHANGES_REQUESTED`, together with an
    optional `decision_note` that becomes mandatory on the change-request
    branch."
    PRD §2.6: "Well-formedness at step 6 means: every required field is present;
    every enumerated value is a member of its declared set; every integer sits
    inside its declared range; `end_at` is strictly after `start_at`; `ends_at`
    is strictly after `starts_at`; `entry_deadline_at` is strictly before
    `slot_start_at`; `decision_note` is present and non-empty when the decision
    outcome is `CHANGES_REQUESTED`; and the `season_year` supplied on a renewal
    equals the permit's current `season_year` plus one."

    Design: Corner/validations/corner_decision_note_required_only_for_changes_requested
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    performer = create_performer()
    application = create_application(performer["id"], zone["id"])
    submit_application(application["id"], performer["id"])
    review_application(application["id"])

    noteless = api.decide_application(application["id"],
                                      decision_payload("CHANGES_REQUESTED"),
                                      make_officer_headers(OFFICER_BETA))
    assert noteless.status_code == 400, f"Expected 400, got {noteless.status_code}"
    validate_error(noteless, ApiErrorId.ERR_INVALID_REQUEST)
    assert read_application(application["id"])["status"] == "UNDER_REVIEW"

    approved = api.decide_application(application["id"],
                                      decision_payload("APPROVED"),
                                      make_officer_headers(OFFICER_BETA))
    data = validate_success(approved, 200)
    assert data["status"] == "APPROVED", \
        "an APPROVED decision needs no decision_note"

    _, meta = validate_paginated(api.list_permits(
        make_officer_headers(), params={"application_id": application["id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine /
#          application_revision_loop_cycles_back_to_submitted_until_limit
# ---------------------------------------------------------------------------

def _application_in_changes_requested():
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    performer = create_performer()
    application = create_application(performer["id"], zone["id"],
                                     requested_act_type="ACOUSTIC_MUSIC")
    submit_application(application["id"], performer["id"])
    review_application(application["id"], OFFICER_ALPHA)
    decide_application(application["id"], "CHANGES_REQUESTED",
                       "Attach the public liability certificate", OFFICER_BETA)
    return performer, application


def test_revision_loop_returns_the_application_to_submitted_twice(api):
    """PRD §3.2: "An accepted revision applies the overrides, increases
    `revision_count` by 1, recomputes `requires_audition` from the post-override
    values, stamps `submitted_at` with the clock, clears `change_request_reason`
    back to null, cancels any sitting still `SCHEDULED` on this application, and
    returns the application to `SUBMITTED`."
    PRD §3.2: "This is the loop that gives the application machine its cycle:
    `CHANGES_REQUESTED → SUBMITTED → UNDER_REVIEW → CHANGES_REQUESTED`, up to
    twice."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_cycles_back_to_submitted_until_limit
    """
    performer, application = _application_in_changes_requested()

    first = revise_application(application["id"], performer["id"],
                               application_version(application["id"]))
    assert first["status"] == "SUBMITTED"
    assert first["revision_count"] == 1
    assert first["change_request_reason"] is None

    review_application(application["id"], OFFICER_ALPHA)
    decide_application(application["id"], "CHANGES_REQUESTED",
                       "Certificate expired last month", OFFICER_BETA)

    second = revise_application(application["id"], performer["id"],
                                application_version(application["id"]))
    assert second["status"] == "SUBMITTED"
    assert second["revision_count"] == 2, \
        f"second accepted revision must climb to 2, got {second['revision_count']}"


def test_third_change_request_is_refused_once_both_revisions_are_used(api):
    """PRD §3.2: "That routing requires a non-empty `decision_note`, which is
    copied verbatim onto the application as `change_request_reason`, and it
    requires that `revision_count` is still below the allowance of two; a change
    request issued when the applicant has already used both revisions is refused
    with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/application_revision_loop_cycles_back_to_submitted_until_limit
    """
    performer, application = _application_in_changes_requested()

    revise_application(application["id"], performer["id"],
                       application_version(application["id"]))
    review_application(application["id"], OFFICER_ALPHA)
    decide_application(application["id"], "CHANGES_REQUESTED",
                       "Certificate expired last month", OFFICER_BETA)
    revise_application(application["id"], performer["id"],
                       application_version(application["id"]))
    review_application(application["id"], OFFICER_ALPHA)

    third = api.decide_application(
        application["id"],
        decision_payload("CHANGES_REQUESTED", "Third pass"),
        make_officer_headers(OFFICER_BETA))
    assert third.status_code == 409, f"Expected 409, got {third.status_code}"
    validate_error(third, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED)

    reread = read_application(application["id"])
    assert reread["status"] == "UNDER_REVIEW", \
        "the refused change request leaves the application where it was"
    assert reread["revision_count"] == 2
    assert reread["change_request_reason"] is None


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers /
#          corner_stale_expected_application_version_rejected_on_revision
# ---------------------------------------------------------------------------

def test_stale_expected_application_version_is_rejected_on_a_revision(api):
    """PRD §2.7: "Filing a revision on a permit application requires
    `expected_application_version`, carrying the `version` the client last
    observed on that application. If it does not equal the application's current
    `version`, the revision is rejected with `ERR_STALE_APPLICATION_VERSION` and
    HTTP 412."
    PRD §3.2: "An accepted revision applies the overrides, increases
    `revision_count` by 1, recomputes `requires_audition` from the post-override
    values, stamps `submitted_at` with the clock, clears `change_request_reason`
    back to null, cancels any sitting still `SCHEDULED` on this application, and
    returns the application to `SUBMITTED`."

    Design: Corner/cross_cutting_layers/corner_stale_expected_application_version_rejected_on_revision
    """
    performer, application = _application_in_changes_requested()
    current = application_version(application["id"])

    stale = api.revise_application(
        application["id"], revision_payload(current - 1),
        make_performer_headers(performer["id"]))
    assert stale.status_code == 412, f"Expected 412, got {stale.status_code}"
    validate_error(stale, ApiErrorId.ERR_STALE_APPLICATION_VERSION)

    after_refusal = read_application(application["id"])
    assert after_refusal["status"] == "CHANGES_REQUESTED"
    assert after_refusal["revision_count"] == 0
    assert after_refusal["version"] == current, \
        "a rejected revision must not advance the application's version"

    fresh = api.revise_application(
        application["id"],
        revision_payload(current, amplification_requested=False),
        make_performer_headers(performer["id"]))
    accepted = validate_success(fresh, 200)
    assert accepted["status"] == "SUBMITTED"
    assert accepted["revision_count"] == 1
    assert accepted["change_request_reason"] is None
