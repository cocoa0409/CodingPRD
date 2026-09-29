"""Tier 4 path existence and tier 7 body reference lookups, plus collection views."""
import db
from errors import ApiError


def _get(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_issuer(row_id):
    return _get(db.db.issuers, row_id, "ERR_ISSUER_NOT_FOUND")


def get_firm(row_id):
    return _get(db.db.firms, row_id, "ERR_FIRM_NOT_FOUND")


def get_deal(row_id):
    return _get(db.db.deals, row_id, "ERR_DEAL_NOT_FOUND")


def get_tranche(row_id):
    return _get(db.db.tranches, row_id, "ERR_TRANCHE_NOT_FOUND")


def get_enhancement(row_id):
    return _get(db.db.enhancements, row_id, "ERR_ENHANCEMENT_NOT_FOUND")


def get_statement(row_id):
    return _get(db.db.statements, row_id, "ERR_OFFICIAL_STATEMENT_NOT_FOUND")


def get_section(row_id):
    return _get(db.db.sections, row_id, "ERR_SECTION_NOT_FOUND")


def get_undertaking(row_id):
    return _get(db.db.undertakings, row_id, "ERR_UNDERTAKING_NOT_FOUND")


def get_engagement(row_id):
    return _get(db.db.engagements, row_id, "ERR_RATING_ENGAGEMENT_NOT_FOUND")


def get_presentation(row_id):
    return _get(db.db.presentations, row_id, "ERR_PRESENTATION_NOT_FOUND")


def get_period(row_id):
    return _get(db.db.periods, row_id, "ERR_ORDER_PERIOD_NOT_FOUND")


def get_order(row_id):
    return _get(db.db.orders, row_id, "ERR_ORDER_NOT_FOUND")


def get_document(row_id):
    return _get(db.db.documents, row_id, "ERR_CLOSING_DOCUMENT_NOT_FOUND")


# --- collection views ------------------------------------------------------

def _children(table, field, value):
    return [row for row in table.values() if row[field] == value]


def tranches_of_deal(deal_id):
    rows = _children(db.db.tranches, "deal_id", deal_id)
    return sorted(rows, key=lambda row: row["sequence_number"])


def members_of_deal(deal_id):
    rows = _children(db.db.members, "deal_id", deal_id)
    return sorted(rows, key=lambda row: row["priority_rank"])


def active_members_of_deal(deal_id):
    return [row for row in members_of_deal(deal_id) if row["status"] == "ACTIVE"]


def enhancements_of_deal(deal_id):
    return _children(db.db.enhancements, "deal_id", deal_id)


def statements_of_deal(deal_id):
    return _children(db.db.statements, "deal_id", deal_id)


def sections_of_statement(statement_id):
    return _children(db.db.sections, "official_statement_id", statement_id)


def undertakings_of_deal(deal_id):
    return _children(db.db.undertakings, "deal_id", deal_id)


def engagements_of_deal(deal_id):
    return _children(db.db.engagements, "deal_id", deal_id)


def presentations_of_engagement(engagement_id):
    return _children(db.db.presentations, "rating_engagement_id", engagement_id)


def presentations_of_deal(deal_id):
    result = []
    for engagement in engagements_of_deal(deal_id):
        result.extend(presentations_of_engagement(engagement["id"]))
    return result


def periods_of_deal(deal_id):
    return _children(db.db.periods, "deal_id", deal_id)


def orders_of_period(period_id):
    return _children(db.db.orders, "order_period_id", period_id)


def orders_of_deal(deal_id):
    result = []
    for period in periods_of_deal(deal_id):
        result.extend(orders_of_period(period["id"]))
    return result


def orders_of_tranche(tranche_id):
    return _children(db.db.orders, "maturity_tranche_id", tranche_id)


def documents_of_deal(deal_id):
    return _children(db.db.documents, "deal_id", deal_id)


def deal_of_statement(statement):
    return db.db.deals[statement["deal_id"]]


def deal_of_section(section):
    statement = db.db.statements[section["official_statement_id"]]
    return db.db.deals[statement["deal_id"]]


def deal_of_engagement(engagement):
    return db.db.deals[engagement["deal_id"]]


def deal_of_presentation(presentation):
    engagement = db.db.engagements[presentation["rating_engagement_id"]]
    return db.db.deals[engagement["deal_id"]]


def deal_of_period(period):
    return db.db.deals[period["deal_id"]]


def deal_of_order(order):
    period = db.db.periods[order["order_period_id"]]
    return db.db.deals[period["deal_id"]]


def deal_of_enhancement(enhancement):
    return db.db.deals[enhancement["deal_id"]]


def deal_of_undertaking(undertaking):
    return db.db.deals[undertaking["deal_id"]]
