# Paggins — Black

Versão **black** da dashboard Paggins, reconstruída em código a partir do arquivo Figma
(cópia `Paggins (cópia)`, página `Web 2.0` — 52 telas em 9 seções).

Segue o **ADR #12** do `PLANO.md`: o design system vive em CSS (`app/globals.css`), não no Figma.

```bash
npm install
npm run dev     # http://localhost:3210
npm run build   # validação de tipos + compilação
```

## Tema

Tokens em `app/globals.css` (`@theme inline` do Tailwind v4). A conversão foi medida no arquivo
original, não chutada:

| Papel | Original (Figma) | Black |
|---|---|---|
| Fundo | `#0f1535` | `#000000` |
| Card | `#1a1f37` | `#0e0e11` |
| Sidebar | `#060b26` | `#060607` |
| Texto secundário | `#a0aec0` | `#8b8b96` |
| Primária | `#0b6eae` | `#1a8fd8` ← elevada p/ contraste sobre preto |
| Sucesso | `#0cc036` | `#22c55e` |
| Teal | `#4fd1c5` | mantida |

Raios **8/12/100px** são fiéis ao original. A tipografia foi trocada de Montserrat para
**Google Sans Flex** (`wght@400`) em 29/08/2026 — ver "Reforma estética" abaixo.
O gradiente azul de fundo virou a classe `.aurora` — um halo frio quase imperceptível no topo,
que dá profundidade sem sujar o preto.

## Reforma estética (em andamento — 29/08/2026)

O projeto entrou numa fase de acabamento visual, registrada em **PG2-15**. Enquanto ela durar,
os ajustes são aplicados **como máscara, não como reescrita**.

**O que isso significa na prática:** ao decidir "tipografia toda em regular", as 81 classes de peso
(`font-bold`, `font-semibold`, `font-medium`) espalhadas por 29 arquivos **não foram apagadas**.
Elas continuam no código, apenas inertes, cobertas por 4 linhas no fim de `app/globals.css`:

```css
body,
body * {
  font-weight: 400;
}
```

Essa regra está **deliberadamente fora de `@layer`**. No Tailwind v4 as utilities vivem em camada,
e CSS sem camada vence camada — por isso ela derruba `font-bold` sem precisar de `!important`.
(Confirmado no CSS compilado que o navegador recebe, não só no fonte.)

**Por que máscara:** decisão estética não é decisão fechada. Reverter uma máscara é apagar um bloco;
reverter uma reescrita é reeditar 29 arquivos. O custo de mudar de ideia fica baixo enquanto a fase
está aberta.

**Quando uma decisão se consolidar**, aí sim vale converter a máscara em reescrita — remover as
classes mortas e apagar o bloco. Fazer isso antes é pagar caro por uma escolha que ainda pode mudar.

### Aplicado até agora

| # | Ajuste | Onde | Como |
|---|---|---|---|
| 1 | Tipografia Google Sans Flex, toda em regular | `app/layout.tsx`, `app/globals.css` | máscara `body, body * { font-weight: 400 }` — 81 classes de peso seguem inertes |
| 2 | Cards sem traçado | `app/globals.css` | máscara `.bg-card { border-color: transparent }` — largura de 1px preservada, sem reflow |
| 3 | Sidebar: ícones sem fundo | `components/shell.tsx` | removido o `IconBox` colorido; `h-8 w-8` mantido para não deslocar os rótulos |
| 4 | Sidebar: realce em varredura horizontal | `app/globals.css` (`.nav-sweep`), `components/shell.tsx` | gradiente 270° (direita → esquerda) num `::before` com opacidade animada |

**Por que o realce vive num `::before`:** `background-image` não é animável em CSS. Posto direto
no `hover:`, o gradiente apareceria de estalo. Animando a opacidade de uma camada, a transição
de 300ms volta a valer.

Ajuste da varredura, tudo em `.nav-sweep::before`:

| Quer | Mexa em |
|---|---|
| morrer mais cedo | `transparent 92%` → `80%` |
| mais área sólida | a parada de `52%` |
| mais lento / mais seco | `300ms` |
| inverter o sentido | `270deg` ↔ `90deg` |


> Regra da fase: mudança visual entra por **token** em `app/globals.css` ou por **componente
> compartilhado** em `components/`. Nunca hardcoded dentro de `app/<rota>/page.tsx`.

## Escopo (10/08/2026)

A **Paggins 2.0** é a **dashboard nova da Paggins 1.0 real** (`www.paggins.com`, acesso no perfil
sip) — todas as funções do painel no tema black. Mapa do painel real capturado por
`scripts/_paggins_absorve.py` → `reports/paggins-v1/`. Diferencial por cima: **Agentes IA**
(inspirados no Hubla — ver `HUBLA.md`).

## Telas (23 rotas — espelham o menu da Paggins 1.0)

| Grupo | Rotas |
|---|---|
| Dashboard | `/` |
| Produtos | `/produtos` (abas Meus/Co-produções/Afiliações) · `/produtos/novo` · `/produtos/order-bump` · `/funil` · `/descontos` |
| Vendas | `/pedidos` · `/assinaturas` · `/clientes` · `/recuperacao` |
| Agentes IA | `/agentes` · `/checkout` (agente checkout) · `/membros` (tutor) · `POST /api/agent` (motor Claude) |
| Indicações | `/indicacao` |
| Financeiro | `/financeiro` · `/financeiro/extrato` · `/financeiro/saque` |
| Relatórios | `/metricas` |
| Extensões | `/extensoes` · `/extensoes/webhooks` · `/extensoes/api-keys` |
| Config | `/configuracoes` |

O motor dos agentes (`/api/agent`) chama a Claude API (`claude-haiku-4-5`) com base de
conhecimento por produto (`lib/agent-kb.ts`). Precisa de `ANTHROPIC_API_KEY` no ambiente
(local: `.env.local`; produção: env do serviço Easypanel). Sem a chave, responde em modo
degradado sem quebrar a UI.

## QA visual

```bash
npm start                                      # sobe em :3210
.\pyrun.ps1 scripts/_paggins_black_shots.py    # → reports/paggins-black/*.png
```
O script falha (exit 1) se alguma rota sair de 200 ou se houver erro de runtime na página.

## Dados de exemplo

`lib/data.ts` — 16 produtos e **524 pedidos** de 3 dias, gerados por um LCG de seed fixa
(determinístico: server e client rendem o mesmo HTML, sem hydration mismatch).

Duas escolhas que fazem a demo parecer real:
- **hora ponderada por curva de tráfego** (madrugada morta, picos às 11h e 20–21h) em vez de
  distribuição uniforme — sem isso o gráfico fica achatado com um pico solitário;
- **produto sorteado por popularidade**, não uniforme — os campeões de venda dominam o mix.

**Nenhum KPI é hardcoded.** Faturamento, ticket médio, taxa de aprovação, top produtos, receita
por método e as pendências são todos derivados de `PEDIDOS`. Mudar o dataset move a dashboard
inteira junto.

## Pendente

- 47 das 52 telas do Figma ainda não portadas (Detalhes do produto, Criar produto digital,
  demais passos do wizard, consultar pedido, Solicitar reembolso, landing page).
- **Sem backend**: dados vêm do módulo, não de API/banco. Filtros, busca, paginação e botões
  são estáticos — a UI existe, a ação não.
- Fonte via Google Fonts CDN; para produção, hospedar local (footprint + offline).
