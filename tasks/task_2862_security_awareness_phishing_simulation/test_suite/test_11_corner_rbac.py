"""Role and ownership boundaries: what each identity may and may not do.

Every test in this module translates exactly one non-stub instance of the
`rbac` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_IN_PROGRESS,
    ASSIGNMENT_OVERDUE,
    CAMPAIGN_APPROVED,
    CAMPAIGN_DRAFT,
    CAMPAIGN_IN_REVIEW,
    CAMPAIGN_RUNNING,
    CAMPAIGN_SCHEDULED,
    DELIVERY_DELIVERED,
    DELIVERY_QUEUED,
    NOTICE_EXPIRED,
    NOTICE_SENT,
    POSTURE_NONE,
    TEMPLATE_DRAFT,
    TIER_1,
    TIER_2,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_delivery,
    assert_instant_equals,
    assert_notice,
    ids_of,
)
from test_helpers.factories import (
    assignment_payload,
    campaign_payload,
    consequence_payload,
    incident_payload,
)
from test_helpers.fixtures import (
    approved_campaign,
    approved_template,
    assign_module,
    create_campaign,
    create_published_module,
    create_template,
    delivery_for,
    list_notices_for,
    read_assignment,
    read_employee,
    register_employee,
    register_manager,
    reset_clock,
    run_sweep,
    scheduled_campaign,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    APPROVER,
    APPROVER_1_ID,
    AUTHOR,
    AUTHOR_1_ID,
    AUTHOR_2,
    make_headers,
    make_learner_headers,
    make_manager_headers,
)


def test_a_legitimate_learner_still_cannot_drive_someone_elses_assignment(api):
    """The Learner 403 is about identity, not about the role name.

    PRD §2.1: "When `X-User-Role` is `Learner`, `X-User-ID` is likewise the `id` of
    the acting `Employee`, and ownership checks compare it to the `employee_id` of
    the assignment being started, submitted or retaken."

    PRD §2.1: "A `Learner` acting on an assignment that is not theirs is refused
    with `ERR_NOT_ASSIGNMENT_OWNER` (HTTP 403)."

    Design: Corner/rbac/learner_cannot_drive_another_employees_assignment_returns_403
    """
    reset_clock(api)
    owner = register_employee(
        api, email="own.a@corp.example", full_name="Ann Owner",
        department="HR", role_code="IC", hire_date="2019-01-01",
    )
    bystander = register_employee(
        api, email="own.b@corp.example", full_name="Ben Bystander",
        department="HR", role_code="IC", hire_date="2019-02-02",
    )
    module = create_published_module(
        api, code="OWN-ANN", title="Ownership Probe Module", module_type="ANNUAL")
    assignment = assign_module(api, owner, module, assignment_reason="ANNUAL")

    intruder = make_learner_headers(bystander["id"])
    validate_error(
        api.start_assignment(assignment["id"], intruder),
        ApiErrorId.NOT_ASSIGNMENT_OWNER.value,
        expected_status=403,
    )
    validate_error(
        api.submit_assignment(assignment["id"], {"score_pct": 100}, intruder),
        ApiErrorId.NOT_ASSIGNMENT_OWNER.value,
        expected_status=403,
    )
    assert_assignment(read_assignment(api, assignment["id"]),
                      state=ASSIGNMENT_ASSIGNED, attempt_count=0)

    started = validate_success(
        api.start_assignment(assignment["id"], make_learner_headers(owner["id"])))
    assert_assignment(started, state=ASSIGNMENT_IN_PROGRESS, attempt_count=0)

    # A ProgramAdmin cannot stand in for the learner: the start endpoint's
    # authorized-role list holds `Learner` alone.
    validate_error(
        api.start_assignment(assignment["id"], ADMIN),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )


def test_manager_authority_follows_the_direct_report_edge_only(api):
    """A manager of nobody is refused on both manager-facing writes.

    PRD §2.1: "A `Manager` who is neither the assignment employee's `manager_id`
    (when granting an extension) nor the notice's `manager_id` (when
    acknowledging) is refused with `ERR_NOT_DIRECT_REPORT_MANAGER` (HTTP 403)."

    PRD §3.5: "It adds `extension_days` to `granted_extension_days` and recomputes
    both `effective_due_at` and `next_reminder_due_at` from the new value. It resets
    `escalation_level` to 0. Every escalation notice of this assignment still in
    `SENT` becomes `EXPIRED`."

    Design: Corner/rbac/manager_cannot_extend_a_non_report_assignment_returns_403
    """
    reset_clock(api)
    owning_manager = register_manager(
        api, email="m1.scope@corp.example", full_name="Mel One",
        department="IT", hire_date="2010-01-01",
    )
    stranger_manager = register_manager(
        api, email="m2.scope@corp.example", full_name="Moe Two",
        department="IT", hire_date="2010-02-02",
    )
    report = register_employee(
        api, email="r1.scope@corp.example", full_name="Rita Report",
        department="IT", role_code="IT_ADMIN", hire_date="2020-03-03",
        manager_id=owning_manager["id"],
    )
    module = create_published_module(
        api, code="SCOPE-REM", title="Scope Probe Remedial",
        module_type="REMEDIAL")
    assignment = assign_module(api, report, module, assignment_reason="REMEDIAL")

    set_clock(api, "2026-08-09T00:00:00Z")
    run_sweep(api)
    notices = list_notices_for(api, assignment["id"], state=NOTICE_SENT)
    assert len(notices) == 1
    notice = notices[0]
    assert notice["manager_id"] == owning_manager["id"]

    stranger = make_manager_headers(stranger_manager["id"])
    validate_error(
        api.extend_assignment(assignment["id"], {"extension_days": 5}, stranger),
        ApiErrorId.NOT_DIRECT_REPORT_MANAGER.value,
        expected_status=403,
    )
    validate_error(
        api.acknowledge_notice(
            notice["id"], {"action_plan_note": "Not my report."}, stranger),
        ApiErrorId.NOT_DIRECT_REPORT_MANAGER.value,
        expected_status=403,
    )
    untouched = validate_success(api.get_notice(notice["id"], ADMIN))
    assert_notice(untouched, state=NOTICE_SENT, level=1)
    assert not untouched["action_plan_note"]
    assert_assignment(read_assignment(api, assignment["id"]),
                      state=ASSIGNMENT_OVERDUE, escalation_level=1)

    extended = validate_success(
        api.extend_assignment(assignment["id"], {"extension_days": 5},
                              make_manager_headers(owning_manager["id"])))
    assert_assignment(extended, granted_extension_days=5, escalation_level=0)
    assert_instant_equals(extended["effective_due_at"], "2026-08-13T00:00:00Z",
                          "effective_due_at")
    assert_notice(validate_success(api.get_notice(notice["id"], ADMIN)),
                  state=NOTICE_EXPIRED, level=1)


def test_peer_authors_cannot_touch_each_others_campaigns(api):
    """author_user_id is captured at creation and enforced afterwards.

    PRD §2.1: "A `CampaignAuthor` whose `X-User-ID` is not the campaign's
    `author_user_id`, on submit-for-review, on scheduling, or on cancellation, is
    refused with `ERR_NOT_CAMPAIGN_AUTHOR` (HTTP 403)."

    PRD §2.1: "a campaign's `author_user_id` is the `X-User-ID` of the
    `CampaignAuthor` who created it"

    Design: Corner/rbac/campaign_author_cannot_schedule_another_authors_campaign_returns_403
    """
    reset_clock(api)
    employee = register_employee(
        api, email="peer.target@corp.example", full_name="Perry Target",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2018-06-06",
    )
    ctx = approved_campaign(
        api, name="Peer Ownership Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
        template_overrides={
            "name": "Peer Probe Template",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    campaign_id = ctx["campaign"]["id"]
    version = ctx["campaign"]["version"]
    assert ctx["campaign"]["author_user_id"] == AUTHOR_1_ID

    validate_error(
        api.schedule_campaign(
            campaign_id,
            {"scheduled_send_at": "2026-08-05T09:00:00Z",
             "expected_campaign_version": version},
            AUTHOR_2,
        ),
        ApiErrorId.NOT_CAMPAIGN_AUTHOR.value,
        expected_status=403,
    )
    validate_error(
        api.cancel_campaign(campaign_id, AUTHOR_2),
        ApiErrorId.NOT_CAMPAIGN_AUTHOR.value,
        expected_status=403,
    )
    held = validate_success(api.get_campaign(campaign_id, ADMIN))
    assert held["state"] == CAMPAIGN_APPROVED
    assert held["version"] == version

    scheduled = validate_success(
        api.schedule_campaign(
            campaign_id,
            {"scheduled_send_at": "2026-08-05T09:00:00Z",
             "expected_campaign_version": version},
            AUTHOR,
        )
    )
    assert scheduled["state"] == CAMPAIGN_SCHEDULED
    assert scheduled["author_user_id"] == AUTHOR_1_ID
    assert_delivery(delivery_for(api, campaign_id, employee["id"]),
                    state=DELIVERY_QUEUED)


def test_segregation_of_duties_is_keyed_on_the_acting_user_not_the_role(api):
    """One human wearing both hats is refused on approve and on reject alike.

    PRD §2.1: "A `CampaignApprover` may never approve or reject a campaign whose
    `author_user_id` equals their own `X-User-ID`; the attempt is refused with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 422)."

    PRD §2.1: "and `reviewer_user_id` is the `X-User-ID` of the `CampaignApprover`
    who most recently approved or rejected it"

    Design: Corner/rbac/campaign_author_cannot_approve_their_own_campaign_returns_422
    """
    reset_clock(api)
    template = approved_template(
        api, name="SOD Probe Template", pretext_category="PACKAGE_DELIVERY",
        difficulty_tier=TIER_2, theme_tags=["CURIOSITY", "URGENCY"],
        credential_capture_enabled=False,
    )
    campaign = create_campaign(
        api, template["id"], AUTHOR, name="Self Approval Wave",
        difficulty_tier=TIER_2,
    )
    in_review = validate_success(
        api.submit_campaign_for_review(campaign["id"], AUTHOR))
    assert in_review["state"] == CAMPAIGN_IN_REVIEW

    self_approver = make_headers("CampaignApprover", AUTHOR_1_ID)
    validate_error(
        api.approve_campaign(campaign["id"], self_approver),
        ApiErrorId.SEGREGATION_OF_DUTIES_VIOLATION.value,
        expected_status=422,
    )
    validate_error(
        api.reject_campaign(
            campaign["id"], {"rejection_reason": "Self rejection attempt."},
            self_approver),
        ApiErrorId.SEGREGATION_OF_DUTIES_VIOLATION.value,
        expected_status=422,
    )
    stalled = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert stalled["state"] == CAMPAIGN_IN_REVIEW
    assert stalled["reviewer_user_id"] is None

    approved = validate_success(api.approve_campaign(campaign["id"], APPROVER))
    assert approved["state"] == CAMPAIGN_APPROVED
    assert approved["reviewer_user_id"] == APPROVER_1_ID


def test_the_approval_chain_has_no_shortcut_from_draft(api):
    """Approve, schedule and launch each need the rung below them.

    PRD §3.7: "Requesting any campaign transition the lifecycle does not declare —
    launching from `APPROVED`, closing from `SCHEDULED`, cancelling something
    already `CLOSED` — is refused with `ERR_CAMPAIGN_STATE_INVALID`."

    PRD §3.7: "Submitting a campaign for review is reserved to its own author and is
    legal from two states: `DRAFT → IN_REVIEW` for a first submission and `REJECTED →
    IN_REVIEW` for a resubmission after feedback."

    Design: Corner/rbac/campaign_approval_cannot_skip_the_review_step_returns_409
    """
    reset_clock(api)
    template = approved_template(
        api, name="Chain Probe Template", pretext_category="INVOICE_APPROVAL",
        difficulty_tier=TIER_2, theme_tags=["AUTHORITY"],
        credential_capture_enabled=False,
    )
    campaign = create_campaign(
        api, template["id"], AUTHOR, name="Chain Order Wave",
        difficulty_tier=TIER_1,
    )
    baseline_version = campaign["version"]
    assert campaign["state"] == CAMPAIGN_DRAFT

    validate_error(
        api.approve_campaign(campaign["id"], APPROVER),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )
    validate_error(
        api.schedule_campaign(
            campaign["id"],
            {"scheduled_send_at": "2026-08-05T09:00:00Z",
             "expected_campaign_version": baseline_version},
            AUTHOR,
        ),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )
    validate_error(
        api.launch_campaign(campaign["id"], ADMIN),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )

    still_draft = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert still_draft["state"] == CAMPAIGN_DRAFT
    assert still_draft["version"] == baseline_version
    assert still_draft["scheduled_send_at"] is None
    assert still_draft["reviewer_user_id"] is None


def test_template_creation_is_shared_while_campaign_creation_is_not(api):
    """The ProgramAdmin gets no hierarchical override on the campaign endpoints.

    PRD §4: "| POST | `/awareness/phishing-templates` | Create a pretext template in
    draft; prohibited themes are recorded, not rejected. | `ProgramAdmin`,
    `CampaignAuthor` |"

    PRD §4: "| POST | `/awareness/campaigns` | Create a campaign in draft owned by
    the acting author. | `CampaignAuthor` |"

    Design: Corner/rbac/program_admin_cannot_create_campaigns_but_shares_template_creation
    """
    reset_clock(api)
    by_admin = create_template(
        api, ADMIN, name="Admin Authored Template",
        pretext_category="IT_PASSWORD_RESET", difficulty_tier=TIER_1,
        theme_tags=["URGENCY"], credential_capture_enabled=False,
    )
    by_author = create_template(
        api, AUTHOR, name="Author Authored Template",
        pretext_category="IT_PASSWORD_RESET", difficulty_tier=TIER_1,
        theme_tags=["URGENCY"], credential_capture_enabled=False,
    )
    assert by_admin["review_state"] == TEMPLATE_DRAFT
    assert by_author["review_state"] == TEMPLATE_DRAFT

    validate_error(
        api.create_campaign(
            campaign_payload(by_admin["id"], name="Admin Attempted Wave",
                             difficulty_tier=TIER_1),
            ADMIN,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    # Approval for use is CampaignApprover-exclusive, even for the admin who
    # is allowed to block the very same template.
    validate_error(
        api.approve_template_for_use(by_admin["id"], ADMIN),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )

    assert validate_success(
        api.get_template(by_admin["id"], ADMIN))["review_state"] == TEMPLATE_DRAFT
    assert validate_success(api.list_campaigns({}, ADMIN)) == []


def test_the_analyst_reads_widely_but_writes_only_incidents(api):
    """Sweeps, assignments and consequences are all closed to SecurityAnalyst.

    PRD §4: "| POST | `/awareness/compliance-sweeps` | Run one compliance sweep at
    the current logical clock across all four steps. | `ProgramAdmin` |"

    PRD §4: "| POST | `/awareness/incidents` | Record a real security incident. |
    `SecurityAnalyst` |"

    Design: Corner/rbac/security_analyst_cannot_write_program_state_returns_403
    """
    reset_clock(api)
    employee = register_employee(
        api, email="sara.analyst@corp.example", full_name="Sara Subject",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2018-08-08",
    )
    module = create_published_module(
        api, code="AN-ANNUAL", title="Analyst Probe Module", module_type="ANNUAL")

    validate_error(
        api.run_compliance_sweep(ANALYST),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api.create_assignment(
            assignment_payload(employee["id"], module["id"], employee["version"],
                               assignment_reason="ANNUAL"),
            ANALYST,
        ),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api.apply_access_consequence(
            employee["id"], consequence_payload(employee["version"]), ANALYST),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )

    incident = validate_success(
        api.create_incident(
            incident_payload(
                incident_type="BEC", severity="MEDIUM", department="FINANCE",
                occurred_at="2026-07-30T09:00:00Z",
                summary="Analyst-recorded vendor fraud attempt.",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    listed = validate_success(api.list_employees({"department": "FINANCE"}, ANALYST))
    assert ids_of(listed) == [employee["id"]]
    assert ids_of(validate_success(api.list_incidents({}, ANALYST))) == [incident["id"]]

    # None of the refused writes touched the employee row.
    after = read_employee(api, employee["id"])
    assert after["version"] == employee["version"]
    assert after["access_posture"] == POSTURE_NONE
    assert validate_success(
        api.list_assignments({"employee_id": employee["id"]}, ADMIN)) == []


def test_execution_of_a_campaign_is_split_away_from_its_approval(api):
    """Neither the approver nor the author may launch or close the send.

    PRD §4: "| POST | `/awareness/campaigns/{id}/launch` | Deliver the reserved
    cohort once the logical clock has reached the scheduled instant. |
    `ProgramAdmin` |"

    PRD §3.8: "a delivery whose employee is still `ACTIVE` moves `QUEUED →
    DELIVERED`, stamping `delivered_at` with the clock, setting
    `quiet_period_until` to `delivered_at` advanced by 5 days, and setting
    `outcome_class` to `PENDING`"

    Design: Corner/rbac/campaign_approver_cannot_launch_or_close_a_campaign_returns_403
    """
    reset_clock(api)
    employee = register_employee(
        api, email="exec.split@corp.example", full_name="Eli Exec",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2017-05-05",
    )
    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-05T09:00:00Z",
        name="Exec Split Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
        template_overrides={
            "name": "Exec Split Template",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    campaign_id = ctx["campaign"]["id"]
    set_clock(api, "2026-08-05T09:00:00Z")

    validate_error(
        api.launch_campaign(campaign_id, APPROVER),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    validate_error(
        api.launch_campaign(campaign_id, AUTHOR),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    assert validate_success(
        api.get_campaign(campaign_id, ADMIN))["state"] == CAMPAIGN_SCHEDULED

    launched = validate_success(api.launch_campaign(campaign_id, ADMIN))
    assert launched["state"] == CAMPAIGN_RUNNING
    delivery = delivery_for(api, campaign_id, employee["id"])
    assert_delivery(delivery, state=DELIVERY_DELIVERED)
    assert_instant_equals(delivery["delivered_at"], "2026-08-05T09:00:00Z",
                          "delivered_at")
    assert_instant_equals(delivery["quiet_period_until"], "2026-08-10T09:00:00Z",
                          "quiet_period_until")

    validate_error(
        api.close_campaign(
            campaign_id, {"debrief_note": "Approver attempting to close."},
            APPROVER),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        expected_status=403,
    )
    assert validate_success(
        api.get_campaign(campaign_id, ADMIN))["state"] == CAMPAIGN_RUNNING
