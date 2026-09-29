"""Corner index — `endpoints` section.

Every test in this module translates exactly one live instance of the
`section: endpoints` slice of SCAFFOLD_CORNER_DESIGN.yaml, and names that
instance on the final `Design:` line of its docstring.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_version,
    assert_whole_cents,
    ids_of,
)

# ─── The bond arithmetic the design index pins ──────────────────────────
#
# Three stations of 1200 + 1500 + 1000 sqm give the parcel a
# `disturbed_area_sqm` of 3700. Against a posted bond of 1,000,000 cents the
# two remediation tasks below are worth
#   1000000 × 2000 / 3700 = 540540.54… → 540541 cents, and
#   1000000 × 1700 / 3700 = 459459.46… → 459459 cents,
# which sum back to the posted bond exactly.

_BOND_CENTS = 1000000
_DISTURBED_SQM = 3700
_TASK_A_SQM = 2000
_TASK_B_SQM = 1700
_SHARE_A_CENTS = 540541
_SHARE_B_CENTS = 459459


def _bond_world(api):
    """A permitted parcel with 3700 sqm disturbed and two PENDING tasks.

    Returns `(parcel, task_a, task_b)`.
    """
    parcel, _permit = fx.permitted_venue(
        api, venue_kwargs={"restoration_bond_cents": _BOND_CENTS}
    )
    fx.three_station_course(
        api,
        parcel["id"],
        station_kwargs=[
            {"difficulty_rating": 3, "footprint_sqm": 1200},
            {"difficulty_rating": 5, "footprint_sqm": 1500},
            {"difficulty_rating": 7, "footprint_sqm": 1000},
        ],
    )
    task_a = fx.restoration_task(
        api, parcel["id"], _TASK_A_SQM, task_type=constants.TASK_TYPE_DECOMPACT
    )
    task_b = fx.restoration_task(
        api, parcel["id"], _TASK_B_SQM, task_type=constants.TASK_TYPE_RESEED
    )
    return parcel, task_a, task_b


# ─── endpoints / the participant surface ────────────────────────────────


def test_enrolment_reads_back_unsigned_pending_and_flagless(api):
    """PRD §3.5: "Enrolment deliberately does not sign the waiver: a new participant reads `waiver_signed` of false, `clearance_status` of `PENDING` and an empty `medical_flags` array."

    Design: Corner/endpoints/the_participant_surface_creates_reads_and_filters_without_an_update
    """
    created = validate_success(
        api.create_participant(
            f.participant_payload(
                full_name="Ada Wren", birth_year=1994, email="ada.wren@example.com"
            ),
            users.OPS,
        ),
        expected_status=201,
    )
    assert created["waiver_signed"] is False
    assert created["clearance_status"] == constants.CLEARANCE_PENDING
    assert created["medical_flags"] == []
    assert_version(created, 1, "participant")

    # The read surface reports the very same enrolment state.
    fetched = fx.read_participant(api, created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["full_name"] == "Ada Wren"
    assert fetched["waiver_signed"] is False
    assert fetched["clearance_status"] == constants.CLEARANCE_PENDING
    assert fetched["medical_flags"] == []
    assert_version(fetched, 1, "participant")


def test_signing_the_waiver_moves_the_human_between_the_clearance_buckets(api):
    """PRD §3.5: "Participants may be listed with an optional filter on `clearance_status`, and one participant may be read to see waiver and clearance state."

    Design: Corner/endpoints/the_participant_surface_creates_reads_and_filters_without_an_update
    """
    human = fx.participant(api, full_name="Bo Rivers")

    pending_rows, pending_meta = validate_paginated(
        api.list_participants(
            users.OPS, params={"clearance_status": constants.CLEARANCE_PENDING}
        )
    )
    assert pending_meta["total_count"] == 1
    assert ids_of(pending_rows) == [human["id"]]

    _rows, cleared_meta = validate_paginated(
        api.list_participants(
            users.OPS, params={"clearance_status": constants.CLEARANCE_CLEARED}
        )
    )
    assert cleared_meta["total_count"] == 0

    signed = validate_success(
        api.sign_waiver(
            human["id"],
            f.waiver_payload(signature_name="Bo Rivers"),
            users.participant_headers(human["id"]),
        )
    )
    assert signed["waiver_signed"] is True
    assert signed["clearance_status"] == constants.CLEARANCE_CLEARED
    assert_version(signed, 2, "participant")

    # The same two filtered reads now report the opposite buckets.
    _rows, pending_after = validate_paginated(
        api.list_participants(
            users.OPS, params={"clearance_status": constants.CLEARANCE_PENDING}
        )
    )
    assert pending_after["total_count"] == 0

    cleared_rows, cleared_after = validate_paginated(
        api.list_participants(
            users.OPS, params={"clearance_status": constants.CLEARANCE_CLEARED}
        )
    )
    assert cleared_after["total_count"] == 1
    assert ids_of(cleared_rows) == [human["id"]]


# ─── endpoints / the passing inspection ─────────────────────────────────


def test_a_passing_inspection_books_the_tasks_pro_rata_bond_share(api):
    """PRD §3.9: "It computes that task's provisional bond share and writes it to `bond_release_cents`: the parcel's `restoration_bond_cents` multiplied by the task's `area_sqm`, divided by the parcel's `disturbed_area_sqm`, and rounded half up to whole cents."

    Design: Corner/endpoints/a_passing_inspection_verifies_the_task_and_books_its_bond_share
    """
    parcel, task_a, task_b = _bond_world(api)
    assert fx.read_venue(api, parcel["id"])["disturbed_area_sqm"] == _DISTURBED_SQM

    inspected = validate_success(
        api.inspect_restoration_task(
            task_a["id"],
            f.inspection_payload(
                constants.INSPECTION_VERIFIED,
                findings_note="Subsoil ripped to 300mm, no compaction left.",
            ),
            users.OFFICER,
        )
    )
    assert inspected["status"] == constants.TASK_VERIFIED
    assert inspected["inspection_rounds"] == 1
    assert_whole_cents(inspected["bond_release_cents"], "bond_release_cents")
    assert inspected["bond_release_cents"] == _SHARE_A_CENTS
    assert_version(inspected, 2, "restoration task")

    # The parcel ledger absorbs that exact amount, and stays conserved.
    settled_parcel = fx.read_venue(api, parcel["id"])
    assert settled_parcel["bond_released_cents"] == _SHARE_A_CENTS
    assert settled_parcel["bond_forfeited_cents"] == 0
    assert settled_parcel["bond_held_cents"] == _BOND_CENTS - _SHARE_A_CENTS
    assert_bond_ledger_conserved(settled_parcel)

    # The sibling task is untouched by its neighbour's inspection.
    sibling = fx.read_task(api, task_b["id"])
    assert sibling["status"] == constants.TASK_PENDING
    assert sibling["inspection_rounds"] == 0
    assert sibling["bond_release_cents"] == 0


def test_re_verifying_an_already_verified_task_is_refused_and_inert(api):
    """PRD §3.9: "An inspection whose outcome would not change the task's state — `VERIFIED` on a task already `VERIFIED`, or `REMEDIATION_REQUIRED` on a task already `REMEDIATION_REQUIRED` — is refused with `ERR_TASK_STATE_INVALID`."

    Design: Corner/endpoints/a_passing_inspection_verifies_the_task_and_books_its_bond_share
    """
    parcel, task_a, _task_b = _bond_world(api)
    fx.inspect(api, task_a["id"], constants.INSPECTION_VERIFIED)

    refused = api.inspect_restoration_task(
        task_a["id"],
        f.inspection_payload(constants.INSPECTION_VERIFIED),
        users.OFFICER,
    )
    validate_error(refused, ApiErrorId.ERR_TASK_STATE_INVALID.value, expected_status=409)

    # Neither the task's round counter nor the parcel ledger moved.
    task_after = fx.read_task(api, task_a["id"])
    assert task_after["status"] == constants.TASK_VERIFIED
    assert task_after["inspection_rounds"] == 1
    assert task_after["bond_release_cents"] == _SHARE_A_CENTS
    assert_version(task_after, 2, "restoration task")

    parcel_after = fx.read_venue(api, parcel["id"])
    assert parcel_after["bond_released_cents"] == _SHARE_A_CENTS
    assert parcel_after["bond_held_cents"] == _BOND_CENTS - _SHARE_A_CENTS
    assert_bond_ledger_conserved(parcel_after)


# ─── endpoints / progressive versus final settlement ────────────────────


def test_a_progressive_settlement_releases_only_the_verified_share(api):
    """PRD §3.9: "It recomputes the parcel's `bond_released_cents` as the sum of `bond_release_cents` over the remediation tasks currently reading `VERIFIED` — tasks reading `PENDING` or `REMEDIATION_REQUIRED` contribute nothing — leaves `bond_forfeited_cents` as it stands, and sets `bond_held_cents` to `restoration_bond_cents` minus `bond_released_cents` minus `bond_forfeited_cents`."

    Design: Corner/endpoints/progressive_settlement_is_allowed_where_final_settlement_is_not
    """
    parcel, task_a, task_b = _bond_world(api)
    fx.inspect(api, task_a["id"], constants.INSPECTION_VERIFIED)

    current = fx.read_venue(api, parcel["id"])
    settled = validate_success(
        api.create_bond_release(
            parcel["id"],
            f.bond_release_payload(
                current["version"], constants.SETTLEMENT_PROGRESSIVE
            ),
            users.OFFICER,
        )
    )
    # Only task A is VERIFIED, so only its share counts.
    assert settled["bond_released_cents"] == _SHARE_A_CENTS
    assert settled["bond_forfeited_cents"] == 0
    assert settled["bond_held_cents"] == _BOND_CENTS - _SHARE_A_CENTS
    assert_bond_ledger_conserved(settled)
    assert fx.read_task(api, task_b["id"])["status"] == constants.TASK_PENDING


def test_a_final_settlement_is_refused_while_one_task_is_unverified(api):
    """PRD §3.9: "It first demands that every remediation task on the parcel reads `VERIFIED` and that at least one such task exists; a parcel with an unverified task, or with no task at all, is refused with `ERR_RESTORATION_INCOMPLETE`."

    Design: Corner/endpoints/progressive_settlement_is_allowed_where_final_settlement_is_not
    """
    parcel, task_a, _task_b = _bond_world(api)
    fx.inspect(api, task_a["id"], constants.INSPECTION_VERIFIED)
    before = fx.read_venue(api, parcel["id"])

    refused = api.create_bond_release(
        parcel["id"],
        f.bond_release_payload(before["version"], constants.SETTLEMENT_FINAL),
        users.OFFICER,
    )
    validate_error(
        refused, ApiErrorId.ERR_RESTORATION_INCOMPLETE.value, expected_status=409
    )

    # The refusal leaves the parcel open and the ledger exactly as it was.
    after = fx.read_venue(api, parcel["id"])
    assert after["site_posture"] == constants.SITE_POSTURE_OPEN
    assert after["bond_released_cents"] == before["bond_released_cents"]
    assert after["bond_held_cents"] == before["bond_held_cents"]
    assert after["version"] == before["version"]

    # The same parcel accepts the PROGRESSIVE settlement the FINAL one refused.
    snapshot = validate_success(
        api.create_bond_release(
            parcel["id"],
            f.bond_release_payload(
                after["version"], constants.SETTLEMENT_PROGRESSIVE
            ),
            users.OFFICER,
        )
    )
    assert snapshot["bond_released_cents"] == _SHARE_A_CENTS
    assert snapshot["site_posture"] == constants.SITE_POSTURE_OPEN


# ─── endpoints / body references are scoped to the addressed course ─────


def test_a_paired_obstacle_on_a_sibling_course_does_not_resolve(api):
    """PRD §3.2: "An obstacle whose `paired_obstacle_id` names another obstacle on the same course is a **bypass lane** that relieves that primary station; a `paired_obstacle_id` that does not resolve on the addressed course is refused with `ERR_OBSTACLE_NOT_FOUND`."

    Design: Corner/endpoints/body_references_must_belong_to_the_path_courses_own_station_set
    """
    parcel = fx.venue(api)
    course_a = fx.course(api, parcel["id"], name="North Gauntlet")
    station_on_a = fx.obstacle(api, course_a["id"], 1, difficulty_rating=4)

    course_b = fx.course(
        api, parcel["id"], name="South Gauntlet", total_distance_m=4000
    )
    fx.obstacle(api, course_b["id"], 1, difficulty_rating=4)

    refused = api.create_obstacle(
        course_b["id"],
        f.obstacle_payload(
            2,
            name="South Bypass Lane",
            difficulty_rating=2,
            lane_count=2,
            service_rate_per_min=4.00,
            marshals_required=1,
            footprint_sqm=300,
            penalty_seconds=0,
            paired_obstacle_id=station_on_a["id"],
        ),
        users.DESIGNER,
    )
    validate_error(
        refused, ApiErrorId.ERR_OBSTACLE_NOT_FOUND.value, expected_status=404
    )

    # Nothing was placed: the sibling course still carries its single station.
    assert fx.read_course(api, course_b["id"])["obstacle_count"] == 1
    rows, meta = validate_paginated(
        api.list_obstacles(users.DESIGNER, params={"course_id": course_b["id"]})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) != [station_on_a["id"]]

    # The same reference resolves when it names a station on the addressed course.
    lane = fx.obstacle(
        api,
        course_a["id"],
        2,
        name="North Bypass Lane",
        difficulty_rating=2,
        lane_count=2,
        service_rate_per_min=4.00,
        marshals_required=1,
        footprint_sqm=300,
        penalty_seconds=0,
        paired_obstacle_id=station_on_a["id"],
    )
    assert lane["paired_obstacle_id"] == station_on_a["id"]
