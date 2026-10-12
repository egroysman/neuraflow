"""Copy-paste setup steps for connecting a warehouse safely: a read-only role, a small warehouse and
the exact grants. Generated from names the person chooses; nothing here is run by NeuraFlow.

These are templates for the customer's own administrator to review and run. They only ever grant
read access (USAGE and SELECT); there is no write, ownership or admin grant anywhere in them."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from .readers import SourceError

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")


def _ident(label: str, value: Any, default: str = "") -> str:
    v = str(value or default).strip()
    if not v:
        raise SourceError(f"Enter the {label}.")
    if not _IDENT.match(v):
        raise SourceError(f"{label.capitalize()} can only use letters, numbers, underscores and $, and must not start with a number.")
    return v


def _schemas(value: Any, default: str) -> List[str]:
    raw = value if isinstance(value, list) else re.split(r"[,\s]+", str(value or ""))
    out = [_ident("schema name", s) for s in raw if str(s).strip()]
    return out or [default]


def egress_ips() -> List[str]:
    """Outbound addresses NeuraFlow connects from, if the operator has a fixed set (NEURAFLOW_EGRESS_IPS)."""
    return [ip.strip() for ip in os.getenv("NEURAFLOW_EGRESS_IPS", "").split(",") if re.fullmatch(r"[0-9a-fA-F:.]{3,45}(/\d{1,3})?", ip.strip())]


def _network_step(kind: str, policy_sql: str) -> Dict[str, Any]:
    ips = egress_ips()
    if ips:
        return {"title": "Allow NeuraFlow through your network rules", "optional": True,
                "text": "Only needed if your account restricts which IP addresses can connect. NeuraFlow connects from: " + ", ".join(ips) + ".",
                "sql": policy_sql.replace("{IPS}", ", ".join(f"'{i}'" for i in ips))}
    return {"title": "Allow NeuraFlow through your network rules", "optional": True,
            "text": "Only needed if your account restricts which IP addresses can connect. Ask your NeuraFlow contact for the address to allow, then add it to your " + ("network policy." if kind == "snowflake" else "workspace IP access list.")}


def snowflake(p: Dict[str, Any]) -> Dict[str, Any]:
    role = _ident("role name", p.get("role"), "NEURAFLOW_READER")
    user = _ident("user name", p.get("user"), "NEURAFLOW_SVC")
    wh = _ident("warehouse name", p.get("warehouse"), "NEURAFLOW_WH")
    db = _ident("database name", p.get("database"))
    schemas = _schemas(p.get("schemas"), "PUBLIC")
    key = (p.get("auth") or "key") == "key"
    create_user = (
        f"CREATE USER IF NOT EXISTS {user}\n  DEFAULT_ROLE = {role}\n  DEFAULT_WAREHOUSE = {wh}\n  TYPE = SERVICE\n  RSA_PUBLIC_KEY = '<paste the public key, without the BEGIN/END lines>';"
        if key else
        f"CREATE USER IF NOT EXISTS {user}\n  DEFAULT_ROLE = {role}\n  DEFAULT_WAREHOUSE = {wh}\n  TYPE = LEGACY_SERVICE\n  PASSWORD = '<choose a long random password>';"
    )
    grants = [f"GRANT USAGE ON DATABASE {db} TO ROLE {role};"]
    for s in schemas:
        grants += [
            f"GRANT USAGE ON SCHEMA {db}.{s} TO ROLE {role};",
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {db}.{s} TO ROLE {role};",
            f"GRANT SELECT ON ALL VIEWS IN SCHEMA {db}.{s} TO ROLE {role};",
            f"GRANT SELECT ON FUTURE TABLES IN SCHEMA {db}.{s} TO ROLE {role};",
            f"GRANT SELECT ON FUTURE VIEWS IN SCHEMA {db}.{s} TO ROLE {role};",
        ]
    steps: List[Dict[str, Any]] = [
        {"title": "Create a read-only role and a small warehouse",
         "text": "Run as a user who can create roles (for example SECURITYADMIN, and SYSADMIN for the warehouse). The warehouse is the smallest size and stops itself when idle, so it costs almost nothing.",
         "sql": f"CREATE ROLE IF NOT EXISTS {role};\nCREATE WAREHOUSE IF NOT EXISTS {wh}\n  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;\nGRANT USAGE ON WAREHOUSE {wh} TO ROLE {role};"},
        {"title": "Create the service user" + (" with a key pair" if key else ""),
         "text": ("Generate a key pair on your own machine (for example: openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out nf_key.p8 -nocrypt, then openssl rsa -in nf_key.p8 -pubout -out nf_key.pub). Paste the public key below and keep the private key; you will paste it into NeuraFlow. "
                 if key else "Use a long random password and keep it in your password manager. If your account requires MFA for password sign-in, use the key-pair option instead. ")
                + "If your Snowflake version doesn't support TYPE for users, remove that line.",
         "sql": create_user + f"\nGRANT ROLE {role} TO USER {user};"},
        {"title": "Give the role read-only access to your data",
         "text": "This is the only access NeuraFlow gets: it can look at and read the schemas below, and cannot change anything. Add or remove schemas to match where your invoices, bills and ledger live.",
         "sql": "\n".join(grants)},
        _network_step("snowflake", f"CREATE NETWORK POLICY NEURAFLOW_ACCESS ALLOWED_IP_LIST = ({{IPS}});\nALTER USER {user} SET NETWORK_POLICY = NEURAFLOW_ACCESS;"),
        {"title": "Check what the role can see",
         "text": "Run this and confirm you only see the access you intended.",
         "sql": f"SHOW GRANTS TO ROLE {role};"},
        {"title": "Find your account identifier",
         "text": "NeuraFlow asks for this in the Account box.",
         "sql": "SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS account_identifier;"},
    ]
    return {"type": "snowflake", "steps": steps, "fill": {"user": user, "warehouse": wh, "database": db, "role": role, **({"schema": schemas[0]} if len(schemas) == 1 else {})},
            "then": "Back in NeuraFlow, choose Save and test. The test also tells you how many tables the role can see."}


def databricks(p: Dict[str, Any]) -> Dict[str, Any]:
    sp = str(p.get("principal") or "").strip()
    if not sp:
        raise SourceError("Enter the service principal's application ID or name.")
    if not re.fullmatch(r"[A-Za-z0-9_.@ -]{1,120}", sp):
        raise SourceError("The service principal can only use letters, numbers, spaces and . _ @ -")
    catalog = _ident("catalog name", p.get("catalog"))
    schemas = _schemas(p.get("schemas"), "default")
    grants = [f"GRANT USE CATALOG ON CATALOG {catalog} TO `{sp}`;"]
    for s in schemas:
        grants += [f"GRANT USE SCHEMA ON SCHEMA {catalog}.{s} TO `{sp}`;", f"GRANT SELECT ON SCHEMA {catalog}.{s} TO `{sp}`;"]
    steps: List[Dict[str, Any]] = [
        {"title": "Create a service principal for NeuraFlow",
         "text": "In your Databricks workspace as an admin: Settings, Identity and access, Service principals, Add service principal. Using a service principal (not a person's account) means access doesn't break when someone leaves."},
        {"title": "Give it read-only access to your data",
         "text": "Run this in a SQL editor as a catalog owner or admin. It allows looking at and reading the schemas below and nothing else. These use Unity Catalog; if you still use legacy table access control, grant SELECT on the tables instead.",
         "sql": "\n".join(grants)},
        {"title": "Let it use a SQL warehouse",
         "text": "Open SQL Warehouses, choose the warehouse to use (a small one is enough), Permissions, and give the service principal Can use. Turn on auto-stop and make sure auto-start is on, so the warehouse wakes when NeuraFlow connects."},
        {"title": "Create an access token for the service principal",
         "text": "NeuraFlow signs in with a token. Create one for the service principal (a workspace admin can do this from the workspace's token settings or the Databricks CLI) and copy it right away; it is only shown once. Give it the shortest lifetime you are comfortable renewing."},
        {"title": "Copy the connection details",
         "text": "Open the SQL warehouse, then Connection details. Copy the Server hostname and the HTTP path into NeuraFlow, and paste the token as the access token."},
        _network_step("databricks", "-- In Databricks: Settings, Security, IP access lists. Add an ALLOW list containing:\n{IPS}"),
    ]
    return {"type": "databricks", "steps": steps, "fill": {"catalog": catalog, **({"schema": schemas[0]} if len(schemas) == 1 else {})},
            "then": "Back in NeuraFlow, choose Save and test. The test also tells you how many tables it can see."}


def build(ctype: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if ctype == "snowflake":
        return snowflake(params or {})
    if ctype == "databricks":
        return databricks(params or {})
    raise SourceError("Setup guides are available for Snowflake and Databricks.")
