import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from store import db, get_clock, format_dt
from resp import err

REFRESH_URGENCY_MONTHS_CAP = 60
BEST_BUY_MIN = Decimal('75')
RECOMMENDED_MIN = Decimal('80')
STANDARD_MIN = Decimal('50')
BEST_BUY_PRICE_CAP_CENTS = 20000
GRACE_DAYS = 14


def round2(d):
    return float(Decimal(d).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def round0(d):
    return int(Decimal(d).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def bump(res):
    res['version'] += 1
    res['updated_at'] = format_dt(get_clock())


def new_common(res):
    res['created_at'] = format_dt(get_clock())
    res['updated_at'] = format_dt(get_clock())
    res['version'] = 1
    return res


def compute_selection_score(cat):
    """§3.1 selection score using the logical clock."""
    clock = get_clock()
    lpa = cat.get('last_published_at')
    if lpa is None:
        months_since = REFRESH_URGENCY_MONTHS_CAP
    else:
        from store import parse_dt
        ldt = parse_dt(lpa)
        days = (clock - ldt).days
        months_since = min(REFRESH_URGENCY_MONTHS_CAP, math.floor(days / 30))
    urgency_raw = Decimal(100) * Decimal(months_since) / Decimal(cat['refresh_cycle_months'])
    urgency = min(Decimal('100'), Decimal(urgency_raw).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    score = (Decimal('0.40') * Decimal(str(cat['market_share_pct']))
             + Decimal('0.35') * Decimal(str(cat['member_interest_pct']))
             + Decimal('0.25') * urgency)
    return float(score.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def recompute_category_last_published(cat):
    """Recompute last_published_at from remaining PUBLISHED non-WITHDRAWN pubs of the category."""
    pubs = [p for p in db['rating_publications'].values()
            if p['status'] == 'PUBLISHED'
            and db['test_programs'][p['program_id']]['category_id'] == cat['id']]
    if not pubs:
        cat['last_published_at'] = None
    else:
        from store import parse_dt
        latest = max(pubs, key=lambda p: parse_dt(p['published_at']))
        cat['last_published_at'] = latest['published_at']


def programs_of_category(cat_id):
    return [p for p in db['test_programs'].values() if p['category_id'] == cat_id]


def pos_of_program(program_id):
    return [p for p in db['purchase_orders'].values() if p['program_id'] == program_id]


def samples_of_program(program_id):
    return [s for s in db['test_samples'].values() if s['program_id'] == program_id]


def findings_of_program(program_id):
    return [f for f in db['safety_findings'].values() if f['program_id'] == program_id]


def pubs_of_program(program_id):
    return [p for p in db['rating_publications'].values() if p['program_id'] == program_id]


def active_protocol_of_category(cat_id):
    prots = [p for p in db['lab_protocols'].values()
             if p['category_id'] == cat_id and p['status'] == 'ACTIVE']
    return prots[0] if prots else None


def is_manufacturer_direct(retailer_name):
    """manufacturer-direct = ends with '-direct' or equals a brand manufacturer name
    (the model_label of any test sample)."""
    if not isinstance(retailer_name, str):
        return False
    if retailer_name.endswith('-direct'):
        return True
    labels = {s['model_label'] for s in db['test_samples'].values()}
    return retailer_name in labels


def is_manufacturer_name(name):
    labels = {s['model_label'] for s in db['test_samples'].values()}
    return isinstance(name, str) and name in labels


def recompute_sample_sourcing(sample):
    pos = db['purchase_orders'].values()
    total = 0
    for po in pos:
        if po['program_id'] != sample['program_id']:
            continue
        if po['status'] not in ('RECEIVED', 'VERIFIED'):
            continue
        for line in po['lines']:
            if line['sample_id'] == sample['id']:
                total += line['qty']
    sample['sourced_units'] = total
    sample['sourcing_complete'] = total >= sample['required_units']


def recompute_sample_testing(sample):
    program = db['test_programs'][sample['program_id']]
    protocol = active_protocol_of_category(program['category_id'])
    repeat_min = protocol['measurement_repeat_min'] if protocol else 1
    per_unit = {}
    for m in db['measurements'].values():
        if m['sample_id'] == sample['id']:
            per_unit.setdefault(m['unit_index'], 0)
            per_unit[m['unit_index']] += 1
    tested = sum(1 for u in range(1, sample['required_units'] + 1)
                 if per_unit.get(u, 0) >= repeat_min)
    sample['tested_units'] = tested
    sample['testing_complete'] = tested >= sample['required_units']


def compute_lab_score(sample):
    """Two-stage mean: per-metric mean (round2), then mean across metrics (round2)."""
    per_metric = {}
    for m in db['measurements'].values():
        if m['sample_id'] == sample['id']:
            per_metric.setdefault(m['metric_code'], []).append(Decimal(str(m['value_num'])))
    if not per_metric:
        return None
    metric_means = []
    for vals in per_metric.values():
        mean = sum(vals) / Decimal(len(vals))
        metric_means.append(mean.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    overall = sum(metric_means) / Decimal(len(metric_means))
    return float(overall.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def median_price_cents(sample):
    prices = []
    for po in db['purchase_orders'].values():
        if po['program_id'] != sample['program_id']:
            continue
        if po['status'] not in ('RECEIVED', 'VERIFIED'):
            continue
        for line in po['lines']:
            if line['sample_id'] == sample['id']:
                prices.append(line['unit_price_cents'])
    if not prices:
        return None
    prices.sort()
    n = len(prices)
    if n % 2 == 1:
        return prices[n // 2]
    return prices[n // 2 - 1]  # lower of two middle values


def compute_survey_score(sample, wave):
    if wave is None:
        return None
    vals = [Decimal(str(r['reliability_score'])) for r in wave['responses']
            if r['status'] == 'COUNTED' and r['model_label'] == sample['model_label']]
    if not vals:
        return None
    return float((sum(vals) / Decimal(len(vals))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def designation_for(program, sample, overall_score, price_cents):
    """Pinned threshold ladder, safety first."""
    for f in findings_of_program(program['id']):
        if f['sample_id'] == sample['id'] and f['status'] in ('OPEN', 'ESCALATED') and f['escalation_tier'] >= 1:
            return 'NOT_RECOMMENDED'
    o = Decimal(str(overall_score))
    if o >= BEST_BUY_MIN and price_cents is not None and price_cents <= BEST_BUY_PRICE_CAP_CENTS:
        return 'BEST_BUY'
    if o >= RECOMMENDED_MIN:
        return 'RECOMMENDED'
    if o >= STANDARD_MIN:
        return 'STANDARD'
    return 'NOT_RECOMMENDED'


def compute_recalled_model_count(finding):
    sample = db['test_samples'][finding['sample_id']]
    count = 0
    for pub in pubs_of_program(finding['program_id']):
        if pub['status'] == 'WITHDRAWN':
            continue
        for entry in pub['rated_models']:
            es = db['test_samples'][entry['sample_id']]
            if es['model_label'] == sample['model_label'] and entry['designation'] == 'NOT_RECOMMENDED':
                count += 1
    return count


def compute_escalation_tier(finding):
    tier = 0
    if finding['severity'] in ('MAJOR', 'CRITICAL'):
        tier = 1
    if finding['severity'] == 'CRITICAL' and finding.get('recalled_model_count', 0) >= 2:
        tier = 2
    if finding['severity'] == 'CRITICAL' and finding.get('hazard_flag'):
        tier = 3
    return tier
