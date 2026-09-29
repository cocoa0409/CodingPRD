"""Error reporting itself: which rung answers when two are violated at once, and the shape
every refusal takes on the wire.

The first test holds one call that breaks both the linkage rung and the sufficiency rung and
watches the higher rung answer first; the second walks a not-found, a malformed body and a
role denial through the same envelope.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import (
    ERR_BASELINE_ENROLLMENT_MISMATCH,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NO_QUALIFYING_DATA,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import assert_error_envelope
from test_helpers.constants import (
    BASELINE_HISTORICAL_DATA,
    CROP_YEAR_2026,
    METHOD_MODEL,
    UNKNOWN_UUIDS,
)
from test_helpers.factories import (
    baseline_payload,
    grower_payload,
    quantification_run_payload,
)
from test_helpers.test_users import ADMIN_HEADERS


def test_a_borrowed_baseline_answers_before_the_missing_packet_set(scenario):
    """A run naming the sibling enrollment's approved baseline over an enrollment with no
    passed packet at all breaks two rungs at once; the linkage rung answers, and only once the
    baseline is corrected does the same call surface the emptiness of the packet set.

    PRD §2.10: "The baseline named on a quantification run belongs to the same enrollment and
    is `APPROVED`"

    PRD §3.6: "If that collection is empty, the run is refused with
    `ERR_NO_QUALIFYING_DATA`."

    Design: Corner/errors/baseline_from_another_enrollment_is_refused_before_data_sufficiency_is_checked
    """
    scenario.active_enrollment()
    enrollment_a = scenario.enrollment_id
    baseline_a = scenario.baseline_id
    _enrollment_b, baseline_b, _field_b = scenario.additional_active_enrollment()
    observed = scenario.reload_enrollment(enrollment_a)["version"]

    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                enrollment_a, baseline_b["id"], observed, CROP_YEAR_2026, METHOD_MODEL
            ),
            ADMIN_HEADERS,
        ),
        ERR_BASELINE_ENROLLMENT_MISMATCH,
        422,
    )

    # The same call with the enrollment's own baseline now reaches the next rung down.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                enrollment_a, baseline_a, observed, CROP_YEAR_2026, METHOD_MODEL
            ),
            ADMIN_HEADERS,
        ),
        ERR_NO_QUALIFYING_DATA,
        422,
    )

    # Neither refusal bumped the version, so the same observed value was still current.
    assert scenario.reload_enrollment(enrollment_a)["version"] == observed
    _runs, meta = validate_paginated(
        scenario.api.list_quantification_runs({"enrollment_id": enrollment_a}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 0


def test_three_error_classes_share_one_envelope(scenario):
    """A missing row, a malformed body and a role denial all answer with the same envelope: an
    error response type, a meta block of exactly two keys and a data object holding nothing but
    the code and the message.

    PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope
    format"

    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/every_error_class_returns_the_declared_error_envelope
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.file_reference_history()
    scenario.create_enrollment()
    observed = scenario.enrollment_version

    not_found = scenario.api.get_enrollment(UNKNOWN_UUIDS["enrollment"], ADMIN_HEADERS)
    validate_error(not_found, ERR_ENROLLMENT_NOT_FOUND, 404)
    assert_error_envelope(not_found.json(), ERR_ENROLLMENT_NOT_FOUND)

    malformed = grower_payload()
    malformed.pop("legal_name")
    invalid = scenario.api.create_grower(malformed, ADMIN_HEADERS)
    validate_error(invalid, ERR_INVALID_REQUEST, 400)
    assert_error_envelope(invalid.json(), ERR_INVALID_REQUEST)

    # A real enrollment addressed by a role that holds no baseline proposal at all.
    denied = scenario.api.propose_baseline(
        scenario.enrollment_id,
        baseline_payload(observed, BASELINE_HISTORICAL_DATA),
        scenario.grower_auth,
    )
    validate_error(denied, ERR_UNAUTHORIZED, 403)
    assert_error_envelope(denied.json(), ERR_UNAUTHORIZED)
    assert scenario.baselines_of_enrollment() == []

    for response in (not_found, invalid, denied):
        body = response.json()
        assert set(body["data"]) == {"error_id", "message"}
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
