"""
Consistency model: every derived field is already correct in the response that
caused it, and a request that fails a late gate applies nothing at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_vial_counters,
    validate_list,
)
from test_helpers import factories as f
from test_helpers.test_users import specialist_headers

SECOND_STUDY_AT = "2026-08-29T08:00:00Z"
SECOND_ENCOUNTER_AT = "2026-08-29T09:00:00Z"


def test_every_derived_field_is_already_correct_in_the_response_that_caused_it(breadth):
    """
    The create response already names the resolved product, the reserved vial and the
    empty lineage; the plan and the lot show the bump and the moved counters on the very
    next read; and the document response already carries the split and the modifiers
    while the vial ledger has already moved.

    Nothing in this API settles later.  "Several operations in this system mutate more
    than one entity, and the propagation is always immediate and fully applied within
    the request that triggered it — there is no deferred queue and no eventual
    convergence."  The create response is itself the record: "The acting specialist's
    identifier is stamped as `clinician_id`, and `patient_id` and `eye` are copied from
    the plan; none of the three may be supplied by the client. A new encounter is born
    in `DRAFT`", and before any drug-dependent check "the server resolves which product
    will really go into the eye, writing `effective_drug_id` and, when a swap occurred,
    `substituted_from_drug_id` (null otherwise)".  The inventory hop lands in the same
    request: "The winning vial's identifier is written to `vial_id`, the vial moves
    `IN_STOCK → RESERVED` with `reserved_for_encounter_id` naming this encounter and
    `reserved_at` set to the logical clock, and the lot's `vials_on_hand` and
    `vials_reserved` are recomputed."  So does the parent's: "`previous_encounter_id` is
    set to whatever the plan's `last_encounter_id` was at the moment of creation, and is
    null for a plan's first encounter", while "Creating an encounter legitimately
    mutates its plan — `last_encounter_id`, `current_interval_days`, `next_due_date` and
    `version` all move".  Documentation answers with its own arithmetic already done:
    "for a `SINGLE_DOSE` product, `wasted_ml` is the effective drug's `vial_fill_ml`
    less `administered_dose_ml`, rounded half up to three decimal places", "Only after
    both lines have been rounded are they added together to give
    `total_billed_billing_units`", "Position zero is always laterality: `RT` when the
    encounter's `eye` is `OD`, `LT` when it is `OS`. For a `SINGLE_DOSE` effective
    product a wastage modifier is appended second — `JW` when `wasted_billing_units` is
    greater than zero", and "The reserved vial moves `RESERVED → ADMINISTERED` and has
    `administered_at` stamped with the encounter's `encounter_datetime` — deliberately
    the clinical instant, not the logical clock".

    Design: Corner/consistency_model/corner_every_derived_field_is_already_correct_in_the_response_that_caused_it
    """
    breadth.pol_np_ref
    lot = breadth.lot_ref
    plan = breadth.plan_np_active
    version_before = plan["version"]

    created = breadth.enc_np

    assert created["status"] == "DRAFT"
    assert created["effective_drug_id"] == breadth.drug_ref["id"]
    assert created["substituted_from_drug_id"] is None
    assert created["clinician_id"] == breadth.cl1["id"]
    assert created["patient_id"] == breadth.pt_np["id"]
    assert created["eye"] == "OD"
    assert created["vial_id"] is not None, "The create response already names the reserved vial"
    assert created["previous_encounter_id"] is None
    assert created["interval_days_from_previous"] is None

    plan_after_create = breadth.read_plan(plan["id"])
    assert plan_after_create["version"] == version_before + 1
    assert plan_after_create["last_encounter_id"] == created["id"]

    lot_after_create = breadth.read_lot(lot["id"])
    assert_vial_counters(
        lot_after_create,
        vials_on_hand=4,
        vials_reserved=1,
        vials_administered=0,
    )

    documented = breadth.enc_np_documented
    assert documented["status"] == "DOCUMENTED"
    assert round(documented["wasted_ml"], 3) == 0.21
    assert documented["administered_billing_units"] == 2
    assert documented["wasted_billing_units"] == 8
    assert documented["total_billed_billing_units"] == 10
    assert documented["modifiers"] == ["RT", "JW"]

    vial = breadth.read_vial(created["vial_id"])
    assert vial["status"] == "ADMINISTERED"
    assert_instant_equals(vial["administered_at"], breadth.ENCOUNTER_AT, "administered_at")
    assert vial["reserved_for_encounter_id"] == created["id"]


def test_a_rejected_write_leaves_no_partial_state_behind(breadth, tech):
    """
    A second encounter create clears authentication, the plan's state and the
    optimistic-concurrency check and then fails on vial eligibility; the plan's version,
    last encounter and due date are exactly where they were, and no encounter row was
    born.

    A rejected multi-entity write applies nothing: "Where a cascade crosses an aggregate
    boundary the narrative in §3 names every hop, and an implementation must apply all
    of them or none."  The gate that fires is the last one in the create: "Last of all,
    and only once every preceding gate has passed, the server picks the physical vial.
    The eligible pool is every vial whose own status is `IN_STOCK`, whose lot's status is
    `AVAILABLE`, whose lot's `drug_id` is the encounter's `effective_drug_id`, and whose
    lot's `expiration_date` is strictly after the logical clock", and "An empty pool is
    `ERR_NO_ELIGIBLE_VIAL` (HTTP 409); no vial is ever reserved by a request that goes
    on to fail."  Its place in the order is fixed — "26. Vial selection finds at least
    one eligible vial — otherwise `ERR_NO_ELIGIBLE_VIAL` (409). Applies to
    injection-encounter creation" — which sits after the concurrency guard, so this
    request is genuinely one that got past the guard.  The bumps under test are declared
    as consequences of success alone: on a successful create "The plan's `version`
    advances by 1", and after documentation "`next_due_date` becomes the encounter's
    `encounter_datetime` advanced by the new interval in whole days while keeping the
    encounter's time of day ... and `last_encounter_id` points at the encounter just
    documented."  The single vial cannot come back: for vials, "`ADMINISTERED`,
    `RETURNED` and `EXPIRED` are terminal."

    Design: Corner/consistency_model/corner_a_rejected_write_leaves_no_partial_state_behind
    """
    breadth.pol_np_ref
    patient = breadth.pt_np
    clinician = breadth.cl1
    injector = specialist_headers(clinician["id"])

    single_vial_lot = breadth.lot(
        drug_id=breadth.drug_ref["id"],
        lot_number="RX-9500",
        expiration_date="2027-05-31T00:00:00Z",
        received_date="2026-07-08T00:00:00Z",
        unit_acquisition_cost_cents=130000,
        vials_received=1,
    )
    plan = breadth.plan_np_active

    first = breadth.encounter(
        clinician_id=clinician["id"],
        treatment_plan_id=plan["id"],
        imaging_study_id=breadth.img_np["id"],
        encounter_datetime=breadth.ENCOUNTER_AT,
        expected_treatment_plan_version=plan["version"],
    )
    breadth.document(
        first["id"],
        clinician_id=clinician["id"],
        administered_dose_ml=0.06,
        post_injection_iop_mmhg=16,
    )

    before = breadth.read_plan(plan["id"])
    consumed_lot = breadth.read_lot(single_vial_lot["id"])
    assert_vial_counters(
        consumed_lot,
        vials_on_hand=0,
        vials_reserved=0,
        vials_administered=1,
    )

    later_study = breadth.imaging(
        clinician_id=clinician["id"],
        patient_id=patient["id"],
        eye="OD",
        study_datetime=SECOND_STUDY_AT,
        central_subfield_thickness_um=405,
        intraretinal_fluid=True,
        subretinal_fluid=False,
        new_hemorrhage=False,
        va_letter_score=58,
    )

    validate_error(
        breadth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan["id"],
                imaging_study_id=later_study["id"],
                encounter_datetime=SECOND_ENCOUNTER_AT,
                expected_treatment_plan_version=before["version"],
            ),
            injector,
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_VIAL,
        409,
    )

    after = breadth.read_plan(plan["id"])
    assert after["version"] == before["version"], "The refused create bumped no version"
    assert after["last_encounter_id"] == before["last_encounter_id"]
    assert after["next_due_date"] == before["next_due_date"]
    assert after["injections_administered"] == before["injections_administered"]
    assert after["current_interval_days"] == before["current_interval_days"]

    rows, meta = validate_list(
        breadth.api.list_injection_encounters(
            injector, f.page_params(treatment_plan_id=plan["id"])
        )
    )
    assert meta["total_count"] == 1, "No encounter row is born by a refused create"
    assert [row["id"] for row in rows] == [first["id"]]

    settled_lot = breadth.read_lot(single_vial_lot["id"])
    assert_vial_counters(
        settled_lot,
        vials_on_hand=0,
        vials_reserved=0,
        vials_administered=1,
        vials_quarantined=0,
    )
    unchanged_vial = validate_success(
        breadth.api.get_vial(breadth.read_encounter(first["id"])["vial_id"], tech), 200
    )
    assert unchanged_vial["status"] == "ADMINISTERED"
