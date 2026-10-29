"use strict";
const test=require("node:test"),assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
// Exercise the actual renderer in isolation from Leaflet/map initialization.
const source=fs.readFileSync(path.join(__dirname,"signaling.js"),"utf8");
const renderer=source.slice(source.indexOf("function buildExistingPointPopup(point)"),source.indexOf("function buildInterventionForm(point)"));
test("waypoint card identifies the backend record independently of marker ordering",()=>{
    const context={hasIndividualAnalysis:true,canReportSignaling:true,
        signalingStatuses:{OK:{popupLabel:"Completa",buttonClass:"btn-success",label:"Completa"}},
        buildInterventionList:()=>"",minSignalingSearchRadiusMeters:10,maxSignalingSearchRadiusMeters:1000,
        reportUrl:id=>`/signaling/points/${id}/report/`};
    vm.createContext(context);vm.runInContext(renderer,context);
    for(const id of [30,9,401]){
        const html=context.buildExistingPointPopup({id,status:"OK",search_radius_meters:100});
        assert.match(html,new RegExp(`<h2>Waypoint #${id}</h2>`));
        assert.match(html,new RegExp(`data-signaling-point-id="${id}"`));
        assert.match(html,new RegExp(`/points/${id}/report/`));
        assert.doesNotMatch(html,/data-close-waypoint/); // Leaflet keeps the sole popup close control.
    }
});
