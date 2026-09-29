"""
Two claims on one exclusive resource: a coverage window and a physical vial.

An authorization window may not touch another live window on the same plan, and a
single vial cannot back two live draft reservations at once.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_instant_equals, assert_vial_counters
from test_helpers import factories as f
from test_helpers.test_users import specialist_headers


# ==========================================================================
# authorization_windows_with_touching_endpoints_count_as_an_overlap
# ==========================================================================


def _second_submitted_authorization(depth):
    """Create and submit a renewal authorization on the already-authorized plan."""
    first = depth.pa1
    plan = depth.read_plan(depth.plan1["id"])
    second = depth.authorization(
        treatment_plan_id=plan["id"], expected_treatment_plan_version=plan["version"]
    )
    depth.submit_authorization(second["id"], clinical_justification="Continuation of therapy")
    return first, second


def test_a_renewal_beginning_on_the_incumbents_last_day_is_an_overlap(depth, billing):
    """
    A renewal whose `effective_date` is the incumbent's own `expiration_date` is
    refused, because the two closed windows share that endpoint.

    The PRD closes both intervals and forbids contact: "the coverage window this
    decision would create — the closed interval running from `effective_date`
    through `effective_date` advanced by the policy's `pa_validity_days` in whole
    days — may not overlap the equivalent interval of any *other* authorization on
    the same plan whose status is `APPROVED` or `EXHAUSTED`. Touching endpoints count
    as an overlap, so a new window must begin at least one full day after the
    previous window's last day; a collision is `ERR_AUTHORIZATION_WINDOW_OVERLAP`
    (HTTP 409)."  The incumbent runs from 2026-08-01 through 2027-01-28 on the
    default 180-day validity, so 2027-01-28 is the shared day.

    Design: Difficulty/resource_temporal_overlap/authorization_windows_with_touching_endpoints_count_as_an_overlap
    """
    first, second = _second_submitted_authorization(depth)
    assert_instant_equals(first["expiration_date"], "2027-01-28T00:00:00Z", "expiration_date")

    response = depth.api.decide_prior_authorization(
        second["id"],
        f.approval_decision_payload(
            auth_number="AUTH-1002",
            approved_injections=3,
            effective_date="2027-01-28T00:00:00Z",
        ),
        billing,
    )
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_WINDOW_OVERLAP, 409)

    assert depth.read_authorization(second["id"])["status"] == "SUBMITTED"


def test_a_renewal_starting_one_day_later_is_approved_and_leaves_the_incumbent_alone(
    depth, billing
):
    """
    Moving the renewal to the day after the incumbent's last day approves it with a
    fresh 180-day window and no effect on the authorization it follows.

    The same sentence supplies the tolerance — "a new window must begin at least one
    full day after the previous window's last day" — and the approval branch
    computes the new window: it "stores `auth_number`, `approved_injections` and
    `effective_date`, computes `expiration_date` as `effective_date` advanced by
    `pa_validity_days` whole days", so 2027-01-29 plus 180 days is 2027-07-28.  A
    fresh approval has consumed nothing, and the overlap rule only ever inspects
    "any *other* authorization on the same plan", so the incumbent is left exactly as
    it stood.

    Design: Difficulty/resource_temporal_overlap/authorization_windows_with_touching_endpoints_count_as_an_overlap
    """
    first, second = _second_submitted_authorization(depth)

    response = depth.api.decide_prior_authorization(
        second["id"],
        f.approval_decision_payload(
            auth_number="AUTH-1002",
            approved_injections=3,
            effective_date="2027-01-29T00:00:00Z",
        ),
        billing,
    )
    approved = validate_success(response, 200)

    assert approved["status"] == "APPROVED"
    assert approved["auth_number"] == "AUTH-1002"
    assert approved["injections_used"] == 0
    assert_instant_equals(approved["effective_date"], "2027-01-29T00:00:00Z", "effective_date")
    assert_instant_equals(approved["expiration_date"], "2027-07-28T00:00:00Z", "expiration_date")

    incumbent = depth.read_authorization(first["id"])
    assert incumbent["status"] == "APPROVED"
    assert incumbent["auth_number"] == first["auth_number"]
    assert incumbent["injections_used"] == 0
    assert_instant_equals(incumbent["expiration_date"], "2027-01-28T00:00:00Z", "expiration_date")


# ==========================================================================
# one_vial_cannot_back_two_overlapping_draft_reservations
# ==========================================================================


def _single_vial_contention(depth):
    """
    Stand up two open-access plans on the compounded product against a lot holding
    exactly one vial, book the first and return both plans plus that booking.
    """
    depth.policy(
        payer_id=depth.pay_np["id"],
        drug_id=depth.drug_cmp["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=1400,
        admin_allowed_cents=10000,
        pa_required=False,
    )
    lot = depth.lot(
        drug_id=depth.drug_cmp["id"],
        lot_number="CMP-3301",
        expiration_date="2027-03-31T00:00:00Z",
        received_date="2026-07-20T00:00:00Z",
        unit_acquisition_cost_cents=24000,
        vials_received=1,
    )
    built = []
    for patient, thickness in ((depth.pt3, 410), (depth.pt4, 395)):
        study = depth.imaging(
            clinician_id=depth.cl1["id"],
            patient_id=patient["id"],
            eye="OS",
            study_datetime=depth.CLOCK,
            central_subfield_thickness_um=thickness,
            subretinal_fluid=True,
        )
        plan = depth.plan(
            clinician_id=depth.cl1["id"],
            patient_id=patient["id"],
            drug_id=depth.drug_cmp["id"],
            eye="OS",
        )
        activated = depth.activate_plan(
            plan["id"], clinician_id=depth.cl1["id"], baseline_imaging_study_id=study["id"]
        )
        built.append((activated, study))

    (plan_a, study_a), (plan_b, study_b) = built
    encounter_a = depth.encounter(
        clinician_id=depth.cl1["id"],
        treatment_plan_id=plan_a["id"],
        imaging_study_id=study_a["id"],
        encounter_datetime="2026-08-01T09:00:00Z",
        expected_treatment_plan_version=plan_a["version"],
    )
    return lot, plan_a, encounter_a, plan_b, study_b


def test_the_second_patient_cannot_reserve_the_vial_the_first_is_holding(depth):
    """
    With one vial in the world and one draft already holding it, the second booking
    finds an empty eligible pool.

    Reservation removes the vial from the pool: "the vial moves `IN_STOCK →
    RESERVED` with `reserved_for_encounter_id` naming this encounter and
    `reserved_at` set to the logical clock", while the pool itself is "every vial
    whose own status is `IN_STOCK`" — so a reserved vial is no longer a candidate and
    "An empty pool is `ERR_NO_ELIGIBLE_VIAL` (HTTP 409)."  The rejected request
    leaves nothing behind: "no vial is ever reserved by a request that goes on to
    fail."

    Design: Difficulty/resource_temporal_overlap/one_vial_cannot_back_two_overlapping_draft_reservations
    """
    lot, _, encounter_a, plan_b, study_b = _single_vial_contention(depth)
    assert encounter_a["vial_id"] is not None

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan_b["id"],
            imaging_study_id=study_b["id"],
            encounter_datetime="2026-08-01T10:00:00Z",
            expected_treatment_plan_version=plan_b["version"],
        ),
        specialist_headers(depth.cl2["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VIAL, 409)

    held = depth.read_lot(lot["id"])
    assert_vial_counters(held, vials_reserved=1, vials_on_hand=0)

    unchanged = depth.read_plan(plan_b["id"])
    assert unchanged["version"] == plan_b["version"]


def test_releasing_the_first_reservation_hands_the_same_vial_to_the_second_patient(
    depth,
):
    """
    Voiding the first draft returns the vial to stock, and the retried booking
    reserves that identical vial while the failed attempt left the plan's version
    untouched.

    Voiding from `DRAFT` "releases the reservation. The vial moves `RESERVED →
    IN_STOCK`, both `reserved_for_encounter_id` and `reserved_at` are cleared to
    null, and the lot's counters are recomputed", and conservation guarantees it is
    the same physical row — "Whatever `vials_received` was booked in, exactly that
    many `Vial` rows exist for that lot forever; vials move between custody states
    but are never created, deleted or transferred to another lot."  The abandoned
    booking never consumed a dose, so "the plan's dose counters were never bumped and
    need no adjustment", and only the successful creation advances a version: "The
    plan's `version` advances by 1."

    Design: Difficulty/resource_temporal_overlap/one_vial_cannot_back_two_overlapping_draft_reservations
    """
    lot, plan_a, encounter_a, plan_b, study_b = _single_vial_contention(depth)

    validate_error(
        depth.api.create_injection_encounter(
            f.encounter_payload(
                treatment_plan_id=plan_b["id"],
                imaging_study_id=study_b["id"],
                encounter_datetime="2026-08-01T10:00:00Z",
                expected_treatment_plan_version=plan_b["version"],
            ),
            specialist_headers(depth.cl2["id"]),
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_VIAL,
        409,
    )

    validate_success(
        depth.api.void_injection_encounter(
            encounter_a["id"],
            f.void_payload(void_reason="Patient deferred treatment at the chair"),
            specialist_headers(depth.cl1["id"]),
        ),
        200,
    )

    response = depth.api.create_injection_encounter(
        f.encounter_payload(
            treatment_plan_id=plan_b["id"],
            imaging_study_id=study_b["id"],
            encounter_datetime="2026-08-01T10:00:00Z",
            expected_treatment_plan_version=plan_b["version"],
        ),
        specialist_headers(depth.cl2["id"]),
    )
    encounter_b = validate_success(response, 201)

    assert encounter_b["status"] == "DRAFT"
    assert encounter_b["vial_id"] == encounter_a["vial_id"]

    vial = depth.read_vial(encounter_b["vial_id"])
    assert vial["status"] == "RESERVED"
    assert vial["reserved_for_encounter_id"] == encounter_b["id"]

    settled = depth.read_lot(lot["id"])
    assert_vial_counters(settled, vials_reserved=1, vials_on_hand=0)
    assert settled["vials_received"] == 1

    abandoned = depth.read_plan(plan_a["id"])
    assert abandoned["injections_administered"] == 0

    advanced = depth.read_plan(plan_b["id"])
    assert advanced["version"] == plan_b["version"] + 1
