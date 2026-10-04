"""Term creation shape rules, the term clock gate, and missing-resource reads."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, create_term_payload,
    create_term, set_clock, assert_term,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def test_term_missing_required_field_returns_invalid_request():
    """PRD §2.7: "Required fields must be present, enum values valid, and
    types correct; otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A `RegistrarAdmin` creates a term by supplying its `name` (a
    label such as "2026 Fall A"), the `start_date` on which instruction
    begins, the `add_drop_end_date` after which roster adds are no longer
    allowed, the `census_date` at which the enrollment snapshot for aid is
    taken, and the `end_date` on which the term closes."

    Design: Corner/entities/term_missing_required_field_returns_invalid_request
    """
    payload = {
        "name": "T",
        "start_date": "2026-10-05",
        "add_drop_end_date": "2026-10-12",
        "end_date": "2026-12-13",
        # census_date omitted
    }
    resp = api_client.create_term(payload, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_term_date_ordering_violation_returns_term_date_invalid():
    """PRD §3.1: "The four dates must obey a strict ordering: `start_date`
    strictly before `add_drop_end_date`, `add_drop_end_date` on or before
    `census_date`, and `census_date` strictly before `end_date`; a term whose
    dates violate this ordering is rejected with `ERR_TERM_DATE_INVALID`."

    Design: Corner/entities/term_date_ordering_violation_returns_term_date_invalid
    """
    payload = create_term_payload(
        add_drop_end_date="2026-10-20",  # after census_date -> violates ordering
        census_date="2026-10-19",
    )
    resp = api_client.create_term(payload, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_TERM_DATE_INVALID)


def test_term_advance_before_clock_gate_rejected():
    """PRD §3.1: "Opening enrollment is permitted only once the logical clock
    has reached the point thirty days before `start_date`; attempting it
    earlier is rejected with `ERR_TERM_CLOCK_NOT_REACHED`."
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and the server must not fall back to wall-clock
    time before the first clock-setting call arrives."

    Design: Corner/validations/term_advance_clock_gate
    """
    term = create_term()  # start_date 2026-10-05; start-30d == 2026-09-05
    # Clock untouched at startup default 2026-09-01T00:00:00Z < 2026-09-05.
    resp = api_client.advance_term(term["id"], "ENROLLMENT_OPEN", REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_TERM_CLOCK_NOT_REACHED)


def test_term_advance_at_exactly_clock_gate_succeeds():
    """PRD §3.1: "Opening enrollment is permitted only once the logical clock
    has reached the point thirty days before `start_date`; attempting it
    earlier is rejected with `ERR_TERM_CLOCK_NOT_REACHED`."

    Design: Corner/validations/term_advance_clock_gate
    """
    term = create_term()
    set_clock("2026-09-05T00:00:00Z")  # exactly start_date - 30 days
    resp = api_client.advance_term(term["id"], "ENROLLMENT_OPEN", REGISTRAR)
    data = validate_success(resp, expected_status=200)
    assert_term(data)
    assert data["status"] == "ENROLLMENT_OPEN", (
        f"advance at exactly start-30d must succeed; got {data['status']}")


def test_get_nonexistent_enrollment_returns_not_found():
    """PRD §2.7: "Referenced resources must exist, validated left to right;
    otherwise `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_enrollment_returns_not_found
    """
    resp = api_client.get_enrollment(NON_EXISTENT_UUID, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
