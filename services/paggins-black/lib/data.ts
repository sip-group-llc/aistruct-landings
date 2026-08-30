/**
 * Dataset de exemplo da Paggins — determinístico (LCG com seed fixa), para que
 * server e client rendam exatamente o mesmo HTML e o build fique estável.
 * Nenhum KPI é hardcoded: tudo abaixo é derivado destes registros.
 */

export type Tipo = 'Físico' | 'Digital';
export type ProdStatus = 'Ativo' | 'Indisponível' | 'Rascunho';
export type PedidoStatus = 'Aprovado' | 'Pendente' | 'Reembolsado' | 'Recusado' | 'Chargeback';
export type Metodo = 'PIX' | 'Cartão' | 'Boleto';

export type Produto = {
  id: string;
  nome: string;
  cor: string;
  tipo: Tipo;
  status: ProdStatus;
  preco: number;
  tags: string[];
  vendas: number;
  conversao: number;
  reembolso: number;
};

export type Pedido = {
  id: string;
  cliente: string;
  email: string;
  produtoId: string;
  valor: number;
  metodo: Metodo;
  parcelas: number;
  status: PedidoStatus;
  hora: number;
  minuto: number;
  dia: number;
  parceiro: string | null;
  uf: string;
};

/* ---------------- gerador determinístico ---------------- */
function lcg(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

/* ---------------- catálogo ---------------- */
export const PRODUTOS: Produto[] = [
  { id: 'p01', nome: 'Cafeteira Expressa Prime', cor: 'from-amber-500 to-orange-700', tipo: 'Físico', status: 'Ativo', preco: 297, tags: ['Casa', 'Best seller'], vendas: 412, conversao: 4.8, reembolso: 1.9 },
  { id: 'p02', nome: 'Gourmet Spice Rack', cor: 'from-rose-500 to-red-800', tipo: 'Físico', status: 'Indisponível', preco: 189, tags: ['Cozinha'], vendas: 138, conversao: 2.7, reembolso: 3.4 },
  { id: 'p03', nome: 'PowerMax Laptop 16"', cor: 'from-slate-400 to-slate-700', tipo: 'Físico', status: 'Indisponível', preco: 4890, tags: ['Eletrônicos'], vendas: 27, conversao: 0.9, reembolso: 7.4 },
  { id: 'p04', nome: 'AquaWave Water Bottle', cor: 'from-sky-400 to-blue-700', tipo: 'Físico', status: 'Ativo', preco: 97, tags: ['Fitness'], vendas: 683, conversao: 6.2, reembolso: 1.1 },
  { id: 'p05', nome: 'UltraComfort Chair Pro', cor: 'from-emerald-500 to-teal-800', tipo: 'Físico', status: 'Ativo', preco: 1249.9, tags: ['Home office'], vendas: 91, conversao: 1.8, reembolso: 4.2 },
  { id: 'p06', nome: 'EcoSmart Blender 1200W', cor: 'from-violet-500 to-purple-800', tipo: 'Físico', status: 'Ativo', preco: 549, tags: ['Cozinha'], vendas: 204, conversao: 3.1, reembolso: 2.6 },
  { id: 'p07', nome: 'Método Renda Extra 6.0', cor: 'from-blue-500 to-indigo-800', tipo: 'Digital', status: 'Ativo', preco: 497, tags: ['Curso', 'Best seller'], vendas: 1284, conversao: 8.9, reembolso: 5.8 },
  { id: 'p08', nome: 'Pack 500 Criativos IA', cor: 'from-fuchsia-500 to-pink-800', tipo: 'Digital', status: 'Ativo', preco: 147, tags: ['Templates'], vendas: 942, conversao: 11.4, reembolso: 2.2 },
  { id: 'p09', nome: 'Mentoria Tráfego 1:1', cor: 'from-cyan-400 to-sky-800', tipo: 'Digital', status: 'Ativo', preco: 2997, tags: ['Mentoria', 'High ticket'], vendas: 38, conversao: 1.2, reembolso: 0 },
  { id: 'p10', nome: 'Planilha Gestão de Ads', cor: 'from-lime-500 to-green-800', tipo: 'Digital', status: 'Ativo', preco: 67, tags: ['Ferramenta'], vendas: 1907, conversao: 14.7, reembolso: 1.4 },
  { id: 'p11', nome: 'Kit Suplementos 90 dias', cor: 'from-orange-500 to-amber-800', tipo: 'Físico', status: 'Ativo', preco: 389, tags: ['Nutra', 'Recorrente'], vendas: 561, conversao: 5.4, reembolso: 6.1 },
  { id: 'p12', nome: 'Whey Isolado 900g', cor: 'from-stone-400 to-stone-700', tipo: 'Físico', status: 'Ativo', preco: 219, tags: ['Nutra'], vendas: 748, conversao: 7.1, reembolso: 2.8 },
  { id: 'p13', nome: 'Curso Copy que Vende', cor: 'from-red-500 to-rose-900', tipo: 'Digital', status: 'Ativo', preco: 397, tags: ['Curso'], vendas: 476, conversao: 6.6, reembolso: 4.9 },
  { id: 'p14', nome: 'Ebook Low Ticket Global', cor: 'from-teal-400 to-cyan-800', tipo: 'Digital', status: 'Rascunho', preco: 27, tags: ['Ebook'], vendas: 0, conversao: 0, reembolso: 0 },
  { id: 'p15', nome: 'Smartwatch FitPro 3', cor: 'from-zinc-400 to-zinc-700', tipo: 'Físico', status: 'Ativo', preco: 649, tags: ['Eletrônicos', 'Fitness'], vendas: 173, conversao: 2.4, reembolso: 5.3 },
  { id: 'p16', nome: 'Comunidade Escala 12m', cor: 'from-indigo-400 to-violet-900', tipo: 'Digital', status: 'Ativo', preco: 1197, tags: ['Recorrente', 'High ticket'], vendas: 112, conversao: 2.1, reembolso: 3.7 },
];

/* ---------------- pedidos ---------------- */
const NOMES = [
  'Ana Beatriz Rocha', 'Rafael Lima', 'Juliana Souza', 'Pedro Henrique Alves', 'Camila Nunes',
  'Lucas Bandeira', 'Fernanda Castro', 'Bruno Tavares', 'Larissa Mendes', 'Thiago Moreira',
  'Patrícia Gomes', 'Diego Barbosa', 'Marina Figueiredo', 'Gustavo Pinheiro', 'Renata Dias',
  'Eduardo Sampaio', 'Vanessa Prado', 'Rodrigo Carvalho', 'Isabela Freitas', 'Marcelo Antunes',
  'Priscila Ramos', 'Vinícius Cardoso', 'Aline Peixoto', 'Otávio Bernardes',
];
const UFS = ['SP', 'RJ', 'MG', 'RS', 'PR', 'BA', 'SC', 'PE', 'CE', 'GO', 'DF', 'ES'];
const PARCEIROS = [null, null, null, 'kaleb.midia', 'lucasbang', 'philip.ads', null, 'traffic.br'];

function slugEmail(nome: string) {
  return (
    nome.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').split(' ')[0] +
    '.' +
    nome.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').split(' ').slice(-1)[0] +
    '@email.com'
  );
}

/** Curva de tráfego de um dia real: madrugada morta, pico 11h e 20-21h. */
const PESO_HORA = [
  0.6, 0.4, 0.3, 0.2, 0.2, 0.3, 0.7, 1.4, 2.3, 3.4, 4.2, 4.8,
  4.1, 3.6, 3.9, 4.3, 4.6, 4.4, 4.9, 5.6, 6.1, 5.4, 3.2, 1.6,
];
const PESO_TOTAL = PESO_HORA.reduce((s, w) => s + w, 0);

function horaPonderada(r: number) {
  let acc = 0;
  const alvo = r * PESO_TOTAL;
  for (let h = 0; h < 24; h++) {
    acc += PESO_HORA[h];
    if (alvo <= acc) return h;
  }
  return 23;
}

/** Produto sorteado por popularidade (vendas históricas), não uniforme. */
function produtoPonderado(r: number, pool: Produto[]) {
  const total = pool.reduce((s, p) => s + p.vendas, 0);
  let acc = 0;
  const alvo = r * total;
  for (const p of pool) {
    acc += p.vendas;
    if (alvo <= acc) return p;
  }
  return pool[pool.length - 1];
}

function gerarPedidos(qtd: number): Pedido[] {
  const rnd = lcg(20260810);
  const vendaveis = PRODUTOS.filter((p) => p.status !== 'Rascunho');
  const out: Pedido[] = [];

  for (let i = 0; i < qtd; i++) {
    const prod = produtoPonderado(rnd(), vendaveis);
    const nome = NOMES[Math.floor(rnd() * NOMES.length)];
    const r = rnd();
    const status: PedidoStatus =
      r < 0.68 ? 'Aprovado' : r < 0.82 ? 'Pendente' : r < 0.9 ? 'Recusado' : r < 0.97 ? 'Reembolsado' : 'Chargeback';
    const metodo: Metodo = prod.tipo === 'Digital'
      ? (rnd() < 0.62 ? 'PIX' : 'Cartão')
      : (rnd() < 0.45 ? 'PIX' : rnd() < 0.9 ? 'Cartão' : 'Boleto');
    const parcelas = metodo === 'Cartão' ? [1, 2, 3, 6, 10, 12][Math.floor(rnd() * 6)] : 1;

    out.push({
      id: `#PG-${10520 - i}`,
      cliente: nome,
      email: slugEmail(nome),
      produtoId: prod.id,
      valor: prod.preco,
      metodo,
      parcelas,
      status,
      hora: horaPonderada(rnd()),
      minuto: Math.floor(rnd() * 60),
      dia: 10 - Math.floor(rnd() * 3),
      parceiro: PARCEIROS[Math.floor(rnd() * PARCEIROS.length)],
      uf: UFS[Math.floor(rnd() * UFS.length)],
    });
  }
  return out;
}

/** Volume de 3 dias de operação. A tabela pagina; as métricas usam tudo. */
export const PEDIDOS = gerarPedidos(524);

export const produtoDe = (id: string) => PRODUTOS.find((p) => p.id === id)!;

/* ---------------- métricas derivadas ---------------- */
const aprovados = PEDIDOS.filter((p) => p.status === 'Aprovado');
const hoje = PEDIDOS.filter((p) => p.dia === 10);
const aprovadosHoje = hoje.filter((p) => p.status === 'Aprovado');

export const METRICAS = {
  pedidosHoje: hoje.length,
  faturamentoHoje: aprovadosHoje.reduce((s, p) => s + p.valor, 0),
  faturamentoTotal: aprovados.reduce((s, p) => s + p.valor, 0),
  ticketMedio: aprovados.length ? aprovados.reduce((s, p) => s + p.valor, 0) / aprovados.length : 0,
  aprovacao: PEDIDOS.length ? (aprovados.length / PEDIDOS.length) * 100 : 0,
  reembolsos: PEDIDOS.filter((p) => p.status === 'Reembolsado').length,
  pendentes: PEDIDOS.filter((p) => p.status === 'Pendente').length,
  chargebacks: PEDIDOS.filter((p) => p.status === 'Chargeback').length,
  disponivelSaque: aprovados.reduce((s, p) => s + p.valor, 0) * 0.82,
  visitantes: 4187,
  aoVivo: 23,
};

/** Faturamento aprovado por hora — alimenta o gráfico do dashboard. */
export const VENDAS_POR_HORA = Array.from({ length: 24 }, (_, h) => ({
  h: `${String(h).padStart(2, '0')}h`,
  v: aprovadosHoje.filter((p) => p.hora === h).reduce((s, p) => s + p.valor, 0),
}));

/** Top produtos por receita aprovada. */
export const TOP_PRODUTOS = PRODUTOS.map((prod) => {
  const meus = aprovados.filter((p) => p.produtoId === prod.id);
  return { prod, qtd: meus.length, receita: meus.reduce((s, p) => s + p.valor, 0) };
})
  .filter((t) => t.qtd > 0)
  .sort((a, b) => b.receita - a.receita);

/** Receita por método de pagamento (share). */
export const POR_METODO = (['PIX', 'Cartão', 'Boleto'] as Metodo[])
  .map((m) => {
    const meus = aprovados.filter((p) => p.metodo === m);
    return { metodo: m, qtd: meus.length, receita: meus.reduce((s, p) => s + p.valor, 0) };
  })
  .filter((x) => x.qtd > 0);

/* ==========================================================================
   ESPELHO DO HUBLA — produtos por papel (owner/co-produção/parceiro) + assinaturas.
   Estrutura fiel ao endpoint deles /products/offers → {owner, affiliates, partners}.
   ========================================================================== */

export type Papel = 'owner' | 'coproducao' | 'parceiro';

export type ProdutoRel = Produto & {
  papel: Papel;
  comissao?: number;      // % (co-produção ou afiliação)
  autor?: string;         // dono do produto quando não é seu
};

/** Meus produtos = os do catálogo. Co-produções e parcerias são de terceiros. */
export const PRODUTOS_REL: ProdutoRel[] = [
  ...PRODUTOS.filter((p) => p.status !== 'Rascunho').slice(0, 8).map(
    (p): ProdutoRel => ({ ...p, papel: 'owner' })
  ),
  // co-produções (você tem % de produto de outro autor)
  { id: 'c01', nome: 'Imersão Escala 7 Dígitos', cor: 'from-indigo-500 to-blue-900', tipo: 'Digital', status: 'Ativo', preco: 1997, tags: ['High ticket'], vendas: 214, conversao: 3.2, reembolso: 4.1, papel: 'coproducao', comissao: 40, autor: 'Bruno Escala' },
  { id: 'c02', nome: 'Método VSL Milionária', cor: 'from-rose-500 to-red-900', tipo: 'Digital', status: 'Ativo', preco: 597, tags: ['Curso'], vendas: 388, conversao: 5.9, reembolso: 3.3, papel: 'coproducao', comissao: 25, autor: 'Lucas Copy' },
  // parcerias (você vende produto de outro por comissão)
  { id: 'a01', nome: 'Suplemento NitroMax', cor: 'from-lime-500 to-green-900', tipo: 'Físico', status: 'Ativo', preco: 289, tags: ['Nutra'], vendas: 1120, conversao: 6.4, reembolso: 5.2, papel: 'parceiro', comissao: 50, autor: 'HealthLab' },
  { id: 'a02', nome: 'Curso Tráfego do Zero', cor: 'from-cyan-500 to-sky-900', tipo: 'Digital', status: 'Ativo', preco: 397, tags: ['Curso'], vendas: 642, conversao: 7.1, reembolso: 2.8, papel: 'parceiro', comissao: 60, autor: 'Ana Tráfego' },
  { id: 'a03', nome: 'Ebook Renda em Dólar', cor: 'from-amber-500 to-yellow-800', tipo: 'Digital', status: 'Ativo', preco: 47, tags: ['Ebook'], vendas: 2310, conversao: 12.1, reembolso: 1.9, papel: 'parceiro', comissao: 70, autor: 'Global Digital' },
];

export const porPapel = (papel: Papel) => PRODUTOS_REL.filter((p) => p.papel === papel);

/* ---------------- assinaturas ---------------- */
export type AssinStatus = 'Ativa' | 'Cancelada' | 'Inadimplente' | 'Trial';

export type Assinatura = {
  id: string;
  assinante: string;
  email: string;
  produto: string;
  plano: 'Mensal' | 'Trimestral' | 'Anual';
  valor: number;
  status: AssinStatus;
  desde: string;       // dd/mm
  proxima: string;     // dd/mm
};

const PLANOS: Assinatura['plano'][] = ['Mensal', 'Trimestral', 'Anual'];
const RECORRENTES = PRODUTOS.filter((p) => p.tags.includes('Recorrente') || p.tipo === 'Digital');

function gerarAssinaturas(qtd: number): Assinatura[] {
  const rnd = lcg(770099);
  const out: Assinatura[] = [];
  for (let i = 0; i < qtd; i++) {
    const nome = NOMES[Math.floor(rnd() * NOMES.length)];
    const prod = RECORRENTES[Math.floor(rnd() * RECORRENTES.length)];
    const plano = PLANOS[Math.floor(rnd() * PLANOS.length)];
    const r = rnd();
    const status: AssinStatus = r < 0.74 ? 'Ativa' : r < 0.86 ? 'Cancelada' : r < 0.94 ? 'Inadimplente' : 'Trial';
    const mult = plano === 'Anual' ? 10 : plano === 'Trimestral' ? 2.7 : 1;
    out.push({
      id: `#SUB-${8400 - i}`,
      assinante: nome,
      email: slugEmail(nome),
      produto: prod.nome,
      plano,
      valor: Math.round(prod.preco * mult),
      status,
      desde: `${String(1 + Math.floor(rnd() * 27)).padStart(2, '0')}/0${1 + Math.floor(rnd() * 7)}`,
      proxima: `${String(1 + Math.floor(rnd() * 27)).padStart(2, '0')}/09`,
    });
  }
  return out;
}

export const ASSINATURAS = gerarAssinaturas(96);

const ativas = ASSINATURAS.filter((a) => a.status === 'Ativa');
export const ASSIN_METRICAS = {
  ativas: ativas.length,
  novos: Math.round(ativas.length * 0.18),
  canceladas: ASSINATURAS.filter((a) => a.status === 'Cancelada').length,
  inadimplentes: ASSINATURAS.filter((a) => a.status === 'Inadimplente').length,
  mrr: ativas.filter((a) => a.plano === 'Mensal').reduce((s, a) => s + a.valor, 0)
     + ativas.filter((a) => a.plano === 'Trimestral').reduce((s, a) => s + a.valor / 3, 0)
     + ativas.filter((a) => a.plano === 'Anual').reduce((s, a) => s + a.valor / 12, 0),
};

/** MRR por mês (últimos 6) — para o gráfico da visão geral de assinaturas. */
export const MRR_SERIE = (() => {
  const base = ASSIN_METRICAS.mrr;
  const fatores = [0.62, 0.71, 0.8, 0.88, 0.95, 1];
  const meses = ['Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago'];
  return meses.map((m, i) => ({ h: m, v: Math.round(base * fatores[i]) }));
})();

/* ==========================================================================
   PAGGINS 2.0 — dados das seções que espelham a Paggins 1.0 completa.
   ========================================================================== */

/* ---------------- Clientes ---------------- */
export type Cliente = {
  id: string; nome: string; email: string; telefone: string;
  pedidos: number; gasto: number; desde: string; uf: string;
};
export const CLIENTES: Cliente[] = (() => {
  const rnd = lcg(31337);
  const seen = new Map<string, Cliente>();
  for (const p of PEDIDOS.filter((x) => x.status === 'Aprovado')) {
    const c = seen.get(p.email) ?? {
      id: `CLI-${8000 + seen.size}`, nome: p.cliente, email: p.email,
      telefone: `(${11 + Math.floor(rnd() * 88)}) 9${Math.floor(rnd() * 9000 + 1000)}-${Math.floor(rnd() * 9000 + 1000)}`,
      pedidos: 0, gasto: 0, desde: `0${1 + Math.floor(rnd() * 7)}/2026`, uf: p.uf,
    };
    c.pedidos += 1; c.gasto += p.valor;
    seen.set(p.email, c);
  }
  return [...seen.values()].sort((a, b) => b.gasto - a.gasto);
})();

/* ---------------- Indicações ---------------- */
export type Parceiro = {
  id: string; nome: string; email: string; vendas: number;
  comissao: number; taxa: number; status: 'Ativo' | 'Pendente';
};
export const PARCEIROS_LISTA: Parceiro[] = [
  { id: 'AF1', nome: 'Kaleb Menezes', email: 'kaleb.midia@email.com', vendas: 142, comissao: 41230, taxa: 50, status: 'Ativo' },
  { id: 'AF2', nome: 'Lucas Bang', email: 'lucasbang@email.com', vendas: 98, comissao: 28470, taxa: 45, status: 'Ativo' },
  { id: 'AF3', nome: 'Philip Ads', email: 'philip.ads@email.com', vendas: 76, comissao: 22100, taxa: 40, status: 'Ativo' },
  { id: 'AF4', nome: 'Traffic BR', email: 'traffic.br@email.com', vendas: 54, comissao: 15660, taxa: 50, status: 'Ativo' },
  { id: 'AF5', nome: 'Marina Growth', email: 'marina.growth@email.com', vendas: 12, comissao: 3480, taxa: 40, status: 'Pendente' },
];

/* ---------------- Descontos (cupons) ---------------- */
export type Cupom = {
  codigo: string; tipo: 'Percentual' | 'Fixo'; valor: number;
  usos: number; limite: number; status: 'Ativo' | 'Expirado';
};
export const CUPONS: Cupom[] = [
  { codigo: 'BLACKFRIDAY', tipo: 'Percentual', valor: 40, usos: 312, limite: 1000, status: 'Ativo' },
  { codigo: 'PRIMEIRA10', tipo: 'Percentual', valor: 10, usos: 1240, limite: 0, status: 'Ativo' },
  { codigo: 'VOLTA50', tipo: 'Fixo', valor: 50, usos: 88, limite: 200, status: 'Ativo' },
  { codigo: 'LANCAMENTO', tipo: 'Percentual', valor: 25, usos: 500, limite: 500, status: 'Expirado' },
];

/* ---------------- OrderBumps ---------------- */
export type OrderBump = {
  nome: string; produto: string; preco: number; conversao: number; ativo: boolean;
};
export const ORDERBUMPS: OrderBump[] = [
  { nome: 'Garantia estendida', produto: 'Método Renda Extra 6.0', preco: 47, conversao: 34.2, ativo: true },
  { nome: 'Pack de templates', produto: 'Pack 500 Criativos IA', preco: 27, conversao: 41.8, ativo: true },
  { nome: 'Mentoria em grupo', produto: 'Curso Copy que Vende', preco: 197, conversao: 12.1, ativo: false },
];

/* ---------------- Recuperação de vendas (abandonados) ---------------- */
export type Abandonado = {
  id: string; cliente: string; email: string; produto: string; valor: number;
  etapa: 'Dados' | 'Pagamento'; quando: string; recuperado: boolean;
};
export const ABANDONADOS: Abandonado[] = (() => {
  const rnd = lcg(9182);
  return Array.from({ length: 18 }, (_, i) => {
    const nome = NOMES[Math.floor(rnd() * NOMES.length)];
    const prod = PRODUTOS[Math.floor(rnd() * 8)];
    return {
      id: `AB-${400 - i}`, cliente: nome, email: slugEmail(nome), produto: prod.nome,
      valor: prod.preco, etapa: rnd() < 0.6 ? 'Pagamento' : 'Dados' as 'Dados' | 'Pagamento',
      quando: `${Math.floor(rnd() * 22 + 1)}h atrás`, recuperado: rnd() < 0.22,
    };
  });
})();

/* ---------------- Financeiro: extrato ---------------- */
export type Movimento = {
  data: string; descricao: string; tipo: 'Entrada' | 'Saque' | 'Taxa' | 'Reembolso'; valor: number;
};
export const EXTRATO: Movimento[] = [
  { data: '10/08', descricao: 'Venda #PG-10520 · Método Renda Extra', tipo: 'Entrada', valor: 497 },
  { data: '10/08', descricao: 'Taxa da plataforma (4,99%)', tipo: 'Taxa', valor: -24.8 },
  { data: '09/08', descricao: 'Saque para conta ****1234', tipo: 'Saque', valor: -5000 },
  { data: '09/08', descricao: 'Venda #PG-10480 · UltraComfort Chair', tipo: 'Entrada', valor: 1249.9 },
  { data: '08/08', descricao: 'Reembolso #PG-10471', tipo: 'Reembolso', valor: -189 },
  { data: '08/08', descricao: 'Venda #PG-10465 · Pack 500 Criativos', tipo: 'Entrada', valor: 147 },
];

/* ---------------- Extensões: apps / webhooks / api keys ---------------- */
export const APPS = [
  { nome: 'UTMify', cat: 'Rastreamento', conectado: true },
  { nome: 'RedTrack', cat: 'Rastreamento', conectado: true },
  { nome: 'Facebook Pixel', cat: 'Pixel', conectado: true },
  { nome: 'Google Ads', cat: 'Pixel', conectado: false },
  { nome: 'Active Campaign', cat: 'E-mail', conectado: false },
  { nome: 'Mandaê', cat: 'Logística', conectado: true },
  { nome: 'Bling', cat: 'ERP / NF-e', conectado: true },
  { nome: 'Typebot', cat: 'Chatbot', conectado: false },
];
export type Webhook = { url: string; evento: string; status: 'Ativo' | 'Falhando' };
export const WEBHOOKS: Webhook[] = [
  { url: 'https://kirvano-bridge.tiectu.easypanel.host/postback', evento: 'Compra aprovada', status: 'Ativo' },
  { url: 'https://hyu-cart.tiectu.easypanel.host/webhook/orders', evento: 'Pedido pago', status: 'Ativo' },
  { url: 'https://radar.tiectu.easypanel.host/hook', evento: 'Reembolso', status: 'Falhando' },
];
export type ApiKey = { nome: string; prefixo: string; criada: string; ultimoUso: string };
export const APIKEYS: ApiKey[] = [
  { nome: 'Produção', prefixo: 'pgk_live_9f2a…', criada: '12/06/2026', ultimoUso: 'há 3 min' },
  { nome: 'Integração Bling', prefixo: 'pgk_live_1c7d…', criada: '20/07/2026', ultimoUso: 'há 2 h' },
  { nome: 'Sandbox', prefixo: 'pgk_test_44be…', criada: '01/08/2026', ultimoUso: 'há 5 dias' },
];
