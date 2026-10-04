"""Producer licensing: issue/revoke count conservation, the suspension gate,
license state guards, the clock-driven expiry sweep, and window rules."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
    make_producer_user_headers,
    make_state_regulator_headers,
    validate_error,
    validate_paginated,
)

STAFF = TEST_USERS["association_staff_headers"]

LIFE_WINDOW = ("2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z")


class TestLicensing:
    def test_license_issue_revoke_count_invariant(self, api):
        """PRD §3.6: "Issuance moves the license from `APPLIED` to `ISSUED`, adds one to the producer's `active_license_count`, and increments the license's `version`."
        PRD §3.6: "Revocation is the same regulator's inverse act on an `ISSUED` license (`ERR_LICENSE_NOT_ISSUED`, 409), moving it to the terminal `REVOKED`, subtracting one from `active_license_count`, and incrementing `version`."
        PRD §3.6: "The producer's `active_license_count` starts at 0 and is maintained by the license lifecycle below."

        Design: Difficulty/compensating_invariant/license_issue_revoke_count_invariant
        """
        state = fixtures.create_state(api, code="CA")
        producer = fixtures.create_producer(api, npn="P-2", home_state_code="CA")
        assert producer["active_license_count"] == 0
        license_row = fixtures.create_license(
            api, producer, state["code"], license_class="LIFE",
            effective_from=LIFE_WINDOW[0], valid_until=LIFE_WINDOW[1],
        )
        issued = fixtures.issue_license(api, license_row["id"], state)
        assert issued["status"] == "ISSUED"
        assert fixtures.read_producer(api, producer["id"])["active_license_count"] == 1
        revoked = fixtures.revoke_license(api, license_row["id"], state)
        assert revoked["status"] == "REVOKED"
        assert fixtures.read_producer(api, producer["id"])["active_license_count"] == 0, (
            "the compensating revoke restores the count exactly"
        )

    def test_license_issue_blocked_when_state_suspended(self, api):
        """PRD §3.6: "Two checks follow in order: the license must be `APPLIED` (`ERR_LICENSE_NOT_APPLIED`, 409), and the licensing state must not be `SUSPENDED` (`ERR_STATE_SUSPENDED`, 422) — an accreditation failure (§3.3) therefore freezes a department's licensing pipeline."

        Design: Difficulty/cross_entity_state_dependency/license_issue_blocked_when_state_suspended
        """
        state = fixtures.create_state(api, code="CA")
        state = fixtures.drive_state_to(api, state["id"], "SUSPENDED")
        assert state["accreditation_status"] == "SUSPENDED"
        producer = fixtures.create_producer(api, npn="P-1", home_state_code="CA")
        license_row = fixtures.create_license(
            api, producer, state["code"], license_class="LIFE",
            effective_from=LIFE_WINDOW[0], valid_until=LIFE_WINDOW[1],
        )
        resp = api.issue_license(
            license_row["id"], make_state_regulator_headers(state["id"])
        )
        validate_error(resp, ApiErrorId.ERR_STATE_SUSPENDED)
        licenses, _meta = validate_paginated(
            api.list_licenses(producer["id"], STAFF)
        )
        assert len(licenses) == 1
        assert licenses[0]["status"] == "APPLIED", "the rejected issue changes nothing"

    def test_license_state_errors(self, api):
        """PRD §3.6: "Revocation is the same regulator's inverse act on an `ISSUED` license (`ERR_LICENSE_NOT_ISSUED`, 409)"
        PRD §3.6: "the license must be `APPLIED` (`ERR_LICENSE_NOT_APPLIED`, 409)"

        Design: Corner/state_machines/license_state_errors
        """
        state = fixtures.create_state(api, code="CA")
        producer = fixtures.create_producer(api, npn="P-11", home_state_code="CA")
        license_row = fixtures.create_license(
            api, producer, state["code"], license_class="LIFE",
            effective_from=LIFE_WINDOW[0], valid_until=LIFE_WINDOW[1],
        )
        regulator = make_state_regulator_headers(state["id"])
        resp = api.revoke_license(license_row["id"], regulator)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ISSUED)
        issued = fixtures.issue_license(api, license_row["id"], state)
        assert issued["status"] == "ISSUED"
        resp = api.issue_license(license_row["id"], regulator)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_APPLIED)
        revoked = fixtures.revoke_license(api, license_row["id"], state)
        assert revoked["status"] == "REVOKED"
        resp = api.revoke_license(license_row["id"], regulator)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ISSUED)

    def test_license_auto_expires_on_clock_advance(self, api):
        """PRD §3.6: "Finally, the logical clock itself is a lifecycle actor: when the clock is advanced strictly past a license's `valid_until`, the license moves from `ISSUED` to the terminal `EXPIRED`, subtracting one from the producer's `active_license_count` and incrementing the license's `version`. A license whose `valid_until` equals the current clock instant has not yet expired; the clock must pass it."

        Design: Corner/state_machines/license_auto_expires_on_clock_advance
        """
        bundle = fixtures.setup_issued_license(
            api, npn="P-12", state_code="CA", license_class="HEALTH",
            effective_from="2027-01-01T00:00:00Z",
            valid_until="2027-06-30T00:00:00Z",
        )
        assert bundle.license["status"] == "ISSUED"
        assert bundle.producer["active_license_count"] == 1
        fixtures.advance_clock(api, "2027-07-01T00:00:00Z")
        licenses, _meta = validate_paginated(
            api.list_licenses(bundle.producer["id"], STAFF)
        )
        assert len(licenses) == 1
        assert licenses[0]["id"] == bundle.license["id"]
        assert licenses[0]["status"] == "EXPIRED", (
            "the clock swept the license once past valid_until"
        )
        producer = fixtures.read_producer(api, bundle.producer["id"])
        assert producer["active_license_count"] == 0

    def test_license_window_overlap_class_scoped(self, api):
        """PRD §3.6: "For the same (`producer_id`, `state_code`, `license_class`) combination, the new window must not intersect the window of any existing license in `APPLIED` or `ISSUED` status, and because these intervals are closed, two windows that merely touch at an endpoint already count as overlapping (`ERR_LICENSE_WINDOW_OVERLAP`, 409)."

        Design: Corner/validations/license_window_overlap_class_scoped
        """
        state = fixtures.create_state(api, code="CA")
        producer = fixtures.create_producer(api, npn="P-13", home_state_code="CA")
        first = fixtures.create_license(
            api, producer, state["code"], license_class="LIFE",
            effective_from=LIFE_WINDOW[0], valid_until=LIFE_WINDOW[1],
        )
        assert first["status"] == "APPLIED"
        resp = api.create_license(
            factories.license_payload(
                producer["id"], state["code"], license_class="LIFE",
                effective_from="2027-06-01T00:00:00Z",
                valid_until="2028-06-01T00:00:00Z",
            ),
            make_producer_user_headers(producer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_OVERLAP)
        # The identical window under a different class is a different scope.
        second = fixtures.create_license(
            api, producer, state["code"], license_class="HEALTH",
            effective_from=LIFE_WINDOW[0], valid_until=LIFE_WINDOW[1],
        )
        assert second["status"] == "APPLIED"

    def test_license_window_inverted_returns_invalid_request(self, api):
        """PRD §3.6: "The window from `effective_from` to `valid_until` is a closed interval — both endpoints are inside the license's life — and `valid_until` must be strictly after `effective_from` (`ERR_INVALID_REQUEST`, 400)."

        Design: Corner/entities/license_window_inverted_returns_invalid_request
        """
        state = fixtures.create_state(api, code="CA")
        producer = fixtures.create_producer(api, npn="P-10", home_state_code="CA")
        resp = api.create_license(
            factories.license_payload(
                producer["id"], state["code"], license_class="LIFE",
                effective_from="2028-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
            ),
            make_producer_user_headers(producer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
