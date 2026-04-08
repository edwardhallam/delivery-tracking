// ── API envelope types ──────────────────────────────────────────────────────

export interface ApiResponse<T> {
  data: T;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

// ── Auth ────────────────────────────────────────────────────────────────────

export interface AuthTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface UserInfo {
  username: string;
  is_demo: boolean;
}

// ── Deliveries ──────────────────────────────────────────────────────────────

export type LifecycleGroup = "ACTIVE" | "ATTENTION" | "TERMINAL";

export type SemanticStatus =
  | "INFO_RECEIVED"
  | "IN_TRANSIT"
  | "OUT_FOR_DELIVERY"
  | "AWAITING_PICKUP"
  | "DELIVERED"
  | "DELIVERY_FAILED"
  | "EXCEPTION"
  | "NOT_FOUND"
  | "STALLED"
  | "UNKNOWN";

export interface DeliverySummary {
  id: string;
  tracking_number: string;
  carrier_code: string;
  description: string;
  semantic_status: SemanticStatus;
  lifecycle_group: LifecycleGroup;
  parcel_status_code: string;
  date_expected_raw: string | null;
  date_expected_end_raw: string | null;
  timestamp_expected: string | null;
  timestamp_expected_end: string | null;
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
}

export interface DeliveryEvent {
  id: string;
  event_description: string;
  event_date_raw: string;
  location: string | null;
  additional_info: string | null;
  sequence_number: number;
  recorded_at: string;
}

export interface StatusHistoryEntry {
  id: string;
  previous_status_code: string | null;
  previous_semantic_status: SemanticStatus | null;
  new_status_code: string;
  new_semantic_status: SemanticStatus;
  detected_at: string;
}

export interface DeliveryDetail extends DeliverySummary {
  extra_information: string | null;
  events: DeliveryEvent[];
  status_history: StatusHistoryEntry[];
}

export interface PaginatedDeliveries {
  items: DeliverySummary[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type SortField =
  | "timestamp_expected"
  | "updated_at"
  | "carrier_code"
  | "first_seen_at";

export type SortDir = "asc" | "desc";

export interface DeliveryListParams {
  page?: number;
  page_size?: number;
  lifecycle_group?: LifecycleGroup;
  search?: string;
  sort_by?: SortField;
  sort_dir?: SortDir;
  include_terminal?: boolean;
}

// ── System ──────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  database: {
    status: string;
    latency_ms: number;
  };
  polling: {
    scheduler_running: boolean;
    last_poll_at: string | null;
    last_poll_outcome: string | null;
    last_successful_poll_at: string | null;
    consecutive_errors: number;
    next_poll_at: string | null;
  };
  version: string;
}

export interface Carrier {
  code: string;
  name: string;
}

export interface CarriersResponse {
  carriers: Carrier[];
  cached_at: string | null;
  cache_status: string;
}
