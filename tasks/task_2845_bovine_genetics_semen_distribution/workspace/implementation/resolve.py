"""Path and foreign-key resolution (PRD 2.6, evaluation band 3)."""

import store
from errors import fail

LABELS = {
    "facilities": "Facility",
    "country_requirements": "CountryRequirement",
    "sires": "Sire",
    "genomic_evaluations": "GenomicEvaluation",
    "health_tests": "HealthTest",
    "collection_bookings": "CollectionBooking",
    "ejaculates": "Ejaculate",
    "straw_lots": "StrawLot",
    "export_certificates": "ExportCertificate",
    "distributors": "Distributor",
    "tanks": "Tank",
    "consignment_transfers": "ConsignmentTransfer",
    "customer_herds": "CustomerHerd",
    "mating_recommendations": "MatingRecommendation",
}


def need(table, row_id):
    """Resolve a stored row or fail with the single shared 404."""
    rec = store.get(table, row_id)
    if rec is None:
        fail("ERR_RESOURCE_NOT_FOUND", "%s '%s' was not found." % (LABELS[table], row_id))
    return rec


def optional(table, row_id):
    if row_id is None:
        return None
    return need(table, row_id)
