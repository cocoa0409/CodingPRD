from store import STORE


def recompute_org_credit(org):
    total = 0
    for g in STORE.grants.values():
        if g['org_id'] == org['id'] and g['status'] in ('ISSUED', 'DEPLETING'):
            total += g['remaining_cents']
    org['unapplied_credit_cents'] = total


def recompute_accrued_trueup(agreement):
    total = 0
    for t in STORE.trueups.values():
        if t['agreement_id'] == agreement['id'] and t['status'] != 'WAIVED':
            total += t['amount_cents']
    agreement['accrued_trueup_cents'] = total


def recompute_grant_remaining(grant):
    grant['remaining_cents'] = grant['amount_cents'] - grant['consumed_cents'] - grant['forfeited_cents']
