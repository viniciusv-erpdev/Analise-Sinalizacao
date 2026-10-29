# Etapa 7F-C1 - refinamento visual de relatorios e waypoints

Sem modelos, migrations, exclusao, alteracao de permissoes ou documentos oficiais.

## Alteracoes

- Navegacao de biblioteca/detalhes alinhada no alto a direita, em fluxo de layout
  sem posicionamento sobre o conteudo. Retorno preserva filtros conhecidos e
  pagina; nao recebe destino externo. Consultas de leitura e autorizacao intactas.
- Relatorio standalone tem Voltar ao mapa no alto a direita. Dentro do iframe,
  esse link e removido ANTES do srcdoc: somente Encerrar relatorio do dialog pai
  fica visivel, agora alinhado a direita. O mesmo finish continua tratando autosave,
  confirmacao de descarte e propriedade da reserva pelo mapa.
- Confirmacao de publicacao tem um unico Cancelar e fechar no cabecalho. Descarte
  tambem mostra Cancelar primeiro no DOM e no alto a direita, sem mudar handlers.
- Fundo do iframe tem scroll bloqueado apenas enquanto modal de publicacao esta
  aberto, restaurado ao cancelar/destruir. O formulario continua sendo o dono do
  scroll dentro do dialog externo; lista de sinistros nao ganha scroll adicional.
- Cabecalho do waypoint usa point.id vindo do backend: Waypoint #ID, com status
  como texto secundario. Subformulario de intervencao mostra a mesma referencia.
  O unico fechamento do popup permanece nativo do Leaflet; popupclose/end intactos.
- Publicar relatorio oficial usa btn-success e o publish-icon.svg existente,
  decorativo, com texto visivel. Nenhuma mudanca em idempotencia, busy, CSRF ou
  estados de publicacao. SHA-256 continua recolhido em Detalhes tecnicos.
- Detalhes mostram Publicado (condicao ja exigida pela politica), sem inventar
  estado administrativo/cancelamento. Autor e Waypoint de origem usam dados
  historicos; UUIDs e caminhos nao viram informacao principal.

## Dependencia investigada: sair da analise

O bloco account_controls.html do formulario era um POST para LogoutView. Sua
funcao e encerrar autenticacao/analise, distinta de fechar o relatorio. Foi removido
somente dessa tela, sem alterar logout global ou navbar. O ciclo de reserva e
responsabilidade do pai: finish()/manager.close()/popupclose, nao desse botao.
O aviso de sessao expirada usado pelo JavaScript do formulario foi mantido sem
reintroduzir logout. Handlers gerais de navegacao/autenticacao permanecem.

## Validacao

80 testes Django aprovados em SQLite temporario (biblioteca, detalhes, arquivos,
politica de leitura e DOCX). 159 testes JavaScript aprovados. A suite cobre ID real, remocao do voltar redundante,
fechamento com reserva, scroll/foco do modal, descarte, publicacao e PGTs.
Check e git diff --check executados. Nao houve migration em banco existente.

## Homologacao visual no navegador

1. Testar viewport 320, 768 e 1280px: retorno/fechamento no alto a direita, sem
   sobrepor titulo, conteudo ou controles. Conferir foco visivel com Tab/Shift+Tab.
2. Biblioteca: filtrar autor/ano, ir a pagina 2, abrir um numero e voltar. Filtros
   e pagina devem continuar iguais. Testes usam 21 registros sinteticos somente
   no banco descartavel; nao criar dados reais em massa apenas para esse cenario.
3. Detalhes: conferir emissao/autor/waypoint/versao, cards e detalhes tecnicos
   recolhidos. Testar PDF, DOCX e fotografias com ambas as permissoes; conta apenas
   de leitura nao recebe acoes de arquivos. Nenhuma regra de download mudou.
4. Mapa: conferir Waypoint #ID contra o registro persistido, fechar pelo X nativo,
   reabrir, editar e entrar/sair do subformulario de intervencao. Nao ha X extra.
5. Relatorio: verificar ausencia do bloco Usuario/Sair e encerrar analise; um unico
   Encerrar relatorio no pai. Com popup ainda aberto, fechar relatorio conserva a
   mesma reserva; sem dono remanescente, fechamento segue liberacao normal.
6. Publicar: botao verde com icone/texto. Modal permite Cancelar/Escape no alto,
   preserva foco e scroll; durante publicacao, bloqueios continuam funcionando.
   Nao habilitar flag em producao para demonstrar estilo. Usar dados sinteticos e
   procedimento local aprovado da 7F-B se for testar publicacao real.
7. Editar sem salvar, fechar, cancelar descarte e reabrir: textos permanecem.
   Gerar relatorio Word continua funcionando. Conferir ausencia de duas barras
   de scroll para o mesmo formulario. Modal longo possui apenas seu scroll ativo.
8. Sair pela navbar do mapa/biblioteca continua encerrando sessao normalmente.

Nao ha Playwright/Puppeteer instalado; nenhuma dependencia foi instalada. As
larguras foram consideradas nas regras de layout, mas a inspecao visual real nas
tres larguras permanece pendente. Testes estruturais nao comprovam geometria.

```powershell
node --test static/js/signaling_presentation.test.js static/js/waypoint_reservation_ui.test.js static/js/report_publication_preview.test.js static/js/report_publication_flow.test.js static/js/report_finalization.test.js static/js/report_draft.test.js static/js/report_characterization.test.js static/js/waypoint_reservations.test.js
python -B manage.py test signaling.test_report_library signaling.test_report_detail signaling.test_report_artifacts signaling.test_report_read_access signaling.test_report_download --verbosity 2
python -B manage.py check
git diff --check
```

Para PostgreSQL, ativar venv e autenticar com scripts/local-postgres-env.ps1; confirmar
host local e test_analise_dev descartavel antes de executar os testes. Sem --noinput
ou --keepdb automaticos. Nao executar migrate em analise_dev/producao.

## Complemento: cards de geracao e publicacao

- Fechar relatorio agora e um X de 36px no mesmo lugar do controle anterior,
  com aria-label e title. O handler finish e o ciclo de reserva nao mudaram.
- Acoes Word/publicacao compartilham altura minima e largura flexivel. O icone
  publish-icon.svg e a cor verde foram preservados.
- O modal mostra somente Status: Salvo, Nao salvo ou Salvando. Salvo requer
  revisao confirmada pelo backend e autosave sem pendencias/bloqueios. Validacao
  de fotos, formulario, reserva, permissao e flag continua independente e integral.
- Sucesso oculta confirmar/verificar/retry. HTTP 202 permite verificar, nunca
  declara sucesso. Retry so aparece para tentativa FAILED/INTERRUPTED, exceto
  erros definitivos de origem/integridade/chave. O fluxo continua reconsultando
  o servidor antes de retry e reutiliza a chave persistida.
- Preparar nova publicacao fica no formulario, fora do modal. E uma acao
  explicitamente distinta: reconsulta tentativa resolvida antes de limpar o
  journal; nao publica nem cria UUID. Outra confirmacao e necessaria. Fechar,
  reabrir e recarregar preservam a tentativa. Novos numeros nao sao novas
  versoes do documento anterior; esse fluxo nao implementa edicao/versionamento.

Homologacao complementar: editar e observar Nao salvo -> Salvando -> Salvo;
interromper rede e confirmar bloqueio sem perda de textos; simular demora/202 e
verificar a tentativa; sucesso deve apresentar numero/versao/link autorizado sem
botoes redundantes. Fechar/reabrir/recarregar nao pode publicar. Testar preparar
nova publicacao explicitamente, cancelar e confirmar que nao ha novo registro.
Conferir Word e fechamento com popup aberto/fechado, nos viewports 320/768/1280.
