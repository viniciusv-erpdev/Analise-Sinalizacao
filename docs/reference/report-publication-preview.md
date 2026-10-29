# Etapa 7F-A - confirmacao sem publicacao

Esta referencia descreve a preparacao inicial. A ativacao posterior esta em
[report-publication-ui.md](report-publication-ui.md).

A acao Publicar relatorio oficial e renderizada somente para usuario autenticado
com view_signalingpoint, generate_signaling_report e finalize_technicalreport.
Nao ha concessao automatica. A flag do ambiente e informativa: mesmo desabilitada,
um finalizador pode abrir a preparacao e recebe aviso. Confirmar permanece
permanentemente disabled, inclusive com reserva e autosave validos.

O botao type=button nao altera o submit DOCX. O dialog nativo vive no iframe e
recebe informacoes pelo mount autorizado da janela principal: manager existente
e snapshot somente leitura de ReportDraft. O snapshot acrescenta confirmed,
pending e paused; revisao zero so e confirmada apos GET/POST validado. Nenhum
flush ou nova consulta e provocado pelo modal. Autosave/heartbeat habituais podem
continuar independentemente; nao iniciam publicacao. Nao cria createIntent,
chave de idempotencia, finalizacao, retry, novo timer ou polling.

Mostra waypoint, imutabilidade e necessidade de nova versao, estado do autosave,
revisao confirmada, quantidade de fotos e avisos. Fotos: conferencia preliminar de
JPEG/PNG, 10 arquivos, 10 MiB individual e 24 MiB total (contrato prepare_photos).
Inspecao completa de bytes/dimensoes e autoritativa no backend da Etapa 6.

Mudancas de reserva usam subscribe existente; estado do autosave usa observacao
do status ja renderizado, sem polling. Inputs atualizam a contagem. Cancelar/Escape
fecha e devolve foco ao botao; destruir/reabrir documento limpa listeners e observer.
Controles de preparacao sao excluidos do bloqueio de mutacoes do formulario:
continuam permitindo consulta/fechamento apos perda de reserva. Confirmar nunca
e habilitado. Inputs e submit DOCX continuam sujeitos as reservas normais.

Limite: a permissao do modal reflete a renderizacao autenticada, nao uma nova
consulta ao backend. Nao e garantia de permissao atual apos revogacao. A 7F-B
precisara revalidar no endpoint, concluir o autosave e congelar revisao/fotos antes
de criar uma intencao explicita. Nenhuma solucao paralela de autenticacao foi criada.

## Homologacao visual

1. Manter REPORT_FINALIZATION_ENABLED=false. Abrir waypoint reservado com analise
   individual, usando conta explicitamente autorizada a finalizar. Abrir relatorio.
2. Confirmar Gerar relatorio Word e comportamento antigo. Publicar relatorio oficial
   deve abrir apenas a preparacao, com waypoint correto e confirmacao desabilitada.
3. Editar um texto e abrir imediatamente: deve indicar pendencias/salvando. Apos
   autosave, conferir estado salvo e revisao persistida. Nao deve salvar por abrir.
4. Selecionar fotos sinteticas JPEG/PNG e conferir contagem; ultrapassar limites
   deve avisar sem enviar fotos. Conferir aviso de ambiente desabilitado.
5. Simular falha de rede/reserva no ambiente de testes: modal mantem avisos e
   fechar continua possivel. Nao modificar reservas/dados reais para demonstrar.
6. Cancelar, Escape, reabrir, retornar ao mapa e gerar DOCX. DevTools Network nao
   deve conter POST report-finalizations nem retry; autosave/renovacao normais
   continuam permitidos. Nenhuma intencao/chave de publicacao deve ser criada.
7. Conta apenas com geracao DOCX nao ve a nova acao; anonimo segue login existente.
8. Testar teclado, foco, rolagem e largura 320/768/1280 no iframe.

## Validacao

79 testes JavaScript passaram (preparacao, draft, reservas/modal e cliente 7E).
46 testes Django passaram (download DOCX e autorizacao) em banco SQLite temporario.
PostgreSQL da nova etapa e inspecao visual permanecem pendentes.

```powershell
node --test static/js/report_publication_preview.test.js static/js/report_draft.test.js static/js/waypoint_reservation_ui.test.js static/js/report_finalization.test.js
python -B manage.py test signaling.test_report_download signaling.test_authorization --verbosity 2
python -B manage.py check
git diff --check
```

Para repetir em PostgreSQL, ativar .venv e dot-source scripts/local-postgres-env.ps1
no PowerShell autenticado. Confirmar host local e test_analise_dev descartavel antes
do comando de testes; sem --noinput/--keepdb. Nao executar migrate em analise_dev.
Sem modelos/migrations, publicacao real, mudanca de documentos, deploy ou 7F-B.
