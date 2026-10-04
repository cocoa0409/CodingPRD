"""Market opening: territories, wholesaler registry, appointment gates."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_agreement,
    assert_territory,
    create_agreement_payload,
    create_territory_payload,
    make_territory,
    make_wholesaler,
    setup_awarded_territory,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_ADMIN = TEST_USERS["admin_headers"]


class TestTerritoryCreation:
    def test_territory_create_defaults_vacant(self, api, admin_headers):
        """PRD §3.1: "Every territory is born `VACANT`, with
        `incumbent_wholesaler_id` null, waiting for its first appointment."
        PRD §2.4: "`version` (integer): begins at 1 when the resource is
        created and increments by one on every mutation."

        Design: Corner/entities/territory_create_defaults_vacant
        """
        resp = api.create_territory(
            create_territory_payload(name="Hill Country", state_code="TX"),
            admin_headers,
        )
        data = validate_success(resp, 201)
        assert_territory(data)
        assert data["status"] == "VACANT"
        assert data["incumbent_wholesaler_id"] is None
        assert data["version"] == 1
        envelope = resp.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"]
        assert envelope["meta"]["api_request_timestamp"]


class TestAppointment:
    def test_agreement_create_awards_territory_and_appoints_wholesaler(
        self, api, admin_headers
    ):
        """PRD §3.1: "The territory moves `VACANT` → `AWARDED`, and its
        `incumbent_wholesaler_id` is set to the appointed wholesaler."
        PRD §3.1: "when this agreement is the wholesaler's first `ACTIVE`
        agreement, the wholesaler itself moves `APPLICANT` → `APPOINTED`."
        PRD §3.1: "The agreement is born `ACTIVE` at `version` 1."

        Design: Corner/state_machines/agreement_create_awards_territory_and_appoints_wholesaler
        """
        territory = make_territory(name="Award Territory")
        wholesaler = make_wholesaler(legal_name="Award Distributing")
        resp = api.create_agreement(
            create_agreement_payload(territory["id"], wholesaler["id"]),
            admin_headers,
        )
        agreement = validate_success(resp, 201)
        assert_agreement(agreement)
        assert agreement["status"] == "ACTIVE"
        assert agreement["version"] == 1

        terr = validate_success(api.get_territory(territory["id"], admin_headers))
        assert terr["status"] == "AWARDED"
        assert terr["incumbent_wholesaler_id"] == wholesaler["id"]

        whole = validate_success(api.get_wholesaler(wholesaler["id"], admin_headers))
        assert whole["status"] == "APPOINTED"

    def test_second_agreement_on_awarded_territory_rejected(self, api, admin_headers):
        """PRD §3.1: "The territory must still be `VACANT` — appointing onto an
        `AWARDED` territory is rejected with `ERR_TERRITORY_NOT_VACANT`."

        Design: Corner/validations/second_agreement_on_awarded_territory_rejected
        """
        territory, first, _ = setup_awarded_territory(territory_name="Exclusive Territory")
        second = make_wholesaler(legal_name="Second Distributing")
        resp = api.create_agreement(
            create_agreement_payload(
                territory["id"],
                second["id"],
                brand_scope=["MIC"],
                distribution_target_pct=70,
                freshness_target_index=85,
                share_target_pct=30,
                declared_distribution_pct=70,
                declared_freshness_index=90,
                declared_share_pct=30,
                term_years=3,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_VACANT)
        whole = validate_success(api.get_wholesaler(second["id"], admin_headers))
        assert whole["status"] == "APPLICANT", (
            "rejected appointment must not promote the second wholesaler"
        )
        assert first["id"] != second["id"]

    def test_agreement_rofr_holder_self_reference_rejected(self, api, admin_headers):
        """PRD §3.1: "A named ROFR holder must differ from the appointed
        wholesaler and must reference an existing, non-`TERMINATED` wholesaler,
        else the creation fails with `ERR_ROFR_HOLDER_CONFLICT`."

        Design: Corner/validations/agreement_rofr_holder_self_reference_rejected
        """
        territory = make_territory(name="Rofr Territory")
        wholesaler = make_wholesaler(legal_name="Self Holder")
        resp = api.create_agreement(
            create_agreement_payload(
                territory["id"],
                wholesaler["id"],
                rofr_holder_wholesaler_id=wholesaler["id"],
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ROFR_HOLDER_CONFLICT)
        terr = validate_success(api.get_territory(territory["id"], admin_headers))
        assert terr["status"] == "VACANT"
        assert terr["incumbent_wholesaler_id"] is None


def _book(entries):
    return [
        {"supplier_name": name, "supplier_type": kind, "added_at": "2026-01-15T00:00:00Z"}
        for name, kind in entries
    ]


class TestBookConcentration:
    def test_book_concentration_ratio_strictly_greater(self, api, admin_headers):
        """PRD §3.1: "the appointment is rejected with
        `ERR_PORTFOLIO_CONCENTRATION_EXCEEDED` when the book holds at least four
        competing entries and either the book contains no entries at all or the
        competing entries make up strictly more than half of all entries."
        PRD §3.1: "Because the ratio comparison is a strict greater-than,
        exactly four competing entries among eight total — a ratio of precisely
        one half — is permitted."

        Design: Corner/calculations/book_concentration_ratio_strictly_greater
        """
        competing = [("Craft One", "CRAFT"), ("Craft Two", "CRAFT"),
                     ("Craft Three", "CRAFT"), ("Import One", "IMPORT")]
        domestic = [("Dom One", "DOMESTIC_PREMIUM"), ("Dom Two", "DOMESTIC_PREMIUM"),
                    ("Dom Three", "DOMESTIC_PREMIUM")]

        t_balanced = make_territory(name="Book Territory A")
        t_concentrated = make_territory(name="Book Territory B")
        w_balanced = make_wholesaler(
            legal_name="Balanced Book",
            supplier_book=_book(competing + domestic + [("Dom Four", "DOMESTIC_PREMIUM")]),
        )
        w_concentrated = make_wholesaler(
            legal_name="Concentrated Book",
            supplier_book=_book(competing + domestic),
        )

        # 4 competing of 8 total -> ratio exactly 0.50 -> allowed.
        ok = api.create_agreement(
            create_agreement_payload(t_balanced["id"], w_balanced["id"]),
            admin_headers,
        )
        agreement = validate_success(ok, 201)
        assert agreement["status"] == "ACTIVE"

        # 4 competing of 7 total -> ratio 4/7 > 0.50 -> rejected.
        bad = api.create_agreement(
            create_agreement_payload(t_concentrated["id"], w_concentrated["id"]),
            admin_headers,
        )
        validate_error(bad, ApiErrorId.ERR_PORTFOLIO_CONCENTRATION_EXCEEDED)


class TestReadback:
    def test_immediate_read_after_write_agreement_listing(self, api, auditor_headers):
        """PRD §2.9: "Reverse reachability is therefore provided through
        dedicated sub-resource list endpoints — agreements by territory and by
        wholesaler, transfer applications by agreement, retail accounts and
        performance reviews by wholesaler, corrective plans by review, and
        draft audits and POS grants by account."
        PRD §3.1: "The agreement is born `ACTIVE` at `version` 1."

        Design: Corner/consistency_model/immediate_read_after_write_agreement_listing
        """
        territory = make_territory(name="Immediate Territory")
        wholesaler = make_wholesaler(legal_name="Immediate Distributing")
        resp = api.create_agreement(
            create_agreement_payload(territory["id"], wholesaler["id"]), TEST_ADMIN
        )
        agreement = validate_success(resp, 201)

        listed = api.list_wholesaler_agreements(wholesaler["id"], auditor_headers)
        rows, _meta = validate_paginated(listed)
        assert len(rows) == 1, f"expected 1 agreement, got {len(rows)}"
        assert rows[0]["id"] == agreement["id"]
        assert rows[0]["status"] == "ACTIVE"
        assert rows[0]["territory_id"] == territory["id"]
        assert rows[0]["version"] == 1

    def test_agreement_get_unknown_id_returns_not_found(self, api, admin_headers):
        """PRD §2.9: "Every identifier referenced in a request path or body —
        territory, wholesaler, agreement, transfer application, allocation
        event, retail account, performance review, corrective plan, POS grant,
        or promotion program — must name an existing resource; an unresolvable
        reference is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/agreement_get_unknown_id_returns_not_found
        """
        resp = api.get_agreement(NON_EXISTENT_UUID, admin_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        envelope = resp.json()
        assert envelope["response_type"] == "error"
        assert isinstance(err.get("message"), str) and err["message"]
        assert envelope["meta"]["api_request_id"]
