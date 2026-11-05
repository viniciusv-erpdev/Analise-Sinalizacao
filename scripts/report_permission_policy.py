"""Declarative asynchronous HML privileges, shared by plan generation and tests.

No connection, role creation, grants or deployment happens on import.
"""
import re

LAUNCH_FUNCTIONS = (
    "report_launcher_envelope(uuid)", "report_launcher_status(uuid)",
    "report_launcher_consume(uuid,uuid,uuid,integer,text,uuid,text,jsonb)",
    "report_launcher_job(uuid,uuid,bigint)",
)
DISPATCH_FUNCTIONS = ("report_dispatch_candidate()",
    "report_dispatch_prepare(uuid,uuid,uuid,text,text,text,uuid)")
OPERATIONAL = ("reportpublicationslot", "reportfinalizationattempt", "reportexecutionidentity",
    "reportlaunch", "reportdispatchdelivery", "reportlauncherreceipt", "reportdeploymentbarrier",
    "reportreleaseauthorization", "reportoperationalevent", "technicalreportversion", "technicalreport", "reportartifact")

# Statements are explicit: no ALL TABLES/SEQUENCES or runtime schema ownership.
HTTP = {
    "SELECT, INSERT, UPDATE, DELETE": (
        "django_session", "auth_user", "auth_group", "auth_user_groups",
        "auth_user_user_permissions", "auth_group_permissions",
        "signaling_signalingpoint", "signaling_signalingintervention",
        "signaling_signalingpointproblem", "signaling_waypointreservation", "signaling_waypointreportdraft"),
    "SELECT": ("auth_permission", "django_content_type",
        *("signaling_" + name for name in OPERATIONAL if name not in
          ("reportreleaseauthorization", "reportlauncherreceipt", "reportoperationalevent")), "signaling_reportannualcounter",
        "signaling_reportdeletion", "signaling_deletedreportkey", "django_admin_log"),
    "INSERT": ("signaling_reportpublicationslot", "signaling_reportfinalizationattempt",
        "signaling_technicalreport", "signaling_technicalreportversion", "signaling_reportartifact",
        "signaling_reportannualcounter", "signaling_reportdeletion", "signaling_deletedreportkey", "django_admin_log"),
    "DELETE": ("signaling_reportfinalizationattempt", "signaling_technicalreport",
        "signaling_technicalreportversion", "signaling_reportartifact"),
    "UPDATE (attempt_id, execution_id)": ("signaling_reportpublicationslot",),
    "UPDATE (last_reserved)": ("signaling_reportannualcounter",),
    "UPDATE (updated_at)": ("signaling_reportfinalizationattempt",),
    # Row locks for the audited physical deletion need an UPDATE privilege.
    # These grants never permit rewriting the historical snapshot or author.
    "UPDATE (finalized_at)": ("signaling_technicalreportversion",),
    "UPDATE (number_assigned_at, waypoint_id)": ("signaling_technicalreport",),
    # Existing Django collector SET_NULL when deleting an official attempt.
    "UPDATE (attempt_id)": ("signaling_reportexecutionidentity",),
    "UPDATE (cleanup_state, pending_keys, version_ids, error_code, cleanup_finished_at)": ("signaling_reportdeletion",),
}
EXECUTOR = {
    "SELECT": tuple("signaling_" + name for name in OPERATIONAL if name != "reportoperationalevent"),
    "INSERT": ("signaling_reportartifact",),
    "UPDATE (attempt_id, execution_id)": ("signaling_reportpublicationslot",),
    "UPDATE (state, execution_id, error_code, updated_at)": ("signaling_reportfinalizationattempt",),
    "UPDATE (finalized_at)": ("signaling_technicalreportversion",),
    "UPDATE (number_assigned_at)": ("signaling_technicalreport",),
    "UPDATE (confirmed_at)": ("signaling_reportlaunch",),  # Lock only; no state/dispatch authority.
    "UPDATE (bound_at, invocation_id, cgroup_path, cgroup_inode, main_pid, process_start_ticks)":
        ("signaling_reportexecutionidentity",),
}
OWNER = {
    "SELECT": tuple("signaling_" + name for name in OPERATIONAL),
    "UPDATE (state, dispatch_id, dispatch_started_at, job_id)": ("signaling_reportlaunch",),
    # SELECT FOR UPDATE requires UPDATE on at least one column of each locked table.
    "UPDATE (execution_id)": ("signaling_reportpublicationslot", "signaling_reportfinalizationattempt",
                               "signaling_reportexecutionidentity"),
    "INSERT": ("signaling_reportexecutionidentity", "signaling_reportlaunch", "signaling_reportdispatchdelivery",
               "signaling_reportlauncherreceipt", "signaling_reportoperationalevent"),
}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("Invalid SQL identifier")
    return '"' + value + '"'


def grant_statements(roles):
    """Only GRANT statements. Tests may exercise these in disposable databases."""
    if set(roles) != {"http", "executor", "dispatcher", "launcher", "owner"} or len(set(roles.values())) != 5:
        raise ValueError("Five distinct roles required")
    quoted = {name: identifier(value) for name, value in roles.items()}
    statements = [f"GRANT USAGE ON SCHEMA public TO {', '.join(quoted.values())}"]
    for role, policy in (("http", HTTP), ("executor", EXECUTOR), ("owner", OWNER)):
        for privilege, tables in policy.items():
            for table in tables:
                statements.append(f"GRANT {privilege} ON TABLE public.{identifier(table)} TO {quoted[role]}")
    # HTTP creates/deletes editable waypoint items; no operational UUID uses a sequence.
    for table in ("auth_user", "auth_group", "auth_user_groups", "auth_user_user_permissions",
            "auth_group_permissions", "django_admin_log", "signaling_signalingpoint",
            "signaling_signalingintervention", "signaling_signalingpointproblem"):
        statements.append(f"GRANT USAGE ON SEQUENCE public.{identifier(table + '_id_seq')} TO {quoted['http']}")
    statements.append(f"GRANT SELECT ON public.report_dispatch_projection TO {quoted['dispatcher']}")
    for role, functions in (("dispatcher", DISPATCH_FUNCTIONS), ("launcher", LAUNCH_FUNCTIONS)):
        for function in functions:
            statements.append(f"GRANT EXECUTE ON FUNCTION public.{function} TO {quoted[role]}")
    return statements


def ownership_statements(owner):
    return [f"ALTER FUNCTION public.{function} OWNER TO {identifier(owner)}"
            for function in (*LAUNCH_FUNCTIONS, *DISPATCH_FUNCTIONS)]
