import { useQuery } from "@tanstack/react-query";
import type { GradedPricePointOut, InternationalPrice, LatestPrice, MarketPriceOut, PricePointOut, SpreadRow } from "../types/api";
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
  condition = "A",
  enabled = true
) {
  return useQuery<PricePointOut[]>({
    queryKey: ["history", setCode, localId, variant, days, condition],
    queryFn: () =>
      apiFetch<PricePointOut[]>(
        `/jp/cards/${setCode}/${localId}/history?variant=${variant}&days=${days}&condition=${encodeURIComponent(condition)}&limit=2000`
      ),
    staleTime: 0,
    enabled: enabled && setCode.length > 0 && localId.length > 0,
  });
}

export function useGradedPriceHistory(
  setCode: string,
  localId: string,
  variant: string,
  days = 365
) {
  return useQuery<GradedPricePointOut[]>({
    queryKey: ["graded-history", setCode, localId, variant, days],
    queryFn: () =>
      apiFetch<GradedPricePointOut[]>(
        `/jp/cards/${setCode}/${localId}/graded-history?variant=${variant}&days=${days}&limit=2000`
      ),
    staleTime: 0,
    enabled: setCode.length > 0 && localId.length > 0,
  });
}

export function useMarketPrice(
  setCode: string,
  localId: string,
  variant: string,
  enabled = true
) {
  return useQuery<MarketPriceOut | null>({
    queryKey: ["market-price", setCode, localId, variant],
    queryFn: () =>
      apiFetch<MarketPriceOut>(
        `/jp/cards/${setCode}/${localId}/market-price?variant=${variant}`
      ).catch((err: Error) => {
        // 404 means no price data yet — treat as null rather than an error
        if (err.message.includes("404")) return null;
        throw err;
      }),
    staleTime: 5 * 60 * 1000,
    enabled: enabled && setCode.length > 0 && localId.length > 0,
  });
}

export function useInternationalPrices(
  setCode: string,
  localId: string,
  variant: string
) {
  return useQuery<InternationalPrice[]>({
    queryKey: ["international-prices", setCode, localId, variant],
    queryFn: () =>
      apiFetch<InternationalPrice[]>(
        `/jp/cards/${setCode}/${localId}/international-prices?variant=${variant}`
      ),
    staleTime: 5 * 60 * 1000,
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
