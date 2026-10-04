"""Clinical referrals: site selection, treatment windows, OCC, discharge cascades."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    validate_error, validate_success,
)
from test_helpers import factories, fixtures

INTAKE = TEST_USERS["intake_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_referral_window_closed_buffered(api):
    """PRD section 3.5: "The extended intervals are **closed**: they conflict
    when the new start falls on or before the existing extended end and the
    existing start falls on or before the new extended end — so a new window
    whose `treatment_start` lands exactly on another referral's buffered end
    still conflicts. Any conflict rejects the creation with
    `ERR_TREATMENT_WINDOW_CONFLICT` (HTTP 409)."
    PRD section 3.5: "First, if the member already has a referral in
    `PENDING_MATCH`, that referral is moved to `SUPERSEDED`."

    Design: Difficulty/resource_temporal_overlap/referral_window_closed_buffered
    """
    fixtures.reset_clock()
    member, track, enrollment = fixtures.setup_intensive_member(member_name="Ref Vet")

    version1 = fixtures.get_member_version(member["id"])
    ref1 = fixtures.create_referral(
        member["id"], expected_member_version=version1,
        treatment_start="2026-10-01T00:00:00Z", treatment_end="2026-11-10T00:00:00Z")
    assert ref1["status"] == "PENDING_MATCH", "no partner sites exist"

    version2 = fixtures.get_member_version(member["id"])
    conflict_resp = api.create_referral(
        factories.create_referral_payload(
            member["id"], version2,
            treatment_start="2026-11-17T00:00:00Z", treatment_end="2026-12-01T00:00:00Z"),
        INTAKE)
    validate_error(conflict_resp, ApiErrorId.ERR_TREATMENT_WINDOW_CONFLICT)

    ok_resp = api.create_referral(
        factories.create_referral_payload(
            member["id"], version2,
            treatment_start="2026-11-18T00:00:00Z", treatment_end="2026-12-01T00:00:00Z"),
        INTAKE)
    ref2 = validate_success(ok_resp, 201)
    assert ref2["status"] == "PENDING_MATCH", "2026-11-18 clears the 7-day buffer"

    referrals = {r["id"]: r for r in fixtures.list_referrals(member_id=member["id"])}
    assert referrals[ref1["id"]]["status"] == "SUPERSEDED"
    assert referrals[ref2["id"]]["status"] == "PENDING_MATCH"


def test_discharge_frees_slot_and_automatches_waiting_referral(api):
    """PRD section 3.5: "Discharge also decrements the site's `current_census`
    by 1 — and the freed slot is immediately offered to the eligible
    `PENDING_MATCH` referral with the smallest `request_seq`, where eligible
    means its `region` equals the freed site's `region` and its
    `required_specialty` appears in the site's `specialties`. That referral moves
    `PENDING_MATCH` → `MATCHED` to the freed site, with `partner_site_id` set,
    `matched_at` stamped, and the census incremented by 1"

    Design: Corner/state_machines/discharge_frees_slot_and_automatches_waiting_referral
    """
    fixtures.reset_clock()
    site = fixtures.create_partner_site(name="Southeast IOP", region="SE",
                                        specialties=("PTSD",), capacity=1)
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)

    member_x = fixtures.create_verified_member(full_name="Patient X")
    enrollment_x = fixtures.create_active_enrollment(member_x["id"], track["id"], (10, 10, 10, 10))
    refx = fixtures.create_referral(member_x["id"],
                                    treatment_start="2026-10-01T00:00:00Z",
                                    treatment_end="2026-11-10T00:00:00Z")
    assert refx["status"] == "MATCHED", "sole candidate, census 0 < 1"
    assert refx["partner_site_id"] == site["id"]
    fixtures.transition_referral(refx["id"], "ADMIT", site["id"])

    member_y = fixtures.create_verified_member(full_name="Patient Y")
    enrollment_y = fixtures.create_active_enrollment(member_y["id"], track["id"], (10, 10, 10, 10))
    refy = fixtures.create_referral(member_y["id"],
                                    treatment_start="2026-12-01T00:00:00Z",
                                    treatment_end="2026-12-20T00:00:00Z")
    assert refy["status"] == "PENDING_MATCH", "site census 1 == capacity 1"

    discharged = fixtures.transition_referral(refx["id"], "DISCHARGE", site["id"])
    assert discharged["status"] == "DISCHARGED"

    refy_after = fixtures.get_referral(refy["id"])
    assert refy_after["status"] == "MATCHED"
    assert refy_after["partner_site_id"] == site["id"]

    sites = {s["id"]: s for s in fixtures.list_partner_sites()}
    assert sites[site["id"]]["current_census"] == 1, "out with X, in with Y"


def test_referral_pending_match_expires_after_treatment_start(api):
    """PRD section 3.5: "A referral still in `PENDING_MATCH` is moved to
    `EXPIRED` by the clock sweep once the logical clock passes its
    `treatment_start`."
    PRD section 3.5: "a referral whose `partner_site_id` is still null falls
    through to the state check, and requesting either action from the wrong state
    is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/referral_pending_match_expires_after_treatment_start
    """
    fixtures.reset_clock()
    member, track, enrollment = fixtures.setup_intensive_member(member_name="Expire Vet")
    referral = fixtures.create_referral(
        member["id"], treatment_start="2026-10-01T00:00:00Z",
        treatment_end="2026-11-01T00:00:00Z")
    assert referral["status"] == "PENDING_MATCH"

    fixtures.set_clock("2026-10-01T00:00:01Z")
    assert fixtures.get_referral(referral["id"])["status"] == "EXPIRED"

    err_resp = api.transition_referral(
        referral["id"], factories.referral_transition_payload("ADMIT"),
        fixtures.make_clinical_partner_headers(NON_EXISTENT_UUID))
    validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE)


def test_site_selector_picks_lowest_occupancy_ratio(api):
    """PRD section 3.5: "Qualified candidates are ranked by occupancy — the
    exact rational ratio of `current_census` to `capacity`, compared without
    rounding — ascending; ties break by the site's `created_at` ascending and
    then by the site's `name` ascending; identifiers are never consulted."

    Design: Corner/calculations/site_selector_picks_lowest_occupancy_ratio
    """
    fixtures.reset_clock()
    site1 = fixtures.create_partner_site(name="Alpha IOP", region="SE",
                                         specialties=("PTSD",), capacity=10)
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)

    member_x = fixtures.create_verified_member(full_name="Occupant X")
    fixtures.create_active_enrollment(member_x["id"], track["id"], (10, 10, 10, 10))
    refx = fixtures.create_referral(member_x["id"],
                                    treatment_start="2026-10-01T00:00:00Z",
                                    treatment_end="2026-11-10T00:00:00Z")
    assert refx["partner_site_id"] == site1["id"], "sole candidate when X was referred"

    fixtures.set_clock("2026-09-01T00:00:01Z")
    site2 = fixtures.create_partner_site(name="Beta IOP", region="SE",
                                         specialties=("PTSD",), capacity=4)

    member_y = fixtures.create_verified_member(full_name="Selector Y")
    fixtures.create_active_enrollment(member_y["id"], track["id"], (10, 10, 10, 10))
    refy = fixtures.create_referral(member_y["id"],
                                    treatment_start="2026-12-01T00:00:00Z",
                                    treatment_end="2026-12-20T00:00:00Z")
    assert refy["status"] == "MATCHED"
    assert refy["partner_site_id"] == site2["id"], "ratio 0/4 beats 1/10 despite S1 being older"


def test_site_selector_tiebreak_earliest_created_at(api):
    """PRD section 3.5: "Qualified candidates are ranked by occupancy — the
    exact rational ratio of `current_census` to `capacity`, compared without
    rounding — ascending; ties break by the site's `created_at` ascending and
    then by the site's `name` ascending; identifiers are never consulted."

    Design: Corner/calculations/site_selector_tiebreak_earliest_created_at
    """
    fixtures.reset_clock()
    site1 = fixtures.create_partner_site(name="First IOP", region="SE",
                                         specialties=("PTSD",), capacity=4)
    fixtures.set_clock("2026-09-01T00:00:01Z")
    site2 = fixtures.create_partner_site(name="Second IOP", region="SE",
                                         specialties=("PTSD",), capacity=4)
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member = fixtures.create_verified_member(full_name="Tie Vet")
    fixtures.create_active_enrollment(member["id"], track["id"], (10, 10, 10, 10))

    referral = fixtures.create_referral(member["id"],
                                        treatment_start="2026-10-01T00:00:00Z",
                                        treatment_end="2026-11-01T00:00:00Z")
    assert referral["status"] == "MATCHED"
    assert referral["partner_site_id"] == site1["id"], "identical ratios, earliest created_at wins"

    sites = {s["name"]: s for s in fixtures.list_partner_sites()}
    assert sites["First IOP"]["current_census"] == 1
    assert sites["Second IOP"]["current_census"] == 0


def test_site_selector_empty_pool_stays_pending_match(api):
    """PRD section 3.5: "When no site qualifies the referral simply stays in
    `PENDING_MATCH` — this is not an error — with `partner_site_id` and
    `matched_at` null."

    Design: Corner/calculations/site_selector_empty_pool_stays_pending_match
    """
    fixtures.reset_clock()
    fixtures.create_partner_site(name="Depression Only IOP", region="SE",
                                 specialties=("DEPRESSION",), capacity=4)
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member = fixtures.create_verified_member(full_name="Pending Vet")
    fixtures.create_active_enrollment(member["id"], track["id"], (10, 10, 10, 10))

    resp = api.create_referral(
        factories.create_referral_payload(
            member["id"], fixtures.get_member_version(member["id"]),
            treatment_start="2026-10-01T00:00:00Z", treatment_end="2026-11-01T00:00:00Z"),
        INTAKE)
    referral = validate_success(resp, 201)
    assert referral["status"] == "PENDING_MATCH"
    assert referral["partner_site_id"] is None


def test_referral_requires_intensive_tier_rejected(api):
    """PRD section 3.5: "The member must hold an enrollment on a `MENTAL_HEALTH`
    track in `ACTIVE` or `SUSPENDED` whose `intensity_tier` is `INTENSIVE`;
    without one, creation is rejected with `ERR_INTENSITY_TIER_INSUFFICIENT`
    (HTTP 409)."

    Design: Corner/validations/referral_requires_intensive_tier_rejected
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member = fixtures.create_verified_member(full_name="Tier Vet")
    enrollment = fixtures.create_active_enrollment(member["id"], track["id"], (5, 5, 5, 5))
    assert enrollment["intensity_tier"] == "ENHANCED", "acuity 50 is below the INTENSIVE floor"

    err_resp = api.create_referral(
        factories.create_referral_payload(
            member["id"], fixtures.get_member_version(member["id"]),
            treatment_start="2026-10-01T00:00:00Z", treatment_end="2026-11-01T00:00:00Z"),
        INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_INTENSITY_TIER_INSUFFICIENT)
    assert fixtures.list_referrals(member_id=member["id"]) == []


def test_occ_referral_stale_member_version(api):
    """PRD section 2.6: "The request must likewise carry
    `expected_member_version` matching the target member's current `version`; a
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a new
    referral supersedes the member's existing `PENDING_MATCH` referral."

    Design: Corner/cross_cutting_layers/occ_referral_stale_member_version
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member = fixtures.create_member(full_name="Stale Vet")
    stale_version = member["version"]  # version 1, before verification/enrollment advance it
    verified = fixtures.verify_member(member)
    enrollment = fixtures.create_active_enrollment(verified["id"], track["id"], (10, 10, 10, 10))

    ref1 = fixtures.create_referral(member["id"],
                                    treatment_start="2026-10-01T00:00:00Z",
                                    treatment_end="2026-11-10T00:00:00Z")

    err_resp = api.create_referral(
        factories.create_referral_payload(
            member["id"], stale_version,
            treatment_start="2026-11-18T00:00:00Z", treatment_end="2026-12-01T00:00:00Z"),
        INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_STALE_VERSION)

    referrals = fixtures.list_referrals(member_id=member["id"])
    assert len(referrals) == 1, "the stale write did not supersede the standing referral"
    assert referrals[0]["id"] == ref1["id"]
    assert referrals[0]["status"] == "PENDING_MATCH"


def test_clinical_partner_cannot_discharge_other_sites_referral(api):
    """PRD section 3.5: "Both steps are driven by a `ClinicalPartner` and both
    are ownership-gated: the referral's `partner_site_id` must equal the caller's
    `X-User-ID`, otherwise `ERR_RESOURCE_NOT_OWNED`"

    Design: Corner/rbac/clinical_partner_cannot_discharge_other_sites_referral
    """
    fixtures.reset_clock()
    site1 = fixtures.create_partner_site(name="Home IOP", region="SE",
                                         specialties=("PTSD",), capacity=4)
    site2 = fixtures.create_partner_site(name="Far IOP", region="NW",
                                         specialties=("PTSD",), capacity=4)
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=10)
    member = fixtures.create_verified_member(full_name="Owned Vet")
    fixtures.create_active_enrollment(member["id"], track["id"], (10, 10, 10, 10))

    referral = fixtures.create_referral(member["id"],
                                        treatment_start="2026-10-01T00:00:00Z",
                                        treatment_end="2026-11-01T00:00:00Z")
    assert referral["partner_site_id"] == site1["id"], "the SE referral matched the SE site"
    fixtures.transition_referral(referral["id"], "ADMIT", site1["id"])

    err_resp = api.transition_referral(
        referral["id"], factories.referral_transition_payload("DISCHARGE"),
        fixtures.make_clinical_partner_headers(site2["id"]))
    validate_error(err_resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED)

    assert fixtures.get_referral(referral["id"])["status"] == "IN_TREATMENT"


def test_get_referral_with_unknown_id_returns_referral_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/entities/get_referral_with_unknown_id_returns_referral_not_found
    """
    fixtures.reset_clock()
    resp = api.get_referral(NON_EXISTENT_UUID, INTAKE)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_REFERRAL_NOT_FOUND"
    assert body["data"]["message"]
