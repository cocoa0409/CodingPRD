"""Injection encounters: booking, documentation, attestation and voiding.

PRD 3.6 and 3.7. The validation order inside create_encounter follows the
numbered ladder of PRD 2.8 exactly; the step numbers are quoted in comments.
"""
from datetime import timedelta

from flask import Blueprint, g

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_RETINA,
    base_row,
    created,
    dec,
    fail,
    get_body,
    get_encounter,
    get_plan,
    get_study,
    listing,
    ok,
    ordered,
    pagination,
    query_filters,
    round_half_up,
    touch,
    validate,
    whole_days,
)
from domain import (
    CAPACITY_WINDOW_HOURS,
    IMAGING_VALIDITY_DAYS,
    PLAN_TREATABLE,
    advance_plan_on_documentation,
    assemble_modifiers,
    billing_units_split,
    encounter_order_key,
    bump_authorization_usage,
    latest_non_voided_encounter,
    policy_for,
    refresh_last_encounter,
    recompute_authorization_usage,
    recompute_lot_counters,
    release_reserved_vial,
    replay_plan_schedule,
    reserve_vial,
)
from routes_authorizations import occ_guard

bp = Blueprint("encounters", __name__)

ENCOUNTER_STATUSES = ["DRAFT", "DOCUMENTED", "ATTESTED", "BILLED", "CLOSED", "VOIDED"]
EYES = ["OD", "OS"]


# ------------------------------------------------------- effective product
def _candidate_pool(plan, payer_id):
    pool = []
    for drug in DB.drugs.values():
        if drug["reference_drug_id"] != plan["drug_id"]:
            continue
        if drug["status"] != "ACTIVE":
            continue
        policy = policy_for(payer_id, drug["id"])
        if policy is None or policy["coverage_tier"] != "PREFERRED":
            continue
        pool.append((policy, drug))
    pool.sort(
        key=lambda pair: (
            int(pair[0]["drug_allowed_cents_per_billing_unit"]),
            pair[1]["created_at"],
            pair[1]["_seq"],
        )
    )
    return [drug for _policy, drug in pool]


def resolve_effective_drug(plan, payer, override):
    """The five-arm cascade of PRD 3.6, exactly one arm firing."""
    plan_drug = DB.drugs[plan["drug_id"]]
    candidates = _candidate_pool(plan, payer["id"])
    best = candidates[0] if candidates else None

    if override:
        return plan_drug, None
    if plan_drug["is_biosimilar"] or best is None:
        return plan_drug, None
    if payer["biosimilar_preference"] == "MANDATORY":
        return best, plan_drug["id"]
    if payer["biosimilar_preference"] == "PREFERRED":
        own_policy = policy_for(payer["id"], plan_drug["id"])
        if own_policy is not None and own_policy["coverage_tier"] == "NON_PREFERRED":
            return best, plan_drug["id"]
    return plan_drug, None


def _select_authorization(plan, effective_drug_id):
    live = [
        a
        for a in DB.authorizations.values()
        if a["treatment_plan_id"] == plan["id"] and a["status"] in ("APPROVED", "EXHAUSTED")
    ]
    if not live:
        fail("ERR_AUTHORIZATION_MISSING", "the plan holds no approved authorization")

    covering = [
        a
        for a in live
        if a["effective_date"] is not None
        and a["expiration_date"] is not None
        and a["effective_date"] <= DB.clock <= a["expiration_date"]
    ]
    if covering:
        covering.sort(key=lambda a: (a["effective_date"], a["created_at"], a["_seq"]), reverse=True)
        pa = covering[0]
    else:
        stale = sorted(
            live,
            key=lambda a: (
                a["expiration_date"] or DB.clock,
                a["created_at"],
                a["_seq"],
            ),
            reverse=True,
        )[0]
        stale["status"] = "EXPIRED"
        touch(stale)
        fail("ERR_AUTHORIZATION_EXPIRED", "the covering authorization has expired")

    if pa["drug_id"] != effective_drug_id:
        fail("ERR_AUTHORIZATION_DRUG_MISMATCH", "the authorization names a different product")
    if int(pa["injections_used"]) >= int(pa["approved_injections"]):
        fail("ERR_AUTHORIZATION_EXHAUSTED", "the authorization has no capacity left")
    return pa


def _select_vial(effective_drug_id):
    pool = []
    for vial in DB.vials.values():
        if vial["status"] != "IN_STOCK":
            continue
        lot = DB.lots.get(vial["drug_lot_id"])
        if lot is None or lot["status"] != "AVAILABLE":
            continue
        if lot["drug_id"] != effective_drug_id:
            continue
        if not lot["expiration_date"] > DB.clock:
            continue
        pool.append((lot, vial))
    if not pool:
        fail("ERR_NO_ELIGIBLE_VIAL", "no eligible vial is available for this product")
    pool.sort(
        key=lambda pair: (
            pair[0]["expiration_date"],
            -int(pair[0]["unit_acquisition_cost_cents"]),
            pair[1]["created_at"],
            pair[1]["_seq"],
        )
    )
    return pool[0][1]


# ----------------------------------------------------------------- creation
@bp.post("/injection-encounters")
@core.api([ROLE_RETINA])
def create_encounter():
    body = get_body()
    values = validate(  # step 5
        body,
        [
            Field("treatment_plan_id", "id", required=True),
            Field("imaging_study_id", "id", required=True),
            Field("encounter_datetime", "datetime", required=True),
            Field("expected_treatment_plan_version", "integer", required=True, minimum=1),
            Field("medical_necessity_override", "boolean", default=False),
            Field("override_reason", "string"),
        ],
    )
    plan = get_plan(values["treatment_plan_id"])  # step 7
    study = get_study(values["imaging_study_id"])  # step 7
    occ_guard(plan, values["expected_treatment_plan_version"])  # step 12

    if plan["status"] not in PLAN_TREATABLE:  # step 13
        fail("ERR_PLAN_NOT_TREATABLE", "the plan is not treatable in %s" % plan["status"])

    clinician = DB.clinicians[g.user_id]
    if clinician["status"] != "ACTIVE" or not clinician["injection_privilege"]:  # step 14
        fail("ERR_CLINICIAN_NOT_ELIGIBLE", "the acting clinician may not inject")

    if study["patient_id"] != plan["patient_id"] or study["eye"] != plan["eye"]:  # step 15
        fail("ERR_IMAGING_EYE_MISMATCH", "study patient or eye disagrees with the plan")

    when = values["encounter_datetime"]
    gap = when - study["study_datetime"]
    if gap < timedelta(0) or gap > timedelta(days=IMAGING_VALIDITY_DAYS):  # step 16
        fail("ERR_IMAGING_STUDY_STALE", "the study is outside its validity window")

    patient = DB.patients[plan["patient_id"]]
    payer = DB.payers[patient["payer_id"]]
    override = bool(values["medical_necessity_override"])
    effective_drug, substituted_from = resolve_effective_drug(plan, payer, override)

    previous = latest_non_voided_encounter(plan["id"])
    if previous is not None:  # step 17
        elapsed = whole_days(previous["encounter_datetime"], when)
        if elapsed < int(effective_drug["min_interval_days"]):
            fail("ERR_INJECTION_INTERVAL_VIOLATION", "the gap since the last injection is short")

    window_start = when - timedelta(hours=CAPACITY_WINDOW_HOURS)
    same_day = 0
    for enc in DB.encounters.values():  # step 18
        if enc["clinician_id"] != g.user_id or enc["status"] == "VOIDED":
            continue
        if window_start <= enc["encounter_datetime"] <= when:
            same_day += 1
    if same_day >= int(clinician["max_injections_per_day"]):
        fail("ERR_CLINICIAN_DAY_CAPACITY_EXCEEDED", "the clinician's daily cap is reached")

    if override:  # step 19
        reason = values["override_reason"]
        if reason is None or not reason.strip():
            fail("ERR_OVERRIDE_REASON_REQUIRED", "override_reason is required for an override")

    policy = policy_for(payer["id"], effective_drug["id"])
    if policy is None:  # step 20
        fail("ERR_PAYER_POLICY_MISSING", "no coverage policy for this payer and product")
    if policy["coverage_tier"] == "EXCLUDED":  # step 21
        fail("ERR_DRUG_EXCLUDED_BY_PAYER", "the payer excludes this product")

    pa = None
    if policy["pa_required"]:  # steps 22 - 25
        pa = _select_authorization(plan, effective_drug["id"])

    vial = _select_vial(effective_drug["id"])  # step 26

    row = base_row()
    row.update(
        {
            "treatment_plan_id": plan["id"],
            "patient_id": plan["patient_id"],
            "clinician_id": g.user_id,
            "imaging_study_id": study["id"],
            "vial_id": vial["id"],
            "prior_authorization_id": pa["id"] if pa is not None else None,
            "previous_encounter_id": plan["last_encounter_id"],
            "effective_drug_id": effective_drug["id"],
            "substituted_from_drug_id": substituted_from,
            "attested_by_clinician_id": None,
            "encounter_datetime": when,
            "eye": plan["eye"],
            "status": "DRAFT",
            "administered_dose_ml": None,
            "wasted_ml": None,
            "administered_billing_units": None,
            "wasted_billing_units": None,
            "total_billed_billing_units": None,
            "modifiers": None,
            "injection_site_prep_confirmed": None,
            "post_injection_iop_mmhg": None,
            "interval_days_from_previous": None,
            "medical_necessity_override": override,
            "override_reason": values["override_reason"],
            "void_reason": None,
        }
    )
    prior = DB.encounters.get(plan["last_encounter_id"])
    if prior is not None:
        row["interval_days_from_previous"] = whole_days(prior["encounter_datetime"], when)
    DB.encounters[row["id"]] = row

    if pa is not None:
        bump_authorization_usage(pa)
    reserve_vial(vial, row["id"])
    # PRD 2.6: "Creating an encounter legitimately mutates its plan -
    # last_encounter_id ... move", and PRD 3.3 keeps that pointer at "the plan's
    # non-VOIDED encounter with the greatest encounter_datetime".
    refresh_last_encounter(plan)
    touch(plan)
    return created(row)


@bp.get("/injection-encounters/<eid>")
@core.api(READ_ROLES)
def read_encounter(eid):
    return ok(get_encounter(eid))


@bp.get("/injection-encounters")
@core.api(READ_ROLES)
def list_encounters():
    limit, offset = pagination()
    filters = query_filters(
        {
            "treatment_plan_id": ("treatment_plan_id", "string"),
            "patient_id": ("patient_id", "string"),
            "clinician_id": ("clinician_id", "string"),
            "imaging_study_id": ("imaging_study_id", "string"),
            "vial_id": ("vial_id", "string"),
            "prior_authorization_id": ("prior_authorization_id", "string"),
            "previous_encounter_id": ("previous_encounter_id", "string"),
            "effective_drug_id": ("effective_drug_id", "string"),
            "substituted_from_drug_id": ("substituted_from_drug_id", "string"),
            "attested_by_clinician_id": ("attested_by_clinician_id", "string"),
            "status": ("status", "enum", ENCOUNTER_STATUSES),
            "eye": ("eye", "enum", EYES),
        }
    )
    return listing(DB.encounters.values(), filters, limit, offset)


# ------------------------------------------------------------ documentation
@bp.post("/injection-encounters/<eid>/document")
@core.api([ROLE_RETINA])
def document_encounter(eid):
    body = get_body()
    values = validate(
        body,
        [
            Field("administered_dose_ml", "number", required=True),
            Field("injection_site_prep_confirmed", "boolean", required=True),
            Field("post_injection_iop_mmhg", "integer", required=True, minimum=0, maximum=80),
        ],
    )
    enc = get_encounter(eid)
    if enc["status"] != "DRAFT" or enc["clinician_id"] != g.user_id:  # step 13
        fail("ERR_ENCOUNTER_STATE_INVALID", "only the injector may document a DRAFT encounter")

    vial = DB.vials[enc["vial_id"]]
    lot = DB.lots[vial["drug_lot_id"]]
    if lot["status"] != "AVAILABLE":  # step 27
        fail("ERR_LOT_NOT_AVAILABLE", "the reserved vial's lot is no longer available")

    drug = DB.drugs[enc["effective_drug_id"]]
    dose = values["administered_dose_ml"]
    if dose <= 0 or dose > dec(drug["vial_fill_ml"]):  # step 28
        fail("ERR_DOSE_EXCEEDS_VIAL_FILL", "the administered dose is not physically possible")
    if not values["injection_site_prep_confirmed"]:  # step 29
        fail("ERR_PREP_ATTESTATION_REQUIRED", "injection_site_prep_confirmed must be true")

    wasted_ml, admin_units, wasted_units, total_units = billing_units_split(drug, dose)
    enc["administered_dose_ml"] = dose
    enc["injection_site_prep_confirmed"] = True
    enc["post_injection_iop_mmhg"] = values["post_injection_iop_mmhg"]
    enc["wasted_ml"] = wasted_ml
    enc["administered_billing_units"] = admin_units
    enc["wasted_billing_units"] = wasted_units
    enc["total_billed_billing_units"] = total_units
    enc["modifiers"] = assemble_modifiers(enc, drug, wasted_units)
    enc["status"] = "DOCUMENTED"
    touch(enc)

    vial["status"] = "ADMINISTERED"
    vial["administered_at"] = enc["encounter_datetime"]
    touch(vial)
    recompute_lot_counters(lot)

    advance_plan_on_documentation(DB.plans[enc["treatment_plan_id"]], enc)
    return ok(enc)


@bp.post("/injection-encounters/<eid>/attest-wastage")
@core.api([ROLE_RETINA])
def attest_wastage(eid):
    body = get_body()
    values = validate(body, [Field("attested_wasted_ml", "number", required=True, minimum=0)])
    enc = get_encounter(eid)
    if enc["clinician_id"] == g.user_id:  # step 9
        fail("ERR_SEGREGATION_OF_DUTIES", "the injector may not attest their own wastage")
    if enc["status"] != "DOCUMENTED":  # step 13
        fail("ERR_ENCOUNTER_STATE_INVALID", "only a DOCUMENTED encounter may be attested")
    attester = DB.clinicians[g.user_id]
    if attester["status"] != "ACTIVE":
        fail("ERR_CLINICIAN_NOT_ELIGIBLE", "a suspended clinician cannot witness wastage")
    if round_half_up(values["attested_wasted_ml"], 3) != round_half_up(enc["wasted_ml"], 3):
        fail("ERR_ATTESTED_WASTAGE_MISMATCH", "the attested wastage disagrees with the computed")
    enc["attested_by_clinician_id"] = g.user_id
    enc["status"] = "ATTESTED"
    touch(enc)
    return ok(enc)


@bp.post("/injection-encounters/<eid>/void")
@core.api([ROLE_RETINA])
def void_encounter(eid):
    body = get_body()
    values = validate(body, [Field("void_reason", "string", required=True, minlen=1)])
    enc = get_encounter(eid)
    if enc["status"] not in ("DRAFT", "DOCUMENTED"):
        fail("ERR_ENCOUNTER_STATE_INVALID", "a %s encounter cannot be voided" % enc["status"])
    if enc["status"] == "DOCUMENTED":
        for claim in DB.claims.values():
            if claim["injection_encounter_id"] == enc["id"]:
                fail("ERR_ENCOUNTER_STATE_INVALID", "a claimed encounter cannot be voided")

    from_documented = enc["status"] == "DOCUMENTED"
    if from_documented:
        vial = DB.vials.get(enc["vial_id"])
        if vial is not None and vial["status"] == "ADMINISTERED":
            vial["status"] = "QUARANTINED"
            touch(vial)
            recompute_lot_counters(DB.lots[vial["drug_lot_id"]])
    else:
        release_reserved_vial(enc)

    enc["status"] = "VOIDED"
    enc["void_reason"] = values["void_reason"]
    touch(enc)

    plan = DB.plans[enc["treatment_plan_id"]]
    if from_documented:
        replay_plan_schedule(plan)
    elif refresh_last_encounter(plan):
        # PRD 3.3 keeps last_encounter_id on a non-VOIDED encounter.
        touch(plan)
    recompute_authorization_usage(DB.authorizations.get(enc["prior_authorization_id"]))
    return ok(enc)
