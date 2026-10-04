"""Route registrations: offerings and all of their sub-resources."""
from flask import request

from router import ROUTES, read_limit_offset
from envelope import ok, paginated
import views
import svc_offering as svcOff
import svc_custody as svcCus
import svc_report as svcRep
import svc_sale as svcSale


def _paged(kind, rows):
    limit, offset = read_limit_offset()
    return paginated([views.view(kind, r) for r in rows], limit, offset)


def artwork_offerings_create(id):
    data, status = svcOff.create_offering(id)
    return ok(data, status)


def offerings_get(id):
    return ok(svcOff.get_offering(id))


def offerings_list():
    return _paged("offerings", svcOff.list_offerings(request.args))


def qualification(id):
    return ok(svcOff.qualification_filing(id))


def allocate(id):
    return ok(svcOff.allocate(id))


def promotion(id):
    return ok(svcOff.waitlist_promotion(id))


def demotion(id):
    return ok(svcOff.waitlist_demotion(id))


def withdraw(id):
    return ok(svcOff.withdraw_offering(id))


def abandon(id):
    return ok(svcOff.abandon_offering(id))


def share_ledger(id):
    return ok(svcOff.share_ledger(id))


def valuation(id):
    return ok(svcOff.valuation(id))


def cost_lots_create(id):
    data, status = svcCus.create_lot(id)
    return ok(data, status)


def cost_lots_list(id):
    return _paged("lots", svcCus.list_lots(id, request.args))


def accrue(id):
    data, status = svcSale.accrue_fees(id)
    return ok(data, status)


def accruals_list(id):
    return _paged("fee_accruals", svcSale.list_accruals(id, request.args))


def reports_create(id):
    data, status = svcRep.file_report(id)
    return ok(data, status)


def reports_list(id):
    return _paged("offering_reports", svcRep.list_reports(id, request.args))


def reconcile(id):
    return ok(svcSale.reconcile_cadence(id))


def insurer_quote(id):
    data, status = svcCus.insurer_quote(id)
    return ok(data, status)


def offering_subs(id):
    return _paged("subscriptions",
                  svcOff.list_subscriptions_of_offering(id, request.args))


def decisions_create(id):
    data, status = svcSale.raise_decision(id)
    return ok(data, status)


def decisions_list(id):
    return _paged("holding_decisions", svcSale.list_decisions(id, request.args))


def custody_of_offering(id):
    return _paged("custody_records", svcCus.list_custody_records(id, request.args))


def custody_create(id):
    data, status = svcCus.open_custody_record(id)
    return ok(data, status)


def policies_of_offering(id):
    return _paged("insurance_policies", svcCus.list_policies(id, request.args))


def policy_create(id):
    data, status = svcCus.create_policy(id)
    return ok(data, status)


def distributions_list(id):
    return _paged("distributions", svcSale.list_distributions(id, request.args))


def distribution_pay(id, distributionId):
    return ok(svcSale.pay_distribution(id, distributionId))


ISSUER_READ = ["IssuerOps", "ComplianceOfficer", "PlatformAdmin"]
ANY_READ = ["IssuerOps", "ComplianceOfficer", "TransferAgent", "PlatformAdmin"]

ROUTES.update({
    "/api/artworks/{id}/offerings": {"POST": (["IssuerOps"], artwork_offerings_create)},
    "/api/offerings": {"GET": (ANY_READ, offerings_list)},
    "/api/offerings/{id}": {"GET": (ANY_READ, offerings_get)},
    "/api/offerings/{id}/qualification-filing": {
        "POST": (["ComplianceOfficer"], qualification)},
    "/api/offerings/{id}/allocate": {"POST": (["ComplianceOfficer"], allocate)},
    "/api/offerings/{id}/waitlist-promotion": {
        "POST": (["ComplianceOfficer"], promotion)},
    "/api/offerings/{id}/waitlist-demotion": {
        "POST": (["ComplianceOfficer"], demotion)},
    "/api/offerings/{id}/withdraw": {"POST": (["ComplianceOfficer"], withdraw)},
    "/api/offerings/{id}/abandon": {"POST": (["ComplianceOfficer"], abandon)},
    "/api/offerings/{id}/share-ledger": {
        "GET": (["Investor", "IssuerOps", "ComplianceOfficer", "TransferAgent",
                 "PlatformAdmin"], share_ledger)},
    "/api/offerings/{id}/valuation": {
        "GET": (["Investor", "IssuerOps", "ComplianceOfficer", "TransferAgent"],
                valuation)},
    "/api/offerings/{id}/cost-lots": {
        "POST": (["IssuerOps"], cost_lots_create),
        "GET": (ISSUER_READ, cost_lots_list)},
    "/api/offerings/{id}/accrue-fees": {"POST": (["IssuerOps"], accrue)},
    "/api/offerings/{id}/fee-accruals": {"GET": (ISSUER_READ, accruals_list)},
    "/api/offerings/{id}/reports": {
        "POST": (["IssuerOps", "ComplianceOfficer"], reports_create),
        "GET": (["Investor", "IssuerOps", "ComplianceOfficer", "PlatformAdmin"],
                reports_list)},
    "/api/offerings/{id}/reconcile-cadence": {
        "POST": (["IssuerOps", "PlatformAdmin"], reconcile)},
    "/api/offerings/{id}/insurer-quote": {"POST": (["IssuerOps"], insurer_quote)},
    "/api/offerings/{id}/subscriptions": {"GET": (ISSUER_READ, offering_subs)},
    "/api/offerings/{id}/holding-decisions": {
        "POST": (["IssuerOps"], decisions_create),
        "GET": (ISSUER_READ, decisions_list)},
    "/api/offerings/{id}/custody-records": {
        "POST": (["IssuerOps"], custody_create),
        "GET": (ISSUER_READ, custody_of_offering)},
    "/api/offerings/{id}/insurance-policies": {
        "POST": (["IssuerOps"], policy_create),
        "GET": (ISSUER_READ, policies_of_offering)},
    "/api/offerings/{id}/distributions": {
        "GET": (["Investor", "IssuerOps", "ComplianceOfficer", "PlatformAdmin"],
                distributions_list)},
    "/api/offerings/{id}/distributions/{distributionId}/pay": {
        "POST": (["IssuerOps"], distribution_pay)},
})