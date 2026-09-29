"""Role admission, identity binding and the three separated duties.

The portal fences every operation three times over, and the three fences fire at
different points in the order of refusal. The first is the endpoint's own role
list: a caller holding a role the operation does not admit is turned away before
anything about the resource, its owner or its state is looked at. The second is
identity binding: a caller who *does* hold an admitted, entity-backed role must
also own the row being written. The third is separation of duties, enforced on
the acting caller identifier rather than on the role name, so that both parties
to a refused pair hold exactly the same role.

Each test here pins the refusal to its own error identifier and then proves the
refused row is untouched, because a 403 that still mutated something would be no
protection at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MODERATOR_HEADERS,
    MODERATOR_ID,
    MODERATOR_SECOND_HEADERS,
    MODERATOR_SECOND_ID,
    PLATFORM_ADMIN_HEADERS,
    PLATFORM_ADMIN_ID,
    PLATFORM_ADMIN_SECOND_HEADERS,
    PLATFORM_ADMIN_SECOND_ID,
    make_officer_headers,
    make_resident_headers,
)

# The reporting window every transparency report in this file is compiled over.
REPORT_PERIOD_START = "2026-08-01T00:00:00Z"
REPORT_PERIOD_END = "2026-08-12T00:00:00Z"


def _total_count(response) -> int:
    """The number of rows a collection reports as matching the filters."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_every_role_outside_an_operations_role_list_is_refused_as_unauthorized(
    api: ApiClient,
) -> None:
    """Four callers reach for an operation their role does not admit and each is refused 403.

    PRD: "When the headers are well formed but the role is not one the target operation admits, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "An `AgencyAdmin` may never define a canvass area, log a justification, submit a request, or audit one — those are sworn-officer duties."

    Design: Corner/rbac/non_officer_roles_calling_officer_and_platform_operations_returns_unauthorized
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    agency_id = world["agency_id"]
    agency_version = world["agency"]["version"]
    resident = fixtures.register_resident(
        api, display_name="R1", email="r1@example.test", home_x_m=0, home_y_m=10, alert_radius_m=0
    )

    # Drawing a canvass area is an Officer-only duty: the agency's own
    # administrator is the closest neighbour to an officer and is still out.
    validate_error(
        api.create_request_area(
            f.request_area_payload(agency_id, area_label="Attempt by admin"),
            world["agency_headers"],
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )
    # A moderator has no standing on the request workflow at all.
    validate_error(
        api.create_request_area(
            f.request_area_payload(agency_id, area_label="Attempt by moderator"),
            MODERATOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )
    # Registering an agency applicant belongs to the platform operator.
    validate_error(
        api.create_agency(
            f.agency_payload(
                name="Resident's Own Police Force", jurisdiction_code="RB-999"
            ),
            make_resident_headers(resident["id"]),
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )
    # So does compiling the transparency report the agency is measured by.
    validate_error(
        api.compile_report(
            f.report_payload(
                agency_id,
                agency_version,
                period_start_utc=REPORT_PERIOD_START,
                period_end_utc=REPORT_PERIOD_END,
            ),
            world["officer_headers"],
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )

    # None of the four refusals wrote a row.
    assert (
        _total_count(
            api.list_request_areas(
                PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, agency_id=agency_id)
            )
        )
        == 0
    ), "A refused canvass-area creation must not leave a canvass area behind"
    assert (
        _total_count(
            api.list_reports(
                PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, agency_id=agency_id)
            )
        )
        == 0
    ), "A refused compilation must not leave a transparency report behind"

    # The refused compilation never repointed latest_report_id either.
    agency = fixtures.read_agency(api, agency_id)
    assertions.assert_version_unchanged(agency, agency_version)
    assertions.assert_subset(
        agency, {"status": k.AGENCY_STATUS_ONBOARDED, "latest_report_id": None}
    )


def test_role_gate_outranks_the_ownership_gate_for_an_agency_admin(
    api: ApiClient,
) -> None:
    """An AgencyAdmin naming its own agency is refused on the role, not on ownership.

    PRD: "The acting role is admitted by the target operation — otherwise `ERR_UNAUTHORIZED`."
    PRD: "For entity-backed roles, the acting identity owns the resource being written — otherwise `ERR_IDENTITY_MISMATCH`."

    Design: Corner/rbac/non_officer_roles_calling_officer_and_platform_operations_returns_unauthorized
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(api, min_device_threshold=3)
    agency_id = world["agency_id"]

    # The acting X-User-ID *is* the agency named in the body, so the ownership
    # check at position 6 would have passed; the role check at position 2 fires
    # first and decides the response.
    body = validate_error(
        api.create_request_area(
            f.request_area_payload(agency_id, area_label="Attempt by admin"),
            world["agency_headers"],
        ),
        ApiErrorId.UNAUTHORIZED.value,
        403,
    )
    assert body["error_id"] != ApiErrorId.IDENTITY_MISMATCH.value, (
        "The role gate is evaluated before the ownership gate, so an AgencyAdmin "
        "that owns the agency in the body is still refused as unauthorized"
    )
    assert (
        _total_count(
            api.list_request_areas(
                PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, agency_id=agency_id)
            )
        )
        == 0
    ), "A refused canvass-area creation must not leave a canvass area behind"


def test_resident_may_exercise_its_own_alert_device_and_post_operations(
    api: ApiClient,
) -> None:
    """The Resident role really can reconfigure alerts, register and patch a camera and post.

    PRD: "Reconfiguring alert preferences later is a partial update over the same three fields — `alert_radius_m`, `notification_budget_per_day` and `notification_mute_enabled` — where any field omitted from the payload is left untouched."
    PRD: "A new camera is created with `status` `ACTIVE` — the three postures are `ACTIVE`, `OFFLINE` and `DECOMMISSIONED` — and with `solicitations_received_count` and `pending_solicitation_count` both at 0."

    Design: Corner/rbac/resident_exclusive_account_device_and_post_operations_are_allowed
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    resident = fixtures.register_resident(
        api,
        display_name="Rosa Lind",
        email="rosa@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=400,
    )
    resident_id = resident["id"]
    headers = make_resident_headers(resident_id)
    assert resident["version"] == 1, "A freshly registered resident is at version 1"

    # 1. The resident rewrites its own alert configuration.
    settings = validate_success(
        api.update_alert_settings(
            resident_id,
            f.alert_settings_payload(
                alert_radius_m=250, notification_budget_per_day=4, notification_mute_enabled=False
            ),
            headers,
        ),
        200,
    )
    assertions.assert_subset(
        settings,
        {
            "alert_radius_m": 250,
            "notification_budget_per_day": 4,
            "notification_mute_enabled": False,
            # Nothing has been dispatched, so the re-derived tier is the base one.
            "fatigue_state": k.FATIGUE_NORMAL,
            "notifications_sent_today": 0,
        },
    )
    assertions.assert_version_advanced(settings, 1)

    # 2. The resident registers a camera it owns.
    device = validate_success(
        api.create_device(
            f.device_payload(
                resident_id,
                label="Front Door",
                grid_x_m=0,
                grid_y_m=0,
                retention_window_days=30,
                auto_decline_requests=False,
            ),
            headers,
        ),
        201,
    )
    assertions.assert_mutable_common_fields(device, version=1)
    assertions.assert_created_equals_updated(device)
    assertions.assert_subset(
        device,
        {
            "owner_resident_id": resident_id,
            "label": "Front Door",
            "grid_x_m": 0,
            "grid_y_m": 0,
            "status": k.DEVICE_STATUS_ACTIVE,
            "retention_window_days": 30,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        },
    )
    assertions.assert_zero_counters(
        device, "solicitations_received_count", "pending_solicitation_count"
    )

    # 3. The resident patches that same camera, and the omitted fields stay put.
    patched = validate_success(
        api.update_device(
            device["id"],
            f.device_patch_payload(label="Front Porch", retention_window_days=14),
            headers,
        ),
        200,
    )
    assertions.assert_subset(
        patched,
        {
            "label": "Front Porch",
            "retention_window_days": 14,
            "status": k.DEVICE_STATUS_ACTIVE,
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        },
    )
    assertions.assert_version_advanced(patched, 1)

    # 4. The resident publishes a post authored by itself.
    post = validate_success(
        api.create_post(
            f.post_payload(
                resident_id,
                body="The streetlight at the corner has been out for three nights.",
                category=k.CATEGORY_SAFETY_REPORT,
                post_x_m=0,
                post_y_m=0,
            ),
            headers,
        ),
        201,
    )
    assertions.assert_mutable_common_fields(post, version=1)
    assertions.assert_subset(
        post,
        {
            "author_resident_id": resident_id,
            "state": k.POST_PUBLISHED,
            "auto_flag_reason": None,
            "flag_count": 0,
            "revision_count": 0,
            # The author is excluded from its own fan-out and nobody else exists.
            "alert_candidate_count": 0,
            "alert_fanout_count": 0,
            "alert_suppressed_count": 0,
        },
    )
    assertions.assert_score(post["discrimination_score"], "0.00")


def test_resident_may_exercise_its_own_account_level_data_control(api: ApiClient) -> None:
    """A resident opting its own account out of the request programme is admitted and cascades.

    PRD: "`OPT_OUT_OF_REQUESTS` is an absolute withdrawal from the video-request programme and cascades five levels."
    PRD: "Level two sets `auto_decline_requests` to true and `auto_decline_source` to `OPT_OUT` on every camera of that resident that is not `DECOMMISSIONED`."

    Design: Corner/rbac/resident_exclusive_account_device_and_post_operations_are_allowed
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    household = fixtures.seed_resident_with_device(
        api,
        display_name="Rosa Lind",
        email="rosa@example.test",
        x=0,
        y=0,
        alert_radius_m=400,
        label="Front Door",
        retention_window_days=30,
    )
    resident_id = household["resident_id"]
    device_id = household["device_id"]

    receipt = validate_success(
        api.exercise_data_control(
            resident_id,
            f.data_control_payload(
                k.ACTION_OPT_OUT, reason="I would rather not receive footage requests."
            ),
            household["headers"],
        ),
        201,
    )
    # The receipt is an append-only row: id and created_at and nothing else from
    # the common property set.
    assertions.assert_receipt_common_fields(receipt)
    assertions.assert_subset(
        receipt,
        {
            "action_type": k.ACTION_OPT_OUT,
            "affected_device_count": 1,
            "affected_solicitation_count": 0,
            "affected_clip_count": 0,
            "affected_request_count": 0,
        },
    )
    assertions.assert_instant(
        receipt["applied_at"], fixtures.SCENARIO_CLOCK, "applied_at"
    )

    resident = fixtures.read_resident(api, resident_id)
    assertions.assert_subset(
        resident,
        {"data_sharing_opt_out": True, "status": k.RESIDENT_STATUS_ACTIVE},
    )
    assertions.assert_version_advanced(resident, 1)

    device = fixtures.read_device(api, device_id)
    assertions.assert_subset(
        device,
        {
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
            "status": k.DEVICE_STATUS_ACTIVE,
        },
    )
    assertions.assert_version_advanced(device, 1)

    # The receipt is discoverable through the resident's own control history.
    receipts = fixtures.list_data_control_actions(api, resident_id)
    assertions.assert_ids_in_order(receipts, [receipt["id"]])


# ── An agency whose officers are split three ways ──────────────────────────

# The auditor's own note, so the successful review is distinguishable from the
# two refused attempts that must leave no note at all.
AUDITOR_NOTE = "Justification and case number reconciled against the dispatch log."


def _seed_audit_flagged_request(api: ApiClient) -> dict:
    """One agency, one officer of each duty role, and a request awaiting audit.

    The disc holds five eligible cameras, which is strictly more than four, so
    logging the justification carries the compliance dimension straight on to
    `AUDIT_FLAGGED`. The request is submitted by the DUAL_ROLE officer, who is
    therefore both entitled to audit in general and barred from auditing this one.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    agency = fixtures.onboarded_agency(api, min_device_threshold=3)
    agency_id = agency["id"]
    requester = fixtures.create_officer(
        api,
        agency_id,
        badge_number="B-100",
        full_name="Officer Vale",
        duty_role=k.DUTY_ROLE_REQUESTER,
    )
    auditor = fixtures.create_officer(
        api,
        agency_id,
        badge_number="B-200",
        full_name="Officer Quill",
        duty_role=k.DUTY_ROLE_AUDITOR,
    )
    dual = fixtures.create_officer(
        api,
        agency_id,
        badge_number="B-300",
        full_name="Sergeant Marsh",
        duty_role=k.DUTY_ROLE_DUAL_ROLE,
    )
    fixtures.seed_residents_with_devices(
        api, ((0, 10), (0, 20), (0, 30), (0, 40), (0, 50))
    )
    area = fixtures.seed_locked_area(api, agency_id, dual["id"])
    assert area["eligible_device_count"] == 5, (
        "The five cameras inside the 500 m disc must all make the frozen roster"
    )
    request = fixtures.create_video_request(
        api, area, dual["id"], case_number="CASE-2030"
    )
    request = fixtures.log_justification(api, request["id"], dual["id"])
    assert request["compliance_state"] == k.COMPLIANCE_AUDIT_FLAGGED, (
        "A roster of five cameras is denser than the audit trigger allows"
    )
    assert request["submitting_officer_id"] == dual["id"]
    return {
        "agency_id": agency_id,
        "area": area,
        "requester": requester,
        "auditor": auditor,
        "dual": dual,
        "request": request,
        "request_id": request["id"],
    }


def test_dual_role_officer_may_not_audit_the_request_it_submitted_itself(
    api: ApiClient,
) -> None:
    """An officer entitled to audit in general still may not audit its own submission.

    PRD: "It is only accepted while `compliance_state` is `AUDIT_FLAGGED` — otherwise `ERR_AUDIT_NOT_PENDING` — and the acting officer must belong to the same agency as the request, must hold a `duty_role` of `AUDITOR` or `DUAL_ROLE`, and must not be the request's `submitting_officer_id`."
    PRD: "The officer who audits a video request may never be the officer who submitted it, and the moderator who decides a moderation case may never be the moderator who opened it."

    Design: Corner/rbac/audit_review_by_the_submitting_officer_or_a_requester_only_officer_returns_forbidden
    """
    world = _seed_audit_flagged_request(api)
    request_version = world["request"]["version"]

    error = validate_error(
        api.review_audit(
            world["request_id"],
            f.audit_review_payload(
                decision=k.AUDIT_DECISION_CLEAR,
                audit_note="I submitted this myself and I am satisfied it is proper.",
            ),
            make_officer_headers(world["dual"]["id"]),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    # The request was audit-ready the whole time, so the state gate further down
    # the ladder is not what refused this call.
    assert error["error_id"] != ApiErrorId.AUDIT_NOT_PENDING.value, (
        "The duty split is evaluated before the audit-pending state gate"
    )

    request = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(request, request_version)
    assertions.assert_subset(
        request,
        {
            "compliance_state": k.COMPLIANCE_AUDIT_FLAGGED,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "auditor_officer_id": None,
            "audit_note": None,
        },
    )
    # A refused review is not a completed audit.
    assert fixtures.read_officer(api, world["dual"]["id"])["audits_completed_count"] == 0


def test_requester_only_officer_is_refused_the_audit_the_auditor_then_clears(
    api: ApiClient,
) -> None:
    """A REQUESTER holds the admitted role yet lacks the audit capability, while the AUDITOR clears.

    PRD: "A violation of that last condition, or an officer whose `duty_role` is `REQUESTER` attempting the review at all, is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "Both outcomes store the `audit_note`, stamp `auditor_officer_id` from the acting officer's identity, increment that officer's `audits_completed_count` by 1, advance the request's `version` by 1, and leave `lifecycle_state` entirely alone — a request may be audited while it is still soliciting."

    Design: Corner/rbac/audit_review_by_the_submitting_officer_or_a_requester_only_officer_returns_forbidden
    """
    world = _seed_audit_flagged_request(api)
    request_version = world["request"]["version"]

    error = validate_error(
        api.review_audit(
            world["request_id"],
            f.audit_review_payload(
                decision=k.AUDIT_DECISION_CLEAR,
                audit_note="Reviewed on behalf of the requesting desk.",
            ),
            make_officer_headers(world["requester"]["id"]),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    # Officer is in this route's role list, so the refusal is a duty split rather
    # than a role gate.
    assert error["error_id"] != ApiErrorId.UNAUTHORIZED.value, (
        "A REQUESTER-only officer is admitted by the route and refused on the duty split"
    )
    refused = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(refused, request_version)
    assertions.assert_subset(
        refused,
        {
            "compliance_state": k.COMPLIANCE_AUDIT_FLAGGED,
            "auditor_officer_id": None,
            "audit_note": None,
        },
    )

    # The auditor of the same agency succeeds on exactly the same request.
    reviewed = validate_success(
        api.review_audit(
            world["request_id"],
            f.audit_review_payload(
                decision=k.AUDIT_DECISION_CLEAR, audit_note=AUDITOR_NOTE
            ),
            make_officer_headers(world["auditor"]["id"]),
        ),
        200,
    )
    assertions.assert_subset(
        reviewed,
        {
            "compliance_state": k.COMPLIANCE_AUDIT_CLEARED,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "auditor_officer_id": world["auditor"]["id"],
            "audit_note": AUDITOR_NOTE,
        },
    )
    assertions.assert_version_advanced(reviewed, request_version)

    # Only the officer who actually reviewed carries the completed audit.
    assert fixtures.read_officer(api, world["auditor"]["id"])["audits_completed_count"] == 1
    assert fixtures.read_officer(api, world["requester"]["id"])["audits_completed_count"] == 0
    assert fixtures.read_officer(api, world["dual"]["id"])["audits_completed_count"] == 0


def test_moderator_may_not_decide_the_case_it_opened_while_a_second_moderator_may(
    api: ApiClient,
) -> None:
    """The duty split on a moderation case is enforced on the opaque caller identifier.

    PRD: "Crucially, **the deciding moderator may never be the moderator who opened the case**: the acting `X-User-ID` is compared against the case's `opened_by_user_id`, and a match is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "`REQUEST_REVISION` on a post whose `revision_count` is still below the ceiling of 2 sends it `UNDER_REVIEW → REVISION_REQUESTED`; the counter is incremented by the author's revision, not by this decision."

    Design: Corner/rbac/case_decided_by_its_opener_and_report_certified_by_its_compiler_return_forbidden
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    first_flagger = fixtures.register_resident(
        api, display_name="N1", email="n1@example.test", home_x_m=10, home_y_m=0, alert_radius_m=0
    )
    second_flagger = fixtures.register_resident(
        api, display_name="N2", email="n2@example.test", home_x_m=20, home_y_m=0, alert_radius_m=0
    )
    seeded = fixtures.seed_post_under_review(
        api,
        author["id"],
        [first_flagger["id"], second_flagger["id"]],
        opener_headers=MODERATOR_HEADERS,
        body="A grey van has been circling the block every evening this week.",
        category=k.CATEGORY_SUSPICIOUS_ACTIVITY,
        post_x_m=0,
        post_y_m=0,
        unverified_assertion_count=1,
    )
    case = seeded["case"]
    case_version = case["version"]
    post_version = seeded["post"]["version"]
    assert case["opened_by_user_id"] == MODERATOR_ID
    assert seeded["post"]["state"] == k.POST_UNDER_REVIEW

    error = validate_error(
        api.decide_moderation_case(
            seeded["case_id"],
            f.decide_case_payload(
                decision=k.DECISION_UPHELD_PUBLISH,
                decision_note="I opened this and I am closing it myself.",
            ),
            MODERATOR_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    # Both parties hold the Moderator role, so only the identity can be wrong.
    assert error["error_id"] != ApiErrorId.UNAUTHORIZED.value, (
        "The opener holds the admitted role; the refusal is the duty split"
    )

    refused_case = fixtures.read_case(api, seeded["case_id"])
    assertions.assert_version_unchanged(refused_case, case_version)
    assertions.assert_subset(
        refused_case, {"state": k.CASE_OPEN, "decision": k.DECISION_NONE}
    )
    refused_post = fixtures.read_post(api, seeded["post_id"])
    assertions.assert_version_unchanged(refused_post, post_version)
    assert refused_post["state"] == k.POST_UNDER_REVIEW

    # A second holder of the very same role decides it immediately afterwards.
    decided = validate_success(
        api.decide_moderation_case(
            seeded["case_id"],
            f.decide_case_payload(
                decision=k.DECISION_REQUEST_REVISION,
                decision_note="Please remove the vehicle description and re-post.",
            ),
            MODERATOR_SECOND_HEADERS,
        ),
        200,
    )
    assertions.assert_subset(
        decided,
        {
            "state": k.CASE_DECIDED,
            "decision": k.DECISION_REQUEST_REVISION,
            "decided_by_user_id": MODERATOR_SECOND_ID,
            "opened_by_user_id": MODERATOR_ID,
        },
    )
    assertions.assert_version_advanced(decided, case_version)
    assertions.assert_instant(
        decided["decided_at"], fixtures.SCENARIO_CLOCK, "decided_at"
    )

    post = fixtures.read_post(api, seeded["post_id"])
    assertions.assert_subset(
        post, {"state": k.POST_REVISION_REQUESTED, "revision_count": 0}
    )


def test_platform_admin_may_not_certify_the_report_it_compiled_while_a_second_may(
    api: ApiClient,
) -> None:
    """Certification is separated inside a single role, on the acting identifier alone.

    PRD: "**The certifying admin may not be the admin who compiled the report**: the acting `X-User-ID` is compared against `compiled_by_user_id`, and a match is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD: "It then sets `variant` to `CERTIFIED`, repoints `published_share_rate_bps` at `certified_share_rate_bps`, records the `certification_note`, stamps `certified_at` from the logical clock and `certified_by_user_id` from the acting caller, and advances the report's `version` by 1."

    Design: Corner/rbac/case_decided_by_its_opener_and_report_certified_by_its_compiler_return_forbidden
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    agency = fixtures.onboarded_agency(api, min_device_threshold=3)
    report = fixtures.compile_report(
        api,
        agency,
        period_start_utc=REPORT_PERIOD_START,
        period_end_utc=REPORT_PERIOD_END,
    )
    report_version = report["version"]
    assertions.assert_subset(
        report,
        {
            "variant": k.REPORT_PROVISIONAL,
            "compiled_by_user_id": PLATFORM_ADMIN_ID,
            "certified_by_user_id": None,
            "certified_at": None,
        },
    )

    error = validate_error(
        api.certify_report(
            report["id"],
            f.certify_payload(
                certification_note="I compiled this and I am certifying it myself."
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )
    assert error["error_id"] != ApiErrorId.UNAUTHORIZED.value, (
        "The compiler holds the admitted role; the refusal is the duty split"
    )
    refused = fixtures.read_report(api, report["id"])
    assertions.assert_version_unchanged(refused, report_version)
    assertions.assert_subset(
        refused,
        {
            "variant": k.REPORT_PROVISIONAL,
            "certified_by_user_id": None,
            "certified_at": None,
        },
    )

    # A second administrator certifies the very same report.
    certified = validate_success(
        api.certify_report(
            report["id"],
            f.certify_payload(
                certification_note="Independently reconciled by the duty administrator."
            ),
            PLATFORM_ADMIN_SECOND_HEADERS,
        ),
        200,
    )
    assertions.assert_subset(
        certified,
        {
            "variant": k.REPORT_CERTIFIED,
            "compiled_by_user_id": PLATFORM_ADMIN_ID,
            "certified_by_user_id": PLATFORM_ADMIN_SECOND_ID,
            "certification_note": "Independently reconciled by the duty administrator.",
        },
    )
    assertions.assert_version_advanced(certified, report_version)
    assertions.assert_instant(
        certified["certified_at"], fixtures.SCENARIO_CLOCK, "certified_at"
    )
    # No request was ever submitted, so both branches read zero and the published
    # figure now follows the certified branch.
    assertions.assert_bps(
        certified["certified_share_rate_bps"], 0, "certified_share_rate_bps"
    )
    assertions.assert_bps(
        certified["published_share_rate_bps"], 0, "published_share_rate_bps"
    )


def test_resident_may_not_write_another_residents_camera_alerts_or_data_controls(
    api: ApiClient,
) -> None:
    """Holding the Resident role admits the route; ownership of the row is a separate gate.

    PRD: "When an entity-backed role acts on a resource that is not its own — a resident touching another resident's camera, solicitation, clip, post or alert settings, or an officer or agency administrator acting for an agency other than the one they belong to — the rejection is `ERR_IDENTITY_MISMATCH` (HTTP 403)."
    PRD: "For entity-backed roles, the acting identity owns the resource being written — otherwise `ERR_IDENTITY_MISMATCH`."

    Design: Corner/rbac/resident_writing_to_another_residents_device_and_solicitation_returns_forbidden
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    owner = fixtures.seed_resident_with_device(
        api,
        display_name="R1",
        email="r1@example.test",
        x=0,
        y=0,
        alert_radius_m=400,
        notification_budget_per_day=5,
        label="R1 Front Door",
        retention_window_days=30,
    )
    resident_version = owner["resident"]["version"]
    device_version = owner["device"]["version"]
    stranger = fixtures.register_resident(
        api,
        display_name="R2",
        email="r2@example.test",
        home_x_m=100,
        home_y_m=0,
        alert_radius_m=0,
    )
    stranger_headers = make_resident_headers(stranger["id"])

    # Every payload below is well formed; only the acting identity is wrong.
    validate_error(
        api.update_device(
            owner["device_id"],
            f.device_patch_payload(
                retention_window_days=1, status=k.DEVICE_STATUS_DECOMMISSIONED
            ),
            stranger_headers,
        ),
        ApiErrorId.IDENTITY_MISMATCH.value,
        403,
    )
    validate_error(
        api.update_alert_settings(
            owner["resident_id"],
            f.alert_settings_payload(
                alert_radius_m=1500, notification_budget_per_day=99
            ),
            stranger_headers,
        ),
        ApiErrorId.IDENTITY_MISMATCH.value,
        403,
    )
    validate_error(
        api.exercise_data_control(
            owner["resident_id"],
            f.data_control_payload(
                action_type=k.ACTION_OPT_OUT, reason="Opting my neighbour out."
            ),
            stranger_headers,
        ),
        ApiErrorId.IDENTITY_MISMATCH.value,
        403,
    )

    device = fixtures.read_device(api, owner["device_id"])
    assertions.assert_version_unchanged(device, device_version)
    assertions.assert_subset(
        device,
        {
            "status": k.DEVICE_STATUS_ACTIVE,
            "retention_window_days": 30,
            "label": "R1 Front Door",
            "auto_decline_requests": False,
        },
    )

    resident = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_version_unchanged(resident, resident_version)
    assertions.assert_subset(
        resident,
        {
            "alert_radius_m": 400,
            "notification_budget_per_day": 5,
            "data_sharing_opt_out": False,
            "status": k.RESIDENT_STATUS_ACTIVE,
        },
    )

    # A refused data control leaves no receipt behind.
    assert (
        _total_count(
            api.list_data_control_actions(
                owner["resident_id"], owner["headers"], f.page(limit=10, offset=0)
            )
        )
        == 0
    ), "A refused data control must not be recorded as an action"
