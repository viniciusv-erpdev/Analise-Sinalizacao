"""Emit a reviewed provisioning SQL plan. Never connects to PostgreSQL or systemd."""
import argparse
from .report_permission_policy import identifier, grant_statements, ownership_statements, LAUNCH_FUNCTIONS, DISPATCH_FUNCTIONS


def render(database, prefix):
    identifier(database)
    identifier(prefix)
    if not database.startswith("analise_hml"):
        raise ValueError("Only a dedicated analise_hml database is accepted")
    roles = {name: prefix + "_" + name for name in ("http", "executor", "dispatcher", "launcher", "owner")}
    for role in roles.values():
        identifier(role)
    lines = ["-- PLAN ONLY. Execute only after separate approval on a disposable host/database.",
        r"\set ON_ERROR_STOP on",
        "-- Fails on existing roles: never silently reuse privileged or cross-environment identities.", "BEGIN;",
        "DO $guard$ BEGIN IF current_database() <> '" + database + "' THEN RAISE EXCEPTION 'wrong HML database'; END IF; END; $guard$;",
        f"REVOKE CONNECT, TEMPORARY ON DATABASE {identifier(database)} FROM PUBLIC;",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC;"]
    for name, role in roles.items():
        lines.append(f"CREATE ROLE {identifier(role)} {'NOLOGIN' if name == 'owner' else 'LOGIN'} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;")
        if name != "owner":
            lines.append(f"GRANT CONNECT ON DATABASE {identifier(database)} TO {identifier(role)};")
    for function in (*LAUNCH_FUNCTIONS, *DISPATCH_FUNCTIONS):
        lines.append(f"REVOKE ALL ON FUNCTION public.{function} FROM PUBLIC;")
    lines.extend(grant_statements(roles))
    lines.extend(ownership_statements(roles["owner"]))
    lines.append("COMMIT;")
    return "\n".join(line if line.startswith(("--", "\\")) or line.endswith(";") else line + ";" for line in lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--roles-prefix", default="report_hml")
    args = parser.parse_args()
    print(render(args.database, args.roles_prefix), end="")


if __name__ == "__main__":
    main()
