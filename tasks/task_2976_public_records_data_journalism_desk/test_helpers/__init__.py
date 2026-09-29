"""Test infrastructure for the Public Records Data Journalism Desk API.

Submodules:

* :mod:`constants` -- paths, roles, enum members and calculation constants.
* :mod:`api_errors` -- error identifiers, the PRD S5 HTTP status map, and the
  import-time registration of that map with the framework validators.
* :mod:`types` -- TypedDict shapes for every persisted resource.
* :mod:`api_client` -- one method per endpoint, plus instant canonicalisation.
* :mod:`assertions` -- envelope helpers and the PRD's named invariants.
* :mod:`factories` -- request-payload builders with PRD-correct JSON types.
* :mod:`test_users` -- caller identities and their header builders.
* :mod:`fixtures` -- composite setup chains built only from PRD S4 endpoints.
"""
