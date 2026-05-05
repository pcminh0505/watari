import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ArtworkDetail, ArtworkSearchResult } from "../types/api";
import { apiFetch, apiFetchPaged } from "./client";

interface CardsParams {
  rarity?: string;
  variant?: string;
  tracked_only?: boolean;
  page?: number;
  limit?: number;
}

export function useCards(setCode: string, params: CardsParams = {}) {
  const { rarity, variant, tracked_only = false, page = 0, limit = 100 } = params;
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(page * limit),
    tracked_only: String(tracked_only),
  });
  if (rarity) qs.set("rarity", rarity);
  if (variant) qs.set("variant", variant);

  return useQuery<{ data: ArtworkDetail[]; total: number }>({
    queryKey: ["cards", setCode, params],
    queryFn: () =>
      apiFetchPaged<ArtworkDetail>(`/jp/sets/${setCode}/cards?${qs}`),
    staleTime: 60 * 60 * 1000,
    placeholderData: keepPreviousData,
    enabled: setCode.length > 0,
  });
}

export function useCard(setCode: string, localId: string) {
  return useQuery<ArtworkDetail>({
    queryKey: ["card", setCode, localId],
    queryFn: () => apiFetch<ArtworkDetail>(`/jp/cards/${setCode}/${localId}`),
    staleTime: 60 * 60 * 1000,
    enabled: setCode.length > 0 && localId.length > 0,
  });
}

interface CardSearchParams {
  q?: string;
  set_code?: string;
  rarity?: string;
  illustrator?: string;
  page?: number;
  limit?: number;
}

export function useCardSearch(params: CardSearchParams) {
  const { q = "", set_code = "", rarity = "", page = 0, limit = 60 } = params;
  const qs = new URLSearchParams({
    limit: String(limit),
    offset: String(page * limit),
  });
  if (q.trim()) qs.set("q", q.trim());
  if (set_code) qs.set("set_code", set_code);
  if (rarity) qs.set("rarity", rarity);
  if (params.illustrator) qs.set("illustrator", params.illustrator);

  return useQuery<{ data: ArtworkSearchResult[]; total: number }>({
    queryKey: ["cards-search", params],
    queryFn: () => apiFetchPaged<ArtworkSearchResult>(`/jp/cards/search?${qs}`),
    placeholderData: keepPreviousData,
    staleTime: 60 * 1000,
    enabled: true,
  });
}
