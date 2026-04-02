import { useQuery, keepPreviousData } from "@tanstack/react-query";
import api from "@/api/client";
import type {
  ApiResponse,
  DeliveryListParams,
  PaginatedDeliveries,
} from "@/types/api";

export function useDeliveries(params: DeliveryListParams) {
  return useQuery({
    queryKey: ["deliveries", params],
    queryFn: async () => {
      // Strip undefined params
      const searchParams: Record<string, string> = {};
      if (params.page) searchParams.page = String(params.page);
      if (params.page_size) searchParams.page_size = String(params.page_size);
      if (params.lifecycle_group)
        searchParams.lifecycle_group = params.lifecycle_group;
      if (params.search) searchParams.search = params.search;
      if (params.sort_by) searchParams.sort_by = params.sort_by;
      if (params.sort_dir) searchParams.sort_dir = params.sort_dir;
      if (params.include_terminal !== undefined)
        searchParams.include_terminal = String(params.include_terminal);

      const response = await api.get<ApiResponse<PaginatedDeliveries>>(
        "/deliveries/",
        { params: searchParams },
      );
      return response.data.data;
    },
    placeholderData: keepPreviousData,
    refetchInterval: 5 * 60 * 1000, // 5 minutes
  });
}
