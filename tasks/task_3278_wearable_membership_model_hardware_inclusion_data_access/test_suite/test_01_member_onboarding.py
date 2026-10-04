"""Member lifecycle tests: registration defaults, 404 envelope, term creation
rules, serial uniqueness, FK reverse reachability."""
from test_helpers import (
    ApiErrorId,
    assert_member,
    create_member_payload,
    create_term_payload,
    is_valid_uuid,
    make_member_headers,
    make_platform_admin_headers,
    make_support_headers,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)


class TestMemberOnboarding:
    def test_member_creation_defaults_applied_on_register(self, api, anonymous_headers):
        """PRD: "Registration creates the member with member_status set to ACTIVE,
        wallet_credit_cents at zero, data_sharing_posture at NORMAL, and
        algorithm_ack_release_id null until the member's first acknowledgement
        of an algorithm release."
        PRD: "id is a server-minted UUID with no type prefix."

        Design: Corner/entities/member_creation_defaults_applied
        """
        resp = api.create_member(create_member_payload(), anonymous_headers)
        member = validate_success(resp, expected_status=201)
        assert_member(member)
        assert member["member_status"] == "ACTIVE"
        assert member["wallet_credit_cents"] == 0
        assert member["data_sharing_posture"] == "NORMAL"
        assert member["algorithm_ack_release_id"] is None
        assert member["version"] == 1
        assert is_valid_uuid(member["id"])

    def test_member_creation_fields_readable_immediately(self, api, anonymous_headers):
        """PRD: "Registration creates the member with member_status set to ACTIVE,
        wallet_credit_cents at zero, data_sharing_posture at NORMAL, and
        algorithm_ack_release_id null until the member's first acknowledgement
        of an algorithm release."

        Design: Corner/entities/member_creation_defaults_applied
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        reread = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert reread["member_status"] == "ACTIVE"
        assert reread["wallet_credit_cents"] == 0
        assert reread["data_sharing_posture"] == "NORMAL"

    def test_member_get_not_found_returns_404(self, api, support_headers):
        """PRD: "Path identifiers are then resolved left to right, with a missing
        id surfacing as ERR_NOT_FOUND".

        Design: Corner/entities/member_get_not_found_returns_404
        """
        resp = api.get_member(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", support_headers
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        assert isinstance(err["message"], str) and err["message"]

    def test_member_get_not_found_error_envelope_shape(self, api, support_headers):
        """PRD: "The meta object for error responses contains only api_request_id
        and api_request_timestamp." PRD: "The error_id is a unique,
        machine-readable string that identifies the specific error."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_member(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", support_headers
        )
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestTermCreation:
    def test_term_creation_missing_required_field_rejected(self, api, anonymous_headers):
        """PRD: "request-body well-formedness — required fields present, enum
        values valid, dates parseable — as ERR_INVALID_REQUEST."

        Design: Corner/entities/term_creation_missing_required_field
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        payload = create_term_payload()
        del payload["commitment_months"]
        resp = api.create_term(member["id"], payload, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_term_creation_birth_state(self, api, anonymous_headers):
        """PRD: "The term is born ACTIVE on the day it is created: started_on is
        stamped with today, commitment_end_on is computed as started_on advanced
        by commitment_months calendar months, months_paid starts at zero,
        pause_days_used starts at zero, pause_windows starts empty,
        open_pause_end_on and cancel_fee_charged_cents and last_upgrade_on are
        null."

        Design: Corner/consistency_model/immediate_visibility_of_writes
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        term = validate_success(
            api.create_term(
                member["id"], create_term_payload(), make_member_headers(member["id"])
            ),
            expected_status=201,
        )
        assert term["term_status"] == "ACTIVE"
        assert term["started_on"] == "2026-09-01"
        assert term["commitment_end_on"] == "2027-09-01"
        assert term["months_paid"] == 0
        assert term["pause_days_used"] == 0
        assert term["pause_windows"] == []
        assert term["open_pause_end_on"] is None
        assert term["cancel_fee_charged_cents"] is None
        assert term["last_upgrade_on"] is None

    def test_term_creation_immediately_visible_in_list(self, api, anonymous_headers):
        """PRD: "Once a term exists, the member can list their terms and read back
        the running state — months_paid, pause_days_used, the scheduled and
        historical pause_windows — at any time."

        Design: Corner/consistency_model/immediate_visibility_of_writes
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        term = validate_success(
            api.create_term(
                member["id"], create_term_payload(), make_member_headers(member["id"])
            ),
            expected_status=201,
        )
        data, meta = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert len(data) == 1
        assert data[0]["id"] == term["id"]
        assert data[0]["commitment_end_on"] == "2027-09-01"

    def test_active_term_uniqueness_rejects_second_open_term(self, api, anonymous_headers):
        """PRD: "A member may hold at most one open term: if the member already
        owns a term whose term_status is ACTIVE, PAUSED, or PAST_DUE, a further
        term creation is refused with ERR_ACTIVE_TERM_EXISTS."

        Design: Corner/validations/active_term_uniqueness
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        validate_success(
            api.create_term(
                member["id"], create_term_payload(), make_member_headers(member["id"])
            ),
            expected_status=201,
        )
        resp = api.create_term(
            member["id"],
            create_term_payload(
                plan_name="P2",
                monthly_fee_cents=5000,
                commitment_months=6,
                hardware_tier="BAND_PRO",
                upgrade_eligibility_months=3,
                pause_days_per_term=10,
                cancel_fee_policy="PAID_MONTHS_FLOOR",
                early_cancel_fee_floor_cents=2000,
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_TERM_EXISTS, expected_status=422)


class TestDeviceProvisioning:
    def test_device_serial_uniqueness_enforced(self, api, anonymous_headers):
        """PRD: "Serial numbers are unique across all devices; reusing one is
        rejected with ERR_SERIAL_NUMBER_TAKEN."

        Design: Corner/entities/device_serial_uniqueness_enforced
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        term = validate_success(
            api.create_term(
                member["id"], create_term_payload(), make_member_headers(member["id"])
            ),
            expected_status=201,
        )
        admin = make_platform_admin_headers()
        validate_success(
            api.provision_device(
                {
                    "member_id": member["id"],
                    "term_id": term["id"],
                    "serial_number": "SN-DUP",
                    "hardware_tier": "BAND_STD",
                },
                admin,
            ),
            expected_status=201,
        )
        resp = api.provision_device(
            {
                "member_id": member["id"],
                "term_id": term["id"],
                "serial_number": "SN-DUP",
                "hardware_tier": "BAND_PRO",
            },
            admin,
        )
        validate_error(resp, ApiErrorId.ERR_SERIAL_NUMBER_TAKEN, expected_status=409)

    def test_fk_reverse_reachability_lists(self, api, anonymous_headers, support_headers):
        """PRD: "Anyone with device visibility — the owning member, Support, or a
        PlatformAdmin — can read a device or list devices, optionally narrowed by
        member_id or term_id."
        PRD: "Once a term exists, the member can list their terms and read back
        the running state".

        Design: Corner/entities/fk_reverse_reachability_lists
        """
        member = validate_success(
            api.create_member(create_member_payload(), anonymous_headers),
            expected_status=201,
        )
        term = validate_success(
            api.create_term(
                member["id"], create_term_payload(), make_member_headers(member["id"])
            ),
            expected_status=201,
        )
        device = validate_success(
            api.provision_device(
                {
                    "member_id": member["id"],
                    "term_id": term["id"],
                    "serial_number": "SN-D4",
                    "hardware_tier": "BAND_STD",
                },
                make_platform_admin_headers(),
            ),
            expected_status=201,
        )
        terms, _ = validate_paginated(
            api.list_member_terms(member["id"], make_member_headers(member["id"]))
        )
        assert [t["id"] for t in terms] == [term["id"]]
        devices, _ = validate_paginated(
            api.list_devices(support_headers, params={"member_id": member["id"]})
        )
        assert [d["id"] for d in devices] == [device["id"]]
        assert devices[0]["serial_number"] == "SN-D4"
