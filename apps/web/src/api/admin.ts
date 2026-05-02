import { useQuery } from "@tanstack/react-query";
import type { ScrapeHealthRow } from "../types/api";
import { apiFetch } from "./client";

export function useScrapeHealth() {
  return useQuery<ScrapeHealthRow[]>({
    queryKey: ["admin", "scrape-health"],
    queryFn: () => apiFetch<ScrapeHealthRow[]>("/admin/scrape-health"),
    staleTime: 60 * 1000,
  });
}
