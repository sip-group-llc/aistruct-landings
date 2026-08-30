import { Topbar } from '@/components/shell';
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Table, Td, Th } from '@/components/ui';
import { KpiRow } from '@/components/kpi';
import { PARCEIROS_LISTA } from '@/lib/data';
import { brl } from '@/lib/utils';
import { Plus } from 'lucide-react';

export default function IndicacaoPage() {
  const ativos = PARCEIROS_LISTA.filter((a) => a.status === 'Ativo').length;
  const vendas = PARCEIROS_LISTA.reduce((s, a) => s + a.vendas, 0);
  const comissao = PARCEIROS_LISTA.reduce((s, a) => s + a.comissao, 0);
  return (
    <>
      <Topbar crumbs={['Indicações']} />
      <main className="px-8 pb-14">
        <KpiRow items={[
          { label: 'Parceiros ativos', value: String(ativos) },
          { label: 'Vendas por parceiros', value: vendas.toLocaleString('pt-BR') },
          { label: 'Comissões pagas', value: brl(comissao) },
          { label: 'Comissão média', value: `${Math.round(PARCEIROS_LISTA.reduce((s, a) => s + a.taxa, 0) / PARCEIROS_LISTA.length)}%` },
        ]} />
        <div className="mb-5 flex justify-end"><Button><Plus size={16} /> Convidar parceiro</Button></div>
        <Card>
          <CardHeader><CardTitle>Parceiros</CardTitle></CardHeader>
          <CardBody className="px-2">
            <Table>
              <thead><tr>
                <Th className="pl-4">Parceiro</Th><Th className="text-right">Vendas</Th>
                <Th className="text-right">Comissão %</Th><Th className="text-right">Comissão gerada</Th><Th>Status</Th>
              </tr></thead>
              <tbody>
                {PARCEIROS_LISTA.map((a) => (
                  <tr key={a.id} className="transition-colors hover:bg-elevated/40">
                    <Td className="pl-4">
                      <p className="font-medium text-foreground">{a.nome}</p>
                      <p className="text-xs text-muted-foreground/70">{a.email}</p>
                    </Td>
                    <Td className="text-right">{a.vendas}</Td>
                    <Td className="text-right"><Badge tone="primary">{a.taxa}%</Badge></Td>
                    <Td className="text-right font-medium text-foreground">{brl(a.comissao)}</Td>
                    <Td><Badge tone={a.status === 'Ativo' ? 'success' : 'warning'}>{a.status}</Badge></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </CardBody>
        </Card>
      </main>
    </>
  );
}
