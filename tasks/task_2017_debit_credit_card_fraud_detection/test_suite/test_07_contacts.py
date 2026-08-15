"""Verification-contact gap rules: per-account 60-minute buffer, exact boundary."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_manual_alert,
    claim_alert,
    set_clock,
    make_analyst_headers,
)

MANAGER = TEST_USERS["manager_headers"]


class TestContactGapExactMinute:
    def _setup(self, api):
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-BP3", cardholder_name="Bee Three")
        card = create_card(acct["id"], "PT-BP3")
        alert = create_manual_alert(acct["id"], card["id"])
        claim_alert(alert["id"])
        first = validate_success(
            api.create_verification_contact(
                {"alert_id": alert["id"], "channel": "VOICE"},
                make_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        assert first["contact_status"] == "PENDING"
        return acct, card, alert

    def test_contact_at_59_minutes_rejected(self, api):
        """PRD §3.5: "at least 60 minutes must separate this attempt from the
        account's most recent contact, and an attempt landing strictly inside that
        gap is rejected with `ERR_CONTACT_TOO_SOON` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/contact_gap_exact_minute
        """
        _acct, _card, alert = self._setup(api)
        set_clock("2026-08-01T00:59:00Z")
        resp = api.create_verification_contact(
            {"alert_id": alert["id"], "channel": "SMS"},
            make_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_CONTACT_TOO_SOON, expected_status=409)

    def test_contact_at_exactly_60_minutes_allowed(self, api):
        """PRD §3.5: "at least 60 minutes must separate this attempt from the
        account's most recent contact"; "creating it transitions the alert from
        `IN_REVIEW` to `CONTACT_PENDING`".

        Design: Difficulty/boundary_precision_check/contact_gap_exact_minute
        """
        _acct, _card, alert = self._setup(api)
        set_clock("2026-08-01T01:00:00Z")
        created = validate_success(
            api.create_verification_contact(
                {"alert_id": alert["id"], "channel": "SMS"},
                make_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        assert created["contact_status"] == "PENDING"
        current = validate_success(api.get_fraud_alert(alert["id"], MANAGER))
        assert current["alert_status"] == "CONTACT_PENDING"


class TestContactBufferGapOnAccount:
    def _setup_two_alerts(self, api):
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-TO2", cardholder_name="Tee Two")
        card = create_card(acct["id"], "PT-TO2", product_type="DEBIT", network="MASTERCARD")
        a1 = create_manual_alert(acct["id"], card["id"])
        a2 = create_manual_alert(acct["id"], card["id"])
        claim_alert(a1["id"])
        claim_alert(a2["id"])
        validate_success(
            api.create_verification_contact(
                {"alert_id": a1["id"], "channel": "VOICE"},
                make_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        return acct, card, a1, a2

    def test_gap_occupies_account_not_alert(self, api):
        """PRD §3.5: "it enforces a per-account contact gap: at least 60 minutes
        must separate this attempt from the account's most recent contact, and an
        attempt landing strictly inside that gap is rejected with
        `ERR_CONTACT_TOO_SOON` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/contact_buffer_gap_on_account
        """
        _acct, _card, _a1, a2 = self._setup_two_alerts(api)
        set_clock("2026-08-01T00:30:00Z")
        resp = api.create_verification_contact(
            {"alert_id": a2["id"], "channel": "SMS"},
            make_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_CONTACT_TOO_SOON, expected_status=409)

    def test_second_alert_contact_allowed_after_gap(self, api):
        """PRD §3.5: "at least 60 minutes must separate this attempt from the
        account's most recent contact"; "creating it transitions the alert from
        `IN_REVIEW` to `CONTACT_PENDING`".

        Design: Difficulty/resource_temporal_overlap/contact_buffer_gap_on_account
        """
        _acct, _card, _a1, a2 = self._setup_two_alerts(api)
        set_clock("2026-08-01T01:00:00Z")
        created = validate_success(
            api.create_verification_contact(
                {"alert_id": a2["id"], "channel": "SMS"},
                make_analyst_headers("analyst-1"),
            ),
            expected_status=201,
        )
        assert created["contact_status"] == "PENDING"
        current = validate_success(api.get_fraud_alert(a2["id"], MANAGER))
        assert current["alert_status"] == "CONTACT_PENDING"
