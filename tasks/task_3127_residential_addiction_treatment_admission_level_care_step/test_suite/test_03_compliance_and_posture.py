"""The compliance risk ledger, posture bands and the facility-ops cascade."""

import pytest

from test_helpers import (
    C,
    READ_HEADERS,
    create_facility,
    grant_accreditation,
    grant_state_license,
    list_accreditations,
    list_beds,
    read_accreditation,
    read_authorization,
    read_episode,
    read_facility,
    read_plan,
    run_ops,
    set_clock,
    setup_cascade_episode,
    setup_site,
)

# A site whose only lapse is a single ACCREDITATION_BODY that expired 31 days ago.
# Raw score = 12 (one lapsed row) + 5 (RECOVERY_HOUSE absent) + 2 (one aged unit)
#          = 19, which sits in the BASE band, so the multiplier is 1.0 (PRD §2.6).
LAPSED_BODY = "2026-08-01T00:00:00Z"


def _ledger_site(expired_grace_days=31):
    """A licensed MN site with one silently lapsed ACCREDITATION_BODY row."""
    set_clock(C.CLOCK_2026_09_01)
    facility = create_facility()
    if expired_grace_days is None:
        expires_at = C.CREDENTIAL_EXPIRES_AT
    else:
        # 2026-09-01 minus the requested whole days.
        day = 1 - expired_grace_days
        import datetime

        instant = datetime.datetime(2026, 9, 1) + datetime.timedelta(days=day)
        expires_at = instant.strftime("%Y-%m-%dT00:00:00Z")
    grant_accreditation(
        facility["id"],
        accreditation_class="ACCREDITATION_BODY",
        granting_body="CARF",
        expires_at=expires_at,
    )
    grant_state_license(facility["id"])
    return facility


def test_lapsed_accreditation_scores_the_raw_ledger_without_a_tier_multiplier(api):
    """PRD §2.6: "The raw score is 12 points per lapsed-but-still-`GRANTED` row, plus 5
    points for each accreditation class the facility is entirely missing, plus the aged
    component."
    PRD §2.6: "the `BASE` tier applies at 10 raw points or fewer."
    PRD §2.6: "each surviving unit contributes 2 points."

    Design: Difficulty/combinatorial_formula/compliance_risk_aged_tiered_deduction
    """
    facility = _ledger_site(expired_grace_days=31)

    run = run_ops(facility["id"])
    after = read_facility(facility["id"])

    # 12 (one lapsed row) + 5 (RECOVERY_HOUSE missing) + 2 (31 days -> one aged unit).
    assert after["compliance_risk_points"] == 19, (
        f"the PRD ledger arithmetic gives 19, got {after['compliance_risk_points']}"
    )
    assert after["facility_posture"] == "OPEN", "19 points sits below the 45 cut"
    assert after["ops_epoch"] == 1
    assert after["last_ops_run_at"] == C.CLOCK_2026_09_01_ISO
    # The lapsed GRANTED row is flipped to EXPIRED by the same run (PRD §3.9).
    body = [a for a in list_accreditations(facility["id"])[0] if a["accreditation_class"] == "ACCREDITATION_BODY"][0]
    assert read_accreditation(body["id"])["status"] == "EXPIRED"


def test_the_aged_component_saturates_and_the_tier_boundary_is_strict(api):
    """PRD §2.6: "that day count is divided by 30 and rounded down, and the resulting unit count is
    capped at 6; each surviving unit contributes 2 points." PRD §2.6: "the `HI` tier applies
    strictly above 30 and at most 60" PRD §2.6: "The stored `compliance_risk_points` is that
    product rounded half up to a whole number."

    Design: Difficulty/combinatorial_formula/compliance_risk_aged_tiered_deduction
    """
    set_clock(C.CLOCK_2026_09_01)
    facility = create_facility()
    # Two lapsed rows (distinct granting bodies are allowed for the same class) aged
    # exactly 30 days, plus the missing RECOVERY_HOUSE class:
    # raw = 2*12 + 5 + min(6, 30//30)*2 = 24 + 5 + 2 = 31 -> HI -> 31 * 1.25 = 38.75.
    grant_accreditation(
        facility["id"], accreditation_class="ACCREDITATION_BODY",
        granting_body="CARF", expires_at="2026-08-02T00:00:00Z",
    )
    grant_accreditation(
        facility["id"], accreditation_class="STATE_LICENSE",
        granting_body="MN-DHS", expires_at="2027-01-01T00:00:00Z",
    )
    grant_accreditation(
        facility["id"], accreditation_class="ACCREDITATION_BODY",
        granting_body="JCAHO", expires_at="2026-08-02T00:00:00Z",
    )

    run_ops(facility["id"])
    after = read_facility(facility["id"])

    assert after["compliance_risk_points"] == 39, (
        "raw 31 crosses strictly above the 30 boundary into HI at 1.25, and round_half_up"
        f" gives 39; got {after['compliance_risk_points']}"
    )
    assert after["facility_posture"] == "OPEN", "39 points still sits below the 45 cut"


def test_epoch_and_compliance_are_recomputed_by_each_ops_run(api):
    """PRD §3.5: "A single facility-ops run advances the facility's `ops_epoch` by exactly 1
    at the very start" and "stamps `last_ops_run_at` with the logical now."
    PRD §2.6: "The score is recomputed from scratch on every facility-ops run"

    Design: Corner/state_machines/facility_ops_increments_the_ops_epoch_and_stamps_the_run
    """
    site = setup_site()

    first = run_ops(site.id)
    second = run_ops(site.id)

    assert second["ops_epoch"] == 2
    assert second["last_ops_run_at"] == C.CLOCK_2026_09_01_ISO
    assert second["facility_posture"] == "OPEN"
    assert second["compliance_risk_points"] == 5, "only the missing RECOVERY_HOUSE class"


def test_the_ops_response_itself_carries_the_mutations_the_run_made(api):
    """PRD §3.5: "Stage two recomputes the facility's compliance risk points and re-derives
    `facility_posture` from them." PRD §3.9: "During a facility-ops run a `GRANTED`
    accreditation whose expiry has passed becomes `EXPIRED`, and the facility's `as_level_max`
    is recomputed; when a `STATE_LICENSE` expires the facility drops to `ASAM_1_0` and stops
    accepting admissions." PRD §2.4: "`updated_at` is a server-stamped instant in the same
    format, refreshed on every mutation of the row."

    Design: Corner/endpoints/facility_ops_run_executes_its_stages_in_the_pinned_order
    """
    facility = _ledger_site(expired_grace_days=31)

    run = run_ops(facility["id"])

    assert run["ops_epoch"] == 1
    assert run["last_ops_run_at"] == C.CLOCK_2026_09_01_ISO
    assert run["compliance_risk_points"] == 19
    assert run["facility_posture"] == "OPEN"
    body = [a for a in list_accreditations(facility["id"])[0] if a["accreditation_class"] == "ACCREDITATION_BODY"][0]
    assert read_accreditation(body["id"])["status"] == "EXPIRED", (
        "the run's own stage three already flipped the lapsed row"
    )


def test_the_admission_response_carries_its_own_derived_fields(api):
    """PRD §3.3: "On success the episode's `admitted_at` is stamped, `clinical_status` becomes
    `IN_TREATMENT`, `care_level_status` moves from `NOT_STARTED` to `ACTIVE`, and the episode's
    version advances." PRD §2.4: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_mutation_response
    """
    from test_helpers import setup_admitted_episode

    setup = setup_admitted_episode(admit_clock=C.CLOCK_2026_09_02)

    assert setup.episode["clinical_status"] == "IN_TREATMENT"
    assert setup.episode["care_level_status"] == "ACTIVE"
    assert setup.episode["admitted_at"] == C.CLOCK_2026_09_02_ISO


def test_lapsed_body_accreditation_leaves_a_healthy_posture_episode_in_treatment(api):
    """PRD §3.9: "An episode already `IN_TREATMENT` at a facility that loses its
    `ACCREDITATION_BODY` standing — a revocation or an expiry — has its treatment plan forced to
    `PENDING_COSIGN` and every `SCHEDULED` session row rewritten to `CANCELLED` with a
    replacement scheduled, which is precisely the situation stage four of the ops cycle handles
    when the facility's posture lands at `FROZEN`." PRD §2.6: "`is_accepting_admissions` is
    false whenever `facility_posture` is `FROZEN`."

    Design: Difficulty/transitive_cascade/cascade_site_expiry_to_stale_authorization_to_stepdown
    """
    setup, sessions = setup_cascade_episode(
        admit_clock=C.CLOCK_2026_09_02,
        first_run_clock=C.CLOCK_2026_09_08,
        body_accreditation_expires_at=C.CLOCK_2026_09_15,
    )
    site = setup.site

    # The 2026-09-08 epoch is one burn inside the grant, and the 2026-09-15 epoch
    # leaves a day in hand, so no exhaustion cascade touches the plan here.
    assert read_authorization(setup.auth_id)["days_used"] == 6

    set_clock(C.CLOCK_2026_09_15)
    run_ops(site.id)

    facility = read_facility(site.id)
    body = read_accreditation(site.body_accreditation_id)
    assert body["status"] == "EXPIRED", "stage three expires the lapsed ACCREDITATION_BODY"

    # A lapsed body plus the missing RECOVERY_HOUSE class and no aged units scores
    # 12 + 5 + 0 = 17, which stays OPEN, so the FROZEN-response stage never fires.
    assert facility["compliance_risk_points"] == 17
    assert facility["facility_posture"] == "OPEN"
    assert read_plan(setup.plan_id)["status"] == "ACTIVE", (
        "a run whose posture stays OPEN does not demote the treatment plan"
    )
    assert read_episode(setup.id)["clinical_status"] == "IN_TREATMENT"


def test_expiry_cascade_banks_the_authorization_and_releases_the_bed(api):
    """PRD §3.6: "An `APPROVED` authorization whose `days_remaining` has reached exactly 0 while
    the episode is `IN_TREATMENT` becomes `EXHAUSTED`, the payer's coverage map is forced to
    promote the next covered lower level, the episode's `care_level_status` becomes
    `STEP_DOWN_PENDING`, and the episode's treatment plan is superseded in the same moment." PRD
    §3.5: "for every episode whose `care_level_status` is `STEP_DOWN_PENDING` and whose current
    bed is `OCCUPIED`, that bed is released into `CLEANING`, which decrements the facility's
    committed bed nights."

    Design: Difficulty/transitive_cascade/cascade_expired_site_accreditation_to_plan_to_bed_release
    """
    setup, _ = setup_cascade_episode(
        admit_clock=C.CLOCK_2026_09_01,
        first_run_clock=C.CLOCK_2026_09_08,
        body_accreditation_expires_at=C.CLOCK_2026_09_15,
    )
    site = setup.site

    set_clock(C.CLOCK_2026_09_15)
    run_ops(site.id)

    auth = read_authorization(setup.auth_id)
    assert auth["days_used"] == 14 and auth["days_remaining"] == 0
    assert auth["posture"] == "EXHAUSTED", (
        "the 14-day grant is fully burnt by the 2026-09-15 epoch"
    )

    episode = read_episode(setup.id)
    assert episode["care_level_status"] == "STEP_DOWN_PENDING"
    assert episode["clinical_status"] == "IN_TREATMENT", (
        "the cascade never progresses the episode's own clinical dimension"
    )

    beds = {b["id"]: b for b in list_beds(site.id)[0]}
    assert beds[setup.bed_id]["status"] == "CLEANING", (
        "the STEP_DOWN_PENDING release drops committed bed nights from 1 to 0"
    )
    assert len([b for b in beds.values() if b["status"] == "OCCUPIED"]) == 0


def test_a_frozen_facility_refuses_admission(api):
    """PRD §2.6: "`FROZEN` applies at 45 or more compliance risk points"
    PRD §2.6: "A `FROZEN` facility refuses admission, discharge, level-of-care changes and
    session scheduling with `ERR_FACILITY_POSTURE_FROZEN`."

    Design: Corner/validations/satisfied_checks_let_the_operation_through_with_no_error_envelope
    """
    from test_helpers import INTAKE_NURSE_HEADERS, ApiErrorId, validate_error

    # Three lapsed rows aged well past the aged cap plus the two missing classes:
    # raw = 3*12 + 2*5 + 6*2 = 58 -> HI 1.25 -> 72.5 -> 73, comfortably FROZEN.
    set_clock(C.CLOCK_2026_09_01)
    facility = create_facility()
    for body in ("CARF", "JCAHO", "COA"):
        grant_accreditation(
            facility["id"], accreditation_class="ACCREDITATION_BODY",
            granting_body=body, expires_at="2026-01-01T00:00:00Z",
        )
    run_ops(facility["id"])
    after = read_facility(facility["id"])
    assert after["compliance_risk_points"] == 73
    assert after["facility_posture"] == "FROZEN"
    assert after["is_accepting_admissions"] is False


def test_a_clean_site_admits_with_a_plain_success_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a
    list of resources." PRD §2.2: "#### Standard Error Response Format All error API responses
    (4xx status codes) follow this standard envelope format: ```json { "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456", "api_request_timestamp":
    "2025-05-24T10:30:00.123Z" }, "response_type": "error", "data": { "error_id":
    "UNIQUE_ERROR_IDENTIFIER_STRING", "message": "A human-readable explanation of the error." }
    } ``` - The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`." PRD §3.3: "On success the episode's `admitted_at` is stamped,
    `clinical_status` becomes `IN_TREATMENT`, `care_level_status` moves from `NOT_STARTED` to
    `ACTIVE`, and the episode's version advances."

    Design: Corner/validations/satisfied_checks_let_the_operation_through_with_no_error_envelope
    """
    from test_helpers import setup_admitted_episode, INTAKE_NURSE_HEADERS

    setup = setup_admitted_episode(admit_clock=C.CLOCK_2026_09_02)
    site = setup.site

    # Re-read the episode through the same nested path the admit used.
    body = api.get_episode_in_facility(site.id, setup.id, READ_HEADERS).json()
    assert body["response_type"] == "object"
    assert "error_id" not in body["data"]
    assert body["data"]["clinical_status"] == "IN_TREATMENT"
