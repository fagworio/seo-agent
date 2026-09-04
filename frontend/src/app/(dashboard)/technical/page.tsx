"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, Correction, TechnicalFinding } from "@/lib/api";
import { fmt, fmtNum, num, pct } from "@/lib/format";
import { Badge } from "@/design-system/badge";
import { Button } from "@/design-system/button";
import { Card } from "@/design-system/card";
import { Input } from "@/design-system/input";
import { Drawer as AccessibleDrawer } from "@/design-system/drawer";
import { Pagination, pageSlice } from "@/components/pagination";
import { DelegateCampaignModal } from "@/components/delegate-campaign-modal";

type SortKey = "potential" | "impressions" | "severity" | "recent";
const PAGE_SIZE = 20;

const TONES: Record<string, "danger" | "warning" | "success" | "neutral" | "info"> = {
  critical: "danger", high: "danger", medium: "warning", low: "neutral", info: "info",
};

export default function TechnicalPage() {
  const [sort, setSort] = useState<SortKey>("potential");
  const [search, setSearch] = useState("");
  const [ruleFilter, setRuleFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [googleFilter, setGoogleFilter] = useState("");
  const [selected, setSelected] = useState<TechnicalFinding | null>(null);
  const [view, setView] = useState<"problems" | "corrections">("problems");
  const [selCorrection, setSelCorrection] = useState<Correction | null>(null);
  const [findingPage, setFindingPage] = useState(1);
  const [bulk, setBulk] = useState<Set<string>>(new Set());
  const [delegateOpen, setDelegateOpen] = useState(false);
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<{ csrf_token: string; user: { permissions: string[] } }>("/auth/me") });

  const { data, error, isLoading } = useQuery({
    queryKey: ["findings", sort],
    queryFn: () => api.get<{ findings: TechnicalFinding[] }>(`/findings?limit=200&sort=${sort}`),
  });
  const corrections = useQuery({
    queryKey: ["corrections"],
    queryFn: () => api.get<{ corrections: Correction[] }>("/actions?limit=200"),
  });

  const all = useMemo(() => data?.findings ?? [], [data?.findings]);
  const approveFix = useMutation({
    mutationFn: (fingerprint: string) => api.post<{ ok: boolean; approved: boolean; dry_run: boolean }>(`/actions/${fingerprint}/execute`, {}, me.data?.csrf_token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["corrections"] }),
  });
  const rollbackFix = useMutation({
    mutationFn: (fingerprint: string) => api.post<{ ok: boolean; reversible: boolean }>(`/actions/${fingerprint}/rollback`, {}, me.data?.csrf_token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["corrections"] }),
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter((f) => {
      if (ruleFilter && f.rule_id !== ruleFilter) return false;
      if (severityFilter && f.severity !== severityFilter) return false;
      if (googleFilter && f.google.data_status !== googleFilter) return false;
      if (q) {
        const hay = `${f.title} ${f.page.public_url} ${f.rule.label}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [all, search, ruleFilter, severityFilter, googleFilter]);

  const summary = useMemo(() => {
    const high = all.filter((f) => (f.potential.realistic ?? 0) >= 50).length;
    const noGoogle = all.filter((f) => f.google.data_status === "missing").length;
    return { problems: all.length, highImpact: high, noGoogle, corrections: corrections.data?.corrections.length ?? 0 };
  }, [all, corrections.data]);

  const ruleOptions = useMemo(() => Array.from(new Set(all.map((f) => f.rule_id))).sort(), [all]);
  const visibleFindings = pageSlice(filtered, findingPage, PAGE_SIZE);

  if (isLoading || corrections.isLoading) return <div className="text-sm text-[var(--muted)]">Carregando…</div>;
  if (error || corrections.error) return <div className="text-sm text-[var(--danger)]">{((error ?? corrections.error) as ApiError).message}</div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-xl font-semibold">SEO técnico</h1><p className="mt-1 max-w-2xl text-sm text-[var(--muted)]">Diagnóstico, evidência e correções verificáveis — sem confundir finding com ação.</p></div>
      <div className="flex gap-1 rounded-md border border-[var(--border)] p-1" role="tablist" aria-label="Visão de SEO técnico">
        <Tab active={view === "problems"} onClick={() => setView("problems")}>Problemas ({summary.problems})</Tab>
        <Tab active={view === "corrections"} onClick={() => setView("corrections")}>Correções disponíveis ({summary.corrections})</Tab>
      </div></div>
      {/* Resumo (≤4 indicadores) */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Kpi label="Problemas" value={summary.problems} />
        <Kpi label="Alto impacto" value={summary.highImpact} tone="success" />
        <Kpi label="Sem dados Google" value={summary.noGoogle} tone="warning" />
        <Kpi label="Correções disponíveis" value={summary.corrections} />
      </div>

      {view === "problems" && (
        <>
      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-64"><Input placeholder="Buscar post ou URL…" value={search} onChange={(e) => { setSearch(e.target.value); setFindingPage(1); }} /></div>
        <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={ruleFilter} onChange={(e) => { setRuleFilter(e.target.value); setFindingPage(1); }}>
          <option value="">Problema · Todos</option>
          {ruleOptions.map((r) => <option key={r} value={r}>{all.find((finding) => finding.rule_id === r)?.rule.label ?? "Problema técnico"}</option>)}
        </select>
        <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={severityFilter} onChange={(e) => { setSeverityFilter(e.target.value); setFindingPage(1); }}>
          <option value="">Severidade · Todas</option>
          {["critical", "high", "medium", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={googleFilter} onChange={(e) => { setGoogleFilter(e.target.value); setFindingPage(1); }}>
          <option value="">Dados Google · Todos</option>
          <option value="available">Disponíveis</option>
          <option value="missing">Sem dados</option>
        </select>
        <select className="h-9 rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm" value={sort} onChange={(e) => { setSort(e.target.value as SortKey); setFindingPage(1); }}>
          <option value="potential">Ordenar · Maior potencial</option>
          <option value="impressions">Mais impressões</option>
          <option value="severity">Severidade</option>
          <option value="recent">Mais recente</option>
        </select>
      </div>

      {/* Tabela */}
      <div className="overflow-x-auto rounded-[9px] border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
            <tr>
              <th className="px-3 py-2">Problema</th>
              <th className="px-3 py-2">Post</th>
              <th className="px-3 py-2">Publicação</th>
              <th className="px-3 py-2">Google</th>
              <th className="px-3 py-2">Potencial</th>
              <th className="px-3 py-2">Sev.</th>
              <th className="px-3 py-2"><span className="sr-only">Ações</span></th>
            </tr>
          </thead>
          <tbody>
            {visibleFindings.map((f) => (
              <tr key={f.id} className="border-t border-[var(--border)] hover:bg-[var(--surface-raised)]">
                <td className="max-w-[15rem] px-3 py-2">
                  <div className="truncate font-medium">{f.rule.label}</div>
                  <div className="truncate text-[11px] text-[var(--muted)]">{layerLabel(f.rule.layer)}</div>
                </td>
                <td className="max-w-[16rem] truncate px-3 py-2">{f.title || "Página sem título identificado"}</td>
                <td className="px-3 py-2">
                  <div className="max-w-[12rem]">
                    <div className="flex items-center gap-1 text-xs">
                      <Badge tone="neutral">Headless</Badge>
                      <a href={f.page.public_url} target="_blank" rel="noopener noreferrer" className="truncate text-[var(--primary)]">Abrir ↗</a>
                    </div>
                    <div className="mt-0.5 flex items-center gap-1 text-xs">
                      <Badge tone="info">WordPress</Badge>
                      <a href={f.page.wordpress_url} target="_blank" rel="noopener noreferrer" className="truncate text-[var(--primary)]">Abrir ↗</a>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2 text-xs">
                  {f.google.data_status === "available" ? (
                    <div>
                      <div className="tabular-nums">{fmt(f.google.impressions)} impressões</div>
                      <div className="tabular-nums">{pct(f.google.ctr)} CTR · Pos. {num(f.google.position)}</div>
                      <div className="text-[11px] text-[var(--muted)]">Google · último período</div>
                    </div>
                  ) : (
                    <span className="text-[var(--muted)]">Sem dados do Search Console</span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs">
                  {f.potential.realistic != null ? (
                    <div>
                      <div className="tabular-nums font-medium">+{fmtNum(f.potential.realistic)} cliques</div>
                      <div className="text-[11px] text-[var(--muted)]">Cenário realista</div>
                    </div>
                  ) : (
                    <span className="text-[var(--muted)]">Potencial ainda não calculado</span>
                  )}
                </td>
                <td className="px-3 py-2"><Badge tone={TONES[f.severity] ?? "neutral"}>{f.severity}</Badge></td>
                <td className="px-3 py-2 text-right"><Button size="sm" variant="secondary" onClick={() => setSelected(f)}>Ver detalhes</Button></td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-[var(--muted)]">Nenhum finding para os filtros.</td></tr>
            )}
          </tbody>
        </table>
        <Pagination page={findingPage} pageSize={PAGE_SIZE} total={filtered.length} onPageChange={setFindingPage} label="findings" />
      </div>
        </>
      )}

      {view === "corrections" && (
        <CorrectionsView
          items={corrections.data?.corrections ?? []}
          selected={selCorrection}
          onSelect={setSelCorrection}
          onClose={() => setSelCorrection(null)}
          canExecute={me.data?.user.permissions.includes("technical.safe_fix") ?? false}
          executing={approveFix.isPending}
          result={approveFix.data}
          error={approveFix.error}
          onApprove={(fingerprint) => approveFix.mutate(fingerprint)}
          rollingBack={rollbackFix.isPending}
          rollbackError={rollbackFix.error}
          rollbackResult={rollbackFix.data}
          onRollback={(fingerprint) => rollbackFix.mutate(fingerprint)}
          bulk={bulk}
          onBulkChange={setBulk}
          onDelegate={() => setDelegateOpen(true)}
        />
      )}

      {delegateOpen && (
        <DelegateCampaignModal
          fingerprints={[...bulk]}
          onClose={() => setDelegateOpen(false)}
          onCreated={() => { setDelegateOpen(false); setBulk(new Set()); queryClient.invalidateQueries({ queryKey: ["corrections"] }); }}
        />
      )}

      {selected && <FindingDrawer finding={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function FindingDrawer({ finding, onClose }: { finding: TechnicalFinding; onClose: () => void }) {
  const f = finding;
  return (
    <AccessibleDrawer title={f.rule.label} onClose={onClose}>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{f.rule.label}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Fechar detalhe">Fechar</Button>
        </div>
        <div className="mb-4 flex items-center gap-2">
          <Badge tone={TONES[f.severity] ?? "neutral"}>{f.severity}</Badge>
          <span className="text-[11px] text-[var(--muted)]">{layerLabel(f.rule.layer)}</span>
        </div>

        <Section title="Post">
          <p>{f.title || "Página sem título identificado"}</p>
          <div className="mt-2 flex gap-2 text-sm">
            <a href={f.page.public_url} target="_blank" rel="noopener noreferrer" className="text-[var(--primary)]">Abrir publicação ↗</a>
            <span className="text-[var(--muted)]">· dev 28 dias</span>
          </div>
        </Section>

        <Section title="Publicação headless">
          <div className="text-sm">
            <AriaLink href={f.page.public_url} label="Abrir publicação">Publicado · {shortUrl(f.page.public_url)}</AriaLink>
          </div>
          <div className="mt-1 text-sm">
            <AriaLink href={f.page.wordpress_url} label="Abrir WordPress">WordPress · {shortUrl(f.page.wordpress_url)}</AriaLink>
          </div>
          {f.page.wordpress_edit_url && (
            <div className="mt-1 text-sm"><AriaLink href={f.page.wordpress_edit_url} label="Editar no WordPress">Editar no WordPress ↗</AriaLink></div>
          )}
        </Section>

        <Section title="Diagnóstico">
          <p className="text-sm text-[var(--muted)]">{f.rule.diagnosis}</p>
        </Section>

        <Section title="Google Search Console">
          {f.google.data_status === "available" ? (
            <div className="text-sm">
              <Grid rows={[
                ["Período", f.google.window_start ? `${f.google.window_start.slice(5).replace("-", "/")} – ${f.google.window_end?.slice(5).replace("-", "/")}` : "—"],
                ["Impressões", fmt(f.google.impressions)],
                ["Cliques", fmt(f.google.clicks)],
                ["CTR", pct(f.google.ctr)],
                ["Posição média", num(f.google.position)],
                ["CTR esperado", f.google.expected_ctr != null ? pct(f.google.expected_ctr) : "—"],
              ]} />
              {f.google.top_queries.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-xs font-medium text-[var(--muted)]">TOP QUERIES</div>
                  <table className="w-full text-xs">
                    <thead className="text-left text-[var(--muted)]"><tr><th className="py-1">query</th><th>impr.</th><th>CTR</th><th>pos.</th></tr></thead>
                    <tbody>
                      {f.google.top_queries.map((q, i) => (
                        <tr key={i}><td className="max-w-[14rem] truncate py-0.5">{q.query}</td><td className="tabular-nums">{fmtNum(q.impressions)}</td><td className="tabular-nums">{pct(q.ctr)}</td><td className="tabular-nums">{num(q.position)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-[var(--muted)]">Sem dados do Search Console.</p>
          )}
        </Section>

        <Section title="Potencial estimado">
          {f.potential.realistic != null ? (
            <div className="text-sm">
              <div className="grid grid-cols-3 gap-2">
                <Scenario label="Conservador" value={f.potential.conservative} />
                <Scenario label="Realista" value={f.potential.realistic} />
                <Scenario label="Otimista" value={f.potential.optimistic} />
              </div>
              <p className="mt-2 text-[11px] text-[var(--muted)]">
                Estimativa baseada nas impressões atuais ({fmt(f.potential.impressions)}), posição
                ({num(f.potential.position)}) e diferença entre CTR observado ({pct(f.potential.ctr)})
                e CTR esperado ({pct(f.potential.ctr_expected)}). Não representa garantia de resultado.
              </p>
            </div>
          ) : (
            <p className="text-sm text-[var(--muted)]">Potencial ainda não calculado.</p>
          )}
        </Section>

        <Section title="Camada da correção">
          <div className="text-sm">
            {layerLabel(f.rule.layer)} · <span className="text-[var(--muted)]">padrão {f.rule.level}</span>
          </div>
          {f.rule.suggested_action && <p className="mt-1 text-sm text-[var(--muted)]">Recomendação: {f.rule.suggested_action}.</p>}
        </Section>
    </AccessibleDrawer>
  );
}

function CorrectionsView({ items, selected, onSelect, onClose, canExecute, executing, result, error, onApprove, rollingBack, rollbackError, rollbackResult, onRollback, bulk, onBulkChange, onDelegate }: {
  items: Correction[]; selected: Correction | null; onSelect: (c: Correction) => void; onClose: () => void;
  canExecute: boolean; executing: boolean; result: { ok: boolean; approved: boolean; dry_run: boolean } | undefined; error: Error | null; onApprove: (fingerprint: string) => void;
  rollingBack: boolean; rollbackError: Error | null; rollbackResult: { ok: boolean; reversible: boolean } | undefined; onRollback: (fingerprint: string) => void;
  bulk: Set<string>; onBulkChange: (next: Set<string>) => void; onDelegate: () => void;
}) {
  const [page, setPage] = useState(1);
  const visibleItems = pageSlice(items, page, PAGE_SIZE);
  const pendingItems = items.filter((c) => c.status !== "executed" && c.status !== "reverted");
  const allSelected = pendingItems.length > 0 && pendingItems.every((c) => bulk.has(c.fingerprint));
  const toggleOne = (fp: string) => { const n = new Set(bulk); n.has(fp) ? n.delete(fp) : n.add(fp); onBulkChange(n); };
  const toggleAll = () => { const n = new Set(bulk); if (allSelected) { for (const c of pendingItems) n.delete(c.fingerprint); } else { for (const c of pendingItems) n.add(c.fingerprint); } onBulkChange(n); };
  return (
    <>
      <div className="mb-2 flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={allSelected} onChange={toggleAll} />
          <span className="text-xs text-[var(--muted)]">Selecionar todas (pendentes)</span>
        </label>
        {bulk.size > 0 && (
          <Button size="sm" onClick={onDelegate} disabled={!canExecute}>Delegar correções ({bulk.size})</Button>
        )}
      </div>
      <div className="overflow-hidden rounded-[9px] border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead className="bg-[var(--surface-raised)] text-left text-xs text-[var(--muted)]">
            <tr><th className="w-8 px-3 py-2"><span className="sr-only">Selecionar</span></th><th className="px-3 py-2">Regra</th><th className="px-3 py-2">URL</th><th className="px-3 py-2">Status</th><th className="px-3 py-2"><span className="sr-only">Ação</span></th></tr>
          </thead>
          <tbody>
            {visibleItems.map((c) => (
              <tr key={c.fingerprint} className="border-t border-[var(--border)]">
                <td className="px-3 py-2"><input type="checkbox" checked={bulk.has(c.fingerprint)} disabled={c.status === "executed" || c.status === "reverted"} onChange={() => toggleOne(c.fingerprint)} aria-label={`Selecionar ${c.url}`} /></td>
                <td className="px-3 py-2 font-medium">{c.label || friendlyRule(c.rule_id)}</td>
                <td className="max-w-md truncate px-3 py-2">{c.url}</td>
                <td className="px-3 py-2"><Badge tone={c.status === "executed" ? "success" : "warning"}>{c.status}</Badge></td>
                <td className="px-3 py-2 text-right"><Button size="sm" variant="secondary" onClick={() => onSelect(c)}>Preview</Button></td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-[var(--muted)]">Nenhuma correção registrada.</td></tr>}
          </tbody>
        </table>
        <Pagination page={page} pageSize={PAGE_SIZE} total={items.length} onPageChange={setPage} label="correções" />
      </div>

      {selected && (
        <AccessibleDrawer title={`Correção · ${selected.label || friendlyRule(selected.rule_id)}`} onClose={onClose}>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Correção · {selected.label || friendlyRule(selected.rule_id)}</h2>
              <Button variant="ghost" size="sm" onClick={onClose} aria-label="Fechar preview">Fechar</Button>
            </div>
            <div className="mb-2 text-xs text-[var(--muted)]">{selected.url}</div>
            <div className="mb-4 grid gap-4 md:grid-cols-2">
              <FieldCard tone="danger" title="Antes" value={metaValue(selected.before)} field={metaField(selected.before)} />
              <FieldCard tone="success" title="Depois" value={metaValue(selected.after)} field={metaField(selected.after)} />
            </div>
            <div className="mb-3">
              <div className="mb-1 text-xs font-medium text-[var(--muted)]">Rollback (reversão)</div>
              {reversible(selected) ? (
                <div className="rounded-md border border-[var(--border)] p-3 text-sm">
                  <div className="mb-1 text-[11px] text-[var(--muted)]">Redefine para o valor anterior · {metaField(selected.rollback)}</div>
                  <pre className="whitespace-pre-wrap font-mono text-xs text-[var(--muted)]">{JSON.stringify(selected.rollback ?? {}, null, 2)}</pre>
                </div>
              ) : (
                <pre className="whitespace-pre-wrap font-mono text-xs text-[var(--muted)]">{JSON.stringify(selected.rollback ?? {}, null, 2)}</pre>
              )}
            </div>
            <p className="mb-3 text-xs text-[var(--muted)]">A aprovação exige a permissão technical.safe_fix e reautenticação. O worker executará conforme dry-run, idempotência e blast radius.</p>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => onApprove(selected.fingerprint)} disabled={!canExecute || executing || selected.status === "executed"}>{executing ? "Aprovando…" : "Aprovar execução"}</Button>
              {selected.status === "executed" && (
                <Button variant="danger" onClick={() => onRollback(selected.fingerprint)} disabled={!canExecute || rollingBack || !reversible(selected)}>{rollingBack ? "Revertendo…" : "Reverter alteração"}</Button>
              )}
              {!reversible(selected) && selected.status === "executed" && <span className="text-[11px] text-[var(--muted)]">Rollback não mapeado para esta correção.</span>}
            </div>
            {!canExecute && <p className="mt-2 text-xs text-[var(--muted)]">Você não possui permissão para aprovar ou reverter esta correção.</p>}
            {result && <p className="mt-2 text-sm text-[var(--success)]">Aprovação registrada{result.dry_run ? " em dry-run" : ""}. O worker fará a execução e verificação.</p>}
            {rollbackResult && <p className="mt-2 text-sm text-[var(--success)]">Revert registrado. O worker restaurará o valor anterior.</p>}
            {error && <p className="mt-2 text-sm text-[var(--danger)]">{error.message}</p>}
            {rollbackError && <p className="mt-2 text-sm text-[var(--danger)]">{rollbackError.message}</p>}
        </AccessibleDrawer>
      )}
    </>
  );
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button onClick={onClick} className={`rounded-md px-3 py-1.5 text-sm ${active ? "bg-[var(--primary-soft)] text-[var(--primary)]" : "text-[var(--muted)] hover:bg-[var(--surface-raised)]"}`}>{children}</button>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4 border-b border-[var(--border)] pb-4">
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">{title}</div>
      {children}
    </div>
  );
}
function AriaLink({ href, label, children }: { href: string; label: string; children: React.ReactNode }) {
  return <a href={href} target="_blank" rel="noopener noreferrer" aria-label={label} className="text-[var(--primary)]">{children}</a>;
}
function Grid({ rows }: { rows: [string, string][] }) {
  return <div className="space-y-1">{rows.map(([k, v]) => <div key={k} className="flex justify-between"><span className="text-[var(--muted)]">{k}</span><span className="tabular-nums">{v}</span></div>)}</div>;
}
function Scenario({ label, value }: { label: string; value: number | null }) {
  return <div className="rounded-md border border-[var(--border)] p-2 text-center"><div className="text-sm tabular-nums font-medium">{value != null ? `+${fmtNum(value)}` : "—"}</div><div className="text-[11px] text-[var(--muted)]">{label}</div></div>;
}
function Kpi({ label, value, tone }: { label: string; value: number; tone?: "success" | "warning" }) {
  return <div className="rounded-[9px] border border-[var(--border)] bg-[var(--surface)] p-4"><div className="text-2xl font-semibold tabular-nums" style={{ color: tone ? `var(--${tone})` : "var(--foreground)" }}>{value}</div><div className="text-xs text-[var(--muted)]">{label}</div></div>;
}
function layerLabel(layer: string) {
  const map: Record<string, string> = { wordpress: "WordPress / Rank Math", headless: "Pipeline Headless / publicação", both: "WordPress + Headless", external: "Fonte externa / infra", manual_review: "Revisão manual" };
  return map[layer] ?? layer;
}
function friendlyRule(ruleId: string) {
  const labels: Record<string, string> = {
    title_manual: "Ajuste manual de título", title_opportunity: "Oportunidade de título",
    title_too_long: "Título longo", wp_static_mismatch: "Conteúdo não sincronizado",
    image_no_alt: "Imagem sem texto alternativo",
  };
  return labels[ruleId] ?? "Correção técnica";
}
function metaField(rec: Record<string, unknown> | null): string {
  const keys = Object.keys(rec ?? {});
  if (keys.length === 0) return "Campo";
  const k = keys[0];
  const map: Record<string, string> = { rank_math_title: "Título SEO (Rank Math)", alt_text: "Texto alternativo (alt)" };
  return map[k] ?? k;
}
function metaValue(rec: Record<string, unknown> | null): string {
  if (!rec) return "";
  const v = Object.values(rec)[0];
  return v == null ? "" : String(v);
}
function reversible(rec: Correction): boolean {
  const fix = rec.rollback as Record<string, unknown> | null;
  const t = fix?.type;
  return t === "wp_post_meta" || t === "wp_media_alt";
}
function FieldCard({ title, value, field, tone }: { title: string; value: string; field: string; tone: "danger" | "success" }) {
  return (
    <div className="rounded-md border border-[var(--border)] p-3 text-sm">
      <div className="mb-1 text-xs font-medium" style={{ color: `var(--${tone})` }}>{title} · {field}</div>
      <p className="whitespace-pre-wrap break-words">{value || <span className="text-[var(--muted)]">(vazio)</span>}</p>
      <div className="mt-2 text-[11px] text-[var(--muted)]">chars: {value.length}</div>
    </div>
  );
}
function shortUrl(u: string) { const host = u.replace(/^https?:\/\//, ""); const path = host.includes("/") ? host.slice(host.indexOf("/")) : ""; return `${host.split("/")[0]}${path.length > 40 ? "…" + path.slice(-24) : path}`; }
