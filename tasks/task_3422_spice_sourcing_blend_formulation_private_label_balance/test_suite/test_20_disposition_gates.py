"""Disposition gates: segregation of duties, latest-FAIL, suite completeness."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_supplier, create_received_lot, post_test, disposition_lot,
    get_lot, make_quality_manager_headers,
)


def _oregano_lot():
    supplier = create_supplier()
    return create_received_lot(supplier["id"], spice_code="OREGANO",
                               origin_region="Lesvos", quantity_kg=40,
                               flavor_intensity_units=60.0,
                               moisture_pct=9.0, cost_per_kg_cents=150)


class TestSegregationOfDuties:
    def test_disposition_segregation_of_duties_forbidden(self, api):
        """PRD §3.2: "Every disposition — accept, quarantine, or reject — is
        subject to a hard segregation of duties: if any safety test on the lot
        carries an `analyst_user_id` equal to the dispositioning manager's
        `X-User-ID`, the action is rejected with `ERR_DISPOSITION_FORBIDDEN`
        (HTTP 403); the person who tested a lot may never disposition it."

        The rule keys on identity, not role: a QualityManager whose X-User-ID
        matches the posting analyst is forbidden; a different manager succeeds.

        Design: Corner/validations/disposition_segregation_of_duties_forbidden
        """
        lot = _oregano_lot()
        post_test(lot["id"], "MICRO", 40000, analyst_id="qa-9")
        resp = api_client.disposition_lot(
            lot["id"], {"action": "QUARANTINE"},
            make_quality_manager_headers("qa-9"))
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_FORBIDDEN)
        quarantined = disposition_lot(lot["id"], "QUARANTINE",
                                      manager_id="qm-2")
        assert quarantined["status"] == "QUARANTINED"


class TestAcceptGates:
    def test_lot_has_failing_test_blocks_accept(self, api):
        """PRD §3.2: "An accept then faces two further gates, evaluated after
        the segregation check and in this order: first, the latest safety test
        of each test type on the lot (latest by `created_at`) must not be a
        `FAIL`, else `ERR_LOT_HAS_FAILING_TEST` (HTTP 409); second, the lot
        must carry at least one recorded `PASS` for each member of the
        required suite — `MICRO`, `ADULTERANT_SCREEN`, and `MOISTURE` — else
        `ERR_TEST_SUITE_INCOMPLETE` (HTTP 409)."

        With a MICRO FAIL on record (and no MICRO PASS), the safety gate —
        evaluated first — is the reported error.

        Design: Corner/validations/lot_has_failing_test_blocks_accept
        """
        lot = _oregano_lot()
        failing = post_test(lot["id"], "MICRO", 200000)
        assert failing["result"] == "FAIL"
        post_test(lot["id"], "ADULTERANT_SCREEN", 0.5)
        post_test(lot["id"], "MOISTURE", 8.0)
        resp = api_client.disposition_lot(
            lot["id"], {"action": "ACCEPT"},
            TEST_USERS["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_LOT_HAS_FAILING_TEST)
        assert get_lot(lot["id"])["status"] == "IN_TEST"

    def test_accept_requires_full_test_suite(self, api):
        """PRD §3.2: "the lot must carry at least one recorded `PASS` for each
        member of the required suite — `MICRO`, `ADULTERANT_SCREEN`, and
        `MOISTURE` — else `ERR_TEST_SUITE_INCOMPLETE` (HTTP 409)."

        MICRO + MOISTURE PASS alone is incomplete; posting the missing
        ADULTERANT_SCREEN PASS then lets the same ACCEPT succeed.

        Design: Corner/validations/accept_requires_full_test_suite
        """
        lot = _oregano_lot()
        post_test(lot["id"], "MICRO", 40000)
        post_test(lot["id"], "MOISTURE", 9.0)
        resp = api_client.disposition_lot(
            lot["id"], {"action": "ACCEPT"},
            TEST_USERS["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_TEST_SUITE_INCOMPLETE)
        post_test(lot["id"], "ADULTERANT_SCREEN", 0.5)
        accepted = disposition_lot(lot["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
