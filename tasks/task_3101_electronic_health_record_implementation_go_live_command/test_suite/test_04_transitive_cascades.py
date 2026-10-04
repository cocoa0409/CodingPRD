"""Transitive cascades: one mutation propagating through dependent hops.

Covers the four-hop defect-resolution cascade (scenario -> build item ->
department -> facility) and the two-hop interface message rejection.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    get_department,
    get_facility,
    get_build_item,
    setup_rejected_build_item_with_sev1_defect,
    setup_interface_channel_in_validation,
    create_interface_message_payload,
    BUILD_ANALYST,
    TEST_LEAD,
    INTERFACE,
    ANALYST,
)


# ===========================================================================
# r4_defect_resolution_four_hop_cascade
# ===========================================================================

def test_resolving_a_blocking_defect_clears_the_scenario_and_item_defect_counts(api, build_analyst_headers, test_lead_headers):
    """PRD §3.5: "Resolving a defect is the most consequential single action in
    the build estate, because it cascades through four links in strict order.
    The first link decrements the `open_defect_count` of the scenario that owns
    the defect by one. The second decrements the `open_defect_count` of the build
    item that owns that scenario by one."
    PRD §3.5: "The second decrements the `open_defect_count` of the build item
    that owns that scenario by one."

    Before resolution the department carries one blocking defect; after it, both
    the scenario and the build item report no open defect.

    Design: Difficulty/transitive_cascade/r4_defect_resolution_four_hop_cascade
    """
    ctx = setup_rejected_build_item_with_sev1_defect()

    dept_before = get_department(ctx["dept"]["id"], ANALYST)
    fac_before = get_facility(ctx["fac"]["id"], ANALYST)
    assert dept_before["status"] == "BUILD_REJECTED"
    assert dept_before["build_blocking_defect_count"] == 1
    assert fac_before["status"] == "REMEDIATION_REQUIRED"

    validate_success(api.begin_remediation(ctx["defect"]["id"], build_analyst_headers), 200)
    validate_success(api.resolve_defect(ctx["defect"]["id"], build_analyst_headers), 200)

    scenario = validate_success(
        api.get_test_scenario(ctx["scenario"]["id"], test_lead_headers), 200
    )
    assert scenario["open_defect_count"] == 0, "link 1: the scenario's open defect count clears"

    item = get_build_item(ctx["item"]["id"], test_lead_headers)
    assert item["open_defect_count"] == 0, "link 2: the build item's open defect count clears"


def test_resolving_a_blocking_defect_carries_the_department_and_facility_back(api, build_analyst_headers, test_lead_headers):
    """PRD §3.5: "The third decrements the owning department's
    `build_blocking_defect_count` by one when the defect's severity is in `SEV1`
    or `SEV2`, and once that count reaches 0 the department moves from
    `BUILD_REJECTED` back to `BUILD_COMPLETE`. The fourth link reaches the
    facility: if the owning facility is sitting in `REMEDIATION_REQUIRED` and no
    department of it remains `BUILD_REJECTED`, the facility returns to
    `BUILD_CONFIGURED`."
    PRD §3.5: "Resolution also stamps `resolution_epoch` with the current epoch
    and clears `blocks_go_live`."

    Design: Difficulty/transitive_cascade/r4_defect_resolution_four_hop_cascade
    """
    ctx = setup_rejected_build_item_with_sev1_defect()
    validate_success(api.begin_remediation(ctx["defect"]["id"], build_analyst_headers), 200)
    resolved = validate_success(api.resolve_defect(ctx["defect"]["id"], build_analyst_headers), 200)

    dept_after = get_department(ctx["dept"]["id"], ANALYST)
    assert dept_after["build_blocking_defect_count"] == 0, "link 3: the blocking count reaches zero"
    assert dept_after["status"] == "BUILD_COMPLETE", "link 3: the department returns to BUILD_COMPLETE"

    fac_after = get_facility(ctx["fac"]["id"], ANALYST)
    assert fac_after["status"] == "BUILD_CONFIGURED", "link 4: the facility returns to BUILD_CONFIGURED"

    assert resolved["status"] == "RESOLVED"
    assert resolved["blocks_go_live"] is False
    assert resolved["resolution_epoch"] == 0


# ===========================================================================
# r4_interface_message_rejection_two_hop_cascade
# ===========================================================================

def test_a_message_whose_code_is_wrong_for_the_channel_is_rejected(api, interface_headers, analyst_headers):
    """PRD §3.6: "The message's `message_code` — one of `ADT_A01`, `ORM_O01`,
    `ORU_R01`, `RDE_O11` or `DICOM_STOW` — must be a member of the valid code set
    for the owning `channel_type`; a code that does not belong to that channel's
    vocabulary is refused with `ERR_INTERFACE_MESSAGE_INVALID` (HTTP 422)."
    PRD §3.6: "Rejection sets `validation_status` to `REJECTED`, refreshes the
    channel's `rejected_message_count`, and populates `validation_error_code` — a
    field that is empty on every non-rejected message — with either
    `ERR_INTERFACE_MESSAGE_INVALID` or `ERR_INTERFACE_LATENCY_EXCEEDED` according
    to which condition failed."

    Design: Difficulty/transitive_cascade/r4_interface_message_rejection_two_hop_cascade
    """
    ctx = setup_interface_channel_in_validation()
    assert ctx["channel"]["status"] == "IN_MESSAGE_VALIDATION", "the channel entered message validation"

    message = get_success_data(api_client.receive_message(
        ctx["channel"]["id"],
        create_interface_message_payload(
            message_code="DICOM_STOW", direction="INBOUND", sent_utc="2026-09-01T00:00:00Z"
        ),
        interface_headers,
    ))

    read = validate_success(api.get_interface_message(message["id"], interface_headers), 200)
    assert read["validation_status"] == "REJECTED", (
        "hop 1: a code outside the channel's vocabulary cannot survive validation"
    )
    assert read["validation_error_code"] == "ERR_INTERFACE_MESSAGE_INVALID"


def test_rejecting_a_message_pulls_the_owning_channel_into_validation_failed(api, interface_headers):
    """PRD §3.6: "Rejection also cascades one level: if the owning channel is
    currently `IN_MESSAGE_VALIDATION`, the channel itself falls to
    `VALIDATION_FAILED`, which is the second link of the message-rejection
    cascade that begins with the message."
    PRD §3.6: "A channel that has fallen to `VALIDATION_FAILED` may be returned to
    `BUILDING`, which zeroes both counters so validation restarts cleanly."

    Design: Difficulty/transitive_cascade/r4_interface_message_rejection_two_hop_cascade
    """
    ctx = setup_interface_channel_in_validation()
    message = get_success_data(api_client.receive_message(
        ctx["channel"]["id"],
        create_interface_message_payload(
            message_code="DICOM_STOW", direction="INBOUND", sent_utc="2026-09-01T00:00:00Z"
        ),
        interface_headers,
    ))
    assert message["validation_status"] == "REJECTED"

    channel = validate_success(api.get_interface_channel(ctx["channel"]["id"], interface_headers), 200)
    assert channel["status"] == "VALIDATION_FAILED", (
        "hop 2: the channel falls because its message was rejected"
    )
    assert channel["rejected_message_count"] == 1

    returned = validate_success(api.return_channel_to_build(ctx["channel"]["id"], interface_headers), 200)
    assert returned["status"] == "BUILDING"
    assert returned["rejected_message_count"] == 0