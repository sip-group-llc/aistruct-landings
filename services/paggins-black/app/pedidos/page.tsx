import { Topbar } from '@/components/shell';
import { Badge, Card, CardBody, CardHeader, CardTitle, Select, Table, Td, Th } from '@/components/ui';
import { ProductThumb } from '@/components/thumb';
import { METRICAS, PEDIDOS, produtoDe, type PedidoStatus } from '@/lib/data';
import { brl } from '@/lib/utils';
import { Download, Eye, Search } from 'lucide-react';

const tone = (s: PedidoStatus) =>
  s === 'Aprovado' ? 'success'
  : s === 'Pendente' ? 'warning'
  : s === 'Recusado' ? 'danger'
  : s === 'Chargeback' ? 'danger'
  : 'neutral';

/** A tabela mostra a primeira página; os KPIs somam os 524 registros. */
const POR_PAGINA = 40;
const PAGINA = PEDIDOS.slice(0, POR_PAGINA);

const RESUMO = [
  { label: 'Pedidos (72h)', value: PEDIDOS.length.toLocaleString('pt-BR') },
  { label: 'Faturamento aprovado', value: brl(METRICAS.faturamentoTotal) },
  { label: 'Ticket médio', value: brl(METRICAS.ticketMedio) },
  { label: 'Taxa de aprovação', value: `${METRICAS.aprovacao.toFixed(1)}%` },
];

export default function PedidosPage() {
  return (
    <>
      <Topbar crumbs={['Vendas', 'Todos os pedidos']} />

      <main className="px-8 pb-14">
        <div className="mb-6 grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {RESUMO.map((r) => (
            <Card key={r.label} className="px-5 py-4">
              <p className="text-xs text-muted-foreground">{r.label}</p>
              <p className="mt-1.5 text-[22px] font-bold tracking-tight">{r.value}</p>
            </Card>
          ))}
        </div>

        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-4 pb-5">
            <CardTitle>Todos os pedidos</CardTitle>
            <div className="flex flex-wrap items-center gap-3">
              <Select defaultValue="todos" className="h-10 w-[150px]">
                <option value="todos">Todos os status</option>
                <option>Aprovado</option>
                <option>Pendente</option>
                <option>Recusado</option>
                <option>Reembolsado</option>
                <option>Chargeback</option>
              </Select>
              <Select defaultValue="todos" className="h-10 w-[140px]">
                <option value="todos">Todo método</option>
                <option>PIX</option>
                <option>Cartão</option>
                <option>Boleto</option>
              </Select>
              <div className="relative w-[210px]">
                <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input
                  placeholder="Pedido, cliente ou e-mail"
                  className="h-10 w-full rounded-[var(--radius-pill)] border border-border bg-input pl-10 pr-4 text-sm outline-none transition-colors focus:border-primary/50"
                />
              </div>
              <button className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-pill)] border border-border-strong px-4 text-sm transition-colors hover:bg-elevated">
                <Download size={15} /> Exportar
              </button>
            </div>
          </CardHeader>

          <CardBody className="px-2">
            <Table>
              <thead>
                <tr>
                  <Th className="pl-4">Pedido</Th>
                  <Th>Cliente</Th>
                  <Th>Produto</Th>
                  <Th>Pagamento</Th>
                  <Th className="text-right">Valor</Th>
                  <Th>Status</Th>
                  <Th>Parceiro</Th>
                  <Th>UF</Th>
                  <Th>Data</Th>
                  <Th className="w-14 pr-6 text-right">Ver</Th>
                </tr>
              </thead>
              <tbody>
                {PAGINA.map((p) => {
                  const prod = produtoDe(p.produtoId);
                  return (
                    <tr key={p.id} className="transition-colors hover:bg-elevated/40">
                      <Td className="pl-4 font-medium text-foreground">{p.id}</Td>
                      <Td>
                        <p className="text-foreground/90">{p.cliente}</p>
                        <p className="text-xs text-muted-foreground/70">{p.email}</p>
                      </Td>
                      <Td>
                        <div className="flex items-center gap-2.5">
                          <ProductThumb nome={prod.nome} cor={prod.cor} tags={prod.tags} size={24} />
                          <span className="max-w-[190px] truncate">{prod.nome}</span>
                        </div>
                      </Td>
                      <Td>
                        {p.metodo}
                        {p.parcelas > 1 && <span className="text-muted-foreground/70"> · {p.parcelas}x</span>}
                      </Td>
                      <Td className="text-right font-medium text-foreground">{brl(p.valor)}</Td>
                      <Td><Badge tone={tone(p.status)}>{p.status}</Badge></Td>
                      <Td>
                        {p.parceiro
                          ? <span className="text-primary">{p.parceiro}</span>
                          : <span className="text-muted-foreground/60">direto</span>}
                      </Td>
                      <Td>{p.uf}</Td>
                      <Td className="whitespace-nowrap">
                        {String(p.dia).padStart(2, '0')}/08 ·{' '}
                        {String(p.hora).padStart(2, '0')}:{String(p.minuto).padStart(2, '0')}
                      </Td>
                      <Td className="pr-6 text-right">
                        <button className="text-muted-foreground transition-colors hover:text-foreground" aria-label="Ver pedido">
                          <Eye size={17} />
                        </button>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>

            <div className="flex items-center justify-between gap-4 pt-6 pb-2">
              <span className="pl-4 text-xs text-muted-foreground">
                Exibindo {PAGINA.length} de {PEDIDOS.length.toLocaleString('pt-BR')} pedidos das últimas 72h
              </span>
              <div className="flex items-center gap-2 pr-4 text-sm">
                <button className="px-2 text-muted-foreground hover:text-foreground">‹</button>
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    className={
                      n === 1
                        ? 'h-7 w-7 rounded-md bg-primary text-white'
                        : 'h-7 w-7 rounded-md bg-elevated text-muted-foreground hover:text-foreground'
                    }
                  >
                    {n}
                  </button>
                ))}
                <button className="px-2 text-muted-foreground hover:text-foreground">›</button>
              </div>
            </div>
          </CardBody>
        </Card>
      </main>
    </>
  );
}
