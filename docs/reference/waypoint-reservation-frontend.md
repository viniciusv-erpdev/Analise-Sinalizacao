# Reservas no frontend — etapa 3B

## Auditoria e integração

O mapa lista dados autorizados sem adquirir reservas. Os pontos de entrada são os
popups de signaling.js, os formulários de intersection_problems.js e o relatório
HTML com report_characterization.js. As gravações já convergiam para postJson;
as exceções eram a navegação HTML/DOCX e a consulta PGT por fetch próprio.
O contrato HTTP continua em [waypoint-reservation-api.md](waypoint-reservation-api.md).

waypoint_reservations.js concentra aquisição, prova, renovação, liberação,
consulta e classificação de falhas. waypoint_reservation_ui.js coordena os
popups, indicadores e relatório. O ajuste posterior acrescenta reconciliação
HTTP de leitura, sem migration ou alteração dos serviços de reservas, pipeline,
infraestrutura ou CI/CD. As suítes novas são carregadas pelo teste JavaScript de
intersection_problems que a CI existente já executa.

## Ciclo da interação

Abrir um popup solicita uma aquisição; nenhuma operação exclusiva fica habilitada
antes da aquisição e da atualização dos dados. Cada aquisição gera um UUID v4 novo
com crypto.randomUUID. Credenciais permanecem no closure do gerenciador, sem
armazenamento persistente ou comunicação entre abas. O snapshot público não inclui
token nem geração. A prova é enviada somente nos três headers do contrato 3A.

Após adquirir, o cliente relê o payload autorizado do mapa pelo GET já existente,
sem criar endpoint novo. Isso atualiza ponto e intervenções após uso por outro
titular. Problemas/soluções mantêm sua consulta própria. A releitura do HTML inteiro
tem custo maior que um endpoint de detalhe; medir esse custo antes de otimizar.

A renovação ocorre a cada 30 segundos, com apenas uma requisição simultânea.
Cada operação protegida também confirma a reserva antes de enviar sua requisição.
O servidor decide a expiração; o cliente usa apenas uma janela conservadora de
frescor monotônico para suspender edição após timers atrasados. Ocultar a aba
suspende controles; retornar exige confirmação. Renovação transitória mantém a
prova em memória para tentar confirmar novamente, sem repetir gravações.
Falha definitiva exige nova aquisição explícita e nova leitura.

O card de gerenciamento e o botão permanente de encerramento foram removidos.
Durante uso normal não há controles manuais de reserva. Avisos discretos e
“Tentar editar novamente” aparecem somente quando a edição precisa de recuperação.
A aquisição ao abrir e a liberação ao fechar continuam automáticas.

Fechar popup, trocar ponto ou cancelar edição invalida a interação local.
Operações já enviadas mantêm heartbeat até terminar o recebimento do corpo; seus
resultados são descartados se a interação tiver sido encerrada. Só então ocorre
a liberação. Uma gravação enviada pode já ter sido confirmada pelo servidor:
cancelar a interface não é rollback. Reabrir sempre relê o estado persistido.

Navegação e logout pelo documento aguardam operações em andamento. pagehide faz
liberação best effort por fetch keepalive, sem substituir os fechamentos normais.
Se a página for terminada ou a rede cair, vale o TTL de 120 segundos do servidor.
Uma aquisição cuja resposta se perdeu pode permanecer ocupada até esse TTL, pois
o cliente não recebeu a prova necessária para liberá-la.

## Operações e relatórios

O helper central inclui prova nas gravações de status, raio, exclusão,
intervenções/condição/notas e problemas/soluções. Criação não exige reserva prévia;
o novo ponto passa a exigir aquisição ao abrir seu popup. Consultas de problemas e
listagem continuam sem reserva e respeitam as permissões 2A.

O relatório abre em dialog com iframe srcdoc do HTML obtido com os headers.
O gerenciador permanece no documento do mapa e continua renovando. Um bridge
em memória encaminha PGTs e o envio multipart do formulário com a mesma prova.
Caracterização e uploads preservam o formulário existente. HTML inválido de
formulário é reapresentado; DOCX só é baixado após consumir o corpo e confirmar
novamente a aquisição. Encerrar o relatório descarta respostas tardias.
O backend mantém snapshot + revalidação 3A; nenhum lock longo foi introduzido.

Não navegar diretamente para o report protegido nem usar seu link em outra aba:
essa aba não possui a aquisição. Abrir o relatório pelo popup. A limitação é
intencional, para não transmitir credenciais por URL, storage ou outra janela.

## Indicadores e limites

As cores originais dos marcadores continuam indicando qualidade da sinalização.
Uma pequena marca adicional distingue disponibilidade, reserva própria e ocupação.
Enquanto desconhecido, o estado não é apresentado como disponível. O popup informa
aquisição, confirmação, perda e falha de rede; informações autorizadas permanecem
legíveis. Controles combinam permissões 2A e confirmação da reserva.

O polling de status ocorre a cada 20 segundos: até quatro marcadores visíveis
mais o ponto aberto, sequencialmente, sem aquisição automática. Mapas grandes
podem demorar várias rodadas para atualizar todos os indicadores. Abas ocultas
não consultam status. A tentativa de aquisição sempre consulta o backend, sem
confiar no indicador. Não há BroadcastChannel nem compartilhamento de tokens.

A segurança transacional continua sendo a do PostgreSQL. Testes JavaScript usam
servidor simulado e DOM doubles para verificar estado assíncrono; não demonstram
exclusividade no banco nem substituem homologação em navegador.
Um bearer deliberadamente copiado continua reutilizável. UUID de documento não é
uma identidade impossível de falsificar. XSS e extensões com acesso à página são
fora desse limite de isolamento. Não há bypass administrativo novo.

Requer navegador moderno com crypto.randomUUID (HTTPS ou localhost), dialog,
fetch, AbortSignal.timeout/any e MutationObserver. As chamadas de controle têm timeout de 20 segundos; operações protegidas têm
limite de cinco minutos, permitindo heartbeat durante gerações demoradas.
PGTs mantêm o limite de 20 segundos da interface existente. Um timeout não
confirma sucesso nem reenvia escrita. Interromper o fetch não garante cancelar
processamento no servidor: a revalidação 3A descarta resultados antigos, e a
liberação continua obedecendo ao protocolo de locks. DOCX muito grande/rede lenta
pode exigir repetir a geração explicitamente.
Relatórios abertos em documento já desconectado devem ser encerrados e reabertos
após a recuperação; nenhum resultado de aquisição substituída é reaproveitado.

## Sincronização incremental do mapa

O novo endpoint POST /signaling/points/sync/ exige view_signalingpoint, sessão e
CSRF. Recebe {"known": {"<id>": "<sha256>"}} e retorna success, upserts (point e
revision) e deleted (IDs). Não consulta nem altera reservas; não retorna sua
geração, sessão, titular ou token. O payload de ponto reutiliza o serializer do mapa.

waypoint_sync.js consulta a cada dez segundos, com uma requisição por vez.
O carregamento inicial permanece no HTML. A resposta traz apenas diferenças;
o servidor lê o inventário completo a cada chamada, portanto este protocolo não
é um log incremental de eventos. O custo cresce com o número de pontos e notas,
mas dispensa cache compartilhado, cursores frágeis e migration de tombstones.
Mudanças transitórias entre chamadas podem não aparecer; o objetivo é convergir
para o estado persistido atual, sem perder mudanças por igualdade de timestamps.

Hashes abrangem o conteúdo serializado, inclusive intervenções, e detectam
gravações sem atualização de updated_at. IDs ausentes no banco removem marcadores
conhecidos. O inventário inicial inclui IDs do HTML, permitindo detectar exclusões
anteriores à primeira consulta. Problemas/soluções mantêm seu GET próprio ao abrir;
o polling não reconstrói formulários nem painéis abertos.

Marcadores são atualizados por PK, sem recriar a camada. Alterações do ponto aberto
são adiadas e seu hash não avança: reaparecem na resposta após fechar os detalhes.
Sua exclusão invalida a edição e descarta resultados pendentes, sem release HTTP
pelo polling; o backend já excluiu o ponto. Gravações locais invalidam respostas
iniciadas antes delas. Rede indisponível mantém os marcadores. Em segundo plano,
o timer verifica a cada minuto sem fazer consultas; ao retornar há nova consulta.
Inicialização repetida interrompe o controlador anterior e start é idempotente.

## Homologação adicional — sincronização em dois navegadores

1. Entrar como A e B autorizados em navegadores separados. A cria um ponto:
   confirmar que aparece em B em aproximadamente dez segundos, sem reload,
   popup automático ou POST de aquisição provocado pela sincronização.
2. A fecha os detalhes; B abre e altera status, raio, intervenção e notas.
   Ao fechar B, confirmar os dados e a aparência em A, sem duplicação.
3. A mantém um formulário com rascunho aberto. A sincronização não pode trocar
   seu conteúdo, sua referência de ponto nem sua aquisição.
4. Excluir o ponto em uma interação autorizada e confirmar remoção em ambos.
   Para simular exclusão de ponto aberto, deixar a reserva expirar em A, adquirir
   e excluir em B; retornar A e confirmar encerramento seguro dos detalhes.
5. Desconectar B: marcadores devem permanecer. Reconectar/retornar à aba e conferir
   convergência. Testar criação durante consulta atrasada e mudança rápida de aba.
6. Sem view_signalingpoint, confirmar ausência de polling no mapa e 403 no endpoint.
   Anônimo recebe 401 com CSRF válido; token CSRF inválido continua recebendo 403.
7. Confirmar que não há card permanente ou botão “Encerrar edição”; abrir/fechar
   detalhes deve adquirir/liberar automaticamente. Recuperação usa somente o link
   contextual ou fechamento e reabertura, sem mostrar credenciais técnicas.

No terminal local com PostgreSQL, repetir:

    . .\scripts\local-postgres-env.ps1
    .\.venv\Scripts\python.exe manage.py test signaling.test_synchronization signaling.test_reservations signaling.test_reservation_concurrency signaling.test_reservation_endpoints signaling.test_reservation_http_concurrency --verbosity 2

## Validação desta execução

- JavaScript: 123 testes aprovados no comando da CI, incluindo as suítes por import.
- Django no ajuste de UX/sincronização: 34 testes aprovados (sincronização,
  autorização e fluxo principal), em SQLite isolado em memória.
  Essa execução não comprova locks nem concorrência PostgreSQL.
- manage.py check e git diff --check: sem problemas.
- PostgreSQL: não executado por este processo, que não recebeu credenciais.
  As suítes existentes de concorrência 2B/3A foram preservadas.
- Navegador real: roteiro abaixo pendente; esta etapa não está homologada em
  navegador até que seja executado.

No mesmo PowerShell local, sem enviar senha ao chat:

```powershell
. .\scripts\local-postgres-env.ps1
.\.venv\Scripts\python.exe manage.py test signaling.test_reservations signaling.test_reservation_concurrency signaling.test_reservation_endpoints signaling.test_reservation_http_concurrency --verbosity 2
.\.venv\Scripts\python.exe manage.py test accidents.test_main_flow signaling
node --test static/js/individual_filters.test.js static/js/map.test.js static/js/intersection_problems.test.js static/js/report_characterization.test.js
```

Confirmar banco local analise_dev e banco exclusivo test_analise_dev. O runner
cria/remove somente seu banco de testes. Não usar credenciais de produção.

## Homologação manual — dois usuários e duas abas

1. No PostgreSQL local, entrar como usuário A autorizado. Importar CSV e confirmar
   análise, filtros, mapa e criação de ponto sem reserva prévia.
2. Abrir o ponto na aba A1. Aguardar reserva própria, editar status/raio, intervenções,
   notas, problemas e soluções. Confirmar persistência ao reabrir.
3. Duplicar a aba como A2 e abrir o mesmo ponto. Deve ficar ocupado/somente leitura,
   inclusive com o mesmo usuário e sessão. Tentar controles e confirmar ausência
   de gravações sem prova válida no Network.
4. Entrar como B em outro perfil/navegador autorizado. Abrir o mesmo ponto:
   informações continuam legíveis, operações exclusivas ficam bloqueadas.
5. Fechar A1; aguardar o indicador disponível em A2/B. A consulta não deve adquirir
   automaticamente. Usar “Tentar editar novamente” em apenas uma aba e confirmar
   que a outra continua impedida.
6. Trocar pontos rapidamente e fechar durante aquisição. Confirmar que respostas
   antigas não mudam o popup atual e que reservas abandonadas são liberadas ou
   expiram pelo TTL quando a resposta da aquisição se perdeu.
7. Suspender rede e depois a aba. Controles devem suspender. Recuperar a conexão:
   exigir confirmação; se expirou, nova aquisição explícita. Não reenviar escrita.
8. Gerar relatório HTML, consultar PGTs, editar caracterização, anexar fotos e baixar
   DOCX. Verificar heartbeat durante geração. Fechar durante geração: resultado
   tardio não deve aparecer e a liberação aguarda o trabalho recebido terminar.
9. Encerrar sessão em outra aba e tentar operar: exigir login, sem repetir escrita.
   Testar também usuário sem change/delete/report e CSRF inválido; reservas não
   devem conceder permissões.
10. Confirmar que nenhuma URL, storage ou mensagem contém token. Não copiar tokens
    para o relatório de homologação. Registrar navegador, ações e códigos HTTP.

Rollback: reverter os arquivos desta etapa de forma coordenada. O frontend antigo
não envia provas e ficará impedido pelo backend 3A (428), portanto não equivale a
restaurar edição. Nunca desabilitar os guards do backend para contornar rollback.
