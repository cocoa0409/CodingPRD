"""Error catalog claims: per-entity 404 identifiers and the shared error envelope."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_ADAPTIVE_REVIEW_NOT_FOUND,
    ERR_ALLOCATION_RUN_NOT_FOUND,
    ERR_CREDIT_BATCH_NOT_FOUND,
    ERR_CREDIT_TRANSACTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MONITORING_SAMPLE_NOT_FOUND,
    ERR_PERMIT_NOT_FOUND,
    ERR_PRACTICE_PROJECT_NOT_FOUND,
    ERR_PRODUCER_NOT_FOUND,
    ERR_REACH_NOT_FOUND,
    ERR_SOURCE_ASSESSMENT_NOT_FOUND,
    ERR_TMDL_ASSESSMENT_NOT_FOUND,
    ERR_WATERSHED_NOT_FOUND,
)
from test_helpers.assertions import assert_error_envelope, assert_request_metadata
from test_helpers.constants import UNKNOWN_UUIDS, UNKNOWN_UUID_FF
from test_helpers.test_users import ADMIN, ANALYST, PERMIT_WRITER, REGISTRY


def test_every_entity_reports_its_own_not_found_identifier(api):
    """Eleven single-resource reads of unused ids name eleven distinct error ids.

    "The path resource exists — `ERR_<RESOURCE>_NOT_FOUND`, 404."

    Design: Corner/errors/unknown_ids_across_every_entity_return_their_own_not_found_error
    """
    (
        reach_id,
        source_id,
        run_id,
        permit_id,
        producer_id,
        project_id,
        batch_id,
        txn_id,
        review_id,
        assessment_id,
        sample_id,
    ) = UNKNOWN_UUIDS

    probes = (
        (api.get_reach(reach_id, ANALYST), ERR_REACH_NOT_FOUND),
        (api.get_source_assessment(source_id, ANALYST), ERR_SOURCE_ASSESSMENT_NOT_FOUND),
        (api.get_allocation_run(run_id, ANALYST), ERR_ALLOCATION_RUN_NOT_FOUND),
        (api.get_permit(permit_id, PERMIT_WRITER), ERR_PERMIT_NOT_FOUND),
        (api.get_producer(producer_id, REGISTRY), ERR_PRODUCER_NOT_FOUND),
        (api.get_practice_project(project_id, REGISTRY), ERR_PRACTICE_PROJECT_NOT_FOUND),
        (api.get_credit_batch(batch_id, REGISTRY), ERR_CREDIT_BATCH_NOT_FOUND),
        (api.get_credit_transaction(txn_id, REGISTRY), ERR_CREDIT_TRANSACTION_NOT_FOUND),
        (api.get_adaptive_review(review_id, ADMIN), ERR_ADAPTIVE_REVIEW_NOT_FOUND),
        (api.get_tmdl_assessment(assessment_id, ANALYST), ERR_TMDL_ASSESSMENT_NOT_FOUND),
        (api.get_monitoring_sample(sample_id, ANALYST), ERR_MONITORING_SAMPLE_NOT_FOUND),
    )

    for response, expected_error in probes:
        validate_error(response, expected_error, 404)
        body = response.json()
        assert body["response_type"] == "error", body
        assert isinstance(body["data"]["message"], str), body
        assert body["data"]["message"].strip(), body


def test_a_shape_failure_and_a_lookup_failure_share_one_error_envelope(api):
    """Both failures carry `error_id`, `message` and the request metadata, and nothing else.

    "An error response has `response_type` of `"error"` and a `data` object holding
    an `error_id` and a human-readable `message`."

    Design: Corner/errors/error_envelope_carries_the_error_id_and_message_with_request_metadata
    """
    shape_failure = api.create_watershed(
        {
            "name": "No Codes Watershed",
            "state_code": "OH",
            "pollutant": "TOTAL_PHOSPHORUS",
            "baseline_year": 2020,
            "baseline_load_lbs_yr": 120000.00,
            "eligible_zone_codes": ["Z1"],
        },
        ADMIN,
    )

    validate_error(shape_failure, ERR_INVALID_REQUEST, 422)
    shape_body = shape_failure.json()
    assert_error_envelope(shape_body, ERR_INVALID_REQUEST)
    assert_request_metadata(shape_body)
    assert set(shape_body.keys()) == {"response_type", "data", "meta"}, shape_body
    assert "total_count" not in shape_body["meta"], shape_body

    lookup_failure = api.get_watershed(UNKNOWN_UUID_FF, ADMIN)

    validate_error(lookup_failure, ERR_WATERSHED_NOT_FOUND, 404)
    lookup_body = lookup_failure.json()
    assert_error_envelope(lookup_body, ERR_WATERSHED_NOT_FOUND)
    assert_request_metadata(lookup_body)
    assert set(lookup_body.keys()) == {"response_type", "data", "meta"}, lookup_body
    assert "total_count" not in lookup_body["meta"], lookup_body
