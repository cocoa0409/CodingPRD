"""The design clearance cycle: rejection, resubmission, re-approval."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    DESIGN_OPS,
    approve_design,
    create_design,
    create_licensor,
    get_design,
    make_licensing_ops_headers,
    reject_design,
    set_clock,
)


def test_a_rejected_design_returns_to_pending_on_resubmission(api):
    """PRD §3.1: "Resubmission requires `APPROVAL_REJECTED` and moves the design
    back to `PENDING_LICENSOR_APPROVAL` with `rejection_reason` cleared to null,
    ready for a fresh licensor decision, and increments `Design.version` by
    exactly 1."

    Design: Difficulty/non_linear_state_machine/design_rejection_resubmission_cycle
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Marks", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="NYC", garment_sku="MINI",
                           design_name="NYC Champs Mini", approve=False)

    rejected = reject_design(api, licensor, design, "Mark placement off brand")
    assert rejected["approval_state"] == "APPROVAL_REJECTED"
    assert rejected["rejection_reason"] == "Mark placement off brand"

    resubmitted = validate_success(
        api.submit_design(
            design["id"], {"expected_design_version": rejected["version"]},
            DESIGN_OPS,
        ),
        expected_status=200,
    )

    assert resubmitted["approval_state"] == "PENDING_LICENSOR_APPROVAL"
    assert resubmitted["rejection_reason"] is None
    assert resubmitted["version"] == rejected["version"] + 1

    read = get_design(api, design["id"])
    assert read["rejection_reason"] is None


def test_a_resubmitted_design_can_then_be_approved(api):
    """PRD §3.1: "Recording `decision` as `APPROVE` requires the design to be in
    `PENDING_LICENSOR_APPROVAL`; it moves `approval_state` to `APPROVED`, which is
    a terminal state for the channel, and pins `approved_version` to the design's
    `version` as it stands after that call's increment."

    Design: Difficulty/non_linear_state_machine/design_rejection_resubmission_cycle
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Marks 2", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="NYC", garment_sku="MINI",
                           approve=False)

    rejected = reject_design(api, licensor, design, "Wrong mark ratio")
    resubmitted = validate_success(
        api.submit_design(
            design["id"], {"expected_design_version": rejected["version"]},
            DESIGN_OPS,
        ),
        expected_status=200,
    )
    approved = approve_design(api, licensor, resubmitted)

    assert approved["approval_state"] == "APPROVED"
    assert approved["version"] == resubmitted["version"] + 1
    assert approved["approved_version"] == approved["version"]

    read = get_design(api, design["id"])
    assert read["approval_state"] == "APPROVED"
    assert read["approved_version"] == approved["version"]


def test_a_second_decision_while_rejected_is_an_invalid_state(api):
    """PRD §3.1: "Recording `decision` as `APPROVE` requires the design to be in
    `PENDING_LICENSOR_APPROVAL`"
    PRD §2.10: "A resource that is not in a state permitting the requested
    transition ... yields `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/design_reject_from_rejected_returns_invalid_state
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor K", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="ATL", garment_sku="MINI",
                           design_name="K Mini", approve=False)
    rejected = reject_design(api, licensor, design, "Wrong mark ratio")

    resp = api.licensor_decision(
        design["id"],
        {"decision": "APPROVE", "expected_design_version": rejected["version"]},
        make_licensing_ops_headers(licensor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    read = get_design(api, design["id"])
    assert read["approval_state"] == "APPROVAL_REJECTED"
    assert read["approved_version"] is None


def test_resubmission_is_refused_on_an_approved_design(api):
    """PRD §3.1: "Resubmission requires `APPROVAL_REJECTED`"
    PRD §2.10: "A resource that is not in a state permitting the requested
    transition ... yields `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/endpoints/design_reversal_only_valid_from_rejected_state
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor X", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="ATL", garment_sku="MINI",
                           design_name="X Mini")

    resp = api.submit_design(
        design["id"], {"expected_design_version": design["version"]}, DESIGN_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    read = get_design(api, design["id"])
    assert read["approval_state"] == "APPROVED"
    assert read["approved_version"] == design["approved_version"]


def test_the_design_version_advances_on_every_accepted_write(api):
    """PRD §2.5: "`version` is an integer that starts at its initial value when
    the resource is created and is incremented by exactly 1 on every mutation of
    that resource."

    Design: Corner/cross_cutting_complexity_layers/design_version_advances_on_every_write
    """
    set_clock(api)
    licensor = create_licensor(api, name="Licensor AL", royalty_rate_pct=0.1)
    design = create_design(api, licensor, team_code="BOS", garment_sku="MINI",
                           design_name="AL Mini", approve=False)

    created_version = design["version"]
    approved = validate_success(
        api.licensor_decision(
            design["id"],
            {"decision": "APPROVE", "expected_design_version": created_version},
            make_licensing_ops_headers(licensor["id"]),
        ),
        expected_status=200,
    )
    assert approved["version"] == created_version + 1

    rejected_write = api.submit_design(
        design["id"], {"expected_design_version": approved["version"]}, DESIGN_OPS,
    )
    validate_error(rejected_write, ApiErrorId.ERR_INVALID_STATE)

    assert get_design(api, design["id"])["version"] == approved["version"]