/* Explicit, durable deletion intents. No automatic requests or new intents on recovery. */
(function(root,factory) {
    const api=factory();
    if (typeof module === "object" && module.exports) module.exports=api;
    else {
        root.ReportDeletion=api;
        root.document.querySelectorAll("[data-report-deletion]").forEach(node=>api.mount(node,root));
        root.document.querySelectorAll("[data-deletion-recovery]").forEach(node=>api.mountRecovery(node,root));
    }
}(typeof globalThis!=="undefined"?globalThis:this,function(){
    "use strict";
    const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    const uuid4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    const prefix=userId=>`rtsv.deletion.v1.u${userId}.`;
    function valid(record,userId,reportId) {
        return record?.schema===1 && record.userId===String(userId) && record.reportId===reportId &&
            uuid.test(record.reportId) && uuid4.test(record.operationId) && /^RTSV-\d{4}-\d{4}$/.test(record.number);
    }
    function operation(crypto) {
        if (typeof crypto?.randomUUID==="function") return crypto.randomUUID();
        if (!crypto?.getRandomValues) throw new Error("secure_random_unavailable");
        const bytes=crypto.getRandomValues(new Uint8Array(16));
        bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
        return Array.from(bytes,(byte,index)=>([4,6,8,10].includes(index)?"-":"")+byte.toString(16).padStart(2,"0")).join("");
    }
    const messages={
        ready:"Digite o n\u00famero oficial para confirmar a exclus\u00e3o permanente.",
        busy:"Exclus\u00e3o em andamento. Aguarde a resposta do servidor.",
        complete:"Exclus\u00e3o conclu\u00edda. Retornando \u00e0 biblioteca.",
        pending:"Os registros foram exclu\u00eddos, mas a limpeza dos arquivos est\u00e1 pendente. Retome a mesma opera\u00e7\u00e3o; ela tamb\u00e9m ficar\u00e1 dispon\u00edvel na biblioteca.",
        forbidden:"Sua permiss\u00e3o ou sess\u00e3o n\u00e3o permite esta opera\u00e7\u00e3o. Confira a autentica\u00e7\u00e3o e solicite revis\u00e3o do acesso.",
        missing:"Relat\u00f3rio n\u00e3o encontrado ou inacess\u00edvel. O resultado da tentativa anterior n\u00e3o foi confirmado. N\u00e3o crie outra inten\u00e7\u00e3o.",
        conflict:"A exclus\u00e3o est\u00e1 em conflito com outra opera\u00e7\u00e3o. Aguarde e verifique novamente usando a mesma inten\u00e7\u00e3o.",
        uncertain:"N\u00e3o foi poss\u00edvel confirmar o resultado. Verifique a mesma opera\u00e7\u00e3o; nenhuma nova inten\u00e7\u00e3o ser\u00e1 criada.",
        invalid:"A solicita\u00e7\u00e3o foi rejeitada. Solicite revis\u00e3o sem apagar a opera\u00e7\u00e3o preservada.",
        journal_error:"N\u00e3o foi poss\u00edvel preservar ou recuperar a opera\u00e7\u00e3o neste navegador. Exclus\u00e3o bloqueada. N\u00e3o limpe os dados locais de uma tentativa incerta.",
        confirmation:"O n\u00famero deve corresponder exatamente ao relat\u00f3rio.",
    };
    function message(state){
        if(state.code==="deletion_operation_conflict")return "O identificador desta opera\u00e7\u00e3o est\u00e1 em conflito. Solicite revis\u00e3o sem criar outra inten\u00e7\u00e3o.";
        if(state.code==="unsafe_deletion_storage")return "A exclus\u00e3o foi bloqueada por inconsist\u00eancia no armazenamento. Solicite revis\u00e3o administrativa.";
        return messages[state.kind]||messages.uncertain;
    }
    function createClient({userId,reportId,number,url,environment,notify=()=>{}}) {
        const key=prefix(userId)+reportId;
        let record=null,storage=null,pending=null,kind="ready",code="";
        try {
            storage=environment.localStorage;
            const raw=storage.getItem(key);
            if(raw){record=JSON.parse(raw);if(!valid(record,userId,reportId)||record.number!==number)throw new Error();kind=record.state==="pending"?"pending":"uncertain";}
        } catch {kind="journal_error";}
        const snapshot=()=>({kind,code,busy:pending!==null,record:record?{...record}:null,
            recoverable:["pending","uncertain","conflict"].includes(kind)&&!["deletion_operation_conflict","unsafe_deletion_storage"].includes(code)});
        function change(next,nextCode=""){kind=next;code=nextCode;notify(snapshot());}
        function persist(){
            if(!storage||!valid(record,userId,reportId))throw new Error();
            const raw=JSON.stringify(record);storage.setItem(key,raw);
            if(storage.getItem(key)!==raw)throw new Error();
        }
        async function request(){
            try {record.state="uncertain";persist();}catch{change("journal_error");return snapshot();}
            change("busy");
            try {
                const target=new URL(url,environment.location.href);
                if(target.origin!==new URL(environment.location.href).origin || !target.pathname.endsWith(`/reports/${reportId}/delete/`))throw new Error();
                const response=await environment.fetch(target.href,{
                    method:"POST",credentials:"same-origin",cache:"no-store",
                    headers:{"Content-Type":"application/json","X-CSRFToken":environment.csrf()},
                    signal:environment.AbortSignal?.timeout(30000),
                    body:JSON.stringify({operation_id:record.operationId,confirm_number:record.number}),
                });
                let data;
                if(!response.redirected && (response.headers.get("Content-Type")||"").split(";")[0].trim().toLowerCase()==="application/json"){
                    try{data=await response.json();}catch{ /* Never display server response bodies. */ }
                }
                if(response.status===200 && data?.success===true && data.report_deleted===true && data.cleanup_state==="COMPLETE" && data.number===number && uuid4.test(data.operation_id)){
                    change("complete");try{storage.removeItem(key);}catch{}return snapshot();
                }
                if(response.status===202 && data?.report_deleted===true && ["PENDING","FAILED"].includes(data.cleanup_state) && data.number===number && uuid4.test(data.operation_id))change("pending");
                else if([401,403].includes(response.status))change("forbidden");
                else if(response.status===404)change("missing");
                else if(response.status===409)change("conflict",["deletion_operation_conflict","unsafe_deletion_storage"].includes(data?.code)?data.code:"");
                else if(response.status===400)change("invalid");
                else change("uncertain");
            } catch {change("uncertain");}
            record.state=kind;try{persist();}catch{ /* Initial journal remains a safe recovery record. */ }
            return snapshot();
        }
        function run(numberTyped,recovery){
            if(pending)return pending;
            if(kind==="journal_error"||kind==="complete")return Promise.resolve(snapshot());
            if(!recovery && numberTyped!==number){change("confirmation");return Promise.resolve(snapshot());}
            // Read durable intent again before creating one; this also reconciles another tab.
            try {
                const raw=storage.getItem(key);
                if(raw){const existing=JSON.parse(raw);if(!valid(existing,userId,reportId)||existing.number!==number)throw new Error();record=existing;}
                if(!record){
                    if(recovery)throw new Error();
                    record={schema:1,userId:String(userId),reportId,number,operationId:operation(environment.crypto),state:"uncertain"};
                }
            }catch{change("journal_error");return Promise.resolve(snapshot());}
            pending=Promise.resolve().then(request).finally(()=>{pending=null;notify(snapshot());});
            notify(snapshot());return pending;
        }
        return {snapshot,submit:numberTyped=>run(numberTyped,false),recover:()=>run(null,true)};
    }
    function mount(root,environment){
        const field=name=>root.querySelector(`[data-delete-${name}]`);
        const dialog=field("dialog"),form=field("form"),open=field("open"),input=field("number");
        if(!dialog?.showModal||!form||!open||!input)return null;
        const client=createClient({...root.dataset,userId:root.dataset.userId,reportId:root.dataset.reportId,
            url:root.dataset.deleteUrl,environment:{localStorage:safeStorage(environment),crypto:environment.crypto,
                location:environment.location,AbortSignal:environment.AbortSignal,fetch:environment.fetch.bind(environment),
                csrf:()=>root.querySelector('[name="csrfmiddlewaretoken"]').value},notify:update});
        let previousOverflow;
        function update(){
            const state=client.snapshot();
            field("status").textContent=message(state);
            input.disabled=state.busy||!!state.record;
            field("confirm").hidden=!!state.record;
            field("confirm").disabled=state.busy||input.value!==root.dataset.number||state.kind==="journal_error";
            field("cancel").disabled=state.busy;
            field("recover").hidden=!state.recoverable;
            field("recover").disabled=state.busy;
            field("recover").textContent=state.kind==="pending"?"Retomar limpeza":"Verificar exclus\u00e3o";
            field("library").hidden=state.busy;
        }
        async function send(recovery){
            const state=await (recovery?client.recover():client.submit(input.value));
            if(state.kind==="complete")environment.location.assign(root.dataset.libraryUrl);
        }
        open.hidden=false;
        open.addEventListener("click",()=>{update();dialog.showModal();previousOverflow=environment.document.body.style.overflow;environment.document.body.style.overflow="hidden";input.focus();});
        function close(){if(client.snapshot().busy)return;dialog.close();environment.document.body.style.overflow=previousOverflow;open.focus();}
        field("cancel").addEventListener("click",close);
        dialog.addEventListener("cancel",event=>{event.preventDefault();close();});
        form.addEventListener("submit",event=>{event.preventDefault();if(!field("confirm").disabled&&!field("confirm").hidden)void send(false);});
        input.addEventListener("input",update);
        field("recover").addEventListener("click",()=>{if(!field("recover").disabled&&!field("recover").hidden)void send(true);});
        update();return {client};
    }
    function safeStorage(environment){try{return environment.localStorage;}catch{return null;}}
    function mountRecovery(root,environment){
        const storage=safeStorage(environment),list=root.querySelector("[data-deletion-recovery-list]");
        if(!storage||!list)return;
        const records=[];
        try{
            for(let i=0;i<storage.length;i++){
                const key=storage.key(i);if(!key?.startsWith(prefix(root.dataset.userId)))continue;
                const record=JSON.parse(storage.getItem(key));
                if(!valid(record,root.dataset.userId,key.slice(prefix(root.dataset.userId).length)))throw new Error();
                records.push(record);
            }
        }catch{root.hidden=false;list.textContent=messages.journal_error;return;}
        root.hidden=records.length===0;
        for(const record of records){
            const row=environment.document.createElement("article"),label=environment.document.createElement("p"),button=environment.document.createElement("button");
            const client=createClient({...record,url:root.dataset.urlTemplate.replace("00000000-0000-0000-0000-000000000000",record.reportId),
                environment:{localStorage:storage,crypto:environment.crypto,location:environment.location,AbortSignal:environment.AbortSignal,
                    fetch:environment.fetch.bind(environment),csrf:()=>root.querySelector('[name="csrfmiddlewaretoken"]').value},
                notify(){const state=client.snapshot();label.textContent=record.number+": "+message(state);button.disabled=state.busy||!state.recoverable;}});
            label.setAttribute("role","status");label.setAttribute("aria-live","polite");
            label.textContent=record.number+": "+message(client.snapshot());
            button.type="button";button.textContent="Verificar / retomar exclus\u00e3o";
            button.addEventListener("click",async()=>{if(button.disabled)return;const state=await client.recover();if(state.kind==="complete")environment.location.assign(root.dataset.libraryUrl);});
            row.append(label,button);list.append(row);
        }
    }
    return {createClient,mount,mountRecovery};
}));
