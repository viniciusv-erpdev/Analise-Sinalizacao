# Integração HTTP de reservas — etapa 3A

## Auditoria e escopo

A branch foi confirmada como feature/waypoint-locking. Havia alterações locais
das etapas anteriores e um backup SQLite; foram preservados. O núcleo 2B continua
em signaling/reservations.py, sem uma segunda implementação de locking.
Os serviços aceitam argumentos nomeados e validate_reservation é context manager.

As views existentes persistiam pontos, intervenções, problemas e soluções sem
reserva. HTML/DOCX e Overpass também não validavam exclusividade. Caracterização
é parte do formulário de relatório; não há endpoint separado que a persista.
O Admin permitia gravações diretas e exclusão em lote. Tudo isso foi considerado.

3A não altera JavaScript, CSV, Nginx, Gunicorn, CI/CD, modelos ou migrations.
A criação autorizada POST /signaling/points/ continua sem reserva; o ponto nasce
disponível. Toda operação exclusiva posterior exige aquisição própria.

## Credenciais e endpoints para a etapa 3B

Base: /signaling/points/<point_id>/.

Todas as rotas exigem login e view_signalingpoint. As operações exclusivas
existentes continuam exigindo também suas permissões add/change/delete/report.
POSTs mantêm o CSRF Django (cookie + X-CSRFToken para JSON).

| Caminho | Método | Entrada | Sucesso |
| --- | --- | --- | --- |
| reservation/acquire/ | POST | JSON com somente interaction_id (UUID v4) | 201, token, interaction_id, generation, expires_at, state |
| reservation/renew/ | POST | Credenciais nos três headers abaixo | 200, generation, expires_at, state |
| reservation/release/ | POST | Credenciais nos headers | 200, released=true |
| reservation/ | GET | Headers opcionais para provar titularidade | 200, state, generation, expires_at |

Os sucessos incluem success=true e point_id. State é available, reserved_self ou
reserved_other. Self exige a credencial completa da mesma aquisição e sessão,
não apenas o mesmo usuário. Status não revela tokens, hashes, sessões ou titular.

Headers obrigatórios nas operações exclusivas:

- X-Waypoint-Token: token retornado SOMENTE pela aquisição.
- X-Waypoint-Interaction: UUID da instância.
- X-Waypoint-Generation: inteiro decimal positivo.

Não enviar credenciais na query string: parâmetros token, reservation_token,
interaction_id e generation em URLs de reserva/proteção são rejeitados.
Renovação não retorna o token novamente. Não salvar tokens em URLs ou logs.
A identidade autenticada vem de request.session.session_key e é revalidada
pelos serviços 2B. Respostas de reserva/protegidas são privadas e no-store.

Release repetido com prova da MESMA aquisição retorna released=true.
Uma prova antiga não libera uma aquisição posterior. Acquire sempre disputa
nova aquisição; repetir acquire com mesmo usuário/sessão/UUID não é recuperação
idempotente. UUID novo por instância de edição; não reutilizar sessionStorage
como identidade garantida de aba. Bearer deliberadamente copiado pode ser usado.

## Operações protegidas

Todos os caminhos abaixo são relativos à mesma base:

- POST status/ e search-radius/.
- POST delete/.
- POST interventions/.
- POST interventions/<id>/condition/, notes/ e delete/.
- POST problems/.
- POST problems/<id>/solution/ e delete/.
- GET/POST report/ (formulário HTML e DOCX).
- POST pgts/ (consulta externa integrante do relatório).

GET problems/, mapa/listagens autorizadas e o pipeline público permanecem sem
reserva. A leitura não concede autorização futura de gravação.

Autorizações da etapa 2A são verificadas ANTES de validar a reserva. A validação
da reserva e a gravação inteira ficam dentro do mesmo validate_reservation.
Filhos são consultados sob o lock do ponto e vinculados ao point_id da rota.
A ordem permanece waypoint -> reserva -> filhos. Não há fallback SQLite.

## Erros JSON

Formato: success=false, code e error (mensagem legível), sem valores secretos.

| HTTP | Code |
| --- | --- |
| 400 | invalid_reservation_arguments |
| 401 | authentication_required |
| 403 | permission_denied, csrf_failed, reservation_credentials_invalid |
| 404 | waypoint_not_found |
| 409 | reservation_occupied, reservation_expired, reservation_generation_stale, reservation_inactive |
| 428 | reservation_required (headers ausentes) |
| 503 | reservation_backend_unsupported |

Nas APIs, sessão encerrada retorna 401 JSON quando o CSRF é válido; uma falha
CSRF pode ser rejeitada antes com 403 csrf_failed. O relatório HTML preserva o
redirecionamento inicial ao login da etapa 2A para anônimos; se a sessão terminar
durante processamento, a revalidação retorna 401 JSON e descarta o resultado.

Erros de filhos inexistentes mantêm o contrato 404 anterior após validar a reserva.
Erros de formulário/negócio mantêm os contratos existentes. Sessão terminada exige
novo login; não repetir automaticamente gravações. Nova aquisição após expiração
deve reler o estado. Tokens antigos nunca são adaptados para a nova geração.

## Relatórios e operações demoradas

A estratégia aprovada de snapshot + revalidação foi implementada sem mudar o
contrato 2B:

1. Validar e bloquear; materializar ponto, intervenções, problemas e soluções.
2. Soltar locks e processar filtros, sinistros, gráficos, uploads e DOCX usando
   somente esse snapshot. Nenhum I/O externo fica no contexto de reserva.
3. Revalidar a MESMA credencial/geração antes de devolver HTML, DOCX ou PGTs.
4. Em perda de reserva, descartar a resposta; fechar o buffer do DOCX.

PGTs usam coordenadas/raio do snapshot e revalidam após Overpass.
Expiração ou release/reacquire durante processamento impedem entregar resultado.
Revalidação autoriza a resposta no servidor; não controla dados já recebidos nem
mantém lock durante tráfego de rede. Cálculo antigo pode terminar em paralelo
após expiração, mas seu resultado não é aceito para entrega com geração obsoleta.
O cliente 3B deve renovar enquanto o formulário/relatório estiver em uso.

## Admin

SignalingPoint e SignalingIntervention ficam somente leitura, inclusive para
superusuários. Add/change/delete retornam False; ações em lote são removidas e
save_model/delete_model/delete_queryset negam operações explicitamente.
A administração nativa de usuários/grupos/permissões não foi alterada.
Não há bypass administrativo de reserva.

## Testes e situação operacional

Os testes funcionais antigos recebem uma fixture ReservationClient que adquire
e envia provas explícitas. Testes negativos continuam com Client comum.
Em SQLite, só fixtures unitárias simulam o guard; testes sem essa simulação
continuam exigindo falha explícita. Isso não prova concorrência PostgreSQL.

Novos testes: test_reservation_endpoints e test_reservation_http_concurrency.
O segundo usa PostgreSQL real, conexões independentes, Barrier e verificação
de bloqueio no banco, reaproveitando os helpers da etapa 2B.

O processo do agente não herda variáveis de um PowerShell externo. O usuário
informou desenvolvimento analise_dev em PostgreSQL 18 e script interativo
scripts/local-postgres-env.ps1. A senha não foi solicitada nem armazenada.
Para executar a prova PostgreSQL, no MESMO terminal local:

    . .\scripts\local-postgres-env.ps1
    # Confirmar DJANGO_DB_BACKEND=postgresql, POSTGRES_DB=analise_dev,
    # POSTGRES_HOST=127.0.0.1 e DJANGO_TEST_DB_NAME=test_analise_dev.
    # Confirmar que test_analise_dev é exclusivo do runner antes de permitir criação/remoção.
    .\.venv\Scripts\python.exe manage.py test accidents.test_main_flow signaling

O runner cria/remove o banco de testes; não usar produção, --keepdb ou confirmar
exclusão de banco compartilhado. O teste não executa migrations no banco dev.
Nunca usar as credenciais de produção para esses comandos.

Até 3B, o frontend antigo não envia as credenciais: edição, exclusão, relatórios
e PGTs retornam 428. Criação e consultas autorizadas continuam funcionando.
Isso é bloqueio intencional. Não implantar 3A isoladamente esperando manter
a experiência antiga de edição. A integração não está homologada em concorrência
até a suíte nova passar em PostgreSQL real.
