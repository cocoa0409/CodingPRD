"""Client audits: the thirty-day cooldown, the absolute re-identification
prohibition, suspension cascades on audit completion, and reinstatement."""
from test_helpers import (
    ApiErrorId,
    create_client,
    request_audit,
    setup_suspended_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PA
from test_helpers.test_users import make_manufacturer_client_headers


class TestAuditCooldown:
    def test_window_29_days_after_completed_audit_rejected(self, api):
        """PRD §3.8: "The new window must respect a thirty-day cooldown measured from the most
        recently completed audit of the same client: the new `window_start_date` must fall at
        least 30 whole days after the greatest `window_end_date` among that client's `COMPLETED`
        audit events, with ties on the end date broken by taking the latest-`created_at` event;
        exactly 30 days passes, since the rule is \"at least\"."

        Design: Difficulty/resource_temporal_overlap/audit_cooldown_thirty_day_buffer
        """
        from test_helpers import complete_audit

        client = create_client(name="Client Aud")
        complete_audit(client["id"], window_start_date="2026-03-01",
                       window_end_date="2026-03-31")
        resp = api.request_audit(
            client["id"],
            {
                "window_start_date": "2026-04-29",
                "window_end_date": "2026-05-15",
                "purpose": "AUDIT_COMPLIANCE",
            },
            make_manufacturer_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_COOLDOWN_ACTIVE)

    def test_window_exactly_30_days_after_completed_audit_allowed(self, api):
        """PRD §3.8: "The new window must respect a thirty-day cooldown measured from the most
        recently completed audit of the same client: the new `window_start_date` must fall at
        least 30 whole days after the greatest `window_end_date` among that client's `COMPLETED`
        audit events, with ties on the end date broken by taking the latest-`created_at` event;
        exactly 30 days passes, since the rule is \"at least\"."

        Design: Difficulty/resource_temporal_overlap/audit_cooldown_thirty_day_buffer
        """
        from test_helpers import complete_audit

        client = create_client(name="Client Aud")
        complete_audit(client["id"], window_start_date="2026-03-01",
                       window_end_date="2026-03-31")
        audit = validate_success(
            api.request_audit(
                client["id"],
                {
                    "window_start_date": "2026-04-30",
                    "window_end_date": "2026-05-15",
                    "purpose": "AUDIT_COMPLIANCE",
                },
                make_manufacturer_client_headers(client["id"]),
            ),
            expected_status=201,
        )
        assert audit["status"] == "REQUESTED"


class TestReidentificationProhibition:
    def test_reidentification_purpose_refused(self, api):
        """PRD §3.8: "Re-identification of de-identified data is absolutely prohibited — a request
        whose purpose is `REIDENTIFICATION` is refused outright with
        `ERR_REIDENTIFICATION_PROHIBITED` (HTTP 403); a suspended client may not request audits at
        all (`ERR_CLIENT_SUSPENDED`)."

        Design: Corner/errors/reidentification_purpose_audit_rejected
        """
        client = create_client(name="Client ReID")
        resp = api.request_audit(
            client["id"],
            {
                "window_start_date": "2026-10-01",
                "window_end_date": "2026-10-15",
                "purpose": "REIDENTIFICATION",
            },
            make_manufacturer_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REIDENTIFICATION_PROHIBITED)
        rows, meta = validate_paginated(
            api.list_client_audit_events(client["id"], PA)
        )
        assert meta["total_count"] == 0 and rows == []


class TestAuditOutcomeSuspensionCascade:
    def test_reidentification_attempted_suspends_client_and_products(self, api):
        """PRD §3.8: "Completion with `REIDENTIFICATION_ATTEMPTED` is the pipeline's nuclear event:
        the owning client transitions from `ACTIVE` to `SUSPENDED`, and every report product of
        that client in `ACTIVE` status transitions to `SUSPENDED` with it, freezing compilation
        and reissue until a `PlatformAdmin` reinstates the client per §3.1."

        Design: Corner/state_machines/audit_reidentification_outcome_suspends_client_and_products
        """
        from test_helpers import complete_audit, create_methodology, create_product

        methodology = create_methodology(name="M-AUD")
        bad_client = create_client(name="Client Bad")
        good_client = create_client(name="Client Good")
        bad_product = create_product(bad_client["id"], methodology["id"], name="P-BAD")
        good_product = create_product(good_client["id"], methodology["id"], name="P-GOOD")
        bad_audit = complete_audit(
            bad_client["id"], outcome="REIDENTIFICATION_ATTEMPTED",
            window_start_date="2026-03-01", window_end_date="2026-03-15",
        )
        good_audit = complete_audit(
            good_client["id"], outcome="CLEAN",
            window_start_date="2026-03-01", window_end_date="2026-03-15",
        )
        assert bad_audit["status"] == "COMPLETED"
        assert bad_audit["outcome"] == "REIDENTIFICATION_ATTEMPTED"
        assert good_audit["status"] == "COMPLETED"
        assert good_audit["outcome"] == "CLEAN"
        assert validate_success(api.get_client(bad_client["id"], PA))["status"] == "SUSPENDED"
        assert validate_success(api.get_product(bad_product["id"], PA))["status"] == "SUSPENDED"
        assert validate_success(api.get_client(good_client["id"], PA))["status"] == "ACTIVE"
        assert validate_success(api.get_product(good_product["id"], PA))["status"] == "ACTIVE"


class TestSuspendedClientAuditRights:
    def test_suspended_client_cannot_request_audit_until_reinstated(self, api):
        """PRD §3.8: "Re-identification of de-identified data is absolutely prohibited — a request
        whose purpose is `REIDENTIFICATION` is refused outright with
        `ERR_REIDENTIFICATION_PROHIBITED` (HTTP 403); a suspended client may not request audits at
        all (`ERR_CLIENT_SUSPENDED`)."
        PRD §3.1: "A client's `status` is either `ACTIVE` or `SUSPENDED`; suspension arrives only
        as the consequence of an audit outcome (see §3.8), never through a direct administrative
        toggle in the other direction — reinstatement is the administrative act, performed by a
        `PlatformAdmin` on a client whose `status` is `SUSPENDED` (any other state yields
        `ERR_INVALID_STATE`), and it flips every `SUSPENDED` report product of that client back to
        `ACTIVE` while restoring the client itself to `ACTIVE`."

        Design: Corner/errors/suspended_client_blocks_new_audit_request
        """
        client, _products, _audit = setup_suspended_client()
        resp = api.request_audit(
            client["id"],
            {
                "window_start_date": "2026-10-01",
                "window_end_date": "2026-10-15",
                "purpose": "AUDIT_COMPLIANCE",
            },
            make_manufacturer_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED)
        validate_success(api.reinstate_client(client["id"], PA))
        audit = validate_success(
            api.request_audit(
                client["id"],
                {
                    "window_start_date": "2026-10-01",
                    "window_end_date": "2026-10-15",
                    "purpose": "AUDIT_COMPLIANCE",
                },
                make_manufacturer_client_headers(client["id"]),
            ),
            expected_status=201,
        )
        assert audit["status"] == "REQUESTED"
