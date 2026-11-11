"use strict";
const test = require("node:test"), assert = require("node:assert/strict");
const {webcrypto} = require("node:crypto");
const {create} = require("./report_publication_flow.js");
const {evaluate} = require("./report_publication_preview.js");
const attemptId="11111111-1111-4111-8111-111111111111",reportId="22222222-2222-4222-8222-222222222222";
const desc=state=>({success:state==="FINALIZED",state,attempt_id:attemptId,report_id:reportId,number:"RTSV-2026-0001",version:1});
const reply=(data,status=200)=>({status,ok:status<400,json:async()=>data});
const deferred=()=>{let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve};};
function shared(){const data=new Map(),held=new Set();return {
    data,storage:{getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value),removeItem:key=>data.delete(key)},
    locks:{async request(name,options,callback){if(held.has(name))return callback(null);held.add(name);try{return await callback({name});}finally{held.delete(name);}}}};}
function fixture(common=shared()){
    let revision=3,ready=true,reserved=true,enabled=true,flush=true,files=[],respond=()=>reply(desc("FINALIZED"),201),status=()=>reply(desc("FINALIZED"));
    const calls=[],gets=[];
    const manager={canOperate:()=>reserved,perform:async(id,url,init,consume)=>{assert.equal(common.data.size,1);calls.push({url,init});return consume(await respond());}};
    const draft={flush:async()=>flush};
    const options={storage:common.storage,locks:common.locks,crypto:webcrypto,userId:"7",pointId:23,draft,manager,
        url:"/signaling/points/23/report-finalizations/?analysis=synthetic&year=2026",
        attemptUrl:(id,retry)=>`/signaling/report-finalizations/${id}/${retry?"retry/":""}`,
        readiness:()=>({ready:ready&&reserved&&enabled,revision}),photos:()=>files,
        fetch:async(url,init)=>{gets.push({url,init});return status();}};
    const flow=create(options);
    return {flow,common,calls,gets,options,set ready(value){ready=value;},set reserved(value){reserved=value;},
        set enabled(value){enabled=value;},set flush(value){flush=value;},set revision(value){revision=value;},
        set files(value){files=value;},set respond(value){respond=value;},set status(value){status=value;}};
}
test("only explicit confirm creates intent; successful publication remains stable across repeat/reload",async()=>{
    const f=fixture();assert.equal(f.calls.length,0);assert.equal(f.common.data.size,0);
    const result=await f.flow.publish();assert.equal(result.kind,"published");
    assert.equal(result.attempt.report_id,reportId);await f.flow.publish();assert.equal(f.calls.length,1);
    const reloaded=fixture(f.common);assert.equal(reloaded.flow.snapshot().record.last.kind,"published");
    await reloaded.flow.publish();assert.equal(reloaded.calls.length,0);
    await reloaded.flow.recover();assert.equal(reloaded.gets.length,1);assert.equal(reloaded.calls.length,0);
});
test("double click shares promise and a second tab cannot create another intent",async()=>{
    const common=shared(),a=fixture(common),b=fixture(common),gate=deferred();
    a.respond=()=>gate.promise;const one=a.flow.publish(),two=a.flow.publish();assert.equal(one,two);
    while(a.calls.length===0)await new Promise(r=>setImmediate(r));
    assert.equal((await b.flow.publish()).code,"other_tab_busy");assert.equal(b.calls.length,0);
    gate.resolve(reply(desc("FINALIZED"),201));await one;
    b.flow.refresh();await b.flow.publish();assert.equal(b.calls.length,0);
    await b.flow.recover();assert.equal(b.gets.length,1);
});
test("autosave failure, missing revision, lost reserve and disabled flag send no POST",async()=>{
    for(const field of ["ready","reserved","enabled","flush"]){const f=fixture();f[field]=false;
        assert.equal((await f.flow.publish()).kind,"blocked");assert.equal(f.calls.length,0);assert.equal(f.common.data.size,0);}
});
test("readiness rejects absent revision and invalid photographs",()=>{
    const input={authorized:true,reserved:true,enabled:true,photos:[],draft:{state:"saved",confirmed:false,revision:0}};
    assert.equal(evaluate(input).ready,false);input.draft.confirmed=true;
    input.photos=[{type:"image/gif",size:10}];assert.equal(evaluate(input).ready,false);
});
test("network acknowledgement loss replays the same frozen body and key after reload",async()=>{
    const a=fixture();a.respond=()=>{throw new TypeError("response lost after commit");};
    assert.equal((await a.flow.publish()).kind,"uncertain");const body=a.calls[0].init.body;
    const b=fixture(a.common);assert.equal(b.flow.snapshot().record.key,JSON.parse(body).idempotency_key);
    assert.equal((await b.flow.recover()).kind,"published");assert.equal(b.calls[0].init.body,body);
    assert.equal(a.common.data.size,1);
});
test("202 is processing; status/retry are explicit and retain the same record",async()=>{
    const f=fixture();f.respond=()=>reply(desc("PROCESSING"),202);
    assert.equal((await f.flow.publish()).kind,"processing");assert.equal(f.gets.length,0);
    f.status=()=>reply(desc("PROCESSING"));await f.flow.retry();assert.equal(f.calls.length,1);
    const key=f.flow.snapshot().record.key;
    f.status=()=>reply(desc("FAILED"));f.respond=()=>reply(desc("FINALIZED"));
    assert.equal((await f.flow.retry()).kind,"published");assert.match(f.calls[1].url,/retry\/$/);
    assert.equal(f.calls[1].init.body,"{}");assert.equal(f.flow.snapshot().record.key,key);
});
test("reload requires the same original photographs before replay",async()=>{
    const original=new Blob(["original synthetic bytes"],{type:"image/png"});
    const a=fixture();a.files=[original];a.respond=()=>{throw new TypeError("offline");};await a.flow.publish();
    const b=fixture(a.common);assert.equal((await b.flow.recover()).code,"original_photos_required");assert.equal(b.calls.length,0);
    b.files=[new Blob(["different bytes"],{type:"image/png"})];await b.flow.recover();assert.equal(b.calls.length,0);
    b.files=[original];await b.flow.recover();assert.equal(b.calls.length,1);
    const stored=JSON.stringify([...a.common.data.values()]);assert.doesNotMatch(stored,/original synthetic bytes|X-Waypoint|csrf|session/);
});
test("permission denied and stale revision preserve intent instead of issuing a new key",async()=>{
    for(const [code,status] of [["permission_denied",403],["draft_revision_conflict",409]]){
        const f=fixture();f.respond=()=>reply({success:false,code},status);await f.flow.publish();
        const key=f.flow.snapshot().record.key;await f.flow.publish();assert.equal(f.calls.length,1);
        assert.equal(f.flow.snapshot().record.key,key);const reset=await f.flow.newReport();
        assert.equal(reset.code, code === "permission_denied" ? "unresolved_intent" : undefined);
    }
});
test("without Web Locks or durable storage there is no side effect",async()=>{
    const f=fixture(), noLocks=create({...f.options,locks:null});
    assert.equal((await noLocks.publish()).code,"browser_protection_unavailable");assert.equal(f.calls.length,0);
    const bad=create({...f.options,storage:{getItem:()=>null,setItem:()=>{throw new Error("quota");}}});
    assert.equal((await bad.publish()).code,"journal_unavailable");assert.equal(f.calls.length,0);
});
test("new report needs a separate explicit action after success, never after timeout",async()=>{
    const f=fixture();await f.flow.publish();const key=f.flow.snapshot().record.key;
    await f.flow.newReport();assert.equal(f.calls.length,1);assert.equal(f.common.data.size,0);
    await f.flow.publish();assert.notEqual(f.flow.snapshot().record.key,key);assert.equal(f.calls.length,2);
});
test("status recovery needs no active waypoint reserve",async()=>{
    const f=fixture();f.respond=()=>reply(desc("PROCESSING"),202);await f.flow.publish();
    f.reserved=false;assert.equal((await f.flow.recover()).kind,"published");assert.equal(f.calls.length,1);
});

test("journal corruption or a source change during hashing cannot issue a POST",async()=>{
    const f=fixture();f.common.storage.setItem("rtsv.publication.v1.u7.p23","not json");
    assert.equal((await f.flow.publish()).code,"journal_unavailable");assert.equal(f.calls.length,0);
    const g=fixture();let reads=0;
    const changed=create({...g.options,readiness:()=>({ready:true,revision:++reads<3?3:4})});
    assert.equal((await changed.publish()).code,"source_changed");assert.equal(g.calls.length,0);
});

test("terminal failure is rechecked before preparing a different report; active work blocks reset",async()=>{
    const f=fixture();f.respond=()=>reply({code:"conversion_failed",attempt:desc("FAILED")},503);await f.flow.publish();
    f.status=()=>reply(desc("PROCESSING"));assert.equal((await f.flow.newReport()).code,"unresolved_intent");
    assert.equal(f.common.data.size,1);assert.equal(f.calls.length,1);
    f.status=()=>reply(desc("FAILED"));await f.flow.recover();
    assert.equal(f.flow.snapshot().canStartNew,true);await f.flow.newReport();
    assert.equal(f.common.data.size,0);assert.equal(f.calls.length,1);
});

test("a first-send validation rejection may be replaced explicitly, but not a bad replay after uncertainty",async()=>{
    const f=fixture();f.respond=()=>reply({code:"invalid_finalization_payload"},400);await f.flow.publish();
    assert.equal(f.flow.snapshot().canStartNew,true);await f.flow.newReport();assert.equal(f.common.data.size,0);
    const g=fixture();g.respond=()=>{throw new TypeError("lost");};await g.flow.publish();
    g.respond=()=>reply({code:"invalid_finalization_payload"},400);await g.flow.recover();
    assert.equal(g.flow.snapshot().canStartNew,false);assert.equal((await g.flow.newReport()).code,"unresolved_intent");
});

test("unreadable photos or storage that does not retain writes blocks publication",async()=>{
    const f=fixture();f.files=[{size:12,type:"image/png",arrayBuffer:async()=>{throw new Error("file removed");}}];
    assert.equal((await f.flow.publish()).code,"original_photos_unavailable");assert.equal(f.calls.length,0);
    const g=fixture();const flow=create({...g.options,storage:{getItem:()=>null,setItem(){}}});
    assert.equal((await flow.publish()).code,"journal_unavailable");assert.equal(g.calls.length,0);
});


test("confirmed independent report atomically replaces previous journal without deleting it",async()=>{
    const f=fixture();await f.flow.publish();const previous=f.flow.snapshot().record.key;
    const old=JSON.parse([...f.common.data.values()][0]);
    f.common.storage.removeItem=()=>{throw Error("replacement must not clear journal");};
    const original=f.common.storage.setItem;
    f.common.storage.setItem=(name,value)=>{assert.equal(f.common.data.size,1);return original(name,value);};
    f.respond=()=>reply({...desc("FINALIZED"),attempt_id:"33333333-3333-4333-8333-333333333333",report_id:"44444444-4444-4444-8444-444444444444",number:"RTSV-2026-0002"},201);
    assert.equal((await f.flow.publishAnother(previous)).kind,"published");
    assert.notEqual(f.flow.snapshot().record.key,previous);
    assert.equal(f.flow.snapshot().record.last.attempt.number,"RTSV-2026-0002");
    assert.equal(f.gets.length,1);assert.equal(f.calls.length,2);
    assert.equal(f.flow.snapshot().record.schema,old.schema);
    assert.deepEqual(Object.keys(f.flow.snapshot().record).sort(),Object.keys(old).sort());
});
test("replacement confirmation is bound to old key across simultaneous and sequential tabs",async()=>{
    const a=fixture();await a.flow.publish();const previous=a.flow.snapshot().record.key;
    const b=fixture(a.common),gate=deferred();a.respond=()=>gate.promise;
    const first=a.flow.publishAnother(previous),duplicate=a.flow.publishAnother(previous);assert.equal(first,duplicate);
    while(a.calls.length<2)await new Promise(r=>setImmediate(r));
    assert.equal((await b.flow.publishAnother(previous)).code,"other_tab_busy");
    gate.resolve(reply(desc("FINALIZED"),201));await first;
    await b.flow.publishAnother(previous);assert.equal(b.calls.length,0);
    assert.equal(a.calls.length,2);assert.notEqual(a.flow.snapshot().record.key,previous);
});
test("failed replacement preconditions never discard previous key",async()=>{
    for(const setting of ["ready","reserved","enabled","flush"]){
        const f=fixture();await f.flow.publish();const old=f.flow.snapshot().record.key;f[setting]=false;
        assert.equal((await f.flow.publishAnother(old)).kind,"blocked");
        assert.equal(f.flow.snapshot().record.key,old);assert.equal(f.calls.length,1);
    }
});
test("journal stays settled during hashing and revision changes prevent replacement",async()=>{
    const f=fixture();await f.flow.publish();const old=f.flow.snapshot().record.key;
    const gate=deferred();let reading=false;
    f.files=[{size:3,type:"image/png",arrayBuffer:async()=>{reading=true;return gate.promise;}}];
    const work=f.flow.publishAnother(old);while(!reading)await new Promise(r=>setImmediate(r));
    assert.equal(JSON.parse([...f.common.data.values()][0]).key,old);
    f.revision=4;gate.resolve(new Uint8Array([1,2,3]).buffer);
    assert.equal((await work).code,"source_changed");
    assert.equal(f.flow.snapshot().record.key,old);assert.equal(f.calls.length,1);
});
test("independent publication may select different photos; recovery still uses its frozen key",async()=>{
    const f=fixture();await f.flow.publish();const old=f.flow.snapshot().record.key;
    f.files=[new Blob(["new synthetic photo"],{type:"image/png"})];
    f.respond=()=>{throw new TypeError("timeout after commit");};
    assert.equal((await f.flow.publishAnother(old)).kind,"uncertain");
    const newKey=f.flow.snapshot().record.key;assert.notEqual(newKey,old);
    const reloaded=fixture(f.common);assert.equal(reloaded.calls.length,0);
    assert.equal((await reloaded.flow.publishAnother(newKey)).code,"unresolved_intent");
    assert.equal(reloaded.flow.snapshot().record.key,newKey);
    reloaded.files=[new Blob(["new synthetic photo"],{type:"image/png"})];
    await reloaded.flow.recover();assert.equal(reloaded.flow.snapshot().record.key,newKey);
    assert.equal(reloaded.calls.length,1);
});
for(const [status,code] of [[404,"finalization_not_found"],[410,"report_deleted"],[403,"permission_denied"]])test(`replacement recheck ${status} preserves journal and blocks new key`,async()=>{
    const f=fixture();await f.flow.publish();const key=f.flow.snapshot().record.key;
    f.status=()=>reply({code},status);
    assert.equal((await f.flow.publishAnother(key)).code,"unresolved_intent");
    assert.equal(f.flow.snapshot().record.key,key);assert.equal(f.flow.snapshot().canStartNew,false);
    assert.equal(f.flow.snapshot().record.last.code,code);assert.equal(f.calls.length,1);
});
test("202 or newly discovered success cannot be turned automatically into another publication",async()=>{
    const f=fixture();await f.flow.publish();const key=f.flow.snapshot().record.key;
    f.status=()=>reply(desc("PROCESSING"),202);
    assert.equal((await f.flow.publishAnother(key)).code,"unresolved_intent");assert.equal(f.calls.length,1);
    const g=fixture();g.respond=()=>reply({code:"conversion_failed",attempt:desc("FAILED")},503);
    await g.flow.publish();const old=g.flow.snapshot().record.key;
    assert.equal((await g.flow.publishAnother(old)).kind,"published"); // status discovers successful old attempt
    assert.equal(g.calls.length,1);assert.equal(g.flow.snapshot().record.key,old);
});

test("replacement journal cannot be overwritten if storage fails after the previous status check",async()=>{
    const f=fixture();await f.flow.publish();const old=f.flow.snapshot().record.key;
    const original=f.common.storage.setItem;let writes=0;
    f.common.storage.setItem=(name,value)=>{if(++writes===2)throw Error("quota");original(name,value);};
    assert.equal((await f.flow.publishAnother(old)).code,"journal_unavailable");
    assert.equal(JSON.parse([...f.common.data.values()][0]).key,old);assert.equal(f.calls.length,1);
});
test("eligible definitive failed attempt is revalidated before independent publication",async()=>{
    const f=fixture();f.respond=()=>reply({code:"report_source_changed",attempt:{...desc("FAILED"),error_code:"report_source_changed"}},409);
    await f.flow.publish();const old=f.flow.snapshot().record.key;
    f.status=()=>reply({...desc("FAILED"),error_code:"report_source_changed"},409);
    f.respond=()=>reply({...desc("FINALIZED"),attempt_id:"33333333-3333-4333-8333-333333333333",number:"RTSV-2026-0002"},201);
    assert.equal((await f.flow.publishAnother(old)).kind,"published");
    assert.notEqual(f.flow.snapshot().record.key,old);assert.equal(f.calls.length,2);
});
