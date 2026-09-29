"""Deep cascades: every level runs to completion inside one request.

Two triggers are exercised here. A resident's account-level opt-out reaches from
the privacy surface all the way down to the agency's concurrent-load counter,
fanning out sideways into the canvass area on the way. A moderator's removal
decision reaches from one strike counter down to brand-new moderation cases the
portal opens against itself. Each test reads back every row the chain is meant
to have moved and every row it is meant to have left alone.
"""

from typing import Any, Dict, List, Sequence, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MODERATOR_ID,
    MODERATOR_SECOND_ID,
    PLATFORM_ADMIN_HEADERS,
    make_resident_headers,
)

# Three camera positions inside a 500 m disc at the origin: squared distances
# 100, 400 and 900. The fourth and later positions extend the same line.
_CAMERA_LINE: Tuple[Tuple[int, int], ...] = (
    (0, 10),
    (0, 20),
    (0, 30),
    (0, 40),
    (0, 50),
    (0, 60),
)


# ── Local setup the shared fixtures do not cover ───────────────────────────


def _seed_owner_with_cameras(
    api: ApiClient,
    *,
    display_name: str,
    email: str,
    home_x_m: int,
    home_y_m: int,
    positions: Sequence[Tuple[int, int]],
) -> Dict[str, Any]:
    """One resident owning several cameras, which the shared fixtures never do.

    ``seed_residents_with_devices`` gives one camera to each of several owners;
    the opt-out cascade needs the opposite shape, because the control is
    exercised once and has to reach every camera of the one account.
    """
    resident = fixtures.register_resident(
        api,
        display_name=display_name,
        email=email,
        home_x_m=home_x_m,
        home_y_m=home_y_m,
        alert_radius_m=0,
    )
    devices = [
        fixtures.register_device(
            api,
            resident["id"],
            label=f"{display_name} camera {index}",
            grid_x_m=x,
            grid_y_m=y,
            retention_window_days=30,
        )
        for index, (x, y) in enumerate(positions, start=1)
    ]
    return {
        "resident": resident,
        "resident_id": resident["id"],
        "devices": devices,
        "device_ids": [device["id"] for device in devices],
    }


def _seed_single_owner_canvass(
    api: ApiClient,
    owner_positions: Sequence[Tuple[int, int]],
    *,
    neighbour_positions: Sequence[Tuple[int, int]] = (),
) -> Dict[str, Any]:
    """A submitted canvass whose whole roster belongs to one household.

    The clock is pinned first, one agency is onboarded with a device floor of
    three and one requester officer, then the owner's cameras are registered and
    a 500 m canvass at the origin over the standard six-hour footage window is
    locked, justified and submitted.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    world["owner"] = _seed_owner_with_cameras(
        api,
        display_name="RT",
        email="rt@example.test",
        home_x_m=0,
        home_y_m=0,
        positions=owner_positions,
    )
    world["neighbour"] = None
    if neighbour_positions:
        world["neighbour"] = _seed_owner_with_cameras(
            api,
            display_name="RX",
            email="rx@example.test",
            home_x_m=0,
            home_y_m=1000,
            positions=neighbour_positions,
        )
    world.update(
        fixtures.seed_submitted_request(
            api, world["agency_id"], world["officer_id"], case_number="CASE-9005"
        )
    )
    return world


def _solicitation_ids(
    api: ApiClient, request_id: str, device_ids: Sequence[str]
) -> List[str]:
    """The identifier of the one solicitation this request put to each camera."""
    return [
        fixtures.solicitation_for_device(api, request_id, device_id)["id"]
        for device_id in device_ids
    ]


def _seed_feed_residents(api: ApiClient) -> Dict[str, Any]:
    """One author and two flaggers, none of whom is in earshot of any post.

    Every alert radius is zero and the two flaggers live away from the origin,
    so publishing alerts nobody and no fatigue arithmetic interferes.
    """
    author = fixtures.register_resident(
        api,
        display_name="RA",
        email="ra@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    first = fixtures.register_resident(
        api,
        display_name="RB",
        email="rb@example.test",
        home_x_m=100,
        home_y_m=0,
        alert_radius_m=0,
    )
    second = fixtures.register_resident(
        api,
        display_name="RC",
        email="rc@example.test",
        home_x_m=200,
        home_y_m=0,
        alert_radius_m=0,
    )
    return {
        "author_id": author["id"],
        "flagger_ids": [first["id"], second["id"]],
    }


def _remove_post(
    api: ApiClient,
    author_id: str,
    flagger_ids: Sequence[str],
    decision: str,
    *,
    body: str,
    category: str = k.CATEGORY_SAFETY_REPORT,
) -> Dict[str, Any]:
    """Publish a post, have it flagged twice, triage it and remove it."""
    seeded = fixtures.seed_post_under_review(
        api, author_id, flagger_ids, body=body, category=category
    )
    fixtures.decide_case(
        api,
        seeded["case_id"],
        decision=decision,
        decision_note="Reviewed against the community standards and removed.",
    )
    return seeded


def _author_suspension_cases(
    api: ApiClient,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every case the portal opened against itself, with the pagination block."""
    response = api.list_moderation_cases(
        PLATFORM_ADMIN_HEADERS,
        f.page(limit=100, offset=0, opened_reason=k.OPENED_REASON_AUTHOR_SUSPENDED),
    )
    return validate_paginated(response)


# ── Instance: resident opt-out reaching the agency's open-request counter ───


def test_resident_opt_out_cascade_reaches_the_agency_open_request_counter(
    api: ApiClient,
) -> None:
    """One opt-out flips three cameras, declines three solicitations, exhausts the request and frees the agency's open-request slot.

    PRD: "`OPT_OUT_OF_REQUESTS` is an absolute withdrawal from the video-request programme and cascades five levels."
    PRD: "Level two sets `auto_decline_requests` to true and `auto_decline_source` to `OPT_OUT` on every camera of that resident that is not `DECOMMISSIONED`."
    PRD: "Level four recomputes the counters of every video request that lost a solicitation and auto-resolves each one out of `SOLICITING` when its `pending_count` reaches 0 — to `FULFILLED` when at least one solicitation of that request is `SHARED`, and to `EXHAUSTED` when none is."
    PRD: "Level five decrements `Agency.open_request_count` once for every request that resolved."

    Design: Difficulty/transitive_cascade/resident_opt_out_cascades_five_levels_to_agency_open_request_counter
    """
    world = _seed_single_owner_canvass(api, _CAMERA_LINE[:3])
    owner_id = world["owner"]["resident_id"]
    device_ids = world["owner"]["device_ids"]
    request_id = world["request_id"]
    area_id = world["area"]["id"]
    agency_id = world["agency_id"]

    # The state the cascade starts from, read immediately before the trigger.
    area_before = fixtures.read_area(api, area_id)
    assertions.assert_subset(
        area_before,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 3,
            "eligible_device_count": 3,
            "derived_request_count": 1,
            "version": 3,
        },
    )
    assertions.assert_nulls(area_before, "invalidated_reason")

    request_before = fixtures.read_request(api, request_id)
    assertions.assert_subset(
        request_before,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "version": 3,
        },
    )
    assertions.assert_solicitation_buckets(request_before, 3, 0, 0, 0, 0)

    agency_before = fixtures.read_agency(api, agency_id)
    assertions.assert_subset(
        agency_before, {"open_request_count": 1, "requests_submitted_count": 1}
    )

    # The owner's own row was already mutated by the submit-time dispatch batch
    # ("the recipient's `notifications_sent_today` rises by 1"), so the version
    # the data control has to advance by exactly 1 is read here, not assumed.
    owner_before = fixtures.read_resident(api, owner_id)

    devices_before = [fixtures.read_device(api, device_id) for device_id in device_ids]
    for device_before in devices_before:
        assertions.assert_subset(
            device_before,
            {
                "auto_decline_requests": False,
                "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
                "pending_solicitation_count": 1,
                "solicitations_received_count": 1,
            },
        )
    solicitation_ids = _solicitation_ids(api, request_id, device_ids)

    receipt = fixtures.exercise_data_control(
        api,
        owner_id,
        k.ACTION_OPT_OUT,
        reason="No longer comfortable sharing footage.",
    )

    # The receipt reports one count per depth of the chain it just ran.
    assertions.assert_receipt_common_fields(receipt)
    assertions.assert_subset(
        receipt,
        {
            "action_type": k.ACTION_OPT_OUT,
            "affected_device_count": 3,
            "affected_solicitation_count": 3,
            "affected_request_count": 1,
            "affected_clip_count": 0,
        },
    )
    assertions.assert_instant(receipt["applied_at"], fixtures.SCENARIO_CLOCK, "applied_at")

    # L1: the account-level flag on the resident.
    owner_after = fixtures.read_resident(api, owner_id)
    assertions.assert_subset(
        owner_after,
        {
            "data_sharing_opt_out": True,
            "status": k.RESIDENT_STATUS_ACTIVE,
            "version": owner_before["version"] + 1,
        },
    )

    # L2: every camera of that account now refuses, attributed to the opt-out.
    for device_before in devices_before:
        device_after = fixtures.read_device(api, device_before["id"])
        assertions.assert_subset(
            device_after,
            {
                "auto_decline_requests": True,
                "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
                "status": k.DEVICE_STATUS_ACTIVE,
                "pending_solicitation_count": 0,
                "solicitations_received_count": 1,
            },
        )
        assert device_after["version"] > device_before["version"], (
            "A camera the cascade rewrote must have advanced its version: "
            f"{device_after['version']} against {device_before['version']}"
        )

    # L3: every open solicitation on those cameras is a recorded refusal.
    for solicitation_id in solicitation_ids:
        solicitation = fixtures.read_solicitation(api, solicitation_id)
        assertions.assert_subset(
            solicitation,
            {
                "status": k.SOLICITATION_DECLINED,
                "decline_reason": k.DECLINE_OWNER_OPT_OUT,
                "clip_count": 0,
                "version": 2,
            },
        )
        assertions.assert_instant(
            solicitation["responded_at"], fixtures.SCENARIO_CLOCK, "responded_at"
        )

    # L4: the request's counters reconcile and it resolves out of soliciting.
    request_after = fixtures.read_request(api, request_id)
    assertions.assert_subset(
        request_after,
        {
            "lifecycle_state": k.LIFECYCLE_EXHAUSTED,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "shared_clip_count": 0,
        },
    )
    assertions.assert_solicitation_buckets(request_after, 0, 0, 3, 0, 0)
    assertions.assert_solicitation_ledger(request_after, 3)
    assertions.assert_bps(
        request_after["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )
    assert request_after["version"] > request_before["version"], (
        "The request the cascade resolved must have advanced its version: "
        f"{request_after['version']} against {request_before['version']}"
    )

    # L5: the concurrent-load counter comes back down, the lifetime one does not.
    agency_after = fixtures.read_agency(api, agency_id)
    assertions.assert_subset(
        agency_after, {"open_request_count": 0, "requests_submitted_count": 1}
    )

    # The lateral branch off L2: the frozen roster no longer clears the floor.
    area_after = fixtures.read_area(api, area_id)
    assertions.assert_subset(
        area_after,
        {
            "status": k.AREA_STATUS_INVALIDATED,
            "invalidated_reason": k.INVALIDATED_ELIGIBILITY,
            "effective_min_devices": 3,
            "derived_request_count": 1,
            "version": 4,
        },
    )


def test_resident_opt_out_cascade_stops_at_a_decommissioned_camera(
    api: ApiClient,
) -> None:
    """A decommissioned camera keeps its open solicitation, so the chain stops at level three and the request stays soliciting.

    PRD: "Level two sets `auto_decline_requests` to true and `auto_decline_source` to `OPT_OUT` on every camera of that resident that is not `DECOMMISSIONED`."
    PRD: "Level three drives every solicitation still in `SOLICITED` on those cameras to `DECLINED` with `decline_reason` `OWNER_OPT_OUT`, processed in ascending `created_at`."
    PRD: "Setting `status` to `DECOMMISSIONED` is deliberately just as inert: every solicitation on that camera stays in `SOLICITED`, `pending_solicitation_count` is left exactly where it was, and the owner is simply unable to share from the dead camera — the solicitations sit there until their response deadline lapses and the retention sweep expires them."

    Design: Difficulty/transitive_cascade/resident_opt_out_cascades_five_levels_to_agency_open_request_counter
    """
    world = _seed_single_owner_canvass(api, _CAMERA_LINE[:4])
    owner_id = world["owner"]["resident_id"]
    live_device_ids = world["owner"]["device_ids"][:3]
    dead_device_id = world["owner"]["device_ids"][3]
    request_id = world["request_id"]
    area_id = world["area"]["id"]
    agency_id = world["agency_id"]

    # The fourth camera dies after the canvass went out, so it drops out of the
    # opt-out's level-two set while keeping the solicitation it already holds.
    fixtures.update_device(
        api, dead_device_id, owner_id, status=k.DEVICE_STATUS_DECOMMISSIONED
    )

    dead_solicitation_id = fixtures.solicitation_for_device(
        api, request_id, dead_device_id
    )["id"]
    live_solicitation_ids = _solicitation_ids(api, request_id, live_device_ids)

    dead_device_before = fixtures.read_device(api, dead_device_id)
    assertions.assert_subset(
        dead_device_before,
        {
            "status": k.DEVICE_STATUS_DECOMMISSIONED,
            "pending_solicitation_count": 1,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        },
    )
    dead_solicitation_before = fixtures.read_solicitation(api, dead_solicitation_id)
    assert dead_solicitation_before["status"] == k.SOLICITATION_SOLICITED

    request_before = fixtures.read_request(api, request_id)
    assertions.assert_solicitation_buckets(request_before, 4, 0, 0, 0, 0)
    assert request_before["lifecycle_state"] == k.LIFECYCLE_SOLICITING

    receipt = fixtures.exercise_data_control(
        api, owner_id, k.ACTION_OPT_OUT, reason="Stepping back from requests."
    )
    assertions.assert_subset(
        receipt,
        {
            "action_type": k.ACTION_OPT_OUT,
            "affected_device_count": 3,
            "affected_solicitation_count": 3,
            "affected_clip_count": 0,
        },
    )

    # The three live cameras and their solicitations did move.
    for device_id in live_device_ids:
        assertions.assert_subset(
            fixtures.read_device(api, device_id),
            {
                "auto_decline_requests": True,
                "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
                "pending_solicitation_count": 0,
            },
        )
    for solicitation_id in live_solicitation_ids:
        assertions.assert_subset(
            fixtures.read_solicitation(api, solicitation_id),
            {
                "status": k.SOLICITATION_DECLINED,
                "decline_reason": k.DECLINE_OWNER_OPT_OUT,
            },
        )

    # The decommissioned camera is exactly where it was, version included.
    dead_device_after = fixtures.read_device(api, dead_device_id)
    assertions.assert_subset(
        dead_device_after,
        {
            "status": k.DEVICE_STATUS_DECOMMISSIONED,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
            "pending_solicitation_count": 1,
            "solicitations_received_count": 1,
        },
    )
    assertions.assert_version_unchanged(dead_device_after, dead_device_before["version"])

    dead_solicitation_after = fixtures.read_solicitation(api, dead_solicitation_id)
    assertions.assert_subset(
        dead_solicitation_after, {"status": k.SOLICITATION_SOLICITED, "clip_count": 0}
    )
    assertions.assert_nulls(dead_solicitation_after, "responded_at", "decline_reason")
    assertions.assert_version_unchanged(
        dead_solicitation_after, dead_solicitation_before["version"]
    )

    # Level four never fires, because one solicitation is still pending.
    request_after = fixtures.read_request(api, request_id)
    assert request_after["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assertions.assert_solicitation_buckets(request_after, 1, 0, 3, 0, 0)
    assertions.assert_solicitation_ledger(request_after, 4)
    assertions.assert_bps(
        request_after["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )

    # Level five therefore never fires either.
    assertions.assert_subset(
        fixtures.read_agency(api, agency_id),
        {"open_request_count": 1, "requests_submitted_count": 1},
    )

    # The lateral branch still runs: nothing eligible is left on the roster.
    assertions.assert_subset(
        fixtures.read_area(api, area_id),
        {
            "status": k.AREA_STATUS_INVALIDATED,
            "invalidated_reason": k.INVALIDATED_ELIGIBILITY,
            "effective_min_devices": 3,
        },
    )


def test_resident_opt_out_leaves_a_neighbours_camera_and_the_locked_area_alone(
    api: ApiClient,
) -> None:
    """When the recomputed roster still clears the floor the area stays locked, and another household's camera and solicitation are untouched.

    PRD: "Whenever a roster member or its owner loses eligibility — the camera's status changes, the owner opts out, the owner deactivates — the eligible count is recomputed against the frozen roster, and if the recomputed count falls below the area's `effective_min_devices`, the area moves `LOCKED → INVALIDATED` with `invalidated_reason` `ELIGIBILITY_BELOW_THRESHOLD` and its `version` advances by 1."
    PRD: "Crucially, the lock froze the roster's *order*, not the eligibility of its members: while the recomputed count still clears the threshold, the area stays `LOCKED` and the newly ineligible camera stays on the roster."
    PRD: "Requests already in `SOLICITING` against the area continue entirely unaffected by an eligibility collapse; only requests still sitting in `DRAFT` become unsubmittable."

    Design: Difficulty/transitive_cascade/resident_opt_out_cascades_five_levels_to_agency_open_request_counter
    """
    world = _seed_single_owner_canvass(
        api, _CAMERA_LINE[:3], neighbour_positions=_CAMERA_LINE[3:6]
    )
    owner_id = world["owner"]["resident_id"]
    owner_device_ids = world["owner"]["device_ids"]
    neighbour_id = world["neighbour"]["resident_id"]
    neighbour_device_ids = world["neighbour"]["device_ids"]
    request_id = world["request_id"]
    area_id = world["area"]["id"]
    agency_id = world["agency_id"]

    area_before = fixtures.read_area(api, area_id)
    assertions.assert_subset(
        area_before,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 6,
            "effective_min_devices": 3,
            "version": 3,
        },
    )

    request_before = fixtures.read_request(api, request_id)
    assertions.assert_solicitation_buckets(request_before, 6, 0, 0, 0, 0)

    # The neighbour was already solicited, so the submit-time dispatch batch has
    # advanced its row once ("the recipient's `notifications_sent_today` rises by
    # 1"); the opt-out must leave that version exactly where it stands.
    neighbour_before = fixtures.read_resident(api, neighbour_id)

    neighbour_devices_before = [
        fixtures.read_device(api, device_id) for device_id in neighbour_device_ids
    ]
    neighbour_solicitations_before = [
        fixtures.read_solicitation(api, solicitation_id)
        for solicitation_id in _solicitation_ids(api, request_id, neighbour_device_ids)
    ]

    receipt = fixtures.exercise_data_control(
        api, owner_id, k.ACTION_OPT_OUT, reason="Stepping back from requests."
    )
    assertions.assert_subset(
        receipt,
        {
            "affected_device_count": 3,
            "affected_solicitation_count": 3,
            "affected_clip_count": 0,
        },
    )

    # The opting-out household moved.
    for device_id in owner_device_ids:
        assertions.assert_subset(
            fixtures.read_device(api, device_id),
            {
                "auto_decline_requests": True,
                "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
                "pending_solicitation_count": 0,
            },
        )

    # The neighbouring household did not, down to its versions.
    assertions.assert_subset(
        fixtures.read_resident(api, neighbour_id),
        {
            "data_sharing_opt_out": False,
            "status": k.RESIDENT_STATUS_ACTIVE,
            "version": neighbour_before["version"],
        },
    )
    for device_before in neighbour_devices_before:
        device_after = fixtures.read_device(api, device_before["id"])
        assertions.assert_subset(
            device_after,
            {
                "auto_decline_requests": False,
                "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
                "status": k.DEVICE_STATUS_ACTIVE,
                "pending_solicitation_count": 1,
                "solicitations_received_count": 1,
            },
        )
        assertions.assert_version_unchanged(device_after, device_before["version"])
    for solicitation_before in neighbour_solicitations_before:
        solicitation_after = fixtures.read_solicitation(api, solicitation_before["id"])
        assert solicitation_after["status"] == k.SOLICITATION_SOLICITED
        assertions.assert_nulls(solicitation_after, "responded_at", "decline_reason")
        assertions.assert_version_unchanged(
            solicitation_after, solicitation_before["version"]
        )

    # Three eligible cameras remain, which is exactly the frozen floor.
    area_after = fixtures.read_area(api, area_id)
    assertions.assert_subset(
        area_after,
        {
            "status": k.AREA_STATUS_LOCKED,
            "effective_min_devices": 3,
            "derived_request_count": 1,
        },
    )
    assertions.assert_nulls(area_after, "invalidated_reason")
    assertions.assert_version_unchanged(area_after, area_before["version"])

    # The soliciting request keeps canvassing and the agency keeps its slot.
    request_after = fixtures.read_request(api, request_id)
    assert request_after["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assertions.assert_solicitation_buckets(request_after, 3, 0, 3, 0, 0)
    assertions.assert_solicitation_ledger(request_after, 6)
    assertions.assert_bps(
        request_after["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )
    assertions.assert_subset(
        fixtures.read_agency(api, agency_id),
        {"open_request_count": 1, "requests_submitted_count": 1},
    )


# ── Instance: discriminatory removal reaching system-opened cases ───────────


def test_discriminatory_removal_cascade_reaches_system_opened_cases(
    api: ApiClient,
) -> None:
    """A discrimination strike on top of an accuracy strike suspends the author, sweeps both of their other published posts into review and opens a case for each in the portal's own name.

    PRD: "**L2** recomputes `total_strike_score` as `accuracy_strike_count` plus twice `discrimination_strike_count` — a discrimination strike weighs double."
    PRD: "**L3** re-derives `post_privilege_state` from that score against two inclusive thresholds: a score of 3 or more is `POSTING_SUSPENDED`, a score of 2 is `REVIEW_REQUIRED`, and anything below is `UNRESTRICTED`."
    PRD: "**L4** fires only when L3 has just moved the author into `POSTING_SUSPENDED`, and only then: every **other** post by that author that is currently in `PUBLISHED` and whose `created_at` is no earlier than 30 days before the current logical-clock instant moves `PUBLISHED → UNDER_REVIEW` with `auto_flag_reason` set to `AUTHOR_UNDER_REVIEW`, processed in ascending `created_at`."
    PRD: "**L5** follows from L4: one moderation case is auto-created for each swept post, in state `OPEN`, with `opened_reason` `AUTHOR_SUSPENDED` and `opened_by_user_id` set to the literal string `system`."

    Design: Difficulty/transitive_cascade/discriminatory_removal_cascades_five_levels_to_system_opened_cases
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    people = _seed_feed_residents(api)
    author_id = people["author_id"]
    flaggers = people["flagger_ids"]

    # One accuracy strike first, so the discrimination strike lands on 3 exactly.
    prior = _remove_post(
        api,
        author_id,
        flaggers,
        k.DECISION_REMOVE_INACCURATE,
        body="Post PA, later removed for inaccuracy.",
    )
    prior_before = fixtures.read_post(api, prior["post_id"])
    assert prior_before["state"] == k.POST_REMOVED

    # The clock is moved between the two other posts so their created_at order
    # is strictly increasing and the sweep order is unambiguous.
    fixtures.set_clock(api, "2026-08-12T01:00:00Z")
    first_other = fixtures.create_post(
        api,
        author_id,
        body="Post P1, an unrelated published note.",
        category=k.CATEGORY_LOST_PET,
    )
    fixtures.set_clock(api, "2026-08-12T02:00:00Z")
    second_other = fixtures.create_post(
        api,
        author_id,
        body="Post P2, a second unrelated published note.",
        category=k.CATEGORY_GENERAL,
    )
    assert first_other["state"] == k.POST_PUBLISHED
    assert second_other["state"] == k.POST_PUBLISHED

    fixtures.set_clock(api, "2026-08-12T03:00:00Z")
    target = fixtures.seed_post_under_review(
        api,
        author_id,
        flaggers,
        body="Post P0, the post that will be removed as discriminatory.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
    )
    assert target["post"]["state"] == k.POST_UNDER_REVIEW

    author_before = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        author_before,
        {
            "accuracy_strike_count": 1,
            "discrimination_strike_count": 0,
            "total_strike_score": 1,
            "post_privilege_state": k.PRIVILEGE_UNRESTRICTED,
        },
    )
    rows_before, meta_before = _author_suspension_cases(api)
    assert meta_before["total_count"] == 0
    assert rows_before == []

    decided = fixtures.decide_case(
        api,
        target["case_id"],
        decision=k.DECISION_REMOVE_DISCRIMINATORY,
        decision_note="Targets a protected class; removed.",
    )

    # The decision itself, and the separated moderator duties it records.
    assertions.assert_subset(
        decided,
        {
            "state": k.CASE_DECIDED,
            "decision": k.DECISION_REMOVE_DISCRIMINATORY,
            "opened_reason": k.OPENED_REASON_RESIDENT_FLAGS,
            "opened_by_user_id": MODERATOR_ID,
            "decided_by_user_id": MODERATOR_SECOND_ID,
            "version": 2,
        },
    )
    assertions.assert_instant(decided["decided_at"], "2026-08-12T03:00:00Z", "decided_at")

    target_after = fixtures.read_post(api, target["post_id"])
    assert target_after["state"] == k.POST_REMOVED
    assertions.assert_version_advanced(target_after, target["post"]["version"])

    # L1, L2 and L3 on the author: one strike each way, a weighted score of 3
    # and the suspension that score buys.
    author_after = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        author_after,
        {
            "accuracy_strike_count": 1,
            "discrimination_strike_count": 1,
            "total_strike_score": 3,
            "post_privilege_state": k.PRIVILEGE_POSTING_SUSPENDED,
            "status": k.RESIDENT_STATUS_ACTIVE,
        },
    )
    assertions.assert_strike_ladder(author_after)
    assertions.assert_version_advanced(author_after, author_before["version"])

    # L4: both other published posts of that author are pulled into review.
    for other in (first_other, second_other):
        swept = fixtures.read_post(api, other["id"])
        assertions.assert_subset(
            swept,
            {
                "state": k.POST_UNDER_REVIEW,
                "auto_flag_reason": k.AUTO_FLAG_AUTHOR_UNDER_REVIEW,
                "flag_count": 0,
                "revision_count": 0,
                "version": 2,
            },
        )

    # The already-removed post is not published, so the sweep passes it by.
    prior_after = fixtures.read_post(api, prior["post_id"])
    assert prior_after["state"] == k.POST_REMOVED
    assertions.assert_version_unchanged(prior_after, prior_before["version"])
    prior_cases = fixtures.list_cases_for_post(api, prior["post_id"])
    assert len(prior_cases) == 1
    assert prior_cases[0]["opened_reason"] == k.OPENED_REASON_RESIDENT_FLAGS

    # L5: one brand-new case per swept post, attributed to the portal itself.
    rows, meta = _author_suspension_cases(api)
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert {row["resident_post_id"] for row in rows} == {
        first_other["id"],
        second_other["id"],
    }
    for row in rows:
        assertions.assert_subset(
            row,
            {
                "state": k.CASE_OPEN,
                "decision": k.DECISION_NONE,
                "opened_reason": k.OPENED_REASON_AUTHOR_SUSPENDED,
                "opened_by_user_id": k.SYSTEM_OPENER,
            },
        )
        assertions.assert_nulls(row, "decided_by_user_id", "decided_at")
        assertions.assert_created_equals_updated(row)

    for other in (first_other, second_other):
        cases = fixtures.list_cases_for_post(api, other["id"])
        assert len(cases) == 1, (
            f"Exactly one case should exist for the swept post {other['id']}, "
            f"got {len(cases)}"
        )
        assertions.assert_subset(
            cases[0],
            {
                "opened_reason": k.OPENED_REASON_AUTHOR_SUSPENDED,
                "opened_by_user_id": k.SYSTEM_OPENER,
                "state": k.CASE_OPEN,
            },
        )


def test_a_lone_discrimination_removal_stops_three_levels_in(
    api: ApiClient,
) -> None:
    """A first discrimination removal weighs 2, which is review territory rather than suspension, so no post is swept and no case is opened.

    PRD: "**L3** re-derives `post_privilege_state` from that score against two inclusive thresholds: a score of 3 or more is `POSTING_SUSPENDED`, a score of 2 is `REVIEW_REQUIRED`, and anything below is `UNRESTRICTED`."
    PRD: "One discrimination removal therefore lands a resident straight in `REVIEW_REQUIRED` at a score of 2, a second takes them to 4 and `POSTING_SUSPENDED`, while two accuracy removals are needed to reach `REVIEW_REQUIRED` — and the score of exactly 3 is reachable only by mixing one discrimination strike with one accuracy strike."
    PRD: "A removal that leaves the author below the suspension threshold stops after L3, creating no cases and sweeping no posts."

    Design: Difficulty/transitive_cascade/discriminatory_removal_cascades_five_levels_to_system_opened_cases
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    people = _seed_feed_residents(api)
    author_id = people["author_id"]
    flaggers = people["flagger_ids"]

    bystander = fixtures.create_post(
        api,
        author_id,
        body="A published note that no sweep should ever reach.",
        category=k.CATEGORY_LOST_PET,
    )
    assert bystander["state"] == k.POST_PUBLISHED

    fixtures.set_clock(api, "2026-08-12T01:00:00Z")
    target = fixtures.seed_post_under_review(
        api,
        author_id,
        flaggers,
        body="The only post this author will lose today.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
    )

    author_before = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        author_before,
        {
            "accuracy_strike_count": 0,
            "discrimination_strike_count": 0,
            "total_strike_score": 0,
            "post_privilege_state": k.PRIVILEGE_UNRESTRICTED,
        },
    )

    fixtures.decide_case(
        api,
        target["case_id"],
        decision=k.DECISION_REMOVE_DISCRIMINATORY,
        decision_note="Targets a protected class; removed.",
    )

    # L1 through L3 land: the doubled strike scores 2, which is review and not
    # suspension.
    author_after = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        author_after,
        {
            "accuracy_strike_count": 0,
            "discrimination_strike_count": 1,
            "total_strike_score": 2,
            "post_privilege_state": k.PRIVILEGE_REVIEW_REQUIRED,
        },
    )
    assertions.assert_strike_ladder(author_after)
    assertions.assert_version_advanced(author_after, author_before["version"])

    assert fixtures.read_post(api, target["post_id"])["state"] == k.POST_REMOVED

    # L4 never fires, so the author's other post is exactly where it was.
    bystander_after = fixtures.read_post(api, bystander["id"])
    assert bystander_after["state"] == k.POST_PUBLISHED
    assertions.assert_nulls(bystander_after, "auto_flag_reason")
    assertions.assert_version_unchanged(bystander_after, bystander["version"])
    assert bystander_after["flag_count"] == 0

    # L5 never fires either, so the portal has opened nothing in its own name.
    rows, meta = _author_suspension_cases(api)
    assert meta["total_count"] == 0
    assert rows == []
    assert fixtures.list_cases_for_post(api, bystander["id"]) == []


def test_author_suspension_sweep_spares_old_posts_and_posts_not_published(
    api: ApiClient,
) -> None:
    """The sweep that follows a suspension takes only the author's published posts from the last thirty days, and opens a case for each of those alone.

    PRD: "**L4** fires only when L3 has just moved the author into `POSTING_SUSPENDED`, and only then: every **other** post by that author that is currently in `PUBLISHED` and whose `created_at` is no earlier than 30 days before the current logical-clock instant moves `PUBLISHED → UNDER_REVIEW` with `auto_flag_reason` set to `AUTHOR_UNDER_REVIEW`, processed in ascending `created_at`."
    PRD: "Posts older than the 30-day lookback are left alone, as are posts already in any state other than `PUBLISHED`."
    PRD: "**L5** follows from L4: one moderation case is auto-created for each swept post, in state `OPEN`, with `opened_reason` `AUTHOR_SUSPENDED` and `opened_by_user_id` set to the literal string `system`."

    Design: Difficulty/transitive_cascade/discriminatory_removal_cascades_five_levels_to_system_opened_cases
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    people = _seed_feed_residents(api)
    author_id = people["author_id"]
    flaggers = people["flagger_ids"]

    # Published six weeks before the removal, so it sits outside the lookback
    # that ends at 2026-07-13T03:00:00Z.
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    stale = fixtures.create_post(
        api,
        author_id,
        body="An old note published six weeks before the removal.",
        category=k.CATEGORY_GENERAL,
    )

    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    recent = fixtures.create_post(
        api,
        author_id,
        body="A recent note published inside the lookback window.",
        category=k.CATEGORY_LOST_PET,
    )
    # Inside the lookback but not published: two flags have already carried it
    # out of PUBLISHED.
    flagged = fixtures.seed_flagged_post(
        api,
        author_id,
        flaggers,
        body="A recent note the neighbours have already flagged twice.",
        category=k.CATEGORY_SAFETY_REPORT,
    )
    assert flagged["post"]["state"] == k.POST_FLAGGED

    # An accuracy strike first, so the discrimination strike reaches exactly 3.
    _remove_post(
        api,
        author_id,
        flaggers,
        k.DECISION_REMOVE_INACCURATE,
        body="A note removed for being inaccurate.",
    )

    fixtures.set_clock(api, "2026-08-12T03:00:00Z")
    target = fixtures.seed_post_under_review(
        api,
        author_id,
        flaggers,
        body="The note removed as discriminatory.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
    )
    stale_before = fixtures.read_post(api, stale["id"])
    flagged_before = fixtures.read_post(api, flagged["post_id"])

    fixtures.decide_case(
        api,
        target["case_id"],
        decision=k.DECISION_REMOVE_DISCRIMINATORY,
        decision_note="Targets a protected class; removed.",
    )

    author_after = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        author_after,
        {
            "accuracy_strike_count": 1,
            "discrimination_strike_count": 1,
            "total_strike_score": 3,
            "post_privilege_state": k.PRIVILEGE_POSTING_SUSPENDED,
        },
    )

    # The one post that qualifies on both tests is swept.
    swept = fixtures.read_post(api, recent["id"])
    assertions.assert_subset(
        swept,
        {
            "state": k.POST_UNDER_REVIEW,
            "auto_flag_reason": k.AUTO_FLAG_AUTHOR_UNDER_REVIEW,
            "flag_count": 0,
        },
    )
    assertions.assert_version_advanced(swept, recent["version"])

    # Too old: published, untouched, still carrying no automatic flag.
    stale_after = fixtures.read_post(api, stale["id"])
    assert stale_after["state"] == k.POST_PUBLISHED
    assertions.assert_nulls(stale_after, "auto_flag_reason")
    assertions.assert_version_unchanged(stale_after, stale_before["version"])

    # Recent enough, but it was never in PUBLISHED to be taken out of.
    flagged_after = fixtures.read_post(api, flagged["post_id"])
    assertions.assert_subset(
        flagged_after,
        {
            "state": k.POST_FLAGGED,
            "auto_flag_reason": k.AUTO_FLAG_RESIDENT_FLAGS,
            "flag_count": 2,
        },
    )
    assertions.assert_version_unchanged(flagged_after, flagged_before["version"])

    # Exactly one case, raised against exactly the swept post.
    rows, meta = _author_suspension_cases(api)
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assertions.assert_subset(
        rows[0],
        {
            "resident_post_id": recent["id"],
            "state": k.CASE_OPEN,
            "decision": k.DECISION_NONE,
            "opened_reason": k.OPENED_REASON_AUTHOR_SUSPENDED,
            "opened_by_user_id": k.SYSTEM_OPENER,
        },
    )
    assertions.assert_nulls(rows[0], "decided_by_user_id", "decided_at")
    assert fixtures.list_cases_for_post(api, stale["id"]) == []
    assert [
        case["opened_reason"]
        for case in fixtures.list_cases_for_post(api, flagged["post_id"])
    ] == []


def test_the_suspension_the_cascade_wrote_closes_the_feed_to_the_author(
    api: ApiClient,
) -> None:
    """Once the third level of the cascade has written `POSTING_SUSPENDED`, the author's next post is refused outright and nothing further moves.

    PRD: "**L2** recomputes `total_strike_score` as `accuracy_strike_count` plus twice `discrimination_strike_count` — a discrimination strike weighs double."
    PRD: "A resident whose `post_privilege_state` reads `POSTING_SUSPENDED` may not publish at all, and is refused with `ERR_POSTING_SUSPENDED`."

    Design: Difficulty/transitive_cascade/discriminatory_removal_cascades_five_levels_to_system_opened_cases
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    people = _seed_feed_residents(api)
    author_id = people["author_id"]
    flaggers = people["flagger_ids"]

    first_removal = _remove_post(
        api,
        author_id,
        flaggers,
        k.DECISION_REMOVE_INACCURATE,
        body="A note removed for being inaccurate.",
    )
    fixtures.set_clock(api, "2026-08-12T01:00:00Z")
    second_removal = _remove_post(
        api,
        author_id,
        flaggers,
        k.DECISION_REMOVE_DISCRIMINATORY,
        body="A note removed for targeting a protected class.",
    )

    suspended = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        suspended,
        {
            "accuracy_strike_count": 1,
            "discrimination_strike_count": 1,
            "total_strike_score": 3,
            "post_privilege_state": k.PRIVILEGE_POSTING_SUSPENDED,
        },
    )

    response = api.create_post(
        f.post_payload(
            author_id,
            body="A note attempted after the suspension landed.",
            category=k.CATEGORY_GENERAL,
        ),
        make_resident_headers(author_id),
    )
    validate_error(response, ApiErrorId.POSTING_SUSPENDED.value, 409)

    # The refusal writes nothing: the author's row and the feed are as the
    # cascade left them.
    after = fixtures.read_resident(api, author_id)
    assertions.assert_subset(
        after,
        {
            "total_strike_score": 3,
            "post_privilege_state": k.PRIVILEGE_POSTING_SUSPENDED,
        },
    )
    assertions.assert_version_unchanged(after, suspended["version"])

    authored = fixtures.list_rows(api, "list_posts", author_resident_id=author_id)
    assert [post["id"] for post in authored] == [
        first_removal["post_id"],
        second_removal["post_id"],
    ]
    assert [post["state"] for post in authored] == [k.POST_REMOVED, k.POST_REMOVED]
