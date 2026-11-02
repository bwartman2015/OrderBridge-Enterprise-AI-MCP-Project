"""Business rules, shared by every channel.

The REST API, the EDI processor, the MCP server and the approval CLI all call
these functions, so a rule (e.g. "no duplicate POs") lives in exactly one place.
Service functions never commit; the caller owns the transaction.
"""
