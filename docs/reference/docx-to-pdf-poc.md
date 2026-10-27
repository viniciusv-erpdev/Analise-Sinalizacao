# PoC DOCX → PDF — Etapa 5

## Estado e escopo

Implementação isolada, sem views novas, alterações de frontend, modelos, migrations,
reserva, persistência de documentos ou infraestrutura. O serviço recebe **bytes**;
não recebe caminhos de documentos nem parâmetros do navegador. A edição futura
continuará baseada em dados estruturados; DOCX e PDF são representações derivadas.

No ambiente Windows auditado, LibreOffice não foi encontrado no PATH nem nas pastas
padrão. Portanto a PoC está **parcialmente validada**, sem aprovação de renderização.
Os testes com conversor simulado e com subprocessos Python reais não equivalem a
uma conversão LibreOffice. Windows e Ubuntu precisam de aceite visual independente.

## Diagnóstico

`signaling.report_generator.generate_signaling_report` retorna `BytesIO` sem HTTP.
A view `point_report` apenas devolve esse buffer como anexo DOCX. Nada nesse fluxo
foi alterado. O documento real usa tabelas, JPEG/PNG, gráficos Matplotlib em PNG,
ícones SVG rasterizados com resvg, cabeçalho com logo, rodapé e margens próprias.
As fontes incluem **Calibri**, **Arial** e **Verdana**; gráficos já são rasterizados.
Não há campo PAGE/NUMPAGES no gerador atual: a PoC não acrescenta numeração.

O exemplo de Gunicorn tem um worker síncrono e não altera o timeout padrão de
30 segundos. Uma conversão de até 60 segundos não deve ser inserida nesse fluxo.

## Escolha técnica

LibreOffice Writer headless reaproveita o layout do DOCX sem reconstruir o relatório
em HTML. Perfil isolado evita encaminhamento para uma instância gráfica existente.
`docx2pdf`/automação do Word não atendem ao Ubuntu sem Word; HTML → PDF exigiria
outro template e não valida a fidelidade do DOCX atual. APIs externas acrescentariam
tráfego de documentos, custo e dependência desnecessários nesta PoC.

A dependência opcional `pypdf==6.21.3` serve para validação estrutural (xref, páginas,
MediaBox, ausência de criptografia), não para renderização. Fica somente em
`requirements-pdf-poc.txt`, sem alterar as dependências do fluxo DOCX existente.

## Uso do serviço

```python
from signaling.pdf_conversion import ConversionOptions, convert_docx_to_pdf

pdf_bytes = convert_docx_to_pdf(docx_bytes, options=ConversionOptions(
    executable="/usr/bin/libreoffice",  # configuração administrativa confiável
    timeout_seconds=60,
))
```

Omitir `executable` procura o binário no PATH e nos locais padrão do Windows.
`LIBREOFFICE_EXECUTABLE` é reconhecido pelos testes de integração; o serviço exige
que o chamador passe essa configuração explicitamente. Nunca mapear opções, caminhos
ou executáveis recebidos de uma requisição HTTP para `ConversionOptions`.

Erros têm `code` fixo, como `converter_unavailable`, `invalid_docx`,
`conversion_timeout`, `converter_failed`, `pdf_not_produced` ou `invalid_pdf`.
O código de saída fica em `returncode`. `diagnostics` contém caudas privadas de
stdout/stderr; não registrar esse objeto, dicionário da exceção, argv ou conteúdo
em logs. `str(error)` contém só o código seguro.

## Dependências Windows — instalação manual

Instalar o MSI oficial do LibreOffice Writer por decisão do administrador.
Exemplo de comando manual, com arquivo previamente baixado do site oficial:

```powershell
msiexec.exe /i 'C:\Downloads\LibreOffice_<versao>_Win_x86-64.msi'
```

Não foi executado. Não é necessário Microsoft Word. Preferir o executável de
console da instalação MSI, e não um launcher de loja/MSIX:

```powershell
& 'C:\Program Files\LibreOffice\program\soffice.com' --version
.\.venv\Scripts\python.exe -m pip install -r requirements-pdf-poc.txt
.\.venv\Scripts\python.exe -B -m scripts.pdf_poc --libreoffice 'C:\Program Files\LibreOffice\program\soffice.com' --output-dir "$env:TEMP\signaling-pdf-review-$(Get-Date -Format yyyyMMdd-HHmmss)"
```

O último comando cria um diretório novo e exclusivo com DOCX/PDF **sintéticos**
para inspeção local, sem sobrescrever arquivos existentes. É um artefato de teste
solicitado na CLI, não armazenamento definitivo do serviço. Sem `--output-dir`,
a conversão ocorre somente em memória e temporários. O exemplo não consulta SQL.
Em caso de conversor ausente, retorna código 2 e informa `converter_unavailable`;
com `--output-dir`, o DOCX sintético continua disponível para inspeção.

## Ubuntu — preparação recomendada, não executada

Exemplo para Ubuntu 24.04; conferir nomes dos pacotes para a versão efetiva da VM:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends libreoffice-writer fontconfig fonts-crosextra-carlito fonts-liberation2 fonts-dejavu-core
fc-cache -f
command -v libreoffice
libreoffice --version
fc-match Calibri
fc-match Arial
fc-match Verdana
.venv/bin/python -m pip install -r requirements-pdf-poc.txt
.venv/bin/python -B -m scripts.pdf_poc --libreoffice /usr/bin/libreoffice --output-dir "$(mktemp -d)/review"
```

Carlito é uma alternativa métrica a Calibri; Liberation Sans pode substituir Arial.
Isso não garante a mesma paginação. Verdana requer a fonte devidamente licenciada
ou aceite explícito de uma substituição; os pacotes acima não garantem equivalência
métrica de Verdana. Não copiar fontes proprietárias do Windows sem verificar licença.
Usar as mesmas fontes/versões em homologação e execução. Registrar `fc-match` e
versão do LibreOffice no aceite. Não modificar fontes ou estilos DOCX nesta PoC.

O usuário do conversor/Gunicorn precisa somente ler binário, bibliotecas, fontes e
assets do relatório, atravessar os diretórios pais e criar/remover arquivos na raiz
temporária administrativa. Sem sudo, sem escrita no checkout ou diretório público.
Perfis, cache XDG e TMP ficam privados por conversão. O ambiente do filho exclui
credenciais PostgreSQL e segredos Django. Nenhum alias Nginx deve publicar temporários.

## Isolamento e limites padrão

| Limite | Valor e razão |
| --- | --- |
| DOCX compactado | 32 MiB: fotos/gráficos usuais, sem admitir o máximo teórico de 100 MiB do formulário |
| ZIP descompactado | 128 MiB e até 2048 entradas: conter expansão abusiva |
| XML individual | 8 MiB; rejeita DTD/entidades, XML com NUL, macros, objetos incorporados, relações externas e campos ativos fora de PAGE/NUMPAGES |
| PDF | 64 MiB e até 200 páginas: limite operacional inicial, não regra do relatório |
| Diretório temporário | 256 MiB / 4096 arquivos, monitorados; pode haver ultrapassagem breve entre amostras |
| Tempo | 60 s de execução; encerramento/limpeza podem acrescentar alguns segundos |
| Memória do conversor | 1 GiB por Job Object no Windows; RLIMIT_AS por processo no Ubuntu |
| CPU | Relógio de parede em ambos; RLIMIT_CPU também no Ubuntu |
| Arquivo no Ubuntu | RLIMIT_FSIZE por arquivo, além da monitoração do diretório |
| Concorrência | 2 por processo Python, rejeição imediata com `conversion_busy` |
| Diagnósticos | Até 16 KiB por stream, privados |

Todos são configuráveis administrativamente e precisam de medição com documentos
representativos. O teto de memória refere-se ao subprocesso; geração DOCX, leitura
dos bytes e validação pypdf consomem memória adicional do chamador. A monitoração
não substitui quota de disco ou limites globais da VM.

O supervisor não usa shell. No Windows, um launcher no executável real do Python
aguarda a associação ao Job Object antes de iniciar o conversor; fechar o job encerra
os descendentes, inclusive no timeout. Isso evita a corrida dos redirectors de venv.
No Ubuntu, usa sessão/grupo próprio, limites antes de exec e kill do grupo no fim.
Em sucesso ou exceção normal, arquivos/perfis são removidos por TemporaryDirectory.
`process_cleanup_failed` sinaliza falha excepcional de encerramento, sem bloquear
indefinidamente o chamador. Interrupção forçada do processo, SIGKILL ou queda da VM
podem deixar diretórios; uma futura política de limpeza operacional deverá considerar
isso. O processo não é uma sandbox para documentos arbitrários hostis; usar somente
DOCX produzidos pelo sistema e manter o LibreOffice atualizado. Rede, quotas globais
e contenção de exploits requerem isolamento do SO na futura implantação.

Não há garantia de limite global entre workers: dois slots por worker multiplicam
CPU/memória. Antes de exposição HTTP, preferir processo/serviço externo supervisionado,
com limite global de admissões, memória/disco e tempo total. Executar fora de locks e
transações de banco e tratar cancelamento do chamador. Uma fila pode ser avaliada no
futuro; nenhuma fila, Celery, Redis, serviço remoto ou mudança de Gunicorn foi criada.
Aumentar somente o timeout do worker não resolve indisponibilidade ou concorrência.

## Testes e aceite

```powershell
.\.venv\Scripts\python.exe -B manage.py test signaling.test_pdf_conversion --verbosity 2
$env:LIBREOFFICE_EXECUTABLE = 'C:\Program Files\LibreOffice\program\soffice.com'
.\.venv\Scripts\python.exe -B manage.py test signaling.test_pdf_integration --verbosity 2
```

```bash
LIBREOFFICE_EXECUTABLE=/usr/bin/libreoffice .venv/bin/python -B manage.py test signaling.test_pdf_integration --verbosity 2
```

Essas suítes não pedem criação de banco nem migrations (runner informa banco não
utilizado). A configuração Django ainda precisa ser válida; credenciais, se exigidas
pelo settings, não são usadas para SQL. Há regressão do gerador real com modelos
não salvos, autor sintético e cursor SQL explicitamente proibido. Os testes unitários
simulam apenas LibreOffice; os testes do supervisor iniciam processos Python reais
para saída limitada, timeout, árvore de filhos e excesso de temporários.
Os dois testes de integração usam LibreOffice real, verificam leitura por parser,
conteúdo, imagens e duas conversões simultâneas. Ausência do executável/dependência
resulta em skip, nunca em aprovação implícita.

Para aceite visual, gerar o exemplo, abrir DOCX e PDF em visualizadores normais e
comparar página a página:

1. Título, acentuação, análise técnica, autor e emissão.
2. Tabelas longas: colunas, cabeçalhos, alinhamento e linhas entre páginas.
3. Três imagens sintéticas, gráfico, ícone e logo sem distorção.
4. Cabeçalho/rodapé, margens e papel, sem cortes ou páginas vazias inesperadas.
5. Fontes efetivamente usadas/substituídas, quebras e quantidade de páginas.
6. Ausência de numeração que não existia no DOCX; o gerador atual não inclui PAGE.
7. Tempo, pico de RAM e espaço temporário com uma e duas conversões.
8. Conferir que o hash/bytes do DOCX original não mudou.

O PDF abrir no parser não comprova fidelidade visual. Registrar separadamente:
conversão Windows; visual Windows; conversão Ubuntu; visual Ubuntu. A PoC só será
aprovada depois da conversão real, testes e aceite visual no ambiente avaliado.

## Fontes técnicas

- [LibreOffice: argumentos, headless e perfil](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)
- [LibreOffice: exportação PDF pela CLI](https://help.libreoffice.org/latest/en-US/text/shared/guide/pdf_params.html)
- [LibreOffice: instalação oficial](https://www.libreoffice.org/installation-instructions/)
- [Ubuntu: Carlito](https://packages.ubuntu.com/en/noble/fonts-crosextra-carlito)
- [pypdf: leitura e estrutura](https://pypdf.readthedocs.io/en/latest/modules/PdfReader.html)
- [Microsoft: Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Gunicorn: timeout](https://gunicorn.org/reference/settings/)
