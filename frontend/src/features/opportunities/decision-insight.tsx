import type { Opportunity } from "@/lib/api";

const number = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const text = (value: unknown): string => typeof value === "string" ? value : "";

const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });

export function opportunityEvidenceSummary(item: Opportunity): string {
  if (item.source === "interlink" || item.decision_type === "internal_link") {
    const terms = item.link_context?.shared_terms ?? [];
    if (terms.length) return `${terms.length} termo${terms.length === 1 ? "" : "s"} relacionado${terms.length === 1 ? "" : "s"} · confiança ${confidenceLabel(item.link_context?.confidence)}`;
    return "Relação temática precisa ser revalidada";
  }
  const gsc = item.gsc_metrics ?? {};
  if (gsc.has_queries === true) {
    return `${integer.format(number(gsc.impressions) ?? 0)} impressões · ${integer.format(number(gsc.clicks) ?? 0)} cliques`;
  }
  const realistic = number(item.projection?.realistic_clicks);
  if (realistic !== null) return `Cenário realista: ${integer.format(realistic)} cliques`;
  return "Evidência quantitativa indisponível";
}

export function DecisionInsight({ item }: { item: Opportunity }) {
  const gsc = item.gsc_metrics ?? {};
  const ga4 = item.ga4_metrics ?? {};
  const projection = item.projection ?? {};
  const breakdown = item.score_breakdown ?? {};
  const hasGsc = gsc.has_queries === true;
  const hasGa4 = text(ga4.measurement_status) === "available" || number(ga4.sessions) !== null;
  const impressions = number(gsc.impressions);
  const clicks = number(gsc.clicks);
  const ctr = impressions && clicks !== null ? clicks / impressions : number(projection.ctr);
  const expectedCtr = number(projection.expected_ctr);
  const queryRows = item.top_queries ?? [];
  const isInternalLink = item.decision_type === "internal_link" || item.source === "interlink";
  const hasPriority = number(item.score) !== null || [breakdown.impacto, breakdown.confianca, breakdown.facilidade].some((value) => number(value) !== null);

  return (
    <div className="space-y-5 text-sm">
      {isInternalLink && <LinkContext item={item} />}

      {hasPriority && <section aria-labelledby="priority-title">
        <SectionTitle id="priority-title">Prioridade da decisão</SectionTitle>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="Índice" value={formatScore(item.score)} />
          <Metric label="Impacto" value={formatFactor(breakdown.impacto)} />
          <Metric label="Confiança" value={formatFactor(breakdown.confianca)} />
          <Metric label="Facilidade" value={formatFactor(breakdown.facilidade)} />
        </div>
        {text(breakdown.confianca_note) && <p className="mt-2 text-xs text-[var(--muted)]">{text(breakdown.confianca_note)}</p>}
      </section>}

      <section aria-labelledby="evidence-title">
        <SectionTitle id="evidence-title">Evidência atual</SectionTitle>
        {hasGsc ? (
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Metric label="Impressões" value={integer.format(impressions ?? 0)} />
            <Metric label="Cliques" value={integer.format(clicks ?? 0)} />
            <Metric label="CTR atual" value={ctr === null ? "—" : percent.format(ctr)} />
            <Metric label="Posição média" value={formatDecimal(number(gsc.position))} />
          </div>
        ) : <MissingData text="Search Console sem dados para esta URL na janela disponível." />}
        <p className="mt-2 leading-6">{item.evidence || "A justificativa textual ainda não foi registrada."}</p>
        {item.data_freshness?.gsc_window_start && (
          <p className="mt-1 text-xs text-[var(--muted)]">Fonte: Google Search Console · janela iniciada em {item.data_freshness.gsc_window_start}</p>
        )}
      </section>

      <section aria-labelledby="potential-title">
        <SectionTitle id="potential-title">Potencial estimado</SectionTitle>
        {hasProjection(projection) ? (
          <>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric label="CTR esperado" value={expectedCtr === null ? "—" : percent.format(expectedCtr)} />
              <Metric label="Cliques esperados" value={formatInteger(number(projection.expected_clicks))} />
              <Metric label="Oportunidade" value={signedClicks(number(projection.gap_clicks))} />
              <Metric label="Cenário realista" value={formatInteger(number(projection.realistic_clicks))} />
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              <Metric label="Conservador" value={formatInteger(number(projection.conservative_clicks))} compact />
              <Metric label="Realista" value={formatInteger(number(projection.realistic_clicks))} compact />
              <Metric label="Otimista" value={formatInteger(number(projection.optimistic_clicks))} compact />
            </div>
            <p className="mt-2 text-xs text-[var(--muted)]">Estimativa determinística baseada na janela disponível; não é garantia de resultado.</p>
          </>
        ) : isInternalLink ? (
          <MissingData text="Impacto qualitativo: melhora descoberta e distribuição de autoridade. O backend não possui modelo confiável para prever cliques deste link." />
        ) : <MissingData text="Ainda não há projeção calculada para esta oportunidade. Aprovar não implica uma promessa de ganho." />}
      </section>

      {queryRows.length > 0 && (
        <section aria-labelledby="queries-title">
          <SectionTitle id="queries-title">Consultas que sustentam a decisão</SectionTitle>
          <div className="mt-2 overflow-x-auto rounded-md border border-[var(--border)]">
            <table className="w-full text-xs">
              <thead className="bg-[var(--surface-raised)] text-left text-[var(--muted)]"><tr><th className="px-2 py-2">Consulta</th><th className="px-2 py-2">Impressões</th><th className="px-2 py-2">Cliques</th><th className="px-2 py-2">Posição</th></tr></thead>
              <tbody>{queryRows.map((row) => <tr key={row.query} className="border-t border-[var(--border)]"><td className="max-w-48 px-2 py-2 font-medium">{row.query}</td><td className="px-2 py-2 tabular-nums">{integer.format(row.impressions)}</td><td className="px-2 py-2 tabular-nums">{integer.format(row.clicks)}</td><td className="px-2 py-2 tabular-nums">{formatDecimal(row.position)}</td></tr>)}</tbody>
            </table>
          </div>
        </section>
      )}

      <section aria-labelledby="engagement-title">
        <SectionTitle id="engagement-title">Engajamento e validação</SectionTitle>
        {hasGa4 ? <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3"><Metric label="Sessões orgânicas" value={formatInteger(number(ga4.sessions))} /><Metric label="Taxa de engajamento" value={number(ga4.engagement_rate) === null ? "—" : percent.format(number(ga4.engagement_rate)!)} /><Metric label="Eventos principais" value={formatInteger(number(ga4.key_events))} /></div> : <MissingData text="GA4 sem dados para esta URL. Ausência de coleta não é interpretada como zero." />}
        <p className="mt-2 text-xs text-[var(--muted)]">Medição: {measurementLabel(item.measurement_state)}. Depois da implementação, o resultado deve ser comparado ao baseline em Experimentos.</p>
      </section>

      <section aria-labelledby="risk-title">
        <SectionTitle id="risk-title">Risco e reversibilidade</SectionTitle>
        <div className="mt-2 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3">
          <p><strong>Risco:</strong> {riskLabel(item.risk)}</p>
          <p className="mt-1"><strong>Reversão:</strong> {item.rollback_available ? "disponível" : "não informada ou não aplicável"}</p>
        </div>
      </section>
    </div>
  );
}

function LinkContext({ item }: { item: Opportunity }) {
  const link = item.link_context ?? {};
  const terms = link.shared_terms ?? [];
  const weak = link.relevance === "weak";
  return <section aria-labelledby="link-title" className="space-y-3">
    <SectionTitle id="link-title">Como este link deve ser feito</SectionTitle>
    {weak && <div className="rounded-md border border-[var(--warning)]/30 bg-[var(--warning)]/10 p-3 text-[var(--warning)]"><strong>Evidência temática fraca.</strong><p className="mt-1 text-xs">O corpus atual não confirmou relação suficiente para aprovação automática. Reanalise o contexto ou rejeite esta sugestão.</p></div>}
    <div className="space-y-3 rounded-md border border-[var(--border)] bg-[var(--surface-raised)] p-3">
      <PageLine label="Página onde o link será inserido" title={link.source_title} url={link.source_url} />
      <div className="border-l-2 border-[var(--primary)] pl-3"><span className="text-xs text-[var(--muted)]">Palavra ou expressão que terá o link</span><blockquote className="mt-1 text-base font-semibold">“{link.suggested_anchor || link.anchor || "Âncora ainda não determinada"}”</blockquote><p className="mt-1 text-xs text-[var(--muted)]">Sugestão baseada no assunto da página de destino. Adapte flexão e artigo à frase, sem trocar o significado.</p></div>
      <PageLine label="Página para onde o usuário será levado" title={link.target_title} url={link.target_url || item.url} />
    </div>

    <div><h4 className="font-medium">O que foi identificado</h4><p className="mt-1 leading-6">{item.evidence || "A sugestão foi gerada a partir da relação temática entre as páginas."}</p>{terms.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{terms.map((term) => <span key={term} className="rounded-full border border-[var(--border)] bg-[var(--surface-raised)] px-2 py-1 text-xs">{term}</span>)}</div> : <MissingData text="A revalidação do corpus não encontrou nenhum termo temático forte entre os dois conteúdos." />}<p className="mt-2 text-xs text-[var(--muted)]">Confiança da relação: {confidenceLabel(link.confidence)}.</p></div>

    <div><h4 className="font-medium">Onde inserir</h4>{link.source_excerpt ? <blockquote className="mt-2 rounded-md border-l-2 border-[var(--primary)] bg-[var(--surface-raised)] p-3 leading-6">{link.source_excerpt}</blockquote> : <MissingData text="O sistema não encontrou um trecho exato com contexto suficiente." />}<p className="mt-2 leading-6">{link.insertion_instruction || "Localize uma menção contextual ao tema do destino; não adicione o link em uma frase sem relação editorial."}</p></div>

    <div className="grid gap-3 sm:grid-cols-2"><BenefitList title="Como ajuda o Google" items={link.google_benefits} /><BenefitList title="Como ajuda o leitor e o site" items={link.site_benefits} /></div>
    <div><h4 className="font-medium">Como comprovar depois</h4><ol className="mt-2 list-decimal space-y-1 pl-5 text-[var(--muted)]">{(link.verification_steps ?? ["Confirmar o link no próximo rastreamento.", "Comparar métricas do destino após a janela de medição."]).map((step) => <li key={step}>{step}</li>)}</ol></div>
    <div className="grid grid-cols-2 gap-2"><Metric label="Links que chegam ao destino" value={formatInteger(number(link.target_inbound_links))} compact /><Metric label="Links que saem da origem" value={formatInteger(number(link.source_outbound_links))} compact /></div>
  </section>;
}

function PageLine({ label, title, url }: { label: string; title?: string; url?: string }) { return <div><span className="text-xs text-[var(--muted)]">{label}</span><p className="font-medium">{cleanTitle(title) || "Título não disponível"}</p><p className="mt-0.5 break-all text-xs text-[var(--muted)]">{url || "URL não informada"}</p></div>; }
function BenefitList({ title, items }: { title: string; items?: string[] }) { return <div className="rounded-md border border-[var(--border)] p-3"><h4 className="font-medium">{title}</h4><ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5 text-[var(--muted)]">{(items ?? []).map((value) => <li key={value}>{value}</li>)}{!items?.length && <li>Benefício ainda não detalhado.</li>}</ul></div>; }
function SectionTitle({ id, children }: { id: string; children: React.ReactNode }) { return <h3 id={id} className="font-semibold">{children}</h3>; }
function Metric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) { return <div className={`rounded-md border border-[var(--border)] bg-[var(--surface-raised)] ${compact ? "p-2" : "p-3"}`}><span className="block text-xs text-[var(--muted)]">{label}</span><strong className="mt-1 block tabular-nums">{value}</strong></div>; }
function MissingData({ text: value }: { text: string }) { return <div className="mt-2 rounded-md border border-dashed border-[var(--border)] p-3 text-[var(--muted)]">{value}</div>; }
function hasProjection(value: Record<string, unknown>) { return ["expected_ctr", "expected_clicks", "gap_clicks", "realistic_clicks"].some((key) => number(value[key]) !== null); }
function formatInteger(value: number | null) { return value === null ? "—" : integer.format(value); }
function formatDecimal(value: number | null) { return value === null ? "—" : decimal.format(value); }
function signedClicks(value: number | null) { return value === null ? "—" : `${value >= 0 ? "+" : ""}${integer.format(value)} cliques`; }
function formatFactor(value: unknown) { const parsed = number(value); return parsed === null ? "—" : percent.format(parsed); }
function formatScore(value: number | null) { if (value === null) return "—"; return value <= 1 ? percent.format(value) : decimal.format(value); }
function measurementLabel(value?: string) { return ({ pending: "baseline pendente", proposed: "aguardando decisão", measuring: "em observação", measured: "resultado medido", waiting_data: "aguardando dados" } as Record<string, string>)[value ?? ""] ?? "ainda não mensurável"; }
function riskLabel(value?: string) { return ({ low: "baixo", medium: "médio", high: "alto", review_required: "requer revisão humana" } as Record<string, string>)[value ?? ""] ?? value ?? "não informado"; }
function confidenceLabel(value?: string) { return ({ high: "alta", medium: "média", low: "baixa" } as Record<string, string>)[value ?? ""] ?? "não calculada"; }
function cleanTitle(value?: string) { return (value ?? "").replace(/\s+[—|-]\s+UnicornioHater$/i, "").trim(); }
