"""The shipping gate's rejection order and the certification-revocation cascade."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_NAMEPLATE_NOT_CERTIFIED,
    ERR_TEARDOWN_EVIDENCE_REQUIRED,
    ERR_UNAUTHORIZED,
)
from test_helpers.fixtures import build_plant


def test_a_build_technician_shipping_an_uncertified_motor_is_refused_as_unauthorized(
    api,
):
    """Two violations are live and the role check must speak first.

    PRD 2.11: "Authentication comes first (`ERR_UNAUTHENTICATED`), then endpoint
    role authorisation (`ERR_UNAUTHORIZED`), then row ownership
    (`ERR_NOT_OWNER`), then segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_nameplate_not_certified_on_ship
    """
    plant = build_plant(api, "tested")
    work_order = plant.get_work_order()
    assert work_order["build_status"] == "TESTED"
    assert work_order["certification_status"] == "PENDING"

    refused = api.ship_work_order(
        work_order["id"], F.ship_payload(), U.BUILD_TECHNICIAN
    )

    reported = validate_error(refused, ERR_UNAUTHORIZED, 403)
    assert reported["error_id"] != ERR_NAMEPLATE_NOT_CERTIFIED
    unchanged = plant.get_work_order()
    assert unchanged["build_status"] == "TESTED"
    assert unchanged["certification_status"] == "PENDING"
    assert unchanged["shipped_at"] is None
    assert plant.get_order()["status"] == "IN_PRODUCTION"
    assert plant.get_distributor()["units_outstanding"] == 12


def test_the_authorized_planner_then_surfaces_the_missing_certification(api):
    """The same request from a ProductionPlanner reaches the compliance gate.

    PRD 3.5: "The transition is guarded *across* the two dimensions:
    `certification_status` must be `CERTIFIED`, so a tested motor whose nameplate
    was never issued (`PENDING`) or has been revoked (`SUSPENDED`) is refused with
    `ERR_NAMEPLATE_NOT_CERTIFIED` (HTTP 409) and must not leave the plant."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_nameplate_not_certified_on_ship
    """
    plant = build_plant(api, "tested")
    work_order = plant.get_work_order()
    validate_error(
        api.ship_work_order(work_order["id"], F.ship_payload(), U.BUILD_TECHNICIAN),
        ERR_UNAUTHORIZED,
        403,
    )

    refused = api.ship_work_order(
        work_order["id"], F.ship_payload(), U.PRODUCTION_PLANNER
    )

    validate_error(refused, ERR_NAMEPLATE_NOT_CERTIFIED, 409)
    unchanged = plant.get_work_order()
    assert unchanged["build_status"] == "TESTED"
    assert unchanged["certification_status"] == "PENDING"
    assert unchanged["shipped_at"] is None
    assert plant.get_order()["status"] == "IN_PRODUCTION"
    assert plant.get_distributor()["units_outstanding"] == 12
    assert plant.get_distributor()["stock_allowance_remaining_units"] == 488


def test_revoking_a_nameplate_suspends_certification_and_flags_the_open_claim(api):
    """Three hops: the certificate, the work order's other axis, then the claim.

    PRD 3.9: "Revocation then propagates in three hops, breadth-first: the owning
    work order's `certification_status` moves `CERTIFIED → SUSPENDED` with its
    `version` incremented; then every warranty claim on that work order whose
    `status` is `SUBMITTED` or `UNDER_ANALYSIS` has `defect_presumption_applied`
    set to true; then `open_presumed_defect_count` is recomputed for every
    distributor owning such a claim, with each affected distributor's `version`
    incremented by 1."

    Design: Difficulty/transitive_cascade/nameplate_revoke_cascades_to_certification_claim_and_distributor_counter
    """
    plant = build_plant(api, "claim_filed")
    assert plant.get_work_order()["certification_status"] == "CERTIFIED"
    assert plant.get_claim()["defect_presumption_applied"] is False
    assert plant.get_distributor()["open_presumed_defect_count"] == 0

    revoked = plant.revoke_nameplate()

    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] == F.RECORD_CLOCK
    assert revoked["revocation_reason"] is not None
    work_order = plant.get_work_order()
    assert work_order["certification_status"] == "SUSPENDED"
    assert work_order["build_status"] == "SHIPPED"
    claim = plant.get_claim()
    assert claim["defect_presumption_applied"] is True
    assert claim["status"] == "SUBMITTED"
    distributor = plant.get_distributor()
    assert distributor["open_presumed_defect_count"] == 1
    assert distributor["warranty_credit_balance_cents"] == 0


def test_the_defect_presumption_bars_a_field_data_analysis(api):
    """Once the certificate is revoked, telemetry alone can no longer rebut it.

    PRD 3.10: "and a claim whose `defect_presumption_applied` is true may only be
    analysed on the `TEARDOWN` basis, because once a certification has been
    revoked, field telemetry alone can no longer rebut the presumption."

    Design: Difficulty/transitive_cascade/nameplate_revoke_cascades_to_certification_claim_and_distributor_counter
    """
    plant = build_plant(api, "claim_filed")
    claim = plant.claim
    plant.revoke_nameplate()
    assert plant.get_claim()["defect_presumption_applied"] is True

    refused = api.analyze_warranty_claim(
        claim["id"], F.analyze_field_data_payload(), U.COMPLIANCE_OFFICER
    )

    validate_error(refused, ERR_TEARDOWN_EVIDENCE_REQUIRED, 422)
    stored = plant.get_claim()
    assert stored["status"] == "SUBMITTED"
    assert stored["adjudication"] is None
    assert stored["misuse_index"] is None
    assert stored["warranty_credit_cents"] == 0
    assert stored["credit_posted"] is False
    assert plant.get_distributor()["open_presumed_defect_count"] == 1
