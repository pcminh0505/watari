import type { ReactNode } from "react";
import { Header } from "./Header";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-screen flex flex-col relative overflow-x-hidden">
      {/* Background ambient glow */}
      <div className="pointer-events-none absolute -top-40 -left-40 h-[600px] w-[600px] rounded-full bg-primary-100 dark:bg-primary-600/10 blur-[120px] transition-colors duration-500" />
      <div className="pointer-events-none absolute top-40 -right-40 h-[500px] w-[500px] rounded-full bg-accent-100 dark:bg-accent-600/10 blur-[100px] transition-colors duration-500" />
      
      <Header />
      <main className="mx-auto w-full max-w-7xl px-4 py-8 flex-1 relative z-10">{children}</main>
      
      <footer className="mt-16 border-t border-slate-200 dark:border-white/10 py-8 text-center text-sm relative z-10 bg-white/50 dark:bg-slate-950/50 backdrop-blur-sm transition-colors duration-500">
        <p className="mb-2 text-slate-600 dark:text-slate-400">Watari — Premium Japanese Pokémon TCG Market Data</p>
        <p className="text-slate-500 dark:text-slate-500">Sourced from Cardrush &amp; SNKRDUNK</p>
      </footer>
    </div>
  );
}
