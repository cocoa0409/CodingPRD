"""Programming-template lineage and the change-control workflow.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_AGENCY_VOTING_SUSPENDED,
    ERR_COVERAGE_CLASS_INSUFFICIENT,
    ERR_REVISION_LIMIT_EXCEEDED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_TEMPLATE_NOT_PUBLISHED,
    ERR_TEMPLATE_SLOT_CAPACITY_EXCEEDED,
    ERR_TEMPLATE_VERSION_STALE,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pagination_meta,
)
from test_helpers.constants import (
    ACTION_ASSIGN,
    ACTION_SUSPEND,
    AGENCY_TYPE_EMS,
    AGENCY_TYPE_FIRE,
    AGENCY_TYPE_LAW,
    AGENCY_TYPE_REGIONAL_AUTHORITY,
    BACKUP_GENERATOR,
    BILLING_CURRENT,
    BILLING_SUSPENDED_FROM_VOTING,
    COVERAGE_UNRATED,
    CR_APPROVED,
    CR_CHANGES_REQUESTED,
    CR_DEPLOYED,
    CR_REJECTED,
    CR_SUBMITTED,
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_REQUEST_CHANGES,
    ENC_CLEAR,
    FEE_BASIS_SNAPSHOT,
    MODEL_MOBILE,
    MODEL_PORTABLE,
    PROVISION_ASSIGNED,
    PROVISION_INVENTORY,
    PROVISION_SUSPENDED,
    ROLE_FLEET_ENGINEER,
    STANDARD_NG_LMR,
    STANDARD_P25_PHASE1,
    STANDARD_P25_PHASE2,
    TEMPLATE_DRAFT,
    TEMPLATE_PUBLISHED,
    TEMPLATE_RETIRED,
    TG_ACTION_DECOMMISSION,
    TG_KIND_ANNOUNCEMENT,
    TG_KIND_DISPATCH,
    TG_KIND_TACTICAL,
)
from test_helpers.test_users import (
    CHANGE_CONTROL_BOARD,
    CHANGE_CONTROL_BOARD_2,
    CHANGE_CONTROL_BOARD_ID,
    CHANGE_CONTROL_BOARD_ID_2,
    FLEET_ENGINEER,
    FLEET_ENGINEER_ID,
    make_agency_radio_manager_headers,
    make_operator_headers,
)


def test_template_deployed_unit_count_recomputes_on_each_assignment(
    api: ApiClient, clock_at_start: str
):
    """`deployed_unit_count` is a query over current rows, so it moves with every
    assignment rather than being patched once.

    PRD 3.4: "Three derived figures are then refreshed: the owning agency's
    `billable_subscriber_count`, the owning agency's `governance_vote_weight` by
    the board-weighting rule of Section 3.9, and the template's
    `deployed_unit_count`."

    Design: Corner/entities/template_deployed_unit_count_recomputes_on_each_assignment
    """
    agency = fx.register_agency(
        api,
        name="Computed Counter Agency",
        agency_code="CMP01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="CMP-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    assert_fields(template, deployed_unit_count=0, status=TEMPLATE_PUBLISHED)
    assert_fields(fx.read_agency(api, agency["id"]), billable_subscriber_count=0)

    first = fx.add_unit(
        api, agency["id"], serial_number="CMP0001", radio_id=22001, model=MODEL_PORTABLE
    )
    second = fx.add_unit(
        api, agency["id"], serial_number="CMP0002", radio_id=22002, model=MODEL_PORTABLE
    )
    # Adding radios to inventory alone changes nothing derived.
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=0)

    fx.lifecycle(api, first["id"], agency["id"], ACTION_ASSIGN, template["id"])
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=1)
    assert_fields(
        fx.read_agency(api, agency["id"]),
        billable_subscriber_count=1,
        governance_vote_weight=1,
    )

    fx.lifecycle(api, second["id"], agency["id"], ACTION_ASSIGN, template["id"])
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=2)
    assert_fields(
        fx.read_agency(api, agency["id"]),
        billable_subscriber_count=2,
        governance_vote_weight=1,
    )


def test_template_revision_supersedes_parent_and_retires_it(
    api: ApiClient, clock_at_start: str
):
    """Revising authors a new row and retires the parent; the lineage is walkable
    forward through the `supersedes_template_id` filter.

    PRD 3.3: "The new row's `template_version` is the parent's
    `template_version` plus one, its `supersedes_template_id` is the parent's
    `id`, its `status` is `DRAFT`, and its `created_by_user_id` is the acting
    engineer. The parent is not left alone: its `status` becomes `RETIRED` and
    its `version` is incremented by one."

    Design: Corner/endpoints/template_revision_supersedes_parent_and_retires_it
    """
    parent = fx.published_template(
        api,
        template_name="REV-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        talkgroup_slot_count=6,
    )
    parent_version = parent["version"]

    child = validate_success(
        api.create_template_revision(
            parent["id"],
            f.template_revision_payload(
                parent_version,
                template_name="REV-BASE-2",
                target_standard=STANDARD_NG_LMR,
                talkgroup_slot_count=6,
                encryption_required=True,
            ),
            FLEET_ENGINEER,
        ),
        201,
    )
    assert_common_fields(child, expected_version=1)
    assert_fields(
        child,
        template_name="REV-BASE-2",
        template_version=2,
        supersedes_template_id=parent["id"],
        status=TEMPLATE_DRAFT,
        target_standard=STANDARD_NG_LMR,
        talkgroup_slot_count=6,
        encryption_required=True,
        created_by_user_id=FLEET_ENGINEER_ID,
        deployed_unit_count=0,
    )

    assert_fields(
        fx.read_template(api, parent["id"]),
        status=TEMPLATE_RETIRED,
        version=parent_version + 1,
    )

    rows, meta = validate_paginated(
        api.list_templates(FLEET_ENGINEER, params={"supersedes_template_id": parent["id"]})
    )
    assert_pagination_meta(meta, total_count=1)
    assert [r["id"] for r in rows] == [child["id"]], (
        "the lineage filter must walk forward to exactly the revision"
    )


def test_occ_template_revision_rejects_stale_expected_version(
    api: ApiClient, clock_at_start: str
):
    """Publishing bumps the parent's row version, so a revision pinned to the
    pre-publication value is refused and nothing branches.

    PRD 2.6: "Creating a revision of a programming template requires
    `expected_template_version`, carrying the `version` of the parent
    `RadioTemplate` as the client last observed it. A mismatch against that
    template's current `version` is rejected with `ERR_STALE_VERSION` and HTTP
    412, forcing the author to re-read the lineage before branching."

    Design: Corner/cross_cutting_complexity_layers/occ_template_revision_rejects_stale_expected_version
    """
    draft = fx.create_template(
        api,
        template_name="OCT-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    v1 = draft["version"]
    published = fx.publish_template(api, draft["id"])
    v2 = published["version"]
    assert v2 == v1 + 1, "publication increments the template's version by one"

    body_args = dict(
        template_name="OCT-BASE-2",
        target_standard=STANDARD_NG_LMR,
        talkgroup_slot_count=4,
    )

    stale = api.create_template_revision(
        draft["id"], f.template_revision_payload(v1, **body_args), FLEET_ENGINEER
    )
    validate_error(stale, ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(
        api.list_templates(FLEET_ENGINEER, params={"supersedes_template_id": draft["id"]})
    )
    assert_pagination_meta(meta, total_count=0)
    assert_fields(
        fx.read_template(api, draft["id"]), status=TEMPLATE_PUBLISHED, version=v2
    )

    child = validate_success(
        api.create_template_revision(
            draft["id"], f.template_revision_payload(v2, **body_args), FLEET_ENGINEER
        ),
        201,
    )
    assert_fields(
        child,
        template_version=2,
        supersedes_template_id=draft["id"],
        status=TEMPLATE_DRAFT,
    )
    assert_fields(
        fx.read_template(api, draft["id"]), status=TEMPLATE_RETIRED, version=v2 + 1
    )


def test_version_pinning_freezes_template_lineage_and_fleet_size_at_approval(
    api: ApiClient, clock_at_start: str
):
    """Approval freezes three separate numbers at once, and the later deployment
    reconciles against exactly those frozen values.

    PRD 3.3: "On approval three snapshots are taken and frozen:
    `pinned_template_version` captures the template's lineage number
    `template_version`; `pinned_template_record_version` captures the template
    row's mutation counter `version`; and `target_unit_count` captures the number
    of that target agency's subscriber units whose `provision_status` is
    `ASSIGNED` or `SUSPENDED` at that instant."

    Design: Corner/cross_cutting_complexity_layers/version_pinning_freezes_template_lineage_and_fleet_size_at_approval
    """
    agency = fx.register_agency(
        api,
        name="Version Pinning Agency",
        agency_code="VPN01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=180,
    )
    template = fx.published_template(
        api,
        template_name="VPN-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    first = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="VPN0001",
        radio_id=43001,
        model=MODEL_PORTABLE,
    )
    second = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="VPN0002",
        radio_id=43002,
        model=MODEL_MOBILE,
    )

    request = fx.create_change_request(
        api, template["id"], agency["id"], title="Pinning check"
    )
    fx.submit_change_request(api, request["id"])

    # Read the live row version immediately before the ruling: that is the value
    # the approval must freeze.
    record_version_pre_approval = fx.read_template(api, template["id"])["version"]

    approved = validate_success(
        api.review_change_request(
            request["id"],
            f.review_decision_payload(DECISION_APPROVE, "Pinned at approval"),
            CHANGE_CONTROL_BOARD,
        ),
        200,
    )
    assert_fields(
        approved,
        status=CR_APPROVED,
        reviewed_by_user_id=CHANGE_CONTROL_BOARD_ID,
        pinned_template_version=1,
        pinned_template_record_version=record_version_pre_approval,
        target_unit_count=2,
        revision_count=0,
    )

    deployed = validate_success(
        api.deploy_change_request(request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(deployed, status=CR_DEPLOYED, deployed_unit_count=2)

    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=2)
    for unit in (first, second):
        assert_fields(fx.read_unit(api, unit["id"]), template_id=template["id"])


def test_conditional_flag_encryption_required_activates_the_coverage_gate_on_deploy(
    api: ApiClient, clock_at_start: str
):
    """The coverage gate is switched on solely by the template flag: the same
    fleet on the same UNRATED site deploys or is refused depending on it.

    PRD 3.3: "First, when the template's `encryption_required` flag is true,
    every site that serves as the `home_site_id` of a talkgroup owned by the
    target agency whose `status` is `ACTIVE` or `LOCKED` must have a
    `coverage_class` of `MISSION_CRITICAL` or `GENERAL`; if any such home site is
    `MARGINAL` or `UNRATED`, deployment is rejected with
    `ERR_COVERAGE_CLASS_INSUFFICIENT`."

    Design: Corner/cross_cutting_complexity_layers/conditional_flag_encryption_required_activates_the_coverage_gate_on_deploy
    """
    agency = fx.register_agency(
        api,
        name="Flag Gate Agency",
        agency_code="FLG01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    site = fx.register_site(
        api,
        site_code="FLG-1",
        name="Flag One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
    )
    fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="FLG-A",
        tg_decimal_id=2501,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )

    # The site has never been drive-tested, so it is UNRATED — the state the
    # gate refuses when, and only when, the flag is set.
    assert_fields(
        fx.read_site(api, site["id"]), total_test_points=0, coverage_class=COVERAGE_UNRATED
    )
    assert_fields(fx.read_agency(api, agency["id"]), billing_status=BILLING_CURRENT)

    clear_template = fx.published_template(
        api,
        template_name="FLG-CLEAR-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
        encryption_required=False,
    )
    crypto_template = fx.published_template(
        api,
        template_name="FLG-CRYPTO-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
        encryption_required=True,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        clear_template["id"],
        serial_number="FLG0001",
        radio_id=44001,
        model=MODEL_PORTABLE,
    )

    clear_request = fx.approved_change_request(
        api, clear_template["id"], agency["id"], title="Clear fleet deploy"
    )
    crypto_request = fx.approved_change_request(
        api, crypto_template["id"], agency["id"], title="Crypto fleet deploy"
    )

    # Flag absent: the gate never runs and the deployment completes.
    permitted = validate_success(
        api.deploy_change_request(clear_request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(permitted, status=CR_DEPLOYED, deployed_unit_count=1)

    # Flag present: the identical fleet on the identical site is refused.
    refused = api.deploy_change_request(crypto_request["id"], FLEET_ENGINEER)
    validate_error(refused, ERR_COVERAGE_CLASS_INSUFFICIENT, 422)

    still_approved = validate_success(
        api.get_change_request(crypto_request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(still_approved, status=CR_APPROVED, deployed_unit_count=0)

    assert_fields(fx.read_unit(api, unit["id"]), template_id=clear_template["id"])
    assert_fields(fx.read_template(api, crypto_template["id"]), deployed_unit_count=0)


def test_change_request_deploy_bubbles_to_deployed_when_counts_reconcile(
    api: ApiClient, clock_at_start: str
):
    """A suspended radio counts as a failure rather than blocking the fan-out, so
    the request still bubbles past `DEPLOYING` inside the same call.

    PRD 3.3: "Because the fan-out covers exactly the set that was pinned at
    approval, the sum of `deployed_unit_count` and `failed_unit_count` always
    ends up equal to `target_unit_count`, which is the condition for the
    automatic `DEPLOYING` → `DEPLOYED` transition evaluated at the end of the
    same request; when it holds, `deployed_at` is stamped with now."

    Design: Corner/state_machines/change_request_deploy_bubbles_to_deployed_when_counts_reconcile
    """
    agency = fx.register_agency(
        api,
        name="Bubble Up Agency",
        agency_code="BUB01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="BUB-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    reachable = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="BUB0001",
        radio_id=25001,
        model=MODEL_PORTABLE,
    )
    suspended = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="BUB0002",
        radio_id=25002,
        model=MODEL_MOBILE,
    )
    suspended = fx.lifecycle(api, suspended["id"], agency["id"], ACTION_SUSPEND)
    assert_fields(suspended, provision_status=PROVISION_SUSPENDED)

    request = fx.create_change_request(
        api, template["id"], agency["id"], title="Bubble-up fleet refresh"
    )
    fx.submit_change_request(api, request["id"])
    record_version = fx.read_template(api, template["id"])["version"]

    approved = validate_success(
        api.review_change_request(
            request["id"],
            f.review_decision_payload(DECISION_APPROVE, "Approved for fleet deployment"),
            CHANGE_CONTROL_BOARD,
        ),
        200,
    )
    # ASSIGNED and SUSPENDED both enter the pinned set.
    assert_fields(
        approved,
        status=CR_APPROVED,
        target_unit_count=2,
        pinned_template_version=1,
        pinned_template_record_version=record_version,
    )

    fx.set_clock(api, "2026-08-02T00:00:00Z")
    deployed = validate_success(
        api.deploy_change_request(request["id"], FLEET_ENGINEER), 200
    )

    assert_fields(
        deployed, status=CR_DEPLOYED, deployed_unit_count=1, failed_unit_count=1
    )
    assert deployed["status"] != "DEPLOYING", (
        "a caller never observes a request sitting in DEPLOYING"
    )
    assert_instant_equals(
        deployed["deployment_started_at"], "2026-08-02T00:00:00Z", "deployment_started_at"
    )
    assert_instant_equals(deployed["deployed_at"], "2026-08-02T00:00:00Z", "deployed_at")

    # The skipped radio keeps the template it already carried.
    assert_fields(fx.read_unit(api, reachable["id"]), template_id=template["id"])
    assert_fields(fx.read_unit(api, suspended["id"]), template_id=template["id"])


def test_error_template_version_stale_on_deploy_after_revision(
    api: ApiClient, clock_at_start: str
):
    """Revising the pinned template between approval and deployment is the
    documented serialization point, and the deploy is refused.

    PRD 3.3: "Second, the live template's `version` must still equal the
    `pinned_template_record_version` captured at approval; if the template has
    been published, revised, or otherwise mutated since, deployment is rejected
    with `ERR_TEMPLATE_VERSION_STALE`."

    Design: Corner/errors/error_template_version_stale_on_deploy_after_revision
    """
    agency = fx.register_agency(
        api,
        name="Stale Template Agency",
        agency_code="STL01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="STL-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="STL0001",
        radio_id=40001,
        model=MODEL_PORTABLE,
    )

    request = fx.approved_change_request(
        api, template["id"], agency["id"], title="Deploy before revision"
    )
    pinned = request["pinned_template_record_version"]
    version_after_approval = fx.read_template(api, template["id"])["version"]
    assert pinned == version_after_approval, (
        "approval pins the template row version as it stood at the ruling"
    )

    child = fx.revise_template(
        api,
        template["id"],
        template_name="STL-BASE-2",
        target_standard=STANDARD_NG_LMR,
        talkgroup_slot_count=4,
    )
    assert_fields(
        fx.read_template(api, template["id"]), version=version_after_approval + 1
    )

    refused = api.deploy_change_request(request["id"], FLEET_ENGINEER)
    validate_error(refused, ERR_TEMPLATE_VERSION_STALE, 409)

    unchanged = validate_success(
        api.get_change_request(request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(unchanged, status=CR_APPROVED, deployed_unit_count=0)
    assert_nulls(unchanged, "deployment_started_at")

    assert_fields(fx.read_template(api, template["id"]), status=TEMPLATE_RETIRED)
    assert_fields(fx.read_template(api, child["id"]), template_version=2)


def test_error_template_not_published_on_assign(api: ApiClient, clock_at_start: str):
    """A `DRAFT` codeplug cannot be programmed into a radio; publication is what
    makes the identical assignment legal.

    PRD 3.3: "Publication moves a template's `status` from `DRAFT` to
    `PUBLISHED` and increments its `version` by one; a template may be assigned
    to radios and approved for deployment only once it is `PUBLISHED`, and any
    other lifecycle position is rejected with `ERR_TEMPLATE_NOT_PUBLISHED`."

    Design: Corner/errors/error_template_not_published_on_assign
    """
    agency = fx.register_agency(
        api,
        name="Draft Template Agency",
        agency_code="DFT01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    template = fx.create_template(
        api,
        template_name="DFT-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    unit = fx.add_unit(
        api,
        agency["id"],
        serial_number="DFT0001",
        radio_id=39001,
        model=MODEL_PORTABLE,
    )

    refused = api.unit_lifecycle(
        unit["id"],
        f.lifecycle_payload(ACTION_ASSIGN, template["id"]),
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(refused, ERR_TEMPLATE_NOT_PUBLISHED, 409)
    assert_fields(fx.read_unit(api, unit["id"]), provision_status=PROVISION_INVENTORY)
    assert_fields(fx.read_template(api, template["id"]), status=TEMPLATE_DRAFT)

    published = fx.publish_template(api, template["id"])
    assert_fields(published, status=TEMPLATE_PUBLISHED)

    accepted = fx.lifecycle(api, unit["id"], agency["id"], ACTION_ASSIGN, template["id"])
    assert_fields(accepted, provision_status=PROVISION_ASSIGNED)
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=1)


def test_rbac_fleet_engineer_cannot_rule_on_its_own_change_request(
    api: ApiClient, clock_at_start: str
):
    """Ruling is the board's act alone; the authoring role is refused on the
    identical body that the board is allowed to send.

    PRD 2.1: "`FleetEngineer` authors programming templates and change requests
    and drives fleet deployment, but never rules on a change request."

    PRD 3.3: "Review is the board's act, and only a `ChangeControlBoard` member
    may perform it."

    Design: Corner/rbac/rbac_fleet_engineer_cannot_rule_on_its_own_change_request
    """
    agency = fx.register_agency(
        api,
        name="RBAC Board Agency",
        agency_code="RBC01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="RBC-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    request = fx.create_change_request(
        api, template["id"], agency["id"], title="RBAC ruling check"
    )
    fx.submit_change_request(api, request["id"])

    body = f.review_decision_payload(DECISION_APPROVE)

    refused = api.review_change_request(request["id"], body, FLEET_ENGINEER)
    validate_error(refused, ERR_UNAUTHORIZED, 403)

    after_refusal = validate_success(
        api.get_change_request(request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(after_refusal, status=CR_SUBMITTED)
    assert_nulls(after_refusal, "reviewed_by_user_id")

    accepted = validate_success(
        api.review_change_request(request["id"], body, CHANGE_CONTROL_BOARD), 200
    )
    assert_fields(
        accepted,
        status=CR_APPROVED,
        reviewed_by_user_id=CHANGE_CONTROL_BOARD_ID,
        pinned_template_version=1,
    )


def test_rbac_segregation_of_duties_blocks_self_review_of_change_request(
    api: ApiClient, clock_at_start: str
):
    """Holding the board role is not enough: the reviewer's identity is compared
    against the identity that submitted the request.

    PRD 2.9: "A `ProgrammingChangeRequest` stores the `X-User-ID` of the
    `FleetEngineer` who most recently submitted it as `submitted_by_user_id`;
    when a `ChangeControlBoard` member rules on that request, the acting
    `X-User-ID` must differ from `submitted_by_user_id`, and an identical value
    is rejected with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    Design: Corner/rbac/rbac_segregation_of_duties_blocks_self_review_of_change_request
    """
    agency = fx.register_agency(
        api,
        name="SoD Board Agency",
        agency_code="SOD01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="SOD-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    request = fx.create_change_request(
        api, template["id"], agency["id"], title="SoD self review"
    )
    # Submitted in the FleetEngineer capacity but under the board member's own
    # opaque operator id, so submitted_by_user_id is "ccb-1".
    submitted = fx.submit_change_request(
        api,
        request["id"],
        make_operator_headers(CHANGE_CONTROL_BOARD_ID, ROLE_FLEET_ENGINEER),
    )
    assert_fields(
        submitted, submitted_by_user_id=CHANGE_CONTROL_BOARD_ID, status=CR_SUBMITTED
    )

    self_review = api.review_change_request(
        request["id"], f.review_decision_payload(DECISION_APPROVE), CHANGE_CONTROL_BOARD
    )
    validate_error(self_review, ERR_SEGREGATION_OF_DUTIES, 403)

    after_refusal = validate_success(
        api.get_change_request(request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(after_refusal, status=CR_SUBMITTED)
    assert_nulls(after_refusal, "reviewed_by_user_id")

    peer_review = validate_success(
        api.review_change_request(
            request["id"],
            f.review_decision_payload(
                DECISION_REJECT, "Reviewed by a different board member"
            ),
            CHANGE_CONTROL_BOARD_2,
        ),
        200,
    )
    assert_fields(
        peer_review, status=CR_REJECTED, reviewed_by_user_id=CHANGE_CONTROL_BOARD_ID_2
    )


def test_voting_suspended_target_agency_blocks_deploy(api: ApiClient, clock_at_start: str):
    """The deployment's validity turns on the target agency's fiscal state, which
    decayed while the request sat approved.

    PRD 3.3: "Third, the target agency's `billing_status` must not be
    `SUSPENDED_FROM_VOTING`; a fiscally suspended agency cannot receive a fleet
    deployment, and the attempt is rejected with `ERR_AGENCY_VOTING_SUSPENDED`."

    PRD 3.9: "Otherwise, when `payment_due_at` is not null and the current
    instant is at or after `payment_due_at` plus a further 60-day
    voting-suspension grace, the target status is `SUSPENDED_FROM_VOTING`."

    Design: Corner/validations/voting_suspended_target_agency_blocks_deploy
    """
    agency = fx.register_agency(
        api,
        name="Voting Suspended Agency",
        agency_code="VOT01",
        agency_type=AGENCY_TYPE_EMS,
        fee_basis=FEE_BASIS_SNAPSHOT,
        recorder_retention_days=90,
    )
    template = fx.published_template(
        api,
        template_name="VOT-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=4,
    )
    unit = fx.assigned_unit(
        api,
        agency["id"],
        template["id"],
        serial_number="VOT0001",
        radio_id=34001,
        model=MODEL_PORTABLE,
    )

    # Assessed for July with payment_due_at 2026-08-31; nothing is paid.
    fx.assess_fees(api, agency["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    # 2026-11-01 is past 2026-08-31 plus the 60-day voting-suspension grace, and
    # a token payment re-runs the billing-status recompute.
    fx.set_clock(api, "2026-11-01T00:00:00Z")
    suspended_agency = fx.pay(api, agency["id"], 1)
    assert_fields(
        suspended_agency,
        fee_balance_cents=4199,
        billing_status=BILLING_SUSPENDED_FROM_VOTING,
        governance_vote_weight=0,
        voting_eligible=False,
    )

    # Approved after every template write, so only the fiscal gate can fail.
    request = fx.approved_change_request(
        api, template["id"], agency["id"], title="Refresh suspended agency fleet"
    )
    assert_fields(request, status=CR_APPROVED)

    refused = api.deploy_change_request(request["id"], FLEET_ENGINEER)
    validate_error(refused, ERR_AGENCY_VOTING_SUSPENDED, 403)

    unchanged = validate_success(
        api.get_change_request(request["id"], FLEET_ENGINEER), 200
    )
    assert_fields(
        unchanged, status=CR_APPROVED, deployed_unit_count=0, failed_unit_count=0
    )
    assert_nulls(unchanged, "deployment_started_at", "deployed_at")
    assert_fields(
        fx.read_unit(api, unit["id"]),
        provision_status=PROVISION_ASSIGNED,
        template_id=template["id"],
    )


def test_template_slot_capacity_exceeded_on_assign(api: ApiClient, clock_at_start: str):
    """The capacity rule counts the agency's live talkgroups, not the radios the
    codeplug has been loaded onto.

    PRD 3.4: "Specifically, the number of talkgroups whose `owner_agency_id` is
    the unit's `agency_id` and whose `status` is `ACTIVE` or `LOCKED` must not
    exceed the template's `talkgroup_slot_count`; if the agency runs more live
    talkgroups than the codeplug has slots, the assignment is rejected with
    `ERR_TEMPLATE_SLOT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/template_slot_capacity_exceeded_on_assign
    """
    agency = fx.register_agency(
        api,
        name="Slot Capacity Agency",
        agency_code="SLT01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    site = fx.register_site(
        api,
        site_code="SLT-1",
        name="Slot One",
        channel_capacity=6,
        backup_power_type=BACKUP_GENERATOR,
    )
    for alias, decimal_id, kind in (
        ("SLT-A", 1401, TG_KIND_DISPATCH),
        ("SLT-B", 1402, TG_KIND_TACTICAL),
        ("SLT-C", 1403, TG_KIND_ANNOUNCEMENT),
    ):
        talkgroup = fx.create_talkgroup(
            api,
            agency["id"],
            site["id"],
            alias=alias,
            tg_decimal_id=decimal_id,
            kind=kind,
            encryption_mode=ENC_CLEAR,
        )
        if alias == "SLT-C":
            surplus = talkgroup

    template = fx.published_template(
        api,
        template_name="SLT-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=2,
    )
    unit = fx.add_unit(
        api, agency["id"], serial_number="SLT0001", radio_id=31001, model=MODEL_PORTABLE
    )

    # Three live talkgroups against two codeplug slots.
    refused = api.unit_lifecycle(
        unit["id"],
        f.lifecycle_payload(ACTION_ASSIGN, template["id"]),
        make_agency_radio_manager_headers(agency["id"]),
    )
    validate_error(refused, ERR_TEMPLATE_SLOT_CAPACITY_EXCEEDED, 422)

    after_refusal = fx.read_unit(api, unit["id"])
    assert_fields(after_refusal, provision_status=PROVISION_INVENTORY, billable=False)
    assert_nulls(after_refusal, "template_id")
    assert_fields(fx.read_template(api, template["id"]), deployed_unit_count=0)
    assert_fields(fx.read_agency(api, agency["id"]), billable_subscriber_count=0)

    # Retiring one talkgroup drops the live count to exactly the slot count.
    fx.talkgroup_action(api, surplus["id"], agency["id"], TG_ACTION_DECOMMISSION)
    accepted = fx.lifecycle(api, unit["id"], agency["id"], ACTION_ASSIGN, template["id"])
    assert_fields(
        accepted, provision_status=PROVISION_ASSIGNED, template_id=template["id"]
    )


def test_change_request_revision_cycle_increments_only_on_loop_closing_edge(
    api: ApiClient, clock_at_start: str
):
    """The first submission is not a revision: `revision_count` moves only when
    the request re-enters `SUBMITTED` from `CHANGES_REQUESTED`.

    PRD 3.3: "From `CHANGES_REQUESTED`, submitting again closes the revision
    loop: it moves back to `SUBMITTED`, increases `revision_count` by one, and
    rewrites `submitted_by_user_id` to the acting engineer."

    PRD 3.3: "Note that the increment fires only on the `CHANGES_REQUESTED` →
    `SUBMITTED` edge, never on the `DRAFT` → `SUBMITTED` edge."

    Design: Difficulty/non_linear_state_machine/change_request_revision_cycle_terminates_at_max_revisions
    """
    agency = fx.register_agency(
        api,
        name="Foxtrot Transit Authority",
        agency_code="RAUF2",
        agency_type=AGENCY_TYPE_REGIONAL_AUTHORITY,
        recorder_retention_days=365,
    )
    template = fx.published_template(
        api,
        template_name="FOX-CODEPLUG-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=12,
    )
    request = fx.create_change_request(
        api, template["id"], agency["id"], title="Foxtrot codeplug refresh"
    )
    assert_fields(request, revision_count=0)

    # DRAFT -> SUBMITTED: the straight edge, no increment.
    first = fx.submit_change_request(api, request["id"])
    assert_fields(
        first,
        status=CR_SUBMITTED,
        revision_count=0,
        submitted_by_user_id=FLEET_ENGINEER_ID,
    )

    # SUBMITTED -> CHANGES_REQUESTED: a ruling, still no increment.
    bounced = fx.review_change_request(
        api, request["id"], DECISION_REQUEST_CHANGES, "Fix scan list order"
    )
    assert_fields(
        bounced,
        status=CR_CHANGES_REQUESTED,
        revision_count=0,
        review_comment="Fix scan list order",
        reviewed_by_user_id=CHANGE_CONTROL_BOARD_ID,
    )

    # CHANGES_REQUESTED -> SUBMITTED: the loop-closing edge does increment.
    second = fx.submit_change_request(api, request["id"])
    assert_fields(second, status=CR_SUBMITTED, revision_count=1)
    assert second["version"] > bounced["version"], (
        "every successful submission increments the request's version by one"
    )


def test_change_request_revision_cycle_terminates_at_max_revisions(
    api: ApiClient, clock_at_start: str
):
    """The revision loop is bounded at two traversals; the third re-entry is
    refused and the request stays where the board left it.

    PRD 3.3: "That loop is bounded — a request that has already been revised
    twice may not be re-submitted a third time, so a re-submission from
    `CHANGES_REQUESTED` is permitted only while `revision_count` is less than 2,
    and an attempt beyond that is rejected with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/change_request_revision_cycle_terminates_at_max_revisions
    """
    agency = fx.register_agency(
        api,
        name="Foxtrot Transit Authority",
        agency_code="RAUF2",
        agency_type=AGENCY_TYPE_REGIONAL_AUTHORITY,
        recorder_retention_days=365,
    )
    template = fx.published_template(
        api,
        template_name="FOX-CODEPLUG-1",
        target_standard=STANDARD_P25_PHASE2,
        talkgroup_slot_count=12,
    )
    request = fx.create_change_request(
        api, template["id"], agency["id"], title="Foxtrot codeplug refresh"
    )

    submitted = fx.submit_change_request(api, request["id"])
    assert_fields(submitted, status=CR_SUBMITTED, revision_count=0)

    fx.review_change_request(
        api, request["id"], DECISION_REQUEST_CHANGES, "Fix scan list order"
    )
    revised_once = fx.submit_change_request(api, request["id"])
    assert_fields(revised_once, status=CR_SUBMITTED, revision_count=1)

    fx.review_change_request(
        api, request["id"], DECISION_REQUEST_CHANGES, "Emergency talkgroup still missing"
    )
    revised_twice = fx.submit_change_request(api, request["id"])
    assert_fields(revised_twice, status=CR_SUBMITTED, revision_count=2)

    third_bounce = fx.review_change_request(
        api, request["id"], DECISION_REQUEST_CHANGES, "Third pass required"
    )
    assert_fields(
        third_bounce,
        status=CR_CHANGES_REQUESTED,
        review_comment="Third pass required",
        revision_count=2,
    )

    # revision_count == 2 is no longer strictly less than 2.
    refused = api.submit_change_request(request["id"], FLEET_ENGINEER)
    validate_error(refused, ERR_REVISION_LIMIT_EXCEEDED, 422)

    final = validate_success(api.get_change_request(request["id"], FLEET_ENGINEER), 200)
    assert_fields(
        final,
        status=CR_CHANGES_REQUESTED,
        revision_count=2,
        reviewed_by_user_id=CHANGE_CONTROL_BOARD_ID,
        submitted_by_user_id=FLEET_ENGINEER_ID,
    )
