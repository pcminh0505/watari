import { NavLink } from "react-router";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "border-b-2 border-blue-600 pb-0.5 text-sm font-semibold text-gray-900"
    : "border-b-2 border-transparent pb-0.5 text-sm text-gray-500 hover:text-gray-800 transition-colors";

export function Header() {
  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
        <NavLink
          to="/"
          className="text-lg font-bold tracking-tight text-gray-900 hover:text-blue-600 transition-colors"
        >
          渡り — Watari
        </NavLink>
        <nav className="flex gap-5">
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
