"""Route blueprints, one module per resource group."""
from . import accounts, actions, connections, folders, integrations, versions, workflows

ALL_BLUEPRINTS = (
    accounts.bp,
    folders.bp,
    workflows.bp,
    versions.bp,
    integrations.bp,
    connections.bp,
    actions.bp,
)