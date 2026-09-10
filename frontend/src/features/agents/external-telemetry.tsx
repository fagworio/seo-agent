/** Telemetria de chamadas externas do ciclo (persistida em agent_runs.summary.telemetry).
 *
 * Mostra o consumo REAL de um run: chamadas externas, quantas foram EVITADAS por
 * cache (HTTP 304 / datasets GSC-GA4), bytes, retentativas e duração. É o dado
 * que permite calibrar MAX_EXTERNAL_CALLS sem bloquear um ciclo frio.
 */
type Telemetry = {
  calls?: number;
  cache_hits?: number;
  bytes?: number;
  retries?: number;
  duration_s?: number;
  max_calls?: number;
  by_kind?: Record<string, number>;
};

export function ExternalTelemetry({ summary }: { summary: Record<string, unknown> | null }) {
  const t = (summary?.telemetry ?? null) as Telemetry | null;
  if (!t || typeof t !== "object" || (t.calls === undefined && t.by_kind === undefined)) {
    return null;
  }
  const kinds = Object.entries(t.by_kind ?? {});
  return (
    <section
      className="mt-4 rounded-[9px] border border-[var(--border)] bg-[var(--surface-raised)] p-4"
      aria-label="Telemetria externa"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
        Chamadas externas do ciclo
      </h3>
      <div className="mt-3 flex flex-wrap gap-6 text-sm">
        <Metric label="Chamadas" value={String(t.calls ?? 0)} />
        <Metric label="Evitadas (cache)" value={String(t.cache_hits ?? 0)} />
        <Metric label="Bytes" value={formatBytes(t.bytes ?? 0)} />
        <Metric label="Retentativas" value={String(t.retries ?? 0)} />
        <Metric label="Duração" value={`${Math.round(t.duration_s ?? 0)}s`} />
        {t.max_calls ? <Metric label="Teto" value={String(t.max_calls)} /> : null}
      </div>
      {kinds.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
          {kinds.map(([kind, count]) => (
            <li key={kind} className="rounded border border-[var(--border)] px-2 py-0.5 tabular-nums">
              {kind}: {count}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      <div className="text-xs text-[var(--muted)]">{label}</div>
    </div>
  );
}

function formatBytes(n: number): string {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
