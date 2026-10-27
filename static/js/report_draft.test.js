"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const {create, mount, fields} = require("./report_draft.js");
const deferred = () => { let resolve,reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; };
const tick = async () => { for (let i=0;i<20;i++) await Promise.resolve(); };
const empty = () => Object.fromEntries(fields.map(name => [name,name === "pgts" ? [] : name.endsWith("_date") ? null : ""]));
const data = (values={},revision=0,point=7) => ({success:true, point_id:point, revision, fields:{...empty(),...values}});
function fixture() {
    let remote=data(),handler=null,next=0;
    const calls=[],paint=[],states=[],timers=new Map();
    const draft=create({pointId:7, initial:empty(),
        request:async(method,body) => {
            calls.push({method,body});
            if (handler) return handler(method,body);
            if (method === "POST") remote=data({...remote.fields,...body.fields},body.expected_revision+1);
            return structuredClone(remote);
        },
        apply:patch => paint.push(patch),notify:state=>states.push(state),
        schedule:(fn,ms)=>{timers.set(++next,{fn,ms});return next;},cancel:id=>timers.delete(id),
    });
    return {draft,calls,paint,states,timers,
        set remote(value){remote=value;},get remote(){return remote;},
        set handler(value){handler=value;},
        edit:patch=>draft.edit({...draft.values(),...patch}),
        async fire(){const entry=timers.entries().next().value;if(entry){timers.delete(entry[0]);entry[1].fn();await tick();}},
    };
}
test("initial GET hydrates all supported fields without a POST",async()=>{
    const f=fixture();f.remote=data({inspection_address:"Rua A",pgts:["Escola"]},3);
    await f.draft.load();
    assert.equal(f.draft.values().inspection_address,"Rua A");
    assert.deepEqual(f.draft.values().pgts,["Escola"]);
    assert.equal(f.draft.snapshot().revision,3);
    assert.equal(f.calls.length,1);assert.equal(f.timers.size,0);
});
test("edits made during initial GET survive late hydration",async()=>{
    const f=fixture(),pending=deferred();f.handler=()=>pending.promise;
    const load=f.draft.load();f.edit({study_reason:"Local"});
    pending.resolve(data({study_reason:"Remoto",inspection_address:"Rua A"},2));await load;
    assert.equal(f.draft.values().study_reason,"Local");
    assert.equal(f.draft.values().inspection_address,"Rua A");
    assert.equal(f.paint[0].study_reason,undefined);
    f.handler=null;await f.fire();
    assert.deepEqual(f.calls[1].body,{expected_revision:2,fields:{study_reason:"Local"}});
});
test("two-second debounce coalesces edits and posts changed fields only",async()=>{
    const f=fixture();await f.draft.load();
    f.edit({study_reason:"a"});f.edit({study_reason:"ab",inspection_date:"2026-10-27"});
    assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,2000);
    assert.equal(f.calls.length,1);await f.fire();
    assert.deepEqual(f.calls[1].body,{expected_revision:0,fields:{study_reason:"ab",inspection_date:"2026-10-27"}});
    assert.equal(f.draft.hasPending(),false);assert.equal(f.draft.snapshot().state,"saved");
});
test("editing during POST is not repainted and is saved once with next revision",async()=>{
    const f=fixture();await f.draft.load();const pending=deferred();
    f.handler=()=>pending.promise;f.edit({study_reason:"Primeiro"});await f.fire();
    f.edit({study_reason:"Segundo"});await f.fire();assert.equal(f.calls.length,2);
    pending.resolve(data({study_reason:"Primeiro"},1));await tick();
    assert.equal(f.draft.values().study_reason,"Segundo");assert.equal(f.paint.length,1);
    f.handler=null;await f.fire();
    assert.deepEqual(f.calls[2].body,{expected_revision:1,fields:{study_reason:"Segundo"}});
    assert.equal(f.draft.hasPending(),false);
});
test("reverting to baseline during POST still requires saving the reversal",async()=>{
    const f=fixture();await f.draft.load();const pending=deferred();
    f.handler=()=>pending.promise;f.edit({study_reason:"Primeiro"});await f.fire();f.edit({study_reason:""});
    assert.equal(f.draft.hasPending(),true);
    pending.resolve(data({study_reason:"Primeiro"},1));await tick();f.handler=null;await f.fire();
    assert.deepEqual(f.calls[2].body,{expected_revision:1,fields:{study_reason:""}});
});
test("close invalidates late GET and a different waypoint cannot populate the form",async()=>{
    const f=fixture(),pending=deferred();f.handler=()=>pending.promise;
    const load=f.draft.load();f.draft.destroy();pending.resolve(data({study_reason:"Antigo"}));await load;
    assert.equal(f.paint.length,0);assert.equal(f.timers.size,0);
    const other=fixture();other.remote=data({study_reason:"Outro"},1,8);await other.draft.load();
    assert.equal(other.paint.length,0);assert.equal(other.draft.snapshot().state,"error");
});
test("late POST after stop cannot acknowledge or overwrite local edits",async()=>{
    const f=fixture();await f.draft.load();const pending=deferred();f.handler=()=>pending.promise;
    f.edit({study_reason:"Local"});await f.fire();f.draft.stop();
    pending.resolve(data({study_reason:"Antigo"},1));await tick();
    assert.equal(f.draft.snapshot().revision,0);assert.equal(f.draft.values().study_reason,"Local");
    assert.equal(f.draft.snapshot().state,"stopped");assert.equal(f.timers.size,0);
});
test("HTTP 409 stops writes and preserves local values without rebasing",async()=>{
    const f=fixture();await f.draft.load();
    f.handler=async()=>{throw Object.assign(new Error("Conflito"),{code:"draft_revision_conflict",status:409});};
    f.edit({study_reason:"Local"});await f.fire();
    assert.equal(f.draft.snapshot().state,"conflict");assert.equal(f.draft.hasPending(),true);
    f.edit({study_reason:"Continua local"});await f.fire();await f.draft.flush();await f.draft.retry();
    assert.equal(f.calls.length,2);assert.equal(f.draft.values().study_reason,"Continua local");
});
test("network failure keeps edits; retry GET precedes retry POST",async()=>{
    const f=fixture();await f.draft.load();
    f.handler=async()=>{throw Object.assign(new Error("offline"),{code:"network"});};
    f.edit({study_reason:"Local"});await f.fire();
    assert.equal(f.draft.snapshot().state,"error");assert.equal(f.timers.size,0);
    f.handler=null;await f.draft.retry();await f.fire();
    assert.deepEqual(f.calls.map(call=>call.method),["GET","POST","GET","POST"]);
    assert.equal(f.draft.hasPending(),false);
});
test("lost POST acknowledgement is reconciled without a duplicate write",async()=>{
    const f=fixture();await f.draft.load();
    f.handler=async(_method,body)=>{
        f.remote=data(body.fields,1);throw Object.assign(new Error("offline"),{code:"network"});
    };
    f.edit({study_reason:"Confirmado no servidor"});await f.fire();f.handler=null;
    await f.draft.retry();await f.fire();
    assert.deepEqual(f.calls.map(call=>call.method),["GET","POST","GET"]);
    assert.equal(f.draft.hasPending(),false);assert.equal(f.draft.snapshot().revision,1);
});
test("recovery detects another writer instead of silently overwriting remote data",async()=>{
    const f=fixture();await f.draft.load();
    f.handler=async()=>{throw Object.assign(new Error("offline"),{code:"network"});};
    f.edit({study_reason:"Local"});await f.fire();f.handler=null;
    f.remote=data({study_reason:"Outro autor"},1);await f.draft.retry();
    assert.equal(f.draft.snapshot().state,"conflict");assert.equal(f.draft.values().study_reason,"Local");
    assert.equal(f.remote.fields.study_reason,"Outro autor");
});
for (const code of ["reservation_expired","reservation_inactive","reservation_generation_stale"]) {
    test(code+" permanently stops autosave and keeps unsaved text",async()=>{
        const f=fixture();await f.draft.load();
        f.handler=async()=>{throw Object.assign(new Error(code),{code,status:409});};
        f.edit({study_reason:"Local"});await f.fire();
        f.draft.pause();f.draft.resume();await f.draft.retry();await f.draft.flush();
        assert.equal(f.calls.length,2);assert.equal(f.draft.snapshot().stopped,true);
        assert.equal(f.draft.values().study_reason,"Local");assert.equal(f.draft.hasPending(),true);
    });
}
test("temporary suspension adds no polling and resumes only the pending debounce",async()=>{
    const f=fixture();await f.draft.load();f.edit({study_reason:"Local"});f.draft.pause();await f.fire();
    assert.equal(f.calls.length,1);f.draft.resume();await f.fire();assert.equal(f.calls.length,2);
});
test("unchanged fields, photos and session payload do not produce writes",async()=>{
    const f=fixture();await f.draft.load();
    f.edit({photos:["not persisted"],analysis_id:"not persisted",pgts:["  "]});
    await f.fire();await f.draft.flush();assert.equal(f.calls.length,1);
    assert.equal(Object.hasOwn(f.draft.values(),"photos"),false);
    assert.equal(Object.hasOwn(f.draft.values(),"analysis_id"),false);
});
test("PGT edits, deletion and canonical whitespace persist without duplicate saves",async()=>{
    const f=fixture();f.remote=data({pgts:["Escola"]},1);await f.draft.load();
    f.edit({pgts:[" Hospital ",""]});await f.fire();
    assert.deepEqual(f.calls[1].body.fields,{pgts:["Hospital"]});
    f.edit({pgts:["Hospital",""]});await f.fire();assert.equal(f.calls.length,2);
    f.edit({pgts:[]});await f.fire();assert.deepEqual(f.calls[2].body.fields,{pgts:[]});
});
test("flush before DOCX drains pending edits without duplicate writes",async()=>{
    const f=fixture();await f.draft.load();f.edit({study_reason:"Documento"});
    await f.draft.flush();await f.draft.flush();await f.fire();
    assert.equal(f.calls.length,2);assert.equal(f.draft.hasPending(),false);
});


function formPage() {
    const nodes=Object.fromEntries(fields.filter(name=>name!=="pgts").map(name=>[name,{value:""}]));
    const status={textContent:""},retry={hidden:true,addEventListener(type,fn){this[type]=fn;}};
    const rows={children:[],replaceChildren(){this.children=[];},append(node){this.children.push(node);}};
    const form={dataset:{draftUrl:"/signaling/points/7/report-draft/"},events:{},
        querySelector(selector){
            if(selector==="[data-draft-status]")return status;
            if(selector==="[data-draft-retry]")return retry;
            if(selector==="[data-pgt-rows]")return rows;
            return nodes[selector.match(/name="([^"]+)"/)?.[1]] || null;
        },
        querySelectorAll(selector){return selector==='[name="pgts"]'?rows.children.map(row=>row.children[0]):[];},
        addEventListener(type,fn){this.events[type]=fn;},
    };
    const doc={defaultView:{},querySelector:()=>form,
        createElement:()=>({dataset:{},children:[],append(...nodes){this.children.push(...nodes);},setAttribute(){}}),
    };
    return {doc,form,nodes,rows,status,retry};
}
test("iframe adapter hydrates PGT rows, captures programmatic changes and posts through manager",async t=>{
    const timers=new Map();let seq=0;
    t.mock.method(global,"setTimeout",fn=>{timers.set(++seq,fn);return seq;});
    t.mock.method(global,"clearTimeout",id=>timers.delete(id));
    let remote=data({pgts:["Escola"],inspection_address:"Rua A"},1);const calls=[];
    const manager={canOperate:()=>true,resume:async()=>{},perform:async(id,url,options)=>{
        calls.push({id,url,options});
        if(options.method==="POST"){
            const body=JSON.parse(options.body);remote=data({...remote.fields,...body.fields},body.expected_revision+1);
        }
        return remote;
    }};
    const page=formPage(),mounted=mount({manager,pointId:7,doc:page.doc});await tick();
    assert.equal(page.nodes.inspection_address.value,"Rua A");
    assert.equal(page.rows.children[0].children[0].value,"Escola");
    page.rows.children[0].children[0].value="Hospital";page.doc.defaultView.waypointDraftChanged();
    await mounted.flush();
    assert.equal(calls.length,2);assert.deepEqual(JSON.parse(calls[1].options.body),{
        expected_revision:1,fields:{pgts:["Hospital"]}});
    assert.equal(calls[1].url,"/signaling/points/7/report-draft/");
    assert.match(page.status.textContent,/salvo/);
    const replacement=formPage();mounted.attach(replacement.doc);
    assert.equal(page.doc.defaultView.waypointDraftChanged,undefined);
    assert.equal(replacement.rows.children[0].children[0].value,"Hospital");
    assert.equal(replacement.nodes.inspection_address.value,"Rua A");
    page.nodes.inspection_address.value="Documento obsoleto";page.form.events.input();
    assert.equal(mounted.hasPending(),false);assert.equal(calls.length,2);
    mounted.destroy();assert.equal(timers.size,0);
});


test("initial form suspended before GET recovers on confirmed reservation",async()=>{
    let allowed=false,calls=0;
    const draft=create({pointId:7,initial:empty(),canSave:()=>allowed,
        request:async()=>{calls++;return data({study_reason:"Recuperado"},1);}});
    await draft.load();assert.equal(calls,0);
    allowed=true;draft.resume();await tick();
    assert.equal(calls,1);assert.equal(draft.values().study_reason,"Recuperado");
    draft.destroy();
});


test("lost acknowledgement plus an in-flight reversal must not discard the local reversal",async()=>{
    const f=fixture();await f.draft.load();const pending=deferred();f.handler=()=>pending.promise;
    f.edit({study_reason:"Enviado"});await f.fire();f.edit({study_reason:""});
    f.remote=data({study_reason:"Enviado"},1);
    pending.reject(Object.assign(new Error("offline"),{code:"network"}));await tick();
    assert.equal(f.draft.hasPending(),true);
    f.handler=null;await f.draft.retry();assert.equal(f.draft.values().study_reason,"");
    await f.fire();assert.deepEqual(f.calls.at(-1).body,{expected_revision:1,fields:{study_reason:""}});
    assert.equal(f.remote.fields.study_reason,"");assert.equal(f.draft.hasPending(),false);
});


test("technical analysis loads and autosaves alone with expected revision",async()=>{
    const f=fixture();f.remote=data({technical_analysis:"Análise anterior"},3);await f.draft.load();
    assert.equal(f.draft.values().technical_analysis,"Análise anterior");
    f.edit({technical_analysis:"Análise técnica.\nConsiderações finais."});await f.fire();
    assert.deepEqual(f.calls[1].body,{expected_revision:3,fields:{technical_analysis:"Análise técnica.\nConsiderações finais."}});
    assert.equal(f.draft.snapshot().revision,4);assert.equal(f.draft.hasPending(),false);
});
test("technical analysis conflict keeps local multiline text without retry writes",async()=>{
    const f=fixture();await f.draft.load();
    f.handler=async()=>{throw Object.assign(new Error("Conflito"),{code:"draft_revision_conflict",status:409});};
    f.edit({technical_analysis:"Texto local\nSegunda linha"});await f.fire();await f.draft.flush();
    assert.equal(f.draft.snapshot().state,"conflict");
    assert.equal(f.draft.values().technical_analysis,"Texto local\nSegunda linha");
    assert.equal(f.calls.length,2);
});
test("technical analysis validation error retains text until corrected",async()=>{
    const f=fixture();await f.draft.load();
    f.handler=async()=>{throw Object.assign(new Error("Limite excedido"),{code:"invalid_draft_fields",status:400});};
    f.edit({technical_analysis:"x".repeat(10001)});await f.fire();
    assert.equal(f.draft.snapshot().state,"error");assert.equal(f.draft.values().technical_analysis.length,10001);
    f.handler=null;f.edit({technical_analysis:"Corrigido"});await f.fire();await f.fire();
    assert.equal(f.remote.fields.technical_analysis,"Corrigido");assert.equal(f.draft.hasPending(),false);
});
