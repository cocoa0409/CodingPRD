"""
Lifecycles that are not a single forward line.

The authorization re-enters `SUBMITTED` from `INFO_REQUESTED` and reaches
`APPROVED` from `APPEALED`, and the claim carries two status axes that leave
`PENDING` together and then advance one at a time.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assert_instant_equals
from test_helpers import factories as f


# ==========================================================================
# authorization_cycles_info_requested_denial_appeal_to_approved
# ==========================================================================


def _draft_authorization(depth):
    """Create one authorization against the freshly activated plan."""
    depth.pol_comm_ref
    plan = depth.plan1_active
    return depth.authorization(
        treatment_plan_id=plan["id"], expected_treatment_plan_version=plan["version"]
    )


def test_an_information_request_returns_the_authorization_to_submitted_and_counts_again(
    depth, billing
):
    """
    A payer that asks for more information sends the authorization back through
    `SUBMITTED`, replacing the narrative, clearing the request and taking the
    submission count to 2.

    The PRD makes the cycle explicit: a decision of `INFO_REQUESTED` "stores it
    while moving the authorization to `INFO_REQUESTED` — which the specialist
    answers by resubmitting, so `SUBMITTED` and `INFO_REQUESTED` may cycle as many
    times as the payer keeps asking".  The resubmission is not identical to the
    first: "A resubmission out of `INFO_REQUESTED` does slightly more: it
    *replaces* `clinical_justification` with the new narrative, clears
    `information_requested` back to null, recomputes
    `step_therapy_failures_documented` against whatever the history now shows, and
    again increases `submission_count` by 1."

    Design: Difficulty/non_linear_state_machine/authorization_cycles_info_requested_denial_appeal_to_approved
    """
    pa = _draft_authorization(depth)
    assert pa["status"] == "DRAFT"
    assert pa["submission_count"] == 0

    first = depth.submit_authorization(pa["id"])
    assert first["status"] == "SUBMITTED"
    assert first["submission_count"] == 1

    asked = validate_success(
        depth.api.decide_prior_authorization(
            pa["id"],
            f.info_requested_decision_payload(information_requested="Send the prior OCT series"),
            billing,
        ),
        200,
    )
    assert asked["status"] == "INFO_REQUESTED"
    assert asked["information_requested"] == "Send the prior OCT series"

    again = depth.submit_authorization(
        pa["id"], clinical_justification="Prior OCT series attached as requested"
    )
    assert again["status"] == "SUBMITTED"
    assert again["submission_count"] == 2
    assert again["information_requested"] is None
    assert again["clinical_justification"] == "Prior OCT series attached as requested"
    assert again["step_therapy_failures_documented"] == 0


def test_an_approval_out_of_appealed_clears_the_denial_and_dates_the_window(depth, billing):
    """
    A denied authorization that is appealed and then approved keeps no trace of the
    denial and carries a window 180 days long.

    The PRD closes the loop on the approval branch: it "stores `auth_number`,
    `approved_injections` and `effective_date`, computes `expiration_date` as
    `effective_date` advanced by `pa_validity_days` whole days, and clears any
    `denial_reason` back to null — which is equally true whether the approval
    arrived from `SUBMITTED` or from `APPEALED`, closing the denial-and-appeal
    cycle."  The policy leaves `pa_validity_days` at its default, and "`pa_validity_days`
    defaults to 180", so an `effective_date` of 2026-08-01 expires 2027-01-28.  A
    fresh approval has consumed nothing: "`injections_used` is defined as the count
    of non-`VOIDED` injection encounters whose `prior_authorization_id` names this
    authorization."

    Design: Difficulty/non_linear_state_machine/authorization_cycles_info_requested_denial_appeal_to_approved
    """
    pa = _draft_authorization(depth)
    depth.submit_authorization(pa["id"])
    validate_success(
        depth.api.decide_prior_authorization(
            pa["id"], f.info_requested_decision_payload(), billing
        ),
        200,
    )
    depth.submit_authorization(pa["id"], clinical_justification="Prior OCT series attached")

    denied = validate_success(
        depth.api.decide_prior_authorization(
            pa["id"], f.denial_decision_payload(denial_reason="NOT_MEDICALLY_NECESSARY"), billing
        ),
        200,
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "NOT_MEDICALLY_NECESSARY"
    assert denied["approved_injections"] is None

    appealed = validate_success(
        depth.api.appeal_prior_authorization(
            pa["id"], f.authorization_appeal_payload(appeal_basis="Bilateral exudative activity"), billing
        ),
        200,
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_basis"] == "Bilateral exudative activity"

    approved = validate_success(
        depth.api.decide_prior_authorization(
            pa["id"],
            f.approval_decision_payload(
                auth_number="AUTH-902", approved_injections=3, effective_date="2026-08-01T00:00:00Z"
            ),
            billing,
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert approved["auth_number"] == "AUTH-902"
    assert approved["approved_injections"] == 3
    assert approved["denial_reason"] is None
    assert approved["injections_used"] == 0
    assert_instant_equals(approved["effective_date"], "2026-08-01T00:00:00Z", "effective_date")
    assert_instant_equals(approved["expiration_date"], "2027-01-28T00:00:00Z", "expiration_date")


# ==========================================================================
# claim_drug_and_admin_line_dimensions_advance_independently
# ==========================================================================


def _submitted_claim(depth):
    """Attest the standing encounter, enrol the patient and submit one claim."""
    depth.enc1_attested
    depth.enrollment1
    claim = depth.claim(injection_encounter_id=depth.enc1["id"])
    return depth.submit_claim(claim["id"])


def test_denying_the_administration_line_leaves_the_drug_axis_where_it_stood(depth, billing):
    """
    A remittance naming only the administration line makes that axis terminal and
    leaves the drug axis in `SUBMITTED` with no realized economics written.

    The PRD separates the axes: "After submission the two axes advance
    independently, and remittance posting is the only place either moves", and the
    administration line is terminal on denial with no way back — "The
    administration line has **no appeal edge at all**: `DENIED` is terminal on that
    axis even while the drug axis is still `APPEALED` and may yet be paid."  The
    realized figures wait for both: they are written "Once — and only once — the
    drug axis has reached `PAID` or `WRITTEN_OFF` *and* the administration axis has
    reached `PAID` or `DENIED`".

    Design: Difficulty/non_linear_state_machine/claim_drug_and_admin_line_dimensions_advance_independently
    """
    claim = _submitted_claim(depth)
    assert claim["drug_line_status"] == "SUBMITTED"
    assert claim["admin_line_status"] == "SUBMITTED"

    response = depth.api.post_remittance(
        claim["id"],
        f.admin_line_denied_payload(
            denial_code="NOT_COVERED", admin_allowed_cents=0, admin_paid_cents=0
        ),
        billing,
    )
    remitted = validate_success(response, 200)

    assert remitted["admin_line_status"] == "DENIED"
    assert remitted["admin_paid_cents"] == 0
    assert remitted["drug_line_status"] == "SUBMITTED"
    assert remitted["realized_margin_cents"] is None
    assert remitted["actual_acquisition_cost_cents"] is None

    encounter = depth.read_encounter(depth.enc1["id"])
    assert encounter["status"] == "BILLED"


def test_the_later_drug_payment_closes_both_axes_and_prices_the_shrunken_allowable(
    depth, billing
):
    """
    Paying the drug line after the administration line was denied closes the claim
    and writes the realized economics on the remitted drug figures.

    The administration denial replaces no allowable — PRD 3.8 gives that branch an
    exhaustive write list, "an `admin_line_outcome` of `DENIED`, also only from
    `SUBMITTED`, sets `admin_paid_cents` to 0 and stores `denial_code`", in
    deliberate contrast to the `PAID` branch which "requires `admin_allowed_cents`
    and `admin_paid_cents`, and stores them".  So step 1's "`total_allowed_cents`
    is `drug_allowed_cents` plus `wastage_allowed_cents` plus `admin_allowed_cents`"
    gives 32000 + 128000 + 12000 = 172000, a 0.2 rate makes `coinsurance_cents`
    34400, the sub-threshold cap halves 40000 to 20000 of relief and leaves 14400
    on the patient.  "The payer shortfall is `total_allowed_cents` less the sum of
    `drug_paid_cents`, `wastage_paid_cents` and `admin_paid_cents`, less
    `coinsurance_cents`, floored at 0" gives 172000 - 128000 - 34400 = 9600.  The
    realized margin then sums the paid amounts with the patient and foundation
    contributions less the 132000 lot cost, and "The same posting moves the
    encounter `BILLED → CLOSED`."

    Design: Difficulty/non_linear_state_machine/claim_drug_and_admin_line_dimensions_advance_independently
    """
    claim = _submitted_claim(depth)
    depth.remit(
        claim["id"],
        f.admin_line_denied_payload(denial_code="NOT_COVERED"),
    )

    response = depth.api.post_remittance(
        claim["id"],
        f.drug_line_paid_payload(
            drug_allowed_cents=32000,
            drug_paid_cents=25600,
            wastage_allowed_cents=128000,
            wastage_paid_cents=102400,
        ),
        billing,
    )
    final = validate_success(response, 200)

    assert final["drug_line_status"] == "PAID"
    assert final["admin_line_status"] == "DENIED"
    assert final["admin_paid_cents"] == 0
    assert final["total_allowed_cents"] == 172000
    assert final["coinsurance_cents"] == 34400
    assert final["foundation_applied_cents"] == 20000
    assert final["patient_responsibility_cents"] == 14400
    assert final["practice_writeoff_cents"] == 9600
    assert final["actual_acquisition_cost_cents"] == 132000
    assert final["realized_margin_cents"] == 30400

    encounter = depth.read_encounter(depth.enc1["id"])
    assert encounter["status"] == "CLOSED"
