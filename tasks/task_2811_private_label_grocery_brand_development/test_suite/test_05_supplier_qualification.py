"""Admitting a plant: audit results, certificate currency and standing changes."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import canonicalize_iso
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_status,
    assert_supplier_status,
)
from test_helpers.constants import (
    AUDIT_FINALIZED,
    AUDIT_RESULT_FAIL,
    AUDIT_RESULT_PASS,
    DECISION_QUALIFY,
    DECISION_REINSTATE,
    DEFAULT_CLOCK,
    SUPPLIER_PROSPECT,
    SUPPLIER_QUALIFIED,
)
from test_helpers.fixtures import build_chain, read_supplier
from test_helpers.test_users import DIRECTOR_HEADERS, QUALITY_HEADERS, SOURCING_HEADERS


def test_qualifying_a_supplier_whose_gfsi_certificate_has_lapsed_is_rejected(api):
    """A certificate that expired before the clock cannot support a QUALIFY.

    PRD 3.2: "Separately, a `QUALIFY` or `CONDITIONAL` decision requires
    `gfsi_certificate_expiry` to be strictly after the logical clock at decision
    time; a certificate expiring exactly at the current instant has already
    lapsed, and the decision is refused with `ERR_GFSI_CERTIFICATE_EXPIRED`
    (HTTP 422)."

    PRD 3.2: "`PROSPECT → QUALIFIED` requires a passing capability audit and a
    live certificate, and on success sets `qualified_at` to the logical clock's
    current instant and refreshes `composite_score_cached`."

    Design: Corner/validations/qualification_with_expired_gfsi_certificate_rejected
    """
    ctx = build_chain(
        api,
        upto=8,
        supplier={
            "legal_name": "Lapsed Cert Bakers",
            "gfsi_certificate_expiry": "2026-07-15T00:00:00Z",
        },
    )
    # The step-8 audit finalize already refreshed composite_score_cached
    # ("The supplier's `composite_score_cached` is also refreshed" - PRD 3.2),
    # so the refused decision must leave that cached figure exactly as it stands.
    before = read_supplier(api, ctx["supplier_id"])

    response = api.decide_qualification(
        ctx["supplier_id"],
        f.qualification_payload(DECISION_QUALIFY, basis_audit_id=ctx["audit_id"]),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_GFSI_CERTIFICATE_EXPIRED.value, 422)

    supplier = read_supplier(api, ctx["supplier_id"])
    assert_supplier_status(supplier, SUPPLIER_PROSPECT)
    assert supplier["qualified_at"] is None
    assert supplier["composite_score_cached"] == before["composite_score_cached"], (
        "a refused decision must not refresh the cached composite score"
    )

    audit = validate_success(api.get_plant_audit(ctx["audit_id"], QUALITY_HEADERS))
    assert audit["result"] == AUDIT_RESULT_PASS, "the audit itself stays a PASS"


def test_qualifying_on_a_failed_capability_audit_is_rejected(api):
    """A FAIL result does not satisfy the basis a QUALIFY decision demands.

    PRD 3.2: "From the four pillars the system computes `result`: `PASS` when the
    food-safety score is at least 90 and the lowest of the four pillar scores is
    at least 80; failing that, `CONDITIONAL` when the food-safety score is at
    least 80 and the lowest of the four is at least 70; otherwise `FAIL`."

    PRD 3.2: "The cited audit must be a `FINALIZED` `CAPABILITY` audit of this
    same supplier whose `result` satisfies the decision being taken: `PASS` for
    `QUALIFY`, and `PASS` or `CONDITIONAL` for `CONDITIONAL` and for `REINSTATE`."

    PRD 3.2: "A basis that fails any of those conditions is refused with
    `ERR_AUDIT_BASIS_INVALID` (HTTP 422)."

    Design: Corner/validations/qualify_on_failed_capability_audit_rejected
    """
    ctx = build_chain(
        api, upto=8, audit_finalize_factory=f.failing_audit_finalize_payload
    )
    assert ctx["audit"]["result"] == AUDIT_RESULT_FAIL
    assert_status(ctx["audit"], AUDIT_FINALIZED, "plant audit")

    response = api.decide_qualification(
        ctx["supplier_id"],
        f.qualification_payload(DECISION_QUALIFY, basis_audit_id=ctx["audit_id"]),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_BASIS_INVALID.value, 422)

    supplier = read_supplier(api, ctx["supplier_id"])
    assert_supplier_status(supplier, SUPPLIER_PROSPECT)
    assert supplier["qualified_at"] is None


def test_reinstating_a_supplier_that_is_already_qualified_is_rejected(
    api, qualified_supplier
):
    """Reinstatement is defined only from SUSPENDED, and the state check runs first.

    PRD 3.2: "A decision that is simply not defined from the supplier's current
    standing — reinstating a `PROSPECT`, disqualifying a `QUALIFIED` supplier — is
    refused with `ERR_SUPPLIER_STATE_INVALID` (HTTP 409)."

    PRD 2.9: "the supplier-scope restriction on `SupplierUser`; the claim
    self-review prohibition; the run self-approval prohibition; the two
    optimistic-concurrency version checks; the program-closed check; the
    program-relaunch-frozen check; category-gap state; supplier qualification
    state and plant-audit state; the addressed resource's own transition state;
    item quality suspension; awarded-supplier qualification; GFSI certificate
    validity; audit-basis validity"

    Design: Corner/state_machines/supplier_reinstate_from_qualified_rejected
    """
    supplier_id = qualified_supplier["supplier_id"]

    response = api.decide_qualification(
        supplier_id,
        f.qualification_payload(
            DECISION_REINSTATE, basis_audit_id=qualified_supplier["audit_id"]
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_SUPPLIER_STATE_INVALID.value, 409)

    supplier = read_supplier(api, supplier_id)
    assert_supplier_status(supplier, SUPPLIER_QUALIFIED)
    assert_instant_equals(supplier["qualified_at"], DEFAULT_CLOCK, "qualified_at")


def test_recertifying_against_the_original_audit_is_rejected_as_stale(
    api, qualified_supplier
):
    """Yesterday's basis cannot renew today: the audit must postdate qualified_at.

    PRD 3.2: "Where freshness matters — annual recertification of an
    already-`QUALIFIED` supplier, promotion of a `CONDITIONAL` supplier to
    `QUALIFIED`, and reinstatement of a `SUSPENDED` one — the cited audit's
    `window_end` must also be strictly after the supplier's current
    `qualified_at`, so that yesterday's basis cannot be reused to renew today."

    Design: Corner/state_machines/supplier_recertification_reusing_stale_audit_rejected
    """
    supplier_id = qualified_supplier["supplier_id"]
    audit = validate_success(
        api.get_plant_audit(qualified_supplier["audit_id"], QUALITY_HEADERS)
    )
    before = read_supplier(api, supplier_id)
    assert canonicalize_iso(audit["window_end"]) < canonicalize_iso(
        before["qualified_at"]
    ), "the basis audit closed before the supplier was qualified"

    response = api.decide_qualification(
        supplier_id,
        f.qualification_payload(
            DECISION_QUALIFY, basis_audit_id=qualified_supplier["audit_id"]
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_BASIS_INVALID.value, 422)

    supplier = read_supplier(api, supplier_id)
    assert_supplier_status(supplier, SUPPLIER_QUALIFIED)
    assert_instant_equals(
        supplier["qualified_at"], before["qualified_at"], "qualified_at"
    )


def test_finalizing_an_already_finalized_audit_is_rejected(api, finalized_audit):
    """Finalization is a one-way move; the second attempt cannot restate scores.

    PRD 3.2: "Finalizing an audit that is already `FINALIZED` is refused with
    `ERR_AUDIT_NOT_SCHEDULED` (HTTP 409)."

    Design: Corner/state_machines/audit_finalize_twice_rejected
    """
    audit_id = finalized_audit["audit_id"]

    response = api.finalize_plant_audit(
        audit_id,
        f.audit_finalize_payload(
            food_safety_score=99,
            sanitation_score=99,
            capacity_score=99,
            traceability_score=99,
            audited_yield_pct=99.0,
        ),
        QUALITY_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_NOT_SCHEDULED.value, 409)

    audit = validate_success(api.get_plant_audit(audit_id, QUALITY_HEADERS))
    assert_status(audit, AUDIT_FINALIZED, "plant audit")
    assert audit["result"] == AUDIT_RESULT_PASS
    assert audit["food_safety_score"] == 92, "the first finalization's scores stand"
    assert audit["audited_yield_pct"] == 91.0


def test_qualification_basis_audit_must_belong_to_the_deciding_supplier(
    api, qualified_supplier
):
    """Another plant's PASS is not a basis for this plant's qualification.

    PRD 3.2: "The cited audit must be a `FINALIZED` `CAPABILITY` audit of this
    same supplier whose `result` satisfies the decision being taken: `PASS` for
    `QUALIFY`, and `PASS` or `CONDITIONAL` for `CONDITIONAL` and for `REINSTATE`."

    PRD 3.2: "A basis that fails any of those conditions is refused with
    `ERR_AUDIT_BASIS_INVALID` (HTTP 422)."

    Design: Corner/endpoints/qualification_decision_rejects_basis_audit_of_another_supplier
    """
    other = validate_success(
        api.create_supplier(
            f.supplier_payload(
                qualified_supplier["program_id"], legal_name="Southgate Baking Co"
            ),
            SOURCING_HEADERS,
        ),
        expected_status=201,
    )
    own_audit = validate_success(
        api.create_plant_audit(
            f.plant_audit_payload(
                other["id"],
                window_start="2026-07-23T08:00:00Z",
                window_end="2026-07-24T17:00:00Z",
            ),
            QUALITY_HEADERS,
        ),
        expected_status=201,
    )
    own_audit = validate_success(
        api.finalize_plant_audit(
            own_audit["id"],
            f.audit_finalize_payload(
                food_safety_score=95,
                sanitation_score=90,
                capacity_score=92,
                traceability_score=88,
                audited_yield_pct=93.0,
            ),
            QUALITY_HEADERS,
        )
    )

    response = api.decide_qualification(
        other["id"],
        f.qualification_payload(
            DECISION_QUALIFY, basis_audit_id=qualified_supplier["audit_id"]
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_AUDIT_BASIS_INVALID.value, 422)

    refused = read_supplier(api, other["id"])
    assert_supplier_status(refused, SUPPLIER_PROSPECT)
    assert refused["qualified_at"] is None
    assert_supplier_status(
        read_supplier(api, qualified_supplier["supplier_id"]), SUPPLIER_QUALIFIED
    )
    assert_status(own_audit, AUDIT_FINALIZED, "plant audit")
    assert own_audit["result"] == AUDIT_RESULT_PASS, (
        "the other plant's own audit remains an unused PASS"
    )
