type Tone = "info" | "primary" | "warning" | "success";

/** Guia de cada tipo de pauta: explica em linguagem humana o que é e como fazer. */
export type Guide = { label: string; hint: string; what: string; how: string; tone: Tone };

export const TYPE_GUIDE: Record<string, Guide> = {
  hub_page: {
    label: "Criar página-guia (hub)",
    hint: "Organizar um grupo de posts do mesmo tema",
    what: 'Você tem vários posts sobre um mesmo tema (um "cluster"), mas nenhuma página que os apresente e conecte. O Google e o leitor não têm uma "porta de entrada" clara desse assunto.',
    how: "Crie uma página-guia que liste, apresente e linke todos os posts dessa categoria. É a página principal do tema: melhora a navegação do site e mostra ao Google que esse assunto é central para você.",
    tone: "info",
  },
  supporting_post: {
    label: "Criar post de apoio",
    hint: "Responder uma busca com demanda, mas sem página boa",
    what: 'Há uma busca com tráfego real (impressões/cliques), mas nenhuma página sua a responde bem. Esse conteúdo faz falta: é um "post de apoio" que soma ao tema (cluster).',
    how: "Escreva um post novo e específico que responda diretamente a essa busca, com ângulo e seções próprias, diferenciando-se das páginas já publicadas. Ao publicar, linke com os outros posts do tema para reforçar o cluster.",
    tone: "primary",
  },
  cannibalization_review: {
    label: "Revisar canibalização",
    hint: "Páginas diferentes disputam a MESMA busca",
    what: 'Mais de uma página sua compete pela mesma busca — uma "rouba" cliques da outra. Isso divide autoridade e confunde o Google sobre qual é a página principal.',
    how: "Decida qual URL é a principal para essa busca; diferencie o ângulo de cada página (cada uma com seu foco) ou combine as que se sobrepõem (consolidação).",
    tone: "warning",
  },
  expand_existing: {
    label: "Expandir página existente",
    hint: "Completar as lacunas de uma página que já posiciona",
    what: "Uma página já cobre a intenção da busca, mas está incompleta em relação ao que as pessoas procuram (faltam seções, respostas ou ângulos).",
    how: 'Adicione ao conteúdo os pontos que faltam (as "lacunas"): seções, respostas diretas e subtópicos. Isso faz a página responder melhor à busca e ganhar relevância, sem criar conteúdo novo.',
    tone: "success",
  },
};

export const FALLBACK_GUIDE: Guide = {
  label: "Pauta editorial",
  hint: "Ação editorial sugerida",
  what: "O agente identificou uma oportunidade de melhoria no conteúdo do site.",
  how: "Revise as evidências ao lado, decida aprovar/adiar/rejeitar e, se aprovar, siga para a publicação.",
  tone: "info",
};

/** Rótulo amigável do slug de pauta (hub_page / supporting_post / …). */
export function guideOf(type: string): Guide {
  return TYPE_GUIDE[type] ?? FALLBACK_GUIDE;
}

/** Traduz a "intenção" (linguagem da máquina) para uma frase clara. */
export function intentLabel(intent: string): string {
  const m: Record<string, string> = {
    "navegação/cluster": "Organizar um grupo de posts do mesmo tema (cluster), criando uma página de entrada que os conecta.",
    "revisão": "Resolver páginas que disputam a mesma busca (canibalização).",
    question: "Responder diretamente a uma pergunta específica que o público faz.",
    informational: "Explicar um assunto e informar o leitor sobre um tema.",
  };
  const key = (intent || "").toLowerCase();
  return m[key] ?? (key || "não informado");
}

export type { Tone };
