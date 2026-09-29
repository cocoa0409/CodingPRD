"""Domain lookups, ownership resolution, derivations and the thirteen
calculation rules of PRD §3 / SCAFFOLD §1.3.

Every formula here traces to a sentence of PRD.md; where SCAFFOLD.yaml and the
PRD disagree the PRD text is the one implemented.
"""

from core import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Row lookups (validations priority 4 / 6)
# ---------------------------------------------------------------------------

def need_account(account_id):
    row = store.accounts.get(account_id)
    if row is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "No GroupAccount with id %s." % account_id)
    return row


def need_lead(lead_id):
    row = store.leads.get(lead_id)
    if row is None:
        fail("ERR_LEAD_NOT_FOUND", "No Lead with id %s." % lead_id)
    return row


def need_package(package_id):
    row = store.packages.get(package_id)
    if row is None:
        fail("ERR_PACKAGE_NOT_FOUND", "No ConcessionPackage with id %s." % package_id)
    return row


def need_analysis(analysis_id):
    row = store.analyses.get(analysis_id)
    if row is None:
        fail("ERR_ANALYSIS_NOT_FOUND", "No DisplacementAnalysis with id %s." % analysis_id)
    return row


def need_quote(quote_id):
    row = store.quotes.get(quote_id)
    if row is None:
        fail("ERR_QUOTE_NOT_FOUND", "No RateQuote with id %s." % quote_id)
    return row


def need_contract(contract_id):
    row = store.contracts.get(contract_id)
    if row is None:
        fail("ERR_CONTRACT_NOT_FOUND", "No GroupContract with id %s." % contract_id)
    return row


def need_block(block_id):
    row = store.blocks.get(block_id)
    if row is None:
        fail("ERR_BLOCK_NOT_FOUND", "No RoomBlock with id %s." % block_id)
    return row


def need_reservation(reservation_id):
    row = store.reservations.get(reservation_id)
    if row is None:
        fail("ERR_RESERVATION_NOT_FOUND", "No Reservation with id %s." % reservation_id)
    return row


def need_charge(charge_id):
    row = store.charges.get(charge_id)
    if row is None:
        fail("ERR_CHARGE_NOT_FOUND", "No AncillaryCharge with id %s." % charge_id)
    return row


def need_reconciliation(recon_id):
    row = store.reconciliations.get(recon_id)
    if row is None:
        fail("ERR_RECONCILIATION_NOT_FOUND", "No Reconciliation with id %s." % recon_id)
    return row


def need_hold(hold_id):
    row = store.holds.get(hold_id)
    if row is None:
        fail("ERR_HOLD_NOT_FOUND", "No FunctionSpaceHold with id %s." % hold_id)
    return row


# ---------------------------------------------------------------------------
# Relationship walks
# ---------------------------------------------------------------------------

def lead_of_quote(quote):
    return store.leads.get(quote.get("lead_id"))


def quote_of_contract(contract):
    return store.quotes.get(contract.get("quote_id"))


def lead_of_contract(contract):
    quote = quote_of_contract(contract)
    return lead_of_quote(quote) if quote else None


def account_of_contract(contract):
    lead = lead_of_contract(contract)
    return store.accounts.get(lead["account_id"]) if lead else None


def account_of_lead(lead):
    return store.accounts.get(lead.get("account_id"))


def contract_of_block(block):
    return store.contracts.get(block.get("contract_id"))


def block_of_reservation(reservation):
    return store.blocks.get(reservation.get("block_id"))


def contract_of_reservation(reservation):
    block = block_of_reservation(reservation)
    return contract_of_block(block) if block else None


def quotes_of_lead(lead_id):
    return in_order([q for q in store.quotes.values() if q["lead_id"] == lead_id])


def analyses_of_lead(lead_id):
    return in_order([a for a in store.analyses.values() if a["lead_id"] == lead_id])


def holds_of_lead(lead_id):
    return [h for h in store.holds.values() if h["lead_id"] == lead_id]


def leads_of_account(account_id):
    return in_order([l for l in store.leads.values() if l["account_id"] == account_id])


def contracts_of_quote(quote_id):
    return in_order([c for c in store.contracts.values() if c["quote_id"] == quote_id])


def blocks_of_contract(contract_id):
    return in_order([b for b in store.blocks.values() if b["contract_id"] == contract_id])


def master_block_of(contract_id):
    for block in blocks_of_contract(contract_id):
        if block["parent_block_id"] is None:
            return block
    return None


def child_blocks_of(block_id):
    return in_order([b for b in store.blocks.values() if b["parent_block_id"] == block_id])


def descendant_blocks_of(block_id):
    out = []
    for child in child_blocks_of(block_id):
        out.append(child)
        out.extend(descendant_blocks_of(child["id"]))
    return out


def nights_of_block(block_id):
    rows = [n for n in store.nights.values() if n["block_id"] == block_id]
    return sorted(rows, key=lambda n: n["stay_date"])


def night_of_block(block_id, stay_date_iso):
    for night in store.nights.values():
        if night["block_id"] == block_id and night["stay_date"] == stay_date_iso:
            return night
    return None


def reservations_of_block(block_id):
    return in_order([r for r in store.reservations.values() if r["block_id"] == block_id])


def reservations_of_contract(contract_id):
    block_ids = set(b["id"] for b in blocks_of_contract(contract_id))
    return in_order([r for r in store.reservations.values() if r["block_id"] in block_ids])


def charges_of_contract(contract_id):
    return in_order([c for c in store.charges.values() if c["contract_id"] == contract_id])


def reconciliations_of_contract(contract_id):
    return in_order([r for r in store.reconciliations.values()
                     if r["contract_id"] == contract_id])


def newest_reconciliation(contract_id):
    rows = reconciliations_of_contract(contract_id)
    return rows[-1] if rows else None


def contracts_of_account(account_id):
    out = []
    for contract in store.contracts.values():
        lead = lead_of_contract(contract)
        if lead is not None and lead["account_id"] == account_id:
            out.append(contract)
    return in_order(out)


# ---------------------------------------------------------------------------
# GroupContact ownership (validations priority 5)
# ---------------------------------------------------------------------------

def owner_of_lead(lead):
    return lead.get("account_id")


def owner_of_quote(quote):
    lead = lead_of_quote(quote)
    return lead.get("account_id") if lead else None


def owner_of_contract(contract):
    lead = lead_of_contract(contract)
    return lead.get("account_id") if lead else None


def owner_of_block(block):
    contract = contract_of_block(block)
    return owner_of_contract(contract) if contract else None


def owner_of_reservation(reservation):
    block = block_of_reservation(reservation)
    return owner_of_block(block) if block else None


def owner_of_charge(charge):
    contract = store.contracts.get(charge.get("contract_id"))
    return owner_of_contract(contract) if contract else None


def owner_of_reconciliation(recon):
    contract = store.contracts.get(recon.get("contract_id"))
    return owner_of_contract(contract) if contract else None


def owner_of_hold(hold):
    lead = store.leads.get(hold.get("lead_id"))
    return owner_of_lead(lead) if lead else None


def require_owner(owner_account_id):
    """PRD §2.1: a GroupContact reaching a real row it does not own gets 403,
    never 404 -- ownership is checked after path existence."""
    if is_group_contact() and actor() != owner_account_id:
        fail("ERR_UNAUTHORIZED",
             "This GroupContact does not act for the owning client organization.")


def filter_owned(rows, resolver):
    """A GroupContact's list reads are narrowed to its own organization."""
    if not is_group_contact():
        return rows
    mine = actor()
    return [r for r in rows if resolver(r) == mine]


# ---------------------------------------------------------------------------
# House inventory calendar
# ---------------------------------------------------------------------------

def inventory_day(day):
    key = day if isinstance(day, str) else iso_date(day)
    return store.inventory_by_date.get(key)


def require_calendar(days):
    """validations priority 19."""
    for day in days:
        if inventory_day(day) is None:
            fail("ERR_INVENTORY_DAY_MISSING",
                 "No InventoryDay row for %s." % (day if isinstance(day, str) else iso_date(day)))


def stay_dates(arrival_iso, departure_iso):
    return date_range(parse_date_str(arrival_iso), parse_date_str(departure_iso))


def move_held(days, delta):
    for day in days:
        row = inventory_day(day)
        if row is None:
            continue
        row["held_group_rooms"] = row["held_group_rooms"] + delta
        touch(row)


def move_committed(day, delta):
    row = inventory_day(day)
    if row is None:
        return
    row["committed_group_rooms"] = row["committed_group_rooms"] + delta
    touch(row)


# ---------------------------------------------------------------------------
# Derived night and block roll-ups (PRD §3.6)
# ---------------------------------------------------------------------------

def night_rooms_sub_allocated(night):
    """Rooms of this night carved out to sub-blocks whose inventory_status is
    not RELEASED (PRD §3.6: a released sub-block returns its rooms to the
    parent's open pool)."""
    total = 0
    for child in child_blocks_of(night["block_id"]):
        if child["inventory_status"] == "RELEASED":
            continue
        child_night = night_of_block(child["id"], night["stay_date"])
        if child_night is not None:
            total += child_night["rooms_allotted"]
    return total


def night_rooms_picked_up(night):
    """Own reservations of the block whose half-open stay range covers this
    date and whose status is in the pickup set."""
    stay = night["stay_date"]
    count = 0
    for res in store.reservations.values():
        if res["block_id"] != night["block_id"]:
            continue
        if res["status"] not in PICKUP_STATUSES:
            continue
        if res["arrival_date"] <= stay < res["departure_date"]:
            count += 1
    return count


def night_rooms_open(night):
    return (night["rooms_allotted"]
            - night_rooms_sub_allocated(night)
            - night_rooms_picked_up(night)
            - night["rooms_released"])


def night_unallocated(night):
    """The figure a sub-block carve is measured against (validations #30)."""
    return (night["rooms_allotted"]
            - night_rooms_sub_allocated(night)
            - night_rooms_picked_up(night)
            - night["rooms_released"])


def block_allotted_room_nights(block):
    return sum(n["rooms_allotted"] for n in nights_of_block(block["id"]))


def block_own_pickup(block):
    return sum(night_rooms_picked_up(n) for n in nights_of_block(block["id"]))


def block_picked_up_room_nights(block):
    total = block_own_pickup(block)
    if block["parent_block_id"] is None:
        for child in descendant_blocks_of(block["id"]):
            total += block_own_pickup(child)
    return total


def block_released_room_nights(block):
    return sum(n["rooms_released"] for n in nights_of_block(block["id"]))


def block_peak_night_rooms(block):
    nights = nights_of_block(block["id"])
    if not nights:
        return 0
    return max(night_rooms_picked_up(n) for n in nights)


def block_comp_room_nights(block):
    total = 0
    for res in reservations_of_block(block["id"]):
        if res["is_comp"] and res["status"] != "CANCELLED":
            total += res["room_nights"]
    return total


# ---------------------------------------------------------------------------
# calculations.lead_qualification_score / lead_room_night_value
# ---------------------------------------------------------------------------

def lead_qualification_score(lead, account):
    volume = min(40, lead["total_requested_room_nights"] // 10)
    peak = min(25, lead["peak_rooms"] // 4)
    ratio = D(lead["meeting_space_sqft_needed"]) / D(max(1, lead["peak_rooms"]))
    if ratio <= D(30):
        space = 15
    elif ratio <= D(60):
        space = 8
    else:
        space = 0
    lead_days = whole_days(parse_date_str(lead["arrival_date"]), store.today())
    if lead_days >= 180:
        timing = 20
    elif lead_days >= 90:
        timing = 12
    else:
        timing = 5
    raw = volume + peak + space + timing
    scaled = round_half_up(D(raw) * SEGMENT_MULTIPLIER[account["market_segment"]])
    return min(100, scaled)


def lead_room_night_value(lead):
    """Strictly pinned two-stage rounding (PRD §3.2)."""
    days = stay_dates(lead["arrival_date"], lead["departure_date"])
    total = 0
    for day in days:
        total += inventory_day(day)["transient_adr_cents"]
    average = round_half_up(D(total) / D(len(days)))
    nightly = round_half_up(D(average) * GROUP_RATE_FACTOR)
    return nightly * lead["total_requested_room_nights"]


# ---------------------------------------------------------------------------
# calculations.displacement_cost
# ---------------------------------------------------------------------------

def displacement_cost(lead, variant):
    displaced_room_nights = 0
    displaced_revenue = 0
    for day in stay_dates(lead["arrival_date"], lead["departure_date"]):
        row = inventory_day(day)
        transient_could_have = (row["total_rooms"]
                                - row["committed_group_rooms"]
                                - row["held_group_rooms"])
        if variant == "FORECAST_BASED":
            demand = row["transient_demand_rooms"]
            rate = row["transient_adr_cents"]
        else:
            demand = row["historical_pickup_rooms"]
            rate = row["historical_adr_cents"]
        displaced = demand + lead["peak_rooms"] - transient_could_have
        if displaced < 0:
            displaced = 0
        displaced_room_nights += displaced
        displaced_revenue += displaced * rate
    group_revenue = lead["estimated_room_night_value_cents"] or 0
    ancillary = round_half_up(
        D(lead["peak_rooms"]) * D(lead["nights_count"]) * D(ANCILLARY_PER_ROOM_NIGHT_CENTS))
    net_benefit = group_revenue + ancillary - displaced_revenue
    return {
        "displaced_room_nights": displaced_room_nights,
        "displaced_revenue_cents": displaced_revenue,
        "group_revenue_cents": group_revenue,
        "ancillary_projection_cents": ancillary,
        "net_benefit_cents": net_benefit,
        "verdict": "ACCEPT" if net_benefit >= 0 else "OVERRIDE_REQUIRED",
    }


# ---------------------------------------------------------------------------
# calculations.effective_net_rate / ancillary_net
# ---------------------------------------------------------------------------

def effective_net_rate(base_rate_cents, room_rate_discount_pct, comp_room_ratio,
                       rebate_per_room_night_cents):
    """Three components, each rounded to whole cents BEFORE any subtraction."""
    rate_component = round_half_up(D(base_rate_cents) * D(room_rate_discount_pct))
    comp_component = round_half_up(D(base_rate_cents) / (D(comp_room_ratio) + D(1)))
    rebate_component = rebate_per_room_night_cents
    return base_rate_cents - rate_component - comp_component - rebate_component


def ancillary_discount_pct(package, category):
    if category == "BANQUET":
        return package["banquet_discount_pct"]
    if category == "AUDIOVISUAL":
        return package["av_discount_pct"]
    if category == "PARKING":
        return package["parking_discount_pct"]
    return 0.0


def ancillary_net(gross_amount_cents, discount_pct):
    return round_half_up(D(gross_amount_cents) * (D(1) - D(discount_pct)))


def discount_stack(package):
    return (D(package["room_rate_discount_pct"])
            + D(package["banquet_discount_pct"])
            + D(package["av_discount_pct"])
            + D(package["parking_discount_pct"]))


# ---------------------------------------------------------------------------
# calculations.comp_room_entitlement (PRD §3.6)
# ---------------------------------------------------------------------------

def rederive_comp_designations(contract):
    """Re-walk the contract's entire non-cancelled reservation set in ascending
    created_at order, restarting from scratch every time."""
    if contract is None:
        return
    quote = quote_of_contract(contract)
    ratio = quote["comp_room_ratio"] if quote else 1
    if ratio < 1:
        ratio = 1
    contracted_rate = contract["contracted_rate_cents"]
    comp_awarded = 0
    paid_room_nights = 0
    for res in reservations_of_contract(contract["id"]):
        if res["status"] == "CANCELLED":
            continue
        if (paid_room_nights // ratio) > comp_awarded:
            new_comp, new_rate = True, 0
            comp_awarded += 1
        else:
            new_comp, new_rate = False, contracted_rate
            paid_room_nights += res["room_nights"]
        if res["is_comp"] != new_comp or res["rate_cents"] != new_rate:
            res["is_comp"] = new_comp
            res["rate_cents"] = new_rate
            touch(res)


# ---------------------------------------------------------------------------
# calculations.attrition_liability (PRD §3.7)
# ---------------------------------------------------------------------------

def actualized_reservations(contract_id):
    return [r for r in reservations_of_contract(contract_id)
            if r["status"] in ACTUALIZED_STATUSES]


def actualized_totals(contract_id):
    rows = actualized_reservations(contract_id)
    actualized = sum(r["room_nights"] for r in rows)
    billable = sum(r["room_nights"] for r in rows if not r["is_comp"])
    return actualized, billable


def waived_room_nights(contract_id):
    total = 0
    for block in blocks_of_contract(contract_id):
        if block["billing_status"] == "WAIVED":
            total += block_allotted_room_nights(block)
    return total


def commitment_base_room_nights(contract):
    return contract["contracted_room_nights"] - waived_room_nights(contract["id"])


def actual_peak_actualized(contract):
    rows = actualized_reservations(contract["id"])
    peak = 0
    for day in stay_dates(contract["arrival_date"], contract["departure_date"]):
        stay = iso_date(day)
        count = 0
        for res in rows:
            if res["arrival_date"] <= stay < res["departure_date"]:
                count += 1
        if count > peak:
            peak = count
    return peak


def attrition_damages_from_shortfall(contract, shortfall_room_nights):
    return round_half_up(D(shortfall_room_nights)
                         * D(contract["contracted_rate_cents"])
                         * ATTRITION_DAMAGE_FACTOR)


def attrition_room_nights_basis(contract, actualized):
    base = commitment_base_room_nights(contract)
    commitment = ceil_int(D(base) * D(contract["attrition_threshold_pct"]))
    shortfall = commitment - actualized
    if shortfall < 0:
        shortfall = 0
    return shortfall


def attrition_peak_night_basis(contract):
    commitment = ceil_int(D(contract["contracted_peak_rooms"])
                          * D(contract["attrition_threshold_pct"]))
    peak = actual_peak_actualized(contract)
    shortfall_rooms = commitment - peak
    if shortfall_rooms < 0:
        shortfall_rooms = 0
    return shortfall_rooms * contract["nights_count"]


def attrition_liability(contract):
    actualized, billable = actualized_totals(contract["id"])
    if contract["attrition_basis"] == "ROOM_NIGHTS":
        shortfall = attrition_room_nights_basis(contract, actualized)
    else:
        shortfall = attrition_peak_night_basis(contract)
    return {
        "actualized_room_nights": actualized,
        "billable_room_nights": billable,
        "attrition_shortfall_room_nights": shortfall,
        "attrition_damages_cents": attrition_damages_from_shortfall(contract, shortfall),
    }


def both_attrition_projections(contract):
    actualized, _billable = actualized_totals(contract["id"])
    rn_shortfall = attrition_room_nights_basis(contract, actualized)
    peak_shortfall = attrition_peak_night_basis(contract)
    return {
        "room_nights_basis_shortfall": rn_shortfall,
        "room_nights_basis_damages_cents":
            attrition_damages_from_shortfall(contract, rn_shortfall),
        "peak_night_basis_shortfall": peak_shortfall,
        "peak_night_basis_damages_cents":
            attrition_damages_from_shortfall(contract, peak_shortfall),
    }


# ---------------------------------------------------------------------------
# calculations.ancillary posted / receivable_conservation (PRD §3.8)
# ---------------------------------------------------------------------------

def posted_ancillary_cents(contract_id):
    return sum(c["net_amount_cents"] for c in charges_of_contract(contract_id)
               if c["status"] == "POSTED")


def recompute_receivable(contract):
    """The conserved ledger identity, always re-derived, never nudged."""
    posted = posted_ancillary_cents(contract["id"])
    total = posted + contract["assessed_damages_cents"] - contract["rebate_paid_cents"]
    changed = (contract["ancillary_posted_cents"] != posted
               or contract["receivable_total_cents"] != total)
    contract["ancillary_posted_cents"] = posted
    contract["receivable_total_cents"] = total
    return changed


# ---------------------------------------------------------------------------
# calculations.settlement_waterfall (PRD §3.9) -- six normative steps
# ---------------------------------------------------------------------------

def settlement_waterfall(attrition_damages_cents, ancillary_net_cents,
                         rebate_per_room_night_cents, billable_room_nights,
                         incentive_rate_snapshot):
    gross = attrition_damages_cents + ancillary_net_cents
    cap = round_half_up(D(gross) * REBATE_CAP_PCT)
    earned = rebate_per_room_night_cents * billable_room_nights
    rebate_payable = earned if earned < cap else cap
    net_before = gross - rebate_payable
    bonus = SIZE_BONUS_PCT if net_before >= SIZE_BONUS_FLOOR_CENTS else D(0)
    applied = D(incentive_rate_snapshot) + bonus
    if applied > INCENTIVE_RATE_CAP:
        applied = INCENTIVE_RATE_CAP
    incentive = round_half_up(D(net_before) * applied)
    return {
        "gross_settlement_cents": gross,
        "rebate_payable_cents": rebate_payable,
        "net_before_incentive_cents": net_before,
        "rebooking_incentive_cents": incentive,
        "total_settlement_cents": net_before - incentive,
    }


def recompute_reconciliation(recon, contract):
    """Re-derive a DRAFT settlement in place; incentive_rate_snapshot is frozen."""
    quote = quote_of_contract(contract)
    liability = attrition_liability(contract)
    recon.update(liability)
    recon["ancillary_net_cents"] = posted_ancillary_cents(contract["id"])
    recon.update(settlement_waterfall(
        recon["attrition_damages_cents"],
        recon["ancillary_net_cents"],
        quote["rebate_per_room_night_cents"] if quote else 0,
        recon["billable_room_nights"],
        recon["incentive_rate_snapshot"],
    ))


# ---------------------------------------------------------------------------
# calculations.cancellation_damages (PRD §3.9)
# ---------------------------------------------------------------------------

def cancellation_damages(contract, reason):
    notice_days = whole_days(parse_date_str(contract["arrival_date"]), store.today())
    if notice_days >= 180:
        tier = D("0.25")
    elif notice_days >= 90:
        tier = D("0.50")
    elif notice_days >= 30:
        tier = D("0.75")
    else:
        tier = D("1.00")
    master = master_block_of(contract["id"])
    picked_up = block_picked_up_room_nights(master) if master is not None else 0
    remainder = contract["contracted_room_nights"] - picked_up
    if remainder < 0:
        remainder = 0
    mitigated_base = D(remainder) * D(contract["contracted_rate_cents"])
    if reason == "FORCE_MAJEURE":
        if contract["force_majeure_clause"] in ("STANDARD", "EXPANDED"):
            return 0
        return round_half_up(mitigated_base * tier * FM_NO_CLAUSE_FACTOR)
    return round_half_up(mitigated_base * tier)


# ---------------------------------------------------------------------------
# calculations.account_rebooking_tier (PRD §3.1 / §3.9)
# ---------------------------------------------------------------------------

def account_history(account_id):
    completed = [c for c in contracts_of_account(account_id) if c["status"] == "COMPLETED"]
    repeat_count = len(completed)
    last_departure = None
    for contract in completed:
        if last_departure is None or contract["departure_date"] > last_departure:
            last_departure = contract["departure_date"]
    lifetime = 0
    for recon in store.reconciliations.values():
        if recon["status"] != "FINALIZED":
            continue
        contract = store.contracts.get(recon["contract_id"])
        if contract is None:
            continue
        lead = lead_of_contract(contract)
        if lead is not None and lead["account_id"] == account_id:
            lifetime += recon["actualized_room_nights"]
    return repeat_count, lifetime, last_departure


def account_rebooking_tier(repeat_count, lifetime, last_departure):
    if repeat_count >= 3 or lifetime >= 1500:
        base = D("0.05")
    elif repeat_count >= 1 or lifetime >= 400:
        base = D("0.03")
    else:
        base = D("0.01")
    if last_departure is not None:
        elapsed = whole_days(store.today(), parse_date_str(last_departure))
        if elapsed > LAPSE_DAYS:
            if base == D("0.05"):
                base = D("0.03")
            elif base == D("0.03"):
                base = D("0.01")
    return float(base)


# ---------------------------------------------------------------------------
# Quote holds, lazy expiry and the group ceiling
# ---------------------------------------------------------------------------

def quote_stay_dates(quote):
    lead = lead_of_quote(quote)
    return stay_dates(lead["arrival_date"], lead["departure_date"])


def release_quote_hold(quote):
    """Take a PROPOSED/COUNTERED quote's soft hold back off the calendar."""
    if not quote.get("hold_placed"):
        return
    move_held(quote_stay_dates(quote), -quote["quoted_peak_rooms"])
    quote["hold_placed"] = False


def expire_quote_if_lapsed(quote):
    """Lazy expiry (PRD §3.4): evaluated when the quote is read for writing."""
    if quote["status"] not in ("PROPOSED", "COUNTERED"):
        return
    expires = parse_instant_str(quote["expires_at"])
    if store.now() < expires:
        return
    quote["status"] = "EXPIRED"
    release_quote_hold(quote)
    touch(quote)
    fail("ERR_QUOTE_EXPIRED", "The quote expired at %s." % quote["expires_at"])


def require_quote_live(quote):
    expires = parse_instant_str(quote["expires_at"])
    if store.now() >= expires:
        fail("ERR_QUOTE_EXPIRED", "The quote expired at %s." % quote["expires_at"])


def withdraw_quotes_of_lead(lead_id, skip_quote_id=None, statuses=("DRAFT", "PROPOSED", "COUNTERED")):
    for quote in quotes_of_lead(lead_id):
        if skip_quote_id is not None and quote["id"] == skip_quote_id:
            continue
        if quote["status"] not in statuses:
            continue
        quote["status"] = "WITHDRAWN"
        release_quote_hold(quote)
        touch(quote)


def check_group_ceiling(day_room_pairs, exclude_held=0):
    """validations priority 28. day_room_pairs is a list of (date, rooms)."""
    for day, rooms in day_room_pairs:
        row = inventory_day(day)
        if row is None:
            continue
        occupied = (row["held_group_rooms"] - exclude_held
                    + row["committed_group_rooms"] + rooms)
        if occupied > row["group_ceiling_rooms"]:
            fail("ERR_GROUP_CEILING_EXCEEDED",
                 "The group ceiling on %s admits no more rooms."
                 % (day if isinstance(day, str) else iso_date(day)))


def lead_has_approved_analysis(lead_id):
    return any(a["status"] == "APPROVED" for a in analyses_of_lead(lead_id))


def lead_has_pending_analysis(lead_id):
    return any(a["status"] == "PENDING" for a in analyses_of_lead(lead_id))


def require_displacement_cleared(lead_id):
    """validations priority 18."""
    if not lead_has_approved_analysis(lead_id) or lead_has_pending_analysis(lead_id):
        fail("ERR_DISPLACEMENT_NOT_APPROVED",
             "The lead needs an APPROVED displacement analysis and no PENDING one.")


# ---------------------------------------------------------------------------
# Function-space holds
# ---------------------------------------------------------------------------

def release_held_space(lead_id):
    for hold in holds_of_lead(lead_id):
        if hold["status"] == "HELD":
            hold["status"] = "RELEASED"
            touch(hold)


def confirm_held_space(lead_id):
    for hold in holds_of_lead(lead_id):
        if hold["status"] == "HELD":
            hold["status"] = "CONFIRMED"
            touch(hold)


def check_space_conflict(space_code, start_at, end_at):
    """validations priority 25: existing intervals extended by the turnover
    buffer at their end, compared half-open."""
    buffer_delta = timedelta(minutes=TURNOVER_MINUTES)
    for hold in store.holds.values():
        if hold["space_code"] != space_code:
            continue
        if hold["status"] not in ("HELD", "CONFIRMED"):
            continue
        existing_start = parse_instant_str(hold["start_at"])
        existing_end = parse_instant_str(hold["end_at"]) + buffer_delta
        if start_at < existing_end and existing_start < end_at:
            fail("ERR_FUNCTION_SPACE_CONFLICT",
                 "Space %s is occupied until %s including turnover."
                 % (space_code, iso_instant(existing_end)))


# ---------------------------------------------------------------------------
# Block cascades (PRD §3.7 cutoff, §3.9 release)
# ---------------------------------------------------------------------------

def cutoff_block_cascade(block):
    """Four hops in normative order."""
    targets = [block]
    block["inventory_status"] = "CUT_OFF"
    for child in child_blocks_of(block["id"]):
        if child["inventory_status"] == "OPEN":
            child["inventory_status"] = "CUT_OFF"
            targets.append(child)
    for touched in targets:
        is_master = touched["parent_block_id"] is None
        for night in nights_of_block(touched["id"]):
            previous = night["rooms_released"]
            released = (night["rooms_allotted"]
                        - night_rooms_sub_allocated(night)
                        - night_rooms_picked_up(night))
            if released < 0:
                released = 0
            if released != previous:
                night["rooms_released"] = released
                touch(night)
            if is_master and released > previous:
                move_committed(night["stay_date"], -(released - previous))
        touch(touched)
    return targets


def release_blocks_of_contract(contract):
    """Contract cancellation hands back every remaining room."""
    releasable = [b for b in blocks_of_contract(contract["id"])
                  if b["inventory_status"] in ("SETUP", "OPEN", "CUT_OFF")]
    for block in releasable:
        block["inventory_status"] = "RELEASED"
    for block in releasable:
        is_master = block["parent_block_id"] is None
        for night in nights_of_block(block["id"]):
            previous = night["rooms_released"]
            remaining_committed = night["rooms_allotted"] - previous
            if remaining_committed < 0:
                remaining_committed = 0
            if previous != night["rooms_allotted"]:
                night["rooms_released"] = night["rooms_allotted"]
                touch(night)
            if is_master and remaining_committed > 0:
                move_committed(night["stay_date"], -remaining_committed)
        touch(block)
    return releasable


def cancel_reservations_of_blocks(blocks):
    block_ids = set(b["id"] for b in blocks)
    for res in in_order([r for r in store.reservations.values()
                         if r["block_id"] in block_ids]):
        if res["status"] in ("PENDING", "CONFIRMED"):
            res["status"] = "CANCELLED"
            touch(res)


def void_all_charges(contract):
    for charge in charges_of_contract(contract["id"]):
        if charge["status"] in ("QUOTED", "POSTED"):
            charge["status"] = "VOIDED"
            touch(charge)
