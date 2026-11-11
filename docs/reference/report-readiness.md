# Prontidão 5B — revisão local, sem provisionamento

Base: feature/report-async-integration. O versionamento da 4C.4, incluindo a
migration 0021, e da 5B foi aprovado em dois commits separados após revisão.
Não há migration posterior criada pela 5B. Não houve merge, alteração de VM,
flags operacionais, usuários Unix, serviços ou execução dos scripts de
provisionamento nesta etapa.

## Dependências e CI

requirements-pdf.txt é a fonte única do pin pypdf==6.21.3; requirements.txt e a
entrada compatível requirements-pdf-poc.txt o incluem. O validador é obrigatório
na publicação. Instalações a partir apenas do antigo conjunto base eram insuficientes.

O job report-postgresql usa runner GitHub-hosted Ubuntu 26.04, PostgreSQL 18.6 em
container efêmero, porta dinâmica e autenticação trust SOMENTE desse laboratório.
Não usa rede corporativa, secrets ou recursos de produção. A permissão do token é
contents:read e o checkout novo não persiste credenciais. Isso não altera o CD.

signaling.report_ci_runner.NoSkipRunner recusa backend não PostgreSQL, coleta vazia
e qualquer skip. O alvo report-contracts centraliza as suítes obrigatórias, incluindo
diagnóstico, exclusão auditada e falhas do executor. As seleções explícitas de
executor/supervisão excluem apenas os casos que requerem o conversor real; estes
continuam sendo gate operacional separado, não resultados aprovados por mocks.
Novos casos nessas duas classes precisam de revisão da seleção obrigatória.

O job Django original preserva o fluxo principal SQLite e agora inclui também
report_finalization.test.js e report_publication_flow.test.js. O workflow manual
report-launcher-linux.yml mantém os 15 casos portáteis e os 4 de UIDs reais. O job
PostgreSQL acrescenta os dois casos de symlinks Linux e uma montagem de release
temporária com wheels/hash-lock; nenhum desses passos instala serviços.

Com ambiente PostgreSQL exclusivamente descartável:

```text
python -B manage.py test report-contracts --testrunner=signaling.report_ci_runner.NoSkipRunner --noinput
```

Esse alvo completo exige Linux. No Windows os dois testes Linux permanecem
pendentes, e executá-lo sem essa condição faz o job reprovar os skips corretamente.
Para validação local, selecionar explicitamente os demais REQUIRED_LABELS; não
adicionar exceções de skips ao runner do CI. Registrar separadamente o que não rodou.

## Matriz de privilégios

A fonte de verdade é scripts/report_permission_policy.py. O exemplo antigo
report-launcher-grants.sql.example é histórico e cobre apenas autoridades; não
aplicá-lo junto com o novo plano completo sem revisão.

| Papel | Direitos | Limites |
|---|---|---|
| HTTP | Auth/sessão e edição normais, INSERT da admissão; SELECT do progresso; DELETE oficial para o fluxo auditado | Sem escrita de snapshot, estado de execução, release, entrega, recibo ou barreira; sem funções das autoridades |
| Executor | SELECT dos insumos/metadados; INSERT de artefatos; UPDATE de colunas de estado, binding e confirmação | Sem edição de snapshot, DELETE, criação de lançamento ou consumo de autoridade |
| Dispatcher | EXECUTE de duas funções e SELECT da projeção | Sem tabelas brutas, snapshots ou funções do launcher |
| Launcher | EXECUTE de quatro funções | Sem DML direto ou administração |
| Dono das funções | NOLOGIN, direitos internos explícitos por tabela/coluna | Sem membership para runtimes ou CREATE no schema |

Exceções necessárias foram verificadas com PostgreSQL real: locks FOR UPDATE
exigem UPDATE em pelo menos uma coluna. HTTP recebe finalized_at/number_assigned_at
para os locks da exclusão e updated_at da tentativa para replay; executor recebe
confirmed_at do lançamento para o lock de binding, sem UPDATE de state/dispatch_id.
HTTP também recebe UPDATE somente de identity.attempt_id para o SET_NULL já usado
na exclusão física auditada. O cleanup pode atualizar version_ids, além de seus
demais campos próprios. Nenhum desses grants autoriza reescrever snapshot/autor.

As permissões SQL não substituem autorização Django, nem impõem sozinhas auditoria
por linha contra comprometimento do runtime HTTP. DELETE de documentos e DML de
auth são necessários aos fluxos existentes. Os testes verificam o fluxo auditado e
as negações críticas; não se alega uma nova garantia de RLS/imutabilidade em SQL.
As credenciais de migração/aprovação de release são administrativas, separadas,
e não devem ser disponibilizadas a nenhum runtime. Nenhum runtime é dono de tabelas.

## Planos de provisionamento preparados — NÃO executados

Gerador sem conexão: scripts.report_hml_plan imprime SQL, não o executa. Exige banco
com prefixo analise_hml, identificadores estritos e cinco papéis distintos; o SQL
confere current_database(), revoga CONNECT/TEMP de PUBLIC só nesse banco, usa
transação e ON_ERROR_STOP, e recusa papéis já existentes. Não contém senhas,
memberships, ALL TABLES/SEQUENCES ou default grants. Credenciais/pg_hba ficam para
uma operação aprovada. O prefixo do banco não é prova de isolamento: o operador
precisa confirmar host/cluster e ausência de dados reais antes de aplicar.

Comando futuro de geração, após revisão:

```text
python -B -m scripts.report_hml_plan --database analise_hml --roles-prefix report_hml > permissions.review.sql
```

Aplicação futura somente como administrador do cluster DESCARTÁVEL, após migrations
até 0021 e revisão do arquivo. O teste aplica apenas a política declarativa com
papéis temporários no banco de testes; não executa o plano de provisionamento.

deploy/provision-report-hml.sh fica preparado para a VM nova. Exige root e sentinel
root:root 0600 /etc/analise-hml-disposable com conteúdo ANALISE_REPORT_HML_ONLY,
criado por aprovação separada. Recusa contas, grupos e destinos já existentes,
verifica o ambiente standalone root-owned sem links/escrita externa e recusa
presença de Django/signaling/config nesse ambiente. Somente então prepara contas,
diretórios, tmpfiles e arquivos inertes de unidades/configuração. Não executa
systemctl, migrations, SQL, acesso à rede, publicação ou alteração no CD.

Todos os arquivos gerados mantêm flags false e catálogo disabled; DSN vazio faz
startup falhar fechado. Não existem segredos padrão. Não reexecutar após falha
parcial: inspecionar e reconstruir a VM descartável, sem remover histórico incerto.
Não foi executado, nem mesmo no Windows; bash -n está previsto no CI Linux.

A sintaxe bash -n foi também validada localmente com o Bash do Git for Windows;
isso apenas analisa o texto, não executa o provisionamento.

## Empacotamento da release

scripts.report_release é um auxiliar de build não privilegiado. Não implanta,
aprova release no banco, altera catálogo ou chama systemd. O catálogo e seu
contrato v1 permanecem inalterados, rejeitando todos os symlinks.

1. Após commit aprovado, exportar git archive do SHA completo. Não copiar o
   checkout inteiro com bancos locais, .git, segredos ou dados privados.
2. Resolver wheels para a plataforma/ABI alvo, incluindo o pip de bootstrap.
   Usar apenas wheels e diretório novo. wheel-lock produz pins de TODAS as wheels
   com SHA-256; revisar e reter wheels + lock. Não resolver novamente durante deploy.
3. Construir o venv com --copies, sem system-site-packages, no prefixo FINAL da
   release. Instalar offline com --no-index --only-binary=:all: --require-hashes e
   --no-compile, usando o lock. Evitar geração de bytecode com -B no build.
4. normalize-lib64 materializa somente o alias literal .venv/lib64 -> lib. Recusa
   links externos/internos inesperados ou normalização incompleta. Não relaxa o
   lançador para aceitar links. A cópia pode duplicar disco/quantidade de arquivos.
5. Colocar o lock em requirements.resolved.txt dentro da release. manifest audita
   prefixo real do venv, packages exatamente iguais ao lock, pins declarados
   (incluindo pypdf), pip check e ausência de links/segredos/arquivos especiais.
   Grava release-runtime.json e manifesto completo; recusa sobrescrever manifesto.
6. Só após validação, selar ownership/permissões com procedimento administrativo
   aprovado. Conferir catálogo com Catalog.validate() antes de admitir algo.
   O helper não certifica ownership root no build não privilegiado.

Comandos futuros no ambiente de build confiável, NÃO executados nesta etapa:

```text
python -B -m scripts.report_release wheel-lock <wheelhouse> > <requirements.resolved.txt>
python -B -m scripts.report_release normalize-lib64 <release-root>
python -B -m scripts.report_release manifest <release-root> --release-id <sha-revisado>
```

manifest_sha256 cobre os bytes exatos do manifesto; bundle_sha256 cobre a lista
canônica de arquivos como já exige o lançador. Wheel lock protege os bytes dos
artefatos aprovados, não sua autenticidade inicial. Bootstrap Python, ABI, bibliotecas
do SO, LibreOffice e fontes continuam externos e devem ser congelados na imagem
da VM. Não há promessa de relocabilidade ou builds bit a bit entre hosts/prefixos.
O venv standalone do lançador é separado, sem Django, sob
/opt/analise-launcher/<versao>/.venv; aplicar a mesma normalização restrita. Construir
seu wheel sem build isolation somente em ambiente de build com ferramentas já
travadas por hash; não executar build de código como root nem resolver ferramentas
livremente durante instalação privilegiada.

O smoke de CI é um build em prefixo temporário Ubuntu. Ainda não é o artefato
root-owned para a VM. Se ultrapassar 50000 arquivos/8 MiB de manifesto, falhar e
revisar o empacotamento; não aumentar limites do lançador automaticamente.

## Gates e aprovação

Continuam fechados por padrão todos os gates HTTP/admissão/executor/supervisão/
dispatcher e o catálogo. Fencing, entrega única, bloqueio UNCERTAIN, snapshots,
numeração, tombstones e ausência de retry automático não foram alterados pela 5B.
Histórico sem prova de término continua bloqueando novas intenções e deploy.

Antes de homologação: aprovar diff/commits, obter CI no SHA completo (PostgreSQL sem
skips, dois testes de links, smoke de release, JS e workflow Unix existente),
revisar grants/credenciais e runbook da VM isolada. Provisionamento/ativação precisam
de aprovação operacional específica. Nenhuma autorização para merge/main/CD decorre
da aprovação desta revisão. Testes simulados não certificam systemd/cgroups.

## Resultados locais para revisão

194 testes Python distintos disponíveis no Windows passaram com PostgreSQL real:
164 na primeira suíte obrigatória portátil e 41 na revisão direcionada, sendo 11
repetidos. As duas execuções usaram NoSkipRunner, sem skips. Os 15 testes portáteis
do lançador e os 262 testes JavaScript dos seis arquivos selecionados no CI passaram.
manage.py check, makemigrations --check --dry-run, pip check e git diff --check
passaram. A análise bash -n passou sem execução do script.

Os dois testes de links Linux foram explicitamente coletados e ignorados por
plataforma no Windows; permanecem pendentes, assim como o job GitHub Actions
atualizado e o smoke de venv/manifesto Linux. Não foram disparados workflows,
instaladas dependências na VM, executados scripts de provisionamento, criados
usuários Unix ou serviços, nem realizadas publicações reais. Os únicos papéis e
grants criados pelos testes pertencem ao cluster PostgreSQL descartável.

Divisão de commits aprovada após revisão do diff e resultados:

1. feat(reports): integrate persistent asynchronous publication — implementação
   integral da 4C.4, inclusive 0021, testes e documentação correspondentes.
2. build(reports): enforce readiness gates and immutable release preparation —
   dependências, política/provisionamento preparados, empacotamento, CI e testes 5B.

O patch usado na revisão inclui os arquivos novos, não apenas git diff tracked,
e permanece em tmp/, ignorado e fora do staging. A aprovação dos dois commits
locais não autoriza push, merge, deploy ou qualquer alteração operacional.
