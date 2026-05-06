import { NavLink } from "react-router";
import { CurrencyToggle } from "./CurrencyToggle";
import { ThemeToggle } from "./ThemeToggle";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "text-sm font-medium text-primary-600 dark:text-white dark:drop-shadow-[0_0_8px_rgba(14,165,233,0.8)] transition-all"
    : "text-sm font-medium text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white transition-colors";

export function Header() {
  return (
    <header className="glass-header">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <NavLink
          to="/"
          className="flex items-center gap-3 transition-opacity hover:opacity-80"
        >
          <img src="/logo.png" alt="Watari Logo" className="h-8 w-8 object-contain rounded" />
          <span className="text-xl font-bold tracking-tight text-slate-900 dark:text-white text-glow">
            Watari
          </span>
        </NavLink>
        <div className="flex items-center gap-4 sm:gap-6">
          <nav className="flex items-center gap-4 sm:gap-6">
            <NavLink to="/" end className={navLinkClass}>
              Sets
            </NavLink>
            <NavLink to="/cards" className={navLinkClass}>
              Cards
            </NavLink>
          </nav>
          <div className="w-px h-5 bg-slate-200 dark:bg-slate-700"></div>
          <CurrencyToggle />
          <div className="w-px h-5 bg-slate-200 dark:bg-slate-700"></div>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
