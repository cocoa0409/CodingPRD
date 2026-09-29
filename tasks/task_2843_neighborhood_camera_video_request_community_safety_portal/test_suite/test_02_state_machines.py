"""State transitions: which moves the portal accepts, and what a refused move leaves behind.

Each test here walks one declared transition of one entity — an agency's
onboarding and discipline, a canvass area's single lock, a video request's two
initial states, a community post's flag threshold — and then pins the row's
final state, its derived counters and its ``version``. Where a move is refused,
the refused row is read back afterwards to show that the rejection wrote
nothing: the state and the ``version`` are exactly where the last accepted write
left them.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    PLATFORM_ADMIN_HEADERS,
    make_agency_admin_headers,
    make_officer_headers,
    make_resident_headers,
)

# The note and agreement version an approval stores verbatim on the agency row.
REVIEWER_NOTE = "MOU on file; CJIS attestation received."
AGREEMENT_VERSION = "MOU-2026.3"
REJECTION_NOTE = "No MOU and no CJIS attestation."


# ── Local setup this file's scenarios need ─────────────────────────────────

def _canvass_world(api: ApiClient) -> Dict[str, Any]:
    """An onboarded agency with a device floor of three, one requester officer
    and three camera-owning households at the standard grid points."""
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    world["households"] = fixtures.seed_residents_with_devices(api)
    return world


def _rejected_agency(api: ApiClient) -> Dict[str, Any]:
    """An applicant whose onboarding review was a rejection, so it stands in the
    terminal REJECTED posture at version 2."""
    applicant = fixtures.register_agency(
        api, name="Declined Constabulary", jurisdiction_code="DC-001"
    )
    rejected = validate_success(
        api.review_agency_onboarding(
            applicant["id"],
            {
                "decision": k.ONBOARDING_DECISION_REJECT,
                "reviewer_note": REJECTION_NOTE,
            },
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )
    return {"applicant": applicant, "rejected": rejected, "agency_id": applicant["id"]}


def _feed_world(api: ApiClient) -> Dict[str, Any]:
    """One author and two other residents, none of whom wants proximity alerts,
    plus one published post carrying no classifier signals at all."""
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    first_flagger = fixtures.register_resident(
        api,
        display_name="Flagger One",
        email="f1@example.test",
        home_x_m=10,
        home_y_m=0,
        alert_radius_m=0,
    )
    second_flagger = fixtures.register_resident(
        api,
        display_name="Flagger Two",
        email="f2@example.test",
        home_x_m=20,
        home_y_m=0,
        alert_radius_m=0,
    )
    post = fixtures.create_post(
        api,
        author["id"],
        body="A parked van has been idling outside the corner shop since Tuesday.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
    )
    return {
        "author_id": author["id"],
        "first_flagger_id": first_flagger["id"],
        "second_flagger_id": second_flagger["id"],
        "post": post,
        "post_id": post["id"],
    }


# ── Agency onboarding ─────────────────────────────────────────────────────

def test_onboarding_approval_stores_the_agreement_and_moves_the_agency_onboarded(
    api: ApiClient, clock: str
) -> None:
    """Approving an applicant records the note and the agreement version and advances the agency one version.

    PRD: "A newly registered applicant lands in `PENDING_REVIEW` with `version` 1, `open_request_count` and `requests_submitted_count` both at 0, and `latest_report_id` null."
    PRD: "Approval moves the agency `PENDING_REVIEW → ONBOARDED` and stores both the note and the agreement version on the row."
    PRD: "Either way the agency's `version` advances by 1."

    Design: Corner/state_machines/agency_onboarding_review_approve_applies_side_effects
    """
    applicant = fixtures.register_agency(api, min_device_threshold=3)
    assert applicant["status"] == k.AGENCY_STATUS_PENDING_REVIEW
    assert applicant["version"] == 1
    assertions.assert_zero_counters(
        applicant, "open_request_count", "requests_submitted_count"
    )
    assertions.assert_nulls(applicant, "latest_report_id")

    reviewed = validate_success(
        api.review_agency_onboarding(
            applicant["id"],
            f.onboarding_review_payload(
                decision=k.ONBOARDING_DECISION_APPROVE,
                reviewer_note=REVIEWER_NOTE,
                onboarding_agreement_version=AGREEMENT_VERSION,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )
    assert reviewed["status"] == k.AGENCY_STATUS_ONBOARDED
    assert reviewed["reviewer_note"] == REVIEWER_NOTE
    assert reviewed["onboarding_agreement_version"] == AGREEMENT_VERSION
    assertions.assert_version_advanced(reviewed, applicant["version"])

    stored = fixtures.read_agency(api, applicant["id"])
    assertions.assert_subset(
        stored,
        {
            "status": k.AGENCY_STATUS_ONBOARDED,
            "reviewer_note": REVIEWER_NOTE,
            "onboarding_agreement_version": AGREEMENT_VERSION,
            "version": 2,
            "open_request_count": 0,
            "requests_submitted_count": 0,
        },
    )


def test_officer_enrolment_is_refused_until_the_agency_is_onboarded(
    api: ApiClient, clock: str
) -> None:
    """An officer may not be attached to an applicant still under review, and lands with both duty counters at zero once it is onboarded.

    PRD: "Officers may only be attached to an agency that is already `ONBOARDED`; an attempt against an agency in `PENDING_REVIEW`, `SUSPENDED`, `REJECTED` or `REVOKED` is refused with `ERR_AGENCY_NOT_ONBOARDED`."
    PRD: "New officers begin with `requests_submitted_count` and `audits_completed_count` at 0; the first counts the requests they have pushed into `SOLICITING`, the second counts the requests they have cleared or escalated."

    Design: Corner/state_machines/agency_onboarding_review_approve_applies_side_effects
    """
    applicant = fixtures.register_agency(api, min_device_threshold=3)
    payload = f.officer_payload(
        applicant["id"],
        badge_number="B-100",
        full_name="Officer Vale",
        duty_role=k.DUTY_ROLE_REQUESTER,
    )

    refused = api.create_officer(payload, make_agency_admin_headers(applicant["id"]))
    validate_error(refused, ApiErrorId.AGENCY_NOT_ONBOARDED.value, 409)

    untouched = fixtures.read_agency(api, applicant["id"])
    assert untouched["status"] == k.AGENCY_STATUS_PENDING_REVIEW
    assertions.assert_version_unchanged(untouched, applicant["version"])

    fixtures.review_onboarding(api, applicant["id"])
    officer = validate_success(
        api.create_officer(payload, make_agency_admin_headers(applicant["id"])), 201
    )
    assert officer["agency_id"] == applicant["id"]
    assert officer["duty_role"] == k.DUTY_ROLE_REQUESTER
    assertions.assert_zero_counters(
        officer, "requests_submitted_count", "audits_completed_count"
    )
    assert officer["version"] == 1


# ── Locking a canvass area ────────────────────────────────────────────────

def test_second_lock_of_the_same_area_is_refused_as_already_locked(
    api: ApiClient, clock: str
) -> None:
    """Locking happens exactly once: the second attempt is refused and the frozen roster and threshold stay put.

    PRD: "Locking requires the area to still be in `DRAFT` — a second attempt is refused with `ERR_AREA_ALREADY_LOCKED` — requires the owning agency to be `ONBOARDED`, requires the acting officer to be the one recorded in `created_by_officer_id`, and requires that officer's `duty_role` to be either `REQUESTER` or `DUAL_ROLE`."
    PRD: "Locking writes `locked_at` from the logical clock, moves the area `DRAFT → LOCKED`, and advances `version` by 1."
    PRD: "Locking also freezes the area's **minimum-participation threshold** into `effective_min_devices`, and this number is never recomputed afterwards — the submission gate re-reads it, it does not re-derive it."

    Design: Corner/state_machines/request_area_second_lock_returns_already_locked
    """
    world = _canvass_world(api)
    officer_headers = make_officer_headers(world["officer_id"])
    area = fixtures.create_area(api, world["agency_id"], world["officer_id"])
    assert area["status"] == k.AREA_STATUS_DRAFT

    locked = validate_success(api.lock_request_area(area["id"], officer_headers), 200)
    assert locked["status"] == k.AREA_STATUS_LOCKED
    assert locked["effective_min_devices"] == 3
    assert locked["eligible_device_count"] == 3
    assertions.assert_version_advanced(locked, area["version"])
    assertions.assert_instant(locked["locked_at"], clock, "locked_at")

    refused = api.lock_request_area(area["id"], officer_headers)
    validate_error(refused, ApiErrorId.AREA_ALREADY_LOCKED.value, 409)

    after = fixtures.read_area(api, area["id"])
    assert after["status"] == k.AREA_STATUS_LOCKED
    assertions.assert_version_unchanged(after, locked["version"])
    assert after["effective_min_devices"] == 3
    assert after["eligible_device_count"] == 3
    assertions.assert_instant(after["locked_at"], locked["locked_at"], "locked_at")


def test_lock_by_an_officer_who_did_not_draw_the_area_is_refused(
    api: ApiClient, clock: str
) -> None:
    """The lock is bound to the officer recorded on the area, so a colleague at the same agency is refused and the area stays in draft.

    PRD: "Locking requires the area to still be in `DRAFT` — a second attempt is refused with `ERR_AREA_ALREADY_LOCKED` — requires the owning agency to be `ONBOARDED`, requires the acting officer to be the one recorded in `created_by_officer_id`, and requires that officer's `duty_role` to be either `REQUESTER` or `DUAL_ROLE`."
    PRD: "For entity-backed roles, the acting identity owns the resource being written — otherwise `ERR_IDENTITY_MISMATCH`."

    Design: Corner/state_machines/lock_by_officer_who_did_not_create_the_area_rejected
    """
    world = _canvass_world(api)
    colleague = fixtures.create_officer(
        api,
        world["agency_id"],
        badge_number="B-200",
        full_name="Officer Quill",
        duty_role=k.DUTY_ROLE_REQUESTER,
    )
    area = fixtures.create_area(api, world["agency_id"], world["officer_id"])
    assert area["created_by_officer_id"] == world["officer_id"]

    refused = api.lock_request_area(area["id"], make_officer_headers(colleague["id"]))
    validate_error(refused, ApiErrorId.IDENTITY_MISMATCH.value, 403)

    still_draft = fixtures.read_area(api, area["id"])
    assert still_draft["status"] == k.AREA_STATUS_DRAFT
    assertions.assert_version_unchanged(still_draft, area["version"])
    assertions.assert_instant(still_draft["locked_at"], area["locked_at"], "locked_at")
    assert still_draft["effective_min_devices"] == area["effective_min_devices"]
    assert still_draft["eligible_device_count"] == area["eligible_device_count"]

    locked = validate_success(
        api.lock_request_area(area["id"], make_officer_headers(world["officer_id"])), 200
    )
    assert locked["status"] == k.AREA_STATUS_LOCKED
    assert locked["eligible_device_count"] == 3
    assertions.assert_version_advanced(locked, area["version"])


# ── A video request's two initial states ──────────────────────────────────

def test_new_video_request_starts_in_draft_with_justification_pending(
    api: ApiClient, clock: str
) -> None:
    """A freshly opened request sits at the initial state of both of its dimensions at once, with every counter at zero.

    PRD: "On success the request is created with `lifecycle_state` `DRAFT` and `compliance_state` `JUSTIFICATION_PENDING`, its `agency_id` copied from the area, its `submitting_officer_id` stamped from the acting officer's identity, `auditor_officer_id` null, `justification_text`, `statutory_basis`, `justification_logged_at`, `audit_note`, `withdraw_reason`, `submitted_at` and `expires_at` all null, every solicitation counter — `solicitation_count`, `pending_count`, `shared_count`, `declined_count`, `expired_count`, `withdrawn_count` and `shared_clip_count` — at 0, and `provisional_share_rate_bps` at 0."

    Design: Corner/state_machines/video_request_starts_in_draft_and_justification_pending
    """
    world = _canvass_world(api)
    area = fixtures.seed_locked_area(api, world["agency_id"], world["officer_id"])

    request = validate_success(
        api.create_video_request(
            f.video_request_payload(area["id"], area["version"], case_number="CASE-1001"),
            make_officer_headers(world["officer_id"]),
        ),
        201,
    )

    assert request["lifecycle_state"] == k.LIFECYCLE_DRAFT
    assert request["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_PENDING
    assert request["agency_id"] == world["agency_id"]
    assert request["submitting_officer_id"] == world["officer_id"]
    assertions.assert_nulls(
        request,
        "auditor_officer_id",
        "justification_text",
        "statutory_basis",
        "justification_logged_at",
        "audit_note",
        "withdraw_reason",
        "submitted_at",
        "expires_at",
    )
    assertions.assert_solicitation_buckets(request, 0, 0, 0, 0, 0)
    assertions.assert_solicitation_ledger(request, 0)
    assertions.assert_zero_counters(request, "shared_clip_count")
    assertions.assert_bps(request["provisional_share_rate_bps"], 0, "provisional_share_rate_bps")
    assert request["version"] == 1


def test_opening_a_request_advances_the_backing_area_but_no_agency_quota(
    api: ApiClient, clock: str
) -> None:
    """Opening a draft request charges the area's request count and version while both agency request counters stay at zero.

    PRD: "The backing area's `derived_request_count` is incremented by 1 and the area's `version` advances, which is precisely why the next officer to create a request against the same area must have read that new version."
    PRD: "`Agency.open_request_count` is the number of that agency's video requests currently in lifecycle state `SOLICITING` and is recomputed on every lifecycle transition of any of them; `Agency.requests_submitted_count` counts every video request of that agency that has *ever* entered `SOLICITING` and is never decremented."

    Design: Corner/state_machines/video_request_starts_in_draft_and_justification_pending
    """
    world = _canvass_world(api)
    area = fixtures.seed_locked_area(api, world["agency_id"], world["officer_id"])
    assert area["derived_request_count"] == 0

    fixtures.create_video_request(api, area, world["officer_id"], case_number="CASE-1001")

    charged = fixtures.read_area(api, area["id"])
    assert charged["derived_request_count"] == 1
    assert charged["status"] == k.AREA_STATUS_LOCKED
    assertions.assert_version_advanced(charged, area["version"])

    agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_zero_counters(
        agency, "open_request_count", "requests_submitted_count"
    )


# ── Withdrawal is terminal on the lifecycle dimension ─────────────────────

def test_withdrawing_a_soliciting_request_withdraws_its_unanswered_solicitations(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """An officer's withdrawal drives the request and all three unanswered solicitations to WITHDRAWN and empties the agency's open-request count.

    PRD: "A request in `SOLICITING` may also be withdrawn — `lifecycle_state` moves `SOLICITING → WITHDRAWN` — and there the cascade runs two levels: at level one every solicitation of that request still in `SOLICITED` moves `SOLICITED → WITHDRAWN` in ascending `dispatch_rank` with `responded_at` stamped from the clock, and at level two each of those cameras has its `pending_solicitation_count` decremented by 1."
    PRD: "The request then recomputes `pending_count` and `withdrawn_count` so that the solicitation ledger still balances, recomputes `provisional_share_rate_bps`, and the agency's `open_request_count` is decremented by 1."

    Design: Corner/state_machines/justification_on_withdrawn_request_rejected
    """
    request = canvass["request"]
    assert request["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assert request["solicitation_count"] == 3

    withdrawn = validate_success(
        api.withdraw_video_request(
            request["id"],
            f.withdraw_payload(reason="Suspect identified by other means."),
            make_officer_headers(canvass["officer_id"]),
        ),
        200,
    )
    assert withdrawn["lifecycle_state"] == k.LIFECYCLE_WITHDRAWN
    assertions.assert_solicitation_buckets(withdrawn, 0, 0, 0, 0, 3)
    assertions.assert_solicitation_ledger(withdrawn, 3)
    assertions.assert_bps(withdrawn["provisional_share_rate_bps"], 0, "provisional_share_rate_bps")
    assertions.assert_version_advanced(withdrawn, request["version"])

    rows = fixtures.list_solicitations(api, video_request_id=request["id"])
    assert [row["status"] for row in rows] == [k.SOLICITATION_WITHDRAWN] * 3
    for row in rows:
        assertions.assert_instant(row["responded_at"], canvass["clock"], "responded_at")

    for device in canvass["devices"]:
        assert fixtures.read_device(api, device["id"])["pending_solicitation_count"] == 0

    agency = fixtures.read_agency(api, canvass["agency_id"])
    assert agency["open_request_count"] == 0
    assert agency["requests_submitted_count"] == 1


def test_justifying_or_submitting_a_withdrawn_request_is_refused(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """Once a request has been withdrawn neither the justification nor the submission gate will look at it again, and nothing it owns moves.

    PRD: "This is only permitted while the request is in `lifecycle_state` `DRAFT` and `compliance_state` `JUSTIFICATION_PENDING`, and only by the officer recorded in `submitting_officer_id`."
    PRD: "The video request is in lifecycle state `DRAFT` where the operation demands it — otherwise `ERR_REQUEST_NOT_IN_DRAFT` (HTTP 409)."
    PRD: "The request must be in `lifecycle_state` `DRAFT`, or the answer is `ERR_REQUEST_NOT_IN_DRAFT`."

    Design: Corner/state_machines/justification_on_withdrawn_request_rejected
    """
    officer_headers = make_officer_headers(canvass["officer_id"])
    withdrawn = fixtures.withdraw_request(api, canvass["request_id"], officer_headers)
    assert withdrawn["lifecycle_state"] == k.LIFECYCLE_WITHDRAWN
    before = fixtures.list_solicitations(api, video_request_id=canvass["request_id"])

    refused_justification = api.log_justification(
        canvass["request_id"], f.justification_payload(), officer_headers
    )
    validate_error(refused_justification, ApiErrorId.REQUEST_NOT_IN_DRAFT.value, 409)

    refused_submit = api.submit_video_request(canvass["request_id"], officer_headers)
    validate_error(refused_submit, ApiErrorId.REQUEST_NOT_IN_DRAFT.value, 409)

    after = fixtures.read_request(api, canvass["request_id"])
    assert after["lifecycle_state"] == k.LIFECYCLE_WITHDRAWN
    assertions.assert_version_unchanged(after, withdrawn["version"])
    assert after["solicitation_count"] == 3
    assertions.assert_solicitation_buckets(after, 0, 0, 0, 0, 3)

    unmoved = fixtures.list_solicitations(api, video_request_id=canvass["request_id"])
    assert [row["status"] for row in unmoved] == [k.SOLICITATION_WITHDRAWN] * 3
    assert [row["version"] for row in unmoved] == [row["version"] for row in before]


# ── The resident-flag threshold on a published post ───────────────────────

def test_a_solitary_flag_leaves_the_post_published(api: ApiClient, clock: str) -> None:
    """One flag counts and versions the post but does not pull it out of the feed.

    PRD: "Every post is created with `flag_count` 0, `revision_count` 0 and an empty `flagged_by_resident_ids`."
    PRD: "Each accepted flag increments `flag_count` by 1, appends the flagger, and advances the post's `version` by 1."
    PRD: "The post itself moves `PUBLISHED → FLAGGED` with `auto_flag_reason` set to `RESIDENT_FLAG_THRESHOLD` only once `flag_count` has reached the resident-flag threshold of 2; a first, solitary flag leaves the post in `PUBLISHED` while still bumping the counter and the version."

    Design: Corner/state_machines/first_flag_leaves_post_published_second_flag_moves_it_to_flagged
    """
    world = _feed_world(api)
    post = world["post"]
    assert post["state"] == k.POST_PUBLISHED
    assert post["flag_count"] == 0
    assert post["revision_count"] == 0
    assert post["flagged_by_resident_ids"] == []

    flagged_once = validate_success(
        api.flag_post(
            world["post_id"],
            f.flag_payload(),
            make_resident_headers(world["first_flagger_id"]),
        ),
        200,
    )
    assert flagged_once["state"] == k.POST_PUBLISHED
    assert flagged_once["flag_count"] == 1
    assert flagged_once["flagged_by_resident_ids"] == [world["first_flagger_id"]]
    assertions.assert_nulls(flagged_once, "auto_flag_reason")
    assertions.assert_version_advanced(flagged_once, post["version"])


def test_the_second_flag_moves_the_post_out_of_the_feed(api: ApiClient, clock: str) -> None:
    """The second distinct flagger reaches the threshold of two, and the post is auto-flagged for that reason.

    PRD: "Each accepted flag increments `flag_count` by 1, appends the flagger, and advances the post's `version` by 1."
    PRD: "The post itself moves `PUBLISHED → FLAGGED` with `auto_flag_reason` set to `RESIDENT_FLAG_THRESHOLD` only once `flag_count` has reached the resident-flag threshold of 2; a first, solitary flag leaves the post in `PUBLISHED` while still bumping the counter and the version."
    PRD: "A post must be in `PUBLISHED` to be flagged, or the attempt is refused with `ERR_POST_NOT_PUBLISHED`."

    Design: Corner/state_machines/first_flag_leaves_post_published_second_flag_moves_it_to_flagged
    """
    world = _feed_world(api)
    once = fixtures.flag_post(api, world["post_id"], world["first_flagger_id"])

    twice = validate_success(
        api.flag_post(
            world["post_id"],
            f.flag_payload(),
            make_resident_headers(world["second_flagger_id"]),
        ),
        200,
    )
    assert twice["state"] == k.POST_FLAGGED
    assert twice["flag_count"] == k.RESIDENT_FLAG_THRESHOLD
    assert twice["auto_flag_reason"] == k.AUTO_FLAG_RESIDENT_FLAGS
    assert twice["flagged_by_resident_ids"] == [
        world["first_flagger_id"],
        world["second_flagger_id"],
    ]
    assertions.assert_version_advanced(twice, once["version"])

    third_flagger = fixtures.register_resident(
        api,
        display_name="Flagger Three",
        email="f3@example.test",
        home_x_m=30,
        home_y_m=0,
        alert_radius_m=0,
    )
    refused = api.flag_post(
        world["post_id"], f.flag_payload(), make_resident_headers(third_flagger["id"])
    )
    validate_error(refused, ApiErrorId.POST_NOT_PUBLISHED.value, 409)

    after = fixtures.read_post(api, world["post_id"])
    assert after["state"] == k.POST_FLAGGED
    assertions.assert_version_unchanged(after, twice["version"])
    assert after["flag_count"] == k.RESIDENT_FLAG_THRESHOLD


# ── A rejected agency is terminal ─────────────────────────────────────────

def test_suspending_a_rejected_agency_is_refused(api: ApiClient, clock: str) -> None:
    """A rejection is the end of the road: the enforcement action cannot reach into it, and the row keeps the note the rejection stored.

    PRD: "Rejection moves it `PENDING_REVIEW → REJECTED`, stores only the note, and is **terminal**: no officer, area, request or report may ever be created for a rejected agency."
    PRD: "Exactly three moves are legal: `ONBOARDED → SUSPENDED`, `SUSPENDED → ONBOARDED`, and `SUSPENDED → REVOKED`."
    PRD: "`REJECTED` and `REVOKED` are terminal, and an onboarded agency must be suspended before it can be revoked — a direct move from `ONBOARDED` to `REVOKED` is refused with `ERR_AGENCY_STATUS_TRANSITION_INVALID`, as is any target that is not reachable from where the agency currently stands."

    Design: Corner/state_machines/agency_status_change_from_rejected_is_rejected
    """
    world = _rejected_agency(api)
    rejected = world["rejected"]
    assert rejected["status"] == k.AGENCY_STATUS_REJECTED
    assert rejected["reviewer_note"] == REJECTION_NOTE
    assertions.assert_version_advanced(rejected, world["applicant"]["version"])

    refused = api.change_agency_status(
        world["agency_id"],
        f.status_change_payload(
            k.AGENCY_STATUS_SUSPENDED, reason="Complaint received after the rejection."
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(refused, ApiErrorId.AGENCY_STATUS_TRANSITION_INVALID.value, 409)

    after = fixtures.read_agency(api, world["agency_id"])
    assert after["status"] == k.AGENCY_STATUS_REJECTED
    assertions.assert_version_unchanged(after, rejected["version"])
    assert after["reviewer_note"] == REJECTION_NOTE
    assert after["status_reason"] == rejected["status_reason"]


def test_revoking_a_rejected_agency_is_refused(api: ApiClient, clock: str) -> None:
    """No enforcement target is reachable from a rejection, so the revocation is refused just as the suspension was.

    PRD: "Exactly three moves are legal: `ONBOARDED → SUSPENDED`, `SUSPENDED → ONBOARDED`, and `SUSPENDED → REVOKED`."
    PRD: "`REJECTED` and `REVOKED` are terminal, and an onboarded agency must be suspended before it can be revoked — a direct move from `ONBOARDED` to `REVOKED` is refused with `ERR_AGENCY_STATUS_TRANSITION_INVALID`, as is any target that is not reachable from where the agency currently stands."
    PRD: "A review submitted against an agency that is not in `PENDING_REVIEW` is rejected with `ERR_AGENCY_STATUS_TRANSITION_INVALID`."

    Design: Corner/state_machines/agency_status_change_from_rejected_is_rejected
    """
    world = _rejected_agency(api)
    rejected = world["rejected"]

    refused_revoke = api.change_agency_status(
        world["agency_id"],
        f.status_change_payload(
            k.AGENCY_STATUS_REVOKED, reason="Escalating the earlier rejection."
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(refused_revoke, ApiErrorId.AGENCY_STATUS_TRANSITION_INVALID.value, 409)

    refused_reinstate = api.change_agency_status(
        world["agency_id"],
        f.status_change_payload(
            k.AGENCY_STATUS_ONBOARDED, reason="Asking for a second look."
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(
        refused_reinstate, ApiErrorId.AGENCY_STATUS_TRANSITION_INVALID.value, 409
    )

    refused_review = api.review_agency_onboarding(
        world["agency_id"],
        f.onboarding_review_payload(
            decision=k.ONBOARDING_DECISION_APPROVE,
            reviewer_note="MOU produced after the rejection.",
            onboarding_agreement_version=AGREEMENT_VERSION,
        ),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(refused_review, ApiErrorId.AGENCY_STATUS_TRANSITION_INVALID.value, 409)

    after = fixtures.read_agency(api, world["agency_id"])
    assert after["status"] == k.AGENCY_STATUS_REJECTED
    assertions.assert_version_unchanged(after, rejected["version"])
    assert after["reviewer_note"] == REJECTION_NOTE
    assert (
        after["onboarding_agreement_version"]
        == rejected["onboarding_agreement_version"]
    )
