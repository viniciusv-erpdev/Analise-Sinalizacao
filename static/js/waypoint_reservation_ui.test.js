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
    const window={setInterval:fn=>{intervals.push(fn);return 1;},clearInterval(){},
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
        get renders(){return renderCount;},body};
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
test("report close discards a late HTML response and delegates draining to manager",async()=>{
    const f=fixture();f.bind();await f.ui.begin(f.marker,f.point);
    let resolve;f.manager.perform=()=>new Promise(done=>resolve=done);
    const pending=f.ui.openReport(7,"/signaling/points/7/report/");
    const dialog=f.body.children.at(-1);
    assert.equal(dialog.shown,true);
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
