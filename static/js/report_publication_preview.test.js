"use strict";
const test=require("node:test"), assert=require("node:assert/strict");
const {evaluate,mount}=require("./report_publication_preview.js");
const ready=()=>({authorized:true,reserved:true,enabled:true,photos:[],
    draft:{state:"saved",confirmed:true,revision:0,pending:false,paused:false,stopped:false,conflict:false}});
test("confirmed zero revision is valid; local unconfirmed revision is not",()=>{
    assert.equal(evaluate(ready()).ready,true);
    const input=ready(); input.draft.confirmed=false;
    assert.equal(evaluate(input).revision,null); assert.equal(evaluate(input).ready,false);
});
for(const state of ["pending","saving","error","conflict","stopped","loading"])test(`autosave ${state} blocks readiness`,()=>{
    const input=ready(); input.draft.state=state; assert.equal(evaluate(input).ready,false);
});
test("authorization, reservation, environment and pending edits each block readiness",()=>{
    for(const field of ["authorized","reserved","enabled"]){const input=ready();input[field]=false;assert.equal(evaluate(input).ready,false);}
    const input=ready();input.draft.pending=true;assert.equal(evaluate(input).ready,false);
});
test("photos counted, formats and per-file/aggregate limits validated",()=>{
    const input=ready();input.photos=[{type:"image/png",size:100}];assert.equal(evaluate(input).count,1);
    for(const photos of [[{type:"image/gif",size:20}],[{type:"image/jpeg",size:11*1024*1024}],
        Array(11).fill({type:"image/png",size:1}),Array(3).fill({type:"image/png",size:9*1024*1024})]){
        input.photos=photos;assert.equal(evaluate(input).ready,false);
    }
});
function node(){const events=new Map();return {events,textContent:"",disabled:false,removeAttribute(name){delete this[name];},addEventListener:(type,fn)=>events.set(type,fn),removeEventListener:type=>events.delete(type),focus(){this.focused=true;}};}
function fixture(withFlow=false,initial={}){
    const open=node(),dialog=node(),form=node(),nodes=Object.fromEntries(["point","save-status","warnings","cancel","confirm","recover","retry","result","report-link"].map(k=>[k,node()]));
    let reserved=true, snapshot=ready().draft, changed;
    dialog.dataset={enabled:"true",userId:"7",reportUrl:"/signaling/reports/00000000-0000-0000-0000-000000000000/"}; dialog.open=false;
    dialog.showModal=()=>{dialog.open=true;}; dialog.close=()=>{dialog.open=false;};
    dialog.querySelector=selector=>nodes[selector.match(/publication-(.*)\]/)[1]];
    form.querySelector=selector=>selector.includes("photos")?{files:[{size:10,type:"image/png"}]}:node();
    const doc={body:{style:{overflow:"auto"}},querySelector:selector=>selector.includes("-open")?open:selector.includes("-dialog")?dialog:form,
        defaultView:{MutationObserver:class {observe(){} disconnect(){}}}};
    const manager={canOperate:()=>reserved,subscribe:fn=>{changed=fn;return ()=>{changed=null;};}};
    const draft={snapshot:()=>snapshot};
    const actions=[], progress={supported:true,busy:false,record:null,outcome:null}; let notify;Object.assign(progress,initial);
    const flowFactory=withFlow?{create(options){notify=options.notify;notify(progress);return {snapshot:()=>progress,refresh(){notify(progress);},
        publish(){actions.push("publish");},recover(){actions.push("recover");},retry(){actions.push("retry");},publishAnother(key){actions.push("another:"+key);}};}}:undefined;
    const environment={fetch:async()=>{},navigator:{},crypto:{},addEventListener(){},removeEventListener(){}};
    const controller=mount({doc,pointId:23,manager,draft,flowFactory,environment});
    return {open,dialog,nodes,controller,actions,doc,set progress(value){Object.assign(progress,value);notify(progress);},set reserved(value){reserved=value;changed();},set snapshot(value){snapshot=value;changed();}};
}
test("open, refresh after lease loss, cancel and destroy have no network or intent side effects",()=>{
    const f=fixture();assert.equal(f.dialog.open,false);
    f.open.events.get("click")();assert.equal(f.dialog.open,true);
    assert.equal(f.nodes.point.textContent,"23");assert.equal(f.nodes["save-status"].textContent,"Salvo");
    f.reserved=false;assert.match(f.nodes.warnings.textContent,/Reserva/);
    f.nodes.cancel.events.get("click")();assert.equal(f.dialog.open,false);assert.equal(f.open.focused,true);
    f.open.events.get("click")();let prevented=false;f.dialog.events.get("cancel")({preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.equal(f.dialog.open,false);
    f.controller.destroy();assert.equal(f.open.events.size,0);
});
test("without authorized server-rendered trigger, nothing mounts",()=>{
    assert.equal(mount({doc:{querySelector:()=>null}}),null);
});

test("confirm is explicit, readiness guarded, and modal cannot close during publication",()=>{
    const f=fixture(true);f.open.events.get("click")();assert.deepEqual(f.actions,[]);
    assert.equal(f.nodes.confirm.disabled,false);f.nodes.confirm.events.get("click")();assert.deepEqual(f.actions,["publish"]);
    f.progress={busy:true};assert.equal(f.nodes.confirm.disabled,true);
    f.nodes.confirm.events.get("click")();assert.equal(f.actions.length,1);
    f.nodes.cancel.events.get("click")();assert.equal(f.dialog.open,true);
    f.progress={busy:false};f.reserved=false;assert.equal(f.nodes.confirm.disabled,true);
});
test("202 is not success; published number and authorized detail link render without visible version",()=>{
    const f=fixture(true);f.open.events.get("click")();
    f.progress={record:{attemptId:"known",last:{attempt:{state:"PROCESSING"}}},outcome:{kind:"processing"}};
    assert.equal(f.nodes["report-link"].hidden,true);assert.equal(f.nodes.confirm.disabled,true);
    const attempt={report_id:"published-id",number:"RTSV-2026-0001",version:1};
    f.progress={record:{last:{kind:"published"}},outcome:{kind:"published",attempt}};
    assert.match(f.nodes.result.textContent,/RTSV-2026-0001/);
    assert.equal(f.nodes["report-link"].href,"/signaling/reports/published-id/");
    assert.equal(f.nodes["report-link"].hidden,false);
    f.dialog.dataset.reportUrl="";f.progress={};assert.equal(f.nodes["report-link"].hidden,true);
});
test("pending autosave or permission error does not present a successful publication",()=>{
    const f=fixture(true);f.open.events.get("click")();f.snapshot={state:"error",confirmed:true,revision:3};
    assert.equal(f.nodes.confirm.disabled,true);
    f.progress={outcome:{kind:"forbidden"},record:{last:{kind:"forbidden"}}};
    assert.match(f.nodes.result.textContent,/Permiss/);assert.equal(f.nodes["report-link"].hidden,true);
});

test("publication modal locks background scroll and restores it on cancel or destroy",()=>{
    const f=fixture();f.open.events.get("click")();assert.equal(f.doc.body.style.overflow,"hidden");
    f.nodes.cancel.events.get("click")();assert.equal(f.doc.body.style.overflow,"auto");
    f.open.events.get("click")();f.controller.destroy();assert.equal(f.doc.body.style.overflow,"auto");
});

for (const [state, confirmed, label] of [["saved",true,"Salvo"],["saved",false,"N\u00e3o salvo"],["pending",true,"N\u00e3o salvo"],["error",true,"N\u00e3o salvo"],["saving",true,"Salvando..."]]) {
    test(`save badge reflects backend confirmation: ${state}/${confirmed}`,()=>{
        const f=fixture(true); f.open.events.get("click")();
        f.snapshot={...ready().draft,state,confirmed};
        assert.equal(f.nodes["save-status"].textContent,label);
        assert.equal(f.nodes.confirm.disabled,label!=="Salvo");
    });
}
test("success removes redundant modal actions; reopening never starts a new intent",()=>{
    const f=fixture(true); f.open.events.get("click")();
    f.progress={canStartNew:true,record:{last:{kind:"published"}},outcome:{kind:"published",attempt:{report_id:"id",number:"RTSV-2026-0001",version:1}}};
    for (const key of ["confirm","recover","retry"]) assert.equal(f.nodes[key].hidden,true);
    assert.equal(f.nodes.new,undefined);
    f.nodes.cancel.events.get("click")(); f.open.events.get("click")();
    assert.deepEqual(f.actions,[]);
});
test("ambiguous result offers verification; only confirmed failed attempt offers retry",()=>{
    const f=fixture(true); f.open.events.get("click")();
    f.progress={record:{attemptId:"a",last:{kind:"uncertain"}},outcome:{kind:"uncertain"}};
    assert.equal(f.nodes.recover.hidden,false); assert.equal(f.nodes.retry.hidden,true);
    f.nodes.recover.events.get("click")(); assert.deepEqual(f.actions,["recover"]);
    f.progress={record:{attemptId:"a",last:{attempt:{state:"FAILED"}}},outcome:{kind:"retry_required"}};
    assert.equal(f.nodes.retry.hidden,false);
    f.nodes.retry.events.get("click")(); assert.deepEqual(f.actions,["recover","retry"]);
    f.progress={outcome:{kind:"conflict",code:"snapshot_integrity_failed"}};
    assert.equal(f.nodes.retry.hidden,true); assert.equal(f.nodes.recover.hidden,true);
});


const previousKey="11111111-1111-4111-8111-111111111111";
const settled=()=>({canStartNew:true,record:{key:previousKey,last:{kind:"published",attempt:{report_id:"id",number:"RTSV-2026-0001",version:1}}},outcome:{kind:"published",attempt:{report_id:"id",number:"RTSV-2026-0001",version:1}}});
test("first render sees restored journal despite synchronous create notification",()=>{
    const f=fixture(true,settled());
    assert.match(f.nodes.result.textContent,/RTSV-2026-0001/);
    assert.equal(f.nodes.confirm.hidden,true);
    assert.doesNotMatch(f.nodes.result.textContent,/vers\u00e3o/i);
    assert.deepEqual(f.actions,[]);
});
test("main action offers explicit independent publication; cancel does not reset or send",async()=>{
    const f=fixture(true,settled());
    f.open.events.get("click")();assert.equal(f.nodes.confirm.hidden,false);
    assert.match(f.nodes.confirm.textContent,/nova publica/);
    assert.match(f.nodes.result.textContent,/outro relat.*independente/);
    assert.match(f.nodes.result.textContent,/novo n/);
    f.nodes.cancel.events.get("click")();assert.deepEqual(f.actions,[]);
    f.open.events.get("click")();await f.nodes.confirm.events.get("click")();
    assert.deepEqual(f.actions,["another:"+previousKey]);
});
test("restored 202 and recoverable failure offer recovery, never independent confirmation",()=>{
    for(const state of ["PROCESSING","FAILED","INTERRUPTED"]){
        const kind=state==="PROCESSING"?"processing":"retry_required";
        const f=fixture(true,{canStartNew:state!=="PROCESSING",record:{key:previousKey,attemptId:"id",last:{kind,code:"conversion_failed",attempt:{state}}},outcome:{kind}});
        f.open.events.get("click")();assert.equal(f.nodes.confirm.hidden,true);
        assert.equal(f.nodes.recover.hidden,false);
        assert.equal(f.nodes.retry.hidden,state==="PROCESSING");assert.deepEqual(f.actions,[]);
    }
});
test("known definitive terminal failure permits specific new-publication confirmation",()=>{
    const f=fixture(true,{canStartNew:true,record:{key:previousKey,attemptId:"id",last:{kind:"error",code:"report_source_changed",attempt:{state:"FAILED",number:"RTSV-2026-0001"}}},outcome:{kind:"error",code:"report_source_changed"}});
    f.open.events.get("click")();assert.equal(f.nodes.confirm.hidden,false);
    assert.match(f.nodes.result.textContent,/novo n/);assert.equal(f.nodes.retry.hidden,true);
});
test("restored forbidden or deleted result never clears intent or offers a new confirmation",()=>{
    for(const code of ["report_deleted","finalization_not_found","permission_denied"]){
        const kind=code==="permission_denied"?"forbidden":"error";
        const f=fixture(true,{canStartNew:false,record:{key:previousKey,attemptId:"id",last:{kind,code}},outcome:{kind,code}});
        f.open.events.get("click")();assert.equal(f.nodes.confirm.hidden,true);
        assert.match(f.nodes.result.textContent,code==="report_deleted"?/exclu/:code==="finalization_not_found"?/inacess/:/Permiss/);
        f.nodes.cancel.events.get("click")();assert.deepEqual(f.actions,[]);
    }
});

test("HTTP409 status description keeps definitive failure eligible via attempt error_code",()=>{
    const f=fixture(true,{canStartNew:true,record:{key:previousKey,attemptId:"id",last:{kind:"conflict",code:"request_failed",attempt:{state:"FAILED",error_code:"report_source_changed"}}},outcome:{kind:"conflict",code:"request_failed",attempt:{state:"FAILED",error_code:"report_source_changed"}}});
    f.open.events.get("click")();assert.equal(f.nodes.confirm.hidden,false);
    assert.equal(f.nodes.retry.hidden,true);assert.match(f.nodes.result.textContent,/novo n/);
});
