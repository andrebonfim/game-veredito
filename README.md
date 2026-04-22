# Game Veredito

Analisador de jogos da Steam com IA. Cole a URL de qualquer jogo e receba um veredito honesto — escrito como um amigo gamer, não um press release — com contexto de preço, menor preço histórico, score de reviews da comunidade e barras de performance técnica.

Feito com FastAPI + HTMX + Google Gemini. Sem framework de frontend, sem build step.

---

## Funcionalidades

- Raspa a página do jogo e as reviews da Steam para capturar o sentimento real dos usuários
- Busca preço atual em BRL e desconto via API da Steam
- Opcionalmente puxa o menor preço histórico via [IsThereAnyDeal](https://isthereanydeal.com)
- Transmite a análise da IA em tempo real via SSE (Server-Sent Events)
- Persiste cada análise em um banco SQLite local
- Página `/history` com todos os vereditos já gerados
- Rate limiting: 5 requisições por minuto por IP

---

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI + Uvicorn |
| IA | Google Gemini (`gemini-2.5-flash` + `gemini-3.1-flash-lite-preview`) |
| Frontend | HTMX + TailwindCSS (CDN, sem build) |
| Templates | Jinja2 |
| Banco de dados | SQLite via SQLAlchemy |
| Rate limiting | SlowAPI |

---

## Como rodar localmente

### 1. Clone e instale as dependências

```bash
git clone git@github.com:andrebonfim/game-veredito.git
cd game-veredito
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure as variáveis de ambiente

Crie um arquivo `.env` na raiz do projeto:

```env
GEMINI_API_KEY=sua_chave_aqui

# Opcional — habilita comparação com o menor preço histórico
# Chave gratuita em https://isthereanydeal.com/dev/app/
ITAD_API_KEY=sua_chave_itad_aqui
```

`GEMINI_API_KEY` é obrigatória. O app recusa iniciar sem ela.  
`ITAD_API_KEY` é opcional — sem ela, a seção de menor preço histórico é simplesmente omitida.

Obtenha uma chave do Gemini em [aistudio.google.com](https://aistudio.google.com).

### 3. Rode

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

O app deve ser executado a partir da raiz do projeto (`game-veredito/`), não de dentro de `app/`.

Acesse [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## Estrutura do projeto

```
app/
├── main.py                  # Entry point, lifespan, handler de rate limit
├── core/
│   ├── config.py            # Configurações via pydantic-settings (.env)
│   ├── database.py          # Persistência SQLite (SQLAlchemy)
│   └── limiter.py           # Instância do SlowAPI
├── routers/
│   └── home.py              # Endpoints HTTP
├── services/
│   └── game_service.py      # Scraping da Steam, Gemini AI, cache, streaming
├── schemas/
│   └── game.py              # Modelos Pydantic (GameData, GameAnalysis, VerdictType)
├── components/
│   └── renderer.py          # Helpers de renderização Jinja2
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── app_analysis.html    # Página individual do jogo (/app/<id>)
│   ├── history.html         # Histórico de análises
│   └── components/          # Fragmentos HTMX
└── static/
```

---

## Fluxo de uma requisição

1. Usuário envia a URL da Steam pelo formulário (`POST /api/analyze`)
2. Cache hit → retorna o card completo imediatamente
3. Cache miss → raspa a Steam, busca preço/reviews/ITAD em paralelo, retorna skeleton card + stream ID
4. Browser conecta em `GET /api/stream/<stream_id>` (SSE)
5. Gemini transmite o texto da análise em tempo real; JSON com o veredito estruturado é anexado ao final
6. Ao completar → card de análise completo é inserido via HTMX
7. Resultado salvo no SQLite e no cache TTL em memória (24h)

---

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Página inicial |
| `POST` | `/api/analyze` | Dispara a análise (rate limited) |
| `GET` | `/api/stream/<stream_id>` | Stream SSE da análise em andamento |
| `GET` | `/api/reanalyze/<app_id>` | Força nova análise (ignora cache) |
| `GET` | `/app/<app_id>` | Página individual da análise |
| `GET` | `/history` | Histórico de todas as análises |

---

## Observações

- O cache em memória é por processo. Com múltiplos workers do Uvicorn (`--workers N`) o mesmo jogo pode ser buscado mais de uma vez entre processos. Aceitável para o deploy atual com worker único.
- A hierarquia de modelos de IA é `gemini-3.1-flash-lite-preview` (primário) → `gemini-2.5-flash` (fallback). O fallback é acionado em erros 503/429/404, desde que nenhum chunk já tenha sido transmitido ao cliente.
- Texto voltado ao usuário em português brasileiro; código e comentários em inglês.
