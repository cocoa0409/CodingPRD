"""Habitat treatments: seasonal windows, nesting blackout buffer, half-open
overlap semantics, posture gating, and the habitat priority scores.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_unit, create_treatment, start_and_complete_treatment,
    create_closure, activate_closure, get_unit_posture, advance_clock,
    create_treatment_payload,
)

BIO = TEST_USERS["biologist_headers"]


def test_habitat_score_breeding_vs_annual_diverge(api):
    """PRD §3.1: "For an identical set of completed treatments the two
    variants differ whenever any window touches the breeding season: one
    prescribed burn executed in March together with one invasive-control
    treatment executed in August yields a breeding-weighted score of 120
    against an annual score of 70."

    Design: Difficulty/dual_variant_calc/habitat_score_breeding_vs_annual_diverge
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    burn = create_treatment(
        unit["id"], treatment_type="PRESCRIBED_BURN",
        window_start="2027-03-10", window_end="2027-03-20")
    invasive = create_treatment(
        unit["id"], treatment_type="INVASIVE_CONTROL",
        window_start="2027-08-01", window_end="2027-08-10")
    start_and_complete_treatment(unit["id"], burn)
    start_and_complete_treatment(unit["id"], invasive)
    posture = get_unit_posture(unit["id"])
    assert posture["habitat_priority_breeding"] == 120, (
        f"breeding score must be 50 x 2 + 20 x 1 = 120, "
        f"got {posture['habitat_priority_breeding']}")
    assert posture["habitat_priority_annual"] == 70, (
        f"annual score must be 50 + 20 = 70, "
        f"got {posture['habitat_priority_annual']}")
    assert posture["habitat_priority_breeding"] != posture["habitat_priority_annual"]


def test_treatment_schedule_safety_beats_temporal(api):
    """PRD §2.6: "Every request passes through a single ordered validation
    cascade, and the first failing check determines the error returned; later
    checks are never consulted once an earlier one has fired."
    PRD §2.6: "Only after those six come the business rules, in their pinned
    sequence: (7) the nesting blackout buffer for prescribed burns
    (`ERR_NESTING_BLACKOUT`); (8) closure-posture gating of program creation
    and treatment starts (`ERR_POSTURE_CLOSED`); (9) determination finality
    (`ERR_DETERMINATION_NOT_FINAL`); (10) determination compatibility
    (`ERR_USE_INCOMPATIBLE`); (11) volunteer clearance for new assignments
    (`ERR_VOLUNTEER_NOT_CLEARED`); (12) agreement between a permit's use type
    and its determination's use type (`ERR_USE_TYPE_MISMATCH`); (13) one open
    bid per cooperator per offering (`ERR_DUPLICATE_BID`); (14) one active
    assignment per volunteer per program (`ERR_DUPLICATE_ASSIGNMENT`); (15)
    the program staffing ceiling (`ERR_PROGRAM_CAPACITY_EXCEEDED`); (16) the
    commercial filming day capacity (`ERR_COMMERCIAL_CAPACITY_EXCEEDED`);
    (17) unresolved comments at determination finalization
    (`ERR_UNRESOLVED_COMMENTS`); (18) date-range sanity
    (`ERR_DATE_RANGE_INVALID`); (19) windows and deadlines that would open in
    the past (`ERR_WINDOW_IN_PAST`); and (20) overlapping treatment windows
    on a unit (`ERR_TREATMENT_WINDOW_OVERLAP`)."

    Design: Difficulty/priority_pair_validation_conflict/treatment_schedule_safety_beats_temporal
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    create_closure(
        unit["id"], closure_type="NESTING", scope="FULL",
        start_date="2027-03-01", end_date="2027-06-30")
    create_treatment(
        unit["id"], treatment_type="WATER_MANIPULATION",
        window_start="2027-02-10", window_end="2027-02-28")
    resp = api_client.create_treatment(
        unit["id"],
        create_treatment_payload(
            treatment_type="PRESCRIBED_BURN",
            window_start="2027-02-12", window_end="2027-02-20"),
        BIO)
    validate_error(resp, ApiErrorId.ERR_NESTING_BLACKOUT)
    data, meta = validate_paginated(api_client.list_treatments(unit["id"], BIO))
    assert meta["total_count"] == 1, (
        f"the doubly-invalid burn must not be persisted; expected 1 "
        f"treatment on the unit, got {meta['total_count']}")


def test_burn_buffer_gap_semantics_against_nesting_window(api):
    """PRD §2.11: "Whenever the burn's window precedes or overlaps the
    closure's window, the request is rejected with `ERR_NESTING_BLACKOUT` if
    the burn's `window_end` falls later than fourteen days before the
    closure's `start_date`. A burn whose window ends exactly fourteen days
    before the closure begins satisfies the buffer; one day later violates
    it."

    Design: Difficulty/resource_temporal_overlap/burn_buffer_gap_semantics_against_nesting_window
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    create_closure(
        unit["id"], closure_type="NESTING", scope="FULL",
        start_date="2027-03-01", end_date="2027-06-30")
    rejected = api_client.create_treatment(
        unit["id"],
        create_treatment_payload(
            treatment_type="PRESCRIBED_BURN",
            window_start="2027-02-10", window_end="2027-02-20"),
        BIO)
    validate_error(rejected, ApiErrorId.ERR_NESTING_BLACKOUT)
    accepted = api_client.create_treatment(
        unit["id"],
        create_treatment_payload(
            treatment_type="PRESCRIBED_BURN",
            window_start="2027-02-01", window_end="2027-02-15"),
        BIO)
    burn = validate_success(accepted, 201)
    assert burn["status"] == "SCHEDULED", (
        "window_end exactly 14 days before the nesting start must satisfy "
        "the buffer")


def test_habitat_score_excludes_non_completed_treatments(api):
    """PRD §3.1: "Only treatments that have reached `COMPLETED` on the unit
    contribute; treatments in `SCHEDULED`, `WINDOW_OPEN`, `IN_PROGRESS`, or
    `EXPIRED` are excluded from both."

    Design: Corner/calculations/habitat_score_excludes_non_completed_treatments
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    burn = create_treatment(
        unit["id"], treatment_type="PRESCRIBED_BURN",
        window_start="2026-10-01", window_end="2026-10-05")
    invasive = create_treatment(
        unit["id"], treatment_type="INVASIVE_CONTROL",
        window_start="2026-10-10", window_end="2026-10-15")
    advance_clock("2026-10-06T00:00:00Z")
    start_and_complete_treatment(unit["id"], invasive)
    posture = get_unit_posture(unit["id"])
    assert posture["habitat_priority_annual"] == 20, (
        f"only the completed invasive control counts (20), "
        f"got {posture['habitat_priority_annual']}")
    assert posture["habitat_priority_breeding"] == 20, (
        f"the expired burn contributes nothing to either score, "
        f"got {posture['habitat_priority_breeding']}")
    data, meta = validate_paginated(api_client.list_treatments(
        unit["id"], BIO, params={"status": "EXPIRED"}))
    assert any(t["id"] == burn["id"] for t in data), (
        "the unexecuted burn must be observable with status EXPIRED")


def test_treatment_start_before_window_opens_rejected(api):
    """PRD §3.4: "Execution itself is a deliberate act: a `Biologist` or
    `RefugeManager` starts a `WINDOW_OPEN` treatment, moving it to
    `IN_PROGRESS` — but only while the unit's access posture at the current
    clock date is not `CLOSED`."

    Design: Corner/state_machines/treatment_start_before_window_opens_rejected
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    treatment = create_treatment(
        unit["id"], treatment_type="INVASIVE_CONTROL",
        window_start="2026-10-01", window_end="2026-10-10")
    assert treatment["status"] == "SCHEDULED"
    resp = api_client.start_treatment(treatment["id"], BIO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_treatment_window_in_past_rejected(api):
    """PRD §3.4: "The window must open in the future: a `window_start`
    earlier than the current clock date is rejected with
    `ERR_WINDOW_IN_PAST`."

    Design: Corner/validations/treatment_window_in_past_rejected
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    resp = api_client.create_treatment(
        unit["id"],
        create_treatment_payload(
            treatment_type="INVASIVE_CONTROL",
            window_start="2026-08-01", window_end="2026-08-10"),
        BIO)
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


def test_treatment_window_overlap_adjacency_vs_intersection(api):
    """PRD §3.4: "Independently, treatment windows on the same unit may not
    overlap: under the half-open semantics of §2.11, two windows that share
    only a boundary day — one `window_end` equal to the other's
    `window_start` — coexist, while any strict intersection is rejected with
    `ERR_TREATMENT_WINDOW_OVERLAP`."

    Design: Corner/errors/treatment_window_overlap_adjacency_vs_intersection
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    create_treatment(
        unit["id"], treatment_type="INVASIVE_CONTROL",
        window_start="2026-10-01", window_end="2026-10-15")
    adjacent = create_treatment(
        unit["id"], treatment_type="WATER_MANIPULATION",
        window_start="2026-10-15", window_end="2026-10-31")
    assert adjacent["status"] == "SCHEDULED", (
        "a window starting exactly at another's window_end is legal adjacency")
    resp = api_client.create_treatment(
        unit["id"],
        create_treatment_payload(
            treatment_type="WATER_MANIPULATION",
            window_start="2026-10-14", window_end="2026-10-20"),
        BIO)
    validate_error(resp, ApiErrorId.ERR_TREATMENT_WINDOW_OVERLAP)


def test_treatment_start_blocked_when_unit_closed(api):
    """PRD §2.11: "starting a treatment is rejected with `ERR_POSTURE_CLOSED`
    when the unit's posture at the current clock date is `CLOSED`, meaning an
    active full-scope closure covers that date."

    Design: Corner/validations/treatment_start_blocked_when_unit_closed
    """
    unit = create_unit(name="Prairie Unit", habitat_type="GRASSLAND", acreage=800)
    closure = create_closure(
        unit["id"], closure_type="MIGRATION", scope="FULL",
        start_date="2026-10-01", end_date="2026-10-31")
    treatment = create_treatment(
        unit["id"], treatment_type="INVASIVE_CONTROL",
        window_start="2026-10-10", window_end="2026-10-20")
    activate_closure(closure["id"])
    advance_clock("2026-10-10T00:00:00Z")
    resp = api_client.start_treatment(treatment["id"], BIO)
    validate_error(resp, ApiErrorId.ERR_POSTURE_CLOSED)
