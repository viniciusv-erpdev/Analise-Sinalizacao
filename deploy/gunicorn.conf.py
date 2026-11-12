"""Configuracao do Gunicorn para Analise-Sinalizacao."""

workers = 2
worker_class = "sync"
bind = "127.0.0.1:8000"

timeout = 120

# Trust scheme information only from the local Nginx proxy.
forwarded_allow_ips = "127.0.0.1,::1"
secure_scheme_headers = {"X-FORWARDED-PROTO": "https"}

accesslog = "-"
errorlog = "-"
