import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { ApiResponse, HealthResponse } from "@/types/api";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const response =
        await api.get<ApiResponse<HealthResponse>>("/health");
      return response.data.data;
    },
    refetchInterval: 60 * 1000, // 60 seconds
  });
}
