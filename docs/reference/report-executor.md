# Executor independente de relatórios — etapa 2

Modo supervisionado opcional e migration 0017:
[report-systemd-supervision.md](report-systemd-supervision.md). Defaults continuam desabilitados.

Diagnóstico administrativo e limite atual da recuperação:
[report-recovery.md](report-recovery.md). Sem liberação do slot por confirmação humana.

## Escopo e operação manual

`signaling.report_executor.execute(attempt_id=None)` processa, no máximo, a única
intenção persistida no slot global. O comando `execute_admitted_report` executa o
serviço em primeiro plano, fora do Gunicorn, sem polling, fila ou retomada automática.
Não existe integração HTTP/UI nova, systemd, CD ou alteração no servidor nesta etapa.

`REPORT_EXECUTOR_ENABLED=false` por padrão. Em homologação autorizada, configurar
explicitamente essa flag, PostgreSQL, `REPORT_PRIVATE_ROOT` e o executável LibreOffice
quando necessário. O runtime precisa também de `requirements-pdf-poc.txt` para pypdf.
Não habilitar a publicação em produção. Desabilitar novas admissões não revoga as já
confirmadas: o executor não depende de `REPORT_ADMISSION_ENABLED` nem da flag legada.

```text
python manage.py execute_admitted_report
python manage.py execute_admitted_report --attempt-id <UUID-da-tentativa>
```

Sem UUID, o comando descobre o ocupante atual do slot. Slot vazio imprime
`no_admitted_report` e termina com sucesso. Com UUID, inexistência ou ausência de
titularidade é erro. Sucesso imprime `FINALIZED <UUID>`. Repetir explicitamente uma
tentativa admitida já FINALIZED retorna o resultado sem conversão adicional.
Os erros são códigos de domínio via CommandError (saída diferente de zero), sem
caminhos, dados do documento, credenciais ou diagnósticos privados do LibreOffice.

## Fluxo e invariantes

1. `claim` exige PostgreSQL, gate explícito e autocommit. Sob a coordenação da etapa
   1, verifica titularidade, integridade e estado ADMITTED. Na mesma transação,
   rotaciona `execution_id` na tentativa e no slot e muda para PROCESSING.
2. Carrega snapshot e fotos por `report_admission.load_inputs`. Não consulta sessão,
   reserva, usuário corrente, rascunho ou ponto atual para autorizar a execução.
3. Usa `report_snapshots.render_snapshot`, revalida fencing e chama
   `pdf_conversion.convert_docx_to_pdf`, com `pdf_process` supervisionando o subprocesso.
4. Valida o PDF; sob fencing muda PROCESSING para STORING.
5. Reutiliza `report_finalization._store` com o fence da admissão para gravar e
   verificar DOCX/PDF privados. O caminho síncrono continua usando seu fence original.
6. `_complete` confirma artefatos, FINALIZED, `finalized_at`, `number_assigned_at`
   e liberação dos dois campos do slot **na mesma transação**.

Não existe geração ou I/O de arquivos dentro dessas transações de execução. O
snapshot, emissão, autoria e número reservados na admissão não são substituídos.
O contador anual não é consultado ou incrementado pelo executor.

`assert_execution` mantém slot/tentativa bloqueados durante cada gravação de
metadados. Uma execução antiga não pode registrar novos artefatos nem confirmar
depois de perder seu execution_id/titularidade. Arquivos gravados antes de perder
o fence podem permanecer sem referência; não são apagados no caminho de exceção.

Dois executores podem tentar assumir a mesma intenção; somente um troca ADMITTED
por PROCESSING. O outro recebe `publication_busy` durante contenção ou
`execution_already_started` após a transição. Nenhum deadline permite reassumir.
Não se mantém advisory lock de sessão nem transação durante a conversão: o estado
persistente impede uma segunda execução, mesmo depois de perder a conexão.

## Falhas, interrupção e recuperação

| Situação | Estado e ação |
| --- | --- |
| Geração, conversão, timeout, PDF inválido ou armazenamento | FAILED, erro seguro e slot preservado, quando o registro da falha é confirmado |
| SIGINT/SIGTERM ou KeyboardInterrupt controlado após claim | INTERRUPTED e slot preservado; o finally do supervisor encerra a árvore do conversor |
| Falha ao confirmar a própria falha | Mantém o último estado confirmado e o slot; exige investigação |
| Perda de conexão/ack de commit | `execution_database_state_unknown`; não tenta rebaixar FINALIZED ou liberar/reassumir um slot |
| SIGKILL, os._exit ou queda da máquina | Pode permanecer PROCESSING/STORING; nenhuma conclusão de morte/limpeza é inferida |
| Tentativa FAILED/INTERRUPTED executada novamente | `admission_reconciliation_required`; nenhuma conversão |

O comando instala handlers temporários de SIGINT/SIGTERM e restaura os anteriores
ao terminar. Novos SIGINT/SIGTERM durante a limpeza controlada são ignorados. Uma
interrupção durante claim/commit pode não permitir registrar INTERRUPTED; o comando
informa estado desconhecido. O handler não substitui a supervisão do SO.

Após erro, consultar tentativa, slot, artefatos e logs. Em ack ambíguo, FINALIZED com
slot livre significa que o commit concluiu: repetir o UUID é somente leitura.
PROCESSING/STORING/FAILED/INTERRUPTED com slot ocupado exige preservar entradas e
confirmar externamente a morte do processo e de seus descendentes antes de qualquer
recuperação. **Não há comando de unlock, force ou retry automático nesta etapa.**

`reconcile_report_finalizations` continua auditando/limpando conservadoramente, sem
expirar ou liberar execuções admitidas. FAILED/INTERRUPTED não são prova de que todos
os descendentes morreram. A exclusão física auditada não foi alterada; publicação
concluída fica disponível ao mecanismo existente depois da liberação transacional.

## Compatibilidade e migrations

Nenhuma migration nova. Estados e campos de `0015_persistent_report_admission` e
constraint de `0016_admission_invariants` são suficientes; `deadline` permanece NULL
na execução independente. As migrations são pré-requisito, a aplicar manualmente
somente em ambiente autorizado; não foram aplicadas no banco principal nesta tarefa.

O caminho síncrono permanece separado. Os defaults de admissão, executor e
finalização continuam desabilitados. Não há alteração de frontend ou rota que passe
a retornar 202 para admitir trabalho sem contrato HTTP completo.

## Validação e próxima etapa

`signaling.test_report_executor_postgresql` cobre sucesso com renderizador e
LibreOffice reais, concorrência entre conexões, processo filho encerrado após claim,
fencing, SIGTERM controlado, perda de conexão e falhas/acks de commit. As substituições
do pipeline são restritas a cenários de falha. Testes de sucesso real são pulados
explicitamente se LibreOffice/pypdf estiverem ausentes; skip não comprova conversão.

Executar junto às suítes de admissão/finalização/reconciliação e ao supervisor:

```text
python manage.py test signaling.test_report_executor_postgresql signaling.test_report_admission_postgresql signaling.test_report_finalization_postgresql signaling.test_report_finalization signaling.test_report_reconciliation signaling.test_pdf_conversion
```

Para systemd futuramente: escolher disparo do comando sem recriar admissão;
configurar usuário, ambiente, diretório privado persistente e executável/fontes;
supervisionar todo o grupo/cgroup, dar tempo à limpeza e definir limites de recursos;
estabelecer drenagem durante deploy e prova de término antes de recuperação com
novo fencing. Reiniciar cegamente o comando não retoma PROCESSING/STORING. No Ubuntu,
SIGKILL do Python pode deixar conversor em sessão própria e temporários: um serviço
futuro deve encerrar todo o cgroup e limpar temporários com uma política segura.

Aceite visual, comportamento real de sinais no Ubuntu, reinício da VM, quotas,
durabilidade conjunta banco/filesystem e recuperação administrativa continuam
pendentes de homologação operacional. Validação estrutural do PDF não substitui
verificação visual nem constitui assinatura digital.

Os limites existentes supervisionam o conversor, não o consumo total do processo
Django nem um timeout global da geração DOCX. Um travamento fora do conversor pode
exigir encerramento operacional, sempre preservando o slot para reconciliação.
