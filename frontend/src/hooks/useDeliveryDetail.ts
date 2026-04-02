import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { ApiResponse, DeliveryDetail } from "@/types/api";

export function useDeliveryDetail(id: string | undefined) {
  return useQuery({
    queryKey: ["delivery", id],
    queryFn: async () => {
      const response = await api.get<ApiResponse<DeliveryDetail>>(
        `/deliveries/${id}`,
      );
      return response.data.data;
    },
    enabled: !!id,
    refetchInterval: (query) => {
      // 30 min for terminal deliveries, 5 min for active
      const data = query.state.data;
      if (data?.lifecycle_group === "TERMINAL") return 30 * 60 * 1000;
      return 5 * 60 * 1000;
    },
  });
}
