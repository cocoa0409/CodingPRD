"""Listing, initial state and invalid transitions."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    get_success_data,
    setup_program,
    setup_program_and_facility,
    setup_program_facility_department,
    create_ticket,
    DIRECTOR,
    ANALYST,
    BUILD_ANALYST,
    COMMAND_CENTER,
)


# ===========================================================================
# c_command_center_tickets_list_paginates_with_total_count
# ===========================================================================

def test_ticket_collection_pages_with_a_filtered_total_count(api, director_headers, command_center_headers):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
    and `has_more` in the `meta` object of the envelope, whether or not the
    caller supplied pagination parameters."
    PRD §2.3: "List endpoints accept a `limit` query parameter giving the maximum
    number of items to return; when it is absent the value is 10, the minimum
    accepted value is 1, and the maximum accepted value is 100."

    Design: Corner/entities/c_command_center_tickets_list_paginates_with_total_count
    """
    prog, fac = setup_program_and_facility()
    create_ticket(fac["id"], severity="SEV3", at_the_elbow_zone="ED")
    create_ticket(fac["id"], severity="SEV4", at_the_elbow_zone="PHARMACY")
    create_ticket(fac["id"], severity="SEV2", at_the_elbow_zone="ICU")

    page_one, meta = validate_paginated(api.list_command_center_tickets(
        command_center_headers,
        params={"ehr_implementation_id": prog["id"], "facility_id": fac["id"],
                "limit": 2, "offset": 0},
    ))
    assert len(page_one) == 2
    assert meta["total_count"] == 3, "total_count counts the filtered set, not the page"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    page_two, meta_two = validate_paginated(api.list_command_center_tickets(
        command_center_headers,
        params={"facility_id": fac["id"], "limit": 2, "offset": 2},
    ))
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False


def test_ticket_collection_narrows_by_severity_and_defaults_its_page_size(api, director_headers, command_center_headers):
    """PRD §3.10: "Tickets are listable across the program and filterable by
    facility, department, linked defect, severity and triage state, and this is
    the one collection that also takes `limit` and `offset` among its declared
    query parameters."
    PRD §2.3: "A companion `offset` parameter gives the number of items to skip
    and defaults to 0."

    Design: Corner/entities/c_command_center_tickets_list_paginates_with_total_count
    """
    prog, fac = setup_program_and_facility()
    create_ticket(fac["id"], severity="SEV3", at_the_elbow_zone="ED")
    create_ticket(fac["id"], severity="SEV4", at_the_elbow_zone="PHARMACY")
    create_ticket(fac["id"], severity="SEV2", at_the_elbow_zone="ICU")

    narrowed, narrowed_meta = validate_paginated(api.list_command_center_tickets(
        command_center_headers, params={"facility_id": fac["id"], "severity": "SEV3"},
    ))
    assert len(narrowed) == 1
    assert narrowed_meta["total_count"] == 1

    all_rows, all_meta = validate_paginated(
        api.list_command_center_tickets(command_center_headers)
    )
    assert len(all_rows) == 3
    assert all_meta["limit"] == 10, "the absent limit defaults to 10"
    assert all_meta["offset"] == 0


# ===========================================================================
# c_new_department_starts_build_pending_with_closed_gate
# ===========================================================================

def test_a_fresh_department_opens_in_build_pending_with_a_closed_gate(api, build_analyst_headers):
    """PRD §3.3: "A new department begins in `BUILD_PENDING`, and its status
    vocabulary runs `BUILD_PENDING`, `BUILD_COMPLETE`, `TRAINING_IN_PROGRESS`,
    `READY_FOR_GO_LIVE`, `REMEDIATION_REQUIRED` and `LIVE`."
    PRD §3.4: "Staff in `REGISTERED`, `TRAINING_ASSIGNED`, `TRAINED` or
    `PROFICIENCY_FAILED` contribute nothing to the numerator while still counting
    in the denominator, so an untrained population drags the ratio down."

    Design: Corner/state_machines/c_new_department_starts_build_pending_with_closed_gate
    """
    prog, fac = setup_program_and_facility()
    created = validate_success(api_client.create_department(
        fac["id"],
        {"department_code": "ED", "application_scope": ["ED"], "required_staff_count": 8},
        build_analyst_headers,
    ), 201)

    assert created["status"] == "BUILD_PENDING"
    assert created["proficiency_cleared_count"] == 0
    assert created["proficiency_cleared_ratio"] == pytest.approx(0.00, abs=0.01)
    assert created["proficiency_gate_open"] is False


def test_a_fresh_department_carries_no_blocking_defects_and_echoes_its_inputs(api, build_analyst_headers):
    """PRD §3.3: "A `BuildAnalyst` creates a department under a facility,
    supplying its `department_code` — unique within that facility — its
    `application_scope`, a list of the application codes the department staffs,
    and its `required_staff_count`, which becomes the denominator of the
    proficiency gate in §3.4."
    PRD §3.3: "The owning department's `build_blocking_defect_count` is narrower —
    only open `SEV1` and `SEV2` defects belonging to the department's build items
    are counted".

    Design: Corner/state_machines/c_new_department_starts_build_pending_with_closed_gate
    """
    prog, fac = setup_program_and_facility()
    created = validate_success(api_client.create_department(
        fac["id"],
        {"department_code": "ED", "application_scope": ["ED"], "required_staff_count": 8},
        build_analyst_headers,
    ), 201)

    assert created["build_blocking_defect_count"] == 0
    assert created["department_code"] == "ED"
    assert created["application_scope"] == ["ED"]
    assert created["required_staff_count"] == 8
    assert created["facility_id"] == fac["id"]


# ===========================================================================
# c_facility_mark_validated_from_site_registered_returns_invalid_state
# ===========================================================================

def test_marking_a_still_registered_facility_validated_reports_invalid_state(api, director_headers):
    """PRD §3.2: "Configuring the build moves a registered facility to
    `BUILD_CONFIGURED` and requires only that the program's posture is `OPEN`."
    PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/state_machines/c_facility_mark_validated_from_site_registered_returns_invalid_state
    """
    prog, fac = setup_program_and_facility()

    refused = api.mark_validated(fac["id"], director_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_the_refused_validation_leaves_the_facility_registered(api, director_headers, analyst_headers):
    """PRD §3.2: "Marks of validation are deliberately demanding: a facility may
    be marked validated only when every one of its departments has an open
    proficiency gate".
    PRD §3.2: "The facility status vocabulary is `SITE_REGISTERED`,
    `BUILD_CONFIGURED`, `REMEDIATION_REQUIRED`, `VALIDATED`, `CUTOVER_READY`,
    `LIVE`, `STABILIZED` and `STABILIZATION_AT_RISK`."

    Design: Corner/state_machines/c_facility_mark_validated_from_site_registered_returns_invalid_state
    """
    prog, fac = setup_program_and_facility()
    api.mark_validated(fac["id"], director_headers)

    read = validate_success(api.get_facility(fac["id"], analyst_headers), 200)
    assert read["status"] == "SITE_REGISTERED"