import { useState } from "react";
import type { SetOut } from "../../types/api";
import { SetCard } from "./SetCard";

interface EraSectionProps {
  label: string;
  sets: SetOut[];
}

export function EraSection({ label, sets }: EraSectionProps) {
  const [open, setOpen] = useState(true);

  return (
    <section className="mb-8">
      <button
        onClick={() => setOpen(!open)}
        className="mb-3 flex items-center gap-2 text-lg font-semibold text-gray-800 hover:text-gray-600"
      >
        <span>{open ? "▾" : "▸"}</span>
        <span>{label}</span>
        <span className="text-sm font-normal text-gray-400">
          ({sets.length})
        </span>
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {sets.map((set) => (
            <SetCard key={set.set_code} set={set} />
          ))}
        </div>
      )}
    </section>
  );
}
