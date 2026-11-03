"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const {createClient,mount,mountRecovery}=require("./report_deletion.js");
const reportId="11111111-1111-4111-8111-111111111111",op="22222222-2222-4222-8222-222222222222",number="RTSV-2026-0001";
function storage(){const map=new Map();return {get length(){return map.size;},key:i=>[...map.keys()][i],getItem:key=>map.get(key)||null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)};}
function response(status=200,extra={}){return {status,headers:{get:()=>"application/json"},json:async()=>({success:status===200,report_deleted:true,operation_id:op,number,cleanup_state:status===202?"FAILED":"COMPLETE",...extra})};}
function fixture(shared=storage()){
    const calls=[],moves=[];let ids=0,answer=async()=>response();
    const env={localStorage:shared,crypto:{randomUUID:()=>{ids++;return op;}},location:{href:"http://localhost/signaling/reports/",assign:url=>moves.push(url),reload:()=>moves.push("reload")},
        csrf:()=>"csrf-local",fetch:async(url,options)=>{calls.push({url,options});return answer();}};
    const make=()=>createClient({userId:"7",reportId,number,url:`/signaling/reports/${reportId}/delete/`,environment:env});
    return {env,make,calls,moves,shared,get ids(){return ids;},set answer(value){answer=value;}};
}
test("no request or UUID on load; exact confirmation, CSRF and same-origin POST",async()=>{
    const f=fixture(),client=f.make();assert.equal(f.ids,0);assert.equal(f.calls.length,0);
    await client.submit(number+" ");assert.equal(f.calls.length,0);assert.equal(f.ids,0);
    assert.equal((await client.submit(number)).kind,"complete");assert.equal(f.ids,1);
    const {options}=f.calls[0];assert.equal(options.method,"POST");assert.equal(options.credentials,"same-origin");
    assert.equal(options.headers["X-CSRFToken"],"csrf-local");
    assert.deepEqual(JSON.parse(options.body),{operation_id:op,confirm_number:number});
    assert.equal(f.shared.length,0);
});
test("double click shares one request and one operation",async()=>{
    const f=fixture();let release;f.answer=()=>new Promise(resolve=>release=resolve);
    const client=f.make(),one=client.submit(number),two=client.submit(number);assert.equal(one,two);
    await Promise.resolve();assert.equal(f.calls.length,1);assert.equal(f.ids,1);
    release(response());await one;
});
test("202 preserves durable operation and explicit recovery uses the same UUID",async()=>{
    const f=fixture(),client=f.make();f.answer=async()=>response(202);
    assert.equal((await client.submit(number)).kind,"pending");assert.equal(f.shared.length,1);
    f.answer=async()=>response();assert.equal((await client.recover()).kind,"complete");
    assert.equal(f.ids,1);assert.equal(f.calls.length,2);
    assert.equal(JSON.parse(f.calls[1].options.body).operation_id,op);
});
for(const [status,kind] of [[403,"forbidden"],[401,"forbidden"],[404,"missing"],[409,"conflict"],[400,"invalid"],[503,"uncertain"]])test(`HTTP ${status} is ${kind} and never integral success`,async()=>{
    const f=fixture(),client=f.make();f.answer=async()=>response(status,{code:"internal-secret"});
    const state=await client.submit(number);assert.equal(state.kind,kind);assert.equal(f.shared.length,1);
    assert.doesNotMatch(JSON.stringify(state),/internal-secret/);
});
test("network timeout, reload and recovery retain intent without auto requests",async()=>{
    const f=fixture();f.answer=async()=>{throw new Error("network-secret");};
    assert.equal((await f.make().submit(number)).kind,"uncertain");
    const restored=f.make();assert.equal(f.calls.length,1);assert.equal(f.ids,1);
    f.answer=async()=>response();await restored.recover();
    assert.equal(JSON.parse(f.calls[1].options.body).operation_id,op);assert.equal(f.ids,1);
});
test("malformed success and HTML errors are ambiguous without trusting response bodies",async()=>{
    const f=fixture();f.answer=async()=>response(200,{number:"wrong"});
    assert.equal((await f.make().submit(number)).kind,"uncertain");
    f.answer=async()=>({status:500,headers:{get:()=>"text/html"},json:()=>{throw Error("must not parse HTML");}});
    assert.equal((await f.make().recover()).kind,"uncertain");
});
test("storage failure blocks POST; invalid journal is never overwritten",async()=>{
    const f=fixture();f.shared.setItem=()=>{throw Error("blocked");};
    assert.equal((await f.make().submit(number)).kind,"journal_error");assert.equal(f.calls.length,0);
    const g=fixture();g.shared.setItem(`rtsv.deletion.v1.u7.${reportId}`,"broken-json");
    assert.equal((await g.make().submit(number)).kind,"journal_error");assert.equal(g.calls.length,0);
});
test("secure random fallback generates UUID v4 without relying on randomUUID",async()=>{
    const f=fixture();f.env.crypto={getRandomValues:array=>array.fill(42)};
    await f.make().submit(number);
    assert.match(JSON.parse(f.calls[0].options.body).operation_id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
function node(){const events={};return {events,hidden:false,disabled:false,value:"",style:{},children:[],dataset:{},textContent:"",append(...items){this.children.push(...items);},setAttribute(){},focus(){this.focused=true;},addEventListener:(name,fn)=>events[name]=fn};}
function ui(){
    const f=fixture(),nodes=Object.fromEntries(["dialog","form","open","number","status","confirm","cancel","recover","library"].map(key=>[key,node()]));
    nodes.dialog.showModal=()=>{nodes.dialog.open=true;};nodes.dialog.close=()=>{nodes.dialog.open=false;};
    const root={dataset:{userId:"7",reportId,number,deleteUrl:`/signaling/reports/${reportId}/delete/`,libraryUrl:"/signaling/reports/?year=2026"},
        querySelector:selector=>selector.includes("csrfmiddlewaretoken")?{value:"csrf-local"}:nodes[selector.match(/data-delete-(.*)\]/)[1]]};
    f.env.document={body:{style:{overflow:"auto"}},createElement:()=>node()};
    mount(root,f.env);return {...f,nodes,root,base:f};
}
const tick=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
test("modal open/cancel/Escape do not create intent; incorrect number remains disabled",()=>{
    const f=ui();f.nodes.open.events.click();assert.equal(f.nodes.dialog.open,true);
    assert.equal(f.nodes.confirm.disabled,true);f.nodes.number.value=number+" ";f.nodes.number.events.input();assert.equal(f.nodes.confirm.disabled,true);
    f.nodes.number.value=number;f.nodes.number.events.input();assert.equal(f.nodes.confirm.disabled,false);
    f.nodes.dialog.events.cancel({preventDefault(){}});assert.equal(f.nodes.dialog.open,false);
    assert.equal(f.nodes.open.focused,true);assert.equal(f.calls.length,0);assert.equal(f.base.ids,0);
    assert.equal(f.env.document.body.style.overflow,"auto");
});
test("confirmed completion returns to filtered library; pending cleanup never redirects",async()=>{
    const f=ui();f.nodes.open.events.click();f.nodes.number.value=number;f.nodes.number.events.input();
    f.base.answer=async()=>response(202);f.nodes.form.events.submit({preventDefault(){}});await tick();
    assert.equal(f.moves.length,0);assert.match(f.nodes.status.textContent,/limpeza.*pendente/);
    assert.equal(f.nodes.confirm.hidden,true);assert.equal(f.nodes.recover.hidden,false);
    f.base.answer=async()=>response();f.nodes.recover.events.click();await tick();
    assert.deepEqual(f.moves,["/signaling/reports/?year=2026"]);
    assert.equal(JSON.parse(f.calls[1].options.body).operation_id,op);
});
test("native modal cannot close during request; no second POST",async()=>{
    const f=ui();let done;f.base.answer=()=>new Promise(resolve=>done=resolve);
    f.nodes.open.events.click();f.nodes.number.value=number;f.nodes.number.events.input();
    f.nodes.form.events.submit({preventDefault(){}});await tick();
    f.nodes.cancel.events.click();assert.equal(f.nodes.dialog.open,true);assert.equal(f.nodes.cancel.disabled,true);
    f.nodes.form.events.submit({preventDefault(){}});assert.equal(f.calls.length,1);
    done(response());await tick();
});
test("library recovery restores only current user's intents with no automatic POST",async()=>{
    const f=fixture();f.answer=async()=>response(202);await f.make().submit(number);
    f.shared.setItem(`rtsv.deletion.v1.u999.${reportId}`,"other-user-secret");
    f.env.document={createElement:()=>node()};const list=node();
    const root={dataset:{userId:"7",libraryUrl:"/signaling/reports/?year=2026",urlTemplate:"/signaling/reports/00000000-0000-0000-0000-000000000000/delete/"},querySelector:selector=>selector.includes("csrfmiddlewaretoken")?{value:"csrf-local"}:list};
    mountRecovery(root,f.env);assert.equal(root.hidden,false);assert.equal(list.children.length,1);assert.equal(f.calls.length,1);
    f.answer=async()=>response();await list.children[0].children[1].events.click();
    assert.equal(f.calls.length,2);assert.deepEqual(f.moves,["/signaling/reports/?year=2026"]);
    assert.equal(JSON.parse(f.calls[1].options.body).operation_id,op);
    assert.doesNotMatch(list.children[0].children[0].textContent,/secret/);
});

for(const [status,retry] of [[403,false],[404,false],[409,true],[503,true]])test(`modal HTTP ${status} shows only applicable recovery action`,async()=>{
    const f=ui();f.base.answer=async()=>response(status);
    f.nodes.open.events.click();f.nodes.number.value=number;f.nodes.number.events.input();
    f.nodes.form.events.submit({preventDefault(){}});await tick();
    assert.equal(f.nodes.confirm.hidden,true);assert.equal(f.nodes.recover.hidden,!retry);
    assert.equal(f.moves.length,0);assert.equal(f.base.ids,1);
});
test("cancel and reopen pending cleanup never starts another intention or sends a request",async()=>{
    const f=ui();f.base.answer=async()=>response(202);
    f.nodes.open.events.click();f.nodes.number.value=number;f.nodes.number.events.input();
    f.nodes.form.events.submit({preventDefault(){}});await tick();
    f.nodes.cancel.events.click();f.nodes.open.events.click();
    assert.equal(f.calls.length,1);assert.equal(f.base.ids,1);assert.equal(f.nodes.confirm.hidden,true);
});
test("unavailable browser storage and unsafe conflict never offer a new intent",async()=>{
    const f=fixture();Object.defineProperty(f.env,"localStorage",{get(){throw Error("denied");}});
    assert.equal((await f.make().submit(number)).kind,"journal_error");assert.equal(f.calls.length,0);
    const g=fixture();g.answer=async()=>response(409,{code:"deletion_operation_conflict"});
    const state=await g.make().submit(number);assert.equal(state.recoverable,false);assert.equal(g.ids,1);
});
