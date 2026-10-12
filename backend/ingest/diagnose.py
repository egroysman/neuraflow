"""Turn a warehouse's raw error into what the person should actually do about it.

The database's own message is always kept; this only adds a plain-language title and a fix.
Matching is on the message text, so an unrecognised error simply gets no hint."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# (pattern, code, title, fix). First match wins, so more specific rules come first.
_RULES: List[Tuple[str, str, str, str]] = [
    # ---- network / allow lists (checked early: they look like generic connection failures)
    (r"ip .{0,40}is not allowed to access|network policy|390422|ip access list|blocked by ip|ip is not allowed",
     "NETWORK_BLOCKED", "Your network rules are blocking NeuraFlow",
     "Add NeuraFlow's outbound IP address to the allowed list (Snowflake: network policy; Databricks: IP access list). The setup guide shows the exact statement."),
    # ---- sign-in
    (r"incorrect username or password|250001.*(incorrect|invalid)|390100|invalid_?credentials|authentication failed",
     "BAD_CREDENTIALS", "The user name or password was not accepted",
     "Check the user name and password (they are case sensitive). If the account requires a key or MFA, use a key-pair service user instead of a password."),
    (r"jwt token is invalid|private key|key pair|public key",
     "BAD_KEY", "The private key was not accepted",
     "Check that the public key was added to the user (ALTER USER … SET RSA_PUBLIC_KEY) and that the private key pasted here is the matching one, in PEM format."),
    (r"multi-?factor|mfa|390190|duo",
     "MFA_REQUIRED", "This user is asked for multi-factor sign-in",
     "A service connection can't answer an MFA prompt. Create a service user that signs in with a key pair instead of a password."),
    (r"invalid (access )?token|401|unauthorized|token is (expired|invalid)|invalid_token",
     "BAD_TOKEN", "The access token was not accepted",
     "The token may be wrong, expired or revoked. Create a new one and paste it here."),
    # ---- permissions / objects
    (r"role .{0,80}(does not exist|not authorized)|390189|requested role",
     "BAD_ROLE", "That role isn't available to this user",
     "Check the role name, and that it was granted to the user (GRANT ROLE … TO USER …)."),
    (r"no active warehouse|warehouse .{0,80}(does not exist|not authorized|suspended)|000606|90106",
     "NO_WAREHOUSE", "No usable warehouse",
     "Name a warehouse in this connection and make sure the role has USAGE on it. Enable auto-resume so it starts when NeuraFlow connects."),
    (r"(database|schema|catalog) .{0,80}(does not exist|not found|not authorized)|schema_not_found|catalog_not_found|003001|002043",
     "BAD_LOCATION", "That database, catalog or schema can't be seen",
     "Check the spelling and that the role or token has USAGE on it. Names are case sensitive in some warehouses."),
    (r"table_or_view_not_found|object .{0,100}does not exist or not authorized|002003|insufficient privileges|permission_denied|does not have (select|use)|403|forbidden|not authorized",
     "NO_ACCESS", "This account isn't allowed to read that",
     "Grant read access: USAGE on the database/catalog and schema, and SELECT on the tables or views. The setup guide has the exact grants."),
    # ---- warehouse state
    (r"temporarily_unavailable|is starting|not running|cluster .{0,40}(terminated|pending)|warehouse .{0,40}(stopped|starting)",
     "WAREHOUSE_STARTING", "The SQL warehouse is starting up",
     "Wait a minute and test again. Turn on auto-start for the warehouse so it wakes when NeuraFlow connects."),
    # ---- addressing
    (r"invalid.{0,20}http.?path|404|warehouses?/.{0,40}not found|endpoint .{0,40}not found",
     "BAD_HTTP_PATH", "The HTTP path doesn't match a SQL warehouse",
     "Open the SQL warehouse in Databricks, then Connection details, and copy the HTTP path (it looks like /sql/1.0/warehouses/…)."),
    (r"could not connect|failed to connect|name or service not known|getaddrinfo|nodename nor servname|max retries exceeded|connection (refused|reset|timed out)|timed out|nxdomain",
     "UNREACHABLE", "Couldn't reach the server",
     "Check the account or server hostname for typos. Snowflake accounts look like orgname-accountname or xy12345.us-east-1, without https:// or .snowflakecomputing.com. If it is right, a firewall may be blocking NeuraFlow."),
]


def diagnose(message: str) -> Optional[Dict[str, str]]:
    m = (message or "").lower()
    for pat, code, title, fix in _RULES:
        if re.search(pat, m):
            return {"code": code, "title": title, "fix": fix}
    return None
