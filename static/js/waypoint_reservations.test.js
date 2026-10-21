 "use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {create} = require("./waypoint_reservations.js");
const deferred = () => { let resolve,reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; };
const tick = async () => { for(let n=0;n<12;n++) await Promise.resolve(); };
function server() {
    let held = null, generation = 0, failRenew = false, failRelease = false;
    const calls = [];
    const reply = (data,status=200) => ({ok:status<400,status,json:async()=>data});
    async function fetch(url,options={}) {
        calls.push({url,options});
        const headers = options.headers || {};
        const matches = held && headers["X-Waypoint-Token"]===held.token &&
            headers["X-Waypoint-Interaction"]===held.interaction_id &&
            +headers["X-Waypoint-Generation"]===held.generation;
        if (url.endsWith("/acquire/")) {
            if (held) return reply({success:false,code:"reservation_occupied"},409);
            held = {...JSON.parse(options.body),generation:++generation,token:"secret-"+generation,expires_at:"server-time"};
            return reply({success:true,...held},201);
        }
        if (url.endsWith("/renew/")) {
            if(failRenew) throw new TypeError("offline");
            if(!matches) return reply({success:false,code:"reservation_generation_stale"},409);
            return reply({success:true,generation:held.generation,expires_at:"server-time"});
        }
        if (url.endsWith("/release/")) {
            if(failRelease) throw new TypeError("offline");
            if(!matches) return reply({success:false,code:"reservation_generation_stale"},409);
            held=null; return reply({success:true,released:true});
        }
        if(url.endsWith("/status/")) return reply({success:true,state:held?(matches?"reserved_self":"reserved_other"):"available"});
        if(!matches) return reply({success:false,code:"reservation_generation_stale"},409);
        return reply({success:true,value:1});
    }
    return {fetch,calls,expire(){held=null;}, get held(){return held;},
        set offline(value){failRenew=value;},set badRelease(value){failRelease=value;}};
}
function client(backend, identity="tab") {
    let seq=0,time=0,csrf="csrf-current", next=0;
    const timers = new Map(), states=[];
    const manager = create({fetch:backend.fetch,csrf:()=>csrf,uuid:()=>identity+"-"+(++seq),
        url:(id,op)=>"/points/"+id+"/"+op+"/",now:()=>time,
        setTimeout:(fn)=>{timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id)});
    manager.subscribe(state=>states.push(state));
    return {manager,timers,states,set time(value){time=value;},set csrf(value){csrf=value;}};
}
test("acquisition stores no public secrets and adds full proof plus fresh CSRF",async()=>{
    const backend=server(),c=client(backend); await c.manager.acquire(7);
    assert.equal(c.manager.canOperate(7),true);
    c.csrf="rotated";
    await c.manager.perform(7,"/points/7/status-change/",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    const call=backend.calls.find(call=>call.url.endsWith("status-change/"));
    assert.equal(call.options.headers["X-CSRFToken"],"rotated");
    assert.equal(call.options.headers["X-Waypoint-Token"],"secret-1");
    assert.equal(call.options.headers["X-Waypoint-Generation"],"1");
    assert.equal(call.options.headers["X-Waypoint-Interaction"],"tab-1");
    assert.equal(call.options.credentials,"same-origin");
    assert.equal(JSON.stringify(c.manager.snapshot()).includes("secret-"),false);
    assert.equal(JSON.stringify(c.states).includes("secret-"),false);
});
for(const identity of ["same-user-other-tab","other-user"]) test("competing interaction "+identity+" remains read-only",async()=>{
    const backend=server(),a=client(backend,"first"),b=client(backend,identity);
    await a.manager.acquire(7);
    await assert.rejects(b.manager.acquire(7),{code:"reservation_occupied"});
    assert.equal(b.manager.canOperate(7),false);
    assert.equal(b.manager.snapshot().state,"occupied");
    assert.equal((await b.manager.status(7)).state,"reserved_other");
    await a.manager.close();
    assert.equal((await b.manager.status(7)).state,"available");
    assert.equal(b.manager.canOperate(7),false); // polling never acquires
});
test("heartbeat single-flight avoids duplicate renewal",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    await c.timers.values().next().value();
    const before=backend.calls.filter(c=>c.url.endsWith("/renew/")).length;
    await Promise.all([c.manager.renew(),c.manager.renew()]);
    assert.equal(backend.calls.filter(c=>c.url.endsWith("/renew/")).length,before+1);
});
test("transient network suspends editing, retains lease and recovers only after confirmation",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    backend.offline=true;
    await assert.rejects(c.manager.renew(),{code:"network"});
    assert.equal(c.manager.canOperate(7),false);
    await assert.rejects(c.manager.perform(7,"/edit/",{method:"POST"}),{code:"reservation_required"});
    backend.offline=false;await c.manager.resume();
    assert.equal(c.manager.canOperate(7),true);
    assert.equal(backend.calls.filter(c=>c.url==="/edit/").length,0);
});
test("expired or replaced generation rejects old operation and requires new acquisition",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    backend.expire(); await assert.rejects(c.manager.renew(),{code:"reservation_generation_stale"});
    assert.equal(c.manager.snapshot().state,"lost");
    await assert.rejects(c.manager.perform(7,"/edit/"),{code:"reservation_required"});
    await c.manager.acquire(7);
    assert.equal(backend.held.generation,2);assert.equal(backend.held.interaction_id,"tab-2");
});
test("closing releases once, stops timers and invalidates editing",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    await c.manager.close();await c.manager.close();
    assert.equal(c.timers.size,0);assert.equal(c.manager.canOperate(7),false);
    assert.equal(backend.calls.filter(c=>c.url.endsWith("/release/")).length,1);
});
test("release failure never announces availability and falls back to server TTL",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);backend.badRelease=true;
    await c.manager.close();
    assert.equal(c.manager.canOperate(7),false);assert.ok(backend.held);
    assert.equal(c.states.at(-1).state,"release_failed");
});
test("late acquisition is released without replacing a newer waypoint",async()=>{
    const backend=server(),wait=deferred(),original=backend.fetch;
    backend.fetch=async(url,opts)=>{
        const res=await original(url,opts);
        if(url==="/points/7/acquire/") {await wait.promise;}
        return res;
    };
    const c=client(backend);
    const old=c.manager.acquire(7); const oldResult=assert.rejects(old,{code:"superseded"});
    await tick();
    // The fake has a single slot, so release completion precedes second acquisition.
    const closing=c.manager.close();wait.resolve();await oldResult;await closing;await tick();
    await c.manager.acquire(8);
    assert.equal(c.manager.snapshot().pointId,8);
    assert.equal(c.manager.canOperate(7),false);
    assert.equal(backend.held.generation,2);
});
test("simultaneous acquisition intents do not leak an untracked lease",async()=>{
    const backend=server(),c=client(backend);
    const a=c.manager.acquire(7),b=c.manager.acquire(8);
    await assert.rejects(a,{code:"superseded"});await b;
    assert.equal(backend.calls.filter(c=>c.url.endsWith("/acquire/")).length,1);
    assert.equal(c.manager.snapshot().pointId,8);
});
test("duplicate pending acquisition sends only one request",async()=>{
    const backend=server(),c=client(backend),wait=deferred(),original=backend.fetch;
    backend.fetch=async(url,opts)=>{await wait.promise;return original(url,opts);};
    // create reads injected fetch at construction
    const d=client(backend);const a=d.manager.acquire(7);await tick();const b=d.manager.acquire(7);
    wait.resolve();await Promise.all([a,b]);
    assert.equal(backend.calls.filter(c=>c.url.endsWith("/acquire/")).length,1);
});
test("closing a slow report retains heartbeat until body is consumed, discards result then releases",async()=>{
    const backend=server(),c=client(backend),body=deferred(),started=deferred();
    await c.manager.acquire(7);
    const work=c.manager.perform(7,"/points/7/report/",{},async()=>{started.resolve();return body.promise;});
    const rejected=assert.rejects(work,{code:"superseded"});await started.promise;
    await c.manager.close();assert.ok(backend.held);
    assert.ok(c.timers.size);
    await c.timers.values().next().value();assert.ok(backend.held);
    body.resolve("old-docx");await rejected;
    assert.equal(backend.held,null);
});
test("report final confirmation rejects replaced generation before presenting a file",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    await assert.rejects(c.manager.perform(7,"/points/7/report/",{method:"POST"},
        async()=>{backend.expire();return "docx";}),{code:"reservation_generation_stale"});
});
test("suspended timers disable editing without deciding database expiry",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);c.time=90000;
    assert.equal(c.manager.canOperate(7),false);assert.ok(backend.held);
    await c.manager.resume();assert.equal(c.manager.canOperate(7),true);
    c.manager.suspend();assert.equal(c.manager.canOperate(7),false);
});
for(const [status,code] of [[401,"authentication_required"],[403,"csrf_failed"],[403,"permission_denied"],[409,"reservation_expired"]]) {
    test("protected HTTP "+code+" is classified without replay",async()=>{
        const backend=server(),original=backend.fetch;
        backend.fetch=async(url,opts)=>url==="/edit/"?{status,ok:false,json:async()=>({success:false,code})}:original(url,opts);
        const c=client(backend);await c.manager.acquire(7);
        await assert.rejects(c.manager.perform(7,"/edit/",{method:"POST"}),{code});
        assert.equal(c.manager.canOperate(7),false);
    });
}
test("independent documents never use browser storage or BroadcastChannel for proof",()=>{
    const source=require("node:fs").readFileSync(require("node:path").join(__dirname,"waypoint_reservations.js"),"utf8");
    assert.doesNotMatch(source,/localStorage|sessionStorage|BroadcastChannel/);
});

test("a pending recovery cannot re-enable editing before the server confirms",async()=>{
    const backend=server(),original=backend.fetch,wait=deferred();
    let delay=false;
    backend.fetch=async(url,options)=>{
        if(delay&&url.endsWith("/renew/"))await wait.promise;
        return original(url,options);
    };
    const c=client(backend);await c.manager.acquire(7);
    c.manager.suspend();delay=true;
    const recovery=c.manager.resume();await tick();
    assert.equal(c.manager.snapshot().state,"renewing");
    assert.equal(c.manager.canOperate(7),false);
    wait.resolve();await recovery;assert.equal(c.manager.canOperate(7),true);
});
test("failure while reading the response body suspends writes",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    await assert.rejects(c.manager.perform(7,"/edit/",{method:"POST"},
        async()=>{throw new TypeError("connection lost");}),{code:"network"});
    assert.equal(c.manager.canOperate(7),false);
});

test("remote deletion invalidates locally without sending release or acquire",async()=>{
    const backend=server(),c=client(backend);await c.manager.acquire(7);
    const before=backend.calls.length;c.manager.invalidate(7);
    assert.equal(c.manager.canOperate(7),false);
    assert.equal(c.timers.size,0);
    await c.manager.close();
    assert.equal(backend.calls.length,before);
});

test("remote deletion during pending work discards its result without releasing a lease",async()=>{
    const backend=server(),c=client(backend),body=deferred(),started=deferred();
    await c.manager.acquire(7);
    const work=c.manager.perform(7,"/edit/",{method:"POST"},async()=>{started.resolve();return body.promise;});
    const rejected=assert.rejects(work,{code:"superseded"});await started.promise;
    const count=backend.calls.length;c.manager.invalidate(7);body.resolve("old result");
    await rejected;assert.equal(backend.calls.length,count);
});
