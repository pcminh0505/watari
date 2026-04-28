import { useQuery } from "@tanstack/react-query";
import type { SetOut } from "../types/api";
import { apiFetch } from "./client";

export function useAllSets() {
  return useQuery<SetOut[]>({
    queryKey: ["sets"],
    queryFn: () => apiFetch<SetOut[]>("/jp/sets?limit=500"),
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
