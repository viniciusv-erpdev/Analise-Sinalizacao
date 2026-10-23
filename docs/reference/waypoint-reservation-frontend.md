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
com o helper uuidV4 de waypoint_reservations.js. Credenciais permanecem no closure do gerenciador, sem
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

Fechar o popup ou trocar de waypoint invalida a interação local.
Voltar/cancelar um painel interno descarta apenas seu rascunho, preservando a
aquisição enquanto os detalhes do waypoint continuarem abertos.
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
novamente a aquisição. Encerrar o relatório descarta respostas tardias. Se os detalhes do mapa continuam
abertos, a mesma aquisição é preservada e confirmada antes de editar. Se o popup
também foi fechado, a liberação aguarda operações pendentes. O backend mantém snapshot + revalidação 3A; nenhum lock longo foi introduzido.

Não navegar diretamente para o report protegido nem usar seu link em outra aba:
essa aba não possui a aquisição. Abrir o relatório pelo popup. A limitação é
intencional, para não transmitir credenciais por URL, storage ou outra janela.

## Indicadores e limites

As cores originais dos marcadores continuam indicando qualidade da sinalização.
Uma pequena marca adicional distingue disponibilidade, reserva própria e ocupação.
Enquanto desconhecido, o estado não é apresentado como disponível. O popup informa
aquisição, confirmação, perda e falha de rede; informações autorizadas permanecem
legíveis. Controles combinam permissões 2A e confirmação da reserva.

O polling de status ocorre a cada três segundos: até quatro marcadores visíveis
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

Requer navegador moderno com crypto.randomUUID ou crypto.getRandomValues (também
em HTTP interno). Sem fonte criptográfica, a aquisição falha com mensagem controlada.
Também requer dialog,
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

waypoint_sync.js consulta a cada três segundos, com uma requisição por vez.
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
o timer verifica a cada 18 segundos sem fazer consultas; ao retornar há nova consulta.
Inicialização repetida interrompe o controlador anterior e start é idempotente.

## Homologação adicional — sincronização em dois navegadores

1. Entrar como A e B autorizados em navegadores separados. A cria um ponto:
   confirmar que aparece em B em aproximadamente três segundos, sem reload,
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

- JavaScript: 144 testes aprovados no comando da CI, incluindo as suítes por import.
- Django após a correção do polling/navegação: 318 testes encontrados,
  277 aprovados e 41 ignorados, em SQLite isolado em memória.
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
   DOCX. Verificar heartbeat durante geração. Fechar o relatório retorna ao mapa
   sem perder a aquisição do popup aberto; resultado tardio não deve aparecer.
   Fechar também os detalhes deve aguardar o trabalho pendente antes de liberar.
9. Encerrar sessão em outra aba e tentar operar: exigir login, sem repetir escrita.
   Testar também usuário sem change/delete/report e CSRF inválido; reservas não
   devem conceder permissões.
10. Confirmar que nenhuma URL, storage ou mensagem contém token. Não copiar tokens
    para o relatório de homologação. Registrar navegador, ações e códigos HTTP.

Rollback: reverter os arquivos desta etapa de forma coordenada. O frontend antigo
não envia provas e ficará impedido pelo backend 3A (428), portanto não equivale a
restaurar edição. Nunca desabilitar os guards do backend para contornar rollback.

## Diagnóstico — navegação interna e polling de três segundos

Duas regressões foram reproduzidas antes da correção, com logs temporários no
harness executando o gerenciador real e backend simulado. Somente evento, estado
local, existência da reserva simulada e contagem de encerramentos foram registrados.
Os logs foram removidos após o diagnóstico; nenhuma credencial foi impressa.

1. Status iniciado durante acquire saía sem prova, retornava reserved_other e
   chegava depois da concessão. O mesmo objeto local já tinha recebido o token:
   a consulta antiga o marcava lost. O trace mostrou serverReserved=true,
   localState=lost e releaseCount=0. Isso reproduz interpretação incorreta no
   frontend, sem demonstrar perda real no PostgreSQL do ambiente do usuário.
2. Voltar de problemas, voltar/cancelar intervenção e cancelar notas chamavam
   close(), apesar de os detalhes permanecerem abertos. O trace do handler
   onBack confirmou closeCount=1. Essa é uma liberação indevida no fluxo interno.
   Enquanto release não confirma (ou falha), a reserva antiga ainda pode existir
   sem prova local, aparecendo corretamente como ocupada numa consulta sem prova.

Consultas agora vinculam sua validade ao estado no envio: intenção de aquisição,
objeto proprietário, presença da prova, confirmação de renovação e sequência de
consulta por waypoint. Dados/erros obsoletos retornam stale e não alteram estado
nem indicadores. Status durante renovação é descartado conservadoramente;
heartbeat e operações continuam confirmando no backend.

A sincronização de conteúdo já pula pontos abertos; isso permanece testado.
Reconstruir o painel principal por navegação interna é intencional e não encerra
a reserva. Bind não registra novos timers nem duplica os guards do popup.
Os intervalos permanecem em três segundos.

Expiração/perda real continua sendo rejeitada pelo backend. Não foi inspecionada
a reserva do navegador do usuário no PostgreSQL, nem presumido que o banco a
perdeu. A prova transacional continua nos testes PostgreSQL existentes, que devem
ser repetidos no terminal local com o ambiente de testes carregado.

## Diagnóstico — retorno do relatório e bfcache

O fluxo normal não navega para fora do mapa: o clique é interceptado e o HTML
obtido com prova entra no iframe srcdoc do diálogo. “Voltar ao mapa” no relatório
encerra esse diálogo. DOCX é recebido por fetch e baixado por blob URL.
O backend não adquire/libera reservas no relatório; mantém snapshot + revalidação.
Abrir a URL protegida diretamente em outra aba não transporta prova, e recebe 428
quando autorizado mas sem aquisição (ou login/403 conforme a sessão/permissões).
A aba do mapa continua titular; não há compartilhamento de credenciais.

Antes da correção, duas regressões novas falharam:
- Fechar relatório com popup aberto registrava closeCount=1, quando a interação
  do mapa ainda precisava da aquisição. A interface podia ficar idle/somente
  leitura; com release malsucedido, a reserva continuava válida no servidor.
- Após leave com falha de rede no release, resume não acompanhava nem repetia a
  liberação. A reserva simulada permanecia ocupada; uma nova aquisição concorria
  legitimamente contra a anterior, embora fosse o mesmo usuário.

A correção mantém a aquisição enquanto o popup do mapa estiver aberto e confirma
sua validade ao voltar. O cancelamento descarta resultados do diálogo encerrado;
não cancela trabalho já enviado no servidor nem libera durante processamento.
Sem popup proprietário, o gerenciador encerra e libera após drenar o trabalho.

Em saída real de página, a aquisição é encerrada localmente. A liberação passa
pelo mesmo caminho acompanhado, com fetch keepalive na saída. Se não houver
confirmação por rede/5xx/CSRF, a prova fica SOMENTE em memória para repetir release
autorizado, nunca para voltar a editar. Ao retornar pelo bfcache, resume tenta
concluir essa liberação; acquire aguarda a conclusão antes de disputar uma
aquisição nova. Não há aquisição forçada nem reutilização da geração antiga.
Release com geração obsoleta não libera o titular posterior.

Pageshow confirma aquisições ainda ativas; para as já encerradas, oferece nova
tentativa contextual. Relatórios restaurados com aquisição encerrada são fechados
e respostas pendentes descartadas. A ausência de prova ativa nunca habilita edição.

Classificação das evidências:
- A (reserva real anterior): reproduzido com backend simulado e release falho;
  os testes verificam retry autorizado e geração nova, sem remover titular alheio.
- B (bloqueio visual): encerramento indevido do gerenciador e ausência de ação
  contextual após retorno foram reproduzidos por handlers reais em DOM doubles.
- C (outro titular): permanece bloqueado nos testes com gerenciadores independentes.
- D (expiração/substituição): relatórios são descartados e nova aquisição é explícita.
Não foi inspecionada a reserva da sessão do navegador no PostgreSQL local.

Homologação adicional:
1. Abrir ponto em A; gerar HTML e DOCX; voltar pelo link e pelo botão do diálogo.
   Editar novamente sem fechar o popup. Não deve haver release nesse retorno.
2. Enquanto o relatório estiver ativo, tentar adquirir em outra aba e no usuário B.
   Ambos devem continuar impedidos. Fechar o popup em A e confirmar liberação.
3. Fechar relatório durante processamento: nenhum arquivo tardio deve aparecer.
   Fechar também o popup: liberação somente depois do processamento recebido.
4. Navegar para outra página com rede normal, voltar pelo histórico e confirmar
   que uma aquisição encerrada exige nova tentativa, sem reusar suas credenciais.
5. Repetir com falha de rede na saída e recuperação no retorno: retry de release
   deve anteceder acquire. Se o documento foi destruído, não existe prova em
   memória para recuperar; aguardar o TTL, sem storage nem bypass.
6. Retornar por bfcache com relatório aberto: formulário da aquisição encerrada
   deve desaparecer e controles continuar suspensos até nova aquisição válida.
7. Expirar a aquisição durante geração; adquirir em B; confirmar descarte do
   resultado antigo e impossibilidade de A liberar ou editar a geração de B.

Validação desta correção: suíte JavaScript completa aprovada; Django
accidents.test_main_flow signaling: 318 encontrados, 277 aprovados, 41 ignorados
em SQLite isolado. PostgreSQL não estava acessível ao processo do agente.
Executar os comandos PostgreSQL documentados acima no terminal local.
Os testes JavaScript não demonstram exclusividade transacional nem substituem
homologação real de bfcache em navegador. Nenhum arquivo de backend, migration,
serviço PostgreSQL ou infraestrutura foi alterado nesta correção.
