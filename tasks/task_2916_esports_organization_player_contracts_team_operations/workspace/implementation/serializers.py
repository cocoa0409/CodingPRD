"""Resource projections.

PRD section 2.4: every resource exposes `id`, `created_at`, `updated_at` and `version`.
Derived counters are recomputed from their children on every read so that they can never
drift out of step with the records that produce them.
"""

import calc
import db
from db import store


def _base(record):
    return {
        "id": record["id"],
        "created_at": db.iso(record["created_at"]),
        "updated_at": db.iso(record["updated_at"]),
        "version": record["version"],
    }


# --------------------------------------------------------------------------------------
# League
# --------------------------------------------------------------------------------------

def league(record):
    out = _base(record)
    out.update({
        "name": record["name"],
        "season_start_at": db.iso(record["season_start_at"]),
        "season_end_at": db.iso(record["season_end_at"]),
        "roster_lock_at": db.iso(record["roster_lock_at"]),
        "transfer_window_open_at": db.iso(record["transfer_window_open_at"]),
        "transfer_window_close_at": db.iso(record["transfer_window_close_at"]),
        "minimum_salary_cents": record["minimum_salary_cents"],
        "min_roster_size": record["min_roster_size"],
        "max_roster_size": record["max_roster_size"],
        "offer_response_window_hours": record["offer_response_window_hours"],
        "max_negotiation_rounds": record["max_negotiation_rounds"],
        "player_association_levy_bp": record["player_association_levy_bp"],
        "association_min_prize_split_bp": record["association_min_prize_split_bp"],
        "association_max_streaming_hours_per_week":
            record["association_max_streaming_hours_per_week"],
        "minor_max_weekly_minutes": record["minor_max_weekly_minutes"],
        "adult_max_weekly_minutes": record["adult_max_weekly_minutes"],
        "education_reserved_minutes": record["education_reserved_minutes"],
        "minor_age_threshold_years": record["minor_age_threshold_years"],
        "free_agency_cooldown_days": record["free_agency_cooldown_days"],
        "tryout_required_before_offer": record["tryout_required_before_offer"],
        "roster_lock_active": calc.roster_lock_active(record),
    })
    return out


# --------------------------------------------------------------------------------------
# Organization
# --------------------------------------------------------------------------------------

def organization(record):
    committed = calc.committed_salary_cents(record)
    out = _base(record)
    out.update({
        "league_id": record["league_id"],
        "name": record["name"],
        "tax_jurisdiction_code": record["tax_jurisdiction_code"],
        "annual_salary_budget_cents": record["annual_salary_budget_cents"],
        "org_prize_share_bp": record["org_prize_share_bp"],
        "committed_salary_cents": committed,
        "uncommitted_salary_cents": record["annual_salary_budget_cents"] - committed,
        "active_roster_count": calc.active_roster_count(record),
        "prize_payable_cents": calc.prize_payable_cents(record),
        "wellness_flag_count": record["wellness_flag_count"],
    })
    return out


# --------------------------------------------------------------------------------------
# Player
# --------------------------------------------------------------------------------------

def player(record):
    out = _base(record)
    out.update({
        "full_name": record["full_name"],
        "birth_date": record["birth_date"],
        "region_code": record["region_code"],
        "association_member": record["association_member"],
        "player_status": record["player_status"],
        "current_organization_id": record["current_organization_id"],
        "age_years": calc.age_years(record),
        "is_minor": calc.is_minor(record),
        "guardian_consent_status": calc.guardian_consent_status(record),
        "guardian_name": record["guardian_name"],
        "guardian_email": record["guardian_email"],
        "guardian_weekly_cap_minutes": record["guardian_weekly_cap_minutes"],
        "education_enrollment_status": record["education_enrollment_status"],
        "free_agency_window_ends_at": db.iso(record["free_agency_window_ends_at"]),
        "last_release_organization_id": record["last_release_organization_id"],
        "scouted_by_user_id": record["scouted_by_user_id"],
    })
    return out


# --------------------------------------------------------------------------------------
# ContractOffer
# --------------------------------------------------------------------------------------

def offer(record):
    out = _base(record)
    out.update({
        "organization_id": record["organization_id"],
        "player_id": record["player_id"],
        "supersedes_offer_id": record["supersedes_offer_id"],
        "offer_status": record["offer_status"],
        "round_number": record["round_number"],
        "base_salary_cents": record["base_salary_cents"],
        "term_months": record["term_months"],
        "prize_split_player_pct_bp": record["prize_split_player_pct_bp"],
        "streaming_hours_per_week": record["streaming_hours_per_week"],
        "signing_bonus_cents": record["signing_bonus_cents"],
        "buyout_multiplier_bp": record["buyout_multiplier_bp"],
        "tax_residency_code": record["tax_residency_code"],
        "counter_base_salary_cents": record["counter_base_salary_cents"],
        "counter_prize_split_player_pct_bp": record["counter_prize_split_player_pct_bp"],
        "counter_streaming_hours_per_week": record["counter_streaming_hours_per_week"],
        "counter_note": record["counter_note"],
        "decline_note": record["decline_note"],
        "sent_at": db.iso(record["sent_at"]),
        "expires_at": db.iso(record["expires_at"]),
    })
    return out


# --------------------------------------------------------------------------------------
# PlayerContract
# --------------------------------------------------------------------------------------

def contract(record):
    out = _base(record)
    out.update({
        "offer_id": record["offer_id"],
        "player_id": record["player_id"],
        "organization_id": record["organization_id"],
        "contract_status": record["contract_status"],
        "obligation_status": record["obligation_status"],
        "base_salary_cents": record["base_salary_cents"],
        "term_months": record["term_months"],
        "signing_bonus_cents": record["signing_bonus_cents"],
        "prize_split_player_pct_bp": record["prize_split_player_pct_bp"],
        "streaming_hours_per_week": record["streaming_hours_per_week"],
        "buyout_multiplier_bp": record["buyout_multiplier_bp"],
        "tax_residency_code": record["tax_residency_code"],
        "effective_at": db.iso(record["effective_at"]),
        "ends_at": db.iso(record["ends_at"]),
        "provisional_cap_charge_cents": record["provisional_cap_charge_cents"],
        "final_cap_charge_cents": calc.final_cap_charge(record),
        "season_practice_minutes": record["season_practice_minutes"],
        "last_self_reported_load": record["last_self_reported_load"],
        "reported_streaming_minutes_7d": record["reported_streaming_minutes_7d"],
        "burnout_score": record["burnout_score"],
        "wellness_hold_until": db.iso(record["wellness_hold_until"]),
        "suspension_reason": record["suspension_reason"],
        "signed_by_user_id": record["signed_by_user_id"],
    })
    return out


def obligation_summary(record):
    """PRD section 3.6 -- a computed read that persists nothing."""
    player_record = store.players.get(record["player_id"])
    league_record = calc.league_of_contract(record)
    scheduled = 0
    streaming = 0
    cap = 0
    if player_record is not None and league_record is not None:
        minor = calc.is_minor(player_record, league=league_record)
        scheduled, streaming, _total = calc.weekly_committed_minutes(
            player_record, db.now(), league_record, minor_flag=minor
        )
        cap = calc.cap_minutes(player_record, league_record, minor_flag=minor)
    return {
        "contract_id": record["id"],
        "obligation_status": record["obligation_status"],
        "burnout_score": calc.rolling_burnout_score(record),
        "season_burnout_score": calc.season_burnout_score(record),
        "scheduled_minutes_this_week": scheduled,
        "streaming_minutes_this_week": streaming,
        "cap_minutes": cap,
        "provisional_cap_charge_cents": record["provisional_cap_charge_cents"],
        "final_cap_charge_cents": calc.final_cap_charge(record),
        "wellness_hold_until": db.iso(record["wellness_hold_until"]),
    }


# --------------------------------------------------------------------------------------
# TeamHouse / PracticeBlock
# --------------------------------------------------------------------------------------

def team_house(record):
    out = _base(record)
    out.update({
        "organization_id": record["organization_id"],
        "name": record["name"],
        "timezone": record["timezone"],
        "turnaround_buffer_minutes": record["turnaround_buffer_minutes"],
        "concurrent_seat_capacity": record["concurrent_seat_capacity"],
    })
    return out


def practice_block(record):
    out = _base(record)
    out.update({
        "organization_id": record["organization_id"],
        "team_house_id": record["team_house_id"],
        "block_type": record["block_type"],
        "starts_at": db.iso(record["starts_at"]),
        "ends_at": db.iso(record["ends_at"]),
        "duration_minutes": record["duration_minutes"],
        "participant_player_ids": list(record["participant_player_ids"]),
        "coach_user_id": record["coach_user_id"],
        "block_status": record["block_status"],
        "cancel_reason": record["cancel_reason"],
        "coach_note": record["coach_note"],
    })
    return out


# --------------------------------------------------------------------------------------
# SponsorshipDeal / DeliverableAssignment
# --------------------------------------------------------------------------------------

def deal(record):
    out = _base(record)
    out.update({
        "organization_id": record["organization_id"],
        "sponsor_name": record["sponsor_name"],
        "exclusivity_category": record["exclusivity_category"],
        "total_fee_cents": record["total_fee_cents"],
        "deliverable_count_required": record["deliverable_count_required"],
        "starts_at": db.iso(record["starts_at"]),
        "ends_at": db.iso(record["ends_at"]),
        "deal_status": record["deal_status"],
        "assigned_count": calc.deal_assigned_count(record),
        "approved_count": calc.deal_approved_count(record),
        "minor_permitted": record["minor_permitted"],
        "per_deliverable_fee_cents": calc.per_item_fee_cents(record),
        "earned_fee_cents": calc.earned_fee_cents(record),
    })
    return out


def assignment(record):
    out = _base(record)
    out.update({
        "sponsorship_deal_id": record["sponsorship_deal_id"],
        "contract_id": record["contract_id"],
        "deliverable_type": record["deliverable_type"],
        "due_at": db.iso(record["due_at"]),
        "fee_share_cents": record["fee_share_cents"],
        "assignment_status": record["assignment_status"],
        "rejection_count": record["rejection_count"],
        "submission_note": record["submission_note"],
        "review_note": record["review_note"],
    })
    return out


# --------------------------------------------------------------------------------------
# PrizeDistribution / PrizeAllocation
# --------------------------------------------------------------------------------------

def distribution(record):
    out = _base(record)
    out.update({
        "organization_id": record["organization_id"],
        "league_id": record["league_id"],
        "tournament_name": record["tournament_name"],
        "placement": record["placement"],
        "gross_prize_cents": record["gross_prize_cents"],
        "tournament_end_at": db.iso(record["tournament_end_at"]),
        "distribution_status": record["distribution_status"],
        "association_levy_cents": record["association_levy_cents"],
        "org_share_cents": record["org_share_cents"],
        "allocated_cents": record["allocated_cents"],
        "unallocated_cents": record["unallocated_cents"],
        "withholding_total_cents": record["withholding_total_cents"],
        "escrow_total_cents": record["escrow_total_cents"],
        "calculated_by_user_id": record["calculated_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "void_reason": record["void_reason"],
    })
    return out


def allocation(record):
    out = _base(record)
    out.update({
        "prize_distribution_id": record["prize_distribution_id"],
        "contract_id": record["contract_id"],
        "weight_bp": record["weight_bp"],
        "gross_share_cents": record["gross_share_cents"],
        "withholding_rate_bp": record["withholding_rate_bp"],
        "withholding_cents": record["withholding_cents"],
        "escrow_holdback_cents": record["escrow_holdback_cents"],
        "net_cents": record["net_cents"],
        "allocation_status": record["allocation_status"],
    })
    return out


# --------------------------------------------------------------------------------------
# RosterMove
# --------------------------------------------------------------------------------------

def roster_move(record):
    out = _base(record)
    out.update({
        "organization_id": record["organization_id"],
        "player_id": record["player_id"],
        "contract_id": record["contract_id"],
        "transfer_to_organization_id": record["transfer_to_organization_id"],
        "move_type": record["move_type"],
        "move_status": record["move_status"],
        "gross_transfer_fee_cents": record["gross_transfer_fee_cents"],
        "buyout_credit_cents": record["buyout_credit_cents"],
        "commission_tier_bp": record["commission_tier_bp"],
        "agent_commission_cents": record["agent_commission_cents"],
        "net_to_org_cents": record["net_to_org_cents"],
        "released_cap_cents": record["released_cap_cents"],
        "effective_at": db.iso(record["effective_at"]),
        "requested_by_user_id": record["requested_by_user_id"],
        "approved_by_user_id": record["approved_by_user_id"],
        "decision_note": record["decision_note"],
        "reversal_reason": record["reversal_reason"],
    })
    return out
