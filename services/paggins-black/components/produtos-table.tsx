'use client';

import { Badge, Table, Td, Th } from '@/components/ui';
import { ProductThumb } from '@/components/thumb';
import { brl } from '@/lib/utils';
import type { ProdutoRel } from '@/lib/data';
import { Eye, Pencil, Search } from 'lucide-react';

export function ProdutosTable({ rows, papel }: { rows: ProdutoRel[]; papel: 'owner' | 'coproducao' | 'parceiro' }) {
  const mostraComissao = papel !== 'owner';
  const mostraAutor = papel !== 'owner';

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-elevated">
          <Search size={22} className="text-muted-foreground" />
        </span>
        <p className="text-sm text-muted-foreground">Nenhum resultado encontrado</p>
      </div>
    );
  }

  return (
    <Table>
      <thead>
        <tr>
          <Th className="pl-4">Produto</Th>
          {mostraAutor && <Th>Autor</Th>}
          <Th className="text-right">Preço</Th>
          <Th className="text-right">Vendas</Th>
          {mostraComissao ? (
            <>
              <Th className="text-right">Comissão</Th>
              <Th className="text-right">Sua receita</Th>
            </>
          ) : (
            <Th className="text-right">Receita</Th>
          )}
          <Th>Status</Th>
          <Th>Tipo</Th>
          <Th className="w-20 pr-6 text-right">Ações</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((p) => {
          const receita = p.preco * p.vendas;
          const sua = p.comissao ? receita * (p.comissao / 100) : receita;
          return (
            <tr key={p.id} className="transition-colors hover:bg-elevated/40">
              <Td className="pl-4">
                <div className="flex items-center gap-3">
                  <ProductThumb nome={p.nome} cor={p.cor} tags={p.tags} />
                  <span className="font-medium text-foreground">{p.nome}</span>
                </div>
              </Td>
              {mostraAutor && <Td>{p.autor}</Td>}
              <Td className="text-right text-foreground/90">{brl(p.preco)}</Td>
              <Td className="text-right">{p.vendas.toLocaleString('pt-BR')}</Td>
              {mostraComissao ? (
                <>
                  <Td className="text-right">
                    <Badge tone="primary">{p.comissao}%</Badge>
                  </Td>
                  <Td className="text-right font-medium text-foreground">{brl(sua)}</Td>
                </>
              ) : (
                <Td className="text-right font-medium text-foreground">{brl(receita)}</Td>
              )}
              <Td>
                <Badge tone={p.status === 'Ativo' ? 'success' : 'neutral'}>{p.status}</Badge>
              </Td>
              <Td>{p.tipo}</Td>
              <Td className="pr-6">
                <div className="flex items-center justify-end gap-3">
                  <button className="text-muted-foreground transition-colors hover:text-foreground" aria-label="Ver">
                    <Eye size={17} />
                  </button>
                  <button className="text-primary transition-colors hover:text-primary-hover" aria-label="Editar">
                    <Pencil size={16} />
                  </button>
                </div>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}
