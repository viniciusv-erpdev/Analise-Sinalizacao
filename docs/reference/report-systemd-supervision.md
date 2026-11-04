# Supervisão do executor — preparação 4A

Contratos posteriores de lançamento persistente e barreira operacional:
[report-operational-contracts.md](report-operational-contracts.md). Não há launcher
ou recuperação habilitados.

## Escolha e escopo

| Estratégia | Vantagens | Custos e limites |
| --- | --- | --- |
| Unidade transitória por publicação, Type=exec | Nome aleatório por intenção de execução, cgroup próprio, correlação direta com invocação e release | Precisa de operador/launcher confiável; unidade pode ser coletada e perder histórico no manager |
| Unidade permanente oneshot, iniciada sob demanda | Configuração instalada simples e caminho de lançamento fixo | Reutiliza nome/cgroup entre invocações; exige correlação histórica adicional e impedir restart/timer durante reconciliação |

Escolhida: **unidade transitória por intenção de execução**. A preparação está no
repositório, mas não foi instalado/iniciado serviço, launcher privilegiado, timer,
regra sudo/Polkit ou integração HTTP. A documentação do
[systemd-run](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html)
descreve o lançamento transitório; validar a versão efetiva na VM antes do uso.

Um operador autorizado do SO será o iniciador na homologação futura. Não conceder
ao Gunicorn permissão de gerenciar unidades. Um broker automatizado futuro deve
aceitar somente UUID de intenção, resolver usuário/binário/ambiente em catálogo
root-owned de releases autorizadas e limitar propriedades/nome/argv. Não aceitar
comando, caminho, EnvironmentFile ou propriedade systemd vindo do HTTP ou confiar
cegamente em valores gravados por um usuário do banco com privilégios amplos.

## Componentes implementados

- `ReportExecutionIdentity`: intenção persistente e vínculo operacional, separados
  de estado da publicação. Não é lease nem prova de encerramento.
- `report_supervision.prepare`: valida ADMITTED e fencing sob coordenação global;
  persiste UUID próprio, próxima epoch, nome e contexto do host/release antes de
  qualquer lançamento. Repetição da mesma intenção retorna o mesmo registro.
- `report_systemd_runtime.capture`: observação Linux e consulta **somente show** do
  system manager por `/usr/bin/systemctl`, sem shell, com timeout e ambiente reduzido.
- `report_supervision.bind`: vincula observação validada e novo execution_id na mesma
  transação que faz ADMITTED → PROCESSING. Nenhuma geração ocorre antes do commit.
- `execute_supervised_report`: entry point para a unidade, com os handlers de sinais
  existentes. Não cria ou encerra unidades. O executor reutiliza DOCX/PDF/storage.
- Diagnóstico existente inclui identidades operacionais sem caminhos do checkout ou
  nomes de usuários. Continua declarando prova de encerramento indisponível.

## Contrato da identidade

O registro contém UUID único, referência histórica da tentativa, execution_id
esperado e próximo, machine-id do host, boot-id, nome único de unidade, release e
raiz do checkout, conta de serviço configurada e datas de preparação/vínculo. No vínculo recebe
InvocationID, cgroup/path/inode, MainPID e ticks de criação do processo.

Identidade planejada não equivale a unidade iniciada. InvocationID/cgroup/PID são
preenchidos juntos ou todos permanecem NULL. Constraints impedem nomes/epochs
repetidos e reutilização de invocação no mesmo host/boot. O serviço não reescreve
identidades e o ORM protege campos congelados; SQL administrativo continua sendo
uma fronteira de confiança. A FK SET_NULL preserva a exclusão física auditada, sem
reter conteúdo, fotos ou autoria do relatório; a referência histórica UUID permanece.

O InvocationID identifica um ciclo de execução da unidade, segundo o
[systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
Ele é comparado entre ambiente do processo e manager, não aceito isoladamente.
O processo precisa ser o MainPID da unidade esperada, no host/boot preparados,
release configurada e cgroup v2 `/system.slice/<nome-exato>`. Executar via wrapper
shell ou em unidade de usuário não atende a esse contrato.

São recusados root, capabilities efetivas, cgroup gravável, Delegate=yes,
NoNewPrivileges ausente, ProtectControlGroups diferente de yes, Type diferente de
exec, KillMode diferente de control-group, Restart diferente de no, manager sem
invocação válida ou estado fora de activating/active. Antes de converter e antes
de confirmar, o contexto é observado novamente e comparado ao registro persistido.
Essas verificações são fora de transações; cada confirmação ainda usa o fencing
transacional existente. As observações não são assinatura/atestação de um supervisor.

## Preparação e início: corridas e falhas

Em homologação autorizada, com PostgreSQL e migration 0017 aplicada manualmente:

```text
python manage.py prepare_report_supervision --attempt-id <UUID> --expected-execution-id <EPOCH-ATUAL>
```

Requer `REPORT_SYSTEMD_SUPERVISION_ENABLED=true`, release hexadecimal de 40–64
caracteres em `REPORT_EXECUTOR_RELEASE_ID` e `REPORT_EXECUTOR_SYSTEMD_USER` não privilegiado.
A flag tem default false e não foi ativada. O comando retorna identity_id,
execution_id, unit_name e release_id; `unit_started` permanece false.

O operador futuro valida o plano e cria a unidade transitória com propriedades do
[exemplo](../../deploy/report-transient.service.example). O único entry point será:

```text
python -B manage.py execute_supervised_report --identity-id <IDENTITY-UUID>
```

Não executar esse entry point fora de sua unidade: ambiente INVOCATION_ID forjado,
PID informado ou ausência de processo não autorizam o claim. A execução também exige
`REPORT_EXECUTOR_ENABLED=true`, mantida false por padrão. Não há chamada systemd
privilegiada no serviço HTTP, na admissão ou nos comandos preparados.

| Interrupção | Resultado seguro |
| --- | --- |
| Antes de preparar | Nenhuma identidade/unidade nova |
| Depois de preparar, antes de iniciar | ADMITTED + identidade sem vínculo; não inferir que a unidade nunca iniciou só porque não vinculou |
| Durante observação | Sem autorização de publicação; falha impede claim |
| Durante commit de vínculo | Identidade e PROCESSING/epoch confirmam juntos ou fazem rollback; ack perdido é estado desconhecido |
| Após vínculo, antes/durante geração | Slot ocupado; reinício com o mesmo identity_id é recusado |
| Antes do commit final | Fencing valida epoch; identidade/ambiente alterados impedem conclusão |
| Após commit final com ack perdido | FINALIZED e slot liberado atomicamente; não gerar nova publicação |

Dois preparadores da mesma epoch produzem uma intenção. Dois executores não
conseguem vincular/publicar simultaneamente. Plano criado bloqueia o caminho manual
para aquela epoch mesmo após desligar a flag; com o modo supervisionado habilitado,
novas execuções manuais sem identidade também são recusadas. Com a flag desligada
e sem plano, o executor manual anterior permanece compatível.

Não reutilizar/recriar nomes de unidade depois de start incerto, GC ou perda de
histórico. O código não emite uma segunda identidade para a mesma epoch. Um futuro
launcher deve persistir o pedido de início antes de StartTransientUnit e resolver
ack ambíguo sem reenviar start cegamente. Ainda não existe esse launcher/registro
de pedido de início: o início é manual e a disciplina operacional não é prova de
encerramento. Root pode recriar unidade/alterar banco; isso não é impedido por Python.

## Descendentes, sinais e recursos

O exemplo usa KillMode=control-group, SIGTERM, escalonamento SIGKILL, Restart=no,
Delegate=no, capabilities vazias, NoNewPrivileges e ProtectControlGroups=yes.
A política de parada do grupo segue
[systemd.kill](https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html).
Os valores de memória, tempo, TasksMax e grace period do exemplo são hipóteses para
medição, não limites homologados. Não instalar o arquivo como unidade reutilizável.

O supervisor Python existente mantém timeout e limpeza controlada do conversor.
A nova sessão POSIX do LibreOffice não altera, por si só, a herança do cgroup;
a hierarquia e a possibilidade de migração estão descritas em
[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html). O processo da aplicação
não deve ter permissão para migrar grupos; terceiros privilegiados ainda podem fazê-lo.
Capture inicial e rechecagens não provam ausência de migração de um descendente.

Usar release imutável, usuário não privilegiado sem shell administrativo nem acesso a
sudo/Polkit, código somente leitura, credenciais fora do checkout e storage privado
persistente separado. O PrivateTmp do exemplo isola temporários da unidade e o
conversor já cria workspaces/perfis separados. Nenhuma rotina nova apaga temporários
ou arquivos ambíguos por idade. Homologar fontes, matplotlib, LibreOffice e sandbox
sem aumentar privilégios indiscriminadamente quando houver incompatibilidade.

## Estado observado não é prova de encerramento

| Observação | Interpretação permitida |
| --- | --- |
| Manager ativo, mesma invocação/host/boot | Contexto de execução observado, não garantia de estado futuro |
| Inactive/failed, invocação histórica correspondente | Evento terminal parcial; falta comprovar o grupo inteiro e ausência de escape |
| Unidade ausente, InvocationID vazio, acesso negado ou histórico coletado | UNKNOWN; ausência e histórico perdido não são distinguíveis com segurança por uma consulta show |
| Novo boot | Incompatibilidade com o plano antigo; não é autorização automática de recuperação |
| Cgroup vazio ou removido | Insuficiente sem histórico confiável, vínculo da identidade e controle de migração |

Não há prova de término verificada, liberação administrativa de slot ou recuperação
por timeout/PID/heartbeat. FAILED/INTERRUPTED e planos não vinculados continuam
exigindo reconciliação segura. Execuções históricas sem identidade não recebem
uma identidade retroativa que pretenda provar sua origem.

## Reboot e CD

`release_id` é um identificador fornecido pela configuração confiável, não uma
atestação criptográfica do conteúdo inteiro do checkout. O código não impede
um agente externo privilegiado de sobrescrever essa release.

Plano do boot anterior é recusado no novo boot, sem renomear, reassumir ou liberar
slot. Unidade transitória desaparecida após reboot é histórico indisponível.
Registrar o boot melhora correlação, mas não resolve host clonado, múltiplos hosts
ou attestação de quem observou esse boot; a recuperação permanece bloqueada.

Nenhuma mudança foi feita no CD. Para habilitar futuramente, o deploy deve impedir
novos lançamentos, drenar ou parar grupos pelo supervisor, preservar identidades e
evidências, manter release/venv/fontes antigas até concluir a execução e só depois
trocar código. Nunca sobrescrever o diretório usado por uma unidade em execução.
Restart=no e recusa de identidade já vinculada impedem reexecução da publicação
pelo mesmo plano; não impedem um CD/root de interromper o processo. Sem drenagem
implantada e homologada, não habilitar o novo modo em produção.

## Migration, testes e homologação Ubuntu

Migration nova: `0017_report_execution_identity`, dependente de 0016. Sem backfill
de identidade para publicações antigas. Não aplicada ao banco principal nesta etapa.

```text
python manage.py migrate --plan
python manage.py migrate signaling 0017_report_execution_identity
python manage.py test signaling.test_report_supervision signaling.test_report_supervision_postgresql
```

Testes unitários usam observações sintéticas para validar recusas. Testes PostgreSQL
verificam concorrência real, atomicidade, fencing, imutabilidade, diagnóstico e
exclusão física; a geração DOCX/PDF usa as implementações reais quando disponíveis.
Isso não certifica integração systemd no Ubuntu. Nenhuma unidade foi iniciada nos testes.

Procedimento futuro, não executado nesta tarefa:

1. Usar VM/banco/storage exclusivos de homologação e revisar migration/configuração.
2. Verificar versões de systemd/cgroup v2, propriedades disponíveis, máquina/boot
   e preservação de identidade; validar o exemplo sem instalá-lo automaticamente.
3. Usar o mesmo usuário Unix não privilegiado do Gunicorn, conferir ownership e
   acesso ao storage 0600/0700 e política operacional fora do Gunicorn; separar papéis SQL de HTTP, preparação
   e executor antes de automatizar o dispatcher.
4. Com autorização operacional posterior, habilitar flags só na homologação,
   preparar uma identidade e iniciar exatamente uma unidade transitória por operador.
5. Conferir identidade no PostgreSQL antes da geração, MainPID/InvocationID/cgroup,
   readonly do cgroup e pertencimento de TODOS os descendentes, inclusive LibreOffice.
6. Ensaiar sucesso, SIGTERM, SIGKILL, OOM/tempo limite, falha PostgreSQL em commits,
   GC/perda de histórico, tentativa de restart/nome repetido e reboot. Preservar slot
   e arquivos nos cenários incertos; não criar comandos SQL de unlock como atalho.
7. Ensaiar drain/deploy com release imutável. Registrar tempos/RAM/disco, fontes e
   equivalência visual. Rejeitar habilitação se acesso ao manager ou sandbox exigir
   privilégios excessivos para a aplicação.

## Antes de implementar recuperação

### Decisão aprovada: mesmo usuário Unix e storage privado

O storage existente cria diretórios 0700 e arquivos 0600, inclusive com chmod
explícito após criação. As fotos são gravadas pela admissão no processo HTTP e os
arquivos finais precisam ser lidos pelo HTTP no download. Usuários Unix distintos
não são compatíveis com esse acesso bidirecional sem uma política adicional.
ReadWritePaths permite escrita no sandbox, mas não concede permissões Unix sobre
arquivos de outro usuário. ACL padrão isolada também pode ser neutralizada pelo chmod.

Foi aprovado usar o mesmo usuário Unix não privilegiado do Gunicorn, com unidade
isolada e sem permissão de gerenciar systemd. Não foram alterados modos, owners,
ACLs, storage ou contas:

- Mesmo usuário Unix não privilegiado: preserva 0600/0700 e não exige permissões
  systemd no Gunicorn. Os processos permanecem isolados pela unidade, mas a
  separação entre HTTP e executor por UID não existe (mesmo UID pode sinalizar ou
  acessar arquivos do outro). Esta é a alternativa escolhida.
- Usuários distintos: melhor separação por identidade Unix, mas requer projetar e
  revisar ACLs/modos/criação de arquivos ou um intermediário restrito para o storage,
  em etapa própria, incluindo leitura dos PDFs pelo HTTP. Não improvisar chmod amplo.

`REPORT_EXECUTOR_SYSTEMD_USER` deve ser configurado explicitamente com o nome dessa
conta existente; o default vazio impede preparar uma execução sem essa configuração.
O exemplo usa APP_USER/APP_GROUP, sem criar contas. Os testes locais não certificam
o isolamento operacional na VM nem permissões entre contas Unix distintas.

### Prova de término permanece pendente

Falta uma autoridade externa confiável que vincule pedidos de início, identidade e
evento terminal durável, impeça relançamento enquanto verifica o grupo e comprove
ausência de processos/descendentes migrados. Também faltam tratamento autenticado
de reboot/múltiplos hosts, permissões SQL/OS implantadas e testes operacionais.
Somente depois: recuperação com epoch esperada, prova validada, locks, nova epoch
e auditoria transacional. Esta entrega não resolve essas lacunas com uma flag booleana.
