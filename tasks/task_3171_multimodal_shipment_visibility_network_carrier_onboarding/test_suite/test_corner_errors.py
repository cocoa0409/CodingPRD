"""Corner probe over the error catalog: left-to-right path existence."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, fixtures
from test_helpers import factories as f
from test_helpers.test_users import make_carrier_rep_headers


def test_error_shipment_not_found_on_nested_events(api):
    """A nonexistent shipment on a nested path fails existence before anything else.

    PRD: "For any endpoint whose path contains multiple resource identifiers,
    the server validates path identifiers strictly left to right: each
    identifier must resolve to an existing resource before the next identifier
    to its right is examined, and the request is rejected with the not-found
    error for the first identifier that fails."
    Design: Corner/errors/error_shipment_not_found_on_nested_events
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)

    response = api.ingest_event(
        "99999999-8888-4777-8666-555555555555",
        f.event_payload("2026-09-01T06:00:00Z", "DEPARTED"),
        make_carrier_rep_headers("11111111-2222-4333-8444-555555555555"),
    )
    validate_error(response, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)
