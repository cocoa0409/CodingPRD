"""Enrollment activation cascade, checklist lifecycle, and OCC tests."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_checklist_to_section,
    create_enrollment_for_lab,
    create_laboratory,
    create_section_for_enrollment,
    get_success_data,
    make_director_headers,
    register_checklist_edition,
    setup_lab_with_active_enrollment,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


def test_enrollment_initial_state_is_waiting_until_first_checklist(api):
    """PRD §3.1: "A new enrollment begins in `WAITING` status with both
    standing fields, `standing_per_event` and `standing_rolling`, reading
    `SATISFACTORY` and an `unsuccessful_event_streak` of zero."
    PRD §3.1: "If this assignment is the one that leaves the enrollment with
    zero `UNASSIGNED` sections while the enrollment was `WAITING`, the
    enrollment cascades to `ACTIVE` as part of the same write; and if the
    laboratory was still `APPLIED`, that same write further cascades the
    laboratory to `ENROLLED`."

    Design: Corner/state_machines/enrollment_initial_state_is_waiting_until_first_checklist
    """
    lab = create_laboratory(name="Init Lab", clia_number="45D1000010")
    enr = create_enrollment_for_lab(lab["id"], "HEMATOLOGY")
    assert enr["status"] == "WAITING"
    lab_before = get_success_data(api.get_laboratory(lab["id"], OFFICER))
    assert lab_before["accreditation_status"] == "APPLIED"

    sec = create_section_for_enrollment(enr["id"], lab["id"], section_name="CBC")
    register_checklist_edition("HEM", "2026")
    assign_checklist_to_section(
        sec["id"], "HEM", "2026", expected_enrollment_version=enr["version"])

    sec_after = get_success_data(api.get_section(sec["id"], OFFICER))
    assert sec_after["checklist_status"] == "ASSIGNED"
    assert sec_after["checklist_code"] == "HEM"
    assert sec_after["checklist_version"] == "2026"
    enr_after = get_success_data(api.get_enrollment(enr["id"], OFFICER))
    assert enr_after["status"] == "ACTIVE"
    lab_after = get_success_data(api.get_laboratory(lab["id"], OFFICER))
    assert lab_after["accreditation_status"] == "ENROLLED"
    assert lab_after["active_discipline_count"] == 1


def test_enrollment_duplicate_discipline_rejected(api):
    """PRD §3.1: "Each laboratory may hold at most one enrollment per
    discipline; a second enrollment in the same discipline for the same
    laboratory is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/entities/enrollment_duplicate_discipline_rejected
    """
    lab1 = create_laboratory(name="Dup Lab One", clia_number="45D1000003")
    lab2 = create_laboratory(name="Dup Lab Two", clia_number="45D1000004")
    create_enrollment_for_lab(lab1["id"], "CHEMISTRY")

    resp_dup = api.create_enrollment(
        {"laboratory_id": lab1["id"], "discipline": "CHEMISTRY"},
        make_director_headers(lab1["id"]))
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value, 409)

    resp_ok = api.create_enrollment(
        {"laboratory_id": lab2["id"], "discipline": "CHEMISTRY"},
        make_director_headers(lab2["id"]))
    validate_success(resp_ok, expected_status=201)


def test_assign_checklist_on_assigned_section_rejected(api):
    """PRD §3.1: "The section must currently be `UNASSIGNED` — attempting to
    assign a section whose `checklist_status` is already `ASSIGNED` is rejected
    with `ERR_CHECKLIST_ALREADY_ASSIGNED`"

    Design: Corner/state_machines/assign_checklist_on_assigned_section_rejected
    """
    ctx = setup_lab_with_active_enrollment()
    sec = ctx["sections"][0]
    resp = api.assign_checklist(
        sec["id"], {"checklist_code": "CHM", "checklist_version": "2026"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_ALREADY_ASSIGNED.value, 409)
    sec_after = get_success_data(api.get_section(sec["id"], OFFICER))
    assert sec_after["checklist_status"] == "ASSIGNED"
    assert sec_after["checklist_code"] == "CHM"
    assert sec_after["checklist_version"] == "2026"


def test_checklist_edition_retirement_invalidates_and_reassign_restores(api):
    """PRD §3.1: "When it does, every section whose `checklist_code` matches
    the family, whose pinned `checklist_version` equals the retired edition,
    and whose `checklist_status` is `ASSIGNED` flips automatically to
    `CHECKLIST_INVALIDATED`, and the edition summary's `retired_count` records
    how many sections were invalidated."
    PRD §3.1: "An invalidated section may be re-assigned through the same
    assignment action — assignment from `CHECKLIST_INVALIDATED` is permitted as
    long as the parent enrollment is not `CEASED`"

    Design: Corner/state_machines/checklist_edition_retirement_invalidates_and_reassign_restores
    """
    ctx = setup_lab_with_active_enrollment()
    sec = ctx["sections"][0]
    enr = ctx["enrollment"]

    edition = get_success_data(api.create_checklist_edition(
        {"checklist_code": "CHM", "checklist_version": "2027",
         "retires_checklist_version": "2026"}, OFFICER))
    assert edition["retired_count"] == 1

    sec_mid = get_success_data(api.get_section(sec["id"], OFFICER))
    assert sec_mid["checklist_status"] == "CHECKLIST_INVALIDATED"
    enr_mid = get_success_data(api.get_enrollment(enr["id"], OFFICER))
    assert enr_mid["status"] == "ACTIVE"

    reassigned = assign_checklist_to_section(sec["id"], "CHM", "2027")
    assert reassigned["checklist_status"] == "ASSIGNED"
    assert reassigned["checklist_version"] == "2027"


def test_occ_stale_version_on_first_checklist_assignment(api):
    """PRD §2.9: "When the parent enrollment is `WAITING`, the assignment
    request must carry `expected_enrollment_version` equal to the enrollment's
    current `version`. If another writer has advanced the enrollment's version
    since the client last read it, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/validations/occ_stale_version_on_first_checklist_assignment
    """
    lab = create_laboratory(name="Occ Lab", clia_number="45D1000034")
    enr = create_enrollment_for_lab(lab["id"], "CHEMISTRY")
    sec = create_section_for_enrollment(enr["id"], lab["id"], section_name="S1")
    register_checklist_edition("CHM", "2026")

    resp = api.assign_checklist(
        sec["id"],
        {"checklist_code": "CHM", "checklist_version": "2026",
         "expected_enrollment_version": enr["version"] + 1},
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    # The correct version succeeds and activates the enrollment.
    ok = assign_checklist_to_section(sec["id"], "CHM", "2026",
                                     expected_enrollment_version=enr["version"])
    assert ok["checklist_status"] == "ASSIGNED"
    enr_after = get_success_data(api.get_enrollment(enr["id"], OFFICER))
    assert enr_after["status"] == "ACTIVE"


def test_subresource_list_returns_children_of_parent(api):
    """PRD §4: "GET | `/laboratories/{labId}/enrollments` | List a laboratory's
    enrollments"
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources
    sorted by `created_at` in ascending order."

    Design: Corner/endpoints/subresource_list_returns_children_of_parent
    """
    lab1 = create_laboratory(name="Sub Lab A", clia_number="45D1000038")
    lab2 = create_laboratory(name="Sub Lab B", clia_number="45D1000039")
    create_enrollment_for_lab(lab1["id"], "CHEMISTRY")
    create_enrollment_for_lab(lab2["id"], "MOLECULAR")

    resp = api.list_laboratory_enrollments(lab1["id"], OFFICER)
    data = get_success_data(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["laboratory_id"] == lab1["id"]
    assert rows[0]["discipline"] == "CHEMISTRY"
