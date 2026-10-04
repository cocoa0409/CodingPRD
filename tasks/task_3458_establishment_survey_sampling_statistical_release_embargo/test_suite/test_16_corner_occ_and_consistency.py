"""Corner coverage: optimistic concurrency and immediate consistency.

OCC on the program version at frame creation, OCC on the release version
at every release advance, and freeze results visible in the freeze
response itself with no settling delay.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_same_instant,
    create_cycle,
    create_frame,
    create_program,
    create_release,
    create_sample_frame_payload,
    create_stratum,
    get_program_version,
    postpone_release,
    release_advance_payload,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]


def test_occ_stale_program_version_on_frame_create(api):
    """PRD §2.7: "Creating a sample frame requires the request to carry `expected_program_version`, holding the `version` of the target `SurveyProgram` as the client last observed it. Because frame creation itself mutates program-level frame lineage — every successful frame creation increments the program's `version` by 1 — a client holding a stale reading would otherwise allocate against a program state it never observed. When `expected_program_version` does not equal the program's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_program_version_on_frame_create
    """
    set_clock("2026-09-01T00:00:00Z")
    program = create_program(code="CES", sample_budget=3)
    prog_v1 = program["version"]
    create_frame("CES", "2026-Q3",
                 strata=[create_stratum("MANUFACTURING", "SMALL", 100)])
    # F1's creation advanced the program past prog_v1.

    strata = [create_stratum("MANUFACTURING", "SMALL", 100)]
    resp = api_client.create_sample_frame(
        create_sample_frame_payload("CES", "2026-Q4", strata, prog_v1), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)  # 412

    prog_v2 = get_program_version("CES")
    assert prog_v2 == prog_v1 + 1
    f2 = validate_success(api_client.create_sample_frame(
        create_sample_frame_payload("CES", "2026-Q4", strata, prog_v2),
        ADMIN), 201)

    re_read = validate_success(api_client.get_sample_frame(f2["id"], ADMIN))
    assert re_read["reference_quarter"] == "2026-Q4", (
        "the rejected attempt created no frame; the retry's data is what "
        "reads back")


def test_occ_stale_release_version_on_reschedule(api):
    """PRD §2.7: "Every release advance action — `POSTPONE`, `RESCHEDULE`, `OPEN_EMBARGO`, `APPROVE_DISCLOSURE`, `REJECT_DISCLOSURE`, and `PUBLISH` — requires the request to carry `expected_release_version`, holding the `version` of the `ReleaseEvent` as the client last observed it. When the supplied value does not match the release's current `version`, the action is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.9: "`embargo_open_at` is snapshotted when the release is created, using the program's embargo window setting current at that moment, and it is recomputed afresh at every reschedule using the program's window setting current at the reschedule — not the value snapshotted at creation."

    Design: Corner/complexity_layers/occ_stale_release_version_on_reschedule
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cycle = create_cycle("CES", "2026-09")
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")
    rv1 = release["version"]

    postponed = postpone_release(release["id"])  # advances the version
    rv2 = postponed["version"]
    assert rv2 == rv1 + 1 and postponed["pub_status"] == "POSTPONED"

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload("RESCHEDULE", rv1,
                                new_release_at="2026-10-08T13:30:00Z"),
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)  # 412: stale view

    rescheduled = validate_success(api_client.advance_release(
        release["id"],
        release_advance_payload("RESCHEDULE", rv2,
                                new_release_at="2026-10-08T13:30:00Z"),
        RELEASE_MANAGER))
    assert rescheduled["pub_status"] == "SCHEDULED"
    assert_same_instant(rescheduled["embargo_open_at"],
                        "2026-10-08T13:00:00Z"), (
        "recomputed from the new release_at and the current 30-minute "
        "window")
    assert rescheduled["version"] == rv2 + 1


def test_immediate_consistency_mutation_visible_in_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.1: "On success, each stratum's `allocated_sample_size` is written, the frame's `total_sample_size` becomes their sum — always exactly equal to the `sample_budget` — and `frozen_at` records the current logical-clock reading."
    PRD §3.1: "each entry's `allocated_sample_size` stays null until a freeze computes it."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    frame = create_frame("CES", "2026-Q3",
                         strata=[create_stratum("MANUFACTURING", "SMALL",
                                                100)])
    assert frame["total_sample_size"] is None, (
        "allocation not computed on DRAFT")
    assert frame["strata"][0]["allocated_sample_size"] is None

    frozen = validate_success(api_client.freeze_sample_frame(
        frame["id"], ADMIN))
    assert frozen["frame_status"] == "FROZEN"
    assert frozen["total_sample_size"] == 3
    assert frozen["strata"][0]["allocated_sample_size"] == 3
    assert_same_instant(frozen["frozen_at"], "2026-09-01T00:00:00Z"), (
        "all visible in the freeze response itself — no re-read or "
        "settling delay")
