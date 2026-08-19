/**
 * Backend client.
 *
 * Every request goes through the same-origin `/api/backend` rewrite, so the
 * browser never learns the API's address and no token is embedded in the
 * bundle. Auth rides on an httpOnly cookie set by the login route.
 */

export interface ClinicMetrics {
  clinic_id: string;
  clinic_name: string;
  consultations: number;
  consultations_offline: number;
  suggestions: number;
  decisions: number;
  acceptance_rate: number | null;
  edit_rate: number | null;
  reject_rate: number | null;
  undecided: number;
  red_flags_fired: number;
  total_cost_usd: number;
  mean_latency_ms: number | null;
  degraded_share: number | null;
  sync_conflicts: number;
}

export interface Clinic {
  id: string;
  name: string;
  region: string;
  type: 'gov' | 'private';
  tier: number;
  offline_mode: boolean;
  default_language: string;
}

export interface AuditVerification {
  ok: boolean;
  entries: number;
  problem: string | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    credentials: 'include',
    cache: 'no-store',
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // A non-JSON error body is not worth failing over.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  metrics: (days = 30) => request<ClinicMetrics[]>(`/admin/metrics?days=${days}`),
  clinics: () => request<Clinic[]>('/admin/clinics'),
  verifyAudit: () => request<AuditVerification>('/admin/audit/verify'),
  auditExportUrl: () => '/api/backend/admin/audit/export',
};

/** Percentages with a stable number of digits, so columns do not jitter. */
export function formatPercent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function formatMs(value: number | null): string {
  return value === null ? '—' : `${Math.round(value)} ms`;
}
