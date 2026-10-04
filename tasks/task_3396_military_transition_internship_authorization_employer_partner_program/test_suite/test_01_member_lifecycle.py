"""Member intake: registration defaults, the logical clock, TAP sequencing,
schema gates, and OCC-protected member record updates."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_instant,
    factories,
    fixtures,
    make_employer_rep_headers,
    make_service_member_headers,
)
from test_helpers.test_users import TRANSITION_COUNSELOR_HEADERS


def test_member_registration_defaults_and_clock_recompute(api):
    """PRD §3.1: "A freshly registered member starts with `service_status` set to
    `ACTIVE_DUTY`, `tap_stage` set to `TAP_NOT_STARTED`, and `active_match_count` at 0."
    PRD §3.1: "Each member record also exposes `days_until_separation`, computed as
    the whole days from the logical clock date to `separation_date` at date
    precision; the value turns negative once the member has separated."
    PRD §2.4: "Before any clock-setting call has been made, the logical clock starts
    at exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock."

    Design: Corner/entities/member_defaults_and_logical_clock_computed_fields
    """
    inst = fixtures.create_installation(api)
    created = get_success_data(
        api.create_service_member(
            factories.create_service_member_payload(home_installation_id=inst["id"]),
            TRANSITION_COUNSELOR_HEADERS,
        ),
        201,
    )
    assert created["service_status"] == "ACTIVE_DUTY"
    assert created["tap_stage"] == "TAP_NOT_STARTED"
    assert created["active_match_count"] == 0
    assert isinstance(created["version"], int) and created["version"] >= 1
    # 2027-01-15 is 136 whole days after the default clock date 2026-09-01.
    assert created["days_until_separation"] == 136
    assert_instant(created["created_at"], "2026-09-01T00:00:00Z", "created_at")

    fixtures.set_clock(api, "2026-09-16T00:00:00Z")
    moved = fixtures.get_member(api, created["id"])
    assert moved["days_until_separation"] == 121, (
        f"days_until_separation must recompute against the moved clock: {moved['days_until_separation']}"
    )


def test_schema_gate_rejects_bad_enum_and_missing_fields(api):
    """PRD §2.7: "Required fields are present, types are correct, enum values are
    in range, and conditional requirements hold: a `decision` of DENY requires a
    `reason`; `location_type` of `ON_SITE` requires a `region_code`; `offer_accepted`
    of true requires `offer_made` of true; `learning_objectives` must be non-empty
    with unique objective codes and positive `weight_hours`; a `variant` of COHORT
    requires both cohort dates; `objectives_achieved` and `objectives_excused` must
    be disjoint; a wage record's `period_start_date` must not fall after its
    `period_end_date`."
    PRD §2.7: "Any failure is `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/invalid_enum_and_missing_required_fields_rejected
    """
    inst = fixtures.create_installation(api)
    employer = fixtures.create_authorized_employer(api)

    bad_branch = api.create_service_member(
        factories.create_service_member_payload(
            full_name="Bad Branch", service_branch="SPACE_MARINES", home_installation_id=inst["id"]
        ),
        TRANSITION_COUNSELOR_HEADERS,
    )
    validate_error(bad_branch, ApiErrorId.ERR_VALIDATION)

    no_capacity = api.create_opening(
        {
            "employer_id": employer["id"],
            "title": "No Capacity",
            "required_skills": ["LOGISTICS"],
            "location_type": "REMOTE",
        },
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(no_capacity, ApiErrorId.ERR_VALIDATION)

    onsite_no_region = api.create_opening(
        factories.create_opening_payload(
            employer["id"], title="Onsite No Region", location_type="ON_SITE", capacity=1
        ),
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(onsite_no_region, ApiErrorId.ERR_VALIDATION)


def test_tap_stage_skip_rejected(api):
    """PRD §3.1: "A counselor advances `tap_stage` by submitting a `target_stage`,
    and the target must be exactly the next stage in the fixed order —
    `TAP_NOT_STARTED` to `PRESEPARATION_COUNSELING_DONE`, then
    `CORE_CURRICULUM_DONE`, then `CAPSTONE_DONE`. Skipping ahead or naming any other
    target is rejected with `ERR_TAP_SEQUENCE_VIOLATION`; there is no regression
    transition."

    Design: Corner/state_machines/tap_stage_skip_rejected
    """
    inst = fixtures.create_installation(api)
    member = fixtures.create_member(api, inst["id"])

    skip = api.tap_advance(
        member["id"], {"target_stage": "CORE_CURRICULUM_DONE"}, TRANSITION_COUNSELOR_HEADERS
    )
    validate_error(skip, ApiErrorId.ERR_TAP_SEQUENCE_VIOLATION)

    advanced = fixtures.tap_advance(api, member["id"], "PRESEPARATION_COUNSELING_DONE")
    assert advanced["tap_stage"] == "PRESEPARATION_COUNSELING_DONE"


def test_separated_member_cannot_apply_or_advance(api):
    """PRD §3.2: "The member must still be `ACTIVE_DUTY` — `ERR_MEMBER_NOT_ON_ACTIVE_DUTY`."
    PRD §3.1: "Advancement requires the member to still be `ACTIVE_DUTY`, otherwise
    `ERR_MEMBER_NOT_ON_ACTIVE_DUTY`, and each successful advance increments the
    member's `version` by 1."
    PRD §2.7 lists the active-duty check (rung 8) ahead of the eligibility-window
    check (rung 15), so the state error surfaces even though 0 days until
    separation would also fail the window.

    Design: Corner/validations/separated_member_cannot_apply
    """
    inst = fixtures.create_installation(api)
    member = fixtures.create_member(api, inst["id"], full_name="Short Timer", separation_date="2026-09-20")

    sweep = fixtures.set_clock(api, "2026-09-20T00:00:00Z")
    assert sweep["members_separated"] == 1

    apply_resp = api.create_application(
        factories.create_application_payload(member["id"]),
        make_service_member_headers(member["id"]),
    )
    validate_error(apply_resp, ApiErrorId.ERR_MEMBER_NOT_ON_ACTIVE_DUTY)

    tap_resp = api.tap_advance(
        member["id"], {"target_stage": "PRESEPARATION_COUNSELING_DONE"}, TRANSITION_COUNSELOR_HEADERS
    )
    validate_error(tap_resp, ApiErrorId.ERR_MEMBER_NOT_ON_ACTIVE_DUTY)


def test_patch_member_stale_version_rejected(api):
    """PRD §2.6: "Updating a service member's record requires
    `expected_service_member_version`, carrying the client's last observed `version`
    of that ServiceMember. If another writer has advanced the member's version since
    the client last read it, the update is rejected with `ERR_STALE_VERSION`
    (HTTP 412), because a `separation_date` edit in particular re-validates every
    non-terminal match of the member and must never apply on top of a record the
    caller has not re-read."

    Design: Corner/cross_cutting_layers/occ_stale_member_version_on_patch
    """
    inst = fixtures.create_installation(api)
    member = fixtures.create_member(api, inst["id"])
    observed_version = member["version"]

    first = validate_success(
        api.patch_service_member(
            member["id"],
            {"expected_service_member_version": observed_version, "skills": ["LOGISTICS", "CDL"]},
            TRANSITION_COUNSELOR_HEADERS,
        )
    )
    assert first["version"] == observed_version + 1
    assert first["skills"] == ["LOGISTICS", "CDL"]

    stale = api.patch_service_member(
        member["id"],
        {"expected_service_member_version": observed_version, "pay_grade": "E6"},
        TRANSITION_COUNSELOR_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    after = fixtures.get_member(api, member["id"])
    assert after["pay_grade"] == "E5", "the loser's write must be discarded"
    assert after["version"] == first["version"]


def test_patch_separation_date_stranding_match_rejected(api):
    """PRD §3.1: "A `separation_date` change re-validates every non-terminal match
    the member holds: each such match's `end_date` must still fall on or before the
    new separation date minus a 7-day buffer, or the update is rejected with
    `ERR_SEPARATION_DATE_CONFLICT` and nothing is written."

    The patch target 2026-11-05 leaves the buffer boundary at 2026-10-29, which the
    in-flight match's end_date 2026-10-31 exceeds, so the conflict genuinely fires.

    Design: Corner/validations/separation_date_patch_conflict
    """
    ns = fixtures.setup_match(api)  # PROPOSED match [2026-10-01, 2026-10-31)
    member_id = ns.member["id"]
    before = fixtures.get_member(api, member_id)

    conflict = api.patch_service_member(
        member_id,
        {"expected_service_member_version": before["version"], "separation_date": "2026-11-05"},
        TRANSITION_COUNSELOR_HEADERS,
    )
    validate_error(conflict, ApiErrorId.ERR_SEPARATION_DATE_CONFLICT)

    after = fixtures.get_member(api, member_id)
    assert after["separation_date"].startswith("2027-01-15"), "no partial write may land"
    assert after["version"] == before["version"]
