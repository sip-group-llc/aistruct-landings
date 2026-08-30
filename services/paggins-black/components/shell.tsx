'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as React from 'react';
import {
  LayoutGrid, Briefcase, ShoppingCart, Tag, Wallet, BarChart3, Grid3x3, Settings,
  Search, ChevronDown, ChevronUp, Lightbulb, RefreshCw, Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { StoreSwitcher } from '@/components/store-switcher';

type Item = {
  label: string;
  href?: string;
  icon: React.ElementType;
  children?: { label: string; href: string }[];
};

const NAV: Item[] = [
  { label: 'Dashboard', href: '/', icon: LayoutGrid },
  {
    label: 'Produtos',
    icon: Briefcase,
    children: [
      { label: 'Todos os produtos', href: '/produtos' },
      { label: 'Order Bumps', href: '/produtos/order-bump' },
      { label: 'Funis de Venda', href: '/funil' },
      { label: 'Descontos', href: '/descontos' },
    ],
  },
  {
    label: 'Vendas',
    icon: ShoppingCart,
    children: [
      { label: 'Pedidos', href: '/pedidos' },
      { label: 'Assinaturas', href: '/assinaturas' },
      { label: 'Clientes', href: '/clientes' },
      { label: 'Recuperação de Vendas', href: '/recuperacao' },
    ],
  },
  { label: 'Agentes IA', href: '/agentes', icon: Sparkles },
  { label: 'Indicações', href: '/indicacao', icon: Tag },
  {
    label: 'Financeiro',
    icon: Wallet,
    children: [
      { label: 'Visão Geral', href: '/financeiro' },
      { label: 'Extrato', href: '/financeiro/extrato' },
      { label: 'Configurações de Saque', href: '/financeiro/saque' },
    ],
  },
  { label: 'Relatórios', href: '/metricas', icon: BarChart3 },
  {
    label: 'Extensões',
    icon: Grid3x3,
    children: [
      { label: 'Apps e Integrações', href: '/extensoes' },
      { label: 'Webhooks', href: '/extensoes/webhooks' },
      { label: 'API Keys', href: '/extensoes/api-keys' },
    ],
  },
  { label: 'Configurações', href: '/configuracoes', icon: Settings },
];

function IconBox({ active, children }: { active?: boolean; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'flex h-8 w-8 shrink-0 items-center justify-center transition-colors duration-300 ease-out',
        active ? 'text-primary' : 'text-muted-foreground'
      )}
    >
      {children}
    </span>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = React.useState<string | null>('Produtos');

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-[264px] flex-col border-r border-border bg-sidebar">
      {/* marca — logo oficial Paggins (branca, sobre o sidebar escuro) */}
      <div className="flex h-[72px] items-center px-6">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/paggins-logo.png" alt="Paggins" className="h-9 w-auto object-contain" />
      </div>

      {/* seletor de loja (multi-loja) */}
      <StoreSwitcher />

      {/* busca */}
      <div className="relative mx-4 mt-3">
        <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          placeholder="Pesquisar"
          className="h-10 w-full rounded-[var(--radius-pill)] border border-border bg-input pl-10 pr-4 text-sm outline-none transition-colors focus:border-primary/50"
        />
      </div>

      {/* navegação */}
      <nav className="mt-4 flex-1 space-y-0.5 overflow-y-auto px-3 pb-6">
        {NAV.map((item) => {
          const isOpen = open === item.label;
          const active =
            item.href === pathname ||
            item.children?.some((c) => c.href === pathname) ||
            false;

          return (
            <div key={item.label}>
              {item.children ? (
                <button
                  onClick={() => setOpen(isOpen ? null : item.label)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-[var(--radius-field)] px-2.5 py-2 text-sm',
                    'nav-sweep transition-colors duration-300 ease-out',
                    active ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <IconBox active={active}>
                    <item.icon size={15} />
                  </IconBox>
                  <span className="flex-1 text-left">{item.label}</span>
                  {isOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                </button>
              ) : (
                <Link
                  href={item.href ?? '#'}
                  className={cn(
                    'flex items-center gap-3 rounded-[var(--radius-field)] px-2.5 py-2 text-sm',
                    'nav-sweep transition-colors duration-300 ease-out',
                    active ? 'is-active text-foreground' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  <IconBox active={active}>
                    <item.icon size={15} />
                  </IconBox>
                  <span>{item.label}</span>
                </Link>
              )}

              {item.children && isOpen && item.children.length > 0 && (
                <div className="mt-0.5 space-y-0.5 pb-1">
                  {item.children.map((c) => (
                    <Link
                      key={c.href}
                      href={c.href}
                      className={cn(
                        'block rounded-[var(--radius-field)] py-2 pl-[52px] pr-3 text-sm',
                        'nav-sweep transition-colors duration-300 ease-out',
                        pathname === c.href
                          ? 'is-active text-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {c.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}

export function Topbar({ crumbs }: { crumbs: string[] }) {
  return (
    <header className="flex h-[68px] items-center justify-between px-8">
      <div className="flex items-center gap-2 text-sm">
        {crumbs.map((c, i) => (
          <React.Fragment key={c}>
            {i > 0 && <span className="text-muted-foreground/60">›</span>}
            <span className={i === crumbs.length - 1 ? 'font-medium text-foreground' : 'text-muted-foreground'}>
              {c}
            </span>
          </React.Fragment>
        ))}
      </div>
      <div className="flex items-center gap-4">
        <Link
          href="/reconhecimento"
          className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-pill)] border border-border-strong px-4 text-sm text-foreground transition-colors hover:bg-elevated"
        >
          <Lightbulb size={15} className="text-muted-foreground" />
          Reconhecimento
        </Link>
        <span className="h-px w-px bg-border" />
        <Link
          href="/reconhecimento"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white transition-transform hover:scale-105"
        >
          OP
        </Link>
      </div>
    </header>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <Sidebar />
      <div className="relative ml-[264px] min-h-screen aurora">
        <div className="relative">{children}</div>
      </div>
    </div>
  );
}
