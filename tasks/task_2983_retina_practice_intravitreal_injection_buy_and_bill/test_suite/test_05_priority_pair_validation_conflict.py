"""
Requests that violate two rules at once, where the normative order decides which
error the caller sees.

The concurrency guard outranks the clinician-eligibility gate, and the injection
interval outranks the clinician's daily capacity.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_vial_counters
from test_helpers import factories as f
from test_helpers.test_users import admin_headers, specialist_headers


# ==========================================================================
# stale_plan_version_outranks_clinician_ineligibility_and_rejects_with_412
# ==========================================================================


def _suspended_injector(depth):
    """Stand up the authorized plan, then suspend the clinician who would inject."""
    depth.pa1
    depth.lot_ref
    suspended = validate_success(
        depth.api.suspend_clinician(
            depth.cl1["id"],
            f.clinician_suspend_payload(suspension_reason="Credentialing lapse"),
            admin_headers(),
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"


def test_a_stale_version_is_reported_even_though_the_injector_is_also_suspended(depth):
    """
    An encounter request that is both behind the plan's version and made by a
    suspended clinician reports the version mismatch at HTTP 412.

    The PRD numbers the guards and then draws the consequence: "`expected_treatment_plan_version`
    equals the plan's current `version` — otherwise `ERR_STALE_PLAN_VERSION` (412)"
    is step 12, while "The acting clinician is eligible to inject — otherwise
    `ERR_CLINICIAN_NOT_ELIGIBLE` (409)" is step 14, and "Because the stale-version
    guard (step 12) precedes every state and business check (steps 13 onward), a
    request that is both stale and pointed at an untreatable plan reports the
    version mismatch."  The plan was observed at version 2 before the authorization
    was created, and "A successful prior-authorization create itself advances the
    plan's `version`", so that observation is now stale.

    Design: Difficulty/priority_pair_validation_conflict/stale_plan_version_outranks_clinician_ineligibility_and_rejects_with_412
    """
    _suspended_injector(depth)
    stale_version = depth.plan1_active["version"]
    current = depth.read_plan(depth.plan1["id"])
    assert current["version"] != stale_version

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=depth.plan1["id"],
            imaging_study_id=depth.img1["id"],
            encounter_datetime=depth.ENCOUNTER_AT,
            expected_treatment_plan_version=stale_version,
        ),
        specialist_headers(depth.cl1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_PLAN_VERSION, 412)


def test_the_eligibility_gate_surfaces_only_once_the_version_matches(depth):
    """
    The same request with the plan's current version reports the suspended
    clinician instead, and neither attempt reserved a vial or moved a counter.

    The PRD makes suspension forward-looking but disqualifying: "a suspended
    clinician can no longer create a new encounter and can no longer serve as the
    second-clinician wastage attester", and the encounter rule states "The acting
    clinician must also be fit to inject — `status` `ACTIVE` and
    `injection_privilege` true — and a suspended or unprivileged clinician is
    refused with `ERR_CLINICIAN_NOT_ELIGIBLE` (HTTP 409)."  Nothing is consumed by
    either rejection: "the rejection happens before any vial is reserved, so no
    inventory is disturbed by a stale request", and "no vial is ever reserved by a
    request that goes on to fail".

    Design: Difficulty/priority_pair_validation_conflict/stale_plan_version_outranks_clinician_ineligibility_and_rejects_with_412
    """
    _suspended_injector(depth)
    stale_version = depth.plan1_active["version"]
    current = depth.read_plan(depth.plan1["id"])

    validate_error(
        depth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=depth.plan1["id"],
                imaging_study_id=depth.img1["id"],
                encounter_datetime=depth.ENCOUNTER_AT,
                expected_treatment_plan_version=stale_version,
            ),
            specialist_headers(depth.cl1["id"]),
        ),
        ApiErrorId.ERR_STALE_PLAN_VERSION,
        412,
    )

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=depth.plan1["id"],
            imaging_study_id=depth.img1["id"],
            encounter_datetime=depth.ENCOUNTER_AT,
            expected_treatment_plan_version=current["version"],
        ),
        specialist_headers(depth.cl1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLINICIAN_NOT_ELIGIBLE, 409)

    plan = depth.read_plan(depth.plan1["id"])
    assert plan["injections_administered"] == 0
    assert plan["last_encounter_id"] is None

    lot = depth.read_lot(depth.lot_ref["id"])
    assert_vial_counters(lot, vials_on_hand=5, vials_reserved=0)

    authorization = depth.read_authorization(depth.pa1["id"])
    assert authorization["injections_used"] == 0


# ==========================================================================
# interval_violation_outranks_day_capacity_and_is_rejected
# ==========================================================================


def _one_injection_by_the_capped_clinician(depth):
    """Have the once-a-day clinician give and document the plan's first injection."""
    depth.pa1
    depth.lot_ref
    plan = depth.read_plan(depth.plan1["id"])
    encounter = depth.encounter(
        clinician_id=depth.cl3["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=depth.img1["id"],
        encounter_datetime=depth.ENCOUNTER_AT,
        expected_treatment_plan_version=plan["version"],
    )
    depth.document(encounter["id"], clinician_id=depth.cl3["id"], administered_dose_ml=0.06)
    return encounter


def test_a_same_day_second_injection_reports_the_interval_not_the_capacity(depth):
    """
    Eleven hours after the first injection, a second booking by a clinician already
    at their daily cap reports the interval violation.

    Both rules are broken: the gap is 0 whole days against a 28-day floor, and the
    clinician's cap of one is already spent inside the closed 24-hour window.  The
    PRD orders them — "The gap since the plan's previous encounter is at least the
    effective drug's minimum interval — otherwise
    `ERR_INJECTION_INTERVAL_VIOLATION` (409)" is step 17 and "The acting clinician
    has capacity in the rolling day window — otherwise
    `ERR_CLINICIAN_DAY_CAPACITY_EXCEEDED` (409)" is step 18 — and the interval rule
    is inclusive only at its floor: "the whole days between that encounter's
    `encounter_datetime` and the requested one — truncated downward — must be at
    least the effective drug's `min_interval_days`".

    Design: Difficulty/priority_pair_validation_conflict/interval_violation_outranks_day_capacity_and_is_rejected
    """
    _one_injection_by_the_capped_clinician(depth)
    plan = depth.read_plan(depth.plan1["id"])

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=depth.img1["id"],
            encounter_datetime="2026-08-01T20:00:00Z",
            expected_treatment_plan_version=plan["version"],
        ),
        specialist_headers(depth.cl3["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INJECTION_INTERVAL_VIOLATION, 409)


def test_with_the_interval_satisfied_the_capacity_gate_is_the_one_that_fires(depth):
    """
    Four weeks later the same clinician has spent their single slot on another
    patient, so a booking that now clears the interval is refused for capacity.

    The window is the one the PRD describes: "a twenty-four-hour window that is
    **closed at both ends** and measured from the requested `encounter_datetime`
    rather than from the logical clock: it runs from that instant moved back
    twenty-four hours through that instant itself. Within it the server counts every
    non-`VOIDED` encounter belonging to the acting clinician across all patients and
    all plans, and requires that count to be strictly fewer than the clinician's
    `max_injections_per_day`."  The earlier injection is 28 days back, so step 17
    passes and step 18 is reached.  Nothing about the failed booking touches the
    plan, whose counters still reflect the single documented injection.

    Design: Difficulty/priority_pair_validation_conflict/interval_violation_outranks_day_capacity_and_is_rejected
    """
    first = _one_injection_by_the_capped_clinician(depth)
    depth.pol_np_ref
    depth.set_clock("2026-08-29T00:00:00Z")

    study_pt1 = depth.imaging(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt1["id"],
        eye="OD",
        study_datetime="2026-08-29T00:00:00Z",
        central_subfield_thickness_um=388,
        intraretinal_fluid=True,
    )
    study_pt3 = depth.imaging(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt3["id"],
        eye="OD",
        study_datetime="2026-08-29T00:00:00Z",
        central_subfield_thickness_um=402,
        intraretinal_fluid=True,
    )
    other_plan = depth.plan(
        clinician_id=depth.cl1["id"],
        patient_id=depth.pt3["id"],
        drug_id=depth.drug_ref["id"],
        eye="OD",
    )
    activated = depth.activate_plan(
        other_plan["id"],
        clinician_id=depth.cl1["id"],
        baseline_imaging_study_id=study_pt3["id"],
    )
    booked = depth.encounter(
        clinician_id=depth.cl3["id"],
        treatment_plan_id=other_plan["id"],
        imaging_study_id=study_pt3["id"],
        encounter_datetime="2026-08-29T08:00:00Z",
        expected_treatment_plan_version=activated["version"],
    )
    assert booked["status"] == "DRAFT"

    plan = depth.read_plan(depth.plan1["id"])
    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan["id"],
            imaging_study_id=study_pt1["id"],
            encounter_datetime="2026-08-29T09:00:00Z",
            expected_treatment_plan_version=plan["version"],
        ),
        specialist_headers(depth.cl3["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLINICIAN_DAY_CAPACITY_EXCEEDED, 409)

    unchanged = depth.read_plan(depth.plan1["id"])
    assert unchanged["injections_administered"] == 1
    assert unchanged["last_encounter_id"] == first["id"]

    authorization = depth.read_authorization(depth.pa1["id"])
    assert authorization["injections_used"] == 1
