from store import STORE, CLOCK


def candidate_grants(org_id):
    """Grants in ISSUED/DEPLETING with expires_at > clock, ordered expires_at ASC, created_at ASC."""
    now = CLOCK.now()
    pool = []
    for g in STORE.grants.values():
        if g['org_id'] != org_id:
            continue
        if g['status'] not in ('ISSUED', 'DEPLETING'):
            continue
        if g['expires_at'] <= now:
            continue
        pool.append(g)
    pool.sort(key=lambda g: (g['expires_at'], g['created_at'], g['id']))
    return pool


def allocate(pool, amount):
    """Walk pool, each grant debited min(remaining, outstanding). Returns list of (grant, debit)."""
    debits = []
    outstanding = amount
    for g in pool:
        if outstanding <= 0:
            break
        take = min(g['remaining_cents'], outstanding)
        if take > 0:
            debits.append((g, take))
            outstanding -= take
    return debits
