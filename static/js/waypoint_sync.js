(function(root,factory) {
    const api=factory();
    if(typeof module==="object"&&module.exports)module.exports=api;
    else root.WaypointSync=api;
}(typeof globalThis!=="undefined"?globalThis:this,function(){
    "use strict";
    function create({fetch, url, csrf, ids=[], apply, remove, hidden=()=>false,
        schedule=setTimeout, cancel=clearTimeout, interval=3000, onError=()=>{}}) {
        const known=Object.fromEntries(ids.map(id=>[id,"0".repeat(64)]));
        let running=false, stopped=true, timer=null, epoch=0, writes=0, rerun=false;
        function plan() {
            cancel(timer);
            if(!stopped)timer=schedule(()=>poll(),hidden()?interval*6:interval);
        }
        async function poll() {
            if(stopped)return;
            if(running){rerun=true;return;}
            if(writes||hidden()){plan();return;}
            running=true;
            const version=epoch;
            try {
                const response=await fetch(url,{method:"POST",credentials:"same-origin",cache:"no-store",
                    headers:{"Content-Type":"application/json","X-CSRFToken":csrf()},
                    body:JSON.stringify({known:{...known}}),signal:AbortSignal.timeout(20000)});
                if(!response.ok)throw Object.assign(new Error(response.status===401?
                    "Entre novamente para atualizar os waypoints.":response.status===403?
                    "Sem autorização para atualizar os waypoints.":"Não foi possível atualizar os waypoints."),
                    {status:response.status});
                const data=await response.json();
                if(!data.success||!Array.isArray(data.upserts)||!Array.isArray(data.deleted)||
                    data.upserts.some(item=>!Number.isSafeInteger(item.point?.id)||
                        typeof item.revision!=="string"||!/^[a-f0-9]{64}$/.test(item.revision))||
                    data.deleted.some(id=>!Number.isSafeInteger(id)||id<1)){
                    throw new Error("Resposta de sincronização inválida.");
                }
                if(stopped||version!==epoch||writes)return;
                for(const item of data.upserts) {
                    if(apply(item.point)!==false)known[item.point.id]=item.revision;
                }
                for(const id of data.deleted) {remove(id);delete known[id];}
            } catch(error) {
                if(!stopped&&version===epoch) {
                    onError(error);
                    if([401,403].includes(error.status))stopped=true;
                }
            } finally {
                running=false;
                if(rerun&&!stopped){rerun=false;queueMicrotask(()=>poll());}else plan();
            }
        }
        return {
            start(){if(!stopped)return;stopped=false;poll();},
            stop(){stopped=true;epoch++;cancel(timer);},
            refresh(){epoch++;cancel(timer);return poll();},
            beginWrite(){writes++;epoch++;},
            endWrite(){writes=Math.max(0,writes-1);epoch++;},
            track(id){if(!(id in known))known[id]="0".repeat(64);epoch++;},
        };
    }
    return {create};
}));
