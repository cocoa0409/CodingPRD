"""Deployment candidates: authoring, validation, approval, segregation of
duties, the version-pinned digests and the deployment job."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_approved_change_set,
    create_change_set,
    create_environment,
    create_production,
    create_sandbox,
    make_platform_admin_headers,
    setup_source_and_target,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RELEASE = TEST_USERS["release_manager_headers"]
ENV_ADMIN = TEST_USERS["environment_admin_headers"]


def _deployments(change_set_id: str) -> list:
    rows, _ = validate_paginated(api_client.list_change_set_deployments(change_set_id, ADMIN))
    return rows


# ─── Authoring a change set ───────────────────────────────────────────────────

def test_change_set_source_may_not_equal_target(api):
    """PRD §3.5: "A change set whose source environment is the same as its
    target is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP status 403,
    because promoting metadata onto itself is not a deployment."

    Design: Corner/errors/change_set_source_may_not_equal_target
    """
    env = create_environment(type="DEVELOPER")
    res = api.create_change_set(
        {"source_environment_id": env["id"], "target_environment_id": env["id"],
         "component_list": [{"component": "acme_controller", "version_tag": 1}],
         "component_dependencies": [],
         "expected_environment_version": env["version"]},
        RELEASE)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    rows, _ = validate_paginated(api.list_change_sets_of_environment(env["id"], ADMIN))
    assert rows == []


def test_existing_change_set_does_not_block_a_distinct_pair(api):
    """PRD §2.6: "opening a new change set that supersedes an earlier one is
    likewise legitimate"
    PRD §3.5: "The change set is created in `DRAFT` with an empty
    `component_digests` map, and creating it advances the target environment's
    version."

    Design: Corner/errors/change_set_source_may_not_equal_target
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(source["id"], target)
    assert change_set["status"] == "DRAFT"
    assert change_set["component_digests"] == {}
    assert change_set["source_environment_id"] != change_set["target_environment_id"]


# ─── OCC on change-set creation ───────────────────────────────────────────────

def test_change_set_creation_rejects_a_stale_target_version(api):
    """PRD §2.6: "The second is the opening of a deployment candidate:
    `POST /platform/change-sets` likewise requires a non-optional
    `expected_environment_version`, matched against the target environment's
    current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` and
    HTTP status 412."

    Design: Difficulty/optimistic_concurrency/change_set_creation_rejects_stale_target_version
    """
    source, target = setup_source_and_target()
    initial_version = target["version"]
    create_change_set(source["id"], target, expected_environment_version=initial_version)

    refreshed = validate_success(api.get_environment(target["id"], ADMIN), 200)
    assert refreshed["version"] > initial_version

    stale = api.create_change_set(
        {"source_environment_id": source["id"], "target_environment_id": target["id"],
         "component_list": [{"component": "acme_layout", "version_tag": 4}],
         "component_dependencies": [],
         "expected_environment_version": initial_version}, RELEASE)
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)
    assert validate_success(api.get_environment(target["id"], ADMIN), 200)["version"] == refreshed["version"]


def test_change_set_creation_succeeds_with_the_current_target_version(api):
    """PRD §2.6: "opening a new change set that supersedes an earlier one is
    likewise legitimate; in both cases nothing about the environment's state
    forbids the request, so the stale `expected_environment_version` the client
    supplied is the sole and complete reason for the rejection."

    Design: Difficulty/optimistic_concurrency/change_set_creation_rejects_stale_target_version
    """
    source, target = setup_source_and_target()
    create_change_set(source["id"], target)

    refreshed = validate_success(api.get_environment(target["id"], ADMIN), 200)
    second = create_change_set(source["id"], target,
                               expected_environment_version=refreshed["version"])
    assert second["status"] == "DRAFT"

    rows, _ = validate_paginated(api.list_change_sets_of_environment(target["id"], ADMIN))
    assert len(rows) == 2
    assert validate_success(api.get_change_set(second["id"], ADMIN), 200)["id"] == second["id"]


# ─── Validation of the component graph ────────────────────────────────────────

def test_component_requiring_an_absent_target_is_refused(api):
    """PRD §3.5: "First, every component named in the `requires` list of any
    dependency entry must itself appear as a component in the `component_list`;
    a missing one is refused with `ERR_MISSING_COMPONENT_DEPENDENCY` and HTTP
    status 422."

    Design: Corner/errors/component_requires_absent_target_returns_missing_dependency
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}],
        component_dependencies=[{"component": "acme_controller",
                                 "requires": ["acme_missing"], "min_version": 1}])

    res = api.validate_change_set(change_set["id"], RELEASE)
    validate_error(res, "ERR_MISSING_COMPONENT_DEPENDENCY", expected_status=422)

    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["status"] == "DRAFT"
    assert reloaded["validated_at"] is None
    assert len(reloaded["component_list"]) == 1


def test_cyclic_component_graph_is_refused(api):
    """PRD §3.5: "Second, the dependency graph must be acyclic, or the change
    set is refused with `ERR_CYCLE_DETECTED` and HTTP status 409."

    Design: Corner/errors/cyclic_component_graph_and_cyclic_callout_graph_return_cycle_detected
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(
        source["id"], target,
        component_list=[{"component": "acme_a", "version_tag": 1},
                        {"component": "acme_b", "version_tag": 1}],
        component_dependencies=[{"component": "acme_a", "requires": ["acme_b"], "min_version": 1},
                                {"component": "acme_b", "requires": ["acme_a"], "min_version": 1}])

    res = api.validate_change_set(change_set["id"], RELEASE)
    validate_error(res, "ERR_CYCLE_DETECTED", expected_status=409)
    assert validate_success(api.get_change_set(change_set["id"], ADMIN), 200)["status"] == "DRAFT"


def test_acyclic_component_graph_validates(api):
    """PRD §3.5: "Validation turns a `DRAFT` or `STALE` change set into
    `VALIDATED`."
    PRD §3.5: "On success the change set's `validated_at` is stamped."

    Design: Corner/errors/cyclic_component_graph_and_cyclic_callout_graph_return_cycle_detected
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(
        source["id"], target,
        component_list=[{"component": "acme_a", "version_tag": 1},
                        {"component": "acme_b", "version_tag": 1}],
        component_dependencies=[{"component": "acme_b", "requires": ["acme_a"], "min_version": 1}])

    validated = validate_success(api.validate_change_set(change_set["id"], RELEASE), 200)
    assert validated["status"] == "VALIDATED"
    assert validated["validated_at"] is not None


def test_empty_component_list_is_refused_and_blocks_deploy(api):
    """PRD §3.5: "Third, the change set's `component_list` must be non-empty, or
    it is refused with `ERR_EMPTY_COMPONENT_LIST` and HTTP status 422."

    Design: Corner/state_machines/change_set_terminal_failed_state_blocks_validate
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(source["id"], target, component_list=[])

    validate_error(api.validate_change_set(change_set["id"], RELEASE),
                   "ERR_EMPTY_COMPONENT_LIST", expected_status=422)
    assert validate_success(api.get_change_set(change_set["id"], ADMIN), 200)["status"] == "DRAFT"


def test_deploy_before_approval_reports_invalid_state(api):
    """PRD §3.5: "the state precondition still runs ahead of all three, so a
    change set that was never approved reports `ERR_INVALID_STATE` rather than
    `ERR_APPROVAL_STALE`."

    Design: Corner/endpoints/invalid_state_on_deploy_before_validation
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(source["id"], target)

    res = api.deploy_change_set(change_set["id"], {"idempotency_key": "stage-key"}, RELEASE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert validate_success(api.get_change_set(change_set["id"], ADMIN), 200)["status"] == "DRAFT"
    assert _deployments(change_set["id"]) == []


def test_change_set_can_be_validated_after_a_refused_deploy(api):
    """PRD §3.5: "Validation turns a `DRAFT` or `STALE` change set into
    `VALIDATED`."

    Design: Corner/endpoints/invalid_state_on_deploy_before_validation
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(source["id"], target)
    api.deploy_change_set(change_set["id"], {"idempotency_key": "stage-key"}, RELEASE)

    validated = validate_success(api.validate_change_set(change_set["id"], RELEASE), 200)
    assert validated["status"] == "VALIDATED"


def test_state_precondition_outranks_component_dependency_check_on_approve(api):
    """PRD §2.12: "Approving a change set checks the change set's state before
    the segregation-of-duties rule on the approving operator."
    PRD §2.12: "a later check is never reached, so a request that violates two
    rules reports only the earlier one."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_precedes_component_dependency_validation
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}],
        component_dependencies=[{"component": "acme_controller",
                                 "requires": ["acme_absent"], "min_version": 1}])

    res = api.approve_change_set(change_set["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["status"] == "DRAFT"
    assert reloaded["component_digests"] == {}


def test_draft_change_set_stays_draft_after_the_refused_approval(api):
    """PRD §2.12: "then the domain rules in the fixed priority sequence
    described below."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_precedes_component_dependency_validation
    """
    source, target = setup_source_and_target()
    change_set = create_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}],
        component_dependencies=[{"component": "acme_controller",
                                 "requires": ["acme_absent"], "min_version": 1}])
    api.approve_change_set(change_set["id"], ADMIN)

    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["status"] == "DRAFT"
    assert reloaded["approved_at"] is None
    assert reloaded["approved_by_user_id"] is None


# ─── Approval and the revision loop ───────────────────────────────────────────

def test_approval_pins_the_component_version_tags(api):
    """PRD §2.5: "`MetadataChangeSet.component_digests` is empty until the
    change set reaches `APPROVED`, at which point it becomes the pinned
    reference for the deployment and is not rewritten by the deployment itself."
    PRD §3.5: "On success the change set's `component_digests` becomes a map from
    component name to the `version_tag` currently held in the `component_list`"

    Design: Difficulty/non_linear_state_machine/metadata_change_set_approval_reopen_cycle
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}])
    assert change_set["status"] == "APPROVED"
    assert change_set["component_digests"] == {"acme_controller": 1}
    assert change_set["approved_at"] is not None


def test_approval_reopen_cycle_re_pins_the_digests(api):
    """PRD §3.5: "Reopening is the compensating move. It takes an `APPROVED`
    change set back to `VALIDATED`, clears `component_digests` to an empty map,
    nulls `approved_at` and `approved_by_user_id`, and stamps `validated_at`."
    PRD §3.5: "Validation turns a `DRAFT` or `STALE` change set into
    `VALIDATED`. It is not valid from `APPROVED`: an approved change set must
    first be reopened, which is what makes the approval cycle on this entity a
    loop rather than a one-way door."

    Design: Difficulty/non_linear_state_machine/metadata_change_set_approval_reopen_cycle
    """
    source, target = setup_source_and_target()
    approved = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}])
    first_version = approved["version"]

    reopened = validate_success(api.reopen_change_set(approved["id"], RELEASE), 200)
    assert reopened["status"] == "VALIDATED"
    assert reopened["component_digests"] == {}
    assert reopened["approved_at"] is None
    assert reopened["approved_by_user_id"] is None

    reapproved = validate_success(api.approve_change_set(approved["id"], ADMIN), 200)
    assert reapproved["status"] == "APPROVED"
    assert reapproved["component_digests"] == {"acme_controller": 1}
    assert reapproved["version"] > first_version


# ─── Segregation of duties on approval ────────────────────────────────────────

def test_editing_an_approved_change_set_keeps_the_pinned_digests_until_reopen(api):
    """PRD §3.5: "editing a change set that has reached `APPROVED` invalidates
    its pinned digests and moves it to `STALE`, because the pins it was approved
    with no longer describe its contents."

    Design: Difficulty/compensating_invariant/change_set_pinned_digests_compensated_by_reopen
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1},
                        {"component": "acme_layout", "version_tag": 2}])
    assert change_set["component_digests"] == {"acme_controller": 1, "acme_layout": 2}

    stale = validate_success(api.edit_change_set(
        change_set["id"],
        {"component_list": [{"component": "acme_controller", "version_tag": 3},
                            {"component": "acme_layout", "version_tag": 2}]},
        RELEASE), 200)
    assert stale["status"] == "STALE"
    assert stale["component_digests"] == {"acme_controller": 1, "acme_layout": 2}
    assert len(stale["component_digests"]) == 2


def test_reopen_clears_every_pinned_digest_entry(api):
    """PRD §3.5: "It takes an `APPROVED` change set back to `VALIDATED`, clears
    `component_digests` to an empty map, nulls `approved_at` and
    `approved_by_user_id`, and stamps `validated_at`. The cleared digests are
    the point: a revised component list must be approved again before it can be
    deployed."

    Design: Difficulty/compensating_invariant/change_set_pinned_digests_compensated_by_reopen
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1},
                        {"component": "acme_layout", "version_tag": 2}])
    assert len(change_set["component_digests"]) == 2

    reopened = validate_success(api.reopen_change_set(change_set["id"], RELEASE), 200)
    assert reopened["status"] == "VALIDATED"
    assert reopened["component_digests"] == {}
    assert reopened["approved_at"] is None
    assert reopened["approved_by_user_id"] is None
    assert len(reopened["component_digests"]) == 0


def test_same_operator_cannot_approve_two_change_sets_from_one_source(api):
    """PRD §3.5: "it requires the approving operator's `X-User-ID` to differ from
    the identifier recorded on the source environment's most recent change-set
    approval; the same operator identifier may not play both the source-side
    role and the approving role of a deployment, and a repeat is refused with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP status 403."

    Design: Corner/errors/same_operator_cannot_author_and_approve_source
    """
    root = create_production()
    source = create_sandbox(root["id"])
    first_target = create_sandbox(root["id"])
    second_target = create_sandbox(root["id"])
    first = make_platform_admin_headers("0050a0000aaa01")

    first_cs = create_change_set(source["id"], first_target)
    validate_success(api.validate_change_set(first_cs["id"], RELEASE), 200)
    approved = validate_success(api.approve_change_set(first_cs["id"], first), 200)
    assert approved["approved_by_user_id"] == "0050a0000aaa01"

    second_cs = create_change_set(source["id"], second_target)
    validate_success(api.validate_change_set(second_cs["id"], RELEASE), 200)
    res = api.approve_change_set(second_cs["id"], first)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    still_validated = validate_success(api.get_change_set(second_cs["id"], ADMIN), 200)
    assert still_validated["status"] == "VALIDATED"
    assert still_validated["component_digests"] == {}


def test_a_different_operator_can_approve_the_second_change_set(api):
    """PRD §3.5: "the same operator identifier may not play both the source-side
    role and the approving role of a deployment"

    Design: Corner/errors/same_operator_cannot_author_and_approve_source
    """
    root = create_production()
    source = create_sandbox(root["id"])
    first_target = create_sandbox(root["id"])
    second_target = create_sandbox(root["id"])

    first_cs = create_change_set(source["id"], first_target)
    api.validate_change_set(first_cs["id"], RELEASE)
    api.approve_change_set(first_cs["id"], make_platform_admin_headers("0050a0000aaa01"))

    second_cs = create_change_set(source["id"], second_target)
    api.validate_change_set(second_cs["id"], RELEASE)
    approved = validate_success(
        api.approve_change_set(second_cs["id"], make_platform_admin_headers("0050a0000aaa02")),
        200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "0050a0000aaa02"


# ─── Deployment job creation and idempotency ──────────────────────────────────

def test_deployment_job_opens_queued_without_advancing_the_change_set(api):
    """PRD §3.5: "Deployment is opened by a `ReleaseManager` naming an
    `idempotency_key`, and it produces a **DeploymentJob** in status `QUEUED`
    that records the change set being deployed in `change_set_id`, inherits that
    change set's pinned digests, and adopts the change set's
    `target_environment_id`."

    Design: Corner/state_machines/deployment_job_queued_initial_state
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1},
                        {"component": "acme_layout", "version_tag": 1}])

    res = api.deploy_change_set(change_set["id"], {"idempotency_key": "queued-key"}, RELEASE)
    job = validate_success(res, 201)
    assert job["status"] == "QUEUED"
    assert job["applied_component_count"] == 0
    assert job["validated_digest_match"] is False
    assert job["version"] == 1
    assert job["change_set_id"] == change_set["id"]

    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["status"] == "APPROVED"


def test_identical_deploy_key_replays_the_same_job(api):
    """PRD §3.5: "Repeating the deployment request with the same
    `idempotency_key` against the same change set does not open a second job:
    the earlier job is returned unchanged and no new row is created, which is
    what makes the call safely retryable."

    Design: Difficulty/idempotency/identical_deploy_key_replays_without_second_job
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}])

    first = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "same-key"}, RELEASE), 201)
    second = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "same-key"}, RELEASE), 201)
    assert first["id"] == second["id"]

    rows = _deployments(change_set["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "QUEUED"
    assert rows[0]["applied_component_count"] == 0


def test_replayed_deploy_leaves_the_pinned_digests_untouched(api):
    """PRD §3.5: "Repeating the deployment request with the same
    `idempotency_key` against the same change set does not open a second job:
    the earlier job is returned unchanged and no new row is created"

    Design: Difficulty/idempotency/identical_deploy_key_replays_without_second_job
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 7}])

    first = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "replay-key-1"}, RELEASE), 201)
    second = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "replay-key-1"}, RELEASE), 201)
    assert first["id"] == second["id"]

    rows = _deployments(change_set["id"])
    assert len(rows) == 1
    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["component_digests"] == {"acme_controller": 7}
    assert rows[0]["status"] == "QUEUED"
    assert rows[0]["validated_digest_match"] is False


def test_replay_does_not_rewrite_the_pinned_digests(api):
    """PRD §2.5: "`MetadataChangeSet.component_digests` is empty until the
    change set reaches `APPROVED`, at which point it becomes the pinned
    reference for the deployment and is not rewritten by the deployment itself."

    Design: Difficulty/version_pinning_on_approval/idempotent_deployment_replay_preserves_pinned_digests
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 7}])

    first = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "replay-key-2"}, RELEASE), 201)
    second = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "replay-key-2"}, RELEASE), 201)
    assert first["id"] == second["id"]

    assert validate_success(
        api.get_change_set(change_set["id"], ADMIN), 200)["component_digests"] == {
            "acme_controller": 7}
    assert _deployments(change_set["id"])[0]["validated_digest_match"] is False


def test_replay_returns_the_job_unchanged_at_its_queued_state(api):
    """PRD §3.5: "Repeating the deployment request with the same
    `idempotency_key` against the same change set does not open a second job:
    the earlier job is returned unchanged and no new row is created, which is
    what makes the call safely retryable."

    Design: Difficulty/version_pinning_on_approval/idempotent_deployment_replay_preserves_pinned_digests
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 7}])

    validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "replay-key-3"}, RELEASE), 201)
    replayed = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "replay-key-3"}, RELEASE), 201)
    assert replayed["status"] == "QUEUED"
    assert replayed["applied_component_count"] == 0
    assert len(_deployments(change_set["id"])) == 1


def test_distinct_deploy_keys_open_a_second_job(api):
    """PRD §3.5: "Repeating the deployment request with the same
    `idempotency_key` against the same change set does not open a second job"
    PRD §3.5: "The deployment history of a change set is readable, and unlike
    the refresh history it is returned oldest first."

    Design: Difficulty/idempotency/distinct_deploy_key_opens_a_second_job
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(source["id"], target)

    first = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "distinct-1"}, RELEASE), 201)
    second = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "distinct-2"}, RELEASE), 201)
    assert first["id"] != second["id"]

    rows = _deployments(change_set["id"])
    assert len(rows) == 2
    assert all(row["status"] == "QUEUED" and row["applied_component_count"] == 0 for row in rows)


def test_distinct_deploy_jobs_keep_their_idempotency_keys(api):
    """PRD §3.5: "Deployment is opened by a `ReleaseManager` naming an
    `idempotency_key`"

    Design: Difficulty/idempotency/distinct_deploy_key_opens_a_second_job
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(source["id"], target)

    validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "distinct-1"}, RELEASE), 201)
    validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "distinct-2"}, RELEASE), 201)

    rows = _deployments(change_set["id"])
    assert {row["idempotency_key"] for row in rows} == {"distinct-1", "distinct-2"}


# ─── Version-pinned digests block completion ──────────────────────────────────

def test_digest_mismatch_blocks_deployment_completion(api):
    """PRD §3.5: "An `EnvironmentAdmin` completes an `EXECUTING` job, but only
    when the change set's pinned digests still match its current component
    `version_tag` values"
    PRD §3.5: "The request is accepted only for a change set that has reached
    `APPROVED`, whose source and target environments differ, and whose
    `component_digests` still equal the `version_tag` values currently carried
    by its `component_list`; any one of those three conditions failing is
    reported as `ERR_APPROVAL_STALE` with HTTP status 409"

    Design: Difficulty/version_pinning_on_approval/digest_mismatch_blocks_deployment_completion
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}])
    job = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "stale-flow-1"}, RELEASE), 201)

    api.edit_change_set(change_set["id"],
                        {"component_list": [{"component": "acme_controller", "version_tag": 2}]},
                        RELEASE)

    res = api.complete_deployment_job(job["id"], ENV_ADMIN)
    validate_error(res, "ERR_APPROVAL_STALE", expected_status=409)


def test_refused_completion_leaves_job_and_change_set_intact(api):
    """PRD §3.5: "editing a change set that has reached `APPROVED` invalidates
    its pinned digests and moves it to `STALE`, because the pins it was approved
    with no longer describe its contents."

    Design: Difficulty/version_pinning_on_approval/digest_mismatch_blocks_deployment_completion
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}])
    job = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "stale-flow-1"}, RELEASE), 201)
    api.edit_change_set(change_set["id"],
                        {"component_list": [{"component": "acme_controller", "version_tag": 2}]},
                        RELEASE)

    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["component_digests"] == {"acme_controller": 1}
    assert reloaded["component_list"][0]["version_tag"] == 2
    assert reloaded["status"] == "STALE"

    api.complete_deployment_job(job["id"], ENV_ADMIN)
    rows = _deployments(change_set["id"])
    assert rows[0]["status"] == "EXECUTING"
    assert rows[0]["applied_component_count"] == 0
    assert validate_success(api.get_change_set(change_set["id"], ADMIN), 200)["status"] == "STALE"


# ─── Completing a deployment ──────────────────────────────────────────────────

def test_deployment_completion_drives_the_change_set_to_deployed(api):
    """PRD §3.5: "on success `applied_component_count` is written as the length
    of the change set's `component_list` and `validated_digest_match` is set
    true, the referencing change set moves from `APPROVED` to `DEPLOYED` and its
    own version advances, and the digests are retained unchanged as the pinned
    reference for the deployment"

    Design: Corner/endpoints/deployment_job_completion_drives_change_set_to_deployed
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1},
                        {"component": "acme_layout", "version_tag": 3}])
    job = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "complete-key"}, RELEASE), 201)

    completed = validate_success(api.complete_deployment_job(job["id"], ENV_ADMIN), 200)
    assert completed["status"] == "SUCCEEDED"
    assert completed["validated_digest_match"] is True
    assert completed["applied_component_count"] == 2

    reloaded = validate_success(api.get_change_set(change_set["id"], ADMIN), 200)
    assert reloaded["status"] == "DEPLOYED"
    assert reloaded["component_digests"] == {"acme_controller": 1, "acme_layout": 3}


def test_failed_deployment_counts_no_applied_components(api):
    """PRD §3.5: "Alternatively an `EnvironmentAdmin` fails an `EXECUTING` job,
    which is terminal for the job and leaves `applied_component_count` at zero,
    since no components are counted as applied on a failed deployment."

    Design: Corner/endpoints/deployment_job_completion_drives_change_set_to_deployed
    """
    source, target = setup_source_and_target()
    change_set = create_approved_change_set(
        source["id"], target,
        component_list=[{"component": "acme_controller", "version_tag": 1}])
    job = validate_success(api.deploy_change_set(
        change_set["id"], {"idempotency_key": "fail-key"}, RELEASE), 201)

    failed = validate_success(api.fail_deployment_job(job["id"], ENV_ADMIN), 200)
    assert failed["status"] == "FAILED"
    assert failed["applied_component_count"] == 0
    assert validate_success(api.get_change_set(change_set["id"], ADMIN), 200)["status"] == "APPROVED"