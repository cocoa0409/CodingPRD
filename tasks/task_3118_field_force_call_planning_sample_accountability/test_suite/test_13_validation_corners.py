"""Validation corner coverage: auth cascade, existence-before-state,
segregation-of-duties, and the return-reason/expiry binding.

Queue B — corner design section ``validations``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import ADMIN_HEADERS, build_user_headers


class TestAuthCascade:
    def test_missing_headers_rejected_even_when_resource_missing(self, api):
        """PRD section 2.1: "A request missing either header, or carrying a role value
        outside this set, is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        (HTTP 400)." PRD section 2.6: "a request that fails both an auth check and a
        business check always surfaces the auth error."

        Design: Corner/validations/error_missing_auth_on_anonymous_call
        """
        response = api.get_territory(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={}
        )
        validate_error(
            response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        )

    def test_undeclared_role_rejected(self, api):
        """PRD section 2.1: "The API recognizes five roles, spelled exactly as
        follows: PlatformAdmin, DistrictManager, FieldRep, ComplianceOfficer, and
        QualityAssurance. A request missing either header, or carrying a role value
        outside this set, is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (HTTP 400)."

        Design: Corner/validations/undeclared_role_returns_unauthorized
        """
        fx.create_region(api)
        response = api.list_regions(
            headers=build_user_headers("some-user", "SuperUser")
        )
        validate_error(
            response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        )

    def test_existence_precedes_state_on_action_endpoint(self, api):
        """PRD section 2.6: "The cascade evaluates, in order: ... (3) existence of
        path-referenced resources, producing ERR_NOT_FOUND; (4) request-body
        well-formedness ...; (5) optimistic-concurrency version match ...; (6)
        state-machine legality of the requested trigger from the entity's current
        state, producing ERR_INVALID_STATE."

        Design: Corner/validations/existence_precedes_state_for_action_on_missing_disbursement
        """
        response = api.capture_signature(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "A" * 40,
            headers=make_field_rep_headers("00000000-0000-0000-0000-000000000000"),
        )
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)


class TestSegregationOfDuties:
    def _setup_custodian_with_manager(self, api):
        region = fx.create_region(api)
        territory = fx.create_territory(api, region["id"])
        manager = fx.create_representative(api, territory["id"])
        custodian = fx.create_representative(
            api, territory["id"], manager_rep_id=manager["id"]
        )
        return manager, custodian

    def test_counter_cannot_be_custodian(self, api):
        """PRD section 3.6: "the counter must differ from the custodian and must also
        differ from the custodian's manager_rep_id, so a rep cannot count their own
        stock and the direct manager cannot serve as the supposedly independent
        counter — either violation is rejected with
        ERR_SEGREGATION_OF_DUTIES_VIOLATION."

        Design: Corner/validations/segregation_counter_cannot_be_custodian_or_custodian_manager
        """
        manager, custodian = self._setup_custodian_with_manager(api)
        response = api.create_count_session(
            f.create_count_session_payload(
                custodian["id"],
                custodian["id"],
                window_start="2026-09-20T00:00:00Z",
                window_end="2026-09-21T00:00:00Z",
            ),
            headers=make_district_manager_headers(manager["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_counter_cannot_be_custodians_manager(self, api):
        """PRD section 3.6: "the counter must differ from the custodian and must also
        differ from the custodian's manager_rep_id, so a rep cannot count their own
        stock and the direct manager cannot serve as the supposedly independent
        counter — either violation is rejected with
        ERR_SEGREGATION_OF_DUTIES_VIOLATION."

        Design: Corner/validations/segregation_counter_cannot_be_custodian_or_custodian_manager
        """
        manager, custodian = self._setup_custodian_with_manager(api)
        response = api.create_count_session(
            f.create_count_session_payload(
                custodian["id"],
                manager["id"],
                window_start="2026-09-20T00:00:00Z",
                window_end="2026-09-21T00:00:00Z",
            ),
            headers=make_district_manager_headers(manager["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_self_transfer_rejected(self, api):
        """PRD section 3.6: "because the sender and receiver must be different people,
        a request naming oneself as receiver is rejected with
        ERR_SEGREGATION_OF_DUTIES_VIOLATION."

        Design: Corner/validations/transfer_sender_equals_receiver_rejected_as_segregation
        """
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        response = api.create_sample_transfer(
            f.create_sample_transfer_payload(
                ctx["sender"]["id"],
                ctx["lot"]["id"],
                3,
                fx.fresh_lot_version(api, ctx["lot"]["id"]),
            ),
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)


class TestReturnReasonBinding:
    def _setup_two_draft_returns(self, api):
        ctx = fx.setup_two_reps_with_lot(
            api, sender_issued=10, lot_quantity=50
        )
        expired = fx.create_draft_return(
            api,
            ctx["sender"],
            ctx["lot"]["id"],
            2,
            return_reason="EXPIRED",
        )
        damaged = fx.create_draft_return(
            api,
            ctx["sender"],
            ctx["lot"]["id"],
            2,
            return_reason="DAMAGED",
        )
        ctx["expired_return"] = expired
        ctx["damaged_return"] = damaged
        return ctx

    def test_expired_reason_requires_past_expiration(self, api):
        """PRD section 3.7: "a return_reason of EXPIRED is only truthful when the
        lot's expiration_date is at or before the logical clock's current time
        (otherwise ERR_RETURN_REASON_MISMATCH)."

        Design: Corner/validations/return_reason_expired_requires_past_expiration_date
        """
        ctx = self._setup_two_draft_returns(api)
        response = api.submit_sample_return(
            ctx["expired_return"]["id"],
            headers=make_field_rep_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_RETURN_REASON_MISMATCH)

    def test_damaged_reason_submits_regardless_of_expiry(self, api):
        """PRD section 3.7: "Submitting the draft moves it to SUBMITTED and enforces
        two checks: the quantity must not exceed the rep's qty_available_forward for
        the lot (otherwise ERR_INSUFFICIENT_BALANCE), and a return_reason of EXPIRED
        is only truthful when the lot's expiration_date is at or before the logical
        clock's current time (otherwise ERR_RETURN_REASON_MISMATCH)."

        Design: Corner/validations/return_reason_expired_requires_past_expiration_date
        """
        ctx = self._setup_two_draft_returns(api)
        data = fx.submit_return(api, ctx["damaged_return"]["id"], ctx["sender"])
        assert data["status"] == "SUBMITTED"
