"""Derived-value arithmetic: the frozen eligible-device roster and the post
alert fan-out.

Two derived figures are exercised here. The first is the eligible-device set a
canvass area freezes when it is locked: six cameras sit inside the same disc but
three of them are struck out by three different clauses of the input set, so the
count the area publishes says which clause was honoured. The second is the alert
fan-out of a community post, where candidacy is decided by each recipient's own
alert radius, the author is never a recipient of their own post, and the fan-out
cap truncates the tail of the nearest-first ordering rather than the candidate
pool.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import validate_success

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.test_users import make_officer_headers, make_resident_headers

# Six cameras on the same street, all inside a 500 m disc centred on the origin:
# squared distances 100, 400, 900, 1600, 2500 and 3600.
_SIX_POSITIONS: Tuple[Tuple[int, int], ...] = (
    (0, 10),
    (0, 20),
    (0, 30),
    (0, 40),
    (0, 50),
    (0, 60),
)

# The squared grid distances the first three of those cameras sit at.
_ROSTER_DISTANCES_SQ = [100, 400, 900]


def _seed_six_camera_block(api: ApiClient) -> Dict[str, Any]:
    """One onboarded agency, one requesting officer, six one-camera households
    and a draft 500 m canvass area over the standard six-hour footage window.

    The fourth camera is taken offline, the fifth is set to refuse outright by
    its owner, and the sixth owner leaves the video-request programme at the
    account level — three different reasons to be ineligible, applied before the
    area is drawn so that nothing has been frozen yet.
    """
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    households = fixtures.seed_residents_with_devices(api, _SIX_POSITIONS)

    fixtures.update_device(
        api,
        households[3]["device_id"],
        households[3]["resident_id"],
        status=k.DEVICE_STATUS_OFFLINE,
    )
    fixtures.update_device(
        api,
        households[4]["device_id"],
        households[4]["resident_id"],
        auto_decline_requests=True,
    )
    fixtures.exercise_data_control(api, households[5]["resident_id"], k.ACTION_OPT_OUT)

    world["households"] = households
    world["area"] = fixtures.create_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=0,
        center_y_m=0,
        radius_m=500,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
    )
    return world


def _seed_fanout_neighbourhood(api: ApiClient) -> Dict[str, Any]:
    """Four accounts on one street: the author at the origin, two neighbours who
    can see 800 m, and one neighbour whose own alert radius is 0.
    """
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=800,
        notification_budget_per_day=6,
    )
    near_one = fixtures.register_resident(
        api,
        display_name="Near One",
        email="n1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=800,
        notification_budget_per_day=6,
    )
    near_two = fixtures.register_resident(
        api,
        display_name="Near Two",
        email="n2@example.test",
        home_x_m=0,
        home_y_m=20,
        alert_radius_m=800,
        notification_budget_per_day=6,
    )
    far_one = fixtures.register_resident(
        api,
        display_name="Far One",
        email="f1@example.test",
        home_x_m=0,
        home_y_m=30,
        alert_radius_m=0,
        notification_budget_per_day=6,
    )
    return {
        "author_id": author["id"],
        "near_one_id": near_one["id"],
        "near_two_id": near_two["id"],
        "far_one_id": far_one["id"],
    }


def _dispatches_for_post(api: ApiClient, resident_id: str, post_id: str) -> List[Dict[str, Any]]:
    """Every alert dispatch this resident holds that names this post."""
    return [
        row
        for row in fixtures.list_dispatches(api, resident_id)
        if row.get("source_ref_id") == post_id
    ]


def test_lock_freezes_a_roster_of_three_out_of_six_cameras_in_the_disc(
    api: ApiClient, clock: str
) -> None:
    """Locking counts only the cameras that clear every clause of the input set.

    PRD: "A camera enters the roster only when all five of the following hold."
    PRD: "The number of cameras on this frozen roster is written to `eligible_device_count`, and their position in this ordering is the `dispatch_rank` each will carry when the request is actually sent."
    PRD: "Locking writes `locked_at` from the logical clock, moves the area `DRAFT → LOCKED`, and advances `version` by 1."
    PRD: "Locking also freezes the area's **minimum-participation threshold** into `effective_min_devices`, and this number is never recomputed afterwards — the submission gate re-reads it, it does not re-derive it."

    Design: Corner/calculations/eligible_device_roster_excludes_offline_auto_decline_and_opted_out
    """
    world = _seed_six_camera_block(api)
    area = world["area"]
    assertions.assert_subset(
        area,
        {
            "status": k.AREA_STATUS_DRAFT,
            "eligible_device_count": 0,
            "effective_min_devices": None,
            "derived_request_count": 0,
            "radius_m": 500,
        },
    )

    response = api.lock_request_area(
        area["id"], make_officer_headers(world["officer_id"])
    )
    locked = validate_success(response, 200)

    assertions.assert_subset(
        locked,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
            "derived_request_count": 0,
            "invalidated_reason": None,
        },
    )
    assertions.assert_version_advanced(locked, area["version"])
    assertions.assert_instant(locked["locked_at"], clock, "locked_at")

    # The count is frozen onto the row, not recomputed on every read.
    stored = fixtures.read_area(api, area["id"])
    assertions.assert_subset(
        stored,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
            "version": locked["version"],
        },
    )


def test_submit_dispatches_one_solicitation_to_each_rostered_camera_only(
    api: ApiClient, clock: str
) -> None:
    """The frozen roster of three decides who is asked, in nearest-first order.

    PRD: "One consent solicitation is then created per roster camera, in the pinned roster order of §3.3 (squared distance ascending, then camera `created_at` ascending), each carrying its `video_request_id`, its `device_id`, the `resident_id` of that camera's owner as at this moment, a `status` of `SOLICITED`, its `distance_sq_m2` — the exact integer squared grid distance from the camera to the area centre — its 1-based `dispatch_rank` within the batch, and a `respond_deadline_utc` copied from the request's `expires_at`."
    PRD: "For every camera solicited, `solicitations_received_count` and `pending_solicitation_count` are each incremented by 1."
    PRD: "On the request itself, `solicitation_count` and `pending_count` are both set to the number of solicitations created, the other four bucket counters stay at 0, and `provisional_share_rate_bps` is 0."

    Design: Corner/calculations/eligible_device_roster_excludes_offline_auto_decline_and_opted_out
    """
    world = _seed_six_camera_block(api)
    households = world["households"]
    officer_id = world["officer_id"]

    locked = fixtures.lock_area(api, world["area"]["id"], officer_id)
    assert locked["eligible_device_count"] == 3, (
        f"Expected a frozen roster of three, got {locked['eligible_device_count']}"
    )

    request = fixtures.create_video_request(
        api, locked, officer_id, case_number="CASE-1003"
    )
    fixtures.log_justification(api, request["id"], officer_id)

    response = api.submit_video_request(request["id"], make_officer_headers(officer_id))
    submitted = validate_success(response, 200)

    assertions.assert_subset(
        submitted,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "solicitation_count": 3,
            "shared_clip_count": 0,
        },
    )
    assertions.assert_solicitation_buckets(
        submitted, pending=3, shared=0, declined=0, expired=0, withdrawn=0
    )
    assertions.assert_bps(
        submitted["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )

    rows = fixtures.list_solicitations(api, video_request_id=request["id"])
    assert len(rows) == 3, f"Expected exactly three solicitations, got {len(rows)}"
    assertions.assert_field_sequence(
        rows, "device_id", [h["device_id"] for h in households[:3]]
    )
    assertions.assert_field_sequence(
        rows, "resident_id", [h["resident_id"] for h in households[:3]]
    )
    assertions.assert_field_sequence(rows, "dispatch_rank", [1, 2, 3])
    assertions.assert_field_sequence(rows, "distance_sq_m2", _ROSTER_DISTANCES_SQ)
    assertions.assert_field_sequence(
        rows, "status", [k.SOLICITATION_SOLICITED] * 3
    )
    for row in rows:
        assert row["video_request_id"] == request["id"]
        assert row["clip_count"] == 0
        assertions.assert_instant(
            row["respond_deadline_utc"], submitted["expires_at"], "respond_deadline_utc"
        )
        assertions.assert_nulls(row, "responded_at", "decline_reason")

    # Each rostered camera now carries exactly one unanswered ask.
    for household in households[:3]:
        device = fixtures.read_device(api, household["device_id"])
        assertions.assert_subset(
            device,
            {"solicitations_received_count": 1, "pending_solicitation_count": 1},
        )

    # The offline camera, the refusing camera and the opted-out camera were
    # never asked at all: no row names them and neither counter moved.
    solicited_device_ids = {row["device_id"] for row in rows}
    for household in households[3:]:
        assert household["device_id"] not in solicited_device_ids, (
            f"Camera {household['device_id']} is ineligible and must not be solicited"
        )
        device = fixtures.read_device(api, household["device_id"])
        assertions.assert_subset(
            device,
            {"solicitations_received_count": 0, "pending_solicitation_count": 0},
        )


def test_each_excluded_camera_carries_the_posture_that_removed_it(
    api: ApiClient, clock: str
) -> None:
    """Three different clauses strike out three different cameras.

    PRD: "Its `auto_decline_requests` is false, so a blanket owner refusal is out."
    PRD: "Setting `auto_decline_requests` to true records `auto_decline_source` `OWNER_MANUAL` and excludes the camera from **future** eligible-device sets only; solicitations already dispatched to it are untouched and remain answerable."
    PRD: "Level two sets `auto_decline_requests` to true and `auto_decline_source` to `OPT_OUT` on every camera of that resident that is not `DECOMMISSIONED`."
    PRD: "Level one sets `data_sharing_opt_out` to true on the resident."

    Design: Corner/calculations/eligible_device_roster_excludes_offline_auto_decline_and_opted_out
    """
    world = _seed_six_camera_block(api)
    households = world["households"]

    # The three cameras that survive every clause.
    for household in households[:3]:
        device = fixtures.read_device(api, household["device_id"])
        assertions.assert_subset(
            device,
            {
                "status": k.DEVICE_STATUS_ACTIVE,
                "auto_decline_requests": False,
                "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
            },
        )
        owner = fixtures.read_resident(api, household["resident_id"])
        assertions.assert_subset(
            owner,
            {
                "status": k.RESIDENT_STATUS_ACTIVE,
                "data_sharing_opt_out": False,
            },
        )

    # Struck out by the camera-status clause, with no refusal recorded anywhere.
    offline = fixtures.read_device(api, households[3]["device_id"])
    assertions.assert_subset(
        offline,
        {
            "status": k.DEVICE_STATUS_OFFLINE,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        },
    )

    # Struck out by the owner's own blanket refusal on a still-active camera.
    manual = fixtures.read_device(api, households[4]["device_id"])
    assertions.assert_subset(
        manual,
        {
            "status": k.DEVICE_STATUS_ACTIVE,
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OWNER_MANUAL,
        },
    )
    manual_owner = fixtures.read_resident(api, households[4]["resident_id"])
    assert manual_owner["data_sharing_opt_out"] is False, (
        "A manual camera refusal is not an account-level opt-out"
    )

    # Struck out by the account-level opt-out, which set the camera's flag itself.
    opted_out = fixtures.read_device(api, households[5]["device_id"])
    assertions.assert_subset(
        opted_out,
        {
            "status": k.DEVICE_STATUS_ACTIVE,
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
        },
    )
    opted_out_owner = fixtures.read_resident(api, households[5]["resident_id"])
    assertions.assert_subset(
        opted_out_owner,
        {
            "status": k.RESIDENT_STATUS_ACTIVE,
            "data_sharing_opt_out": True,
        },
    )

    # Three postures, three exclusions, one count.
    locked = fixtures.lock_area(api, world["area"]["id"], world["officer_id"])
    assert locked["eligible_device_count"] == 3, (
        "Six cameras sit in the disc; only three clear every clause, so the "
        f"frozen count is 3, got {locked['eligible_device_count']}"
    )


def test_alert_fanout_cap_of_one_truncates_the_tail_of_the_candidate_order(
    api: ApiClient, clock: str
) -> None:
    """A cap of 1 keeps the leading candidate and drops the rest of the tail.

    PRD: "`alert_candidate_count` records the size of the ordered list **before** the cap is applied, and the cap then truncates the **tail**, keeping the leading entries."
    PRD: "`alert_fanout_count` counts the resulting dispatches that were delivered and `alert_suppressed_count` counts those that were suppressed, so the two together sum to the **lesser** of `alert_candidate_count` and `alert_fanout_cap` — not to `alert_candidate_count`."
    PRD: "A score below 0.49 means the post is created in `PUBLISHED` with a null `auto_flag_reason` and the alert fan-out runs immediately."

    Design: Corner/calculations/post_alert_fanout_cap_truncates_tail_and_never_alerts_author
    """
    people = _seed_fanout_neighbourhood(api)

    response = api.create_post(
        f.post_payload(
            people["author_id"],
            body="Two bicycles were taken from the shared rack behind the building last night.",
            category=k.CATEGORY_SAFETY_REPORT,
            post_x_m=0,
            post_y_m=0,
            alert_fanout_cap=1,
        ),
        make_resident_headers(people["author_id"]),
    )
    post = validate_success(response, 201)

    assertions.assert_mutable_common_fields(post, version=1)
    assertions.assert_subset(
        post,
        {
            "state": k.POST_PUBLISHED,
            "auto_flag_reason": None,
            "alert_fanout_cap": 1,
            "alert_candidate_count": 2,
            "alert_fanout_count": 1,
            "alert_suppressed_count": 0,
        },
    )
    assertions.assert_score(post["discrimination_score"], "0.00")
    assertions.assert_fanout_conservation(post, 1)

    # The candidate pool was two, so the cap — not the pool — is what limited
    # the fan-out to one.
    assert post["alert_candidate_count"] > post["alert_fanout_cap"], (
        "The cap must be the binding constraint for this scenario to discriminate"
    )

    stored = fixtures.read_post(api, post["id"])
    assertions.assert_subset(
        stored,
        {
            "alert_candidate_count": 2,
            "alert_fanout_count": 1,
            "alert_suppressed_count": 0,
            "version": 1,
        },
    )


def test_the_single_capped_alert_reaches_the_nearer_candidate_and_not_the_author(
    api: ApiClient, clock: str
) -> None:
    """One dispatch exists, aimed at the nearest neighbour; the author gets none.

    PRD: "Every resident is considered except the author themselves and except any resident whose `status` is not `ACTIVE`."
    PRD: "Each surviving candidate receives exactly one notification dispatch, its `batch_sequence_no` assigned in that same order, with delivery or suppression decided by the fatigue rules of §3.7."
    PRD: "Each dispatch names its recipient as `resident_id`, its `kind` — either `CONSENT_SOLICITATION` when it accompanies a consent solicitation or `POST_ALERT` when it accompanies a neighbourhood post — and its `source_ref_id`, a polymorphic reference holding the identifier of the consent solicitation for the first kind and of the community post for the second."
    PRD: "Otherwise the dispatch is delivered — `suppressed` false and `suppression_reason` null — the delivered count for this batch rises by 1, and the recipient's `notifications_sent_today` rises by 1."

    Design: Corner/calculations/post_alert_fanout_cap_truncates_tail_and_never_alerts_author
    """
    people = _seed_fanout_neighbourhood(api)

    post = fixtures.create_post(
        api,
        people["author_id"],
        body="Two bicycles were taken from the shared rack behind the building last night.",
        post_x_m=0,
        post_y_m=0,
        alert_fanout_cap=1,
    )

    delivered = _dispatches_for_post(api, people["near_one_id"], post["id"])
    assert len(delivered) == 1, (
        f"The nearest candidate takes the one uncapped slot, got {len(delivered)} dispatches"
    )
    assertions.assert_subset(
        delivered[0],
        {
            "resident_id": people["near_one_id"],
            "kind": k.DISPATCH_KIND_POST_ALERT,
            "source_ref_id": post["id"],
            "batch_sequence_no": 1,
            "suppressed": False,
            "suppression_reason": None,
        },
    )

    # The truncated tail, the far-sighted-enough-only neighbour and the author
    # himself hold no dispatch for this post at all.
    for label, resident_id in (
        ("the truncated second candidate", people["near_two_id"]),
        ("the resident whose own alert radius is 0", people["far_one_id"]),
        ("the author", people["author_id"]),
    ):
        assert _dispatches_for_post(api, resident_id, post["id"]) == [], (
            f"No dispatch may exist for {label}"
        )

    near_one = fixtures.read_resident(api, people["near_one_id"])
    assert near_one["notifications_sent_today"] == 1, (
        "A delivered alert raises the recipient's daily counter by 1, got "
        f"{near_one['notifications_sent_today']}"
    )
    assert near_one["fatigue_state"] == k.FATIGUE_NORMAL

    for resident_id in (
        people["near_two_id"],
        people["far_one_id"],
        people["author_id"],
    ):
        resident = fixtures.read_resident(api, resident_id)
        assert resident["notifications_sent_today"] == 0, (
            "A resident who was never dispatched to keeps a daily counter of 0, got "
            f"{resident['notifications_sent_today']}"
        )
        assert resident["fatigue_state"] == k.FATIGUE_NORMAL


def test_without_a_truncating_cap_both_radius_qualifying_neighbours_are_alerted(
    api: ApiClient, clock: str
) -> None:
    """Candidacy rests on each recipient's own radius, so the pool really is two.

    PRD: "For each remaining resident, the squared distance from the post's position to that resident's `home_x_m` and `home_y_m` is computed as an exact integer, and the resident is a candidate when that squared distance is no greater than the square of **their own** `alert_radius_m` — a closed disc, boundary inclusive, per §2.6."
    PRD: "Candidates are then ordered by ascending squared distance and, for equal distances, by ascending `Resident.created_at` — nearest home first, then earliest account."
    PRD: "`alert_candidate_count` records the size of the ordered list **before** the cap is applied, and the cap then truncates the **tail**, keeping the leading entries."

    Design: Corner/calculations/post_alert_fanout_cap_truncates_tail_and_never_alerts_author
    """
    people = _seed_fanout_neighbourhood(api)

    # No cap is supplied, so the declared default of 50 applies and nothing is
    # truncated: the same two candidates are both alerted.
    response = api.create_post(
        f.post_payload(
            people["author_id"],
            body="Two bicycles were taken from the shared rack behind the building last night.",
            category=k.CATEGORY_SAFETY_REPORT,
            post_x_m=0,
            post_y_m=0,
        ),
        make_resident_headers(people["author_id"]),
    )
    post = validate_success(response, 201)

    assertions.assert_subset(
        post,
        {
            "state": k.POST_PUBLISHED,
            "alert_fanout_cap": k.DEFAULT_ALERT_FANOUT_CAP,
            "alert_candidate_count": 2,
            "alert_fanout_count": 2,
            "alert_suppressed_count": 0,
        },
    )
    assertions.assert_fanout_conservation(post, k.DEFAULT_ALERT_FANOUT_CAP)

    # Nearest home first: the neighbour 10 m away leads the batch, the one 20 m
    # away follows it.
    for expected_sequence, resident_id in (
        (1, people["near_one_id"]),
        (2, people["near_two_id"]),
    ):
        rows = _dispatches_for_post(api, resident_id, post["id"])
        assert len(rows) == 1, (
            f"Each candidate receives exactly one dispatch, got {len(rows)}"
        )
        assertions.assert_subset(
            rows[0],
            {
                "kind": k.DISPATCH_KIND_POST_ALERT,
                "batch_sequence_no": expected_sequence,
                "suppressed": False,
                "suppression_reason": None,
            },
        )
        resident = fixtures.read_resident(api, resident_id)
        assert resident["notifications_sent_today"] == 1

    # The author and the neighbour whose own radius is 0 are still not
    # candidates, so raising the cap reaches neither of them.
    for resident_id in (people["author_id"], people["far_one_id"]):
        assert _dispatches_for_post(api, resident_id, post["id"]) == []
        resident = fixtures.read_resident(api, resident_id)
        assert resident["notifications_sent_today"] == 0
