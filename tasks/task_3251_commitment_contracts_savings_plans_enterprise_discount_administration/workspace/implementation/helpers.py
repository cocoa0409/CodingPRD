from store import STORE, CLOCK, ApiError, new_id, iso_fmt


def get_org(oid):
    org = STORE.orgs.get(oid)
    if org is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'billing org not found: ' + str(oid))
    return org


def get_account(aid):
    a = STORE.linked_accounts.get(aid)
    if a is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'linked account not found: ' + str(aid))
    return a


def get_agreement(aid):
    a = STORE.agreements.get(aid)
    if a is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'agreement not found: ' + str(aid))
    return a


def get_tier(tid):
    t = STORE.tiers.get(tid)
    if t is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'discount tier not found: ' + str(tid))
    return t


def get_amendment(aid):
    a = STORE.amendments.get(aid)
    if a is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'pricing amendment not found: ' + str(aid))
    return a


def get_plan(pid):
    p = STORE.plans.get(pid)
    if p is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'commitment plan not found: ' + str(pid))
    return p


def get_usage(uid):
    u = STORE.usage.get(uid)
    if u is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'usage record not found: ' + str(uid))
    return u


def get_grant(gid):
    g = STORE.grants.get(gid)
    if g is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'credit grant not found: ' + str(gid))
    return g


def get_invoice(iid):
    inv = STORE.invoices.get(iid)
    if inv is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'invoice not found: ' + str(iid))
    return inv


def get_line(lid):
    ln = STORE.lines.get(lid)
    if ln is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'invoice line not found: ' + str(lid))
    return ln


def get_trueup(tid):
    t = STORE.trueups.get(tid)
    if t is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'true-up charge not found: ' + str(tid))
    return t


def get_forecast(fid):
    f = STORE.forecasts.get(fid)
    if f is None:
        raise ApiError('ERR_NOT_FOUND', 404, 'renewal forecast not found: ' + str(fid))
    return f


_created_seq = [0]


def make_resource(with_version=True):
    # The logical clock is fixed between explicit sets, so resources created in
    # the same logical instant share a millisecond created_at. PRD rules order
    # by created_at ascending (ties by creation order), so append a monotonic
    # sequence suffix that keeps string ordering aligned with creation order.
    _created_seq[0] += 1
    now = iso_fmt(CLOCK.now()) + f'#{_created_seq[0]:09d}'
    r = {'id': new_id(), 'created_at': now}
    if with_version:
        r['updated_at'] = now
        r['version'] = 1
    return r


def touch(resource):
    resource['updated_at'] = iso_fmt(CLOCK.now())
    resource['version'] = int(resource.get('version', 1)) + 1


def serialize(d):
    """Serialize a resource dict, converting any datetime values to ISO strings."""
    out = {}
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            out[k] = iso_fmt(v)
        else:
            out[k] = v
    return out
