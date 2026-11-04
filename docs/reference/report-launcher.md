# Lançador mínimo — implementação local 4C.3B

Não instalado, não iniciado, não habilitado. Nenhuma chamada real a systemd foi
feita. As flags Django continuam com os defaults anteriores. O dispatcher 4C.2
continua exclusivamente diagnóstico. Não existe recuperação administrativa.

## Componentes e fronteira privilegiada

`report_launcher/` é um pacote independente, instalável pelo seu próprio
`pyproject.toml`. Não importa Django, signaling ou config; não chama subprocess,
shell, systemctl ou systemd-run. Dependências isoladas em requirements-launcher.txt.
O processo privilegiado usa Python isolado (`-I`), pacote/venv controlados por root,
psycopg e uma chamada D-Bus tipada StartTransientUnit. Nunca usa o venv Django para
executar seu entry point e nunca executa manage.py como root.

O serviço futuro recebe exatamente um socket AF_UNIX/SOCK_SEQPACKET do systemd,
no FD 3, caminho `/run/analise-report-launcher/control.sock`. Recusa outros tipos,
manual bind, mais FDs, usuário não root, plataforma não Linux e argumentos extras.
Verifica as contas distintas analise_dispatch/analise_app, UID configurado, grupo
do socket, diretório root:analise_dispatch 0750 e socket 0660. Recusa analise_app
como membro do grupo do dispatcher.

Cada pacote é autenticado por SO_PASSCRED/SCM_CREDENTIALS do kernel. Ausência,
duplicidade, truncamento, UID incorreto e ancillary data inesperada são recusados.
SCM_RIGHTS é recusado e os FDs recebidos são fechados. Repasse de conexão não dá
autoridade a outro UID. PID/GID não substituem a validação de UID por mensagem.
Pacote até 4096 bytes, timeout 5 s, uma solicitação por conexão, processamento
serial, backlog 8 no exemplo e limite de 8 mensagens válidas/s por instância.
Esse limite local reduz abuso; não participa da exclusividade da publicação.

## Protocolo v1

```json
{"protocol":1,"operation":"start","request_id":"UUID","launch_id":"UUID","expected_barrier_generation":"UUID"}
```

`status` aceita somente protocol, operation, request_id e launch_id. UUIDs devem
ser canônicos; a geração da barreira admite UUID zero (OPEN implícito). Campos
extras/duplicados e outras operações são recusados. Nenhum comando, argv, path,
EnvironmentFile, unidade, usuário, variável de ambiente ou propriedade systemd é
recebido do solicitante. Não existe stop, restart, kill, cancel ou recover.

Respostas têm códigos estáveis: STATUS, ALREADY_CONSUMED, UNCERTAIN, JOB_OBSERVED,
ou código de rejeição. Não contêm dispatch_id/ticket, snapshot, senhas ou paths.
STATUS apenas lê PostgreSQL: não confirma liveness nem consulta o manager.

## PostgreSQL e ponto de autorização

Migrations novas:

- 0019_report_launcher_receipt: recibo imutável, OneToOne com ReportLaunch; UUID de
  solicitação, dispatch_id, geração autorizadora, UID, host/boot e hashes da política,
  manifesto e inventário. Não guarda dados pessoais do relatório.
- 0020_launcher_sql_contract: funções SECURITY DEFINER, search_path pg_catalog,
  referências às tabelas qualificadas e EXECUTE revogado de PUBLIC. Não cria roles,
  não concede privilégios a runtimes nem configura pg_hba.

Interfaces: report_launcher_envelope, report_launcher_status,
report_launcher_consume e report_launcher_job. report_dispatch_projection é uma
view reduzida, sem snapshot, fotos, autoria ou credenciais, para uso futuro.

O launcher lê um envelope limitado e valida hashes/contrato/entradas persistidas
com código JSON puro, sem importar a aplicação. Verifica catálogo local, host/boot,
unidade derivada, conta, slot/epoch, snapshot, fonte, número e metadados de fotos.
Não lê os arquivos privados: o executor mantém a validação dos bytes.

Após a validação cara, consume adquire o MESMO mutex transacional PostgreSQL
(182736,1), bloqueia slot/tentativa/identidade/lançamento, compara o envelope atual
ao previamente validado e revalida estado e geração da barreira. REQUESTED vira
UNCERTAIN; recibo, dispatch_id e evento LAUNCHER_CONSUMED confirmam juntos.
Recebimento de novo ticket só é retornado após ACK do commit no adapter psycopg.

Só o chamador que recebe `fresh=true` pode tentar uma chamada. Recibo existente
nunca devolve uma nova autorização, mesmo com novo request_id ou após reboot.
UNCERTAIN antigo sem recibo também não é reassumido. request_id reutilizado para
outro lançamento não é aceito. O SQL não mantém transação durante a chamada D-Bus.
O begin_dispatch Python antigo permanece para compatibilidade dos contratos
anteriores; seu ticket NÃO é aceito pelo protocolo do launcher. O futuro dispatcher
nunca deve chamá-lo: o consumo novo pertence exclusivamente à interface SQL da
autoridade, com recibo. Não conceder essa interface ao papel dispatcher.

Falha antes do consumo deixa REQUESTED. ACK do commit perdido impede a chamada.
Queda depois do consumo, timeout, unidade já existente, erro D-Bus, resposta perdida
ou falha ao registrar job conservam UNCERTAIN. Não há reenvio automático. Isso
oferece no máximo uma tentativa de chamada por autorização, não exactly-once entre
dois sistemas. Uma autorização confirmada antes da barreira pode estar em trânsito;
o registro pendente impede DEPLOYING. Não se promete atomicidade SQL/D-Bus.

Job retornado é registrado idempotentemente, mas NÃO vira CONFIRMED: observação de
InvocationID/eventos terminais e prova durável serão integradas posteriormente.
O executor atual pode fazer bind legítimo em UNCERTAIN, preservando execution_id,
snapshot/número e liberação final transacional. Histórico operacional continua
bloqueando nova admissão/deploy segundo 4C.1, sem liberação automática.

## Privilégios e auditoria

Exemplo NÃO executado: deploy/report-launcher-grants.sql.example. O owner das funções
deve ser NOLOGIN/não superuser, com os direitos internos necessários. Runtime do
launcher recebe somente EXECUTE; dispatcher somente SELECT na projeção. Sem DDL,
privilégio direto de escrita ou associação a roles elevadas. O serviço recusa
inicialização com role superuser/createdb/createrole/bypassrls, memberships, CREATE
no public, escrita direta nas tabelas signaling ou owner de função privilegiado.

Também é obrigatório separar o usuário de migrations do usuário PostgreSQL do
Gunicorn, retirar acesso a aprovação de releases/recibos/funções do launcher e
auditar grants herdados/PUBLIC. O exemplo não configura toda a política SQL Django.
Se o runtime HTTP ainda for owner/admin do DB, a integração NÃO está homologada.
Superuser PostgreSQL/root/kernel permanecem fronteiras de confiança.

O exemplo de sandbox permite somente AF_UNIX. Usar conexão PostgreSQL local por
socket Unix, com role própria e mapeamento peer específico ou autenticação revisada
em pg_hba; não copiar o DSN TCP do ambiente de testes. Nunca colocar a senha do
launcher no ambiente do Gunicorn/dispatcher ou em um arquivo legível por eles.

Aceites e job observado ficam em ReportOperationalEvent. Rejeições/resultado
incerto são JSON de códigos e IDs validados em stdout/journald; nunca payload
bruto, texto de exceção, SQL, DSN ou propriedades com ambiente. UID vem do kernel;
credencial malformada usa -1. O exemplo limita logs. Conexão negada pelo filesystem
ocorre antes da aplicação e depende de auditoria do SO. Journald não substitui
estado autoritativo nem prova de término. Perda de auditoria não libera estado.

## Catálogo, inventário e unidade

Configuração fixa: /etc/analise-report-launcher/catalog.json e database.dsn;
segundo arquivo root 0600 e catálogo sem escrita por outros usuários. O exemplo
de catálogo tem enabled=false e nenhuma release. Nunca copiar um UID fictício.
Atualizações do catálogo exigem drenagem e restart operacional do launcher; o
catálogo é carregado no início. Não editar arquivos de release existentes.

Cada release autorizada mapeia ID para root absoluto, environment_file root 0600,
manifest_sha256 e bundle_sha256. manifesto em `<root>/manifest.json`:

```json
{"protocol":1,"release_id":"ID","contract":{"admission":1,"snapshot":1,"renderer":1,"launcher":1},"files":[{"path":"manage.py","sha256":"SHA256"}]}
```

O exemplo acima é apenas formato; inventário completo precisa incluir manage.py,
.venv/bin/python, .venv/pyvenv.cfg e TODOS os arquivos da árvore, sem extras.
manifest_sha256 é hash dos bytes exatos do manifesto. bundle_sha256 v1 é SHA-256
do JSON canônico da lista `files` (sort_keys, separadores compactos, ensure_ascii),
comprometendo paths e hashes de conteúdo; não é hash de um tar comprimido. A
aprovação DB e catálogo root devem usar a MESMA definição e os mesmos valores.

Todos os arquivos/diretórios e ancestrais devem ser root-owned e não graváveis
por grupo/outros. Paths relativos são normalizados; traversal e arquivos especiais
são recusados. Inventário v1 rejeita TODOS os symlinks, inclusive os comuns de venv.
O build deve usar cópias e normalização auditada; não presume compatibilidade do
venv atual nem relocabilidade entre prefixes/hosts. Executável fixo é
`<root>/.venv/bin/python -B <root>/manage.py execute_supervised_report --identity-id <UUID>`.
Proibir alteração em uso é indispensável: root malicioso ou CD que sobrescreva a
árvore permanece fora da garantia de hashes observados.

EnvironmentFile aceita somente chaves enumeradas no código, linhas simples sem
continuações, sem PYTHONPATH/PYTHONHOME/LD_*; rejeita duplicatas. Exige backend
PostgreSQL, debug false, release/conta/storage correspondentes e flags do executor
e supervisão true no AMBIENTE FUTURO APROVADO. Nenhum arquivo de ambiente foi criado
ou flag ativada nesta entrega. Secrets devem seguir a sintaxe systemd admitida.

unit_properties fixa Type=exec, analise_app, Restart=no, KillMode=control-group,
SIGTERM/SIGKILL, Delegate=no, capabilities vazias, NoNewPrivileges, cgroup protegido,
sandbox de filesystem/temporários e escrita somente no root privado configurado.
Execução real ocorre no system manager; o launcher não faz fork/exec do Django.
Limites dos exemplos ainda são hipóteses de homologação, não valores certificados.

## CD futuro: mudanças obrigatórias, NÃO implementadas

1. Build/testes sem privilégios em ambiente equivalente ao Ubuntu alvo; construir
   venv normalizado com Python/dependências/fontes compatíveis e prefix adequado.
2. Produzir wheel independente do launcher e inventário/manifesto da aplicação;
   verificar artefatos antes da promoção. Não executar hooks/build/Django como root.
3. Adquirir barreira DRAINING, impedir novos inícios e exigir DEPLOYING antes de
   alterar instalações. Hoje histórico sem prova bloqueia deploy: não criar bypass.
4. Promover artefato NOVO para diretório versionado root-owned; nunca git pull,
   pip install, sobrescrita ou chown em release em uso. Não usar `current` no plano.
5. Aplicar migrations/grants somente em operação autorizada; aprovar catálogo DB
   e root com hashes compatíveis. Não aceitar paths do HTTP ou banco como argv.
6. Manter releases, venvs e ambientes antigos enquanto houver referências/estado
   incerto. Não aplicar GC por idade. Rollback muda a seleção futura, sem apagar
   recibos, inverter migrations ou relançar unidade consumida.
7. Reabrir barreira explicitamente só após as verificações; CD deve falhar fechado
   em erro de DB, manager, prova ou drain. Timer existente permanece inativo.

Atualizações de Python, LibreOffice, fontes e bibliotecas do SO também precisam de
manutenção coordenada: o inventário da aplicação não torna esses componentes
externos imutáveis nem certifica compatibilidade após uma atualização.

## Testes e homologação pendente

Testes portáveis: report_launcher.test_launcher. Testes PostgreSQL:
signaling.test_report_launcher_postgresql; exercitam roles reais, concorrência,
compare sob lock, geração, rollback, replay e auditoria. Não fazem chamada real
D-Bus, publicação ou instalação de roles fora do banco temporário.

Testes REAIS de Unix: report_launcher.test_linux_credentials. Executar somente em
Linux descartável, como root, com pacote independente instalado, SEM Django:

```text
<launcher-venv>/bin/python -I -m unittest report_launcher.test_linux_credentials
```

Usam daemon/nobody já existentes como UIDs distintos, fork com abandono de grupos
e privilégios, arquivos/sockets temporários em /run. Não criam usuários, unidades,
nem leem storage real. Validam DAC do socket, credenciais reais, reutilização de
FD por UID diferente e negação de arquivo 0600/diretório 0700. Em Windows são
SKIPPED e não contam como homologação aprovada. O ambiente desta implementação
não possui distribuição WSL instalada nem Docker; não se instalou Linux para
contornar essa limitação. Esta condição adicional do usuário permanece pendente.

Após confirmação do usuário de que não há Linux descartável disponível, foi
preparado `.github/workflows/report-launcher-linux.yml`: somente workflow_dispatch,
runner GitHub-hosted ubuntu-26.04, contents:read, checkout fixado em SHA e sem
persistência de credenciais. Não altera ci.yml nem CD, não usa SSH/segredos,
não chama systemd e não foi enviado/disparado nesta etapa. O build do pacote de
testes acontece sem privilégios e sem dependências Django; sudo é usado somente
no runner descartável para os quatro testes de kernel/UID/DAC. Eles não podem
ser ignorados silenciosamente: o job exige exatamente quatro execuções e zero
skips. A execução manual deve usar apenas uma revisão confiável e revisada.

Para executar futuramente: disponibilizar o workflow no repositório, selecionar
"Report launcher - isolated Linux checks" em Actions e executar Run workflow.
Alternativa CLI, após essa disponibilização e autorização:

```text
gh workflow run report-launcher-linux.yml --ref <revisao-confiavel>
```

Em VM descartável com pacote independente instalado e daemon/nobody existentes:

```text
<launcher-venv>/bin/python -I -m unittest report_launcher.test_launcher
sudo <launcher-venv>/bin/python -I -B -m unittest -v report_launcher.test_linux_credentials
```

O workflow está apenas preparado; sua existência não é resultado aprovado de
Linux e não certifica D-Bus, systemd 259, venv da aplicação ou sandbox completo.

### Revisão do workflow Linux e critérios de aprovação

O job usa exclusivamente `runs-on: ubuntu-26.04`, runner hospedado pelo GitHub,
sem labels/grupos self-hosted, services, ambientes de produção ou secrets
configurados. Não precisa de PostgreSQL, Django, rede corporativa ou storage real.
Há acesso público à rede para checkout e dependências de build do pip (setuptools);
`--no-deps` evita instalar psycopg/dbus-next, pois estes testes não os utilizam.
O checkout usa o token efêmero automático do GitHub, restrito a contents:read e
sem persistência de credenciais; portanto não se deve descrever o job como
literalmente sem qualquer credencial. Não há credenciais de produção.

Os testes não criam contas nem novos números de UID: reutilizam daemon/nobody
do runner como representantes de dispatcher/app. Cada filho abandona grupos
suplementares e muda GID/UID reais e efetivos, verificando esses valores. Eles
comprovam a separação por identidades distintas, sem provisionar analise_dispatch
ou analise_app. O arquivo privado sintético também tem controle positivo: seu
proprietário consegue lê-lo e o dispatcher não. Os quatro testes cobrem:

- DAC do socket e autenticação SCM_CREDENTIALS com usuário autorizado e rejeição
  do outro usuário;
- rejeição por credenciais de cada mensagem, mesmo usando um descritor herdado;
- isolamento de diretório 0700/arquivo 0600 pertencentes ao outro UID;
- aceitação de catálogo root e rejeição após alteração de proprietário/permissão.

O sudo não interage com systemd: executa somente a suíte isolada, com ambiente
limpo (`env -i`), Python `-I -B`, limite externo de 90 segundos e término forçado
após mais 5 segundos. Filhos de teste têm espera limitada e cleanup apenas dos
PIDs que a própria suíte criou. O job inteiro tem limite de 10 minutos. Não há
continue-on-error; erros de import/build, identidades ausentes, falhas, skips,
timeouts ou contagem diferente da esperada produzem falha. A etapa portátil exige
15 sucessos sem skips; a etapa privilegiada exige 4 sucessos sem skips.

Risco residual: o runner permite sudo e executa código do repositório com root;
o pacote/venv é preparado pelo usuário do runner, não constitui instalação
imutável de produção. Código malicioso nessa revisão teria autoridade no runner.
Executar somente commit revisado/confiável, nunca ref de contribuição não revisada;
não adicionar secrets ou recursos operacionais ao job. O isolamento relevante é
a VM efêmera hospedada pelo GitHub, não uma sandbox contra código hostil.

Para execução manual, o workflow precisa primeiro existir na branch padrão do
repositório. Em Actions, selecionar o workflow e **Run workflow**, escolhendo uma
branch confiável cujo commit tenha sido revisado; registrar o SHA efetivamente
executado. Pela CLI, usar o comando acima e acompanhar com `gh run list
--workflow report-launcher-linux.yml`, `gh run watch <run-id>` e `gh run view
<run-id> --log`.

Aprovar somente quando o job unix-credentials terminar success, os logs mostrarem
runner Ubuntu hospedado, 15 testes portáteis OK e os 4 testes Linux nominalmente
OK, com zero skips/erros/falhas e sem timeout. Registrar URL da execução, SHA e
imagem do runner. Um job cancelado, pendente ou ignorado não aprova os testes.
Isso não aprova integração D-Bus/systemd, papéis SQL ou o lançador em produção.

Na revisão local Windows: 19 testes executados, 15 passaram e os 4 Linux ficaram
ignorados por plataforma. O workflow não foi acionado; a aprovação Linux continua
pendente até obter os resultados acima.
Uma tentativa adicional de construir o wheel offline no Windows não pôde ser
concluída porque o venv local não contém setuptools.build_meta. O workflow usa
build isolation do pip para obter esse backend publicamente; a construção e
instalação efetivas no Ubuntu ainda precisam passar no job, sem presumir aprovação.

Depois, em VM de homologação autorizada: verificar contas/grupos reais, sandbox,
assinaturas D-Bus/versão 259, empacotamento e venv sem links, fontes/cache/tmp,
CPU/RAM/tempo, biblioteca D-Bus e acesso ao manager com capabilities vazias.
Executar primeiro carga inofensiva, depois pipeline real sob autorização separada.
Ensaiar SIGTERM/SIGKILL/timeout/reboot/ACK perdido/unidade coletada e isolamento do
Gunicorn. Não habilitar produção antes de aprovar essas verificações e o contrato
de provas. A implementação local não certifica a integração do systemd na VM.
