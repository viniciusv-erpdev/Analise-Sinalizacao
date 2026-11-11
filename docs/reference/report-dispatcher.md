# Despachante diagnóstico — etapa 4C.2

Implementação: `signaling/report_dispatcher.py`, função `evaluate()`. Pré-requisito:
schema até `0018_report_operational_contracts`. Nenhuma migration foi criada nesta
etapa. Os contratos de [4C.1](report-operational-contracts.md) não foram alterados.

## Comando

```text
python manage.py diagnose_report_dispatch
python manage.py diagnose_report_dispatch --dry-run
```

Ambas as formas fazem uma avaliação única e exclusivamente diagnóstica. Não há
modo ativo, polling, seleção de tentativa por argumento ou fila. O candidato é
sempre o ocupante de `ReportPublicationSlot(pk=1)`. Tentativas fora do slot são
reportadas como inconsistência, nunca selecionadas para execução.

O comando imprime um objeto JSON em uma linha. Estados operacionais observáveis
retornam exit code zero, inclusive manutenção/incompatibilidade. Falha técnica
imprime JSON `UNAVAILABLE` e termina com CommandError sanitizado/exit code não zero.
Nenhum SQL, credencial ou detalhe privado da exceção é impresso.

## Resultados

| outcome | Significado |
| --- | --- |
| NO_ADMISSION | Slot ausente/vazio, sem tentativas pendentes ou histórico operacional não verificado |
| PREPARATION_REQUIRED | Admissão e release compatíveis; identidade ainda não preparada |
| ELIGIBLE | Metadados persistidos atendem às verificações locais para solicitar lançamento; NÃO autoriza início |
| MAINTENANCE | Barreira DRAINING ou DEPLOYING |
| INCOMPATIBLE | Contrato incompatível, aprovação ausente, hashes inválidos ou configuração de supervisão divergente |
| LAUNCH_REQUESTED | REQUESTED ou início CONFIRMED aguardando claim; não criar outro lançamento |
| EXECUTION_IN_PROGRESS | Tentativa PROCESSING/STORING; não reassumir |
| UNCERTAIN | Falha/interrupção, lançamento UNCERTAIN, término apenas observado ou histórico sem prova de término |
| INCONSISTENT | Slot/fencing divergentes, tentativa fora do slot, metadados inválidos ou identidade/lançamento conflitantes |
| STALE | Dados diferentes nas duas leituras; observed_outcome registra a classificação da primeira |
| UNAVAILABLE | PostgreSQL/schema/conexão indisponível, backend incorreto ou chamada em transação externa |

Inconsistências têm prioridade sobre manutenção; razões estruturadas continuam
visíveis e o estado/generation da barreira também. Manutenção precede estados
operacionais normais. `eligible` só é true para ELIGIBLE sem mudança detectada.
`authorization_granted` é SEMPRE false e `potentially_stale` é SEMPRE true nos
diagnósticos concluídos. Flags desligadas não escondem a avaliação dos metadados:
`activation_flags` mostra seus valores, sem modificá-los ou permitir ativação.

PREPARATION_REQUIRED é normal: `admit()` não cria identidade e o diagnóstico não
chama `prepare()`. Um registro REQUESTED também não é permissão de chamar systemd.
TERMINAL_OBSERVED não se transforma em prova, slot livre ou deploy seguro.

## Leituras e verificações

Cada leitura ocorre em transação curta PostgreSQL REPEATABLE READ, READ ONLY, com
lock_timeout de 1 segundo e statement_timeout de 5 segundos. Não há SELECT FOR
UPDATE, advisory lock, get_or_create, eventos, tickets, alterações de timestamps
ou inspeção de arquivos. Ausência do slot/barreira não cria singletons; a geração
implícita da barreira OPEN é UUID zero, conforme 4C.1.

São comparados slot/epoch, admissão, snapshot e hashes, fonte, número e autoria
internamente, schema, datas, fotos e seus metadados, ausência de derivados em
ADMITTED, identidade/epoch/unidade, contrato aprovado da release, hashes de bundle
e manifesto bem formados e correlação de lançamento/invocação persistida. As listas
de identidade/lançamento são limitadas a dois registros para detectar multiplicidade;
fotos são limitadas ao máximo existente mais um. Contagens globais detectam outros
registros que a política conservadora 4C.1 não permite ignorar.

A saída é uma projeção permitida: UUIDs operacionais, estados, geração da barreira,
horários da observação, códigos de razão e flags. Não inclui snapshot, autor,
endereço, chave de idempotência, request hash, dispatch_id, storage keys, paths,
conteúdo de arquivos ou credenciais. O conteúdo privado lido para validar hashes
não é incorporado ao JSON.

Não há consultas ao systemd, host/boot atual, processos, bundle/manifesto instalado
ou storage. Essas verificações constam como `not_verified`. Hash bem formado e
aprovação no banco não atestam bytes instalados, permissões SQL ou origem confiável.

## Concorrência e futuro modo ativo

Duas observações independentes permitem detectar mudanças nos dados consultados,
inclusive geração da barreira, criação de lançamento e rotação de epoch. Mudança
visível força STALE/eligible=false. Igualdade não prova estabilidade: mudanças após
a segunda leitura, alterações transitórias revertidas ou estado externo não são
detectados. `observed_outcome=ELIGIBLE` nunca deve servir como autorização durável.

Um futuro despachante pode usar evaluate para descoberta/logs e decidir tentar a
operação transacional. Deve então revalidar os contratos de 4C.1 sob coordenação:
barreira/geração atual, slot, tentativa, epoch, identidade, release e integridade.
Se necessário, preparar identidade explicitamente fora do diagnóstico. Usar
request_launch e begin_dispatch; somente o ticket novo retornado após commit
reconhecido pode fundamentar a chamada do launcher confiável. Não usar o JSON para
reconstruir ticket, reutilizar um dispatch_id ou contornar geração alterada.

Essa revalidação ainda precisa integrar verificações externas autenticadas e
compatibilidade do bundle real. Não reaproveitar a função pura de classificação
como substituto do fencing transacional. O resultado não autoriza recuperação,
limpeza de arquivos, liberação de slot ou reabertura de manutenção.

## Testes

`python manage.py test signaling.test_report_dispatcher_postgresql`

Usa PostgreSQL real e conexões distintas. Fixtures de admissão/identidade/catálogo
e transições 4C.1 são criadas ANTES das avaliações; o diagnóstico não chama essas
operações. Os testes cobrem estados, imutabilidade das linhas, enforcement READ
ONLY pelo próprio PostgreSQL, ausência de chamadas externas, concorrência com
observadores/locks/deploy, privacidade, falha sanitizada e classificação obsoleta.
Não há geração de DOCX/PDF nem início de unidades.
