"use strict";
const test=require("node:test"),assert=require("node:assert/strict");
const {create}=require("./waypoint_reservation_ui.js");
class Node {
    constructor(tag="div") {this.tag=tag;this.children=[];this.dataset={};this.style={};this.attrs={};this.events={};this.disabled=false;}
    append(...nodes){this.children.push(...nodes);}
    prepend(node){this.children.unshift(node);}
    contains(node){return this===node||this.children.some(child=>child.contains(node));}
    setAttribute(key,value){this.attrs[key]=value;}
    getAttribute(key){return this.attrs[key];}
    removeAttribute(key){delete this.attrs[key];}
    matches(selector){return this.kind==="report"?selector.includes("data-generate-report"):
        this.kind==="delete"?selector.includes("signaling-popup__delete"):false;}
    querySelectorAll(){return this.mutations||[];}
    querySelector(){return null;}
    addEventListener(type,fn){(this.events[type]||=[]).push(fn);}
    closest(){return this.protected?this:null;}
    showModal(){this.shown=true;}
    close(){this.shown=false;}
    remove(){this.removed=true;}
}
function fixture({change=true,occupied=false}={}) {
    const root=new Node(),write=new Node("button"),read=new Node("button");
    root.mutations=[write];root.append(write,read);write.protected=true;
    const marker={getPopup:()=>({getElement:()=>root}),isPopupOpen:()=>true,getElement:()=>null};
    const point={id:7},body=new Node("body"),events={},windows={},intervals=[];
    const document={body,createElement:tag=>new Node(tag),getElementById:()=>null,
        addEventListener:(event,fn)=>events[event]=fn};
    const window={setInterval:(fn,ms)=>{fn.interval=ms;intervals.push(fn);return 1;},clearInterval(){},
        addEventListener:(event,fn)=>windows[event]=fn,location:{pathname:"/",href:"http://localhost/"}};
    let state={pointId:null,state:"idle",busy:0},listener;
    const calls=[];
    const emit=next=>{state={...state,...next};listener?.(state);};
    const manager={
        subscribe(fn){listener=fn;},snapshot:()=>state,
        canOperate:id=>state.pointId===id&&["active","renewing"].includes(state.state),
        async acquire(id){calls.push(["acquire",id]);
            if(occupied){emit({pointId:id,state:"occupied"});throw Object.assign(new Error("Ocupado"),{code:"reservation_occupied"});}
            emit({pointId:id,state:"active"});},
        async close(){calls.push(["close"]);emit({pointId:null,state:"idle"});},
        async perform(){return [{id:7,status:"OK"}];},
        status:async()=>({state:"available"}),leave(){calls.push(["leave"]);},
        suspend(){emit({state:"uncertain"});},resume(){calls.push(["resume"]);},
    };
    let renderCount=0;
    const observer={observe(){},disconnect(){}};
    const saved=global.MutationObserver;global.MutationObserver=class{constructor(fn){this.fn=fn;}observe(){}disconnect(){}};
    const ui=create({manager,document,window,map:{},markers:new Map([[7,marker]]),
        canChange:change,canDelete:true,canReport:true,csrf:()=>"",render:()=>{renderCount++;}});
    global.MutationObserver=saved;
    // bind() also creates an observer.
    function bind(){const old=global.MutationObserver;global.MutationObserver=class{observe(){}disconnect(){}};
        try{ui.bind(marker,point);}finally{global.MutationObserver=old;}}
    return {ui,manager,point,marker,write,read,root,calls,emit,events,windows,intervals,bind,
        get renders(){return renderCount;},body,window,document};
}
test("popup stays read-only until acquisition and refresh complete; loss disables mutations only",async()=>{
    const f=fixture();f.bind();assert.equal(f.write.disabled,true);assert.equal(f.read.disabled,false);
    await f.ui.begin(f.marker,f.point);f.bind();
    assert.equal(f.write.disabled,false);assert.equal(f.renders,1);
    f.emit({state:"uncertain"});assert.equal(f.write.disabled,true);assert.equal(f.read.disabled,false);
});
test("occupied popup preserves read access and never enables writes",async()=>{
    const f=fixture({occupied:true});f.bind();await f.ui.begin(f.marker,f.point);
    assert.equal(f.write.disabled,true);assert.equal(f.read.disabled,false);assert.equal(f.renders,0);
});
test("reservation does not grant change permission to a view-only user",async()=>{
    const f=fixture({change:false});f.bind();await f.ui.begin(f.marker,f.point);f.bind();
    assert.equal(f.write.disabled,true);
});
test("closing popup ends its interaction, while unrelated popup closures do not",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    f.ui.end(8);assert.equal(f.calls.filter(c=>c[0]==="close").length,0);
    f.ui.end(7);assert.equal(f.calls.filter(c=>c[0]==="close").length,1);
});
test("explicit retry obtains fresh data instead of silently acquiring on status polling",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    f.emit({state:"lost"});await f.intervals[0]();
    assert.equal(f.calls.filter(c=>c[0]==="acquire").length,1);
    await f.ui.begin(f.marker,f.point);assert.equal(f.renders,2);
});
test("visibility loss suspends writes; navigation while busy is blocked",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    f.emit({state:"uncertain"});assert.equal(f.write.disabled,true);
    let prevented=false,stopped=false;
    f.emit({state:"active",busy:1});
    f.events.submit({target:{closest:()=>null},preventDefault(){prevented=true;},
        stopImmediatePropagation(){stopped=true;}});
    assert.equal(prevented,true);assert.equal(stopped,true);
    assert.equal(f.calls.some(c=>c[0]==="leave"),false);
});
test("report close after popup closes discards late HTML and delegates draining to manager",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    let resolve;f.manager.perform=()=>new Promise(done=>resolve=done);
    const pending=f.ui.openReport(7,"/signaling/points/7/report/");
    const dialog=f.body.children.at(-1);
    assert.equal(dialog.shown,true);
    f.marker.isPopupOpen=()=>false;
    dialog.children[0].onclick();assert.equal(dialog.removed,true);
    resolve("old report");await pending;
    assert.equal(dialog.children[2].srcdoc,undefined);
    assert.equal(f.calls.filter(c=>c[0]==="close").length,1);
});

test("normal popup has no management card or permanent release/restart button",async()=>{
    const f=fixture();f.bind();
    const notice=f.root.children[0];
    assert.doesNotMatch(notice.className,/alert|border/);
    assert.equal(notice.children.length,2);
    assert.equal(notice.children[1].textContent,"Tentar editar novamente");
    assert.equal(notice.children[1].hidden,true);
    await f.ui.begin(f.marker,f.point);f.bind();
    assert.equal(notice.children[1].hidden,true);
});

test("three-second status polling and repeated panel binding preserve the active popup lifecycle",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    f.manager.status=async()=>({state:"reserved_self"});
    const listeners=Object.fromEntries(Object.entries(f.root.events).map(([type,list])=>[type,list.length]));
    for(let i=0;i<12;i++){f.bind();await f.intervals[0]();}
    assert.equal(f.intervals.length,1);
    assert.equal(f.intervals[0].interval,3000);
    assert.equal(f.calls.filter(call=>call[0]==="acquire").length,1);
    assert.equal(f.calls.filter(call=>call[0]==="close").length,0);
    assert.equal(f.renders,1);
    assert.equal(f.manager.canOperate(7),true);
    assert.deepEqual(Object.fromEntries(Object.entries(f.root.events).map(([type,list])=>[type,list.length])),listeners);
    f.ui.end(7);assert.equal(f.calls.filter(call=>call[0]==="close").length,1);
});
test("an obsolete status cannot display foreign ownership over a live own popup",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    const message=f.root.children[0].children[0];
    message.textContent="owned";
    f.manager.status=async()=>({stale:true,state:"reserved_other"});
    await f.intervals[0]();
    assert.equal(message.textContent,"owned");
    assert.equal(f.manager.canOperate(7),true);
    assert.equal(f.calls.some(call=>call[0]==="close"),false);
});

test("leaving report for the still-open map popup must preserve its acquisition",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    let resolve;f.manager.perform=()=>new Promise(done=>resolve=done);
    const pending=f.ui.openReport(7,"/signaling/points/7/report/");
    f.body.children.at(-1).children[0].onclick();
    resolve("late HTML");await pending;
    assert.equal(f.calls.filter(c=>c[0]==="close").length,0);
    assert.equal(f.manager.canOperate(7),true);
    f.ui.end(7);
    assert.equal(f.calls.filter(c=>c[0]==="close").length,1);
});

function reportDOM(t,f) {
    const oldParser=global.DOMParser, oldObserver=global.MutationObserver;
    global.DOMParser=class{parseFromString(){return {
        createElement:tag=>new Node(tag),head:{prepend(){}},documentElement:{outerHTML:"<html>report</html>"},
    };}};
    global.MutationObserver=class{observe(){}disconnect(){}};
    t.after(()=>{global.DOMParser=oldParser;global.MutationObserver=oldObserver;});
    const events={};
    const doc={querySelectorAll:()=>[],addEventListener:(type,fn)=>events[type]=fn};
    const win={FormData:class{},HTMLFormElement:{prototype:{submit(){}}}};
    return {events,attach(){
        const dialog=f.body.children.at(-1),frame=dialog.children[2];
        frame.contentDocument=doc;frame.contentWindow=win;frame.onload();
        return {dialog,frame,win};
    }};
}
test("HTML report returns to the same map acquisition and preserves close/reopen lifecycle",async(t)=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    const dom=reportDOM(t,f),mapRead=f.manager.perform;
    f.manager.perform=async(_id,_url,_options,consume)=>consume({ok:true,text:async()=>"<html>HTML report</html>"});
    await f.ui.openReport(7,"/signaling/points/7/report/");
    const {dialog,frame}=dom.attach();
    assert.match(frame.srcdoc,/html/);
    f.manager.status=async()=>({state:"reserved_self"});
    await f.intervals[0](); // status during report
    dom.events.click({target:{closest:()=>({target:"",getAttribute:()=>"/"})},preventDefault(){}});
    assert.equal(dialog.removed,true);
    assert.equal(f.calls.filter(call=>call[0]==="close").length,0);
    assert.equal(f.manager.canOperate(7),true);
    f.ui.end(7);assert.equal(f.calls.filter(call=>call[0]==="close").length,1);
    f.manager.perform=mapRead;
    await f.ui.begin(f.marker,f.point);
    assert.equal(f.calls.filter(call=>call[0]==="acquire").length,2);
    assert.equal(f.manager.canOperate(7),true);
});
test("DOCX form consumes the artifact without ending the map lease",async(t)=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    const dom=reportDOM(t,f),requests=[],downloads=[];
    // Download link only: report DOM remains the real UI controller under test.
    t.mock.method(URL,"createObjectURL",()=>"blob:report-test");
    t.mock.method(URL,"revokeObjectURL",()=>{});
    t.mock.method(global,"setTimeout",fn=>{fn();return 1;});
    f.manager.perform=async(id,url,options={},consume)=>{
        requests.push({id,url,method:options.method||"GET"});
        return consume({ok:true,headers:{get:()=>"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            text:async()=>"<html>report</html>",blob:async()=>new Blob(["docx"])});
    };
    // The document factory creates the download anchor inside the production handler.
    const previousClick=Node.prototype.click;
    Node.prototype.click=function(){downloads.push(this.download);};
    t.after(()=>{if(previousClick)Node.prototype.click=previousClick;else delete Node.prototype.click;});
    await f.ui.openReport(7,"/signaling/points/7/report/");
    const {dialog}=dom.attach();
    const form={dataset:{},matches:selector=>selector==="[data-waypoint-report-form]"};
    await dom.events.submit({target:form,preventDefault(){}});
    assert.deepEqual(requests.map(item=>item.method),["GET","POST"]);
    assert.deepEqual(downloads,["relatorio-sinalizacao.docx"]);
    dialog.children[0].onclick();
    assert.equal(f.calls.filter(call=>call[0]==="close").length,0);
});
test("failed or expired report does not silently reacquire or release the map waypoint",async()=>{
    for(const state of ["uncertain","lost"]){
        const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
        f.manager.perform=async()=>{
            f.emit({state});
            throw Object.assign(new Error("Report rejected"),{code:state==="lost"?"reservation_expired":"network"});
        };
        await f.ui.openReport(7,"/signaling/points/7/report/");
        f.body.children.at(-1).children[0].onclick();
        assert.equal(f.calls.filter(call=>call[0]==="close").length,0);
        assert.equal(f.calls.filter(call=>call[0]==="acquire").length,1);
        assert.equal(f.manager.canOperate(7),false);
    }
});
test("BFCache restored popup offers a fresh acquisition instead of remaining visually locked",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    f.manager.leave=()=>f.emit({pointId:null,state:"idle"});
    f.windows.pagehide({persisted:true});await f.windows.pageshow({persisted:true});
    const retry=f.root.children[0].children[1];
    assert.equal(f.write.disabled,true);
    assert.equal(retry.hidden,false);
    assert.equal(f.calls.filter(call=>call[0]==="acquire").length,1);
});

test("BFCache restoration dismisses a report tied to an ended acquisition and drops late HTML",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    let resolve;f.manager.perform=()=>new Promise(done=>resolve=done);
    const pending=f.ui.openReport(7,"/signaling/points/7/report/");
    const dialog=f.body.children.at(-1);
    f.manager.leave=()=>f.emit({pointId:null,state:"idle"});
    f.windows.pagehide({persisted:true});await f.windows.pageshow({persisted:true});
    assert.equal(dialog.removed,true);
    resolve("ended report");await pending;
    assert.equal(dialog.children[2].srcdoc,undefined);
    assert.equal(f.write.disabled,true);
    assert.equal(f.root.children[0].children[1].hidden,false);
    assert.equal(f.calls.filter(call=>call[0]==="acquire").length,1);
});


function draftUI(t) {
    const f=fixture(),dom=reportDOM(t,f);
    const draft={pending:true,stops:0,destroyed:false,attached:0,flushes:0,
        hasPending(){return this.pending;},
        async flush(){this.flushes++;return false;},
        stop(){this.stops++;},pause(){},resume(){},
        destroy(){this.destroyed=true;},attach(){this.attached++;},
    };
    f.window.ReportDraft={mount:()=>draft};
    f.manager.perform=async(_id,_url,_options,consume)=>consume({ok:true,text:async()=>"<html>report</html>"});
    return {f,dom,draft,async open(){
        const perform=f.manager.perform;f.manager.perform=async()=>[{id:7,status:"OK"}];
        await f.ui.begin(f.marker,f.point);f.manager.perform=perform;
        await f.ui.openReport(7,"/signaling/points/7/report/");
        return dom.attach();
    }};
}
test("closing an unsaved report permits cancel; discard requires explicit confirmation",async t=>{
    const {f,draft,open}=draftUI(t),{dialog}=await open();
    const close=dialog.children[0].onclick();await Promise.resolve();await Promise.resolve();
    assert.equal(draft.flushes,1);assert.equal(dialog.removed,undefined);
    const confirmation=f.body.children.at(-1);assert.notEqual(confirmation,dialog);
    confirmation.children[2].onclick();await close;
    assert.equal(dialog.removed,undefined);assert.equal(draft.destroyed,false);
    const discard=dialog.children[0].onclick();await Promise.resolve();await Promise.resolve();
    f.body.children.at(-1).children[1].onclick();await discard;
    assert.equal(dialog.removed,true);assert.equal(draft.destroyed,true);
});
test("successful flush closes the report without a discard dialog",async t=>{
    const {f,draft,open}=draftUI(t),{dialog}=await open();
    draft.flush=async()=>{draft.pending=false;return true;};
    await dialog.children[0].onclick();
    assert.equal(dialog.removed,true);assert.equal(f.body.children.length,1);
});
for (const state of ["lost","closing","acquiring"]) test("reservation "+state+" retains unsaved report for copy",async t=>{
    const {f,draft,open}=draftUI(t),{dialog}=await open();
    f.emit({state});assert.ok(draft.stops>0);assert.equal(dialog.removed,undefined);
    let prevented=false;f.windows.beforeunload({preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.equal(draft.destroyed,false);
});
test("switching reservation to another waypoint stops the old form",async t=>{
    const {f,draft,open}=draftUI(t),{dialog}=await open();
    f.emit({pointId:8,state:"active"});assert.ok(draft.stops>0);
    assert.equal(dialog.removed,undefined);
});
test("DOCX waits for pending autosave and uses the same report POST",async t=>{
    const {f,dom,draft,open}=draftUI(t);await open();const order=[];
    draft.flush=async()=>{order.push("draft");draft.pending=false;};
    f.manager.perform=async(_id,url,options,consume)=>{
        order.push(options.method+":"+url);
        return consume({ok:true,headers:{get:()=>"text/html"},text:async()=>"<html>validation</html>"});
    };
    const form={dataset:{},matches:()=>true};
    await dom.events.submit({target:form,preventDefault(){}});
    assert.deepEqual(order,["draft","POST:/signaling/points/7/report/"]);
    dom.attach();assert.equal(draft.attached,1);
});


test("BFCache and remote deletion retain unsaved report instead of destroying it",async t=>{
    const {f,draft,open}=draftUI(t),{dialog}=await open();
    f.manager.leave=()=>f.emit({pointId:null,state:"idle"});
    f.windows.pagehide();await f.windows.pageshow();
    assert.equal(dialog.removed,undefined);assert.equal(draft.destroyed,false);
    f.manager.invalidate=()=>f.emit({pointId:null,state:"idle"});
    f.ui.invalidate(7);
    assert.equal(dialog.removed,undefined);assert.equal(draft.destroyed,false);
});
test("outer navigation cannot silently discard unsaved form",async t=>{
    const {f,open}=draftUI(t);await open();let prevented=false;
    const link={target:"",closest:()=>null,getAttribute:()=>"/other/"};
    f.events.click({target:{closest:()=>link},preventDefault(){prevented=true;},stopImmediatePropagation(){}});
    assert.equal(prevented,true);assert.equal(f.calls.some(item=>item[0]==="leave"),false);
});


test("a DOCX error page without a form must not replace unsaved local fields",async t=>{
    const {f,dom,open}=draftUI(t),{frame,dialog}=await open();
    const original=frame.srcdoc;
    global.DOMParser=class{parseFromString(){return {querySelector:()=>null};}};
    f.manager.perform=async(_id,_url,_options,consume)=>consume({ok:true,
        headers:{get:()=>"text/html"},text:async()=>"<html>filter error</html>"});
    await dom.events.submit({target:{dataset:{},matches:()=>true},preventDefault(){}});
    assert.equal(frame.srcdoc,original);assert.match(dialog.children[1].textContent,/textos foram mantidos/);
});
test("lost reservation leaves text selectable in read-only fields",async t=>{
    const {f,open}=draftUI(t),{frame}=await open();const text={readOnly:false,value:"Local"};
    frame.contentDocument.querySelectorAll=selector=>selector.includes("textarea")?[text]:[];
    f.emit({state:"lost"});
    assert.equal(text.readOnly,true);assert.equal(text.disabled,undefined);assert.equal(text.value,"Local");
});
