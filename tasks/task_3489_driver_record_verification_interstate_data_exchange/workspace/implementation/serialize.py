"""Entity serialization: strips internal bookkeeping fields and derives the
read-time disqualification status."""
import state


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def jurisdiction(j):
    return _public(j)


def participation(p):
    return _public(p)


def certification(c):
    return _public(c)


def driver(d):
    return _public(d)


def record(r):
    return _public(r)


def conviction(c):
    return _public(c)


def disqualification(d):
    out = _public(d)
    out["status"] = state.dq_derived_status(d)
    return out


def license(lic):
    return _public(lic)


def license_transfer(t):
    return _public(t)


def vehicle_title(t):
    return _public(t)


def title_transfer(t):
    return _public(t)


def fee_invoice(inv):
    return _public(inv)
