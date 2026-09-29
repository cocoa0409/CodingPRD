"""Required fields, declared defaults and computed-versus-client-supplied
fields on partner registration and complaint intake."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_complaint_payload,
    create_partner_payload,
    file_complaint,
    is_valid_uuid,
    read_partner,
    validate_error,
    validate_paginated,
    validate_success,
    CO,
    PO,
)


def _no_partner_was_persisted():
    rows, meta = validate_paginated(api_client.list_partners(PO))
    assert rows == []
    assert meta["total_count"] == 0


class TestPartnerCreateSchema:
    def test_omitting_the_business_model_is_a_schema_failure_that_persists_nothing(self):
        """All required body fields are present, every enum value is a recognised member, every
        number lies inside the range declared for that field, every string lies inside its declared
        length, and `limit` and `offset` lie inside the pagination bounds of §2.3. Any failure is
        `ERR_VALIDATION` (422).

        Design: Corner/entities/partner_create_missing_business_model_returns_validation
        """
        payload = create_partner_payload(
            legal_name="Omission Fintech Inc",
            funding_stage="SEED",
            months_runway=6,
            disclosed_complaints_per_10k=0.00,
            end_user_account_count=0,
        )
        payload.pop("business_model")
        validate_error(
            api_client.create_partner(payload, PO), ApiErrorId.ERR_VALIDATION, 422
        )
        _no_partner_was_persisted()

    def test_a_closed_enum_and_a_bounded_number_are_both_rejected_rather_than_coerced(self):
        """A `ProgramOfficer` registers a prospective fintech by supplying its registered
        `legal_name` — between 1 and 120 characters and not blank — together with the
        `business_model` under which it intends to operate (`LENDING`, `DEPOSIT_WALLET`,
        `CARD_ISSUING` or `PAYMENT_FACILITATION`), its `funding_stage` (`SEED`, `SERIES_A`,
        `SERIES_B_PLUS` or `PUBLIC`), its self-declared `months_runway` (a whole number from 0
        through 120 inclusive) and its self-disclosed pre-onboarding consumer complaint history as
        `disclosed_complaints_per_10k`, a number from 0 through 10000 inclusive carrying two decimal
        places.

        Design: Corner/entities/partner_create_with_an_out_of_enum_funding_stage_returns_validation
        """
        validate_error(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Bad Enum Fintech Inc",
                    business_model="LENDING",
                    funding_stage="SERIES_C",
                    months_runway=24,
                    disclosed_complaints_per_10k=5.00,
                    end_user_account_count=100,
                ),
                PO,
            ),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        validate_error(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Out Of Range Fintech Inc",
                    business_model="LENDING",
                    funding_stage="SEED",
                    months_runway=121,
                    disclosed_complaints_per_10k=5.00,
                    end_user_account_count=100,
                ),
                PO,
            ),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        _no_partner_was_persisted()

    def test_the_only_optional_body_field_defaults_to_null_and_a_zero_census_floors_the_denominator(self):
        """The denominator is `end_user_account_count`, or 1 if that value is smaller than 1. A
        partner that has never filed a census therefore has a denominator floor of 1, so a single
        complaint alone drives the rate to 10000 basis points.

        Design: Corner/entities/partner_create_omitting_optional_fields_applies_declared_defaults
        """
        partner = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Bare Minimum Pay Inc",
                    business_model="PAYMENT_FACILITATION",
                    funding_stage="SEED",
                    months_runway=0,
                    disclosed_complaints_per_10k=0.00,
                    end_user_account_count=0,
                ),
                PO,
            ),
            201,
        )
        assert partner["parent_partner_id"] is None, "the omitted optional field stores null"
        assert partner["end_user_account_count"] == 0, "a supplied zero is accepted, not treated as absent"
        assert partner["status"] == "PROSPECT"
        assert partner["oversight_posture"] == "OPEN"
        assert partner["capability_tier"] == "UNRATED"
        assert partner["complaint_rate_bps"] == 0

        file_complaint(
            partner["id"],
            channel="EMAIL",
            category="SERVICING",
            severity="LOW",
            received_at="2026-07-06T00:00:00Z",
            narrative="no reply to the email thread about a duplicate charge",
        )
        assert read_partner(partner["id"])["complaint_rate_bps"] == 10000


class TestComplaintIntakeFields:
    def test_the_deadline_and_the_handling_owner_are_derived_not_client_supplied(self):
        """`handling_owner` is copied from the `dispute_owner` of the partner's `EXECUTED` program
        agreement, so the contractual allocation of dispute handling is frozen onto each complaint as
        it arrives; when no executed agreement exists for that partner, `handling_owner` defaults to
        `BANK`.

        Design: Corner/entities/complaint_computed_fields_are_derived_and_never_client_supplied
        """
        partner = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Northbeam Pay Inc",
                    business_model="CARD_ISSUING",
                    funding_stage="SERIES_B_PLUS",
                    months_runway=24,
                    disclosed_complaints_per_10k=12.50,
                    end_user_account_count=100000,
                ),
                PO,
            ),
            201,
        )
        assert partner["status"] == "PROSPECT", "no agreement of any kind exists yet"

        complaint = validate_success(
            api_client.create_complaint(
                create_complaint_payload(
                    partner["id"],
                    channel="CFPB_PORTAL",
                    category="FEES",
                    severity="MEDIUM",
                    received_at="2026-07-20T09:30:00Z",
                    narrative="Monthly maintenance fee charged twice in July.",
                ),
                CO,
            ),
            201,
        )
        assert_same_instant(
            complaint["response_due_at"], "2026-08-04T09:30:00.000Z", "response_due_at"
        )
        assert complaint["handling_owner"] == "BANK"
        assert complaint["status"] == "RECEIVED"
        assert complaint["root_cause_code"] is None
        assert complaint["escalation_count"] == 0
        assert complaint["redress_cents"] == 0
        assert complaint["resolved_at"] is None

        after = read_partner(partner["id"])
        assert after["total_complaint_count"] == 1
        assert after["open_complaint_count"] == 1
        assert after["complaint_rate_bps"] == 0, (
            "one complaint over 100000 end-user accounts rounds to 0 basis points"
        )

    def test_system_owned_fields_ignore_whatever_the_create_body_carries(self):
        """The complaint is stored in `RECEIVED` with `root_cause_code` null, `escalation_count` at
        0, `redress_cents` at 0, and `resolved_at` null.

        Design: Corner/entities/complaint_system_fields_are_server_generated_and_extra_field_client_input_ignored
        """
        partner = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Northbeam Pay Inc",
                    business_model="CARD_ISSUING",
                    funding_stage="SERIES_B_PLUS",
                    months_runway=24,
                    disclosed_complaints_per_10k=12.50,
                    end_user_account_count=100000,
                ),
                PO,
            ),
            201,
        )
        payload = create_complaint_payload(
            partner["id"],
            channel="BANK_CALL_CENTER",
            category="SERVICING",
            severity="LOW",
            received_at="2026-07-02T12:00:00Z",
            narrative="Call centre could not locate the account.",
        )
        payload.update(
            {
                "status": "RESOLVED",
                "resolved_at": "2026-07-03T00:00:00Z",
                "escalation_count": 7,
                "version": 99,
            }
        )
        complaint = validate_success(api_client.create_complaint(payload, PO), 201)

        assert complaint["status"] == "RECEIVED", "the client cannot dictate the landing state"
        assert complaint["resolved_at"] is None
        assert complaint["escalation_count"] == 0
        assert complaint["version"] == 1
        assert_same_instant(
            complaint["response_due_at"], "2026-08-01T12:00:00.000Z", "response_due_at"
        )
        assert is_valid_uuid(complaint["id"])
        assert complaint["created_at"] is not None
        assert complaint["updated_at"] is not None
