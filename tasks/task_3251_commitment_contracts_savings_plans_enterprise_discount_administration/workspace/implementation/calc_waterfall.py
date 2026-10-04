from decimal import Decimal
from store import STORE, CLOCK, new_id
from calc_tiers import round_cents, tier_discount_for
from calc_amend import amendment_rate_for
from calc_coverage import active_plan_for_family
from calc_credits import candidate_grants


def generate_invoice_lines(org, agreement, period_index):
    """Compute the four-stage waterfall for one org/period.

    Returns (lines list of dicts, usage_records swept, eligible_period_spend int).
    Line dicts contain integer cent fields + transient '_account_created' for ordering.
    """
    # Sweep usage
    usage = [u for u in STORE.usage.values()
             if u['org_id'] == org['id'] and u['status'] == 'INGESTED'
             and u['period_index'] == period_index]
    usage.sort(key=lambda u: (STORE.linked_accounts[u['linked_account_id']]['created_at'],
                              u['linked_account_id'], u['service_family'], u['usage_hour_start']))

    # Group into lines keyed (account, family), ordered by account created_at, family ASC
    groups = {}
    order = []
    for u in usage:
        key = (u['linked_account_id'], u['service_family'])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(u)
    order.sort(key=lambda k: (STORE.linked_accounts[k[0]]['created_at'], k[0], k[1]))

    lines = []
    # Shared per-(plan, hour) remaining coverage budget across all lines
    hour_budget = {}
    # c0 keyed by service family
    fam_c0 = {}
    eligible_spend = 0
    covered_families = set()
    if agreement is not None:
        for t in STORE.tiers.values():
            if t['agreement_id'] == agreement['id']:
                covered_families.add(t['service_family'])
        for fam in covered_families:
            fam_c0[fam] = Decimal(agreement['consumed_commitment_cents'])

    for key in order:
        account_id, family = key
        recs = groups[key]
        list_cents = sum(u['list_price_cents'] for u in recs)

        # Stage 1: amendment
        amendment_discount = Decimal(0)
        base_after_amend = Decimal(0)
        for u in recs:
            u_base = Decimal(u['list_price_cents'])
            if agreement is not None:
                rate = amendment_rate_for(agreement, family, u['usage_hour_start'])
            else:
                rate = None
            if rate is not None:
                u_after = u_base * (Decimal(1) - rate)
                amendment_discount += u_base - u_after
            else:
                u_after = u_base
            base_after_amend += u_after

        # Stage 2: plan coverage. Per §3.4 ACTUAL replay, the plan's hourly
        # budget is shared across ALL of the org's accounts in account
        # created_at ascending order, so track remaining budget per
        # (plan, usage_hour) across lines rather than per line.
        plan_covered = Decimal(0)
        plan_discount = Decimal(0)
        base_after_plan = Decimal(0)
        for u in sorted(recs, key=lambda x: x['usage_hour_start']):
            u_base = Decimal(u['list_price_cents'])
            rate_am = None
            if agreement is not None:
                rate_am = amendment_rate_for(agreement, family, u['usage_hour_start'])
            u_after_am = u_base if rate_am is None else u_base * (Decimal(1) - rate_am)
            plan = active_plan_for_family(org['id'], family, u['usage_hour_start'])
            if plan is not None:
                hkey = (plan['id'], u['usage_hour_start'])
                if hkey not in hour_budget:
                    hour_budget[hkey] = Decimal(plan['hourly_commitment_cents'])
                remaining = hour_budget[hkey]
                covered_amt = min(u_after_am, remaining)
                hour_budget[hkey] = remaining - covered_amt
                uncovered = u_after_am - covered_amt
                plan_covered += covered_amt
                plan_discount += covered_amt * Decimal(str(plan['plan_discount_rate']))
                base_after_plan += uncovered + covered_amt * (Decimal(1) - Decimal(str(plan['plan_discount_rate'])))
            else:
                base_after_plan += u_after_am

        # Stage 3: tier discount on post-stage-2 amount
        tier_discount = Decimal(0)
        if agreement is not None and family in covered_families:
            tiers = sorted([t for t in STORE.tiers.values()
                            if t['agreement_id'] == agreement['id'] and t['service_family'] == family],
                           key=lambda t: t['threshold_cents'])
            c0 = fam_c0[family]
            tier_discount, c1 = tier_discount_for(base_after_plan, c0, tiers)
            fam_c0[family] = c1

        base_after_tier = base_after_plan - tier_discount
        if base_after_tier < 0:
            base_after_tier = Decimal(0)

        # Eligible spend accrual (pass-1 weighting on raw list price)
        for u in recs:
            if family in covered_families:
                if u['is_marketplace']:
                    eligible_spend += int((Decimal(u['list_price_cents']) * Decimal('0.5')).to_integral_value(rounding='ROUND_FLOOR'))
                else:
                    eligible_spend += u['list_price_cents']

        lines.append({
            'linked_account_id': account_id,
            'service_family': family,
            'list_cents': list_cents,
            '_amend_dec': amendment_discount,
            '_plan_covered_dec': plan_covered,
            '_plan_dec': plan_discount,
            '_tier_dec': tier_discount,
            '_post_tier_dec': base_after_tier,
            '_records': recs,
        })

    # Stage 4: credit allocation over post-stage-3 remainders (rounded)
    pool = candidate_grants(org['id'])
    post3_totals = [round_cents(ln['_post_tier_dec']) for ln in lines]
    outstanding = sum(post3_totals)
    debits_left = {}
    for g in pool:
        if outstanding <= 0:
            break
        take = min(g['remaining_cents'], outstanding)
        if take > 0:
            debits_left[g['id']] = debits_left.get(g['id'], 0) + take
            outstanding -= take
    # Proportional allocation: walk lines in order, assign from grants in expiry order
    credits_per_line = [0] * len(lines)
    g_pool = [(g, debits_left[g['id']]) for g in pool if debits_left.get(g['id'], 0) > 0]
    gi = 0
    for i, ln in enumerate(lines):
        need = post3_totals[i]
        while need > 0 and gi < len(g_pool):
            g, left = g_pool[gi]
            if left <= 0:
                gi += 1
                continue
            take = min(left, need)
            credits_per_line[i] += take
            g_pool[gi] = (g, left - take)
            need -= take
            if g_pool[gi][1] <= 0:
                gi += 1

    # Finalize integer fields
    out_lines = []
    for i, ln in enumerate(lines):
        list_c = ln['list_cents']
        a = round_cents(ln['_amend_dec'])
        pc = round_cents(ln['_plan_covered_dec'])
        p = round_cents(ln['_plan_dec'])
        t = round_cents(ln['_tier_dec'])
        c = credits_per_line[i]
        # Cap credit so it never exceeds post-stage-3 remainder
        remainder_after_apt = list_c - a - p - t
        if c > remainder_after_apt:
            c = remainder_after_apt
        net = list_c - a - p - t - c
        if net < 0:
            c += net
            net = 0
        out_lines.append({
            'id': new_id(),
            'linked_account_id': ln['linked_account_id'],
            'service_family': ln['service_family'],
            'list_cents': list_c,
            'amendment_discount_cents': a,
            'plan_covered_cents': pc,
            'plan_discount_cents': p,
            'tier_discount_cents': t,
            'credit_applied_cents': c,
            'net_due_cents': net,
            '_records': ln['_records'],
        })
    return out_lines, usage, eligible_spend
