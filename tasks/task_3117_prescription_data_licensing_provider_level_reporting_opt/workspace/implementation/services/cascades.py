"""Cascade side-effect implementations per SCAFFOLD section 1.2 and PRD section 2.9."""

from db import db
from services.calculations import recall_delivery
from services.common import touch


def suspend_agreement_cascade(agreement):
    """Three-link cascade fired on agreement ACTIVE -> SUSPENDED and ACTIVE -> TERMINATED."""
    # Link 1: quarantine VALIDATED / DEIDENTIFIED batches of this agreement.
    quarantined = []
    for batch in db.batches.values():
        if batch["agreement_id"] == agreement["id"] and batch["status"] in (
            "VALIDATED",
            "DEIDENTIFIED",
        ):
            batch["status"] = "QUARANTINED"
            batch["deidentification_profile_id"] = None
            touch(batch)
            quarantined.append(batch)
    # Link 2: each quarantined batch marks matching CURRENT cells PENDING_RESTATEMENT.
    pending_cells = []
    for batch in quarantined:
        for cell in db.projection_cells.values():
            if (
                cell["status"] == "CURRENT"
                and cell["period_code"] == batch["period_code"]
                and agreement["supplier_id"] in cell["supplier_ids"]
            ):
                cell["status"] = "PENDING_RESTATEMENT"
                touch(cell)
                pending_cells.append(cell)
    # Link 3: each marked cell recalls COMPILED / RELEASED deliveries containing it.
    for cell in pending_cells:
        recall_deliveries_for_cell(cell)


def resume_agreement_cascade(agreement):
    """QUARANTINED batches of the agreement return to VALIDATED."""
    for batch in db.batches.values():
        if batch["agreement_id"] == agreement["id"] and batch["status"] == "QUARANTINED":
            batch["status"] = "VALIDATED"
            touch(batch)


def recall_deliveries_for_cell(cell):
    """Recall every COMPILED/RELEASED delivery whose compiled_cell_ids contains the cell."""
    for delivery in list(db.deliveries.values()):
        if delivery["status"] in ("COMPILED", "RELEASED") and cell["id"] in delivery[
            "compiled_cell_ids"
        ]:
            recall_delivery(delivery)


def suspend_client_cascade(client):
    """Client ACTIVE -> SUSPENDED: every ACTIVE product of the client -> SUSPENDED."""
    client["status"] = "SUSPENDED"
    touch(client)
    for product in db.products.values():
        if product["client_id"] == client["id"] and product["status"] == "ACTIVE":
            product["status"] = "SUSPENDED"
            touch(product)


def reinstate_client_cascade(client):
    """Client SUSPENDED -> ACTIVE: every SUSPENDED product of the client -> ACTIVE."""
    client["status"] = "ACTIVE"
    touch(client)
    for product in db.products.values():
        if product["client_id"] == client["id"] and product["status"] == "SUSPENDED":
            product["status"] = "ACTIVE"
            touch(product)
