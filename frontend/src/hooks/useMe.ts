import { useQuery } from "@tanstack/react-query";
import api from "@/api/client";
import type { ApiResponse, UserInfo } from "@/types/api";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const response = await api.get<ApiResponse<UserInfo>>("/auth/me");
      return response.data.data;
    },
    staleTime: Infinity,
  });
}
