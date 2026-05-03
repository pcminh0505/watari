import { NavLink } from "react-router";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "text-sm font-medium text-white drop-shadow-[0_0_8px_rgba(168,85,247,0.8)] transition-all"
    : "text-sm font-medium text-neutral-400 hover:text-white transition-colors";

export function Header() {
  return (
    <header className="glass-header">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
        <NavLink
          to="/"
          className="flex items-center gap-3 transition-opacity hover:opacity-80"
        >
          <img src="/logo.png" alt="Watari Logo" className="h-8 w-8 object-contain rounded" />
          <span className="text-xl font-bold tracking-tight text-white text-glow">
            Watari
          </span>
        </NavLink>
        <nav className="flex items-center gap-6">
          <NavLink to="/" end className={navLinkClass}>
            Sets
          </NavLink>
          <NavLink to="/cards" className={navLinkClass}>
            Cards
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
