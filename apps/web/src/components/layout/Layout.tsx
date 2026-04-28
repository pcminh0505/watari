import type { ReactNode } from "react";
import { Header } from "./Header";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      <footer className="mt-16 border-t py-6 text-center text-sm text-gray-400">
        JP Pokemon TCG price data from Cardrush &amp; SNKRDUNK
      </footer>
    </div>
  );
}
