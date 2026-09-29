"""Gates that read a parent's state because the child does not exist yet.

A lab result is admitted on the sample's status, and a residuals manifest on the
pilot's; in both cases the identical body flips from a refusal to a creation the
moment the parent moves.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_PILOT_NOT_COMPLETED, ERR_SAMPLE_NOT_RECEIVED
from test_helpers.assertions import (
    assert_decimal,
    assert_equals,
    assert_is_null,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    build_registry,
    collect_sample,
    complete_pilot,
    open_evaluation,
    read_pilot,
    read_sample,
    receive_sample,
    register_entry_point,
    register_pilot,
    ship_sample,
    start_pilot,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, TREATMENT_ENGINEER_HEADERS


def _sample_in_transit(api):
    registry = build_registry(api)
    sample = collect_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        monitoring_period="2026Q2",
        preservative_lot="LOT-XE",
    )
    ship_sample(api, sample["id"], registry["laboratory_id"])
    return registry, sample


def _result_body(registry, sample):
    return f.lab_result_payload(
        sample["id"],
        registry["contaminant_id"],
        method="METHOD_533",
        reported_ng_per_l=3.00,
        detection_limit_ng_per_l=1.00,
        analyzed_at="2026-05-20T08:00:00.000Z",
    )


def test_a_result_offered_against_a_sample_still_in_transit_is_refused(api):
    """The gate is a state read on the parent, not on the row being created.

    The sample has been shipped but not yet booked in, so it is IN_TRANSIT with a
    null received_at, and the submission is refused before any result row exists.

    PRD: "The parent sample must currently be in `RECEIVED` status — a result
    offered against a `COLLECTED`, `IN_TRANSIT`, `ANALYZED` or `INVALIDATED`
    sample is refused with `ERR_SAMPLE_NOT_RECEIVED`, and note that this is a
    state read on the sample rather than on the result being created."

    Design: Difficulty/cross_entity_state_dependency/lab_result_creation_reads_the_parent_sample_state_not_its_own
    """
    registry, sample = _sample_in_transit(api)

    validate_error(
        api.create_lab_result(_result_body(registry, sample), registry["lab_headers"]),
        ERR_SAMPLE_NOT_RECEIVED,
        422,
    )

    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 0
    )
    stored = read_sample(api, sample["id"])
    assert_status(stored, "IN_TRANSIT")
    assert_is_null(stored, "received_at")


def test_the_same_result_body_succeeds_once_the_laboratory_records_receipt(api):
    """Nothing about the body changes; only the parent's state does.

    Booking the shipment in moves the sample IN_TRANSIT to RECEIVED, and the
    identical submission that was refused a moment ago is now created in
    SUBMITTED status against that sample and that laboratory.

    PRD: "When the custody seal was intact **and** the field blank read strictly
    below 2.00 ng/L, the sample advances `IN_TRANSIT → RECEIVED`, `received_at`
    is set to the logical clock, and the entry point's
    `consecutive_invalidated_samples` streak is reset to 0."

    Design: Difficulty/cross_entity_state_dependency/lab_result_creation_reads_the_parent_sample_state_not_its_own
    """
    registry, sample = _sample_in_transit(api)
    validate_error(
        api.create_lab_result(_result_body(registry, sample), registry["lab_headers"]),
        ERR_SAMPLE_NOT_RECEIVED,
        422,
    )

    received = receive_sample(api, sample["id"], registry["laboratory_id"])
    assert_status(received, "RECEIVED")
    assert_equals(received, "chain_of_custody_intact", True)

    result = validate_success(
        api.create_lab_result(_result_body(registry, sample), registry["lab_headers"]), 201
    )

    assert_status(result, "SUBMITTED")
    assert_equals(result, "sample_id", sample["id"])
    assert_equals(result, "laboratory_id", registry["laboratory_id"])
    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 1
    )


def _running_pilot(api):
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"])
    pilot = register_pilot(api, f.gac_pilot_payload(evaluation["id"]))
    start_pilot(api, pilot["id"])
    return pilot


def test_a_manifest_raised_against_a_running_pilot_is_refused(api):
    """Only a completed run has spent media to ship.

    The GAC skid is RUNNING with spent_media_kg still null, so a manifest for
    300 kg of carbon is refused and no manifest row is created.

    PRD: "The pilot must be in `COMPLETED` status, else
    `ERR_PILOT_NOT_COMPLETED`, since only a completed run has spent media to
    ship."

    Design: Difficulty/cross_entity_state_dependency/residuals_manifest_creation_reads_the_pilot_state_not_its_own
    """
    pilot = _running_pilot(api)

    validate_error(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="GAC_CARBON", mass_kg=300.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_PILOT_NOT_COMPLETED,
        422,
    )

    assert_total_count(
        api.list_residuals_manifests(
            TREATMENT_ENGINEER_HEADERS, params={"pilot_test_id": pilot["id"]}
        ),
        0,
    )
    stored = read_pilot(api, pilot["id"])
    assert_status(stored, "RUNNING")
    assert_is_null(stored, "spent_media_kg")


def test_completing_the_pilot_admits_the_manifest_and_draws_down_the_ledger(api):
    """The same 300 kg body becomes a DRAFT manifest and moves the media ledger.

    Completing the run records 800.00 kg of spent media, after which the manifest
    is created in DRAFT with no classification yet and the pilot's unmanifested
    remainder falls to 500.00 kg.

    PRD: "On success the manifest is created in `DRAFT` status with
    `waste_classification`, `disposal_method`, `disposal_cost_cents` and
    `leachate_pfas_ng_per_l` all null, and the pilot's `unmanifested_media_kg` is
    reduced by the manifested mass."

    Design: Difficulty/cross_entity_state_dependency/residuals_manifest_creation_reads_the_pilot_state_not_its_own
    """
    pilot = _running_pilot(api)
    validate_error(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="GAC_CARBON", mass_kg=300.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_PILOT_NOT_COMPLETED,
        422,
    )

    complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=1.85,
        bed_volumes_treated=25000.00,
        spent_media_kg=800.00,
    )
    manifest = validate_success(
        api.create_residuals_manifest(
            f.manifest_payload(pilot["id"], media_type="GAC_CARBON", mass_kg=300.00),
            TREATMENT_ENGINEER_HEADERS,
        ),
        201,
    )

    assert_status(manifest, "DRAFT")
    assert_decimal(manifest["mass_kg"], 300.00, label="mass_kg")
    assert_is_null(manifest, "waste_classification")

    stored = read_pilot(api, pilot["id"])
    assert_status(stored, "COMPLETED")
    assert_decimal(stored["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(stored["unmanifested_media_kg"], 500.00, label="unmanifested_media_kg")
    assert_total_count(
        api.list_residuals_manifests(
            TREATMENT_ENGINEER_HEADERS, params={"pilot_test_id": pilot["id"]}
        ),
        1,
    )
