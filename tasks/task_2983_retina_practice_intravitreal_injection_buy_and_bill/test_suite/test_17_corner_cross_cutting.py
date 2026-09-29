"""
Cross-cutting layers: the plan's single version counter guards two different
write families, and pricing selects exactly one coverage policy out of a
database that holds more generous rivals.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_fields_equal, assert_money_cents, validate_list
from test_helpers import factories as f
from test_helpers.test_users import billing_headers

# The allowance the rival PAY-COMM policy would have produced:
# 2 x 20000 administered + 8 x 20000 wasted + 15000 admin.
RIVAL_POLICY_TOTAL_CENTS = 215000


def test_the_plan_version_counter_guards_both_of_its_writes(breadth, billing):
    """
    An authorization create quoting the version the plan carried before activation
    is refused and persists nothing; quoting the live version succeeds, copies the
    drug and the payer, and itself advances the counter, which makes the value the
    client just sent stale for the very next create.

    Both guarded writes share one counter.  "Two write operations take an
    optimistic-concurrency guard, and both guard the same parent entity — the
    `TreatmentPlan`. Both require a non-optional integer field named
    `expected_treatment_plan_version` in the request body, carrying the `version` value
    of the plan the client last observed."  Activation already moved it: a successful
    activation "sets `next_due_date` to the logical clock advanced by those 28 days, and
    advances the plan's `version` by 1".  The second guarded write is the one under
    test: "The second is prior-authorization creation. A new authorization supersedes
    the plan's earlier authorization record for renewal purposes, so a create whose
    `expected_treatment_plan_version` is behind the plan's current `version` is rejected
    with the same `ERR_STALE_PLAN_VERSION` (HTTP 412): the requester has not observed
    the authorization that already superseded theirs. A successful prior-authorization
    create itself advances the plan's `version`."  What the accepted create writes is
    copied, not supplied: "`patient_id` is copied from the plan, `drug_id` is copied
    from the plan's planned product and is never re-derived afterwards, and `payer_id`
    is copied from the patient's current payer. The new authorization begins in `DRAFT`
    with `injections_used` at 0".

    Design: Corner/cross_cutting_complexity_layers/corner_authorization_create_is_the_second_occ_guarded_write_on_the_same_parent
    """
    breadth.pol_np_ref
    breadth.lot_ref
    patient = breadth.pt_np
    plan_at_create = breadth.plan_np
    plan_activated = breadth.plan_np_active

    version_at_create = plan_at_create["version"]
    version_after_activation = plan_activated["version"]
    assert version_after_activation == version_at_create + 1

    validate_error(
        breadth.api.create_prior_authorization(
            f.authorization_payload(
                treatment_plan_id=plan_activated["id"],
                expected_treatment_plan_version=version_at_create,
            ),
            billing,
        ),
        ApiErrorId.ERR_STALE_PLAN_VERSION,
        412,
    )
    _, empty_meta = validate_list(
        breadth.api.list_prior_authorizations(
            billing, f.page_params(treatment_plan_id=plan_activated["id"])
        )
    )
    assert empty_meta["total_count"] == 0, "A refused create must leave no authorization row"
    assert breadth.read_plan(plan_activated["id"])["version"] == version_after_activation

    accepted = validate_success(
        breadth.api.create_prior_authorization(
            f.authorization_payload(
                treatment_plan_id=plan_activated["id"],
                expected_treatment_plan_version=version_after_activation,
            ),
            billing,
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["drug_id"] == breadth.drug_ref["id"]
    assert accepted["payer_id"] == breadth.pay_np["id"]
    assert accepted["patient_id"] == patient["id"]
    assert accepted["injections_used"] == 0

    validate_error(
        breadth.api.create_prior_authorization(
            f.authorization_payload(
                treatment_plan_id=plan_activated["id"],
                expected_treatment_plan_version=version_after_activation,
            ),
            billing_headers(),
        ),
        ApiErrorId.ERR_STALE_PLAN_VERSION,
        412,
    )

    settled_plan = breadth.read_plan(plan_activated["id"])
    assert settled_plan["version"] == version_after_activation + 1, (
        "Exactly one increment, contributed by the accepted create alone"
    )

    rows, meta = validate_list(
        breadth.api.list_prior_authorizations(
            billing, f.page_params(treatment_plan_id=plan_activated["id"])
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [accepted["id"]]


def test_pricing_selects_the_one_policy_keyed_on_the_payer_and_the_effective_drug(
    breadth, billing
):
    """
    A far more generous policy for the same drug under a rival payer, and a policy for
    a different drug under the patient's own payer, both sit in the database while the
    claim is priced from neither.

    The key is stated once and it names both dimensions: "Pricing reads the coverage
    policy for the claim's payer paired with the encounter's effective drug."  The
    claim's payer is the patient's: "The claim copies `patient_id` from the encounter
    and `payer_id` from that patient as the payer stood at claim creation."  Each line
    then follows from that one policy: "`drug_billed_cents` is the encounter's
    `administered_billing_units` multiplied by the policy's
    `drug_allowed_cents_per_billing_unit`", "`admin_billed_cents` is the policy's
    `admin_allowed_cents`", and of the allowables, "`wastage_allowed_cents` equal to
    `wastage_billed_cents` when the policy's `wastage_reimbursed` is true and exactly 0
    when it is false".  The units come from the split: "Each of those two milligram
    figures is then divided by the drug's `billing_unit_mg` and rounded half up to a
    whole number **independently**, producing `administered_billing_units` and
    `wasted_billing_units`. Only after both lines have been rounded are they added
    together to give `total_billed_billing_units`", and the claim "copies ...
    `billed_billing_units` from the encounter's `total_billed_billing_units`".  The
    waterfall closes it: "`total_allowed_cents` is `drug_allowed_cents` plus
    `wastage_allowed_cents` plus `admin_allowed_cents`" and "`coinsurance_cents` is
    `total_allowed_cents` multiplied by the payer's `coinsurance_rate`, rounded half up
    to whole cents."

    Design: Corner/cross_cutting_complexity_layers/corner_policy_selection_is_keyed_on_the_patients_payer_and_the_effective_drug
    """
    governing = breadth.pol_np_ref

    other_drug = breadth.drug(
        brand_name="Zaltruvex",
        hcpcs_code="J2779",
        vial_type="SINGLE_DOSE",
        vial_fill_ml=0.5,
        label_dose_ml=0.05,
        mg_per_ml=100,
        billing_unit_mg=1,
        asp_cents_per_billing_unit=20000,
        min_interval_days=28,
        max_interval_days=112,
        is_biosimilar=False,
    )
    rival_payer_policy = breadth.policy(
        payer_id=breadth.pay_comm["id"],
        drug_id=breadth.drug_ref["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=20000,
        admin_allowed_cents=15000,
        wastage_reimbursed=True,
        pa_required=False,
    )
    other_drug_policy = breadth.policy(
        payer_id=breadth.pay_np["id"],
        drug_id=other_drug["id"],
        coverage_tier="PREFERRED",
        drug_allowed_cents_per_billing_unit=30000,
        admin_allowed_cents=12000,
        wastage_reimbursed=True,
        pa_required=False,
    )
    assert governing["wastage_reimbursed"] is False
    assert rival_payer_policy["drug_allowed_cents_per_billing_unit"] == 20000
    assert other_drug_policy["drug_allowed_cents_per_billing_unit"] == 30000

    attested = breadth.enc_np_attested
    assert attested["effective_drug_id"] == breadth.drug_ref["id"]
    assert attested["administered_billing_units"] == 2
    assert attested["wasted_billing_units"] == 8
    assert attested["total_billed_billing_units"] == 10

    claim = validate_success(
        breadth.api.create_claim(f.claim_payload(injection_encounter_id=attested["id"]), billing),
        201,
    )

    assert claim["payer_id"] == breadth.pay_np["id"]
    assert claim["billed_billing_units"] == 10
    assert_money_cents(
        claim,
        "drug_allowed_cents",
        "wastage_allowed_cents",
        "admin_allowed_cents",
        "total_allowed_cents",
        "coinsurance_cents",
    )
    assert_fields_equal(
        claim,
        {
            "drug_allowed_cents": 28000,
            "wastage_allowed_cents": 0,
            "admin_allowed_cents": 10000,
            "total_allowed_cents": 38000,
            "coinsurance_cents": 3800,
        },
    )

    rival_values = [
        key
        for key, value in claim.items()
        if isinstance(value, int) and not isinstance(value, bool)
        and value == RIVAL_POLICY_TOTAL_CENTS
    ]
    assert rival_values == [], (
        "The rival payer's policy would have allowed "
        f"{RIVAL_POLICY_TOTAL_CENTS}; it must appear nowhere on the claim, "
        f"but {rival_values} carry it"
    )
