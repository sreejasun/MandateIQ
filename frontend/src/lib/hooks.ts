import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export function useConfig() {
  return useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: 60_000 });
}
