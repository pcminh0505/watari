import { Link } from "react-router";

export function Header() {
  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
        <Link
          to="/"
          className="text-lg font-bold text-gray-900 hover:text-blue-600"
        >
          渡り — Watari
        </Link>
        <nav className="flex gap-4 text-sm text-gray-600">
          <Link to="/" className="hover:text-gray-900">
            Sets
          </Link>
        </nav>
      </div>
    </header>
  );
}
