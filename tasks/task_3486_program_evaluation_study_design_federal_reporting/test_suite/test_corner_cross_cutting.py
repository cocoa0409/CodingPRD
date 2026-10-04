"""Corner queue — cross-cutting layer claims: optimistic concurrency, version
increments, version pinning (consent form, primary outcomes), and the
half-open IRB expiry boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_participant,
    amend_analysis_plan_payload,
    approve_irb_protocol,
    consent_payload,
    create_design_plan,
    make_participant_headers,
    set_clock,
    setup_active_site_study,
    setup_contract,
    setup_contract_with_study,
    setup_registered_analysis_plan,
    setup_study_with_locked_plan,
    terminate_contract_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]


def test_occ_stale_study_version_conflict(api):
    """PRD §2.9: "If the supplied value no longer matches the study's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    which signals that another design-plan write has legitimately superseded
    the prior plan since the client last read the study."
    PRD §3.2: "Creation automatically supersedes the study's current plan when
    that plan sits in `DRAFT` or `RETURNED_FOR_REVISION`: the older plan moves
    to `SUPERSEDED`, a terminal state, and is never again the study's current
    plan. The creation also increments the study's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_study_version_conflict
    """
    ctx = setup_contract_with_study()
    study = ctx["study"]
    study_id = study["id"]

    plan1 = create_design_plan(study_id, expected_study_version=study["version"])
    study_v2 = api.get_study(study_id, PI).json()["data"]["version"]
    plan2 = create_design_plan(
        study_id, expected_study_version=study_v2, design_type="QED_DID"
    )  # supersedes plan1, bumps the study version again

    # Replaying the pre-supersede version is stale.
    resp = api.create_design_plan(
        study_id,
        {
            "design_type": "RCT", "mde": 0.3, "cluster_size": 10,
            "icc": 0.05, "attrition_rate": 0.15,
            "expected_study_version": study_v2,
        },
        PI,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    plans, _ = validate_paginated(api.list_design_plans(study_id, PI))
    assert len(plans) == 2, "the rejected create added no plan"
    assert next(p for p in plans if p["id"] == plan1["id"])["status"] == "SUPERSEDED"
    assert next(p for p in plans if p["id"] == plan2["id"])["status"] == "DRAFT"


def test_entity_version_increments_on_mutation(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    by one on every mutation of the resource, whether the mutation came from a
    client request or from an automatic system transition."

    Design: Corner/cross_cutting_layers/entity_version_increments_on_mutation
    """
    contract = setup_contract(award_amount_cents=50000000)
    assert contract["version"] == 1

    contract = validate_success(
        api.terminate_contract(contract["id"], terminate_contract_payload("Descoped"), AO),
        200,
    )
    assert contract["version"] == 2, "terminate is one mutation"
    assert contract["status"] == "TERMINATED"


def test_consent_version_stale_after_irb_modification_cycle(api):
    """PRD §3.3: "if the protocol's history within this submission cycle passed
    through `MODIFICATIONS_REQUIRED` at least once, `consent_form_version`
    increments by one — this is how participants are forced to re-consent
    against revised consent language, per §3.5."
    PRD §3.5: "the supplied `consent_form_version` must equal that currently
    approved protocol's `consent_form_version` — a participant handed last
    cycle's form is rejected with `ERR_CONSENT_VERSION_STALE`."

    Design: Corner/cross_cutting_layers/consent_version_stale_after_irb_modification_cycle
    """
    ctx = setup_active_site_study(with_modifications_cycle=True)
    protocols, _ = validate_paginated(api.list_irb_protocols(ctx["study"]["id"], PI))
    irb = next(p for p in protocols if p["id"] == ctx["irb"]["id"])
    assert irb["consent_form_version"] == 2, "bumped after the modifications cycle"

    p1 = add_participant(ctx["site"]["id"], external_ref="P001")
    resp = api.consent_participant(
        p1["id"], consent_payload(1), make_participant_headers(p1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_VERSION_STALE)

    p1 = validate_success(
        api.consent_participant(
            p1["id"], consent_payload(2), make_participant_headers(p1["id"])
        ),
        200,
    )
    assert p1["status"] == "CONSENTED"
    assert p1["consent_form_version"] == 2


def test_primary_outcomes_frozen_after_registration(api):
    """PRD §3.7: "a `PrincipalInvestigator` amends a `PREREGISTERED` plan ...
    replacing `secondary_outcomes` wholesale and incrementing
    `amendment_count` by one, but any payload containing a `primary_outcomes`
    key is rejected outright with `ERR_PRIMARY_OUTCOME_FROZEN`."

    Design: Corner/cross_cutting_layers/primary_outcomes_frozen_after_registration
    """
    ctx = setup_study_with_locked_plan()
    aplan = setup_registered_analysis_plan(
        ctx, secondary_outcomes=["job_retention"]
    )
    assert aplan["status"] == "PREREGISTERED"

    aplan = validate_success(
        api.amend_analysis_plan(
            aplan["id"],
            amend_analysis_plan_payload(
                secondary_outcomes=["job_retention", "benefit_receipt"]
            ),
            PI,
        ),
        200,
    )
    assert aplan["amendment_count"] == 1
    assert aplan["secondary_outcomes"] == ["job_retention", "benefit_receipt"]

    resp = api.amend_analysis_plan(
        aplan["id"], amend_analysis_plan_payload(primary_outcomes=["employment_q4"]), PI
    )
    validate_error(resp, ApiErrorId.ERR_PRIMARY_OUTCOME_FROZEN)

    plans, _ = validate_paginated(api.list_analysis_plans(ctx["study"]["id"], PI))
    aplan = next(p for p in plans if p["id"] == aplan["id"])
    assert aplan["primary_outcomes"] == ["employment_q4", "earnings_q4"], "frozen"
    assert aplan["amendment_count"] == 1, "the rejected amend did not count"


def test_irb_expiry_exact_midnight_boundary(api):
    """PRD §3.3: "When the logical clock of §2.4 reaches or passes an
    `APPROVED` protocol's `approval_end` — at exactly `approval_end` the
    protocol is already expired, because the window is half-open — the protocol
    moves to `EXPIRED`."

    Design: Corner/cross_cutting_layers/irb_expiry_exact_midnight_boundary
    """
    ctx = setup_contract_with_study()
    irb = approve_irb_protocol(ctx["study"]["id"])  # [2026-09-01, 2027-09-01)
    assert irb["status"] == "APPROVED"

    set_clock("2027-08-31T23:59:59Z")  # one second before the exclusive end
    protocols, _ = validate_paginated(api.list_irb_protocols(ctx["study"]["id"], PI))
    assert next(p for p in protocols if p["id"] == irb["id"])["status"] == "APPROVED"

    set_clock("2027-09-01T00:00:00Z")  # exactly approval_end: already expired
    protocols, _ = validate_paginated(api.list_irb_protocols(ctx["study"]["id"], PI))
    assert next(p for p in protocols if p["id"] == irb["id"])["status"] == "EXPIRED"
