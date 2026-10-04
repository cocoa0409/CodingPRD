"""Route registrations: custody records, policies, decisions, transfer orders,
platform accounts and the test-driving clock."""
from flask import request

from router import ROUTES, read_limit_offset
from envelope import ok, paginated
import views
import svc_custody as svcCus
import svc_sale as svcSale
import svc_transfer as svcTr


def _paged(kind, rows):
    limit, offset = read_limit_offset()
    return paginated([views.view(kind, r) for r in rows], limit, offset)


def custody_get(id):
    return ok(svcCus.get_custody_record(id))


def custody_receive(id):
    return ok(svcCus.receive_custody(id))


def custody_release(id):
    return ok(svcCus.release_custody(id))


def policy_get(id):
    return ok(svcCus.get_policy(id))


def policy_bind(id):
    return ok(svcCus.bind_policy(id))


def policy_lapse(id):
    return ok(svcCus.lapse_policy(id))


def decision_get(id):
    return ok(svcSale.get_decision(id))


def decision_approve(id):
    return ok(svcSale.approve_decision(id))


def decision_reject(id):
    return ok(svcSale.reject_decision(id))


def decision_revise(id):
    return ok(svcSale.revise_decision(id))


def execute(id):
    return ok(svcSale.execute_sale(id))


def _actor():
    from types import SimpleNamespace
    from flask import g
    return SimpleNamespace(user_id=getattr(g, "user_id", None),
                           role=getattr(g, "user_role", None))


def transfer_create():
    data, status = svcTr.post_transfer_order(_actor())
    return ok(data, status)


def transfer_list():
    return _paged("transfer_orders", svcTr.list_transfer_orders(request.args, _actor()))


def transfer_get(id):
    return ok(svcTr.get_transfer_order(id))


def transfer_accept(id):
    return ok(svcTr.accept_transfer(id, _actor()))


def transfer_repost(id):
    return ok(svcTr.repost_transfer(id, _actor()))


def transfer_approve(id):
    return ok(svcTr.approve_transfer(id))


def transfer_cancel(id):
    return ok(svcTr.cancel_transfer(id, _actor()))


def account_create():
    data, status = svcSale.open_platform_account()
    return ok(data, status)


def account_get(id):
    return ok(svcSale.get_platform_account(id))


def clock_set():
    return ok(svcSale.set_clock())


ANY_TRANSFER = ["Investor", "IssuerOps", "ComplianceOfficer", "TransferAgent",
                "PlatformAdmin"]
DECIDER = ["IssuerOps", "ComplianceOfficer", "PlatformAdmin"]

ROUTES.update({
    "/api/custody-records/{id}": {"GET": (DECIDER, custody_get)},
    "/api/custody-records/{id}/receive": {"POST": (["IssuerOps"], custody_receive)},
    "/api/custody-records/{id}/release": {"POST": (["IssuerOps"], custody_release)},
    "/api/insurance-policies/{id}": {"GET": (DECIDER, policy_get)},
    "/api/insurance-policies/{id}/bind": {"POST": (["IssuerOps"], policy_bind)},
    "/api/insurance-policies/{id}/lapse": {"POST": (["IssuerOps"], policy_lapse)},
    "/api/holding-decisions/{id}": {"GET": (DECIDER, decision_get)},
    "/api/holding-decisions/{id}/approve": {"PATCH": (["IssuerOps"], decision_approve)},
    "/api/holding-decisions/{id}/reject": {
        "PATCH": (["ComplianceOfficer"], decision_reject)},
    "/api/holding-decisions/{id}/revise": {"PATCH": (["IssuerOps"], decision_revise)},
    "/api/holdings/{id}/execute": {"POST": (["IssuerOps"], execute)},
    "/api/transfer-orders": {
        "POST": (["Investor"], transfer_create),
        "GET": (ANY_TRANSFER, transfer_list)},
    "/api/transfer-orders/{id}": {"GET": (ANY_TRANSFER, transfer_get)},
    "/api/transfer-orders/{id}/accept": {"POST": (["Investor"], transfer_accept)},
    "/api/transfer-orders/{id}/repost": {
        "POST": (["Investor", "IssuerOps"], transfer_repost)},
    "/api/transfer-orders/{id}/approve-transfer": {
        "POST": (["TransferAgent"], transfer_approve)},
    "/api/transfer-orders/{id}/cancel": {
        "POST": (["Investor", "IssuerOps"], transfer_cancel)},
    "/api/platform-accounts": {"POST": (["PlatformAdmin"], account_create)},
    "/api/platform-accounts/{id}": {"GET": (["PlatformAdmin"], account_get)},
    "/api/_clock/set_current_utc": {"POST": (["PlatformAdmin"], clock_set)},
})