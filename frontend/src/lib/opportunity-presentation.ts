import type { Opportunity } from "@/lib/api";

export function presentOpportunity(item: Opportunity) {
  const detail = item.recommendation?.trim() || item.evidence?.trim();
  if (item.decision_type === "title_meta") return { label: "Título a revisar", action: "Revisar título e meta", detail: detail || "Ajuste o título e o snippet à intenção de busca identificada." };
  if (item.decision_type === "internal_link") return { label: "Link interno a adicionar", action: "Revisar link", detail: item.title ? `Adicionar um link de ${item.title.replace(" → ", " para ")}. ${detail || "Use uma âncora descritiva e contextual."}` : detail || "Inclua links de entrada a partir de páginas relevantes do mesmo tema." };
  if (item.decision_type === "content") return { label: "Conteúdo a criar ou expandir", action: "Revisar pauta", detail: detail || "Há uma intenção de busca que merece uma pauta ou ampliação de conteúdo." };
  if (item.source === "content_brief") return { label: "Conteúdo a criar ou expandir", action: "Revisar pauta", detail: detail || "Há uma intenção de busca que merece uma pauta ou ampliação de conteúdo." };
  if (item.source === "interlink") return { label: "Link interno a adicionar", action: "Revisar link", detail: detail || "Há uma conexão interna recomendada entre duas páginas do site." };
  if (item.source === "backlog") return { label: "Decisão editorial pendente", action: "Revisar pauta", detail: detail || "Esta pauta precisa de uma decisão editorial antes de avançar." };
  if ((item.type ?? "").includes("title")) return { label: "Título a revisar", action: "Revisar título", detail: detail || "Há uma oportunidade de melhorar o título para a intenção de busca da página." };
  return { label: "Oportunidade de SEO", action: "Abrir decisão", detail: detail || "Revise a evidência e escolha o próximo passo." };
}
