"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {createIntent} = require("./report_finalization.js");
const reservations = require("./waypoint_reservations.js");
const key = "12345678-1234-4234-8234-123456789abc";
const description = state => ({success:state === "FINALIZED", state, attempt_id:"attempt-1", report_id:"report-1", number:"RTSV-2026-0001", version:1});
const reply = (data, status=200) => ({ok:status < 400, status, json:async () => data});
function fixture() {
    const calls = [], gets = [];
    let respond = () => reply(description("FINALIZED"), 201);
    const manager = {perform:async (id,url,init,consume,policy) => {
        calls.push({id,url,init,policy}); return consume(await respond());
    }};
    const options = {manager, pointId:23, expectedRevision:7, idempotencyKey:key,
        url:"/signaling/points/23/report-finalizations/?analysis=synthetic&year=2026",
        attemptUrl:(id,retry) => `/signaling/report-finalizations/${id}/${retry ? "retry/" : ""}`,
        fetch:async (url,init) => { gets.push({url,init}); return respond(); }};
    const client = createIntent(options);
    return {client, calls, gets, set respond(fn) { respond=fn; }, options};
}
test("valid request has frozen revision, key, session and original query; published result retained", async () => {
    const f=fixture(); const output=await f.client.submit();
    assert.equal(output.kind,"published"); assert.equal(output.attempt.number,"RTSV-2026-0001");
    assert.deepEqual(JSON.parse(f.calls[0].init.body),{idempotency_key:key,expected_revision:7});
    assert.equal(f.calls[0].init.credentials,"same-origin");
    assert.match(f.calls[0].url,/analysis=synthetic&year=2026/);
    await f.client.submit(); assert.equal(f.calls.length,1);
});
test("module creation and status without attempt publish nothing", async () => {
    const f=fixture(); assert.equal(f.calls.length,0); assert.equal(f.gets.length,0);
    assert.equal((await f.client.check()).kind,"unknown");
    assert.equal((await f.client.retry()).code,"explicit_retry_not_available"); assert.equal(f.calls.length,0);
});
test("duplicate submissions share one in-flight operation", async () => {
    const f=fixture(); let resolve; f.respond=()=>new Promise(r=>{resolve=r;});
    const first=f.client.submit(), second=f.client.submit(); assert.equal(first,second);
    await Promise.resolve(); resolve(reply(description("FINALIZED"),201)); await first;
    assert.equal(f.calls.length,1);
});
test("network after sending preserves key and explicit replay recovers", async () => {
    const f=fixture(); f.respond=()=>{throw new TypeError("offline");};
    assert.equal((await f.client.submit()).kind,"uncertain");
    assert.equal(f.client.recovery().idempotencyKey,key);
    f.respond=()=>reply(description("FINALIZED"));
    assert.equal((await f.client.submit()).kind,"published");
    assert.equal(f.calls[0].init.body,f.calls[1].init.body);
});
for (const [status,code,kind] of [[403,"permission_denied","forbidden"],[409,"draft_revision_conflict","conflict"],
    [409,"idempotency_key_conflict","conflict"],[503,"finalization_disabled","unavailable"],
    [428,"reservation_required","reservation_error"]]) test(`handles ${code}`, async () => {
    const f=fixture(); f.respond=()=>reply({success:false,code},status);
    const output=await f.client.submit(); assert.equal(output.kind,kind); assert.equal(output.recovery.idempotencyKey,key);
});
test("202 false success is processing, status is explicit and needs no reservation", async () => {
    const f=fixture(); f.respond=()=>reply(description("PROCESSING"),202);
    assert.equal((await f.client.submit()).kind,"processing");
    f.respond=()=>reply(description("FINALIZED")); assert.equal((await f.client.check()).kind,"published");
    assert.equal(f.calls.length,1); assert.equal(f.gets[0].init.credentials,"same-origin");
});
test("failed attempt retained; only explicit retry posts empty payload to retry endpoint", async () => {
    const f=fixture(); f.respond=()=>reply({code:"conversion_failed",attempt:description("FAILED")},503);
    await f.client.submit(); assert.equal(f.client.recovery().attemptId,"attempt-1");
    f.respond=()=>reply(description("FINALIZED")); assert.equal((await f.client.retry()).kind,"published");
    assert.match(f.calls[1].url,/attempt-1\/retry\/$/); assert.equal(f.calls[1].init.body,"{}");
});
test("multipart originals have no manually set content-type", async () => {
    const f=fixture(); const client=createIntent({...f.options,photos:[new Blob(["synthetic"])]});
    await client.submit(); assert.equal(f.calls[0].init.headers["Content-Type"],undefined);
    assert.equal(f.calls[0].init.body.get("idempotency_key"),key);
    assert.equal(f.calls[0].init.body.getAll("photos").length,1);
});
test("real manager supplies CSRF and proof; business 409 preserves lease; real reservation conflict loses it", async () => {
    const calls=[]; let conflict=false, processing=false;
    const manager=reservations.create({csrf:()=>"csrf-test",uuid:()=>key,url:(id,op)=>`/points/${id}/${op}/`,
        setTimeout:()=>1,clearTimeout:()=>{},now:()=>0,
        fetch:async (url,init)=>{
            calls.push({url,init});
            if(url.endsWith("acquire/"))return reply({success:true,token:"test-token",interaction_id:key,generation:1,expires_at:"future"});
            if(url.endsWith("renew/"))return reply({success:true,generation:1});
            if(processing) return reply(description("PROCESSING"),202);
            return reply({code:conflict?"reservation_expired":"report_source_changed"},409);
        }});
    await manager.acquire(23);
    const f=fixture(), client=createIntent({...f.options,manager});
    assert.equal((await client.submit()).kind,"conflict"); assert.equal(manager.canOperate(23),true);
    const sent=calls.find(c=>c.url.includes("report-finalizations"));
    assert.equal(sent.init.headers["X-CSRFToken"],"csrf-test");
    assert.equal(sent.init.headers["X-Waypoint-Token"],"test-token");
    assert.equal(sent.init.headers["X-Waypoint-Interaction"],key);
    assert.equal(sent.init.headers["X-Waypoint-Generation"],"1");
    processing=true; assert.equal((await client.submit()).kind,"processing");
    assert.equal(manager.canOperate(23),true);
    processing=false; conflict=true; assert.equal((await client.submit()).kind,"reservation_error");
    assert.equal(manager.canOperate(23),false);
});

test("malformed successful body is ambiguous and preserves the key", async () => {
    const f=fixture(); f.respond=()=>reply({success:true});
    assert.equal((await f.client.submit()).kind,"uncertain");
    assert.equal(f.client.recovery().idempotencyKey,key);
});
test("key collision never enables retry of an unrelated attempt", async () => {
    const f=fixture(); f.respond=()=>reply({code:"idempotency_key_conflict",attempt:description("FAILED")},409);
    await f.client.submit();
    assert.equal(f.client.recovery().attemptId,null);
    assert.equal((await f.client.retry()).code,"explicit_retry_not_available");
    assert.equal(f.calls.length,1);
});
test("HTML CSRF rejection is forbidden, HTML server failure remains ambiguous", async () => {
    const f=fixture(); f.respond=()=>({status:403,json:async()=>{throw new Error("html");}});
    assert.equal((await f.client.submit()).kind,"forbidden");
    f.respond=()=>({status:500,json:async()=>{throw new Error("html");}});
    const output=await f.client.submit(); assert.equal(output.kind,"unavailable"); assert.equal(output.ambiguous,true);
});
