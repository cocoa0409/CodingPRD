"""Queue A: resource_temporal_overlap — half-open vs closed interval rules."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_applicant, make_reference_product, make_application, make_facility,
    schedule_inspection, make_protected_indication,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


def test_inspection_half_open_overlap_allows_adjacency():
    """PRD section 3.6: "Adjacency is allowed: a new window starting on the
    very day another window ends does not conflict." and "A genuine collision
    is rejected with `ERR_INSPECTION_OVERLAP` (HTTP 409)." The occupied window
    is the half-open interval [scheduled_start_date, scheduled_end_date).

    Design: Difficulty/resource_temporal_overlap/inspection_half_open_overlap_allows_adjacency
    """
    applicant = make_applicant(legal_name="Overlap Generics")
    rld = make_reference_product(brand_name="Overlapix")
    app = make_application(rld["id"], applicant["id"])
    facility = make_facility(applicant["id"], facility_name="Overlap Plant")
    schedule_inspection(facility["id"], app["id"],
                        scheduled_start_date="2026-09-10",
                        scheduled_end_date="2026-09-12")

    adjacent = api_client.create_inspection({
        "facility_id": facility["id"], "application_id": app["id"],
        "scheduled_start_date": "2026-09-12", "scheduled_end_date": "2026-09-14"},
        REVIEWER)
    created = validate_success(adjacent, 201)
    assert created["status"] == "SCHEDULED", (
        "start == existing end does not collide under half-open semantics")

    straddling = api_client.create_inspection({
        "facility_id": facility["id"], "application_id": app["id"],
        "scheduled_start_date": "2026-09-11", "scheduled_end_date": "2026-09-13"},
        REVIEWER)
    validate_error(straddling, ApiErrorId.ERR_INSPECTION_OVERLAP)
    assert straddling.status_code == 409, "a one-day interior collision conflicts"


def test_protection_window_closed_overlap_rejects_adjacency():
    """PRD section 3.2: "Adjacency therefore counts as conflict — a new window
    whose `effective_from` is exactly the existing window's `protected_until`
    is rejected with `ERR_INDICATION_WINDOW_OVERLAP` (HTTP 409). `EXPIRED`
    windows never block new registrations." The rule is scoped per
    (reference_product_id, indication_code).

    Design: Difficulty/resource_temporal_overlap/protection_window_closed_overlap_rejects_adjacency
    """
    rld = make_reference_product(brand_name="Protectin",
                                 indication_codes=["IND-A", "IND-B"],
                                 patent_owner_user_id="innovator-ops-17")
    make_protected_indication(rld["id"], indication_code="IND-A",
                              effective_from="2026-01-01", protected_until="2028-01-01")

    adjacent = api_client.create_protected_indication(rld["id"], {
        "indication_code": "IND-A", "effective_from": "2028-01-01",
        "protected_until": "2029-06-30"}, ADMIN)
    validate_error(adjacent, ApiErrorId.ERR_INDICATION_WINDOW_OVERLAP)
    assert adjacent.status_code == 409, "closed intervals treat shared endpoints as overlap"

    with_gap = api_client.create_protected_indication(rld["id"], {
        "indication_code": "IND-A", "effective_from": "2028-01-02",
        "protected_until": "2029-06-30"}, ADMIN)
    validate_success(with_gap, 201)

    other_code = api_client.create_protected_indication(rld["id"], {
        "indication_code": "IND-B", "effective_from": "2027-06-01",
        "protected_until": "2027-12-31"}, ADMIN)
    validate_success(other_code, 201)
