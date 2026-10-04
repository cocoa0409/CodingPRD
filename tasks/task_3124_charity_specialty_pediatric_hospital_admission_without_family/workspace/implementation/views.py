"""Entity serializers (views). Datetimes are serialized at 00:00:00Z date granularity."""


def hospital_view(h):
    return dict(h)


def program_view(p):
    return dict(p)


def referral_source_view(r):
    return dict(r)


def application_view(a):
    d = dict(a)
    d.pop("accepted_at", None)
    return d


def review_view(r):
    return dict(r)


def policy_view(p):
    return dict(p)


def billing_account_view(b):
    return dict(b)


def claim_view(c):
    return dict(c)


def care_plan_view(p):
    return dict(p)


def stage_view(s):
    return dict(s)


def grant_view(g):
    return dict(g)


def clinic_view(c):
    return dict(c)


def screening_view(s):
    return dict(s)


def fund_view(f):
    return dict(f)


def allocation_view(a):
    return dict(a)
