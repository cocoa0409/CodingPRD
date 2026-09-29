"""Pagination bounds, the append-only ledger, and body-foreign-key resolution
ahead of the optimistic-concurrency and acyclicity sweeps."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_diligence_review_payload,
    create_ledger_entry_payload,
    create_partner,
    create_partner_payload,
    read_custody_account,
    read_partner,
    setup_contracted_partner,
    validate_error,
    validate_paginated,
    validate_success,
    PO,
)


class TestPaginationBounds:
    def test_the_declared_bounds_are_enforced_and_never_silently_clamped(self):
        """Every list endpoint accepts two optional query parameters. `limit` controls page size: it
        defaults to 10, may be no smaller than 1 and no larger than 100. `offset` controls the
        starting position: it defaults to 0 and may not be negative. A `limit` or `offset` outside
        those bounds is a schema failure and is rejected with `ERR_VALIDATION` (HTTP 422).

        Design: Corner/entities/pagination_limit_above_the_declared_maximum_returns_validation
        """
        create_partner(legal_name="Northbeam Pay Inc", business_model="CARD_ISSUING")

        validate_error(
            api_client.list_partners(PO, {"limit": 101, "offset": 0}),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        validate_error(
            api_client.list_partners(PO, {"limit": 0, "offset": 0}),
            ApiErrorId.ERR_VALIDATION,
            422,
        )

        at_max, meta_max = validate_paginated(api_client.list_partners(PO, {"limit": 100}))
        assert len(at_max) == 1
        assert meta_max["total_count"] == 1
        assert meta_max["limit"] == 100, "the declared maximum is accepted as supplied"

        at_min, meta_min = validate_paginated(api_client.list_partners(PO, {"limit": 1}))
        assert len(at_min) == 1
        assert meta_min["limit"] == 1
        assert meta_min["has_more"] is False


class TestLedgerAppendOnly:
    def test_ledger_rows_carry_a_monotonic_sequence_number_and_no_version_or_updated_at(self):
        """The entry is assigned a `sequence_no`, a monotonic per-custody-account insertion index
        starting at 1, which fixes the replay order for balance reconstruction. A ledger entry is
        immutable once written and, as noted in §2.4, carries neither `updated_at` nor `version`.

        Design: Corner/entities/ledger_entry_is_append_only_with_no_version_and_a_monotonic_sequence_no
        """
        ctx = setup_contracted_partner(
            partner_overrides={
                "legal_name": "Northbeam Pay Inc",
                "business_model": "CARD_ISSUING",
                "funding_stage": "SERIES_B_PLUS",
                "months_runway": 24,
                "disclosed_complaints_per_10k": 12.50,
                "end_user_account_count": 100000,
            },
            agreement_overrides={
                "dispute_owner": "PARTNER",
                "concentration_cap_pct": 80.00,
                "reserve_requirement_bps": 500,
            },
        )
        partner_id = ctx["partner"]["id"]
        reserve_id = ctx["reserve"]["id"]

        first_view = read_custody_account(reserve_id)
        first = validate_success(
            api_client.create_ledger_entry(
                create_ledger_entry_payload(
                    partner_id,
                    reserve_id,
                    first_view["version"],
                    entry_type="RESERVE_FUND",
                    amount_cents=312_500,
                    effective_at="2026-08-05T00:00:00Z",
                    memo="initial reserve top-up",
                ),
                PO,
            ),
            201,
        )
        second_view = read_custody_account(reserve_id)
        second = validate_success(
            api_client.create_ledger_entry(
                create_ledger_entry_payload(
                    partner_id,
                    reserve_id,
                    second_view["version"],
                    entry_type="RESERVE_FUND",
                    amount_cents=100_000,
                    effective_at="2026-08-06T00:00:00Z",
                    memo="second reserve top-up",
                ),
                PO,
            ),
            201,
        )

        assert first["sequence_no"] == 1
        assert second["sequence_no"] == 2
        for entry in (first, second):
            assert "version" not in entry, "an immutable row carries no version"
            assert "updated_at" not in entry, "an immutable row carries no updated_at"
            assert entry["settlement_batch_id"] is None
            assert entry["reversal_of_entry_id"] is None
            assert entry["created_at"] is not None

        account = read_custody_account(reserve_id)
        assert account["balance_cents"] == 412_500
        assert account["version"] == 3, (
            f"each booking increments the account version by 1, got {account['version']}"
        )

        rows, _ = validate_paginated(
            api_client.list_ledger_entries(PO, {"custody_account_id": reserve_id})
        )
        assert [row["sequence_no"] for row in rows] == [1, 2], "ordered by sequence_no ascending"


class TestBodyForeignKeyPrecedence:
    def test_an_unknown_body_partner_id_outranks_the_stale_version_guard(self):
        """Every foreign-key id supplied in a request body must name an existing row, resolved in
        this declaration order: `partner_id` first, then `agreement_id`, then `custody_account_id`,
        then `parent_partner_id`.

        Design: Corner/entities/diligence_review_create_with_an_unknown_body_partner_id_returns_partner_not_found
        """
        partner = create_partner(legal_name="Northbeam Pay Inc", business_model="CARD_ISSUING")
        error = validate_error(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    NON_EXISTENT_UUID,
                    partner["version"],
                    review_type="INITIAL",
                    business_model_score=80,
                    funding_score=80,
                    compliance_capability_score=90,
                    complaint_history_score=85,
                ),
                PO,
            ),
            ApiErrorId.ERR_PARTNER_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_STALE_PARTNER_VERSION.value

        rows, meta = validate_paginated(api_client.list_diligence_reviews(PO))
        assert rows == []
        assert meta["total_count"] == 0
        assert read_partner(partner["id"])["version"] == 1, "the rejected create bumped nothing"

    def test_an_unknown_parent_partner_id_is_a_not_found_rather_than_a_group_cycle(self):
        """The named parent must be an existing partner, and the resulting chain must remain
        acyclic: walking `parent_partner_id` upward from the supplied parent must never reach the
        partner being registered.

        Design: Corner/entities/partner_create_with_a_self_referential_parent_chain_cycle_returns_group_cycle
        """
        root = create_partner(legal_name="Northbeam Pay Inc", business_model="CARD_ISSUING")
        child = create_partner(
            legal_name="Northbeam Lending LLC",
            business_model="LENDING",
            funding_stage="SERIES_A",
            months_runway=18,
            disclosed_complaints_per_10k=30.00,
            end_user_account_count=5000,
            parent_partner_id=root["id"],
        )

        error = validate_error(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Northbeam Holdings Inc",
                    business_model="CARD_ISSUING",
                    funding_stage="PUBLIC",
                    months_runway=60,
                    disclosed_complaints_per_10k=1.00,
                    end_user_account_count=0,
                    parent_partner_id=NON_EXISTENT_UUID,
                ),
                PO,
            ),
            ApiErrorId.ERR_PARTNER_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_PARTNER_GROUP_CYCLE.value

        children, _ = validate_paginated(
            api_client.list_partners(PO, {"parent_partner_id": root["id"]})
        )
        assert [row["id"] for row in children] == [child["id"]]
        everyone, meta = validate_paginated(api_client.list_partners(PO))
        assert len(everyone) == 2
        assert meta["total_count"] == 2
