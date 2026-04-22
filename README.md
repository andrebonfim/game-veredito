# Game Veredito

Analisador de jogos da Steam com IA. Cole a URL de qualquer jogo e receba um veredito honesto — escrito como um amigo gamer, não um press release — com contexto de preço, menor preço histórico, score de reviews da comunidade e barras de performance técnica.

---

## Por que esse stack?

Comecei querendo uma coisa simples: colar uma URL da Steam e receber uma análise com cara de opinião real, não de review corporativo. O stack foi crescendo em torno disso.

**FastAPI** foi a escolha óbvia assim que decidi fazer streaming. O texto da análise aparece na tela enquanto o Gemini ainda está gerando — palavra por palavra, como um chat. Isso exige SSE (Server-Sent Events) com resposta assíncrona de verdade. Django daria um trabalhão pra isso; no FastAPI é literalmente `StreamingResponse` e pronto.

**HTMX** foi a decisão que mais me surpreendeu positivamente. Não escrevi uma linha de JavaScript. O formulário envia com `hx-post`, o resultado entra no DOM com `hx-swap`, a conexão SSE abre com `hx-ext="sse"`. O servidor manda fragmentos HTML prontos — sem API JSON, sem estado no cliente, sem bundle. Parece que você tá construindo uma SPA mas o código tem a simplicidade de um site estático.

**Jinja2** fecha o ciclo: cada fragmento que o HTMX injeta (card de análise, skeleton de loading, bloco de veredito) é um template separado renderizado no servidor. Nada de framework de frontend, nada de build step.

**CSS puro** — aqui eu deliberadamente não usei Tailwind. O visual tem efeitos que simplesmente não cabem em classes utilitárias: fundo com quatro camadas de `radial-gradient`, borda giratória no input animada com `@property` CSS, ruído SVG de textura, glow dinâmico nos vereditos. Tentar colocar isso em Tailwind seria uma bagunça de valores arbitrários. Fiz um design system com custom properties (`--accent`, `--glow`, `--radius-lg`) diretamente e ficou mais limpo assim.

**Gemini com dois modelos:** o primário é o `gemini-3.1-flash-lite-preview` (mais rápido, latência menor pro streaming), com fallback automático pro `gemini-2.5-flash` em erros como 503 e 429. O prompt pede uma resposta em duas partes separadas por um marcador `---JSON---`: primeiro o texto da análise em português informal, depois um JSON estruturado com veredito, pontos e barras de performance. Assim o streaming mostra o texto naturalmente enquanto o JSON estruturado chega só no final.

**SQLite** porque não precisa de mais. Cada análise é salva localmente e o cache em memória é aquecido no startup — sem refazer chamadas à Steam ou à IA pra jogos já analisados. Infraestrutura zero.

**SlowAPI** pra rate limiting (5 req/min por IP). Um detalhe que faz diferença: o retorno de limite excedido é HTML, não JSON — porque o HTMX espera fragmentos HTML e servir JSON numa interface assim não faz sentido.

**IsThereAnyDeal** é opcional. Se você configurar a `ITAD_API_KEY`, o menor preço histórico do jogo entra no prompt e a IA usa isso na análise. Sem a chave, simplesmente não aparece.

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
Obtenha uma em [aistudio.google.com](https://aistudio.google.com).

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
│   ├── base.html            # Layout base + todo o CSS
│   ├── index.html           # Página inicial
│   ├── app_analysis.html    # Página individual do jogo (/app/<id>)
│   ├── history.html         # Histórico de análises
│   └── components/          # Fragmentos HTMX (card, skeleton, veredito, erro)
└── static/
```

---

## Fluxo de uma requisição

1. Usuário envia a URL da Steam pelo formulário (`POST /api/analyze`)
2. Cache hit → retorna o card completo imediatamente
3. Cache miss → raspa a Steam, busca preço/reviews/ITAD em paralelo, retorna skeleton card + stream ID
4. Browser conecta em `GET /api/stream/<stream_id>` via SSE
5. Gemini transmite o texto da análise em tempo real; JSON estruturado é enviado ao final
6. Ao completar → card completo substituído via HTMX
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
- O fallback de modelo só é acionado se nenhum chunk foi transmitido ao cliente ainda — uma vez que o streaming começa, não é possível "desfazer" o que já foi enviado.
- Texto voltado ao usuário em português brasileiro; código e comentários em inglês.
