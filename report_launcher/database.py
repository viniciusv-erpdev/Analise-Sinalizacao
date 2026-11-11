"""The only DB surface used by the standalone service. No ORM imports."""
import json
from .protocol import Rejected

MAX_ENVELOPE = 24*1024*1024


class Database:
    def __init__(self, dsn, connect=None):
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self.connect, self.dsn = connect, dsn

    def verify_privileges(self):
        valid = self._query("""SELECT current_user=session_user
          AND NOT (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls)
          AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid)
          AND NOT has_schema_privilege(current_user,'public','CREATE')
          AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_tables t WHERE t.schemaname='public'
            AND t.tablename LIKE 'signaling_%%' AND (has_table_privilege(current_user,
                quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'INSERT,UPDATE,DELETE,TRUNCATE')
              OR has_any_column_privilege(current_user,
                quote_ident(t.schemaname)||'.'||quote_ident(t.tablename),'INSERT,UPDATE')))
          AND (SELECT count(*)=4 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            JOIN pg_catalog.pg_roles o ON o.oid=p.proowner
            WHERE n.nspname='public' AND p.proname IN ('report_launcher_envelope','report_launcher_status',
              'report_launcher_consume','report_launcher_job') AND p.prosecdef AND NOT o.rolcanlogin
              AND NOT o.rolsuper AND p.proconfig @> ARRAY['search_path=pg_catalog']
              AND has_function_privilege(current_user,p.oid,'EXECUTE'))
          FROM pg_catalog.pg_roles r WHERE r.rolname=current_user""", ())
        if valid is not True:
            raise Rejected("database_privileges_unsafe")

    def _query(self, sql, parameters):
        try:
            # Return AFTER successful transaction context exit, never before ACK.
            with self.connect(self.dsn, connect_timeout=5) as db:
                with db.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                    cursor.execute("SET LOCAL lock_timeout = '1s'")
                    cursor.execute(sql, parameters)
                    row = cursor.fetchone()
            return row[0] if row else None
        except Exception as error:
            code = getattr(getattr(error, "diag", None), "message_primary", None)
            if code in {"publication_busy", "request_conflict", "launch_changed", "publication_maintenance",
                        "launch_invalid", "receipt_invalid", "job_conflict"}:
                raise Rejected(code) from None
            raise Rejected("database_state_unknown") from None

    def status(self, launch_id):
        return self._query("SELECT public.report_launcher_status(%s::uuid)", (launch_id,))

    def envelope(self, launch_id):
        value = self._query("SELECT public.report_launcher_envelope(%s::uuid)::text", (launch_id,))
        if value is None or len(value) > MAX_ENVELOPE:
            raise Rejected("envelope_unavailable")
        try:
            return json.loads(value)
        except (ValueError, RecursionError):
            raise Rejected("envelope_invalid") from None

    def consume(self, request, peer, host, boot, policy, envelope):
        return self._query("""SELECT public.report_launcher_consume(
            %s::uuid,%s::uuid,%s::uuid,%s::integer,%s::text,%s::uuid,%s::text,%s::jsonb)""",
            (request["launch_id"], request["request_id"], request["expected_barrier_generation"],
             peer["uid"], host, str(boot), policy, json.dumps(envelope, allow_nan=False)))

    def record_job(self, launch_id, request_id, job_id):
        self._query("SELECT public.report_launcher_job(%s::uuid,%s::uuid,%s::bigint)",
                    (launch_id, request_id, job_id))
