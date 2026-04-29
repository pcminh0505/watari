import { useQuery } from "@tanstack/react-query";
import type { SetOut } from "../types/api";
import { apiFetch } from "./client";

interface SetsParams {
  era?: string;
  sort?: "release_date" | "value" | "set_code";
  order?: "asc" | "desc";
}

export function useAllSets(params: SetsParams = {}) {
  const qs = new URLSearchParams({ limit: "500" });
  if (params.era) qs.set("era", params.era);
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);

  return useQuery<SetOut[]>({
    queryKey: ["sets", params],
    queryFn: () => apiFetch<SetOut[]>(`/jp/sets?${qs.toString()}`),
    staleTime: 60 * 60 * 1000,
  });
}

export function useSet(setCode: string) {
  return useQuery<SetOut>({
    queryKey: ["sets", setCode],
    queryFn: () => apiFetch<SetOut>(`/jp/sets/${setCode}`),
    staleTime: 60 * 60 * 1000,
    enabled: setCode.length > 0,
  });
}
