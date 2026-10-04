"""Grade catalog corners (PRD §3.1)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_error,
    make_mill, create_grade_payload,
)

MET = TEST_USERS["metallurgist_headers"]


def test_grade_mn_max_below_mn_min_returns_invalid_request():
    """PRD §3.1: "The chemistry band is defined by a strictly positive `cu_max_pct`,
    a non-negative `mn_min_pct`, and an `mn_max_pct` at least equal to `mn_min_pct`."

    Design: Corner/entities/grade_mn_max_below_mn_min_returns_invalid_request
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    resp = api_client.create_grade(
        mill["id"],
        create_grade_payload(grade_code="BAD-BAND", mn_min_pct=0.010, mn_max_pct=0.005),
        MET,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
