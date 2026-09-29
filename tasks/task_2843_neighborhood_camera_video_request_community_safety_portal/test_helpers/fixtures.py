"""Composite fixtures that walk the API to a wanted state.

The harness restarts the server before every individual test, so each test
starts against an empty deployment and has to build the world it needs from
scratch. These helpers do that walking only through the public API — never
around it — and return the rows, identifiers and headers the test then asserts
against.

They are ordered from the smallest step to the widest scenario:

  Tier 1  the logical clock, agencies, officers, residents and cameras
  Tier 2  canvass areas, video requests and the submit-time dispatch
  Tier 3  answering solicitations: sharing, declining, purging and sweeping
  Tier 4  the community feed: posting, flagging, moderating and revising
  Tier 5  transparency reports
  Tier 6  read-through helpers for final-state assertions

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import (
    ACTION_OPT_OUT,
    AGENCY_STATUS_SUSPENDED,
    AUDIT_DECISION_ESCALATE,
    DUTY_ROLE_AUDITOR,
    DUTY_ROLE_REQUESTER,
    PURGE_OWNER_REVOCATION,
)
from .test_users import (
    ANONYMOUS_HEADERS,
    MODERATOR_HEADERS,
    MODERATOR_SECOND_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PLATFORM_ADMIN_SECOND_HEADERS,
    make_agency_admin_headers,
    make_officer_headers,
    make_resident_headers,
)

# The instant every scenario pins the clock to before it builds anything: late
# enough that a footage window a few days earlier is already in the past.
SCENARIO_CLOCK = "2026-08-12T00:00:00Z"

# The closed footage window most canvass areas use, six hours on 8 August.
FOOTAGE_WINDOW_START = "2026-08-08T00:00:00Z"
FOOTAGE_WINDOW_END = "2026-08-08T06:00:00Z"

# The three camera positions a standard canvass is built around: squared
# distances 100, 400 and 900 from the centre at the origin.
STANDARD_POSITIONS: Tuple[Tuple[int, int], ...] = ((0, 10), (0, 20), (0, 30))


# ═══ Tier 1: clock, agencies, officers, residents, cameras ═════════════════

def set_clock(api: ApiClient, to_iso8601: str, headers: Optional[Dict[str, str]] = None):
    """Move the logical clock and return what the write reported."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601), headers or PLATFORM_ADMIN_HEADERS)
    )


def register_agency(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register an agency, which lands under review and may do nothing yet."""
    return get_success_data(
        api.create_agency(f.agency_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def review_onboarding(api: ApiClient, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record the onboarding review of a pending agency."""
    return get_success_data(
        api.review_agency_onboarding(
            agency_id, f.onboarding_review_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def onboarded_agency(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register an agency and approve its onboarding, returning the onboarded row."""
    agency = register_agency(api, **overrides)
    return review_onboarding(api, agency["id"])


def change_agency_status(
    api: ApiClient, agency_id: str, target_status: str, **overrides: Any
) -> Dict[str, Any]:
    """Suspend, reinstate or revoke an agency."""
    return get_success_data(
        api.change_agency_status(
            agency_id,
            f.status_change_payload(target_status, **overrides),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def suspend_agency(api: ApiClient, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    """Suspend an onboarded agency, running the enforcement cascade."""
    return change_agency_status(api, agency_id, AGENCY_STATUS_SUSPENDED, **overrides)


def create_officer(
    api: ApiClient, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Enrol an officer at an onboarded agency, acting as that agency's admin."""
    return get_success_data(
        api.create_officer(
            f.officer_payload(agency_id, **overrides), make_agency_admin_headers(agency_id)
        )
    )


def register_resident(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a resident account through the self-registration route."""
    return get_success_data(
        api.create_resident(f.resident_payload(**overrides), ANONYMOUS_HEADERS)
    )


def register_device(
    api: ApiClient, resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Register a camera owned by this resident, acting as that resident."""
    return get_success_data(
        api.create_device(
            f.device_payload(resident_id, **overrides), make_resident_headers(resident_id)
        )
    )


def update_device(
    api: ApiClient, device_id: str, owner_resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Update an owned camera, acting as its owner."""
    return get_success_data(
        api.update_device(
            device_id,
            f.device_patch_payload(**overrides),
            make_resident_headers(owner_resident_id),
        )
    )


def exercise_data_control(
    api: ApiClient, resident_id: str, action_type: str = ACTION_OPT_OUT, **overrides: Any
) -> Dict[str, Any]:
    """Exercise an account-level data control and return the receipt."""
    return get_success_data(
        api.exercise_data_control(
            resident_id,
            f.data_control_payload(action_type, **overrides),
            make_resident_headers(resident_id),
        )
    )


def update_alert_settings(
    api: ApiClient, resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Update a resident's own alert configuration."""
    return get_success_data(
        api.update_alert_settings(
            resident_id,
            f.alert_settings_payload(**overrides),
            make_resident_headers(resident_id),
        )
    )


# ── Small bundles ──────────────────────────────────────────────────────────

def seed_agency_with_officer(
    api: ApiClient,
    *,
    duty_role: str = DUTY_ROLE_REQUESTER,
    badge_number: str = "B-100",
    full_name: str = "Officer Vale",
    **agency_overrides: Any,
) -> Dict[str, Any]:
    """An onboarded agency plus one officer, with both header sets to hand."""
    agency = onboarded_agency(api, **agency_overrides)
    officer = create_officer(
        api,
        agency["id"],
        badge_number=badge_number,
        full_name=full_name,
        duty_role=duty_role,
    )
    return {
        "agency": agency,
        "agency_id": agency["id"],
        "agency_headers": make_agency_admin_headers(agency["id"]),
        "officer": officer,
        "officer_id": officer["id"],
        "officer_headers": make_officer_headers(officer["id"]),
    }


def add_auditor(
    api: ApiClient,
    agency_id: str,
    *,
    badge_number: str = "B-200",
    full_name: str = "Officer Iyer",
    duty_role: str = DUTY_ROLE_AUDITOR,
) -> Dict[str, Any]:
    """A second officer at the same agency who is allowed to audit."""
    officer = create_officer(
        api,
        agency_id,
        badge_number=badge_number,
        full_name=full_name,
        duty_role=duty_role,
    )
    officer["_headers"] = make_officer_headers(officer["id"])
    return officer


def seed_resident_with_device(
    api: ApiClient,
    *,
    display_name: str = "R1",
    email: str = "r1@example.test",
    x: int = 0,
    y: int = 10,
    alert_radius_m: int = 0,
    notification_budget_per_day: Optional[int] = None,
    notification_mute_enabled: Optional[bool] = None,
    label: str = "Front door camera",
    retention_window_days: int = 30,
    auto_decline_requests: Optional[bool] = None,
    device_x: Optional[int] = None,
    device_y: Optional[int] = None,
) -> Dict[str, Any]:
    """One resident at a grid point, owning one camera at the same point."""
    resident_kwargs: Dict[str, Any] = {
        "display_name": display_name,
        "email": email,
        "home_x_m": x,
        "home_y_m": y,
        "alert_radius_m": alert_radius_m,
    }
    if notification_budget_per_day is not None:
        resident_kwargs["notification_budget_per_day"] = notification_budget_per_day
    if notification_mute_enabled is not None:
        resident_kwargs["notification_mute_enabled"] = notification_mute_enabled
    resident = register_resident(api, **resident_kwargs)

    device_kwargs: Dict[str, Any] = {
        "label": label,
        "grid_x_m": x if device_x is None else device_x,
        "grid_y_m": y if device_y is None else device_y,
        "retention_window_days": retention_window_days,
    }
    if auto_decline_requests is not None:
        device_kwargs["auto_decline_requests"] = auto_decline_requests
    device = register_device(api, resident["id"], **device_kwargs)

    return {
        "resident": resident,
        "resident_id": resident["id"],
        "headers": make_resident_headers(resident["id"]),
        "device": device,
        "device_id": device["id"],
    }


def seed_residents_with_devices(
    api: ApiClient,
    positions: Sequence[Tuple[int, int]] = STANDARD_POSITIONS,
    *,
    prefix: str = "R",
    alert_radius_m: int = 0,
    retention_window_days: int = 30,
    notification_budget_per_day: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """One resident with one camera at each grid point, in the order given.

    Each account gets its own display name and its own unique email address, so
    no two owners ever share an identity.
    """
    households: List[Dict[str, Any]] = []
    for index, (x, y) in enumerate(positions, start=1):
        name = f"{prefix}{index}"
        households.append(
            seed_resident_with_device(
                api,
                display_name=name,
                email=f"{name.lower()}@example.test",
                x=x,
                y=y,
                alert_radius_m=alert_radius_m,
                retention_window_days=retention_window_days,
                notification_budget_per_day=notification_budget_per_day,
                label=f"{name} camera",
            )
        )
    return households


# ═══ Tier 2: canvass areas and video requests ═════════════════════════════

def create_area(
    api: ApiClient, agency_id: str, officer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Draw a canvass area, which lands in draft."""
    return get_success_data(
        api.create_request_area(
            f.request_area_payload(agency_id, **overrides), make_officer_headers(officer_id)
        )
    )


def lock_area(api: ApiClient, area_id: str, officer_id: str) -> Dict[str, Any]:
    """Lock a draft area, freezing its roster and computing its device floor."""
    return get_success_data(
        api.lock_request_area(area_id, make_officer_headers(officer_id))
    )


def seed_locked_area(
    api: ApiClient, agency_id: str, officer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Draw an area and lock it, returning the locked row."""
    area = create_area(api, agency_id, officer_id, **overrides)
    return lock_area(api, area["id"], officer_id)


def create_video_request(
    api: ApiClient,
    area: Dict[str, Any],
    officer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a draft request against a locked area, quoting the version observed."""
    return get_success_data(
        api.create_video_request(
            f.video_request_payload(area["id"], area["version"], **overrides),
            make_officer_headers(officer_id),
        )
    )


def log_justification(
    api: ApiClient, request_id: str, officer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Log the legal justification, which may flag the request for audit."""
    return get_success_data(
        api.log_justification(
            request_id, f.justification_payload(**overrides), make_officer_headers(officer_id)
        )
    )


def submit_request(api: ApiClient, request_id: str, officer_id: str) -> Dict[str, Any]:
    """Submit a justified request, dispatching one solicitation per roster camera."""
    return get_success_data(
        api.submit_video_request(request_id, make_officer_headers(officer_id))
    )


def withdraw_request(
    api: ApiClient, request_id: str, headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    """Withdraw a request, cancelling every unanswered solicitation."""
    return get_success_data(
        api.withdraw_video_request(request_id, f.withdraw_payload(**overrides), headers)
    )


def review_audit(
    api: ApiClient, request_id: str, auditor_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Record the compliance audit of a flagged request."""
    return get_success_data(
        api.review_audit(
            request_id, f.audit_review_payload(**overrides), make_officer_headers(auditor_id)
        )
    )


def escalate_audit(
    api: ApiClient, request_id: str, auditor_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Escalate a flagged request, which is what puts later clips on legal hold."""
    return review_audit(
        api, request_id, auditor_id, decision=AUDIT_DECISION_ESCALATE, **overrides
    )


def seed_justified_request(
    api: ApiClient,
    agency_id: str,
    officer_id: str,
    *,
    area: Optional[Dict[str, Any]] = None,
    case_number: str = "CASE-9001",
    justification_text: Optional[str] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A locked area plus a draft request whose justification has been logged."""
    if area is None:
        area = seed_locked_area(api, agency_id, officer_id, **(area_overrides or {}))
    request = create_video_request(api, area, officer_id, case_number=case_number)
    justify_kwargs: Dict[str, Any] = {}
    if justification_text is not None:
        justify_kwargs["justification_text"] = justification_text
    request = log_justification(api, request["id"], officer_id, **justify_kwargs)
    return {"area": area, "request": request, "request_id": request["id"]}


def seed_submitted_request(
    api: ApiClient,
    agency_id: str,
    officer_id: str,
    *,
    area: Optional[Dict[str, Any]] = None,
    case_number: str = "CASE-9001",
    justification_text: Optional[str] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A request carried all the way to soliciting, with its solicitations read back."""
    seeded = seed_justified_request(
        api,
        agency_id,
        officer_id,
        area=area,
        case_number=case_number,
        justification_text=justification_text,
        area_overrides=area_overrides,
    )
    submitted = submit_request(api, seeded["request_id"], officer_id)
    seeded["request"] = submitted
    seeded["submit_response"] = submitted
    seeded["solicitations"] = list_solicitations(api, video_request_id=submitted["id"])
    return seeded


def seed_standard_canvass(
    api: ApiClient,
    *,
    clock: str = SCENARIO_CLOCK,
    positions: Sequence[Tuple[int, int]] = STANDARD_POSITIONS,
    duty_role: str = DUTY_ROLE_REQUESTER,
    agency_overrides: Optional[Dict[str, Any]] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
    case_number: str = "CASE-9001",
    justification_text: Optional[str] = None,
    submit: bool = True,
    min_device_threshold: int = 3,
) -> Dict[str, Any]:
    """The scenario most tests need, built in one call.

    Pins the clock, onboards one agency with a device floor of three, enrols one
    officer, seeds one resident with one camera at each grid point, then draws a
    500 m area at the origin over the standard six-hour footage window, locks it,
    opens a request, logs its justification and — unless asked not to — submits
    it. Returns every row, the header sets and the dispatched solicitations
    ordered by dispatch rank.
    """
    set_clock(api, clock)
    agency_kwargs: Dict[str, Any] = {"min_device_threshold": min_device_threshold}
    agency_kwargs.update(agency_overrides or {})
    world = seed_agency_with_officer(api, duty_role=duty_role, **agency_kwargs)
    world["clock"] = clock
    world["households"] = seed_residents_with_devices(api, positions)
    world["residents"] = [h["resident"] for h in world["households"]]
    world["devices"] = [h["device"] for h in world["households"]]
    world["resident_headers"] = [h["headers"] for h in world["households"]]

    if submit:
        seeded = seed_submitted_request(
            api,
            world["agency_id"],
            world["officer_id"],
            case_number=case_number,
            justification_text=justification_text,
            area_overrides=area_overrides,
        )
    else:
        seeded = seed_justified_request(
            api,
            world["agency_id"],
            world["officer_id"],
            case_number=case_number,
            justification_text=justification_text,
            area_overrides=area_overrides,
        )
    world.update(seeded)
    return world


# ═══ Tier 3: answering solicitations ══════════════════════════════════════

def list_solicitations(
    api: ApiClient,
    headers: Optional[Dict[str, str]] = None,
    *,
    limit: int = 100,
    **filters: Any,
) -> List[Dict[str, Any]]:
    """Read solicitations, which the submit-time dispatch is the only source of."""
    response = api.list_solicitations(
        headers or PLATFORM_ADMIN_HEADERS, f.page(limit=limit, offset=0, **filters)
    )
    rows, _meta = validate_paginated(response)
    return rows


def solicitation_for_device(
    api: ApiClient, request_id: str, device_id: str
) -> Dict[str, Any]:
    """The one solicitation this request aimed at this camera."""
    rows = list_solicitations(api, video_request_id=request_id, device_id=device_id)
    assert rows, f"No solicitation found for request {request_id} and device {device_id}"
    return rows[0]


def share_footage(
    api: ApiClient, solicitation_id: str, resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Share footage in answer to a solicitation and return the clip created."""
    return get_success_data(
        api.share_footage(
            solicitation_id, f.share_payload(**overrides), make_resident_headers(resident_id)
        ),
        201,
    )


def decline_solicitation(
    api: ApiClient, solicitation_id: str, resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Decline a solicitation, which is a recorded answer rather than silence."""
    return get_success_data(
        api.decline_solicitation(
            solicitation_id, f.decline_payload(**overrides), make_resident_headers(resident_id)
        )
    )


def purge_clip(
    api: ApiClient,
    clip_id: str,
    headers: Dict[str, str],
    purge_reason: str = PURGE_OWNER_REVOCATION,
) -> Dict[str, Any]:
    """Delete a shared clip."""
    return get_success_data(api.purge_clip(clip_id, f.purge_payload(purge_reason), headers))


def run_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the retention sweep at the current logical-clock instant."""
    return get_success_data(api.run_retention_sweep(PLATFORM_ADMIN_HEADERS))


# ═══ Tier 4: the community feed ═══════════════════════════════════════════

def create_post(api: ApiClient, resident_id: str, **overrides: Any) -> Dict[str, Any]:
    """Publish a neighbourhood post, which is scored and fanned out on the spot."""
    return get_success_data(
        api.create_post(
            f.post_payload(resident_id, **overrides), make_resident_headers(resident_id)
        ),
        201,
    )


def flag_post(
    api: ApiClient, post_id: str, flagger_resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Flag a published post as one resident."""
    return get_success_data(
        api.flag_post(
            post_id, f.flag_payload(**overrides), make_resident_headers(flagger_resident_id)
        )
    )


def flag_until_flagged(
    api: ApiClient, post_id: str, flagger_resident_ids: Sequence[str]
) -> Dict[str, Any]:
    """Flag a post once per resident given, and return the post after the last flag."""
    post: Dict[str, Any] = {}
    for resident_id in flagger_resident_ids:
        post = flag_post(api, post_id, resident_id)
    return post


def revise_post(
    api: ApiClient, post_id: str, author_resident_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Rewrite a post that a moderator sent back, which re-scores it."""
    return get_success_data(
        api.revise_post(
            post_id, f.revise_payload(**overrides), make_resident_headers(author_resident_id)
        ),
        200,
    )


def open_case(
    api: ApiClient,
    post: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a moderation case, quoting the post version the opener observed."""
    return get_success_data(
        api.open_moderation_case(
            f.moderation_case_payload(post["id"], post["version"], **overrides),
            headers or MODERATOR_HEADERS,
        ),
        201,
    )


def decide_case(
    api: ApiClient,
    case_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Decide a moderation case, by default as the moderator who did not open it."""
    return get_success_data(
        api.decide_moderation_case(
            case_id, f.decide_case_payload(**overrides), headers or MODERATOR_SECOND_HEADERS
        )
    )


def seed_flagged_post(
    api: ApiClient,
    author_resident_id: str,
    flagger_resident_ids: Sequence[str],
    **post_overrides: Any,
) -> Dict[str, Any]:
    """A published post carried to flagged by two distinct residents' flags."""
    post = create_post(api, author_resident_id, **post_overrides)
    flagged = flag_until_flagged(api, post["id"], flagger_resident_ids)
    return {"post": flagged or post, "post_id": post["id"]}


def seed_post_under_review(
    api: ApiClient,
    author_resident_id: str,
    flagger_resident_ids: Sequence[str],
    *,
    opener_headers: Optional[Dict[str, str]] = None,
    **post_overrides: Any,
) -> Dict[str, Any]:
    """A flagged post with an open moderation case, ready to be decided."""
    seeded = seed_flagged_post(
        api, author_resident_id, flagger_resident_ids, **post_overrides
    )
    case = open_case(api, seeded["post"], opener_headers)
    seeded["case"] = case
    seeded["case_id"] = case["id"]
    seeded["post"] = read_post(api, seeded["post_id"])
    return seeded


# ═══ Tier 5: transparency reports ═════════════════════════════════════════

def compile_report(
    api: ApiClient, agency: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Compile a report over a reporting window, quoting the agency version seen."""
    return get_success_data(
        api.compile_report(
            f.report_payload(agency["id"], agency["version"], **overrides),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )


def certify_report(
    api: ApiClient,
    report_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Certify a provisional report as a platform user who did not compile it."""
    return get_success_data(
        api.certify_report(
            report_id, f.certify_payload(**overrides), headers or PLATFORM_ADMIN_SECOND_HEADERS
        )
    )


# ═══ Tier 6: read-through helpers ═════════════════════════════════════════

def read_agency(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_agency(agency_id, PLATFORM_ADMIN_HEADERS))


def read_officer(api: ApiClient, officer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_officer(officer_id, PLATFORM_ADMIN_HEADERS))


def read_resident(api: ApiClient, resident_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_resident(resident_id, PLATFORM_ADMIN_HEADERS))


def read_device(api: ApiClient, device_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_device(device_id, PLATFORM_ADMIN_HEADERS))


def read_area(api: ApiClient, area_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_request_area(area_id, PLATFORM_ADMIN_HEADERS))


def read_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_video_request(request_id, PLATFORM_ADMIN_HEADERS))


def read_solicitation(api: ApiClient, solicitation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_solicitation(solicitation_id, PLATFORM_ADMIN_HEADERS))


def read_clip(api: ApiClient, clip_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shared_clip(clip_id, PLATFORM_ADMIN_HEADERS))


def read_post(api: ApiClient, post_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_post(post_id, PLATFORM_ADMIN_HEADERS))


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_moderation_case(case_id, PLATFORM_ADMIN_HEADERS))


def read_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_report(report_id, PLATFORM_ADMIN_HEADERS))


def list_rows(api: ApiClient, method_name: str, *, limit: int = 100, **filters: Any):
    """Read any collection through its client method and return the rows."""
    method = getattr(api, method_name)
    response = method(PLATFORM_ADMIN_HEADERS, f.page(limit=limit, offset=0, **filters))
    rows, _meta = validate_paginated(response)
    return rows


def list_dispatches(
    api: ApiClient, resident_id: str, *, limit: int = 100, **filters: Any
) -> List[Dict[str, Any]]:
    """Read a resident's notification dispatches, oldest first."""
    response = api.list_notification_dispatches(
        resident_id, PLATFORM_ADMIN_HEADERS, f.page(limit=limit, offset=0, **filters)
    )
    rows, _meta = validate_paginated(response)
    return rows


def list_data_control_actions(
    api: ApiClient, resident_id: str, *, limit: int = 100, **filters: Any
) -> List[Dict[str, Any]]:
    """Read a resident's data-control receipts, oldest first."""
    response = api.list_data_control_actions(
        resident_id, PLATFORM_ADMIN_HEADERS, f.page(limit=limit, offset=0, **filters)
    )
    rows, _meta = validate_paginated(response)
    return rows


def list_cases_for_post(api: ApiClient, post_id: str) -> List[Dict[str, Any]]:
    """Every moderation case raised on one post, oldest first."""
    return list_rows(api, "list_moderation_cases", resident_post_id=post_id)


def list_clips_for_device(api: ApiClient, device_id: str) -> List[Dict[str, Any]]:
    """Every clip shared from one camera."""
    return list_rows(api, "list_shared_clips", device_id=device_id)
