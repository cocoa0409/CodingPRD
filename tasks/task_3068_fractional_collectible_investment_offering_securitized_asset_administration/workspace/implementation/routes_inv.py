"""Route registrations: investors and subscriptions."""
from flask import request

from router import ROUTES, read_limit_offset
from envelope import ok, paginated
import views
import svc_investor as svcInv


def _paged(kind, rows):
    limit, offset = read_limit_offset()
    return paginated([views.view(kind, r) for r in rows], limit, offset)


def investors_create():
    data, status = svcInv.register_investor()
    return ok(data, status)


def investors_get(id):
    from flask import g
    return ok(svcInv.get_investor(id, _actor()))


def investors_list():
    from flask import g
    return _paged("investors", svcInv.list_investors(request.args, _actor()))


def revoke(id):
    return ok(svcInv.revoke_suitability(id))


def subs_create():
    from flask import g
    data, status = svcInv.submit_subscription(_actor())
    return ok(data, status)


def subs_get(id):
    return ok(svcInv.get_subscription(id, _actor()))


def subs_list():
    return _paged("subscriptions", svcInv.list_subscriptions(request.args, _actor()))


def subs_screen(id):
    return ok(svcInv.screen_subscription(id))


def subs_collect(id):
    return ok(svcInv.collect_funds(id))


def subs_withdraw(id):
    return ok(svcInv.withdraw_subscription(id, _actor()))


def _actor():
    from types import SimpleNamespace
    from flask import g
    return SimpleNamespace(user_id=getattr(g, "user_id", None),
                           role=getattr(g, "user_role", None))


ROUTES.update({
    "/api/investors": {
        "POST": (["Anonymous"], investors_create),
        "GET": (["ComplianceOfficer", "IssuerOps", "PlatformAdmin"], investors_list),
    },
    "/api/investors/{id}": {
        "GET": (["Investor", "ComplianceOfficer", "IssuerOps", "PlatformAdmin"],
                investors_get),
    },
    "/api/investors/{id}/revoke-suitability": {
        "POST": (["ComplianceOfficer"], revoke),
    },
    "/api/subscriptions": {
        "POST": (["Investor"], subs_create),
        "GET": (["Investor", "IssuerOps", "ComplianceOfficer", "PlatformAdmin"],
                subs_list),
    },
    "/api/subscriptions/{id}": {
        "GET": (["Investor", "IssuerOps", "ComplianceOfficer", "PlatformAdmin"], subs_get),
    },
    "/api/subscriptions/{id}/screen": {
        "POST": (["ComplianceOfficer"], subs_screen),
    },
    "/api/subscriptions/{id}/collect": {
        "POST": (["IssuerOps"], subs_collect),
    },
    "/api/subscriptions/{id}/withdraw": {
        "POST": (["Investor"], subs_withdraw),
    },
})