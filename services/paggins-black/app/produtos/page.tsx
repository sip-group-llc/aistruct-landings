'use client';

import Link from 'next/link';
import { Topbar } from '@/components/shell';
import { Card, CardBody } from '@/components/ui';
import { Tabs } from '@/components/tabs';
import { ProdutosTable } from '@/components/produtos-table';
import { porPapel } from '@/lib/data';
import { brl } from '@/lib/utils';
import { Plus } from 'lucide-react';

const owner = porPapel('owner');
const copro = porPapel('coproducao');
const afil = porPapel('parceiro');

const RESUMO = [
  { label: 'Meus produtos', value: String(owner.length) },
  { label: 'Co-produções', value: String(copro.length) },
  { label: 'Afiliações', value: String(afil.length) },
  {
    label: 'Receita atribuída',
    value: brl(
      owner.reduce((s, p) => s + p.preco * p.vendas, 0) +
        [...copro, ...afil].reduce((s, p) => s + p.preco * p.vendas * ((p.comissao ?? 0) / 100), 0)
    ),
  },
];

export default function ProdutosPage() {
  return (
    <>
      <Topbar crumbs={['Produtos', 'Todos os produtos']} />

      <main className="px-8 pb-14">
        <div className="mb-6 grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {RESUMO.map((r) => (
            <Card key={r.label} className="px-5 py-4">
              <p className="text-xs text-muted-foreground">{r.label}</p>
              <p className="mt-1.5 text-[22px] font-bold tracking-tight">{r.value}</p>
            </Card>
          ))}
        </div>

        <div className="mb-5 flex justify-end">
          <Link
            href="/produtos/novo"
            className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-pill)] bg-primary px-5 text-sm font-medium text-white transition-colors hover:bg-primary-hover"
          >
            <Plus size={16} /> Criar novo produto
          </Link>
        </div>

        <Card>
          <CardBody className="px-2 pt-5">
            <div className="px-2">
              <Tabs
                tabs={[
                  { key: 'owner', label: 'Meus produtos', count: owner.length },
                  { key: 'coproducao', label: 'Minhas co-produções', count: copro.length },
                  { key: 'parceiro', label: 'Minhas parcerias', count: afil.length },
                ]}
              >
                {(active) =>
                  active === 'owner' ? (
                    <ProdutosTable rows={owner} papel="owner" />
                  ) : active === 'coproducao' ? (
                    <ProdutosTable rows={copro} papel="coproducao" />
                  ) : (
                    <ProdutosTable rows={afil} papel="parceiro" />
                  )
                }
              </Tabs>
            </div>
          </CardBody>
        </Card>
      </main>
    </>
  );
}
