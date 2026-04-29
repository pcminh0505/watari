import { NavLink } from "react-router";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? "text-gray-900 font-medium"
    : "text-gray-500 hover:text-gray-900";

export function Header() {
  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <NavLink
          to="/"
          className="text-lg font-bold text-gray-900 hover:text-blue-600"
        >
          渡り — Watari
        </NavLink>
        <nav className="flex gap-4 text-sm">
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
