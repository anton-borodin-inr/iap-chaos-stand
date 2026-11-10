"""Backend module: players, game actions, catalog and receipt validation.

It shares no code, tables or database file with the store module. The only
contract between them is the signing secret and the wire formats of the
player token and the receipt (spec/openapi.yaml).
"""
