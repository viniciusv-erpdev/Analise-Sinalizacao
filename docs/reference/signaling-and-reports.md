# Referência: sinalização e relatórios

## Responsabilidade

Este domínio cobre a análise de pontos de sinalização, integração com PGTs e geração de relatórios a partir dos sinistros selecionados.

Arquivos centrais:

- `signaling/models.py`
- `signaling/views.py`
- `signaling/forms.py`
- `signaling/report_filters.py`
- `signaling/report_generator.py`
- `signaling/overpass.py`
- `signaling/services.py`
- `signaling/surveys.py`

## Entidades persistidas

`SignalingPoint` representa um ponto georreferenciado com:

- latitude e longitude;
- status (`OK`, `INCOMPLETE`, `ABSENT`);
- raio de busca em metros;
- intervenções e problemas associados.

`SignalingIntervention` mantém a intervenção aplicada ao ponto e seu status/observações.

`SignalingPointProblem` liga um problema de geometria/segurança a uma solução válida.

## Fluxo do ponto e relatório

1. O usuário cria ou seleciona um ponto de sinalização.
2. O endpoint `search_point_pgts` consulta Overpass para localizar PGTs próximos ao ponto.
3. O relatório usa a análise atual em sessão para filtrar os sinistros relevantes ao ponto.
4. `parse_individual_report_filters()` aplica filtros por categoria, gravidade e períodos.
5. `build_signaling_survey_from_items()` monta o survey do ponto com ocorrências e intervenções.
6. O template `templates/signaling/report.html` renderiza o HTML do relatório.
7. Ao confirmar, `generate_signaling_report()` gera o DOCX em memória e devolve o arquivo para download.

## Integrações e limitações

- `signaling.overpass` faz a busca externa por PGTs; falhas são tratadas como `OverpassUnavailable`.
- O WorkFlow principal usa dados da sessão, não uma nova leitura do banco de acidentes.
- O relatório final é emitido sob demanda; não há persistência do documento gerado em banco.

## Regras de negócio relevantes

- O raio do ponto tem intervalo validado entre `MIN_SIGNALING_SEARCH_RADIUS_METERS` e `MAX_SIGNALING_SEARCH_RADIUS_METERS`.
- O relatório individual exige que a análise ativa em sessão seja do tipo `individual`.
- Filtros repetidos e parâmetros inválidos são rejeitados antes da geração do Word.
- O conjunto de soluções e problemas é validado por catálogo e por `CheckConstraint` no modelo.

## Frontend relevante

A interface do mapa e do relatório depende de:

- `templates/map.html`
- `static/js/map.js`
- `static/js/individual_filters.js`
- `static/js/report_characterization.js`

Esses arquivos implementam seleções, filtros visíveis, links de relatório e apresentação de itens do formulário.

## Testes relevantes

- `signaling/tests.py`
- `signaling/test_report_download.py`
- `signaling/test_report_generator.py`
- `signaling/test_report_filters.py`
- `signaling/test_overpass.py`
- `signaling/test_pgt_endpoint.py`

Esses testes cobrem ponto, raio, filtros, geração do DOCX e integrações externas mockadas.


## Autenticação e autorização (etapa 2A)

O mapa e a análise CSV permanecem públicos. Dados de waypoints só são incluídos
no HTML para usuários com `signaling.view_signalingpoint`. Login e logout usam as
views nativas do Django; logout exige POST com CSRF e limpa a análise da sessão.
A interface informa essa consequência. Não há cadastro público nem concessão
automática de permissões.

A política está em `signaling/authorization.py`: todas as operações exigem view,
além de add para criar ponto, change para editar ponto/intervenções/problemas/
soluções, delete para excluir ponto, e generate_signaling_report para relatório
HTML/DOCX e busca PGT. APIs respondem JSON 401 (não autenticado) ou 403 (sem
permissão). CSRF continua ativo, com erro JSON nas APIs e resposta padrão nos
formulários HTML. O relatório anônimo redireciona ao login.

Autorização não concede uma reserva exclusiva. A etapa 2A não implementa reservas:
a futura verificação deverá ser adicional, inclusive para usuários com view.
O Admin exige a política do waypoint E as permissões nativas do modelo operado.
Usuários normais não precisam de is_staff nem superuser.

### Provisionamento administrativo

Executar apenas após autorização de implantação, backup e aplicação da migration
0008 no ambiente escolhido. A migration declara uma permissão, sem atribuí-la a
usuários ou criar grupos. Confirmar a existência das cinco permissões no banco.

Um administrador já autorizado pode criar grupos no Admin de autenticação e
atribuir explicitamente estas permissões de SignalingPoint:

| Grupo | Permissões |
| --- | --- |
| Consulta | view_signalingpoint |
| Analista | view_signalingpoint, add_signalingpoint, change_signalingpoint, generate_signaling_report |
| Gestor | As de Analista e delete_signalingpoint |

Criar cada usuário com identidade individual e senha única, pelo formulário de
criação de usuários do Admin (com validação de senha). Associar somente os grupos
aprovados; manter staff e superuser desmarcados para usuários normais. Não usar
senhas em comandos, fixtures, documentação ou repositório. Não há contas padrão.
Revisar permissões diretas e outros grupos, pois permissões Django são aditivas.
A gestão de usuários/grupos deve ser restrita a administradores de confiança:
poder alterar permissões de usuários pode permitir escalada de privilégios.

Para operadores administrativos de sinalização, conceder is_staff somente por
necessidade administrativa aprovada, além das permissões nativas de cada modelo.
Editar intervenções no Admin requer também view/change do waypoint. Excluir um
ponto pode exigir delete nos modelos relacionados devido à proteção nativa de
cascata do Admin. Não liberar gestão de contas a operadores de sinalização.

### Validação e implantação futura

Rodar `manage.py check`, `manage.py makemigrations --check --dry-run` e
`manage.py test accidents.test_main_flow signaling` em ambiente de testes.
Executar também os quatro arquivos `static/js/*.test.js` listados na CI.
A CI mantém o job django-tests e não faz deploy.

Antes de produção: validar em PostgreSQL de homologação, revisar HTTPS e cookies
Secure/HttpOnly/SameSite, conferir configuração de proxy e segredo de sessão,
provisionar contas/grupos e testar o acesso real. As flags de cookies Secure
dependem de HTTPS efetivo; não foram habilitadas sem essa confirmação.
O login nativo não fornece limitação de tentativas: definir proteção operacional
antes de expor credenciais em rede não confiável. Não enviar tokens ou senhas a logs.

Coordenar com o CD existente: ele aplica migrations antes de reiniciar. GET /
permanece público com HTTP 200, mas isso não valida login nem permissões.
Reverter somente o código para uma versão anterior pode reabrir os endpoints:
em falha, restringir o acesso operacionalmente e corrigir com uma revisão compatível;
não desfazer migrations nem restaurar banco sobre gravações novas automaticamente.


## Núcleo de reservas (etapa 2B)

Modelo, protocolo, contratos e limites estão em
[waypoint-reservations.md](waypoint-reservations.md).
A existência desse núcleo não aplica reservas às views nem ao Admin.


## Integração obrigatória (etapa 3A)

As operações exclusivas agora exigem reserva no backend. O Admin de sinalização
é somente leitura. Contratos HTTP, erros, snapshot/fencing de relatórios e
dependências da interface 3B: [waypoint-reservation-api.md](waypoint-reservation-api.md).


## Rascunhos compartilhados — backend

`WaypointReportDraft` mantém um registro por waypoint, com os textos/datas atuais
do formulário, lista textual de PGTs, revisão, autor da última alteração e horários.
Não armazena fotos, credenciais ou análise da sessão. O modelo não é exposto no
Admin; o serviço de gravação é `signaling/report_drafts.py`. A migration adicional
é `0010_waypoint_report_draft`; não há alteração das migrations anteriores.

`GET /signaling/points/<id>/report-draft/` consulta sem adquirir reserva ou criar
registro. Exige autenticação, `view_signalingpoint` e `generate_signaling_report`.
Retorna `success`, `point_id`, `exists`, `revision`, `fields`, `updated_by`,
`created_at` e `updated_at`. Ausência é representada por revisão zero, campos
vazios, datas/metadados nulos e `exists=false`. A revisão atual vem nessa resposta;
não é necessário outro endpoint. Os horários são ISO 8601 e as datas AAAA-MM-DD.

`POST` na mesma URL usa JSON com exatamente `expected_revision` (inteiro) e
`fields` (objeto não vazio contendo somente campos editáveis). Exige as mesmas
permissões, CSRF e os três headers do protocolo existente de reservas. Campos
omitidos são preservados; texto vazio e lista vazia limpam seus valores; datas
aceitam vazio ou null para limpeza. Textos exigem strings, com os limites atuais
do formulário e sem caracteres inválidos em XML. PGTs reutilizam a validação
existente: até 50 textos de 300 caracteres, removendo entradas em branco e espaços
externos. Multipart, fotos e campos não permitidos são rejeitados.

A gravação usa `validate_reservation`, depois bloqueia o rascunho, compara a revisão,
valida e salva na mesma transação. O bloqueio do waypoint serializa também a
primeira criação. A primeira gravação espera zero e devolve um; cada gravação
aceita incrementa a revisão. Conflitos retornam HTTP 409 `draft_revision_conflict`
com `revision` atual; falhas de payload/campos retornam 400, além dos erros atuais
de autorização/reserva. Respostas são privadas e no-store. A permissão de relatório
é novamente conferida depois da espera pelo bloqueio, sem reutilizar cache do request.

O rascunho é removido com o waypoint; exclusão do autor preserva os textos e torna
`updated_by` nulo. Não há histórico de revisões. A geração DOCX permanece
independente do rascunho; a integração do formulário está descrita abaixo.
`technical_analysis` integra o contrato: texto opcional de até 10.000 caracteres,
com quebras de linha preservadas e validação dos caracteres aceitos no DOCX.

Testes: `signaling.test_report_drafts` e `signaling.test_report_draft_concurrency`.
O segundo exige PostgreSQL real e é ignorado em SQLite; os testes funcionais em
SQLite usam o mesmo isolamento de fixture das suítes existentes, sem comprovar locks.


## Recuperação e autosave no formulário

`static/js/report_draft.js` carrega o rascunho pelo GET e envia somente diferenças
com debounce de dois segundos, uma gravação por vez e revisão esperada. É montado
pelo controlador do mapa no iframe; não adquire nem renova reservas por conta própria.
`report_characterization.js` também sinaliza alterações programáticas dos PGTs.
Fotos e dados de análise não entram no payload. O status fica em uma linha no formulário.

Respostas antigas não repintam edições locais. Falha de rede mantém os valores;
a recuperação lê o servidor antes de repetir uma gravação, inclusive quando a
resposta de um POST confirmado se perdeu. Um conflito suspende autosave sem invalidar
a reserva: os textos permanecem disponíveis para copiar e revisar antes de reabrir.
Não há sobrescrita ou resolução automática de conflito HTTP 409.

Fechar tenta concluir o salvamento. Se restarem alterações, é necessário confirmar
explicitamente o descarte; cancelar mantém o formulário. Perda da reserva interrompe
autosave e mantém os textos em modo de leitura, inclusive após exclusão remota ou
retorno pelo BFCache. Navegação interna com pendências é bloqueada; saída da página
solicita o aviso nativo do navegador. Os valores não confirmados ficam apenas em
memória: encerramento forçado/crash não tem recuperação garantida.

Reapresentação de erros do DOCX reaproveita o controlador e os textos locais.
O download continua multipart na rota original e pode usar os valores locais
mesmo em conflito de rascunho, desde que a reserva permaneça válida.
Testes JS: `report_draft.test.js`, controles do iframe, reservas e caracterização;
a nova suíte é importada pela entrada `intersection_problems.test.js` já usada na CI.


## Identificação e análise técnica no DOCX

O formulário e o documento usam o título “Relatório Técnico de Segurança Viária”.
A análise técnica fica após as fotos e participa do mesmo rascunho/autosave,
com revisão e reservas existentes. A migration aditiva
`0011_report_draft_technical_analysis` acrescenta texto vazio aos rascunhos antigos,
sem alterar seus demais campos, revisão ou timestamps. Não é aplicada pelo fluxo HTTP.

O DOCX termina com a análise técnica (ou “Não informado”) e o registro de autoria.
A view fornece exclusivamente `request.user` ao gerador; nome completo e username
identificam o autor, usando apenas username quando o nome está vazio. O responsável
pela vistoria continua sendo um campo separado. A emissão vem de um único instante
do relógio do servidor, convertido pelo timezone Django; o mesmo instante determina
a data de geração no documento. A configuração atual continua em UTC.
Esse registro não constitui assinatura digital ou certificação jurídica.

O endpoint continua gerando DOCX em memória, com os dados atuais do formulário;
não há PDF, numeração oficial ou armazenamento de documentos finalizados.
