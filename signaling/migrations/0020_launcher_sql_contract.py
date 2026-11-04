"""Restricted external authority API. No roles/grants to runtime are installed.

Deployment must assign these SECURITY DEFINER functions to a NOLOGIN owner and
explicitly grant only approved entry points; PUBLIC execute is revoked here.
"""
from django.db import migrations

SQL = r"""
CREATE FUNCTION public.report_launcher_envelope(p_launch uuid) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $body$
SELECT jsonb_build_object(
 'launch', to_jsonb(l), 'identity', to_jsonb(i),
 'attempt', to_jsonb(a) - ARRAY['idempotency_key','request_sha256','requested_by_id'],
 'version', to_jsonb(v), 'release', to_jsonb(r), 'slot', to_jsonb(s),
 'official_number', 'RTSV-' || lpad(t.year::text,4,'0') || '-' || lpad(t.sequence::text,4,'0'),
 'number_assigned_at', t.number_assigned_at,
 'barrier', coalesce((SELECT jsonb_build_object('state',b.state,'generation',b.generation)
    FROM public.signaling_reportdeploymentbarrier b WHERE b.id=1),
    '{"state":"OPEN","generation":"00000000-0000-0000-0000-000000000000"}'::jsonb),
 'photos', coalesce((SELECT jsonb_agg(jsonb_build_object('ordinal',p.ordinal,'metadata',p.metadata,
    'size',p.size,'sha256',p.sha256,'content_type',p.content_type) ORDER BY p.ordinal)
    FROM public.signaling_reportartifact p WHERE p.version_id=v.id AND p.kind='PHOTO'), '[]'::jsonb),
 'derivatives', EXISTS(SELECT 1 FROM public.signaling_reportartifact p WHERE p.version_id=v.id AND p.kind IN ('DOCX','PDF')),
 'other_unfinished', (SELECT count(*) FROM public.signaling_reportfinalizationattempt x WHERE x.id<>a.id AND x.state<>'FINALIZED'),
 'identity_count', (SELECT count(*) FROM public.signaling_reportexecutionidentity),
 'launch_count', (SELECT count(*) FROM public.signaling_reportlaunch))
FROM public.signaling_reportlaunch l
JOIN public.signaling_reportexecutionidentity i ON i.id=l.identity_id
JOIN public.signaling_reportfinalizationattempt a ON a.id=i.attempt_id
JOIN public.signaling_technicalreportversion v ON v.id=a.version_id
JOIN public.signaling_technicalreport t ON t.id=v.report_id
JOIN public.signaling_reportreleaseauthorization r ON r.release_id=l.release_id
JOIN public.signaling_reportpublicationslot s ON s.id=1 AND s.attempt_id=a.id
WHERE l.id=p_launch AND octet_length(v.snapshot::text)<=16777216;
$body$;

CREATE FUNCTION public.report_launcher_status(p_launch uuid) RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $body$
SELECT jsonb_build_object('launch_id',l.id,'state',l.state,'consumed',r.id IS NOT NULL,
 'request_id',r.id,'job_id',l.job_id,'invocation_id',l.invocation_id)
FROM public.signaling_reportlaunch l LEFT JOIN public.signaling_reportlauncherreceipt r ON r.launch_id=l.id
WHERE l.id=p_launch;
$body$;

CREATE FUNCTION public.report_launcher_consume(p_launch uuid,p_request uuid,p_generation uuid,
 p_peer integer,p_host text,p_boot uuid,p_policy text,p_expected jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
DECLARE e jsonb; receipt public.signaling_reportlauncherreceipt; ticket uuid; rid uuid;
BEGIN
 IF NOT pg_try_advisory_xact_lock(182736,1) THEN RAISE EXCEPTION 'publication_busy'; END IF;
 PERFORM 1 FROM public.signaling_reportpublicationslot WHERE id=1 FOR UPDATE NOWAIT;
 SELECT * INTO receipt FROM public.signaling_reportlauncherreceipt WHERE launch_id=p_launch;
 IF FOUND THEN
   RETURN jsonb_build_object('fresh',false,'state','UNCERTAIN');
 END IF;
 IF EXISTS(SELECT 1 FROM public.signaling_reportlauncherreceipt WHERE id=p_request) THEN
   RAISE EXCEPTION 'request_conflict';
 END IF;
 PERFORM 1 FROM public.signaling_reportlaunch WHERE id=p_launch FOR UPDATE;
 PERFORM 1 FROM public.signaling_reportfinalizationattempt
    WHERE id=(SELECT attempt_id FROM public.signaling_reportexecutionidentity
      WHERE id=(SELECT identity_id FROM public.signaling_reportlaunch WHERE id=p_launch)) FOR UPDATE;
 PERFORM 1 FROM public.signaling_reportexecutionidentity
    WHERE id=(SELECT identity_id FROM public.signaling_reportlaunch WHERE id=p_launch) FOR UPDATE;
 e := public.report_launcher_envelope(p_launch);
 IF e IS NULL OR e IS DISTINCT FROM p_expected THEN RAISE EXCEPTION 'launch_changed'; END IF;
 IF e#>>'{barrier,state}' <> 'OPEN' OR (e#>>'{barrier,generation}')::uuid<>p_generation THEN
   RAISE EXCEPTION 'publication_maintenance';
 END IF;
 IF e#>>'{launch,state}'<>'REQUESTED' OR e#>>'{launch,dispatch_id}' IS NOT NULL
    OR e#>>'{attempt,state}'<>'ADMITTED' OR e#>>'{attempt,admitted_at}' IS NULL
    OR e#>>'{attempt,deadline}' IS NOT NULL OR e#>>'{identity,bound_at}' IS NOT NULL
    OR e#>>'{identity,expected_execution_id}'<>e#>>'{attempt,execution_id}'
    OR e#>>'{slot,execution_id}'<>e#>>'{attempt,execution_id}'
    OR e#>>'{identity,host_id}'<>p_host OR (e#>>'{identity,boot_id}')::uuid<>p_boot
    OR p_peer<=0 OR p_policy !~ '^[a-f0-9]{64}$'
    OR (e->>'identity_count')::int<>1 OR (e->>'launch_count')::int<>1
    OR (e->>'other_unfinished')::int<>0 THEN RAISE EXCEPTION 'launch_invalid'; END IF;
 ticket := gen_random_uuid();
 INSERT INTO public.signaling_reportlauncherreceipt
  (id,launch_id,dispatch_id,barrier_generation,peer_uid,host_id,boot_id,policy_sha256,
   manifest_sha256,bundle_sha256,created_at)
 VALUES(p_request,p_launch,ticket,p_generation,p_peer,p_host,p_boot,p_policy,
   e#>>'{release,manifest_sha256}',e#>>'{release,bundle_sha256}',clock_timestamp());
 UPDATE public.signaling_reportlaunch SET state='UNCERTAIN',dispatch_id=ticket,
   dispatch_started_at=clock_timestamp() WHERE id=p_launch;
 INSERT INTO public.signaling_reportoperationalevent(id,subject,kind,actor,fingerprint,details,created_at)
 VALUES(gen_random_uuid(),p_launch,'LAUNCHER_CONSUMED',p_request,
   encode(sha256(convert_to(p_request::text||p_launch::text||p_policy,'UTF8')),'hex'),
   jsonb_build_object('peer_uid',p_peer,'generation',p_generation,'policy_sha256',p_policy),clock_timestamp());
 RETURN jsonb_build_object('fresh',true,'dispatch_id',ticket);
END;
$body$;

CREATE FUNCTION public.report_launcher_job(p_launch uuid,p_request uuid,p_job bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
DECLARE l public.signaling_reportlaunch; r public.signaling_reportlauncherreceipt;
BEGIN
 IF NOT pg_try_advisory_xact_lock(182736,1) THEN RAISE EXCEPTION 'publication_busy'; END IF;
 SELECT * INTO r FROM public.signaling_reportlauncherreceipt WHERE launch_id=p_launch AND id=p_request;
 IF NOT FOUND OR p_job<=0 THEN RAISE EXCEPTION 'receipt_invalid'; END IF;
 SELECT * INTO l FROM public.signaling_reportlaunch WHERE id=p_launch FOR UPDATE;
 IF l.dispatch_id<>r.dispatch_id OR (l.job_id IS NOT NULL AND l.job_id<>p_job) THEN
   RAISE EXCEPTION 'job_conflict';
 END IF;
 IF l.job_id=p_job THEN RETURN; END IF;
 UPDATE public.signaling_reportlaunch SET job_id=p_job WHERE id=p_launch;
 INSERT INTO public.signaling_reportoperationalevent(id,subject,kind,actor,fingerprint,details,created_at)
 VALUES(gen_random_uuid(),p_launch,'LAUNCHER_JOB_OBSERVED',p_request,
  encode(sha256(convert_to(p_request::text||p_job::text,'UTF8')),'hex'),
  jsonb_build_object('job_id',p_job),clock_timestamp());
END;
$body$;

CREATE VIEW public.report_dispatch_projection AS
SELECT s.attempt_id,s.execution_id,a.state,a.execution_contract,b.state AS barrier_state,b.generation,
 i.id AS identity_id,l.id AS launch_id,l.state AS launch_state
FROM public.signaling_reportpublicationslot s
LEFT JOIN public.signaling_reportfinalizationattempt a ON a.id=s.attempt_id
LEFT JOIN public.signaling_reportdeploymentbarrier b ON b.id=1
LEFT JOIN public.signaling_reportexecutionidentity i ON i.attempt_id=a.id
LEFT JOIN public.signaling_reportlaunch l ON l.identity_id=i.id WHERE s.id=1;

REVOKE ALL ON FUNCTION public.report_launcher_envelope(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.report_launcher_status(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.report_launcher_consume(uuid,uuid,uuid,integer,text,uuid,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.report_launcher_job(uuid,uuid,bigint) FROM PUBLIC;
REVOKE ALL ON public.report_dispatch_projection FROM PUBLIC;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
        DROP VIEW public.report_dispatch_projection;
        DROP FUNCTION public.report_launcher_job(uuid,uuid,bigint);
        DROP FUNCTION public.report_launcher_consume(uuid,uuid,uuid,integer,text,uuid,text,jsonb);
        DROP FUNCTION public.report_launcher_status(uuid);
        DROP FUNCTION public.report_launcher_envelope(uuid);
        """)


class Migration(migrations.Migration):
    dependencies = [("signaling", "0019_report_launcher_receipt")]
    operations = [migrations.RunPython(install, uninstall)]
