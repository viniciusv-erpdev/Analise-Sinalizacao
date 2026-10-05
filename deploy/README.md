# Primeira camada de deploy

Arquitetura planejada: **Nginx -> Gunicorn -> Django -> SQLite**.
Gunicorn executa a aplicação WSGI; systemd inicia o processo no boot, supervisiona sua execução e reinicia em caso de falha. SQLite permanece inalterado.

## Template do serviço

Substitua em `gunicorn.service.example`:

- `<APP_USER>`: usuário Linux que executará a aplicação.
- `<PROJECT_PATH>`: caminho absoluto da raiz do projeto, onde está `manage.py`.
- `<VENV_PATH>`: caminho absoluto do virtualenv deste projeto no Ubuntu.
- `<ENV_FILE_PATH>`: caminho absoluto de um arquivo de ambiente externo ao checkout, em um diretório administrativo como `/etc`. O caminho definitivo depende do servidor.

O comando usa `<VENV_PATH>/bin/gunicorn`, `config.wsgi:application`, **1 worker síncrono** e bind exclusivo em **127.0.0.1:8000**. A porta não deve ser exposta diretamente aos usuários. O virtualenv não precisa ser ativado por shell. `gunicorn==26.2.0` já está declarado em `requirements.txt`; nenhuma dependência foi instalada nesta etapa.

O serviço roda em primeiro plano, registra saída no journal e reinicia em falhas após 5 segundos, com limite de 5 tentativas em 60 segundos. A parada permite até 45 segundos antes de encerramento forçado. O timeout de worker permanece no padrão do Gunicorn (30 segundos); processamento pesado de CSV/relatórios poderá exigir ajuste após medição no servidor. Não houve tuning nesta etapa.

## Ambiente e permissões futuras

O arquivo indicado por `EnvironmentFile` é obrigatório e deverá ser criado **somente no servidor, fora do Git**, com linhas `NOME=valor` (sem `export`):

- `DJANGO_SECRET_KEY`: segredo real de produção.
- `DJANGO_DEBUG=False`.
- `DJANGO_ALLOWED_HOSTS`: hosts reais autorizados, separados por vírgulas.

Proteja esse arquivo com proprietário `root` e modo `0600`. O gerenciador systemd do sistema lê o arquivo e fornece as variáveis ao processo; o usuário da aplicação não precisa ler o arquivo diretamente. Não há segredo real nem arquivo de ambiente criado neste repositório.

O usuário do serviço precisará de acesso de leitura ao projeto e ao virtualenv, execução dos binários e travessia dos diretórios pais. Precisará também de **escrita em `<PROJECT_PATH>/db.sqlite3` e no diretório `<PROJECT_PATH>`**, pois SQLite cria arquivos auxiliares junto ao banco. Proprietários e permissões serão definidos no servidor; nada foi alterado agora.

O usuário também precisará de um diretório temporário gravável e de local gravável para o cache/configuração do Matplotlib. Se os locais padrão do servidor não atenderem, defina `TMPDIR` e `MPLCONFIGDIR` no mesmo arquivo de ambiente, apontando para diretórios previamente criados e graváveis pelo serviço. Nenhuma mudança no código ou caminho definitivo foi necessária nesta etapa.

## Comandos previstos no Ubuntu

Após substituir os placeholders, preparar o ambiente e instalar o template como `/etc/systemd/system/gunicorn.service`, estão previstos:

```sh
sudo systemctl daemon-reload
sudo systemctl enable gunicorn.service
sudo systemctl start gunicorn.service
sudo systemctl status gunicorn.service
sudo journalctl -u gunicorn.service -n 100 --no-pager
```

**Esses comandos não foram executados**: esta etapa foi preparada no Windows, fora do servidor Linux definitivo. O nome `gunicorn.service` acima é o nome proposto para instalação do template; ajuste os comandos se escolher outro nome.

HTTPS, preparação do servidor e ajustes baseados em medições ficam para etapas posteriores. O template systemd não serve arquivos estáticos por si só.

## Template HTTP do Nginx

`nginx.conf.example` prepara a camada Nginx -> Gunicorn: usuários acessam o Nginx, que encaminha requisições dinâmicas para `http://127.0.0.1:8000`. Gunicorn mantém o bind interno; **a porta 8000 não deve ser liberada externamente**. `listen 80;` representa apenas o estágio HTTP inicial, sem decidir a exposição final dessa porta pela TI.

Substitua `<SERVER_NAME>` pelo host real, também autorizado em `DJANGO_ALLOWED_HOSTS`; `<STATIC_ROOT>` pelo caminho absoluto de `staticfiles` (sem barra final); e `<MAX_UPLOAD_SIZE>` por um limite não nulo, com unidade aceita pelo Nginx, definido após validar os tamanhos de CSV/imagens e os requisitos da TI. Não há limite definitivo escolhido; os placeholders precisam ser substituídos antes da validação no servidor.

Execute futuramente `python manage.py collectstatic --noinput` antes de disponibilizar `/static/`. Nginx servirá esses arquivos diretamente de `STATIC_ROOT`, nunca da pasta source `static/`. Seu usuário precisará de leitura dos arquivos e travessia dos diretórios pais. Não há alias para a raiz do projeto, listagem de diretórios ou acesso a arquivos ocultos. Código-fonte, SQLite e segredos não são publicados pelo Nginx.

O proxy preserva `Host` e informa `X-Real-IP`, `X-Forwarded-For` e `X-Forwarded-Proto`. Para o único proxy previsto, `X-Forwarded-For` é substituído pelo IP da conexão recebida, sem confiar em valores enviados pelo cliente. Uma futura camada de proxy adicional exigirá revisão dessa política.

Não foi configurado `/media/`: os settings não definem `MEDIA_ROOT`/`MEDIA_URL` e, conforme o contexto desta etapa, uploads não dependem desse armazenamento persistente. HTTPS/certificados e configurações Django de confiança em HTTPS por proxy, redirecionamento, cookies seguros e HSTS permanecem para outra etapa.

O template não redefine timeouts de proxy; mantém os padrões do Nginx (conexão, envio e leitura: 60 segundos, sujeitos à configuração global do servidor). Esses limites não representam um prazo total da operação. Proxy timeouts, timeout do worker Gunicorn e duração real de processamento deverão ser medidos em conjunto, sem aumentar valores arbitrariamente.

No Ubuntu, a instalação futura será como um site no contexto `http`, tipicamente em `/etc/nginx/sites-available/<nome>`, com link em `sites-enabled`. Nome, caminhos e conflitos com sites existentes serão confirmados no servidor. Após substituir os placeholders e preparar o ambiente, os comandos previstos são:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

**Não foram executados**: a preparação ocorreu no Windows, sem instalação, execução ou simulação do Nginx.
