import { useQuery } from "@tanstack/react-query";
import type { LatestPrice, PricePointOut, SpreadRow } from "../types/api";
import { apiFetch } from "./client";

export function useLatestPrices(
  setCode: string,
  localId: string,
  variant: string
) {
  return useQuery<LatestPrice[]>({
    queryKey: ["prices", setCode, localId, variant],
    queryFn: () =>
      apiFetch<LatestPrice[]>(
        `/jp/cards/${setCode}/${localId}/prices?variant=${variant}`
      ),
    staleTime: 5 * 60 * 1000,
    enabled: setCode.length > 0 && localId.length > 0,
  });
}

export function usePriceHistory(
  setCode: string,
  localId: string,
  variant: string,
  days = 30,
  condition = "A"
) {
  return useQuery<PricePointOut[]>({
    queryKey: ["history", setCode, localId, variant, days, condition],
    queryFn: () =>
      apiFetch<PricePointOut[]>(
        `/jp/cards/${setCode}/${localId}/history?variant=${variant}&days=${days}&condition=${encodeURIComponent(condition)}&limit=500`
      ),
    staleTime: 0,
    enabled: setCode.length > 0 && localId.length > 0,
  });
}

export function useSpread(setCode: string, localId: string, variant: string) {
  return useQuery<SpreadRow[]>({
    queryKey: ["spread", setCode, localId, variant],
    queryFn: () =>
      apiFetch<SpreadRow[]>(
        `/jp/cards/${setCode}/${localId}/spread?variant=${variant}`
      ),
    staleTime: 5 * 60 * 1000,
    enabled: setCode.length > 0 && localId.length > 0,
  });
}
