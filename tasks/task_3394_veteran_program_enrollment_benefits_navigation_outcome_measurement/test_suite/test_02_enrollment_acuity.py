"""Program tracks, enrollment lifecycle, duplication avoidance, and acuity scoring."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    validate_error, validate_paginated, validate_success,
)
from test_helpers import factories, fixtures

INTAKE = TEST_USERS["intake_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_enrollment_create_with_unknown_track_returns_track_not_found(api):
    """PRD section 2.9: "Request-body foreign keys are likewise resolved in the
    order the endpoint's input list declares them."
    PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/enrollment_create_with_unknown_track_returns_track_not_found
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Orphan Vet")
    resp = api.create_enrollment(
        factories.create_enrollment_payload(member["id"], NON_EXISTENT_UUID), INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_TRACK_NOT_FOUND)
    assert fixtures.list_enrollments(member_id=member["id"]) == []


def test_enrollments_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
    of 100; `offset` defaults to 0. List responses are always sorted by
    `created_at` ascending. The `meta` object of every list response carries the
    four pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/enrollments_list_paginates_with_total_count_and_has_more
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    for name in ("Page One", "Page Two", "Page Three"):
        member = fixtures.create_verified_member(full_name=name)
        fixtures.create_enrollment(member["id"], track["id"])

    page1, meta1 = validate_paginated(
        api.list_enrollments(INTAKE, params={"program_track_id": track["id"], "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_enrollments(INTAKE, params={"program_track_id": track["id"], "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta_all = validate_paginated(api.list_enrollments(INTAKE))
    assert len(all_rows) == 3
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_track_capacity_boundary_count(api):
    """PRD section 3.2: "Third, the track's `active_enrollment_count` must be
    below its `capacity`; a full track rejects with `ERR_TRACK_CAPACITY_REACHED`
    (HTTP 409) — the boundary is inclusive-full, so a count equal to capacity
    rejects."

    Design: Difficulty/boundary_precision_check/track_capacity_boundary_count
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="PHYSICAL_HEALTH", capacity=2)
    members = [fixtures.create_verified_member(full_name=n)
               for n in ("Cap A", "Cap B", "Cap C")]

    resp_a = api.create_enrollment(
        factories.create_enrollment_payload(members[0]["id"], track["id"]), INTAKE)
    assert validate_success(resp_a, 201)["status"] == "INTAKE"
    resp_b = api.create_enrollment(
        factories.create_enrollment_payload(members[1]["id"], track["id"]), INTAKE)
    assert validate_success(resp_b, 201)["status"] == "INTAKE"

    err_resp = api.create_enrollment(
        factories.create_enrollment_payload(members[2]["id"], track["id"]), INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_TRACK_CAPACITY_REACHED)

    assert fixtures.get_track_by_code("PHYSICAL_HEALTH")["active_enrollment_count"] == 2
    assert fixtures.list_enrollments(member_id=members[2]["id"]) == []


def test_enrollment_referential_beats_fiscal(api):
    """PRD section 2.7: "When several checks could reject the same request, they
    are evaluated in a single fixed priority order, and the **first** failure
    wins."
    PRD section 3.2: "if the member holds an `ACTIVE` external service record
    whose `service_category` equals the target track's `track_code`, creation is
    rejected with `ERR_EXTERNAL_SERVICE_CONFLICT` (HTTP 409) unless
    `coordination_consent` is true"

    Design: Difficulty/priority_pair_validation_conflict/enrollment_referential_beats_fiscal
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=1)
    member_a = fixtures.create_verified_member(full_name="Dup A")
    fixtures.create_external_service_record(member_a["id"], service_category="MENTAL_HEALTH")
    member_b = fixtures.create_verified_member(full_name="Filler B")
    fixtures.create_enrollment(member_b["id"], track["id"])  # fills the only seat

    err_resp = api.create_enrollment(
        factories.create_enrollment_payload(member_a["id"], track["id"]), INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_EXTERNAL_SERVICE_CONFLICT)
    assert err_resp.status_code == 409
    assert err_resp.json()["data"]["error_id"] != "ERR_TRACK_CAPACITY_REACHED"

    assert fixtures.list_enrollments(member_id=member_a["id"]) == []
    assert fixtures.get_track_by_code("MENTAL_HEALTH")["active_enrollment_count"] == 1


def test_enrollment_intake_cannot_complete_rejected(api):
    """PRD section 3.2: "**Completion** (`ACTIVE` → `COMPLETED`)"
    PRD section 3.2: "Requesting an exit from an enrollment not in one of the
    listed source states is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/enrollment_intake_cannot_complete_rejected
    """
    fixtures.reset_clock()
    member = fixtures.create_verified_member(full_name="Skip Vet")
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    enrollment = fixtures.create_enrollment(member["id"], track["id"])

    err_resp = api.transition_enrollment(
        enrollment["id"], factories.enrollment_transition_payload("COMPLETED"), INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE)

    current = fixtures.get_enrollment(enrollment["id"])
    assert current["status"] == "INTAKE"
    assert current["exit_at"] is None
    surveys = fixtures.list_surveys(enrollment["id"])
    assert len(surveys) == 1, "only the BASELINE wave exists; no EXIT was scheduled"
    assert surveys[0]["wave"] == "BASELINE"


def test_engagement_graduated_only_via_completion(api):
    """PRD section 3.2: "it is `ENGAGED` while the member holds at least one
    enrollment in `INTAKE`, `ACTIVE`, or `SUSPENDED`; `GRADUATED` when no
    enrollment remains in those states and at least one sits in `COMPLETED`; and
    `INACTIVE` when none remain active and none are completed."
    PRD section 3.2: "**Withdrawal** (`INTAKE`, `ACTIVE`, or `SUSPENDED` →
    `WITHDRAWN`): the track count decrements by 1, **no** outcome surveys are
    created, and the member's engagement is re-derived."

    Design: Corner/state_machines/engagement_graduated_only_via_completion
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)

    member_w = fixtures.create_verified_member(full_name="Withdraw W")
    enrollment_w = fixtures.create_enrollment(member_w["id"], track["id"])
    member_c = fixtures.create_verified_member(full_name="Complete C")
    enrollment_c = fixtures.create_active_enrollment(member_c["id"], track["id"])

    fixtures.transition_enrollment(enrollment_w["id"], "WITHDRAWN")
    fixtures.complete_enrollment(enrollment_c["id"])

    assert fixtures.get_member(member_w["id"])["engagement_status"] == "INACTIVE"
    assert fixtures.get_member(member_c["id"])["engagement_status"] == "GRADUATED"
    assert fixtures.get_track_by_code("MENTAL_HEALTH")["active_enrollment_count"] == 0


def test_external_conflict_consent_override_allows_enrollment(api):
    """PRD section 3.2: "Second, duplication avoidance: if the member holds an
    `ACTIVE` external service record whose `service_category` equals the target
    track's `track_code`, creation is rejected with
    `ERR_EXTERNAL_SERVICE_CONFLICT` (HTTP 409) unless `coordination_consent` is
    true, recording the member's consent to coordinate with the other
    organization."

    Design: Corner/validations/external_conflict_consent_override_allows_enrollment
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_verified_member(full_name="Consent Vet")
    fixtures.create_external_service_record(member["id"], service_category="MENTAL_HEALTH")

    resp = api.create_enrollment(
        factories.create_enrollment_payload(member["id"], track["id"], coordination_consent=True),
        INTAKE)
    enrollment = validate_success(resp, 201)
    assert enrollment["status"] == "INTAKE"
    assert enrollment["coordination_consent"] is True

    records = fixtures.list_external_service_records(member["id"])
    assert records[0]["status"] == "ACTIVE", "consent does not close the external record"


def test_duplicate_track_code_rejected(api):
    """PRD section 3.2: "Each track has a `track_code` — one of `MENTAL_HEALTH`,
    `PHYSICAL_HEALTH`, `CAREER`, or `INDEPENDENCE` — which must be unique across
    all tracks (a duplicate is rejected with `ERR_DUPLICATE_TRACK_CODE`,
    HTTP 409)"

    Design: Corner/validations/duplicate_track_code_rejected
    """
    fixtures.reset_clock()
    fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    resp = api.create_program_track(
        factories.create_program_track_payload(track_code="MENTAL_HEALTH", name="Duplicate Track", capacity=3),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRACK_CODE)
    assert len(fixtures.list_program_tracks()) == 1


def test_acuity_weighted_branching_by_member_type(api):
    """PRD section 3.3: "For a `VETERAN`, the weights are psychological 0.4,
    physical 0.3, vocational 0.2, and social 0.1."
    PRD section 3.3: "For a `FAMILY_SUPPORT` member, the weights are
    psychological 0.5, physical 0.1, vocational 0.2, and social 0.2."
    PRD section 3.3: "The weighted sum of the four scores lies between 0 and 10;
    multiplying by 10 and rounding half-up to an integer under decimal arithmetic
    yields the `acuity_score`. The tier mapping is threshold-based: an acuity of
    at least 70 is `INTENSIVE`; an acuity of at least 40 but below 70 is
    `ENHANCED`; anything below 40 is `STANDARD`."

    Design: Difficulty/combinatorial_formula/acuity_weighted_branching_by_member_type
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    veteran = fixtures.create_verified_member(full_name="Vet A")
    family = fixtures.create_verified_member(
        full_name="Fam B", member_type="FAMILY_SUPPORT",
        injury_connection_claimed="NON_SERVICE_CONNECTED",
        verified_injury_connection="NON_SERVICE_CONNECTED")
    enrollment_a = fixtures.create_enrollment(veteran["id"], track["id"])
    enrollment_b = fixtures.create_enrollment(family["id"], track["id"])

    assessment_a = fixtures.add_assessment(enrollment_a["id"], 9, 3, 5, 6)
    assessment_b = fixtures.add_assessment(enrollment_b["id"], 9, 3, 5, 6)

    assert assessment_a["acuity_score"] == 61
    assert assessment_a["tier_result"] == "ENHANCED"
    assert assessment_b["acuity_score"] == 70
    assert assessment_b["tier_result"] == "INTENSIVE", "70 >= ACUITY_TIER_INTENSIVE_MIN is inclusive"

    enr_a = fixtures.get_enrollment(enrollment_a["id"])
    enr_b = fixtures.get_enrollment(enrollment_b["id"])
    assert enr_a["status"] == "ACTIVE" and enr_a["intensity_tier"] == "ENHANCED"
    assert enr_b["status"] == "ACTIVE" and enr_b["intensity_tier"] == "INTENSIVE"


def test_acuity_tier_boundary_40_inclusive(api):
    """PRD section 3.3: "The tier mapping is threshold-based: an acuity of at
    least 70 is `INTENSIVE`; an acuity of at least 40 but below 70 is `ENHANCED`;
    anything below 40 is `STANDARD`."

    Design: Corner/calculations/acuity_tier_boundary_40_inclusive
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member_hi = fixtures.create_verified_member(full_name="Boundary High")
    member_lo = fixtures.create_verified_member(full_name="Boundary Low")
    enrollment_hi = fixtures.create_enrollment(member_hi["id"], track["id"])
    enrollment_lo = fixtures.create_enrollment(member_lo["id"], track["id"])

    assessment_hi = fixtures.add_assessment(enrollment_hi["id"], 4, 4, 4, 4)
    assessment_lo = fixtures.add_assessment(enrollment_lo["id"], 4, 4, 4, 3)

    assert assessment_hi["acuity_score"] == 40
    assert assessment_hi["tier_result"] == "ENHANCED", "40 >= 40 inclusive"
    assert assessment_lo["acuity_score"] == 39
    assert assessment_lo["tier_result"] == "STANDARD"


def test_reassessment_replaces_tier_in_place(api):
    """PRD section 3.3: "Subsequent re-assessments on an `ACTIVE` or `SUSPENDED`
    enrollment simply recompute the tier in place and leave the status untouched."
    PRD section 3.3: "Every assessment writes its result back onto the
    enrollment: the enrollment's `intensity_tier` becomes the new `tier_result`,
    its `latest_acuity_score` becomes the new `acuity_score`, and the
    enrollment's `version` increments by 1."

    Design: Corner/cross_cutting_layers/reassessment_replaces_tier_in_place
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member = fixtures.create_verified_member(full_name="Reassess Vet")
    enrollment = fixtures.create_enrollment(member["id"], track["id"])
    fixtures.add_assessment(enrollment["id"], 9, 3, 5, 6)  # 61 -> ENHANCED, flips to ACTIVE

    second = fixtures.add_assessment(enrollment["id"], 10, 10, 10, 10)
    assert second["acuity_score"] == 100
    assert second["tier_result"] == "INTENSIVE"

    current = fixtures.get_enrollment(enrollment["id"])
    assert current["status"] == "ACTIVE", "re-assessment leaves the status untouched"
    assert current["intensity_tier"] == "INTENSIVE"
    assert current["latest_acuity_score"] == 100
    assert current["version"] == 3

    rows = fixtures.list_assessments(enrollment["id"])
    assert len(rows) == 2, "both assessments are retained"


def test_assessment_rows_carry_no_version(api):
    """PRD section 2.4: "Two resources are deliberately leaner: an `Assessment`
    and a `DonorReport` carry only `id` and `created_at`. Both `updated_at` and
    `version` are absent from those two resources"

    Design: Corner/entities/assessment_rows_carry_no_version
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_verified_member(full_name="Immutable Vet")
    enrollment = fixtures.create_enrollment(member["id"], track["id"])

    resp = api.create_assessment(
        enrollment["id"], factories.create_assessment_payload(6, 6, 6, 6), INTAKE)
    assessment = validate_success(resp, 201)
    assert assessment["id"]
    assert assessment["created_at"]
    assert "version" not in assessment
    assert "updated_at" not in assessment

    rows = fixtures.list_assessments(enrollment["id"])
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


def test_assessment_create_unknown_enrollment_returns_enrollment_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/assessment_create_unknown_enrollment_returns_enrollment_not_found
    """
    fixtures.reset_clock()
    resp = api.create_assessment(
        NON_EXISTENT_UUID, factories.create_assessment_payload(), INTAKE)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)
