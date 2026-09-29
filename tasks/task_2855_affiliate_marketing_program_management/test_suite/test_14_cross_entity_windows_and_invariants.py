"""Cross-entity state gates, window endpoint conventions and money conservation.

Three behaviours meet in this file.  One entity's state decides whether an
operation on a *different* entity is allowed — the applicant partner gates the
application decision, and the partner's tax document gates the payout line.
Temporal windows differ in which endpoint they include — rate-card windows are
half-open and may sit adjacent, monitoring-scan windows are closed and may not
even touch.  And the compensating operations conserve money exactly — after a
void the partner's balances and the ledger row set are what they were, and after
a full cancellation the ledger's signed sum returns to zero while the ledger
itself only ever grows.
"""

import pytest

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AFFILIATE_NOT_ELIGIBLE,
    ERR_POLICY_WINDOW_OVERLAP,
    ERR_SCAN_WINDOW_OVERLAP,
    ERR_TAX_DOCUMENT_INVALID,
)
from test_helpers.assertions import (
    assert_append_only_row,
    assert_bps,
    assert_cents,
    assert_created,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_null,
    assert_object_response,
    assert_one_decimal_score,
    assert_total_count,
    assert_version_unchanged,
    rows_by,
)
from test_helpers.fixtures import (
    activate_policy,
    activated_partner,
    approve_batch,
    attribute,
    attributed_order,
    build_program,
    create_conversion,
    create_network,
    draft_and_activate_policy,
    draft_policy,
    file_tax_document,
    generate_batch,
    ingest_click,
    mint_link,
    pin_clock,
    read_affiliate,
    read_batch,
    read_conversion,
    read_line,
    record_scan,
    screened_partner,
    suspend_partner,
    valid_tax_document,
    validate_batch,
    verify_tax_document,
    void_batch,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    FINANCE_CONTROLLER,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

# Instants used across this file.  §2.4 fixes the shape as "an ISO 8601 UTC
# timestamp with three fractional digits (for example `2026-08-01T00:00:00.000Z`)".
AUG_01_00_00 = "2026-08-01T00:00:00.000Z"
AUG_10_10_00 = "2026-08-10T10:00:00.000Z"
AUG_12_09_00 = "2026-08-12T09:00:00.000Z"
AUG_12_12_00 = "2026-08-12T12:00:00.000Z"
AUG_13_09_00 = "2026-08-13T09:00:00.000Z"
SEP_15_00_00 = "2026-09-15T00:00:00.000Z"
PERIOD_START_AUG = "2026-08-01T00:00:00.000Z"
PERIOD_END_SEP = "2026-09-01T00:00:00.000Z"

# Rate-card windows for the half-open adjacency pair (§3.3).
H1_FROM = "2026-01-01T00:00:00.000Z"
H1_TO = "2026-07-01T00:00:00.000Z"
H2_FROM = "2026-07-01T00:00:00.000Z"
H2_TO = "2027-01-01T00:00:00.000Z"
STRADDLE_FROM = "2026-06-30T00:00:00.000Z"
STRADDLE_TO = "2026-08-01T00:00:00.000Z"

# Monitoring-scan windows for the closed-window touch and cooldown pair (§3.7).
SCAN1_START = "2026-07-01T00:00:00.000Z"
SCAN1_END = "2026-07-15T00:00:00.000Z"
SCAN_LATER_END = "2026-07-20T00:00:00.000Z"


def _balance_pair(affiliate):
    """The conserved money quantity of §3.9: accrued plus reserved."""
    return affiliate["accrued_balance_cents"] + affiliate["reserved_balance_cents"]


def _signed_ledger_sum(rows):
    """The signed sum of a partner's or an order's ledger movements (§3.6)."""
    return sum(row["amount_cents"] for row in rows)


def _ledger_rows(api, params, expected_total):
    """List ledger entries through the §4 list channel and pin `total_count`."""
    rows = assert_total_count(api.list_ledger_entries(FINANCE_CONTROLLER, params), expected_total)
    return rows


class TestApplicationDecisionGatedByApplicantState:
    def test_decide_refused_when_applicant_partner_was_suspended_after_screening(self, api):
        """A `SCREENED`/`PASS` application cannot be decided once its applicant is suspended.

        PRD §2.10: "The applicant partner's `status` is `PENDING_APPLICATION` and no
        violation case for that partner is `UPHELD` — otherwise
        `ERR_AFFILIATE_NOT_ELIGIBLE` (409). Applies to deciding an application: a
        decision cannot activate a partner that compliance has already suspended,
        terminated, or upheld a violation against."

        Design: Difficulty/cross_entity_state_dependency/application_decide_blocked_by_applicant_affiliate_state
        """
        pin_clock(api, AUG_01_00_00)
        screened = screened_partner(api, create_network(api)["id"], partner_type="CONTENT")
        application = screened["application"]

        # The application itself is in a perfectly decidable state: §3.2 makes
        # 60.0 site quality and 70.0 brand suitability a `PASS`.
        assert_fields(
            application,
            {"review_state": "SCREENED", "screening_outcome": "PASS"},
        )
        assert_one_decimal_score(application, "site_quality_score", 87.8)
        assert_one_decimal_score(application, "brand_suitability_score", 100.0)
        application_version = application["version"]

        suspend_partner(api, screened["affiliate_id"], reason="fraud investigation opened")
        suspended = read_affiliate(api, screened["affiliate_id"])
        assert_field(suspended, "status", "SUSPENDED")

        response = api.decide_application(
            application["id"],
            # The guard token is the applicant's *current* version, so the 412 of
            # §2.10 rule 29 has nothing to fire on.
            f.decide_payload("APPROVE", suspended["version"], decision_notes="looks good"),
            PARTNER_MANAGER,
        )

        assert_error_response(response, ERR_AFFILIATE_NOT_ELIGIBLE, 409)

        after = assert_object_response(api.get_application(application["id"], PARTNER_MANAGER))
        assert_field(after, "review_state", "SCREENED")
        assert_null(after, "decided_by_user_id")
        assert_version_unchanged(after, application_version, "application")
        assert_field(read_affiliate(api, screened["affiliate_id"]), "status", "SUSPENDED")

    def test_decide_approves_the_same_application_while_applicant_still_pending(self, api):
        """The identical `SCREENED`/`PASS` decision succeeds while the applicant is pending.

        PRD §3.2: "`APPROVE` moves the application `SCREENED → APPROVED` and requires
        the `screening_outcome` to be exactly `PASS`. It cascades the applicant partner
        `PENDING_APPLICATION → ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/application_decide_blocked_by_applicant_affiliate_state
        """
        pin_clock(api, AUG_01_00_00)
        screened = screened_partner(api, create_network(api)["id"], partner_type="CONTENT")
        application = screened["application"]
        assert_fields(
            application,
            {"review_state": "SCREENED", "screening_outcome": "PASS"},
        )

        applicant = read_affiliate(api, screened["affiliate_id"])
        assert_field(applicant, "status", "PENDING_APPLICATION")

        decided = assert_object_response(
            api.decide_application(
                application["id"],
                f.decide_payload("APPROVE", applicant["version"], decision_notes="looks good"),
                PARTNER_MANAGER,
            )
        )

        assert_fields(decided, {"review_state": "APPROVED", "decided_by_user_id": "pm-001"})
        activated = read_affiliate(api, screened["affiliate_id"])
        # §3.2: "The partner moves to `ACTIVE`, its `suspension_cause` is set back to
        # `NONE`".
        assert_fields(activated, {"status": "ACTIVE", "suspension_cause": "NONE"})


def _two_partner_tax_program(api, verify_second_document: bool):
    """Two arithmetically identical partners whose tax documents differ in state.

    Each partner books one returning-customer order of 100000 cents at 400 bps —
    §3.5 makes that a gross of 4000 cents — and the network charges nothing, so the
    only thing that can separate the two payout lines is the tax document.
    """
    pin_clock(api, AUG_12_12_00)
    network = create_network(api, fee_bps=0, flat_fee_cents=0)
    draft_and_activate_policy(
        api,
        product_category="APPAREL",
        partner_type_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=400,
        effective_from=f.YEAR_2026_START,
        effective_to=f.YEAR_2027_START,
    )

    program = {"network_id": network["id"]}
    for key, device, form_type, last4 in (
        ("a", "TA", "W9", "7777"),
        ("b", "TB", "W8BEN", "8888"),
    ):
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        document = file_tax_document(
            api,
            partner["affiliate_id"],
            form_type=form_type,
            tax_id_last4=last4,
            treaty_withholding_bps=0,
            expires_on=f.TAX_EXPIRY_2027,
        )
        if key == "a" or verify_second_document:
            verify_tax_document(api, document["id"], "VALID")
        link = mint_link(api, partner["affiliate_id"])
        ingest_click(api, link["id"], occurred_at=AUG_10_10_00, device_id=device)
        conversion = create_conversion(
            api,
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref=f"CUST-{device}",
            is_new_customer=False,
            placed_at=AUG_12_09_00,
            device_id=device,
        )
        attribute(api, conversion["id"], conversion["version"])
        program[key] = {
            "affiliate_id": partner["affiliate_id"],
            "document_id": document["id"],
            "conversion_id": conversion["id"],
        }

    pin_clock(api, SEP_15_00_00)
    program["batch"] = generate_batch(
        api, network["id"], period_start=PERIOD_START_AUG, period_end=PERIOD_END_SEP
    )
    return program


def _lines_by_affiliate(api, batch_id, expected_total):
    rows = assert_total_count(
        api.list_payout_lines(FINANCE_ANALYST, {"payout_batch_id": batch_id}), expected_total
    )
    return rows_by(rows, "affiliate_id")


class TestPayoutLineGatedByTaxDocumentState:
    def test_validation_holds_only_the_line_whose_tax_document_is_unverified(self, api):
        """Two identical lines diverge at validation on their partners' tax-document state.

        PRD §3.9: "A line whose partner's `tax_document_status` is anything other than
        `VALID` at validation time moves to `HELD_TAX_DOC` with `hold_reason`
        `TAX_DOCUMENT_NOT_VALID`."

        Design: Difficulty/cross_entity_state_dependency/payout_line_held_by_affiliate_tax_document_state_at_validation
        """
        program = _two_partner_tax_program(api, verify_second_document=False)
        batch_id = program["batch"]["id"]

        # §3.8: filing mirrors `PENDING` onto the partner, accepting mirrors `VALID`.
        assert_field(
            read_affiliate(api, program["a"]["affiliate_id"]), "tax_document_status", "VALID"
        )
        assert_field(
            read_affiliate(api, program["b"]["affiliate_id"]), "tax_document_status", "PENDING"
        )

        before = _lines_by_affiliate(api, batch_id, 2)
        line_a = before[program["a"]["affiliate_id"]]
        line_b = before[program["b"]["affiliate_id"]]
        assert_fields(line_a, {"state": "INCLUDED"})
        assert_fields(line_b, {"state": "INCLUDED"})
        # §3.9: "in every other case — no document at all, `PENDING`, `EXPIRED` or
        # `REJECTED` — the line uses the default backup withholding rate of 2400
        # basis points."
        assert_bps(line_b, "withholding_bps", 2400)
        assert_cents(line_b, "withholding_cents", 960)
        assert_cents(line_b, "net_cents", 3040)
        assert_cents(read_batch(api, batch_id), "net_payable_cents", 4000 + 3040)

        validated = validate_batch(api, batch_id, statement_gross_cents=8000, statement_fee_cents=0)

        after = _lines_by_affiliate(api, batch_id, 2)
        held = after[program["b"]["affiliate_id"]]
        kept = after[program["a"]["affiliate_id"]]
        assert_fields(held, {"state": "HELD_TAX_DOC", "hold_reason": "TAX_DOCUMENT_NOT_VALID"})
        assert_fields(kept, {"state": "INCLUDED"})
        assert_bps(kept, "withholding_bps", 0)
        assert_cents(kept, "withholding_cents", 0)
        assert_cents(kept, "net_cents", 4000)

        assert_field(validated, "state", "VALIDATED")
        # §3.9: "Which lines contribute also differs by total: `gross_commission_cents`
        # and `clawback_cents` include **every** line whatever its state, except that a
        # `VOIDED` line contributes to neither, so that the reconciliation check sees the
        # full statement-side gross; while `network_fee_cents`, `withholding_cents` and
        # `net_payable_cents` include only lines that are `INCLUDED` or `PAID`."
        assert_cents(validated, "gross_commission_cents", 8000)
        assert_cents(validated, "net_payable_cents", 4000)
        assert_cents(validated, "network_fee_cents", 0)
        assert_cents(validated, "withholding_cents", 0)
        assert_cents(validated, "network_fee_variance_cents", 0)
        assert_bps(validated, "network_fee_variance_bps", 0)
        assert_field(validated, "reconciliation_status", "MATCHED")

    def test_validation_keeps_both_lines_included_when_both_documents_are_valid(self, api):
        """Verifying the second partner's form before validation keeps its line payable.

        PRD §3.9: "The line's `withholding_bps` comes from the partner's most recent
        tax document ordered by `created_at` descending: when that document's `status`
        is `VALID` the line uses its `treaty_withholding_bps`, and in every other case
        — no document at all, `PENDING`, `EXPIRED` or `REJECTED` — the line uses the
        default backup withholding rate of 2400 basis points."

        Design: Difficulty/cross_entity_state_dependency/payout_line_held_by_affiliate_tax_document_state_at_validation
        """
        program = _two_partner_tax_program(api, verify_second_document=True)
        batch_id = program["batch"]["id"]

        assert_field(
            read_affiliate(api, program["b"]["affiliate_id"]), "tax_document_status", "VALID"
        )
        assert_cents(read_batch(api, batch_id), "net_payable_cents", 8000)

        validated = validate_batch(api, batch_id, statement_gross_cents=8000, statement_fee_cents=0)

        lines = _lines_by_affiliate(api, batch_id, 2)
        for key in ("a", "b"):
            line = lines[program[key]["affiliate_id"]]
            assert_fields(line, {"state": "INCLUDED"})
            assert_null(line, "hold_reason")
            assert_bps(line, "withholding_bps", 0)
            assert_cents(line, "net_cents", 4000)

        assert_field(validated, "state", "VALIDATED")
        assert_cents(validated, "gross_commission_cents", 8000)
        assert_cents(validated, "net_payable_cents", 8000)
        assert_field(validated, "reconciliation_status", "MATCHED")

    def test_release_refused_while_the_partner_holds_no_valid_tax_document(self, api):
        """The tax hold cannot be released while the partner's own form is still pending.

        PRD §2.10: "The partner has a tax document whose `status` is `VALID` and whose
        `expires_on` is strictly after the logical clock — otherwise
        `ERR_TAX_DOCUMENT_INVALID` (422). Applies to hold release, and is deliberately
        ranked below the fraud-hold check so that a fraud-held line on a partner with an
        expired form reports the fraud hold."

        Design: Difficulty/cross_entity_state_dependency/payout_line_held_by_affiliate_tax_document_state_at_validation
        """
        program = _two_partner_tax_program(api, verify_second_document=False)
        batch_id = program["batch"]["id"]
        validate_batch(api, batch_id, statement_gross_cents=8000, statement_fee_cents=0)

        held = _lines_by_affiliate(api, batch_id, 2)[program["b"]["affiliate_id"]]
        assert_field(held, "state", "HELD_TAX_DOC")
        held_version = held["version"]

        response = api.release_hold(
            held["id"], f.release_hold_payload("partner promises to file"), FINANCE_CONTROLLER
        )

        assert_error_response(response, ERR_TAX_DOCUMENT_INVALID, 422)

        after = read_line(api, held["id"])
        assert_fields(after, {"state": "HELD_TAX_DOC", "hold_reason": "TAX_DOCUMENT_NOT_VALID"})
        assert_null(after, "released_by_user_id")
        assert_version_unchanged(after, held_version, "payout line")
        assert_cents(read_batch(api, batch_id), "net_payable_cents", 4000)


class TestRateCardHalfOpenWindowAdjacency:
    def test_activating_a_card_that_starts_where_the_incumbent_ends_is_allowed(self, api):
        """A rate card beginning at the incumbent's exclusive end activates alongside it.

        PRD §3.3: "A window that begins exactly where another ends is therefore adjacent
        rather than overlapping and is allowed."

        Design: Difficulty/resource_temporal_overlap/commission_policy_half_open_window_adjacency_allowed_then_straddle_rejected
        """
        pin_clock(api, AUG_01_00_00)
        incumbent = draft_policy(
            api,
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=900,
            returning_customer_rate_bps=400,
            effective_from=H1_FROM,
            effective_to=H1_TO,
        )
        incumbent = activate_policy(api, incumbent["id"], incumbent["version"])
        assert_field(incumbent, "status", "ACTIVE")

        successor = draft_policy(
            api,
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=950,
            returning_customer_rate_bps=450,
            effective_from=H2_FROM,
            effective_to=H2_TO,
        )
        assert_field(successor, "status", "DRAFT")

        activated = assert_object_response(
            api.activate_commission_policy(
                successor["id"], f.activate_policy_payload(successor["version"]), PROGRAM_ADMIN
            )
        )

        assert_field(activated, "status", "ACTIVE")
        assert_null(activated, "superseded_by_policy_id")
        # §3.3: only an exactly-equal window supersedes — "Exactly-equal windows
        # supersede; partially overlapping windows are rejected."
        still_active = assert_object_response(
            api.get_commission_policy(incumbent["id"], PROGRAM_ADMIN)
        )
        assert_field(still_active, "status", "ACTIVE")
        assert_null(still_active, "superseded_by_policy_id")

        assert_total_count(
            api.list_commission_policies(
                PROGRAM_ADMIN, {"product_category": "APPAREL", "status": "ACTIVE"}
            ),
            2,
        )

    def test_activating_a_card_that_straddles_the_seam_is_refused(self, api):
        """A card starting one day before the seam overlaps both neighbours and is refused.

        PRD §2.10: "No active rate card with the same product category and an
        intersecting partner-type scope has a window overlapping the activating policy's
        window, unless the two windows are exactly equal — otherwise
        `ERR_POLICY_WINDOW_OVERLAP` (409). Applies to rate-card activation."

        Design: Difficulty/resource_temporal_overlap/commission_policy_half_open_window_adjacency_allowed_then_straddle_rejected
        """
        pin_clock(api, AUG_01_00_00)
        for effective_from, effective_to in ((H1_FROM, H1_TO), (H2_FROM, H2_TO)):
            card = draft_policy(
                api,
                product_category="APPAREL",
                partner_type_scope=["CONTENT"],
                new_customer_rate_bps=900,
                returning_customer_rate_bps=400,
                effective_from=effective_from,
                effective_to=effective_to,
            )
            activate_policy(api, card["id"], card["version"])

        straddling = draft_policy(
            api,
            product_category="APPAREL",
            partner_type_scope=["CONTENT"],
            new_customer_rate_bps=1000,
            returning_customer_rate_bps=500,
            effective_from=STRADDLE_FROM,
            effective_to=STRADDLE_TO,
        )

        response = api.activate_commission_policy(
            straddling["id"], f.activate_policy_payload(straddling["version"]), PROGRAM_ADMIN
        )

        assert_error_response(response, ERR_POLICY_WINDOW_OVERLAP, 409)

        # §3.3: "Two windows conflict when the activating card starts strictly before
        # the incumbent's end **and** the incumbent starts strictly before the
        # activating card's end."
        after = assert_object_response(
            api.get_commission_policy(straddling["id"], PROGRAM_ADMIN)
        )
        assert_field(after, "status", "DRAFT")
        assert_version_unchanged(after, straddling["version"], "commission policy")
        assert_total_count(
            api.list_commission_policies(
                PROGRAM_ADMIN, {"product_category": "APPAREL", "status": "ACTIVE"}
            ),
            2,
        )


def _partner_with_one_clean_scan(api):
    """An `ACTIVE` partner carrying one `GOOGLE_ADS` scan whose every signal is zero."""
    pin_clock(api, AUG_01_00_00)
    partner = activated_partner(api, create_network(api)["id"], partner_type="CONTENT")
    scan = record_scan(
        api,
        partner["affiliate_id"],
        engine="GOOGLE_ADS",
        window_start=SCAN1_START,
        window_end=SCAN1_END,
        trademark_hits=0,
        forced_click_ratio_bps=0,
        cookie_stuffing_index=0,
        unauthorized_coupon_hits=0,
    )
    return partner["affiliate_id"], scan


class TestMonitoringScanClosedWindowAndCooldown:
    @pytest.mark.parametrize(
        "window_start",
        [
            pytest.param(SCAN1_END, id="touching_the_incumbent_end_instant"),
            pytest.param("2026-07-15T12:00:00.000Z", id="twelve_hour_gap_inside_the_cooldown"),
            pytest.param("2026-07-16T00:00:00.000Z", id="gap_of_exactly_twenty_four_hours"),
        ],
    )
    def test_scan_refused_when_it_touches_or_sits_inside_the_cooldown(self, api, window_start):
        """A touch at the shared endpoint and any gap up to twenty-four hours both collide.

        PRD §3.7: "A new scan is refused when its window overlaps another scan's window
        for the same partner and the same `engine`, when the two windows merely touch at
        an endpoint, or when the new window's nearer edge sits within twenty-four hours
        of the existing window — the cooldown interval is closed, so a gap of exactly
        twenty-four hours is still a collision."

        Design: Difficulty/resource_temporal_overlap/monitoring_scan_closed_window_touch_and_cooldown_boundary
        """
        affiliate_id, _scan = _partner_with_one_clean_scan(api)

        response = api.create_monitoring_scan(
            f.monitoring_scan_payload(
                affiliate_id,
                engine="GOOGLE_ADS",
                window_start=window_start,
                window_end=SCAN_LATER_END,
            ),
            COMPLIANCE_ANALYST,
        )

        assert_error_response(response, ERR_SCAN_WINDOW_OVERLAP, 409)

        assert_total_count(
            api.list_monitoring_scans(affiliate_id, COMPLIANCE_ANALYST, {"limit": 20}), 1
        )

    def test_scan_accepted_once_the_gap_clears_the_closed_cooldown(self, api):
        """A window opening two days after the incumbent closes is neither a touch nor a collision.

        PRD §3.7: "A new scan is refused when its window overlaps another scan's window
        for the same partner and the same `engine`, when the two windows merely touch at
        an endpoint, or when the new window's nearer edge sits within twenty-four hours
        of the existing window — the cooldown interval is closed, so a gap of exactly
        twenty-four hours is still a collision."

        Design: Difficulty/resource_temporal_overlap/monitoring_scan_closed_window_touch_and_cooldown_boundary
        """
        affiliate_id, _scan = _partner_with_one_clean_scan(api)

        created = assert_created(
            api.create_monitoring_scan(
                f.monitoring_scan_payload(
                    affiliate_id,
                    engine="GOOGLE_ADS",
                    window_start="2026-07-17T00:00:00.000Z",
                    window_end=SCAN_LATER_END,
                ),
                COMPLIANCE_ANALYST,
            )
        )

        assert_fields(
            created,
            {
                "affiliate_id": affiliate_id,
                "engine": "GOOGLE_ADS",
                "window_start": "2026-07-17T00:00:00.000Z",
                "window_end": SCAN_LATER_END,
                "opened_case_count": 0,
            },
        )
        # §2.4: the monitoring scan is one of the four append-only resources, so it
        # carries "only `id` and `created_at`".
        assert_append_only_row(created)

        assert_total_count(
            api.list_monitoring_scans(affiliate_id, COMPLIANCE_ANALYST, {"limit": 20}), 2
        )
        partner = read_affiliate(api, affiliate_id)
        assert_fields(
            partner, {"status": "ACTIVE", "fraud_risk_score": 0, "open_violation_case_count": 0}
        )
        assert_one_decimal_score(partner, "fraud_risk_score_trailing", 0.0)

    def test_scan_on_a_different_engine_may_repeat_the_identical_window(self, api):
        """The same closed window is free for a second surface, because the cooldown is per engine.

        PRD §3.7: "A different `engine` for the same partner, or the same `engine` for a
        different partner, is never a collision."

        Design: Difficulty/resource_temporal_overlap/monitoring_scan_closed_window_touch_and_cooldown_boundary
        """
        affiliate_id, scan = _partner_with_one_clean_scan(api)

        created = assert_created(
            api.create_monitoring_scan(
                f.monitoring_scan_payload(
                    affiliate_id,
                    engine="BING_ADS",
                    window_start=scan["window_start"],
                    window_end=scan["window_end"],
                ),
                COMPLIANCE_ANALYST,
            )
        )

        assert_fields(
            created,
            {
                "engine": "BING_ADS",
                "window_start": SCAN1_START,
                "window_end": SCAN1_END,
                "opened_case_count": 0,
            },
        )
        assert_append_only_row(created)

        rows = assert_total_count(
            api.list_monitoring_scans(affiliate_id, COMPLIANCE_ANALYST, {"limit": 20}), 2
        )
        assert {row["engine"] for row in rows} == {"GOOGLE_ADS", "BING_ADS"}, (
            "both surfaces must keep their own scan over the identical window"
        )


def _validated_single_line_batch(api):
    """One partner, one 4000-cent accrual, one `VALIDATED` batch prepared by fa-001."""
    program = build_program(
        api,
        setup_clock=AUG_12_12_00,
        partner_type="CONTENT",
        fee_bps=0,
        flat_fee_cents=0,
        policy_category="APPAREL",
        policy_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=400,
        effective_from=f.YEAR_2026_START,
        effective_to=f.YEAR_2027_START,
    )
    order = attributed_order(
        api,
        program,
        order_total_cents=100000,
        is_new_customer=False,
        click_at=AUG_10_10_00,
        placed_at=AUG_12_09_00,
        device_id="D1",
    )
    valid_tax_document(
        api,
        program["affiliate_id"],
        form_type="W9",
        tax_id_last4="9999",
        treaty_withholding_bps=0,
        expires_on=f.TAX_EXPIRY_2027,
    )
    pin_clock(api, SEP_15_00_00)
    batch = generate_batch(
        api, program["network_id"], period_start=PERIOD_START_AUG, period_end=PERIOD_END_SEP
    )
    batch = validate_batch(api, batch["id"], statement_gross_cents=4000, statement_fee_cents=0)
    return program, order, batch


class TestApproveThenVoidConservesBalanceAndLedger:
    def test_approval_moves_the_pre_fee_amount_from_accrued_into_reserved(self, api):
        """Approval reserves the line's pre-fee amount, leaving accrued plus reserved intact.

        PRD §3.9: "On success the batch moves to `APPROVED` with `approved_by_user_id`
        recorded, and for every `INCLUDED` line the line's `net_before_fees_cents` moves
        out of the partner's `accrued_balance_cents` and into its
        `reserved_balance_cents`, with each reserved partner's `version` incremented."

        Design: Difficulty/compensating_invariant/approve_then_void_conserves_affiliate_balance_and_ledger_row_count
        """
        program, _order, batch = _validated_single_line_batch(api)
        affiliate_id = program["affiliate_id"]

        before = read_affiliate(api, affiliate_id)
        assert_cents(before, "accrued_balance_cents", 4000)
        assert_cents(before, "reserved_balance_cents", 0)
        entries = _ledger_rows(api, {"affiliate_id": affiliate_id}, 1)
        assert _signed_ledger_sum(entries) == _balance_pair(before) == 4000, (
            "accrued plus reserved must equal the signed sum of the partner's ledger rows"
        )

        line = _lines_by_affiliate(api, batch["id"], 1)[affiliate_id]
        assert_cents(line, "net_before_fees_cents", 4000)
        assert_cents(line, "net_cents", 4000)

        approved = approve_batch(api, batch["id"], batch["version"])

        assert_fields(approved, {"state": "APPROVED", "approved_by_user_id": "fc-001"})
        after = read_affiliate(api, affiliate_id)
        assert_cents(after, "accrued_balance_cents", 0)
        assert_cents(after, "reserved_balance_cents", 4000)
        assert _balance_pair(after) == 4000, (
            "approval only moves money between the two pools, it never creates or destroys it"
        )
        # §3.9: approval writes no ledger row of its own, so the pool total still
        # reconciles against the single accrual behind it.
        still_one = _ledger_rows(api, {"affiliate_id": affiliate_id}, 1)
        assert _signed_ledger_sum(still_one) == 4000, (
            "the ledger behind the reservation must be unchanged by the approval"
        )

    def test_void_after_approval_restores_the_balances_and_the_exact_ledger_row_set(self, api):
        """Voiding an approved batch returns every cent and leaves the ledger row set untouched.

        PRD §3.9: "Voiding is therefore an exact compensating action for approval:
        approving and then voiding leaves the sum of `accrued_balance_cents` and
        `reserved_balance_cents` and the entire ledger row set exactly as they were
        beforehand."

        Design: Difficulty/compensating_invariant/approve_then_void_conserves_affiliate_balance_and_ledger_row_count
        """
        program, order, batch = _validated_single_line_batch(api)
        affiliate_id = program["affiliate_id"]

        before = read_affiliate(api, affiliate_id)
        original_entry = _ledger_rows(api, {"affiliate_id": affiliate_id}, 1)[0]
        assert_fields(original_entry, {"entry_type": "ACCRUAL", "payout_batch_id": batch["id"]})
        assert_cents(original_entry, "amount_cents", 4000)
        assert _balance_pair(before) == 4000

        approve_batch(api, batch["id"], batch["version"])
        voided = void_batch(api, batch["id"], reason="network statement retracted")

        assert_field(voided, "state", "VOIDED")
        assert_field(_lines_by_affiliate(api, batch["id"], 1)[affiliate_id], "state", "VOIDED")

        after = read_affiliate(api, affiliate_id)
        assert_cents(after, "accrued_balance_cents", 4000)
        assert_cents(after, "reserved_balance_cents", 0)
        assert _balance_pair(after) == _balance_pair(before) == 4000, (
            "the round trip must leave accrued plus reserved exactly where it started"
        )
        assert_cents(after, "lifetime_paid_cents", 0)

        # §3.9: "every ledger entry stamped to this batch is un-stamped back to null,
        # and **no ledger entry is created or deleted**".
        rows = _ledger_rows(api, {"affiliate_id": affiliate_id}, 1)
        surviving = rows[0]
        assert_field(surviving, "id", original_entry["id"])
        assert_fields(surviving, {"entry_type": "ACCRUAL", "payout_batch_id": None})
        assert_cents(surviving, "amount_cents", 4000)
        assert _signed_ledger_sum(rows) == _balance_pair(after), (
            "the signed ledger sum must still equal the partner's pooled balance"
        )
        # §2.4: the commission ledger entry is append-only, so it never grew a version.
        assert_append_only_row(surviving)

        # §3.9: voiding recovers the reservation and touches nothing on the order.
        unwound = read_conversion(api, order["conversion_id"], PROGRAM_ADMIN)
        assert_field(unwound, "validation_status", "VALIDATED")
        assert_cents(unwound, "payable_commission_cents", 4000)


def _coupon_new_customer_program(api):
    """A fresh `CONTENT` partner and one new-customer coupon order of 100000 cents."""
    program = build_program(
        api,
        setup_clock=AUG_12_12_00,
        partner_type="CONTENT",
        fee_bps=0,
        flat_fee_cents=0,
        policy_category="APPAREL",
        policy_scope=["CONTENT"],
        new_customer_rate_bps=900,
        returning_customer_rate_bps=400,
        effective_from=f.YEAR_2026_START,
        effective_to=f.YEAR_2027_START,
    )
    return program, read_affiliate(api, program["affiliate_id"])


class TestFullCancellationConservesLedgerSumAndCounters:
    def test_attribution_books_the_accrual_and_lifts_the_counters(self, api):
        """The forward path books 9000 cents and moves all three attribution counters.

        PRD §3.5: "An `ACCRUAL` ledger entry is appended for the partner in the amount of
        the payable commission, positive in sign. That ledger append raises the partner's
        `accrued_balance_cents` by the same amount."

        Design: Difficulty/compensating_invariant/attribute_then_full_cancellation_conserves_conversion_ledger_sum_and_counters
        """
        program, fresh = _coupon_new_customer_program(api)
        # §3.5: a brand-new `CONTENT` partner sits "at 4500 in `MEDIUM`", so the
        # pre-state tier selects the raw last-click variant at a full credit share.
        assert_bps(fresh, "incrementality_score_bps", 4500)
        assert_field(fresh, "incrementality_tier", "MEDIUM")

        order = attributed_order(
            api,
            program,
            order_total_cents=100000,
            is_new_customer=True,
            coupon_code_used="SAVE10",
            click_at=AUG_10_10_00,
            placed_at=AUG_12_09_00,
            device_id="D1",
        )

        conversion = order["conversion"]
        assert_field(conversion, "attribution_status", "AFFILIATE_ATTRIBUTED")
        assert_cents(conversion, "gross_commission_cents", 9000)
        assert_cents(conversion, "payable_commission_cents", 9000)

        partner = read_affiliate(api, program["affiliate_id"])
        assert_fields(
            partner,
            {
                "attributed_conversion_count": 1,
                "new_customer_attributed_count": 1,
                "coupon_assisted_conversion_count": 1,
                "incrementality_tier": "MEDIUM",
            },
        )
        assert_bps(partner, "incrementality_score_bps", 5500)
        assert_cents(partner, "accrued_balance_cents", 9000)

        rows = _ledger_rows(api, {"conversion_id": order["conversion_id"]}, 1)
        accrual = rows[0]
        assert_fields(
            accrual,
            {
                "entry_type": "ACCRUAL",
                "affiliate_id": program["affiliate_id"],
                "conversion_id": order["conversion_id"],
                "payout_batch_id": None,
            },
        )
        assert_cents(accrual, "amount_cents", 9000)
        assert _signed_ledger_sum(rows) == partner["accrued_balance_cents"] == 9000, (
            "the accrued pool must equal the signed sum of the order's ledger rows"
        )

    def test_full_cancellation_zeroes_the_ledger_sum_by_appending_a_reversal_row(self, api):
        """The cancellation appends a mirror-image row and rewinds every derived counter.

        PRD §3.6: "The magnitude reversed is the order's `payable_commission_cents`,
        appended as a `REVERSAL` entry against that order in the negative of that amount.
        That append lowers the partner's `accrued_balance_cents` by the same magnitude."

        Design: Difficulty/compensating_invariant/attribute_then_full_cancellation_conserves_conversion_ledger_sum_and_counters
        """
        program, fresh = _coupon_new_customer_program(api)
        order = attributed_order(
            api,
            program,
            order_total_cents=100000,
            is_new_customer=True,
            coupon_code_used="SAVE10",
            click_at=AUG_10_10_00,
            placed_at=AUG_12_09_00,
            device_id="D1",
        )
        accrual = _ledger_rows(api, {"conversion_id": order["conversion_id"]}, 1)[0]
        assert_cents(accrual, "amount_cents", 9000)

        # The clock never leaves the thirty-day hold, so §3.6 unwinds the whole
        # accrual: "While the order's `validation_status` is `PENDING_VALIDATION`, the
        # entire accrual is undone regardless of how much of the order came back".
        pin_clock(api, AUG_12_12_00)
        cancelled = assert_object_response(
            api.adjust_order(
                order["conversion_id"],
                f.order_adjustment_payload("FULL_CANCELLATION", 100000, occurred_at=AUG_13_09_00),
                TRACKING_INGESTOR,
            )
        )

        assert_fields(
            cancelled,
            {"attribution_status": "DETACHED", "validation_status": "REVERSED"},
        )
        assert_null(cancelled, "attributed_affiliate_id")
        assert_cents(cancelled, "clawed_back_cents", 9000)
        assert_cents(cancelled, "returned_amount_cents", 100000)

        # §3.6: "The detachment then decrements the partner's
        # `attributed_conversion_count`, and `new_customer_attributed_count` and
        # `coupon_assisted_conversion_count` wherever they had been incremented for this
        # order, and recomputes the partner's `incrementality_score_bps` and
        # `incrementality_tier`."
        partner = read_affiliate(api, program["affiliate_id"])
        assert_fields(
            partner,
            {
                "attributed_conversion_count": 0,
                "new_customer_attributed_count": 0,
                "coupon_assisted_conversion_count": 0,
                "incrementality_tier": fresh["incrementality_tier"],
            },
        )
        assert_bps(partner, "incrementality_score_bps", fresh["incrementality_score_bps"])
        assert_bps(partner, "incrementality_score_bps", 4500)
        assert_cents(partner, "accrued_balance_cents", 0)
        assert_cents(partner, "reserved_balance_cents", 0)

        # §1: "money is append-only: no commission movement is ever edited or deleted,
        # and every correction is a new signed ledger entry".
        rows = _ledger_rows(api, {"conversion_id": order["conversion_id"]}, 2)
        by_type = rows_by(rows, "entry_type")
        assert set(by_type) == {"ACCRUAL", "REVERSAL"}, (
            "the compensation must arrive as a new REVERSAL row beside the original ACCRUAL"
        )
        assert_field(by_type["ACCRUAL"], "id", accrual["id"])
        assert_cents(by_type["ACCRUAL"], "amount_cents", 9000)
        assert_cents(by_type["REVERSAL"], "amount_cents", -9000)
        assert by_type["REVERSAL"]["id"] != accrual["id"], (
            "the reversal must be a distinct row rather than an edit of the accrual"
        )
        for row in rows:
            assert_field(row, "conversion_id", order["conversion_id"])
            assert_append_only_row(row)
        assert _signed_ledger_sum(rows) == 0, (
            "after the compensation the order's signed ledger sum must be exactly zero"
        )
