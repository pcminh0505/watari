import { type Currency, useCurrency } from "../../contexts/CurrencyContext";

const OPTIONS: { value: Currency; label: string }[] = [
  { value: "JPY", label: "¥" },
  { value: "USD", label: "$" },
  { value: "VND", label: "₫" },
];

export function CurrencyToggle() {
  const { currency, setCurrency } = useCurrency();

  return (
    <div className="flex items-center rounded-full bg-slate-100 dark:bg-slate-800 p-0.5">
      {OPTIONS.map(({ value, label }) => (
        <button
          key={value}
          onClick={() => setCurrency(value)}
          className={`px-2.5 py-1 rounded-full text-sm font-medium transition-colors ${
            currency === value
              ? "bg-white dark:bg-slate-700 text-primary-600 dark:text-primary-400 shadow-sm"
              : "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          }`}
          aria-label={`Switch to ${value}`}
          aria-pressed={currency === value}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
