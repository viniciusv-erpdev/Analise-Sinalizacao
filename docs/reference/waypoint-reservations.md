# Reservas de waypoints — núcleo da etapa 2B

## Escopo e ponto de partida

Auditoria inicial: branch feature/waypoint-locking, workspace limpo, autenticação
2A presente e migrations até 0008. Os quatro modelos existentes usam PKs do banco;
os serviços atuais ficam em signaling/services.py e os testes junto ao app.
A configuração escolhe explicitamente SQLite ou PostgreSQL; produção não faz fallback.
O núcleo novo fica em signaling/reservations.py, sem dependência de HTTP.

Esta etapa NÃO integra reservas em views, Admin, relatórios, PGTs ou frontend.
Esses caminhos ainda exigem somente a autorização da etapa 2A. Portanto o sistema
completo ainda não garante uso exclusivo dos waypoints.

## Persistência e geração

WaypointReservation tem OneToOne com SignalingPoint (UNIQUE no banco), usuário
FK/SET_NULL, digest HMAC da sessão, UUID da interação, digest SHA-256 do token,
geração e horários acquired_at, renewed_at, expires_at e released_at.
O índice expires_at auxilia futuras consultas operacionais; não há job obrigatório.
CHECKs exigem geração positiva, acquired_at <= renewed_at < expires_at e
released_at nulo ou posterior/igual à aquisição. Não há permissões padrão nem
registro do modelo no Admin.

SignalingPoint recebe reservation_generation, contador bigint não editável que
começa em zero. Somente uma aquisição nova o incrementa. Renovação/liberação não
o alteram. A linha de reserva é mantida como tombstone após liberação.
O contador separado é necessário para preservar a geração MESMO se a linha de
reserva for excluída e recriada; as credenciais são conferidas também contra ele.
Overflow falha explicitamente, sem voltar a zero. Nenhuma PK é modificada.

Excluir o waypoint encerra sua identidade e remove a reserva por cascata.
A recriação manual de PKs e restaurações de backup são operações administrativas
fora do protocolo: não reutilizar identidades antigas enquanto clientes antigos
puderem operar. Exclusão de usuário preserva a reserva e contador (FK SET_NULL);
ela deixa de ter titular autenticável e fica disponível ao liberar por expiração.
Não há modificação das entidades de intervenção, problema ou solução.

## Identidade e autorização

ReservationIdentity recebe SOMENTE a chave de sessão obtida pela camada confiável
do servidor (futuramente request.session.session_key), nunca user_id do JSON.
Em cada operação o serviço relê django_session, verifica validade temporal,
backend permitido, usuário ativo, hash de autenticação atual/fallback e permissão
view_signalingpoint. A verificação se repete após a espera por locks. Permissões
revogadas, senha alterada, logout ou sessão expirada invalidam a identidade.
O suporte atual exige sessões de banco e USE_TZ=True, como configurado no projeto.

A camada HTTP futura continuará responsável por CSRF e pelas permissões
add/change/delete/report da operação. View não autoriza uma mutação por si só.
O serviço valida a identidade autenticada e a credencial da aquisição, não uma
declaração de usuário do cliente.

O token usa secrets.token_urlsafe(32), com 256 bits de entropia; apenas o digest
é persistido. A sessão usa HMAC-SHA256 com domínio próprio e SECRET_KEY.
Comparações dos verificadores usam constant_time_compare. Não logar chaves,
tokens, hashes ou serializar dataclasses de credenciais. repr de identidade e
credenciais omite segredos; str/repr do modelo não contém verificadores.
Alterar SECRET_KEY pode invalidar o vínculo da reserva mesmo preservando sessões
por fallback; a consequência segura é aguardar expiração e adquirir novamente.

## Contrato para instâncias e abas

A futura interface deve gerar crypto.randomUUID() em memória para CADA nova
instância efetiva de edição/documento, sem recuperar esse UUID ou token de
localStorage/sessionStorage. Duplicar uma aba deve iniciar uma nova aquisição
com novo UUID. Não presumir isolamento de sessionStorage em duplicação.

acquire sempre disputa uma NOVA aquisição: mesmo usuário, sessão e UUID não
reutilizam automaticamente uma reserva existente. Repetir acquire durante uma
reserva ativa gera ReservationOccupied. Resposta de aquisição perdida exige
recuperação explícita futura ou expiração; não há idempotência por usuário/sessão.

Uma segunda instância normal não recebe a credencial da primeira. Entretanto,
um bearer deliberadamente copiado com a sessão e UUID corretos pode ser usado.
UUID declarado pelo navegador é falsificável. Isso não garante isolamento
absoluto contra scripts maliciosos, XSS ou transferência intencional de segredos.
Um segredo em memória por documento ou canal BroadcastChannel pode ajudar a
detectar duplicação cooperativa; não é uma fronteira de segurança. Chaves
WebCrypto não exportáveis com prova de posse exigiriam outro protocolo e ainda
não impediriam um script autorizado de solicitar assinaturas. Nenhuma dessas
alternativas foi introduzida nesta etapa.

## Serviços e resultados

Entradas são keyword-only, com PK inteira positiva, ReservationIdentity,
UUID v4 real (adaptadores devem converter a representação textual) e, quando
necessário, ReservationCredentials(interaction_id, generation, token).

- acquire_reservation: retorna ReservationGrant(point_id, credentials, expires_at).
- renew_reservation: exige a mesma identidade completa e reserva ainda ativa;
  retorna a mesma credencial com nova expiração.
- release_reservation: retorna True tanto na liberação quanto na repetição
  comprovada da MESMA aquisição. Retém verificadores para autenticar a repetição.
  Pode liberar uma reserva vencida própria; nunca uma aquisição posterior.
- validate_reservation: context manager, não booleano nem autorização durável.
  Uso obrigatório: entrar no contexto e gravar ponto/filhos DENTRO dele.
- get_reservation_status: leitura consultiva sem adquirir ou gravar; retorna
  available, reserved_self ou reserved_other, PK, geração e expiração.
  Self exige prova completa; igualdade de usuário ou sessão é insuficiente.
  Sem prova, inclusive o próprio usuário vê reserved_other. Não expõe titular,
  token, chave de sessão nem verificadores. O resultado pode ficar desatualizado.

Exemplo para a próxima etapa (não integrado):

    with validate_reservation(point_id=point_id, identity=identity,
                              credentials=credentials) as locked_point:
        # Validar a permissão específica antes; consultar e alterar filhos aqui.
        # Esta gravação e a validação compartilham a transação e os locks.
        ...

Exceções de domínio têm códigos fixos: invalid_reservation_arguments,
authentication_required, permission_denied, waypoint_not_found,
reservation_occupied, reservation_credentials_invalid,
reservation_generation_stale, reservation_expired, reservation_inactive,
reservation_backend_unsupported. Não incluem valores recebidos.
Configuração incompatível gera ImproperlyConfigured; falhas operacionais de banco
propagam para rollback e diagnóstico, sem retry cego em transação abortada.

## Transações, tempo e bancos

Ordem obrigatória: lock do waypoint existente, lock da reserva, entidades filhas.
A ausência inicial de reserva é serializada pelo waypoint. Leitura, incremento
do contador e gravação da aquisição ficam na mesma transaction.atomic().
Serviços aninhados mantêm os locks até o término da transação mais externa.

O relógio é consultado em uma NOVA instrução SELECT clock_timestamp() depois de
obter ambos os locks. PostgreSQL CURRENT_TIMESTAMP/now() refletem o início da
transação e não são usados. Assim uma requisição que começou válida mas esperou
por um lock não usa o horário anterior à espera.
Referência: https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT

TTL e intervalo planejado ficam centralizados nos settings:
WAYPOINT_RESERVATION_TTL_SECONDS=120 e
WAYPOINT_RESERVATION_RENEW_INTERVAL_SECONDS=30, com 0 < intervalo < TTL.
O intervalo é planejamento para o cliente futuro; nenhum heartbeat foi integrado.
Reserva é ativa apenas quando released_at é nulo E expires_at > horário do banco.
Na igualdade já expirou. Nova aquisição substitui a expirada atomicamente.
Limpeza periódica não determina disponibilidade. Não há transação durante
a interação do usuário, rede, geração de DOCX ou I/O externo.

Uma mutação é admitida no instante da validação após locks: pode terminar depois
do TTL, mantendo a exclusão até commit. Manter transações curtas; não prometer
que esse contexto interrompe uma operação no meio quando o relógio avança.
Saltos do relógio do servidor são um risco operacional; manter sincronização.
As constraints temporais fazem gravações incoerentes falharem com rollback.

PostgreSQL é o único backend aceito para acquire/renew/release/validate.
Em SQLite essas operações falham com ReservationBackendUnsupported, mesmo em
desenvolvimento: select_for_update não oferece a garantia necessária.
Modelos/migration e consulta consultiva continuam compatíveis com SQLite.
O relógio SQLite é usado apenas nessa leitura e em testes unitários isolados.
Não existe flag de produção que silenciosamente desabilite o guard.

A referência é a configuração PostgreSQL padrão do Django (READ COMMITTED).
Conexões com isolamento diferente podem exigir retries de transações inteiras;
falhas de serialização nunca devem ser convertidas em sucesso.
Não usar multi-database: sessões, usuários e sinalização usam o default existente.

## Testes e homologação

signaling.test_reservations contém:
- testes de contrato com clock controlado e guard mockado SOMENTE nos testes
  unitários; comprovam regras, não concorrência SQLite;
- o mesmo contrato em PostgreSQL com locks reais;
- teste sem mocks que exige recusa explícita das operações em SQLite.

signaling.test_reservation_concurrency usa TransactionTestCase, conexões
independentes, Barrier e observação de pg_blocking_pids para ordenar disputas.
As esperas têm limite e não inferem estado por sleep. Inclui primeira aquisição,
aquisição/renovação, aquisição/liberação, disputa após expiração, vencimento
durante espera, credencial antiga, lock mantido durante mutação e sessão vencida.
signaling.test_reservation_migration verifica preservação de pontos/filhos.
Referência: https://docs.djangoproject.com/en/6.0/ref/models/querysets/#select-for-update

A CI existente já descobre testes de signaling; seu YAML não foi alterado.
SQLite ignora explicitamente os testes PostgreSQL. Aprovação SQLite NÃO comprova
exclusividade transacional. Antes de integrar endpoints, executar a suíte em
PostgreSQL de homologação com credenciais dedicadas e banco de testes exclusivo:

    python manage.py test signaling.test_reservations signaling.test_reservation_concurrency signaling.test_reservation_migration

Selecionar DJANGO_DB_BACKEND=postgresql e fornecer POSTGRES_* administrativos de
TESTE por ambiente seguro. Definir DJANGO_TEST_DB_NAME novo e distinto do banco
base. O runner cria/remove esse banco; não usar --keepdb nem produção.
Não executar comandos de teste ou migrate no servidor ativo.

Antes de produção: backup/restauração, ensaio da migration e coordenação com CD
(que aplica migrations). A adição do contador pode bloquear tabela durante DDL;
medir em homologação. Não reverter migrations nem restaurar banco por rotina de
rollback. Preservar o esquema aditivo e corrigir o código em revisão compatível.
Se um backup antigo for restaurado, invalidar sessões/credenciais de clientes
anteriores para evitar reutilização de gerações já emitidas.


## Integração posterior 3A

O escopo descrito acima documenta o núcleo 2B. A proteção HTTP e o bloqueio de
gravações no Admin foram acrescentados na etapa 3A; consultar
[waypoint-reservation-api.md](waypoint-reservation-api.md) para o comportamento atual.
