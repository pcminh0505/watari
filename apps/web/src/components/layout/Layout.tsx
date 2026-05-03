import type { ReactNode } from "react";
import { Header } from "./Header";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-50 flex flex-col relative overflow-hidden">
      {/* Background ambient glow */}
      <div className="pointer-events-none absolute -top-40 -left-40 h-[600px] w-[600px] rounded-full bg-primary-600/10 blur-[120px]" />
      <div className="pointer-events-none absolute top-40 -right-40 h-[500px] w-[500px] rounded-full bg-accent-600/10 blur-[100px]" />
      
      <Header />
      <main className="mx-auto w-full max-w-7xl px-4 py-8 flex-1 relative z-10">{children}</main>
      
      <footer className="mt-16 border-t border-white/10 py-8 text-center text-sm text-neutral-500 relative z-10 bg-neutral-950/50">
        <p className="mb-2 text-neutral-400">Watari — Premium Japanese Pokémon TCG Market Data</p>
        <p className="text-neutral-600">Sourced from Cardrush &amp; SNKRDUNK</p>
      </footer>
    </div>
  );
}
