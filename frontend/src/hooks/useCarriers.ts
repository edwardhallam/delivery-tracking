import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { ApiResponse, CarriersResponse } from "@/types/api";

export function useCarriers() {
  return useQuery({
    queryKey: ["carriers"],
    queryFn: async () => {
      const response =
        await api.get<ApiResponse<CarriersResponse>>("/carriers");
      return response.data.data;
    },
    staleTime: 24 * 60 * 60 * 1000, // Cache for 24h — carrier list rarely changes
  });
}
