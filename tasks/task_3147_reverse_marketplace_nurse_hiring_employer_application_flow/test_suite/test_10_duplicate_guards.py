"""Duplicate-guard error surfaces: email, screening, license-number uniqueness."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.factories import create_license_verification_payload
from test_helpers.test_users import make_candidate_headers


class TestLicenseUniqueness:
    def test_duplicate_license_number_per_state(self, api):
        """PRD §3.1: "the state-issued `license_number` (unique within its `license_state`; duplicates rejected with `ERR_DUPLICATE_RESOURCE`)"

        Design: Corner/errors/err_duplicate_license_number_per_state
        """
        fx.set_clock()
        nurse_a = fx.create_draft_nurse(email="nora@x.com")
        fx.add_license(nurse_a, license_number="RN-CA-100")

        nurse_b = fx.create_draft_nurse(email="dup@x.com")

        same_state = api_client.create_license_verification(
            create_license_verification_payload(
                nurse_b["id"], license_number="RN-CA-100", license_state="CA"
            ),
            make_candidate_headers(nurse_b["id"]),
        )
        validate_error(same_state, ApiErrorId.ERR_DUPLICATE_RESOURCE)

        other_state = api_client.create_license_verification(
            create_license_verification_payload(
                nurse_b["id"], license_number="RN-CA-100", license_state="OR"
            ),
            make_candidate_headers(nurse_b["id"]),
        )
        validate_success(other_state, expected_status=201)
