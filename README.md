# Connect Evolution API

Interface web + worker de varredura para facilitar a conexão de instâncias WhatsApp via Evolution Global API. O projeto cria links temporários com QR Code, envia-os ao cliente e acompanha o status até a conexão.

## Visão geral
- **app web (FastAPI + Jinja + Tailwind):** entrega a tela de conexão (`/?t=<token>`) e APIs internas para status do QR, imagem fallback e perfil.
- **scanner (worker Python):** consulta a Evolution Global API, identifica instâncias que precisam de QR, gera/recupera o link temporário e o envia pelo WhatsApp de uma instância administrativa.
- **Redis:** armazena tokens temporários e controla links ativos por instância.
- **Evolution Global API (externa):** fornece lista de instâncias, status/QR e operações de logout.

## Fluxo resumido
1) O scanner roda em loop (`modules_scan.core_loop.main_loop`), busca instâncias com `EVOLUTION_GLOBAL_KEY` e checa o status real de cada uma (`/instance/connect/{instance}`).
2) Se a instância precisa de QR, o scanner cria ou reaproveita um token no Redis (`get_or_create_connect_link`) com TTL padrão de 4h e monta o link público usando `BASE_URL/?t=<token>`.
3) O link é enviado ao número cadastrado do cliente via instância admin (`send_text_admin_to_client`).
4) O usuário acessa o link: o app valida o token no Redis, exibe o QR e faz polling a cada 5 s em `/api/qr-status`.
5) Quando o servidor Evolution sinaliza conexão, o app reduz o TTL do token (30 s), captura nome/número/foto da instância e mostra “Dispositivo conectado”.
6) Se o número realmente conectado divergir do número cadastrado, o scanner força logout e reabre o ciclo para obter novo QR.

## Pré-requisitos
- Python 3.11+ (imagem oficial `python:3.11-slim` no Dockerfile).
- Redis 7+ (no Docker Compose já sobe automaticamente com `redis:7-alpine`).
- Acesso à Evolution Global API (domínio + keys).

## Variáveis de ambiente (.env)
- `BASE_URL` – URL pública do frontend de conexão (usada no link enviado ao cliente).
- `EVOLUTION_DOMAIN` – domínio da Evolution API (com ou sem http/https; o app adiciona https se faltar).
- `EVOLUTION_GLOBAL_KEY` – chave master usada pelo scanner para listar instâncias.
- `EVOLUTION_INSTANCE_NAME_ADMIN` – nome da instância admin usada para enviar o link ao cliente.
- `EVOLUTION_INSTANCE_KEY_ADMIN` – token da instância admin.
- `REDIS_URL` (opcional) – URL do Redis (ex.: `redis://redis:6379/0`). Se ausente, o app tenta `redis` e depois `localhost`.
- `APP_PORT` (opcional) – porta para `python app.py`; se não informar, usa `80` automaticamente.

## Como executar com Docker Compose
```bash
# editar .env com seus valores
docker compose up -d --build
```
Serviços criados:
- `redis`: Redis em memória sem persistência.
- `app`: uvicorn servindo o FastAPI (porta 80 interna, publicada como `http://localhost:8501` no host).
- `scanner`: worker em loop contínuo (`python scan.py`).

Logs podem ser vistos com `docker compose logs -f app` ou `docker compose logs -f scanner`.

## Execução local (sem Docker)
```bash
python -m venv .venv
.\.venv\Scripts\activate    # PowerShell
pip install -r requirements.txt
# se quiser sobrescrever a porta padrão (80)
set APP_PORT=8000
python app.py       # servidor web
python scan.py      # em outro terminal: worker de varredura
```
O app monta arquivos estáticos em `/static` e desativa a documentação pública (OpenAPI/Swagger) por padrão.

## Rotas expostas pelo app
- `GET /?t=<token>` – tela de conexão; tokens inválidos exibem `invalid.html`.
- `GET /api/qr-status` – status atual (`qr_code` com valor/format, `connected`, `invalid`, `error`).
- `GET /api/qr-png` – fallback que devolve o QR como PNG (gera a partir de texto ou base64).
- `GET /api/profile` – nome e número do bot conectado (quando disponível).
- `GET /api/profile-photo` – stream da foto de perfil do bot.
- `GET /favicon.ico` – favicon local.

## Estrutura do projeto
- `app.py` – inicialização do FastAPI e montagem de rotas.
- `scan.py` – entrypoint do worker.
- `modules_app/` – configuração do app, segurança (validação de token), serviços de QR/profile, utilidades e rotas.
- `modules_scan/` – integração com Evolution API, Redis, envio de mensagens e loop principal.
- `templates/` – `connect.html` (UI com Tailwind, polling do QR) e `invalid.html`.
- `static/img/` – background, thumbnail (OG) e favicon.

## Boas práticas e segurança
- Use sempre HTTPS no domínio da Evolution API e no `BASE_URL`.
- Trate as variáveis do `.env` como segredos; não reutilize valores de exemplo em produção.
- O QR code contém credenciais de sessão; prefira manter o link restrito e com TTL curto.

## Solução de problemas
- **“Redis indisponível”**: no Docker Compose, confirme se o serviço `redis` está saudável e se `app`/`scanner` estão na mesma rede do compose.
- **“Link inválido ou expirado”**: token não está no Redis ou TTL expirou; peça um novo link ao scanner.
- **QR não aparece**: confirme se o domínio Evolution está acessível e se a instância realmente está em estado `close/connecting`.
- **Divergência de número**: o scanner fará logout automático se o `ownerJid` não coincidir com o número cadastrado.

## Licença
Não foi fornecida licença explícita; confirme internamente antes de distribuição.
