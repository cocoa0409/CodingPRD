"""Entity output projections (SCAFFOLD section 1.1 field order, PRD section 2.5)."""

FIELDS = {
    "Agency": [
        "id", "name", "agency_code", "agency_type", "status",
        "federal_donee_status", "donee_certification_expires_on",
        "proceeds_account_balance_cents", "posted_distribution_count",
        "created_at", "updated_at", "version",
    ],
    "TurnIn": [
        "id", "turning_in_agency_id", "custody_location", "remarks", "status",
        "rejection_reason", "asset_count", "appraised_total_cents",
        "submitted_at", "reviewed_at", "created_at", "updated_at", "version",
    ],
    "SurplusAsset": [
        "id", "turn_in_id", "component_of_asset_id", "category", "description",
        "acquisition_cost_cents", "acquisition_date", "is_data_bearing",
        "is_restricted", "demil_code", "federal_source",
        "federal_use_period_start_on", "federal_use_period_end_on", "vin",
        "odometer_reading", "title_number", "lien_holder_name",
        "odometer_disclosure_reading", "lien_release_reference",
        "title_recipient_name", "condition_code", "fair_market_value_cents",
        "disposition_status", "clearance_status", "released_at",
        "created_at", "updated_at", "version",
    ],
    "ConditionAssessment": [
        "id", "asset_id", "assessor_user_id", "condition_code", "functional",
        "repair_cost_estimate_cents", "assessed_on", "notes", "superseded",
        "created_at",
    ],
    "ScreeningCycle": [
        "id", "asset_id", "opens_at", "tier_window_days", "current_tier",
        "tier_opened_at", "tier_deadline_at", "status", "tier_advance_count",
        "awarded_by_user_id", "awarded_at", "open_request_count",
        "created_at", "updated_at", "version",
    ],
    "ScreeningRequest": [
        "id", "screening_cycle_id", "requesting_agency_id", "intended_use",
        "justification", "needed_by_date", "tier_at_submission", "status",
        "information_request_note", "resubmission_count", "denial_reason",
        "created_at", "updated_at", "version",
    ],
    "TransferOrder": [
        "id", "asset_id", "recipient_agency_id", "screening_request_id",
        "base_transfer_cents", "handling_fee_cents", "transfer_price_cents",
        "status", "issued_by_user_id", "acknowledged_at", "use_period_end_on",
        "void_reason", "created_at", "updated_at", "version",
    ],
    "SaleVenue": [
        "id", "name", "venue_code", "concurrent_lot_capacity",
        "buyer_premium_pct", "sales_tax_pct", "status", "active_lot_count",
        "created_at", "updated_at", "version",
    ],
    "AuctionLot": [
        "id", "asset_id", "venue_id", "lot_number", "opens_at", "closes_at",
        "reserve_price_cents", "reserve_source", "required_deposit_cents",
        "status", "high_bid_cents", "bid_count", "closed_by_user_id",
        "closed_at", "created_at", "updated_at", "version",
    ],
    "Bidder": [
        "id", "legal_name", "email", "bidder_type", "status",
        "end_use_certificate_expires_on", "deposit_paid_cents",
        "deposit_held_cents", "deposit_applied_cents",
        "deposit_forfeited_cents", "winning_lot_count",
        "created_at", "updated_at", "version",
    ],
    "Bid": [
        "id", "auction_lot_id", "bidder_id", "amount_cents", "placed_at",
        "status", "created_at", "updated_at", "version",
    ],
    "SaleInvoice": [
        "id", "auction_lot_id", "bidder_id", "hammer_price_cents",
        "buyer_premium_cents", "sales_tax_cents", "total_due_cents",
        "amount_paid_cents", "deposit_applied_cents", "balance_due_cents",
        "due_at", "status", "default_reason", "void_reason",
        "created_at", "updated_at", "version",
    ],
    "ClearanceCertificate": [
        "id", "asset_id", "cert_type", "method", "technician_user_id",
        "serials_verified", "certified_on", "notes", "created_at",
    ],
    "ProceedsDistribution": [
        "id", "auction_lot_id", "beneficiary_agency_id", "basis",
        "distributable_base_cents", "service_fee_cents", "cost_recovery_cents",
        "net_to_agency_cents", "status", "posted_by_user_id", "posted_at",
        "reversal_reason", "created_at", "updated_at", "version",
    ],
}


def view(kind, row):
    if row is None:
        return None
    return dict((f, row.get(f)) for f in FIELDS[kind])


def views(kind, rows):
    return [view(kind, r) for r in rows]
