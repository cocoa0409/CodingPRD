"""Two rules broken by one call: the higher-priority refusal is the one reported.

Each scenario here arms two refusals at once on a single write and checks that the
portal names the earlier rule in its ordering. Each pair is then disarmed in one
place only — the higher-priority condition is repaired and the identical call is
reissued — so the second, lower-priority refusal surfaces on its own. That second
call is what shows the lower rule really was violated during the first call rather
than merely unreached.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_resident_headers

# A second canvass centre far enough from the origin that the repeat-canvass
# proximity disc of 300 m never touches the first area.
FAR_CENTRE_X_M = 5000
FAR_CENTRE_Y_M = 5000
FAR_POSITIONS = ((5000, 5010), (5000, 5020), (5000, 5030))

# Two footage segments on one camera that genuinely overlap: the second begins
# ten minutes before the first one ends.
FIRST_SEGMENT_START = "2026-08-08T01:00:00Z"
OVERLAPPING_SEGMENT_START = "2026-08-08T01:20:00Z"
SEGMENT_SECONDS = 1800


def _seed_quota_pressed_world(api: ApiClient) -> Dict[str, Any]:
    """An agency at its one-open-request ceiling plus a second, unjustified draft request."""
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(
        api,
        duty_role=k.DUTY_ROLE_REQUESTER,
        min_device_threshold=3,
        max_open_requests=1,
        period_request_quota=20,
    )
    fixtures.seed_residents_with_devices(api, fixtures.STANDARD_POSITIONS)
    fixtures.seed_residents_with_devices(api, FAR_POSITIONS, prefix="Q")

    near_area = fixtures.seed_locked_area(api, world["agency_id"], world["officer_id"])
    first = fixtures.create_video_request(
        api, near_area, world["officer_id"], case_number="CASE-P"
    )
    fixtures.log_justification(api, first["id"], world["officer_id"])
    fixtures.submit_request(api, first["id"], world["officer_id"])

    far_area = fixtures.seed_locked_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=FAR_CENTRE_X_M,
        center_y_m=FAR_CENTRE_Y_M,
        area_label="Riverside Q",
    )
    # The guarded creation quotes the area version read immediately beforehand.
    observed_area = fixtures.read_area(api, far_area["id"])
    second = fixtures.create_video_request(
        api, observed_area, world["officer_id"], case_number="CASE-Q"
    )

    world["first_request_id"] = first["id"]
    world["area_id"] = far_area["id"]
    world["request_id"] = second["id"]
    world["request"] = second
    return world


def _assert_second_request_never_left_draft(
    api: ApiClient,
    world: Dict[str, Any],
    request_version: int,
    area_version: int,
    compliance_state: str,
) -> None:
    """The refused request, its backing area and the agency ledger all stand still."""
    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(request, request_version)
    assertions.assert_subset(
        request,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": compliance_state,
            "solicitation_count": 0,
            "shared_clip_count": 0,
            "provisional_share_rate_bps": 0,
        },
    )
    assertions.assert_solicitation_buckets(request, 0, 0, 0, 0, 0)
    assertions.assert_nulls(request, "submitted_at", "expires_at")
    assert fixtures.list_solicitations(api, video_request_id=world["request_id"]) == [], (
        "A refused submission dispatches no solicitation at all"
    )

    area = fixtures.read_area(api, world["area_id"])
    assertions.assert_version_unchanged(area, area_version)
    assertions.assert_subset(
        area,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
            "derived_request_count": 1,
        },
    )

    agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        agency,
        {"open_request_count": 1, "requests_submitted_count": 1},
    )


def test_unlogged_justification_outranks_the_open_request_quota(api: ApiClient) -> None:
    """A submit that is both unjustified and over the open-request quota reports the justification gate.

    PRD: "Rules are evaluated strictly in the order below, the first violated rule decides the response, and no later rule is evaluated once one has fired."
    PRD: "The compliance dimension must have moved off `JUSTIFICATION_PENDING`, or the answer is `ERR_JUSTIFICATION_NOT_LOGGED`."
    PRD: "The agency's two quotas are checked **last**, after every state precondition and every other business rule, so a quota breach can never mask a consent, window or threshold failure."

    Design: Difficulty/priority_pair_validation_conflict/submit_state_rule_16_beats_fiscal_rule_44
    """
    world = _seed_quota_pressed_world(api)

    # Both rules are genuinely armed before the call: the request has never been
    # justified, and the agency already holds the single open request it allows.
    before_request = fixtures.read_request(api, world["request_id"])
    assertions.assert_subset(
        before_request,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_PENDING,
        },
    )
    before_area = fixtures.read_area(api, world["area_id"])
    assertions.assert_subset(
        before_area,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
            "derived_request_count": 1,
        },
    )
    before_agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        before_agency,
        {
            "max_open_requests": 1,
            "open_request_count": 1,
            "requests_submitted_count": 1,
        },
    )

    response = api.submit_video_request(world["request_id"], world["officer_headers"])
    validate_error(response, ApiErrorId.JUSTIFICATION_NOT_LOGGED.value, 409)

    _assert_second_request_never_left_draft(
        api,
        world,
        before_request["version"],
        before_area["version"],
        k.COMPLIANCE_JUSTIFICATION_PENDING,
    )


def test_open_request_quota_surfaces_once_the_justification_is_repaired(api: ApiClient) -> None:
    """Repairing only the justification leaves the quota breach standing, and it is then reported.

    PRD: "On success both fields are stored, `justification_logged_at` is stamped from the logical clock, and the compliance dimension moves `JUSTIFICATION_PENDING → JUSTIFICATION_LOGGED`."
    PRD: "The first gate is concurrent load: when `open_request_count` has reached `max_open_requests` the submission is refused with `ERR_AGENCY_OPEN_REQUEST_QUOTA_EXCEEDED`; the comparison is inclusive, so an agency configured to allow one open request is blocked while exactly one of its requests is `SOLICITING` and is unblocked the instant that request resolves."
    PRD: "Either way `lifecycle_state` is left untouched at `DRAFT` and the request's `version` advances by 1."

    Design: Difficulty/priority_pair_validation_conflict/submit_state_rule_16_beats_fiscal_rule_44
    """
    world = _seed_quota_pressed_world(api)
    area_version = fixtures.read_area(api, world["area_id"])["version"]

    # Repair the state violation only: log the justification and change nothing
    # about the agency's concurrent load.
    logged = fixtures.log_justification(api, world["request_id"], world["officer_id"])
    assertions.assert_subset(
        logged,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
        },
    )
    assertions.assert_version_advanced(logged, world["request"]["version"])

    before_request = fixtures.read_request(api, world["request_id"])
    before_agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        before_agency,
        {
            "max_open_requests": 1,
            "open_request_count": 1,
            "requests_submitted_count": 1,
        },
    )
    first_request = fixtures.read_request(api, world["first_request_id"])
    assert first_request["lifecycle_state"] == k.LIFECYCLE_SOLICITING, (
        "The agency's one permitted open request must still be canvassing"
    )

    response = api.submit_video_request(world["request_id"], world["officer_headers"])
    validate_error(response, ApiErrorId.AGENCY_OPEN_REQUEST_QUOTA_EXCEEDED.value, 409)

    _assert_second_request_never_left_draft(
        api,
        world,
        before_request["version"],
        area_version,
        k.COMPLIANCE_JUSTIFICATION_LOGGED,
    )
    # The refusal charged neither quota, so the canvassing sibling is untouched.
    still_soliciting = fixtures.read_request(api, world["first_request_id"])
    assertions.assert_version_unchanged(still_soliciting, first_request["version"])
    assert still_soliciting["lifecycle_state"] == k.LIFECYCLE_SOLICITING


def _seed_opted_out_repeat_sharer(api: ApiClient) -> Dict[str, Any]:
    """One owner who has already shared a segment and has since opted out of requests."""
    world = fixtures.seed_standard_canvass(api)
    household = world["households"][0]
    solicitation = fixtures.solicitation_for_device(
        api, world["request_id"], household["device_id"]
    )
    clip = fixtures.share_footage(
        api,
        solicitation["id"],
        household["resident_id"],
        recorded_start_utc=FIRST_SEGMENT_START,
        duration_seconds=SEGMENT_SECONDS,
    )
    receipt = fixtures.exercise_data_control(
        api, household["resident_id"], k.ACTION_OPT_OUT
    )

    world["resident_id"] = household["resident_id"]
    world["sharer_headers"] = make_resident_headers(household["resident_id"])
    world["device_id"] = household["device_id"]
    world["solicitation_id"] = solicitation["id"]
    world["clip_id"] = clip["id"]
    world["area_id"] = world["area"]["id"]
    world["opt_out_receipt"] = receipt
    return world


def _assert_single_shared_clip_intact(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    solicitation_version: int,
    clip_version: int,
    request_version: int,
) -> None:
    """The one consent given, the one clip it produced and every ledger stand exactly still."""
    solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assertions.assert_version_unchanged(solicitation, solicitation_version)
    assertions.assert_subset(
        solicitation,
        {"status": k.SOLICITATION_SHARED, "clip_count": 1, "decline_reason": None},
    )

    clip = fixtures.read_clip(api, world["clip_id"])
    assertions.assert_version_unchanged(clip, clip_version)
    assertions.assert_subset(
        clip,
        {
            "status": k.CLIP_RETAINED,
            "retention_variant": k.RETENTION_DEVICE_ANCHORED,
            "duration_seconds": SEGMENT_SECONDS,
        },
    )
    assertions.assert_instant(
        clip["recorded_start_utc"], FIRST_SEGMENT_START, "recorded_start_utc"
    )
    assertions.assert_nulls(clip, "purged_at", "purge_reason")
    assert len(fixtures.list_clips_for_device(api, world["device_id"])) == 1, (
        "A refused share must not leave a second clip on the camera"
    )

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(request, request_version)
    assertions.assert_subset(
        request,
        {"lifecycle_state": k.LIFECYCLE_SOLICITING, "shared_clip_count": 1},
    )
    assertions.assert_solicitation_buckets(request, 2, 1, 0, 0, 0)
    assertions.assert_solicitation_ledger(request, 3)
    assertions.assert_bps(request["provisional_share_rate_bps"], 3333)

    resident = fixtures.read_resident(api, world["resident_id"])
    assertions.assert_footage_ledger(
        resident, lifetime=SEGMENT_SECONDS, retained=SEGMENT_SECONDS, purged=0
    )

    area = fixtures.read_area(api, world["area_id"])
    assertions.assert_subset(
        area,
        {
            "status": k.AREA_STATUS_INVALIDATED,
            "invalidated_reason": k.INVALIDATED_ELIGIBILITY,
        },
    )


def test_account_opt_out_outranks_the_overlapping_footage_segment(api: ApiClient) -> None:
    """A share that both breaks an account opt-out and overlaps an existing clip reports the opt-out.

    PRD: "Their `data_sharing_opt_out` must be false — an account-level opt-out is an absolute refusal to participate and is checked before any window, conflict or quota consideration, refused with `ERR_RESIDENT_OPTED_OUT`."
    PRD: "Second, non-collision: the offered half-open segment must not intersect the half-open interval of any existing clip on the **same camera** whose `status` is not `PURGED`."
    PRD: "The resident answering a solicitation has not opted out of video requests at the account level — otherwise `ERR_RESIDENT_OPTED_OUT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/share_safety_rule_30_beats_constraint_rule_40
    """
    world = _seed_opted_out_repeat_sharer(api)

    # The opt-out closed the camera to future canvasses but touched no solicitation
    # and no clip, because this owner had already answered.
    assertions.assert_subset(
        world["opt_out_receipt"],
        {
            "action_type": k.ACTION_OPT_OUT,
            "affected_device_count": 1,
            "affected_solicitation_count": 0,
            "affected_clip_count": 0,
        },
    )
    before_resident = fixtures.read_resident(api, world["resident_id"])
    assert before_resident["data_sharing_opt_out"] is True
    before_device = fixtures.read_device(api, world["device_id"])
    assertions.assert_subset(
        before_device,
        {
            "status": k.DEVICE_STATUS_ACTIVE,
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
        },
    )
    before_solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assert before_solicitation["status"] == k.SOLICITATION_SHARED
    before_clip = fixtures.read_clip(api, world["clip_id"])
    before_request = fixtures.read_request(api, world["request_id"])

    # The segment offered overlaps the one already shared from this same camera,
    # so the interval rule is armed too — but it sits below the opt-out.
    response = api.share_footage(
        world["solicitation_id"],
        f.share_payload(
            recorded_start_utc=OVERLAPPING_SEGMENT_START,
            duration_seconds=SEGMENT_SECONDS,
        ),
        world["sharer_headers"],
    )
    validate_error(response, ApiErrorId.RESIDENT_OPTED_OUT.value, 409)

    _assert_single_shared_clip_intact(
        api,
        world,
        solicitation_version=before_solicitation["version"],
        clip_version=before_clip["version"],
        request_version=before_request["version"],
    )


def test_device_window_conflict_surfaces_once_the_opt_out_is_reversed(api: ApiClient) -> None:
    """Opting back in disarms only the account refusal, and the identical share then hits the interval rule.

    PRD: "It sets `data_sharing_opt_out` back to false, and clears `auto_decline_requests` on exactly those cameras whose `auto_decline_source` is `OPT_OUT`, resetting their `auto_decline_source` to `NONE`."
    PRD: "Intervals that merely touch at an endpoint do not conflict — a segment ending exactly where another begins is fine — but one second of true overlap is refused with `ERR_DEVICE_WINDOW_CONFLICT`."
    PRD: "The offered footage segment does not collide with footage already shared from the same camera — otherwise `ERR_DEVICE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/share_safety_rule_30_beats_constraint_rule_40
    """
    world = _seed_opted_out_repeat_sharer(api)

    # Reverse the account-level refusal and nothing else.
    fixtures.exercise_data_control(api, world["resident_id"], k.ACTION_OPT_IN)

    reinstated = fixtures.read_resident(api, world["resident_id"])
    assert reinstated["data_sharing_opt_out"] is False
    assert reinstated["status"] == k.RESIDENT_STATUS_ACTIVE
    before_device = fixtures.read_device(api, world["device_id"])
    assertions.assert_subset(
        before_device,
        {
            "status": k.DEVICE_STATUS_ACTIVE,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
            "pending_solicitation_count": 0,
        },
    )

    before_solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    before_clip = fixtures.read_clip(api, world["clip_id"])
    before_request = fixtures.read_request(api, world["request_id"])

    response = api.share_footage(
        world["solicitation_id"],
        f.share_payload(
            recorded_start_utc=OVERLAPPING_SEGMENT_START,
            duration_seconds=SEGMENT_SECONDS,
        ),
        world["sharer_headers"],
    )
    validate_error(response, ApiErrorId.DEVICE_WINDOW_CONFLICT.value, 409)

    _assert_single_shared_clip_intact(
        api,
        world,
        solicitation_version=before_solicitation["version"],
        clip_version=before_clip["version"],
        request_version=before_request["version"],
    )
    after_device = fixtures.read_device(api, world["device_id"])
    assertions.assert_version_unchanged(after_device, before_device["version"])
    after_resident = fixtures.read_resident(api, world["resident_id"])
    assertions.assert_version_unchanged(after_resident, reinstated["version"])
    assert after_resident["data_sharing_opt_out"] is False
