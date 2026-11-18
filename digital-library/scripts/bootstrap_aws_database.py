"""Explicit deployment bootstrap, run inside the VPC with Secret-backed URLs.

No credentials are read from files or printed. Application processes do not run
this script. Existing roles are retained, and their passwords match the Secrets.
"""

import os
import sys
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql


def bootstrap():
    admin_url = os.environ["ADMIN_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    roles = {}
    with psycopg.connect(admin_url) as connection:
        with connection.cursor() as cursor:
            for service in ("member", "reservation", "lending", "availability", "fine"):
                url = urlsplit(os.environ[f"{service.upper()}_DATABASE_URL"])
                role = unquote(url.username)
                if role != f"library_{service}":
                    raise ValueError("Unexpected application role")
                roles[service] = role
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
                # PostgreSQL 16 gives a non-superuser creator ADMIN membership
                # without SET; default-privilege management also needs SET.
                cursor.execute(sql.SQL("GRANT {} TO {} WITH SET TRUE").format(
                    sql.Identifier(role), sql.Identifier(connection.info.user)))
                cursor.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(unquote(url.password))))
                cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.info.dbname), sql.Identifier(role)))
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
                if service in {"member", "reservation", "lending"}:
                    cursor.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            for owner, reader, table in (
                ("reservation", "availability", "reservations"),
                ("lending", "availability", "loans"),
                ("lending", "fine", "loans"),
            ):
                cursor.execute(sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(roles[owner]), sql.Identifier(roles[reader])))
                cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                if cursor.fetchone()[0] is not None:
                    cursor.execute(sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(
                        sql.Identifier(table), sql.Identifier(roles[reader])))
    print("Database bootstrap completed: application owners and read-only roles configured.", flush=True)


if __name__ == "__main__":
    try:
        bootstrap()
    except Exception as error:
        # Connection strings and SQL literals can contain credentials.
        print(f"Database bootstrap failed: {type(error).__name__}; SQLSTATE={getattr(error, 'sqlstate', None)}", file=sys.stderr)
        if getattr(error, "sqlstate", None) == "42501":
            print(error.diag.message_primary, file=sys.stderr)
        sys.exit(1)
