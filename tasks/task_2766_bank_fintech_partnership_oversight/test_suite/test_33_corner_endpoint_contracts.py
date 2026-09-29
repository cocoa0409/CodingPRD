"""Endpoint-surface corners: filter composition and the meaning of `total_count`,
the two declared non-default collection orders, the clock projection, the
oversight-summary read, the fixed envelope and the flat FK topology."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    PO,
    ApiErrorId,
    api_client,
    assert_same_instant,
    clawback_batch,
    create_batch,
    create_diligence_review_payload,
    create_partner,
    create_partner_payload,
    dispose_alert,
    file_complaint,
    file_marketing_review,
    fund_batch,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    oversight_summary,
    raise_alert,
    raise_sanctions_alert,
    read_custody_account,
    read_partner,
    seed_end_user_balance,
    setup_contracted_partner,
    setup_live_partner,
    setup_matched_batch,
    set_clock,
    validate_error,
    validate_paginated,
)

THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

SUMMARY_KEYS = {
    "partner_id",
    "oversight_posture",
    "capability_tier",
    "complaint_rate_bps",
    "concentration_ratio_pct",
    "group_root_partner_id",
    "group_balance_cents",
    "bank_total_fbo_balance_cents",
    "required_reserve_cents",
    "reserve_shortfall_cents",
    "consecutive_shortfall_cycles",
    "growth_breach_count",
    "unreconciled_variance_cents",
    "open_sanctions_alert_count",
    "systemic_root_cause_code",
    "last_closed_cycle_index",
}


class TestFilterCompositionAndTotalCount:
    def test_total_count_describes_the_filtered_set_and_an_offset_past_the_end_is_not_an_error(self):
        """List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta`
        object, where `total_count` is the number of rows matching the filters before pagination is
        applied and `has_more` states whether any matching row remains beyond the current page.
        A `limit` or `offset` outside those bounds is a schema failure and is rejected with
        `ERR_VALIDATION` (HTTP 422).

        Design: Corner/endpoints/filters_compose_and_total_count_describes_the_filtered_set_not_the_page
        """
        partner_a = create_partner(legal_name="Aldergate Wallet Inc")
        partner_b = create_partner(legal_name="Bexhill Money Inc")
        a_id, b_id = partner_a["id"], partner_b["id"]

        email_low_1 = file_complaint(a_id, channel="EMAIL", severity="LOW")
        email_low_2 = file_complaint(a_id, channel="EMAIL", severity="LOW")
        email_high = file_complaint(a_id, channel="EMAIL", severity="HIGH")
        file_complaint(a_id, channel="CFPB_PORTAL", severity="MEDIUM")
        file_complaint(a_id, channel="CFPB_PORTAL", severity="LOW")
        file_complaint(b_id, channel="EMAIL", severity="LOW")

        everything, all_meta = validate_paginated(api_client.list_complaints(PO))
        assert all_meta["total_count"] == 6, all_meta
        assert all_meta["limit"] == 10, "the page size defaults to 10 when none is supplied"
        assert all_meta["offset"] == 0
        assert all_meta["has_more"] is False, "six rows fit inside the default page of ten"
        assert len(everything) == 6

        a_email = {"partner_id": a_id, "channel": "EMAIL"}
        page1, meta1 = validate_paginated(
            api_client.list_complaints(PO, dict(a_email, limit=2, offset=0))
        )
        assert meta1["total_count"] == 3, (
            "total_count counts the rows matching the filters, not the rows on the page, got "
            f"{meta1['total_count']}"
        )
        assert meta1["has_more"] is True, "offset 0 plus 2 returned is still short of 3"
        assert [row["id"] for row in page1] == [email_low_1["id"], email_low_2["id"]], (
            "list results are ordered by created_at ascending"
        )

        page2, meta2 = validate_paginated(
            api_client.list_complaints(PO, dict(a_email, limit=2, offset=2))
        )
        assert meta2["total_count"] == 3, meta2
        assert meta2["has_more"] is False, "offset 2 plus 1 returned reaches the total of 3"
        assert [row["id"] for row in page2] == [email_high["id"]]

        page3, meta3 = validate_paginated(
            api_client.list_complaints(PO, dict(a_email, limit=2, offset=5))
        )
        assert page3 == [], "an offset past the end yields an empty page, not an error"
        assert meta3["total_count"] == 3, (
            f"the unpaginated match count is unchanged by the offset, got {meta3['total_count']}"
        )
        assert meta3["has_more"] is False

        narrow, narrow_meta = validate_paginated(
            api_client.list_complaints(
                PO, {"partner_id": a_id, "channel": "EMAIL", "severity": "HIGH"}
            )
        )
        assert narrow_meta["total_count"] == 1, (
            "three filters compose with AND, not OR: a two-filter OR would have matched five "
            f"rows, got {narrow_meta['total_count']}"
        )
        assert [row["id"] for row in narrow] == [email_high["id"]]

        empty, empty_meta = validate_paginated(
            api_client.list_complaints(PO, {"partner_id": b_id, "channel": "CFPB_PORTAL"})
        )
        assert empty == [], "a filter combination matching nothing is a 200 with an empty array"
        assert empty_meta["total_count"] == 0
        assert empty_meta["has_more"] is False

        validate_error(
            api_client.list_complaints(PO, {"limit": 0}), ApiErrorId.ERR_VALIDATION, 422
        )


class TestLedgerOrderingAndForeignKeyFilters:
    def test_sequence_numbers_restart_per_account_and_every_declared_filter_isolates_its_legs(self):
        """The entry is assigned a `sequence_no`, a monotonic per-custody-account insertion index
        starting at 1, which fixes the replay order for balance reconstruction. Two collections
        declare their own order and are the only exceptions: ledger entries are returned ordered by
        `custody_account_id` and then by `sequence_no` ascending, and oversight cycles are returned
        ordered by `cycle_index` ascending.

        Design: Corner/endpoints/ledger_entries_list_in_custody_account_then_sequence_no_order_and_every_fk_filter_is_honoured
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Cardinal Rail Inc",
                "business_model": "CARD_ISSUING",
                "end_user_account_count": 9_000,
            },
            fbo_balance_cents=8_100_000,
            reserve_balance_cents=506_250,
        )
        partner_id = ctx["partner"]["id"]
        fbo_id, reserve_id = ctx["fbo"]["id"], ctx["reserve"]["id"]

        batch = setup_matched_batch(
            partner_id,
            gross_settlement_cents=8_000_000,
            interchange_cents=200_000,
            returns_cents=100_000,
            partner_reported_net_cents=8_100_000,
        )
        funded = fund_batch(batch["id"], funding_reference="WIRE-LED-1")
        assert funded["reserve_funding_cents"] == 400_000
        assert funded["bank_fee_cents"] == 61_000
        clawed = clawback_batch(batch["id"], clawback_reason="DUPLICATE_FUNDING")
        assert clawed["funding_status"] == "CLAWED_BACK"

        rows, meta = validate_paginated(
            api_client.list_ledger_entries(PO, {"partner_id": partner_id, "limit": 100})
        )
        assert meta["total_count"] == 8, (
            "one manual seed on each account, three funding legs and three clawback legs, got "
            f"{meta['total_count']}"
        )
        for row in rows:
            assert "version" not in row, "a ledger entry is an immutable historical fact"
            assert "updated_at" not in row

        groups = []
        for row in rows:
            if not groups or groups[-1][0] != row["custody_account_id"]:
                groups.append((row["custody_account_id"], []))
            groups[-1][1].append(row["sequence_no"])
        assert len(groups) == 2, (
            "all the rows of one custody account appear contiguously, so two accounts produce "
            f"exactly two runs, got {[g[0] for g in groups]}"
        )
        for account_id, sequences in groups:
            assert sequences == sorted(sequences), (
                f"account {account_id} must ascend by sequence_no, got {sequences}"
            )
            assert sequences == list(range(1, len(sequences) + 1)), (
                f"per-account numbering restarts at 1, got {sequences} for {account_id}"
            )

        fbo_rows, fbo_meta = validate_paginated(
            api_client.list_ledger_entries(PO, {"custody_account_id": fbo_id})
        )
        assert fbo_meta["total_count"] == 3, fbo_meta
        assert [row["sequence_no"] for row in fbo_rows] == [1, 2, 3]
        assert fbo_rows[0]["entry_type"] == "VARIANCE_ADJUSTMENT"
        assert fbo_rows[0]["settlement_batch_id"] is None, "a manual entry names no batch"
        assert fbo_rows[0]["reversal_of_entry_id"] is None
        assert [row["entry_type"] for row in fbo_rows[1:]] == ["END_USER_DEBIT", "CLAWBACK"]

        reserve_rows, reserve_meta = validate_paginated(
            api_client.list_ledger_entries(PO, {"custody_account_id": reserve_id})
        )
        assert reserve_meta["total_count"] == 5, (
            "the manual seed, the reserve routing, the fee and the two reserve-side reversals, "
            f"got {reserve_meta['total_count']}"
        )
        assert [row["sequence_no"] for row in reserve_rows] == [1, 2, 3, 4, 5], (
            "sequence_no is scoped per custody account and never global, so the reserve account "
            f"also starts at 1, got {[row['sequence_no'] for row in reserve_rows]}"
        )

        batch_rows, batch_meta = validate_paginated(
            api_client.list_ledger_entries(PO, {"settlement_batch_id": batch["id"]})
        )
        assert batch_meta["total_count"] == 6, (
            "three funding legs plus the three reversals the settlement machinery synthesised, "
            f"got {batch_meta['total_count']}"
        )
        assert all(row["settlement_batch_id"] == batch["id"] for row in batch_rows)

        routing, routing_meta = validate_paginated(
            api_client.list_ledger_entries(
                PO, {"settlement_batch_id": batch["id"], "entry_type": "RESERVE_FUND"}
            )
        )
        assert routing_meta["total_count"] == 1, routing_meta
        routing_leg = routing[0]
        assert routing_leg["amount_cents"] == 400_000
        assert routing_leg["custody_account_id"] == reserve_id

        reversals, reversal_meta = validate_paginated(
            api_client.list_ledger_entries(PO, {"reversal_of_entry_id": routing_leg["id"]})
        )
        assert reversal_meta["total_count"] == 1, reversal_meta
        assert reversals[0]["entry_type"] == "CLAWBACK"
        assert reversals[0]["amount_cents"] == -400_000, (
            "the reversal of the positive routing leg is its exact negation, got "
            f"{reversals[0]['amount_cents']}"
        )

        single = get_success_data(api_client.get_ledger_entry(routing_leg["id"], PO))
        assert single["id"] == routing_leg["id"]
        assert single["entry_type"] == "RESERVE_FUND"
        assert single["settlement_batch_id"] == batch["id"]
        assert single["sequence_no"] == routing_leg["sequence_no"]

        assert read_custody_account(fbo_id)["balance_cents"] == 8_100_000
        assert read_custody_account(reserve_id)["balance_cents"] == 506_250


class TestLogicalClockProjection:
    def test_the_clock_moves_both_ways_and_never_recomputes_a_stored_deadline(self):
        """A `ProgramOfficer` may advance the clock by supplying a `to_iso8601` instant to the
        administrative clock endpoint at `POST /_clock/set_current_utc`, which is the only route in
        the system not mounted under `/oversight`. It responds with the new value of the clock as
        `current_utc` and performs no recomputation of any entity — advancing the clock changes what
        future evaluations will see, and nothing more.

        Design: Corner/endpoints/the_logical_clock_is_settable_in_both_directions_and_recomputes_nothing_by_itself
        """
        partner = create_partner(legal_name="Dunmore Deposits Inc")
        partner_id = partner["id"]

        early = file_complaint(
            partner_id, channel="EMAIL", received_at="2026-08-01T00:00:00Z"
        )
        assert_same_instant(
            early["response_due_at"], "2026-08-31T00:00:00.000Z", "the calendar-day deadline"
        )
        early_due = early["response_due_at"]
        early_version = early["version"]
        version_before_clock_calls = read_partner(partner_id)["version"]

        forward = set_clock("2026-08-20T12:34:56Z")
        assert_same_instant(forward["current_utc"], "2026-08-20T12:34:56Z", "current_utc forward")

        after_forward = get_success_data(api_client.get_complaint(early["id"], PO))
        assert_same_instant(after_forward["response_due_at"], early_due, "deadline after the move")
        assert after_forward["version"] == early_version, (
            "moving the clock bumped no version, so it persisted no recomputation"
        )
        assert read_partner(partner_id)["version"] == version_before_clock_calls

        later = file_complaint(
            partner_id, channel="EMAIL", received_at="2026-08-20T00:00:00Z"
        )
        assert_same_instant(
            later["response_due_at"], "2026-09-19T00:00:00.000Z", "the later intake's deadline"
        )
        assert later["response_due_at"] != early_due, (
            "the deadline is a function of received_at, so the two intakes differ"
        )
        version_after_second_intake = read_partner(partner_id)["version"]

        backward = set_clock("2026-08-01T00:00:00Z")
        assert_same_instant(backward["current_utc"], "2026-08-01T00:00:00Z", "current_utc backward")
        rewound_early = get_success_data(api_client.get_complaint(early["id"], PO))
        rewound_later = get_success_data(api_client.get_complaint(later["id"], PO))
        assert_same_instant(rewound_early["response_due_at"], early_due, "frozen at write time")
        assert_same_instant(
            rewound_later["response_due_at"],
            later["response_due_at"],
            "a deadline computed under a clock that is now in the future is still stored",
        )
        assert rewound_later["status"] == "RECEIVED", (
            "winding the clock past a deadline does not escalate a complaint"
        )

        assert_same_instant(
            set_clock("2026-08-25T00:00:00Z")["current_utc"], "2026-08-25T00:00:00Z", "third call"
        )
        assert_same_instant(
            set_clock("2026-08-01T00:00:00Z")["current_utc"], "2026-08-01T00:00:00Z", "fourth call"
        )
        assert read_partner(partner_id)["version"] == version_after_second_intake, (
            "no partner version changed across any of the four clock calls"
        )
        assert (
            get_success_data(api_client.get_complaint(early["id"], PO))["version"] == early_version
        )


class TestOversightSummaryProjection:
    def test_the_summary_agrees_field_for_field_with_the_partner_row_and_persists_nothing(self):
        """A bank-internal computed read — unavailable to `FintechPartner` — assembles the partner's
        current supervisory picture into a flat object: `partner_id`, `oversight_posture`,
        `capability_tier`, `complaint_rate_bps`, `concentration_ratio_pct`, the
        `group_root_partner_id` reached by walking the parentage chain to its root,
        `group_balance_cents` and `bank_total_fbo_balance_cents` as the numerator and denominator of
        the concentration ratio computed live at read time.

        Design: Corner/endpoints/the_oversight_summary_read_agrees_field_for_field_with_the_partner_row_and_mutates_nothing
        """
        ctx = setup_live_partner(
            partner_overrides={
                "legal_name": "Elmsworth Payments Inc",
                "business_model": "PAYMENT_FACILITATION",
                "end_user_account_count": 6_000,
            },
            fbo_balance_cents=0,
            reserve_balance_cents=312_500,
        )
        partner_id = ctx["partner"]["id"]
        seed_end_user_balance(partner_id, ctx["fbo"], 8_099_999)
        seed_end_user_balance(partner_id, ctx["fbo"], 1)

        alert = raise_sanctions_alert(
            partner_id,
            alert_type="SANCTIONS_HIT",
            triggered_at="2026-07-25T09:00:00Z",
            transaction_volume_cents=310_000,
            detection_note="screening hit on a beneficiary name, later attributed to a homonym",
        )
        cleared = dispose_alert(
            alert["id"], "CLEARED", disposition_note="homonym confirmed against the primary list"
        )
        assert cleared["disposition"] == "CLEARED"

        row = read_partner(partner_id)
        assert row["status"] == "LIVE"
        assert row["open_sanctions_alert_count"] == 0, "the cause has been removed"
        assert row["oversight_posture"] == "HEIGHTENED", row["oversight_posture"]
        assert row["required_reserve_cents"] == 506_250, row["required_reserve_cents"]
        assert row["reserve_shortfall_cents"] == 193_750, row["reserve_shortfall_cents"]

        summary = oversight_summary(partner_id)
        assert set(summary) == SUMMARY_KEYS, (
            f"the sixteen declared keys and nothing else, got {sorted(set(summary))}"
        )
        for absent in ("id", "created_at", "updated_at", "version"):
            assert absent not in summary, (
                f"the summary is a flat projection, not an entity, so {absent} has no place in it"
            )

        assert summary["partner_id"] == partner_id
        for shared in (
            "oversight_posture",
            "capability_tier",
            "complaint_rate_bps",
            "concentration_ratio_pct",
            "required_reserve_cents",
            "reserve_shortfall_cents",
            "consecutive_shortfall_cycles",
            "growth_breach_count",
            "unreconciled_variance_cents",
            "open_sanctions_alert_count",
        ):
            assert summary[shared] == row[shared], (
                f"{shared} is a projection over the same persisted column, summary "
                f"{summary[shared]} against row {row[shared]}"
            )

        assert summary["complaint_rate_bps"] == 0
        assert summary["consecutive_shortfall_cycles"] == 0
        assert summary["growth_breach_count"] == 0
        assert summary["unreconciled_variance_cents"] == 0
        assert summary["concentration_ratio_pct"] == 100.00, (
            "this partner is the only holder of end-user custody in the bank, so its own group "
            f"is the whole denominator, got {summary['concentration_ratio_pct']}"
        )
        assert summary["group_root_partner_id"] == partner_id, (
            "the parentage chain has no parent to walk to, so the partner is its own root"
        )
        assert summary["group_balance_cents"] == 8_100_000, summary["group_balance_cents"]
        assert summary["bank_total_fbo_balance_cents"] == 8_100_000, (
            f"numerator and denominator coincide, got {summary['bank_total_fbo_balance_cents']}"
        )
        assert summary["systemic_root_cause_code"] is None, (
            "the pool of diagnosed complaints is empty, so there is no dominant defect"
        )

        again = oversight_summary(partner_id)
        assert again == summary, "the read is pure, so two consecutive reads agree"
        assert read_partner(partner_id)["version"] == row["version"], (
            "neither read incremented version, so no read path persists a recompute"
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 8_100_000, (
            "and neither read moved a balance"
        )


class TestEnvelopeAndStatusCodes:
    def test_creates_return_201_actions_return_200_and_the_envelope_never_varies(self):
        """Creation endpoints return HTTP 201 with the created resource; every other successful call
        returns HTTP 200, and state-changing calls return the full updated resource in `data`. The
        `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`.

        Design: Corner/endpoints/creates_return_201_actions_return_200_and_every_response_carries_the_fixed_envelope
        """
        created = api_client.create_partner(
            create_partner_payload(legal_name="Fenwick Ledger Inc"), PO
        )
        assert created.status_code == 201, (
            f"a creation endpoint returns 201, got {created.status_code}: {created.text}"
        )
        body = created.json()
        assert set(body) == {"meta", "response_type", "data"}, (
            f"the envelope has exactly three top-level keys, got {sorted(set(body))}"
        )
        assert body["response_type"] == "object", body["response_type"]
        assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        partner = body["data"]
        partner_id = partner["id"]
        assert is_valid_uuid(partner_id), "a server-minted UUID with no type prefix"
        assert partner["version"] == 1, "version begins at 1 when the row is created"
        assert THREE_FRACTIONAL_DIGITS.match(partner["created_at"]), partner["created_at"]
        assert THREE_FRACTIONAL_DIGITS.match(partner["updated_at"]), partner["updated_at"]
        assert partner["created_at"] == partner["updated_at"], (
            "nothing has mutated the row yet, so the two stamps coincide"
        )

        review_created = api_client.create_diligence_review(
            create_diligence_review_payload(partner_id, partner["version"]), PO
        )
        assert review_created.status_code == 201, review_created.text
        review = review_created.json()["data"]
        assert review["status"] == "DRAFT"
        assert review["revision_round"] == 0
        assert review["version"] == 1

        submitted = api_client.submit_diligence_review(review["id"], {}, PO)
        assert submitted.status_code == 200, (
            "a POST that acts on an existing row is not a creation, so it returns 200, got "
            f"{submitted.status_code}: {submitted.text}"
        )
        submitted_body = submitted.json()
        assert set(submitted_body) == {"meta", "response_type", "data"}
        assert submitted_body["response_type"] == "object"
        assert submitted_body["data"]["status"] == "SUBMITTED", (
            "the state-changing call returns the full updated resource"
        )
        assert submitted_body["data"]["version"] == 2

        census = api_client.report_account_census(
            partner_id, {"end_user_account_count": 1_200, "as_of_date": "2026-08-01T00:00:00Z"}, PO
        )
        assert census.status_code == 200, (
            f"another POST action that creates nothing, got {census.status_code}: {census.text}"
        )
        assert census.json()["response_type"] == "object"
        assert census.json()["data"]["end_user_account_count"] == 1_200

        clock = api_client.set_current_utc("2026-08-02T00:00:00Z", PO)
        assert clock.status_code == 200, clock.text
        clock_body = clock.json()
        assert clock_body["response_type"] == "object"
        assert_same_instant(
            clock_body["data"]["current_utc"], "2026-08-02T00:00:00Z", "the clock projection"
        )

        single = api_client.get_partner(partner_id, PO)
        assert single.status_code == 200, single.text
        single_body = single.json()
        assert single_body["response_type"] == "object"
        assert single_body["data"]["id"] == partner_id

        listed = api_client.list_partners(PO)
        assert listed.status_code == 200
        list_body = listed.json()
        assert list_body["response_type"] == "array", list_body["response_type"]
        assert isinstance(list_body["data"], list)
        for pagination_field in ("limit", "offset", "total_count", "has_more"):
            assert pagination_field in list_body["meta"], (
                f"a list endpoint carries {pagination_field} inside meta, got "
                f"{sorted(list_body['meta'])}"
            )

        missing = api_client.get_partner(NON_EXISTENT_UUID, PO)
        assert missing.status_code == 404, missing.text
        error_body = missing.json()
        assert set(error_body) == {"meta", "response_type", "data"}, (
            f"an error carries no extra top-level key, got {sorted(set(error_body))}"
        )
        assert error_body["response_type"] == "error", (
            f"the literal string error, got {error_body['response_type']}"
        )
        assert set(error_body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
            f"an error meta carries no pagination fields, got {sorted(error_body['meta'])}"
        )
        assert error_body["data"]["error_id"] == ApiErrorId.ERR_PARTNER_NOT_FOUND.value, (
            error_body["data"]
        )
        assert error_body["data"]["message"], "a human-readable explanation is present"


class TestEveryChildCollectionIsReachableThroughAFilter:
    def test_each_foreign_key_is_traversable_from_the_parent_id_and_an_empty_edge_is_an_array(self):
        """The `parent_partner_id` filter is the only channel through which the corporate tree can
        be traversed downward, since parentage is expressed as a body field rather than as a URL
        segment. Marketing reviews are listable with filters on `partner_id`, `agreement_id`,
        `material_type`, `placement_channel` and `status`; the `agreement_id` filter is the only
        channel through which the filings under a given agreement can be enumerated.

        Design: Corner/endpoints/every_child_collection_is_reachable_from_its_parent_id_through_a_declared_filter
        """
        ctx = setup_contracted_partner(
            partner_overrides={
                "legal_name": "Gravelane Holdings Inc",
                "end_user_account_count": 3_000,
            }
        )
        partner_id = ctx["partner"]["id"]
        agreement_id = ctx["agreement"]["id"]

        child = create_partner(
            legal_name="Gravelane Sub Inc", parent_partner_id=partner_id
        )
        assert child["parent_partner_id"] == partner_id

        marketing = file_marketing_review(
            partner_id,
            agreement_id,
            material_type="AD",
            placement_channel="IN_APP",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2026-09-10T00:00:00Z",
        )
        batch = create_batch(partner_id)
        complaint = file_complaint(partner_id)
        alert = raise_alert(partner_id)

        reviews, review_meta = validate_paginated(
            api_client.list_diligence_reviews(PO, {"partner_id": partner_id})
        )
        assert review_meta["total_count"] == 1, review_meta
        assert reviews[0]["id"] == ctx["review"]["id"]

        agreements, agreement_meta = validate_paginated(
            api_client.list_agreements(PO, {"partner_id": partner_id})
        )
        assert agreement_meta["total_count"] == 1, agreement_meta
        assert agreements[0]["id"] == agreement_id

        filings, filing_meta = validate_paginated(
            api_client.list_marketing_reviews(PO, {"agreement_id": agreement_id})
        )
        assert filing_meta["total_count"] == 1, (
            "the agreement_id foreign key is reachable from the agreement, not only from the "
            f"partner, got {filing_meta['total_count']}"
        )
        assert filings[0]["id"] == marketing["id"]

        accounts, account_meta = validate_paginated(
            api_client.list_custody_accounts(PO, {"partner_id": partner_id})
        )
        assert account_meta["total_count"] == 2, (
            f"the custody pair is still returned as an array, got {account_meta['total_count']}"
        )
        assert sorted(row["account_type"] for row in accounts) == [
            "FBO_END_USER",
            "RESERVE",
        ], [row["account_type"] for row in accounts]
        assert all(row["status"] == "ACTIVE" for row in accounts)

        batches, batch_meta = validate_paginated(
            api_client.list_settlement_batches(PO, {"partner_id": partner_id})
        )
        assert batch_meta["total_count"] == 1, batch_meta
        assert batches[0]["id"] == batch["id"]

        complaints, complaint_meta = validate_paginated(
            api_client.list_complaints(PO, {"partner_id": partner_id})
        )
        assert complaint_meta["total_count"] == 1, complaint_meta
        assert complaints[0]["id"] == complaint["id"]

        alerts, alert_meta = validate_paginated(
            api_client.list_alerts(PO, {"partner_id": partner_id})
        )
        assert alert_meta["total_count"] == 1, alert_meta
        assert alerts[0]["id"] == alert["id"]

        children, child_meta = validate_paginated(
            api_client.list_partners(PO, {"parent_partner_id": partner_id})
        )
        assert child_meta["total_count"] == 1, (
            f"the self-referential group edge is reachable downward, got {child_meta}"
        )
        assert children[0]["id"] == child["id"]
        assert children[0]["parent_partner_id"] == partner_id

        plans, plan_meta = validate_paginated(
            api_client.list_wind_down_plans(PO, {"partner_id": partner_id})
        )
        assert plans == [], "a foreign key with no children yields an empty array, never a 404"
        assert plan_meta["total_count"] == 0
        assert plan_meta["has_more"] is False
