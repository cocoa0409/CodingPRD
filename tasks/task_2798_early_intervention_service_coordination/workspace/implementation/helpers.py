"""Existence lookups, serializers and shared temporal guards."""
import domain as D
from errors import fail
from store import clock_date, db, pd, public

SERIALIZE_FIELDS = {
    "child": D.CHILD_FIELDS,
    "coordinator": D.COORDINATOR_FIELDS,
    "referral": D.REFERRAL_FIELDS,
    "assessment": D.ASSESSMENT_FIELDS,
    "ifsp": D.IFSP_FIELDS,
    "ifsp_service": D.IFSP_SERVICE_FIELDS,
    "provider": D.PROVIDER_FIELDS,
    "authorization": D.AUTHORIZATION_FIELDS,
    "visit": D.VISIT_FIELDS,
    "cost_share": D.COST_SHARE_FIELDS,
    "contact_log": D.CONTACT_LOG_FIELDS,
    "transition_plan": D.TRANSITION_PLAN_FIELDS,
}


def make_serializer(kind):
    fields = SERIALIZE_FIELDS[kind]

    def serialize(row):
        return public(row, fields)
    return serialize


ser_child = make_serializer("child")
ser_coordinator = make_serializer("coordinator")
ser_referral = make_serializer("referral")
ser_assessment = make_serializer("assessment")
ser_ifsp = make_serializer("ifsp")
ser_line = make_serializer("ifsp_service")
ser_provider = make_serializer("provider")
ser_authorization = make_serializer("authorization")
ser_visit = make_serializer("visit")
ser_cost_share = make_serializer("cost_share")
ser_contact_log = make_serializer("contact_log")
ser_transition_plan = make_serializer("transition_plan")


def _get(collection, key, error_id, label):
    row = collection.get(key)
    if row is None:
        fail(error_id, "%s '%s' does not exist." % (label, key))
    return row


def get_child(child_id):
    return _get(db.children, child_id, "ERR_CHILD_NOT_FOUND", "Child")


def get_referral(referral_id):
    return _get(db.referrals, referral_id, "ERR_REFERRAL_NOT_FOUND", "Referral")


def get_coordinator(coordinator_id):
    return _get(db.coordinators, coordinator_id, "ERR_COORDINATOR_NOT_FOUND",
                "Service coordinator")


def get_assessment(assessment_id):
    return _get(db.assessments, assessment_id, "ERR_ASSESSMENT_NOT_FOUND",
                "Assessment")


def get_ifsp(ifsp_id):
    return _get(db.ifsps, ifsp_id, "ERR_IFSP_NOT_FOUND", "IFSP")


def get_line(service_id):
    return _get(db.ifsp_services, service_id, "ERR_IFSP_SERVICE_NOT_FOUND",
                "IFSP service line")


def get_provider(provider_id):
    return _get(db.providers, provider_id, "ERR_PROVIDER_NOT_FOUND", "Provider")


def get_authorization(authorization_id):
    return _get(db.authorizations, authorization_id,
                "ERR_AUTHORIZATION_NOT_FOUND", "Provider authorization")


def get_visit(visit_id):
    return _get(db.visits, visit_id, "ERR_VISIT_NOT_FOUND", "Service visit")


def get_cost_share(cost_share_id):
    return _get(db.cost_shares, cost_share_id, "ERR_COST_SHARE_NOT_FOUND",
                "Cost share determination")


def get_contact_log(contact_log_id):
    return _get(db.contact_logs, contact_log_id, "ERR_CONTACT_LOG_NOT_FOUND",
                "Contact log")


def get_transition_plan(plan_id):
    return _get(db.transition_plans, plan_id, "ERR_TRANSITION_PLAN_NOT_FOUND",
                "Transition plan")


# ------------------------------------------------------------ temporal guards

def not_future(value, label):
    if value is None:
        return
    parsed = pd(value)
    if parsed is not None and parsed > clock_date():
        fail("ERR_DATE_IN_FUTURE",
             "%s must not be later than the current logical date." % label)


def ordered_dates(earlier, later, message):
    if earlier is None or later is None:
        return
    if pd(later) < pd(earlier):
        fail("ERR_INVALID_DATE_RANGE", message)
