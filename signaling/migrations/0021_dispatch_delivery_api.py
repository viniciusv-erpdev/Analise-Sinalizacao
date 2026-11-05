"""One-shot handoff + restricted dispatcher API. No runtime grants or roles."""
from django.db import migrations, models
import django.db.models.deletion


SQL = r"""
CREATE FUNCTION public.report_dispatch_candidate() RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $body$
SELECT jsonb_build_object(
 'attempt_id',s.attempt_id,'execution_id',s.execution_id,'state',a.state,
 'contract',a.execution_contract,'admitted',a.admitted_at IS NOT NULL,
 'barrier_state',coalesce(b.state,'OPEN'),
 'generation',coalesce(b.generation,'00000000-0000-0000-0000-000000000000'::uuid),
 'identity_id',i.id,'launch_id',l.id,'launch_state',l.state,'delivered',d.id IS NOT NULL,
 'other_unfinished',(SELECT count(*) FROM public.signaling_reportfinalizationattempt x
   WHERE x.state<>'FINALIZED' AND x.id IS DISTINCT FROM s.attempt_id),
 'identity_count',(SELECT count(*) FROM public.signaling_reportexecutionidentity),
 'launch_count',(SELECT count(*) FROM public.signaling_reportlaunch))
FROM (SELECT 1 AS id) seed
LEFT JOIN public.signaling_reportpublicationslot s ON s.id=seed.id
LEFT JOIN public.signaling_reportfinalizationattempt a ON a.id=s.attempt_id
LEFT JOIN public.signaling_reportdeploymentbarrier b ON b.id=seed.id
LEFT JOIN public.signaling_reportexecutionidentity i ON i.attempt_id=a.id
LEFT JOIN public.signaling_reportlaunch l ON l.identity_id=i.id
LEFT JOIN public.signaling_reportdispatchdelivery d ON d.launch_id=l.id;
$body$;

CREATE FUNCTION public.report_dispatch_prepare(p_attempt uuid,p_execution uuid,p_generation uuid,
 p_release text,p_root text,p_host text,p_boot uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $body$
DECLARE s public.signaling_reportpublicationslot; a public.signaling_reportfinalizationattempt;
 i public.signaling_reportexecutionidentity; l public.signaling_reportlaunch;
 r public.signaling_reportreleaseauthorization; b public.signaling_reportdeploymentbarrier;
 d public.signaling_reportdispatchdelivery; contract jsonb;
BEGIN
 IF NOT pg_try_advisory_xact_lock(182736,1) THEN RAISE EXCEPTION 'publication_busy'; END IF;
 SELECT * INTO s FROM public.signaling_reportpublicationslot WHERE id=1 FOR UPDATE NOWAIT;
 IF s.attempt_id IS DISTINCT FROM p_attempt OR s.execution_id IS DISTINCT FROM p_execution
    OR p_attempt IS NULL OR p_execution IS NULL THEN RAISE EXCEPTION 'dispatch_slot_changed'; END IF;
 SELECT * INTO b FROM public.signaling_reportdeploymentbarrier WHERE id=1;
 IF coalesce(b.state,'OPEN')<>'OPEN' OR coalesce(b.generation,
   '00000000-0000-0000-0000-000000000000'::uuid) IS DISTINCT FROM p_generation THEN
   RAISE EXCEPTION 'publication_maintenance'; END IF;
 SELECT * INTO a FROM public.signaling_reportfinalizationattempt WHERE id=p_attempt FOR UPDATE;
 contract := '{"admission":1,"snapshot":1,"renderer":1,"launcher":1}'::jsonb;
 IF a.state IS DISTINCT FROM 'ADMITTED' OR a.admitted_at IS NULL OR a.deadline IS NOT NULL
   OR a.execution_id IS DISTINCT FROM p_execution OR a.execution_contract IS DISTINCT FROM contract
   OR EXISTS(SELECT 1 FROM public.signaling_reportfinalizationattempt x
       WHERE x.id<>p_attempt AND x.state<>'FINALIZED') THEN RAISE EXCEPTION 'dispatch_intent_invalid'; END IF;
 SELECT * INTO r FROM public.signaling_reportreleaseauthorization WHERE release_id=p_release;
 IF NOT FOUND OR r.execution_contract IS DISTINCT FROM contract
   OR p_release !~ '^[a-f0-9]{40,64}$' OR r.manifest_sha256 !~ '^[a-f0-9]{64}$'
   OR r.bundle_sha256 !~ '^[a-f0-9]{64}$' THEN RAISE EXCEPTION 'launch_release_incompatible'; END IF;
 -- The root catalogue independently attests this root and every release file.
 -- This argument is metadata, never an executable path accepted by the launcher.
 IF p_root IS NULL OR length(p_root)>1024 OR p_root !~ '^/[^[:cntrl:]]+$'
    OR p_root ~ '(^|/)\.\.?(/|$)' OR p_host IS NULL OR p_host !~ '^[a-f0-9]{32}$'
    OR p_host=repeat('0',32) OR p_boot IS NULL
    OR p_boot='00000000-0000-0000-0000-000000000000'::uuid THEN
   RAISE EXCEPTION 'dispatch_configuration_invalid'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.signaling_technicalreportversion v
   JOIN public.signaling_technicalreport t ON t.id=v.report_id WHERE v.id=a.version_id
   AND v.schema_version=1 AND v.finalized_at IS NULL AND t.number_assigned_at IS NULL
   AND v.snapshot_sha256 ~ '^[a-f0-9]{64}$' AND v.source_sha256 ~ '^[a-f0-9]{64}$')
   OR EXISTS(SELECT 1 FROM public.signaling_reportartifact WHERE version_id=a.version_id
             AND kind IN ('DOCX','PDF')) THEN RAISE EXCEPTION 'dispatch_intent_invalid'; END IF;
 SELECT * INTO i FROM public.signaling_reportexecutionidentity WHERE attempt_reference=p_attempt
   AND expected_execution_id=p_execution;
 IF FOUND THEN
   IF i.attempt_id IS DISTINCT FROM p_attempt OR i.bound_at IS NOT NULL
     OR i.host_id<>p_host OR i.boot_id<>p_boot OR i.release_id<>p_release
     OR i.release_root<>p_root OR i.service_user<>'analise_app' THEN
     RAISE EXCEPTION 'dispatch_identity_conflict'; END IF;
 ELSE
   IF EXISTS(SELECT 1 FROM public.signaling_reportexecutionidentity) THEN
     RAISE EXCEPTION 'operational_reconciliation_required'; END IF;
   i.id := gen_random_uuid();
   INSERT INTO public.signaling_reportexecutionidentity(id,attempt_id,attempt_reference,
     expected_execution_id,execution_id,host_id,boot_id,unit_name,release_id,release_root,service_user,prepared_at)
   VALUES(i.id,p_attempt,p_attempt,p_execution,gen_random_uuid(),p_host,p_boot,
     'rtsv-report-'||replace(i.id::text,'-','')||'.service',p_release,p_root,'analise_app',clock_timestamp());
 END IF;
 IF EXISTS(SELECT 1 FROM public.signaling_reportexecutionidentity WHERE id<>i.id) THEN
   RAISE EXCEPTION 'operational_reconciliation_required'; END IF;
 IF EXISTS(SELECT 1 FROM public.signaling_reportexecutionidentity WHERE id=i.id AND
    (unit_name<>'rtsv-report-'||replace(i.id::text,'-','')||'.service'
     OR execution_id=p_execution OR execution_id='00000000-0000-0000-0000-000000000000'::uuid)) THEN
   RAISE EXCEPTION 'dispatch_identity_conflict'; END IF;
 SELECT * INTO l FROM public.signaling_reportlaunch WHERE identity_id=i.id;
 IF NOT FOUND THEN
   IF EXISTS(SELECT 1 FROM public.signaling_reportlaunch) THEN RAISE EXCEPTION 'operational_reconciliation_required'; END IF;
   INSERT INTO public.signaling_reportlaunch(id,identity_id,release_id,state,contract_sha256,requested_at)
   VALUES(gen_random_uuid(),i.id,p_release,'REQUESTED',
     encode(sha256(convert_to('{"admission":1,"launcher":1,"renderer":1,"snapshot":1}','UTF8')),'hex'),clock_timestamp())
   RETURNING * INTO l;
 END IF;
 IF EXISTS(SELECT 1 FROM public.signaling_reportlaunch WHERE id<>l.id) THEN
   RAISE EXCEPTION 'operational_reconciliation_required'; END IF;
 IF l.release_id<>p_release OR l.contract_sha256<>
   encode(sha256(convert_to('{"admission":1,"launcher":1,"renderer":1,"snapshot":1}','UTF8')),'hex') THEN
   RAISE EXCEPTION 'dispatch_intent_invalid'; END IF;
 SELECT * INTO d FROM public.signaling_reportdispatchdelivery WHERE launch_id=l.id;
 IF FOUND OR l.state<>'REQUESTED' OR l.dispatch_id IS NOT NULL THEN
   RETURN jsonb_build_object('fresh',false,'outcome','DELIVERY_UNCERTAIN'); END IF;
 INSERT INTO public.signaling_reportdispatchdelivery(id,launch_id,barrier_generation,created_at)
 VALUES(gen_random_uuid(),l.id,p_generation,clock_timestamp()) RETURNING * INTO d;
 INSERT INTO public.signaling_reportoperationalevent(id,subject,kind,actor,fingerprint,details,created_at)
 VALUES(gen_random_uuid(),l.id,'DISPATCH_DELIVERY_PREPARED',d.id,
   encode(sha256(convert_to(d.id::text||l.id::text,'UTF8')),'hex'),
   jsonb_build_object('generation',p_generation),clock_timestamp());
 RETURN jsonb_build_object('fresh',true,'launch_id',l.id,'request_id',d.id,'generation',p_generation);
END;
$body$;
REVOKE ALL ON FUNCTION public.report_dispatch_candidate() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.report_dispatch_prepare(uuid,uuid,uuid,text,text,text,uuid) FROM PUBLIC;
"""


def install(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP FUNCTION public.report_dispatch_prepare(uuid,uuid,uuid,text,text,text,uuid);")
        schema_editor.execute("DROP FUNCTION public.report_dispatch_candidate();")


class Migration(migrations.Migration):
    dependencies = [("signaling", "0020_launcher_sql_contract")]
    operations = [migrations.CreateModel(name="ReportDispatchDelivery", fields=[
        ("id", models.UUIDField(primary_key=True, editable=False, serialize=False)),
        ("barrier_generation", models.UUIDField(editable=False)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
        ("launch", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
            related_name="delivery", to="signaling.reportlaunch")),
    ], options={"default_permissions": ()}), migrations.RunPython(install, uninstall)]
