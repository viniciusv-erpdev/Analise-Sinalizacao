# HTTPS opcional — preparação, sem ativação

## Fonte e limites da inspeção

Este checkout não contém a implementação Ansible do repositório de infraestrutura
mencionado no pedido. Foram inspecionados `deploy/nginx.conf.example`,
`deploy/gunicorn.conf.py`, settings e CI. Não houve acesso aos servidores.
A role `deploy/ansible/roles/nginx_candidate` é uma unidade de integração:
incorporar essa mesma role ao Ansible existente quando ele estiver disponível,
sem criar outro fluxo de deploy. Ela apenas renderiza um candidato; não instala
pacotes, configura sites, emite certificados ou opera serviços. Não há inventário,
playbook de deploy nem handler novo.

O exemplo HTTP antigo permanece como referência de compatibilidade; o template
Jinja é a fonte para parametrização futura. Um teste compara o HTTP renderizado
com esse exemplo, ignorando apenas comentários e espaços.

## Variáveis Ansible

| Variável | Padrão | Uso |
| --- | --- | --- |
| `nginx_https_enabled` | `false` | Adiciona servidor 443 TLS |
| `nginx_server_name` | `_` | Host único, sem esquema/porta; definir explicitamente para TLS |
| `nginx_tls_certificate` | vazio | Caminho absoluto externo do certificado e cadeia PEM |
| `nginx_tls_certificate_key` | vazio | Caminho absoluto externo da chave privada |
| `nginx_http_redirect_https` | `false` | Redirecionamento 308 para hostname fixo; exige TLS |
| `nginx_forwarded_for_mode` | `remote_addr` | `remote_addr` sobrescreve a cadeia; `append` preserva o comportamento de produção informado |
| `nginx_static_root` | vazio, obrigatório | Caminho verificado do collectstatic |
| `nginx_max_upload_size` | vazio, obrigatório | Limite atual verificado, inteiro positivo com k/m/g |
| `nginx_candidate_path` | vazio, obrigatório | Arquivo candidato absoluto, pai existente, fora da árvore ativa do Nginx |

Os switches devem ser booleanos YAML, sem aspas. Certificados e hostname não são
exigidos com TLS desativado. `_` não é wildcard de autorização: manter os hosts
atuais no inventário e em `DJANGO_ALLOWED_HOSTS`. A interface aceita um host
simples; configurações reais com múltiplos nomes, IPv6 ou caminhos com espaços
precisarão de adaptação após inspeção, nunca substituição automática.

A role rejeita `/etc/nginx/` como destino, mas caminhos personalizados ou links
simbólicos só podem ser verificados pelo operador. Não usar nenhum destino que
esteja incluído pela configuração ativa. O candidato não é validado com
`template.validate: nginx -t -c %s`: ele contém blocos `server`, não uma
configuração principal completa.

## HTTP e Django

Com os padrões, só existe `listen 80`, sem TLS, redirecionamento ou HSTS.
Permanecem o proxy `127.0.0.1:8000`, Host original, protocolo informado por
`$scheme`, política explícita de X-Forwarded-For, bloqueio de arquivos ocultos,
alias `/static/` e limite de upload
informado. Rotas e uploads dinâmicos continuam passando por `location /`.
Não há `/media/` no exemplo nem MEDIA_ROOT nos settings: não se inventou um alias.
Conferir uploads e quaisquer locations/timeouts extras na configuração real antes
de migrá-la. O exemplo do repositório não prova equivalência com o servidor.

Variáveis do ambiente externo do Django (todas `false` por padrão):

- `DJANGO_TRUST_PROXY_HTTPS`: configura `SECURE_PROXY_SSL_HEADER` para
  `HTTP_X_FORWARDED_PROTO=https`. Só habilitar depois de confirmar que Gunicorn
  aceita apenas o proxy confiável e que ele sobrescreve o header recebido.
- `DJANGO_SESSION_COOKIE_SECURE`: cookie de sessão exclusivo de HTTPS.
- `DJANGO_CSRF_COOKIE_SECURE`: cookie CSRF exclusivo de HTTPS.

`SECURE_SSL_REDIRECT=False` e `SECURE_HSTS_SECONDS=0` permanecem explícitos;
redirecionamento opcional pertence ao Nginx. Não é necessário adicionar
CSRF_TRUSTED_ORIGINS para acesso no mesmo host/esquema: validar login/POST com o
hostname autorizado e reconhecimento correto do protocolo. Origens diferentes
exigem avaliação separada, sem wildcard. Cookies seguros devem ficar desativados
enquanto usuários ainda precisarem autenticar por HTTP.

## Procedimento futuro em homologação

Este roteiro só deve ser executado em outra etapa autorizada, pelo deploy
controlado existente. Nenhum comando de servidor foi executado neste trabalho.

1. Identificar no repositório de infraestrutura o inventário/role responsável pelo
   site. Integrar a role candidata ao fluxo, mantendo separação de ambientes.
   Registrar `nginx -T` (saída administrativa, fora do Git), includes, listeners,
   nomes/caminhos reais, limite de upload, permissões, versões Nginx/OpenSSL e
   eventuais locations adicionais. Guardar cópia da configuração e ambiente atual.
2. Definir o hostname de homologação e autorizá-lo em `DJANGO_ALLOWED_HOSTS`,
   mantendo os hosts HTTP necessários. Pode-se testar sem DNS público usando
   resolução local ou `curl --resolve`; isso não dispensa certificado confiável
   cujo SAN corresponda ao hostname. Emissão/distribuição serão definidas depois.
3. Disponibilizar certificado/cadeia e chave fora do checkout pelo mecanismo a
   definir. Verificar validade, SAN, cadeia, correspondência da chave e acesso
   restrito da chave ao processo master do Nginx. Não copiar segredos para Git.
4. No inventário de homologação, definir valores verificados para os caminhos e
   limite. Definir `nginx_server_name`, `nginx_tls_certificate` e
   `nginx_tls_certificate_key`; usar `nginx_https_enabled: true` e inicialmente
   `nginx_http_redirect_https: false`. Renderizar fora da árvore ativa. Nenhum
   caminho de servidor foi predefinido aqui.
5. Validar o candidato em configuração principal temporária que reproduza o
   contexto/inclusões necessários sem duplicar o site antigo. Para uma validação
   isolada mínima, criar arquivo absoluto com `events {}` e
   `http { include /CAMINHO/ABSOLUTO/DO/CANDIDATO; }`, com pid/logs em caminhos
   apropriados ao ensaio; executar `sudo nginx -t -c /CAMINHO/DO/WRAPPER`.
   O comando abre os certificados indicados, sem iniciar o serviço. Não apontar
   `-c` diretamente para o fragmento `server`. Depois da instalação pelo deploy
   controlado, exigir também `sudo nginx -t` sobre a configuração completa antes
   de qualquer reload. Se falhar, restaurar os arquivos, sem reload.
6. Preparar `DJANGO_TRUST_PROXY_HTTPS=true` no ambiente externo e aplicá-lo pelo
   procedimento habitual do serviço. Instalar/recarregar o site somente na janela
   autorizada e após os testes. Confirmar HTTP e HTTPS, login/CSRF, estáticos,
   uploads, mapa e relatórios. Um teste sem DNS pode usar
   `curl --resolve HOSTNAME:443:IP https://HOSTNAME/`, sem `-k`.
7. Só após aceitação exclusiva de HTTPS, habilitar redirecionamento se desejado e
   os dois cookies seguros. Repetir renderização, `nginx -t`, aplicação controlada
   e testes. 308 preserva método/corpo, mas clientes e uploads devem ser ensaiados.
   HSTS e automação de renovação ficam para decisão posterior.

## Reversão e produção

Para reverter, restaurar variáveis/candidato HTTP (`nginx_https_enabled: false`,
`nginx_http_redirect_https: false`) e ambiente Django anterior, com cookies seguros
`false` e confiança do proxy `false` se era o padrão. Validar com `nginx -t` e
aplicar pelo fluxo controlado. Cookies já gravados como Secure podem exigir novo
login/limpeza no navegador; redirects 308 podem ficar em cache. Não remover
certificados nem mudar banco ou migrations para reverter.

Em produção, repetir a descoberta e o ensaio, definir hostname próprio, estratégia
de emissão, renovação e distribuição, permissões dos certificados, acessibilidade
da porta 443 e janela de deploy/rollback. Confirmar que não há outro proxy antes
de habilitar confiança no header. DNS, firewall e serviços serão tratados apenas
em tarefas posteriores autorizadas. TLS 1.2/1.3 depende do Nginx/OpenSSL instalado.
As versões de produção foram informadas pelo operador (ver revisão abaixo);
build, módulos e configuração global ainda exigem verificação antes da implantação.

## Verificações locais/CI

Em ambiente de desenvolvimento com as dependências da aplicação e Jinja2/PyYAML:

```sh
python manage.py check
python manage.py test config.test_proxy
python -m unittest scripts.test_nginx_template
```

O teste de sintaxe HTTP usa Nginx local quando disponível; sem ele fica marcado
como skip. A CI Linux extrai o binário Nginx apenas no runner descartável e testa sem
iniciar serviço. TLS é renderizado nas duas variantes de redirecionamento, sem
gerar certificados. `nginx -t` para TLS depende de certificados reais fornecidos
posteriormente; não está comprovado por esses testes.

Referências: [Django/proxy HTTPS](https://docs.djangoproject.com/en/6.0/ref/settings/#secure-proxy-ssl-header),
[Nginx TLS](https://nginx.org/en/docs/http/ngx_http_ssl_module.html),
[Nginx -t](https://nginx.org/en/docs/switches.html) e
[Ansible template](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/template_module.html).

### Resultado desta preparação

Validação local: `manage.py check` sem problemas, quatro testes de proxy Django
aprovados e dois testes de renderização aprovados (equivalência HTTP e matriz
HTTPS). Dois testes ficaram como skip por ausência local de Ansible/Nginx.
YAML da role/workflow foi carregado com sucesso e `git diff --check` passou.
A CI foi adicionada, mas não foi executada remotamente nesta etapa. Nenhum
`nginx -t` real ou validação de certificados foi executado localmente.

## Revisão com a configuração de produção informada

Dados fornecidos pelo operador: Nginx **1.28.3**, OpenSSL **3.5.5**, HTTP 80,
Gunicorn em `127.0.0.1:8000`, sem HTTPS. Não houve inspeção remota. O bloco
fornecido está em `tests/fixtures/production-http.conf` apenas como referência de
teste, sem chave ou certificado. Valores correspondentes estão em
`ansible/examples/production-http.yml`, sem inventário, alvo ou tarefa de deploy.

| Item | Produção informada / parametrização equivalente |
| --- | --- |
| Nome do servidor | `nginx_server_name: "172.28.240.99"` |
| Estáticos | `nginx_static_root: /var/www/analise-sinalizacao/static` |
| Limite de corpo | `nginx_max_upload_size: 500M` |
| X-Forwarded-For | `nginx_forwarded_for_mode: append` |
| HTTP/HTTPS | `nginx_https_enabled: false`, `nginx_http_redirect_https: false` |

O template anterior divergia em X-Forwarded-For: descartava a cadeia recebida
usando `$remote_addr`, enquanto produção usa `$proxy_add_x_forwarded_for`.
A nova opção `append` mantém essa semântica nos dois protocolos. O padrão genérico
`remote_addr` permanece compatível com o exemplo HTTP antigo; **não equivale à
produção sem carregar explicitamente as variáveis acima**. Caminhos e limite de
homologação precisam ser fornecidos independentemente, sem copiar os de produção.

Com esse conjunto de variáveis, o teste compara todas as diretivas do HTTP gerado
com o bloco de produção, ignorando apenas comentários/espaços. O teste de modo
duplo também compara integralmente ambos os blocos de aplicação com essa base,
removendo somente as diretivas TLS. Logo, rotas, proxy, headers, bloqueio de
ocultos, alias e limite 500M permanecem iguais. `nginx_https_enabled: true` não implica redirecionamento: com
`nginx_http_redirect_https: false`, HTTP e HTTPS atendem simultaneamente. Os
caminhos de certificados só são exigidos com HTTPS habilitado.

O alias real termina em `/static/`, não no `staticfiles` sugerido no exemplo
antigo. Foi preservado exatamente conforme informado. Antes de uma implantação,
confirmar como o collectstatic/deploy atual abastece esse diretório; não alterar
STATIC_ROOT nem mover arquivos nesta revisão. Não há location de media no bloco
fornecido; uploads continuam passando pelo proxy e pelo limite de corpo.

### Headers e fronteira de confiança

`append` inclui valores de X-Forwarded-For enviados pelo cliente antes do IP da
conexão. Preservar esse comportamento **não torna a cadeia inteira confiável**;
consumidores de IP, logs, auditoria e rate limits não devem tratar o primeiro IP
como autenticado. Esta revisão não muda essa política atual. A documentação do
[Nginx descreve a composição da cadeia](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#var_proxy_add_x_forwarded_for).

Nos dois listeners, `X-Forwarded-Proto` é sobrescrito com `$scheme`, sem usar o
header arbitrário do cliente. Ao habilitar `DJANGO_TRUST_PROXY_HTTPS`, Django
reconhece `https` como seguro e `http` como não seguro; não transforma todo tráfego
em HTTPS. Sem a opção, o header é ignorado. X-Forwarded-For não decide is_secure.

**SECURE_PROXY_SSL_HEADER não valida REMOTE_ADDR nem autentica o Nginx.** O teste
explicita que um cliente com acesso direto ao Gunicorn poderia forjar HTTPS com
a opção habilitada. A garantia depende do bind exclusivo em loopback informado,
da ausência de encaminhamentos alternativos e de somente processos locais
confiáveis acessarem essa porta. Não se presume que qualquer header chamado
X-Forwarded-Proto prove a origem. Verificar o isolamento real e as opções
`forwarded_allow_ips`/`secure_scheme_headers` efetivas do Gunicorn antes de ativar;
um processo local ou encaminhamento indevido continua sendo um risco. Nenhum
middleware ou mudança de arquitetura foi introduzido. Essa condição segue as
[advertências do Django](https://docs.djangoproject.com/en/6.0/ref/settings/#secure-proxy-ssl-header).

Enquanto os protocolos coexistirem, manter cookies seguros desativados permite
login por HTTP, mas mantém a exposição inerente a autenticação sem TLS. Não há
redirecionamento Django nem HSTS automático.

### Hostname e TLS futuros

É possível trocar `nginx_server_name` por um hostname, sem modificar o template.
Atualizar `DJANGO_ALLOWED_HOSTS` externamente e obter certificado cujo SAN cubra
o novo nome. Manter o IP autorizado no Django se o acesso HTTP por IP precisar
continuar; seleção do site por IP após trocar server_name depende dos demais
sites/default_server reais, ainda não conhecidos. A interface atual aceita um
nome por site, não uma lista de aliases.

As diretivas TLS 1.2/1.3 usadas são compatíveis com as versões informadas conforme
a [documentação do módulo SSL](https://nginx.org/en/docs/http/ngx_http_ssl_module.html#ssl_protocols).
Isso não valida o build instalado, seus includes globais, os certificados ou o
handshake. O runner da CI usa o pacote da distribuição, não comprova o par exato
Nginx 1.28.3/OpenSSL 3.5.5. Antes de qualquer implantação continuam necessários:
integração com o Ansible de infraestrutura, revisão dos includes globais e sites,
confirmação das opções efetivas do Gunicorn, certificados reais e seus caminhos,
`nginx -t` completo, ensaio funcional em homologação e aprovação do deploy
controlado. Nada disso foi executado contra servidores nesta revisão.
### Resultado dos testes desta revisão

- Seis testes Django de configuração/confiança no proxy aprovados.
- Cinco testes de renderização aprovados: exemplo antigo, produção informada,
  modo duplo HTTP/HTTPS, hostname/header e matriz com/sem redirecionamento.
- Dois testes opcionais não executados por ausência local de Nginx e Ansible.
- `manage.py check`, leitura dos YAML e `git diff --check` sem erros.
- CI remota, Nginx real, handshake TLS e certificados não foram testados nesta revisão.
