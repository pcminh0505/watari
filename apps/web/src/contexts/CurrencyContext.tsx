import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { formatPrice } from "../lib/formatters";

export type Currency = "JPY" | "USD" | "VND";
export interface ExchangeRates {
  USD: number;
  VND: number;
}

const FALLBACK_RATES: ExchangeRates = { USD: 0.0065, VND: 163 };

function useExchangeRates(): ExchangeRates {
  const { data } = useQuery<ExchangeRates>({
    queryKey: ["exchange-rates"],
    queryFn: async () => {
      const res = await fetch(
        "https://api.frankfurter.app/latest?from=JPY&to=USD,VND"
      );
      if (!res.ok) throw new Error("Failed to fetch rates");
      const json = await res.json();
      return { USD: json.rates.USD, VND: json.rates.VND };
    },
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
  return data ?? FALLBACK_RATES;
}

interface CurrencyContextValue {
  currency: Currency;
  setCurrency: (c: Currency) => void;
  rates: ExchangeRates;
  formatPrice: (jpy: number) => string;
}

const CurrencyContext = createContext<CurrencyContextValue | null>(null);

function readStoredCurrency(): Currency {
  const stored = localStorage.getItem("currency");
  if (stored === "USD" || stored === "VND") return stored;
  return "JPY";
}

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [currency, setCurrencyState] = useState<Currency>(readStoredCurrency);
  const rates = useExchangeRates();

  const setCurrency = (c: Currency) => {
    setCurrencyState(c);
    localStorage.setItem("currency", c);
  };

  return (
    <CurrencyContext.Provider
      value={{
        currency,
        setCurrency,
        rates,
        formatPrice: (jpy) => formatPrice(jpy, currency, rates),
      }}
    >
      {children}
    </CurrencyContext.Provider>
  );
}

export function useCurrency(): CurrencyContextValue {
  const ctx = useContext(CurrencyContext);
  if (!ctx) throw new Error("useCurrency must be used inside CurrencyProvider");
  return ctx;
}
