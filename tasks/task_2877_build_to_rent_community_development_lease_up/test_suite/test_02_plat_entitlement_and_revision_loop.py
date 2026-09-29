"""Entitlement and platting: the revision loop, terminal rejection, and the two decision gates."""

from test_helpers import (
    ApiErrorId,
    DEVELOPER_PRINCIPAL_USER_ID,
    assert_community,
    create_community_payload,
    make_developer_principal_headers,
    make_entitlement_officer_headers,
    plat_decision_payload,
    plat_submission_payload,
    validate_error,
    validate_success,
)

GRANITE_ROW_PAYLOAD = dict(
    name="Granite Row",
    market_code="TX-HOU",
    total_planned_units=2,
    product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
    single_ownership_covenant=True,
    concession_budget_cents=1_000_000,
    facility_commitment_cents=20_000_000,
    maintenance_tech_headcount=1,
)


def test_plat_revision_loop_returns_to_submitted_without_resetting_the_round(
    api, developer_principal_headers, entitlement_officer_headers
):
    """A plat that is submitted, sent back for revision and resubmitted occupies SUBMITTED a
    second time while the revision round it accumulated stays where it is, and the final
    approval leaves that round untouched.

    Submission is legal from either `DRAFT` or `REVISION_REQUESTED`; attempting it while the plat is already `SUBMITTED`, or after it has reached `APPROVED` or `REJECTED`, is refused with `ERR_INVALID_PLAT_STATE`. Resubmission after a revision request is the same operation and closes the revision loop `DRAFT → SUBMITTED → REVISION_REQUESTED → SUBMITTED`; it additionally requires that `plat_revision_round` has not exceeded 2, and it deliberately does **not** reset `plat_revision_round`. On success `plat_status` becomes `REVISION_REQUESTED`, `plat_revision_round` increases by 1, and the community's `version` increments.
    Design: Difficulty/non_linear_state_machine/plat_revision_loop_returns_submitted_to_submitted_and_increments_round
    """
    community = validate_success(
        api.create_community(
            create_community_payload(**GRANITE_ROW_PAYLOAD), developer_principal_headers
        ),
        201,
    )
    assert community["plat_status"] == "DRAFT"
    assert community["plat_revision_round"] == 0

    submitted = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-GR-1"),
            developer_principal_headers,
        ),
        201,
    )
    assert submitted["plat_status"] == "SUBMITTED"
    assert submitted["plat_revision_round"] == 0
    assert submitted["plat_package_reference"] == "PLAT-GR-1"

    revised = validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload(
                "REQUEST_REVISION", decision_note="Reduce lot coverage on the north edge"
            ),
            entitlement_officer_headers,
        ),
        201,
    )
    assert revised["plat_status"] == "REVISION_REQUESTED"
    assert revised["plat_revision_round"] == 1

    resubmitted = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-GR-2"),
            developer_principal_headers,
        ),
        201,
    )
    assert resubmitted["plat_status"] == "SUBMITTED"
    assert resubmitted["plat_revision_round"] == 1, (
        "the round does not increment on resubmission and is never reset"
    )
    assert resubmitted["plat_package_reference"] == "PLAT-GR-2"

    approved = validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload("APPROVE"),
            entitlement_officer_headers,
        ),
        201,
    )
    assert_community(approved)
    assert approved["plat_status"] == "APPROVED"
    assert approved["plat_revision_round"] == 1


def test_plat_revision_loop_keeps_the_posture_frozen_until_the_approval(
    api, asset_manager_headers, developer_principal_headers, entitlement_officer_headers
):
    """Throughout the submit, revise and resubmit cycle the community stays frozen and keeps
    the operator who lodged the package; only the approving decision opens it.

    Nothing in a community can be built or leased until the plat is approved, because the posture stays `FROZEN` for as long as `plat_status` is anything other than `APPROVED`. A successful submission moves `plat_status` to `SUBMITTED`, records the supplied reference in `plat_package_reference`, records the submitting operator's `X-User-ID` in `plat_submitted_by_user_id`, recomputes the community's `posture` — which stays `FROZEN`, since the plat is not yet approved — and increments the community's `version` by 1. On success `plat_status` becomes `APPROVED`, the community's `version` increments, and the posture is recomputed — which is the moment a community first leaves `FROZEN`, landing on `OPEN` when no housing phase is halted and the amenity gate is satisfied, or on `RESTRICTED` when it is not.
    Design: Difficulty/non_linear_state_machine/plat_revision_loop_returns_submitted_to_submitted_and_increments_round
    """
    community = validate_success(
        api.create_community(
            create_community_payload(**GRANITE_ROW_PAYLOAD), developer_principal_headers
        ),
        201,
    )
    assert community["posture"] == "FROZEN"

    submitted = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-GR-1"),
            developer_principal_headers,
        ),
        201,
    )
    assert submitted["posture"] == "FROZEN"
    assert submitted["plat_submitted_by_user_id"] == DEVELOPER_PRINCIPAL_USER_ID

    revised = validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload(
                "REQUEST_REVISION", decision_note="Reduce lot coverage on the north edge"
            ),
            entitlement_officer_headers,
        ),
        201,
    )
    assert revised["posture"] == "FROZEN"

    resubmitted = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-GR-2"),
            developer_principal_headers,
        ),
        201,
    )
    assert resubmitted["posture"] == "FROZEN"
    assert resubmitted["plat_submitted_by_user_id"] == DEVELOPER_PRINCIPAL_USER_ID

    approved = validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload("APPROVE"),
            entitlement_officer_headers,
        ),
        201,
    )
    assert approved["posture"] == "OPEN"
    assert approved["plat_submitted_by_user_id"] == DEVELOPER_PRINCIPAL_USER_ID

    reread = validate_success(api.get_community(community["id"], asset_manager_headers), 200)
    assert reread["plat_status"] == "APPROVED"
    assert reread["posture"] == "OPEN"
    assert reread["plat_revision_round"] == 1


def test_plat_submission_moves_the_plat_from_draft_to_submitted(
    api, developer_principal_headers
):
    """The first plat transition fires on its own trigger, records the lodged package and the
    submitting operator, and leaves the community frozen because submission is not approval.

    A successful submission moves `plat_status` to `SUBMITTED`, records the supplied reference in `plat_package_reference`, records the submitting operator's `X-User-ID` in `plat_submitted_by_user_id`, recomputes the community's `posture` — which stays `FROZEN`, since the plat is not yet approved — and increments the community's `version` by 1.
    Design: Corner/state_machines/plat_submission_moves_the_plat_from_draft_to_submitted
    """
    community = validate_success(
        api.create_community(
            create_community_payload(
                name="Kestrel Run",
                market_code="TX-AUS",
                total_planned_units=4,
                product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
                single_ownership_covenant=True,
                concession_budget_cents=2_000_000,
                facility_commitment_cents=40_000_000,
                maintenance_tech_headcount=2,
            ),
            developer_principal_headers,
        ),
        201,
    )

    submitted = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-KR-1"),
            developer_principal_headers,
        ),
        201,
    )

    assert_community(submitted)
    assert submitted["plat_status"] == "SUBMITTED"
    assert submitted["plat_package_reference"] == "PLAT-KR-1"
    assert submitted["plat_submitted_by_user_id"] == DEVELOPER_PRINCIPAL_USER_ID
    assert submitted["plat_revision_round"] == 0
    assert submitted["posture"] == "FROZEN"
    assert submitted["version"] == 2


def test_a_rejected_plat_is_terminal_and_blocks_every_further_plat_trigger(
    api, asset_manager_headers, developer_principal_headers, entitlement_officer_headers
):
    """Once a plat is rejected, neither a fresh submission nor a later approval is accepted,
    and the community keeps the rejected package, a frozen posture and its planning lifecycle.

    Submission is legal from either `DRAFT` or `REVISION_REQUESTED`; attempting it while the plat is already `SUBMITTED`, or after it has reached `APPROVED` or `REJECTED`, is refused with `ERR_INVALID_PLAT_STATE`. Any decision requires that `plat_status` is currently `SUBMITTED` — deciding a plat in any other state is `ERR_INVALID_PLAT_STATE` — and that the deciding `X-User-ID` differs from the community's `plat_submitted_by_user_id`, failing which the decision is `ERR_SEGREGATION_OF_DUTIES`. On success `plat_status` becomes `REJECTED`, which is terminal, the posture becomes `FROZEN` permanently — no later action can lift it — and the community's `version` increments.
    Design: Corner/state_machines/a_rejected_plat_is_terminal_and_blocks_every_further_plat_trigger
    """
    community = validate_success(
        api.create_community(
            create_community_payload(
                name="Quarrystone",
                market_code="TX-DFW",
                total_planned_units=4,
                product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
                single_ownership_covenant=True,
                concession_budget_cents=2_000_000,
                facility_commitment_cents=40_000_000,
                maintenance_tech_headcount=2,
            ),
            developer_principal_headers,
        ),
        201,
    )
    validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-QS-1"),
            developer_principal_headers,
        ),
        201,
    )
    rejected = validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload(
                "REJECT",
                decision_note="Lot layout severs the single-ownership parcel",
            ),
            entitlement_officer_headers,
        ),
        201,
    )
    assert rejected["plat_status"] == "REJECTED"

    resubmission = api.submit_plat(
        community["id"],
        plat_submission_payload(plat_package_reference="PLAT-QS-2"),
        developer_principal_headers,
    )
    validate_error(resubmission, ApiErrorId.ERR_INVALID_PLAT_STATE.value)

    late_approval = api.decide_plat(
        community["id"], plat_decision_payload("APPROVE"), entitlement_officer_headers
    )
    validate_error(late_approval, ApiErrorId.ERR_INVALID_PLAT_STATE.value)

    reread = validate_success(api.get_community(community["id"], asset_manager_headers), 200)
    assert reread["plat_status"] == "REJECTED"
    assert reread["plat_package_reference"] == "PLAT-QS-1"
    assert reread["posture"] == "FROZEN"
    assert reread["lifecycle_status"] == "PLANNING"


def test_a_third_revision_request_is_refused_and_the_plat_can_still_be_approved(
    api, asset_manager_headers, developer_principal_headers, entitlement_officer_headers
):
    """After two revision rounds the plat sits submitted with its round at two; a third
    revision request is refused on the limit while an approval on that same plat still works.

    A `REQUEST_REVISION` decision additionally requires that `plat_revision_round` has not yet reached 2; a third revision request on the same plat is refused with `ERR_PLAT_REVISION_LIMIT`. Resubmission after a revision request is the same operation and closes the revision loop `DRAFT → SUBMITTED → REVISION_REQUESTED → SUBMITTED`; it additionally requires that `plat_revision_round` has not exceeded 2, and it deliberately does **not** reset `plat_revision_round`. On success `plat_status` becomes `APPROVED`, the community's `version` increments, and the posture is recomputed — which is the moment a community first leaves `FROZEN`, landing on `OPEN` when no housing phase is halted and the amenity gate is satisfied, or on `RESTRICTED` when it is not.
    Design: Corner/state_machines/a_third_revision_request_is_refused_and_the_plat_can_still_be_approved
    """
    community = validate_success(
        api.create_community(
            create_community_payload(
                name="Stonefall",
                market_code="TX-HOU",
                total_planned_units=4,
                product_mix={"DETACHED": 4, "COTTAGE": 0, "TOWNHOME": 0},
                single_ownership_covenant=True,
                concession_budget_cents=2_000_000,
                facility_commitment_cents=40_000_000,
                maintenance_tech_headcount=2,
            ),
            developer_principal_headers,
        ),
        201,
    )
    validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-SF-1"),
            developer_principal_headers,
        ),
        201,
    )
    validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload(
                "REQUEST_REVISION", decision_note="Add the shared drive easement"
            ),
            entitlement_officer_headers,
        ),
        201,
    )
    validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-SF-2"),
            developer_principal_headers,
        ),
        201,
    )
    validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload(
                "REQUEST_REVISION", decision_note="Easement width still short"
            ),
            entitlement_officer_headers,
        ),
        201,
    )
    third_submission = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-SF-3"),
            developer_principal_headers,
        ),
        201,
    )
    assert third_submission["plat_status"] == "SUBMITTED"
    assert third_submission["plat_revision_round"] == 2

    refused = api.decide_plat(
        community["id"],
        plat_decision_payload(
            "REQUEST_REVISION", decision_note="One more look at the drainage"
        ),
        entitlement_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_PLAT_REVISION_LIMIT.value)

    after_refusal = validate_success(
        api.get_community(community["id"], asset_manager_headers), 200
    )
    assert after_refusal["plat_status"] == "SUBMITTED"
    assert after_refusal["plat_revision_round"] == 2

    approved = validate_success(
        api.decide_plat(
            community["id"], plat_decision_payload("APPROVE"), entitlement_officer_headers
        ),
        201,
    )
    assert approved["plat_status"] == "APPROVED"
    assert approved["posture"] == "OPEN"
    assert approved["plat_package_reference"] == "PLAT-SF-3"


def test_plat_decision_by_the_submitting_user_is_refused_for_segregation_of_duties(
    api, asset_manager_headers
):
    """One operator identifier that both lodged the package and then wears the reviewing role
    is refused, while the identical approval from a different identifier goes through.

    Two duties in this system are deliberately segregated, and both are enforced by comparing `X-User-ID` values rather than roles. The `EntitlementOfficer` who decides a plat must not be the operator recorded in that community's `plat_submitted_by_user_id`, and the `AssetManager` who decides a concession must not be the operator recorded in that lease's `concession_requested_by_user_id`. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
    Design: Corner/validations/plat_decision_by_the_submitting_user_is_rejected_for_segregation_of_duties
    """
    both_hats_headers = make_developer_principal_headers("u_both")
    community = validate_success(
        api.create_community(
            create_community_payload(
                name="Dunwarren",
                market_code="TX-SAT",
                total_planned_units=2,
                product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
                single_ownership_covenant=True,
                concession_budget_cents=1_000_000,
                facility_commitment_cents=20_000_000,
                maintenance_tech_headcount=2,
            ),
            both_hats_headers,
        ),
        201,
    )
    submitted = validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-DW-1"),
            both_hats_headers,
        ),
        201,
    )
    assert submitted["plat_submitted_by_user_id"] == "u_both"

    collision = api.decide_plat(
        community["id"],
        plat_decision_payload("APPROVE"),
        make_entitlement_officer_headers("u_both"),
    )
    validate_error(collision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after_collision = validate_success(
        api.get_community(community["id"], asset_manager_headers), 200
    )
    assert after_collision["plat_status"] == "SUBMITTED"
    assert after_collision["posture"] == "FROZEN"

    approved = validate_success(
        api.decide_plat(
            community["id"],
            plat_decision_payload("APPROVE"),
            make_entitlement_officer_headers("u_ent_1"),
        ),
        201,
    )
    assert approved["plat_status"] == "APPROVED"
    assert approved["posture"] == "OPEN"
    assert approved["plat_submitted_by_user_id"] == "u_both"


def test_plat_approval_is_refused_when_the_single_ownership_covenant_is_false(
    api, asset_manager_headers, developer_principal_headers, entitlement_officer_headers
):
    """A community registered without the single-ownership covenant may lodge its package but
    can never have it approved, and its posture is frozen by the covenant itself.

    An `APPROVE` decision additionally requires that the community's `single_ownership_covenant` is true; platting that would break single-ownership operation of the whole community may not be approved, and the attempt draws `ERR_SINGLE_OWNERSHIP_COVENANT_REQUIRED`. The posture is `FROZEN` if any of these three conditions holds: the community's `plat_status` is anything other than `APPROVED`; or its `single_ownership_covenant` is false; or at least one phase of the community whose `kind` is `HOUSING` currently has `status` equal to `CONSTRUCTION_HALTED`.
    Design: Corner/validations/plat_approval_is_rejected_when_the_single_ownership_covenant_is_false
    """
    community = validate_success(
        api.create_community(
            create_community_payload(
                name="Elsmere",
                market_code="TX-DFW",
                total_planned_units=2,
                product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
                single_ownership_covenant=False,
                concession_budget_cents=1_000_000,
                facility_commitment_cents=20_000_000,
                maintenance_tech_headcount=2,
            ),
            developer_principal_headers,
        ),
        201,
    )
    assert community["single_ownership_covenant"] is False

    validate_success(
        api.submit_plat(
            community["id"],
            plat_submission_payload(plat_package_reference="PLAT-EM-1"),
            developer_principal_headers,
        ),
        201,
    )

    refused = api.decide_plat(
        community["id"], plat_decision_payload("APPROVE"), entitlement_officer_headers
    )
    validate_error(refused, ApiErrorId.ERR_SINGLE_OWNERSHIP_COVENANT_REQUIRED.value)

    reread = validate_success(api.get_community(community["id"], asset_manager_headers), 200)
    assert_community(reread)
    assert reread["plat_status"] == "SUBMITTED"
    assert reread["posture"] == "FROZEN"
