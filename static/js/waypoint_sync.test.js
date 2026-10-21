"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const {create}=require("./waypoint_sync.js");
const revision="a".repeat(64),changed="b".repeat(64);
const item=(id,status="OK")=>({point:{id,status},revision:status==="OK"?revision:changed});
const packet=(upserts=[],deleted=[])=>({success:true,upserts,deleted});
const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function setup() {
    let data=packet(),fail=false,hidden=false;
    const nodes=new Map(),calls=[],timers=new Map(),errors=[],pending=[];
    let counter=0,open=null,delay=false;
    const sync=create({url:"/signaling/points/sync/",csrf:()=>"csrf",
        hidden:()=>hidden,ids:[9],
        fetch:async(url,options)=>{
            calls.push({url,options});
            if(delay)return new Promise(resolve=>pending.push(resolve));
            if(fail)throw new TypeError("offline");
            return {ok:true,status:200,json:async()=>data};
        },
        apply:point=>{if(point.id===open)return false;nodes.set(point.id,point);return true;},
        remove:id=>nodes.delete(id),
        schedule:(fn,ms)=>{timers.set(++counter,{fn,ms});return counter;},
        cancel:id=>timers.delete(id),onError:error=>errors.push(error)});
    return {sync,nodes,calls,timers,errors,pending,
        set data(value){data=value;},set fail(value){fail=value;},
        set hidden(value){hidden=value;},set open(value){open=value;},set delay(value){delay=value;}};
}
test("remote creation, update, deletion converge by stable ID without duplicate nodes",async()=>{
    const s=setup();s.data=packet([item(1)],[9]);s.sync.start();await tick();
    assert.equal(s.nodes.size,1);
    s.data=packet([item(1,"ABSENT"),item(2)]);await s.sync.refresh();
    assert.equal(s.nodes.size,2);assert.equal(s.nodes.get(1).status,"ABSENT");
    s.data=packet([],[1]);await s.sync.refresh();assert.deepEqual([...s.nodes.keys()],[2]);
    assert.equal(s.calls[0].options.headers["X-CSRFToken"],"csrf");
    assert.deepEqual(Object.keys(JSON.parse(s.calls[0].options.body)),["known"]);
});
test("open details and unsaved local draft are preserved; update is fetched after closing",async()=>{
    const s=setup();s.data=packet([item(1)]);s.sync.start();await tick();
    const original=s.nodes.get(1);original.draft="not saved";s.open=1;
    s.data=packet([item(1,"ABSENT")]);await s.sync.refresh();
    assert.equal(s.nodes.get(1),original);assert.equal(original.draft,"not saved");
    const known=JSON.parse(s.calls.at(-1).options.body).known;
    assert.equal(known["1"],revision);
    s.open=null;await s.sync.refresh();assert.equal(s.nodes.get(1).status,"ABSENT");
});
test("network failure keeps existing markers and schedules another poll",async()=>{
    const s=setup();s.data=packet([item(1)]);s.sync.start();await tick();
    s.fail=true;await s.sync.refresh();assert.equal(s.nodes.size,1);
    assert.equal(s.errors.length,1);assert.ok(s.timers.size);
});
test("only one request runs and obsolete response cannot overwrite a newer local write",async()=>{
    const s=setup();s.delay=true;s.sync.start();await tick();
    const refresh=s.sync.refresh();await refresh;assert.equal(s.calls.length,1);
    s.sync.beginWrite();s.sync.endWrite();
    s.delay=false;s.data=packet([item(2)]);
    s.pending[0]({ok:true,json:async()=>packet([item(1)])});await tick();
    assert.equal(s.nodes.has(1),false);assert.equal(s.nodes.has(2),true);
});
test("background polling is reduced and return requests fresh data immediately",async()=>{
    const s=setup();s.hidden=true;s.sync.start();await tick();assert.equal(s.calls.length,0);
    assert.equal([...s.timers.values()][0].ms,60000);
    s.hidden=false;s.data=packet([item(1)]);await s.sync.refresh();
    assert.equal(s.nodes.has(1),true);
    assert.equal([...s.timers.values()][0].ms,10000);
});
test("start is idempotent and stopped responses never update markers",async()=>{
    const s=setup();s.delay=true;s.sync.start();s.sync.start();await tick();
    assert.equal(s.calls.length,1);s.sync.stop();
    s.pending[0]({ok:true,json:async()=>packet([item(1)])});await tick();
    assert.equal(s.nodes.size,0);assert.equal(s.timers.size,0);
});
test("known initial IDs allow deletion before the first synchronization",async()=>{
    const s=setup();s.nodes.set(9,{id:9});s.data=packet([],[9]);s.sync.start();await tick();
    assert.equal(s.nodes.size,0);
    assert.equal(JSON.parse(s.calls[0].options.body).known["9"],"0".repeat(64));
});
test("polling only uses sync endpoint, never reservation proofs, acquisition or release",async()=>{
    const s=setup();s.sync.start();await tick();await s.sync.refresh();
    for(const call of s.calls) {
        assert.equal(call.url,"/signaling/points/sync/");
        assert.equal(Object.keys(call.options.headers).some(key=>key.startsWith("X-Waypoint")),false);
    }
});
