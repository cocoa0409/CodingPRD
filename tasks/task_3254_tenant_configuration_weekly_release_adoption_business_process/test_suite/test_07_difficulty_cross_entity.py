"""Difficulty queue A: cross-entity state dependencies."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    admin_of,
    ApiErrorId,
    add_membership,
    add_step,
    create_active_unit,
    create_definition,
    create_feature_train,
    create_group,
    create_tenant,
    create_worker,
    enroll,
    get_adoption,
    get_train,
    set_clock,
)


def _definition_referencing_understaffed_group():
    """Tenant with a USER_BASED group (min_approvers 2) holding only one ACTIVE
    member, and a DRAFT definition whose step 1 references the group."""
    tenant = create_tenant("T-CE1")
    admin = admin_of(tenant)
    tid = tenant["id"]
    unit = create_active_unit(tid, "U1", admin)
    approver = create_worker(tid, unit["id"], "MGR", admin)
    second = create_worker(tid, unit["id"], "MGR2", admin)
    group = create_group(tid, "G1", admin, min_approvers=2)
    add_membership(tid, group["id"], approver["id"], admin)
    definition = create_definition(tid, admin, transaction_type="HIRE", name="Flow")
    add_step(tid, definition["id"], 1, admin, group_id=group["id"])
    return tenant, admin, group, definition, second


def test_activation_rejected_when_group_below_min_approvers(api):
    """PRD §3.5: "every `APPROVAL` and `REVIEW` step's
    `approver_security_group_id` references a group that is `ACTIVE` with
    `ACTIVE` memberships of at least the group's `min_approvers`
    (`ERR_GROUP_INELIGIBLE`, HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/definition_activation_requires_group_eligible
    """
    tenant, admin, group, definition, _second = \
        _definition_referencing_understaffed_group()
    tid = tenant["id"]

    current = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    resp = api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": current["version"]}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_GROUP_INELIGIBLE)

    definition = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    assert definition["status"] == "DRAFT", (
        "the rejected activation must not change the definition state"
    )


def test_activation_succeeds_after_group_gains_membership(api):
    """PRD §3.5: "every `APPROVAL` and `REVIEW` step's
    `approver_security_group_id` references a group that is `ACTIVE` with
    `ACTIVE` memberships of at least the group's `min_approvers`
    (`ERR_GROUP_INELIGIBLE`, HTTP 422). A successful activation increments the
    definition's `version` by 1."

    Once the group reaches min_approvers, the same definition activates.

    Design: Difficulty/cross_entity_state_dependency/definition_activation_requires_group_eligible
    """
    tenant, admin, group, definition, second = \
        _definition_referencing_understaffed_group()
    tid = tenant["id"]

    before = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    resp = api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": before["version"]}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_GROUP_INELIGIBLE)

    add_membership(tid, group["id"], second["id"], admin)  # 2 ACTIVE members

    current = get_success_data(api_client.get_definition(tid, definition["id"], admin))
    activated = get_success_data(api_client.activate_definition(
        tid, definition["id"],
        {"expected_definition_version": current["version"]}, admin,
    ))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == current["version"] + 1


def _testing_passed_on_closed_train():
    """Adoption driven to TESTING_PASSED while the window is open; clock then
    advanced past opt_in_window_end."""
    tenant = create_tenant("T-CE2")
    admin = admin_of(tenant)
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")
    adoption = enroll(tenant["id"], train["id"], "F1", admin)
    get_success_data(api_client.record_testing(
        tenant["id"], adoption["id"], {"sandbox_test_evidence_id": "EV"}, admin,
    ))
    set_clock("2026-09-11T00:00:00Z")  # window closed
    return tenant, admin, train, adoption


def test_adopt_rejected_after_opt_in_window_closes(api):
    """PRD §3.7: "All four adoption transitions — enrollment, record-testing,
    adopt, defer — are permitted only while the train is `OPT_IN_OPEN`
    (inclusive of `opt_in_window_end`); outside the window they fail with
    `ERR_OPT_IN_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/adoption_transitions_require_train_opt_in_open
    """
    tenant, admin, train, adoption = _testing_passed_on_closed_train()
    tid = tenant["id"]
    assert get_train(train["id"])["status"] == "OPT_IN_CLOSED"

    resp = api_client.adopt_feature(tid, adoption["id"], admin)
    validate_error(resp, ApiErrorId.ERR_OPT_IN_WINDOW_CLOSED)

    adoption = get_adoption(tid, adoption["id"], admin)
    assert adoption["status"] == "TESTING_PASSED", (
        "a failed transition must not change the adoption state"
    )


def test_enrollment_rejected_after_opt_in_window_closes(api):
    """PRD §3.7: "All four adoption transitions — enrollment, record-testing,
    adopt, defer — are permitted only while the train is `OPT_IN_OPEN`
    (inclusive of `opt_in_window_end`); outside the window they fail with
    `ERR_OPT_IN_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/adoption_transitions_require_train_opt_in_open
    """
    tenant, admin, train, _adoption = _testing_passed_on_closed_train()
    assert get_train(train["id"])["status"] == "OPT_IN_CLOSED"

    resp = api_client.create_feature_adoption(
        tenant["id"], {"release_train_id": train["id"], "feature_key": "F2"}, admin,
    )
    validate_error(resp, ApiErrorId.ERR_OPT_IN_WINDOW_CLOSED)
