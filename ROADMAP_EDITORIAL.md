# Roadmap — Inteligência Editorial e Pautas de Conteúdo

Este roadmap é separado do ciclo de auditoria técnica. O objetivo é transformar
dados já disponíveis no site e no Google Search Console em **pautas editoriais
revisáveis**, com sugestões de interlinking e evidências. Nenhuma fase cria,
publica, altera ou remove conteúdo automaticamente.

## Princípios

- **Sugestão, não execução:** toda pauta entra em uma fila humana de revisão.
- **Evidência obrigatória:** uma recomendação precisa citar queries, métricas,
  URLs relacionadas ou sinais do conteúdo publicado.
- **Valor incremental:** conteúdo novo deve ter intenção e escopo próprios;
  não reutilizar texto de URLs existentes para criar duplicação.
- **Interlinking contextual:** sugerir links apenas quando a relação temática
  for clara e o destino acrescentar valor ao leitor.
- **Consolidação humana:** sinais de canibalização nunca geram redirect,
  canonical, noindex ou exclusão automática.

## Fase E0 — Fundação editorial

**Objetivo:** criar uma visão confiável do acervo antes de sugerir novos posts.

Entregas:

- Inventário persistente de cada URL publicada: title, H1, H2, texto principal,
  data de modificação, canonical e status de indexação.
- Grafo de links internos: links de saída, links de entrada e páginas sem
  conexões editoriais relevantes.
- Normalização de URLs e exclusão de navegação, rodapé, scripts e links
  utilitários do cálculo editorial.
- Snapshot de conteúdo com hash do texto principal, separado do HTML integral.

Critérios de aceite:

- É possível consultar quais páginas apontam para uma URL e para quais URLs ela
  aponta.
- O inventário cobre todas as URLs elegíveis do sitemap, com processamento
  incremental para evitar recrawl desnecessário.
- Nenhuma alteração é enviada ao WordPress.

## Fase E1 — Base de demanda e intenção

**Objetivo:** relacionar consultas de busca às páginas que o site já possui.

Entregas:

- Coleta e persistência de pares `query × página` do Search Console, com
  cliques, impressões, CTR, posição e janela analisada.
- Agrupamento determinístico de variações óbvias de query (acentos, espaços,
  plural simples), preservando a query original como evidência.
- Classificação inicial de intenção: informacional, pergunta, comparação,
  navegação/marca e atualização/notícia quando reconhecível por regras.
- Histórico mensal para diferenciar oportunidade consistente de pico passageiro.

Critérios de aceite:

- Cada oportunidade informa a janela e os dados que a sustentam.
- Queries sem volume suficiente são mantidas como sinal fraco, não como pauta.
- O sistema identifica queries compartilhadas por múltiplas URLs como
  **possível** canibalização, nunca como diagnóstico conclusivo.

## Fase E2 — Diagnóstico de lacunas por conteúdo existente

**Objetivo:** decidir quando a melhor ação é melhorar uma página existente.

Entregas:

- Comparação entre intenção/queries e title, H1, H2 e texto principal da URL.
- Diagnóstico de cobertura: resposta direta ausente, pergunta sem seção,
  estrutura insuficiente, profundidade baixa ou falta de links contextuais.
- Recomendação de expansão da URL existente antes de sugerir um post novo quando
  ela já é a melhor candidata para a intenção.
- ContentBrief com evidência, ação manual, prioridade e URLs relacionadas.

Critérios de aceite:

- A recomendação explica qual lacuna existe e em que elemento foi observada.
- Não recomenda inserir keywords sem relação com a intenção ou o escopo da URL.
- O checklist continua manual e não alimenta o executor de `safe_fix`.

## Fase E3 — Backlog de pautas novas

**Objetivo:** propor conteúdos novos que complementem o acervo e reforcem
clusters já existentes.

Novo comando proposto:

```bash
hermes-seo-agent editorial-backlog --limit 30 --write
```

Tipos de pauta:

| Tipo | Quando propor |
|---|---|
| `expand_existing` | A URL atual já atende a intenção, mas tem lacuna clara. |
| `supporting_post` | Há demanda relacionada e nenhuma URL cobre bem o ângulo específico. |
| `hub_page` | Existem vários conteúdos próximos sem uma página-guia que os conecte. |
| `cannibalization_review` | Duas ou mais URLs disputam demanda semelhante e requerem decisão editorial. |

Formato mínimo de cada pauta:

- título de trabalho e intenção;
- evidências de GSC e período analisado;
- hipótese de valor para o leitor e para o cluster;
- URLs que justificam a pauta;
- escopo original: perguntas, seções e diferenciação obrigatória;
- plano de links internos de entrada e saída;
- risco de duplicação e páginas comparadas;
- score, esforço estimado e status editorial.

Critérios de aceite:

- Uma pauta nova só é criada se não houver URL existente que já satisfaça a
  mesma intenção de maneira adequada.
- Há pelo menos uma URL existente para conectar, exceto em pautas estratégicas
  aprovadas manualmente.
- A proposta não contém corpo de post pronto nem reutiliza trechos do acervo.

## Fase E4 — Planejador de interlinking

**Objetivo:** transformar clusters e pautas aprovadas em sugestões contextuais
de links internos.

Entregas:

- Sugestões de origem → destino, com trecho/contexto onde o link caberia.
- Âncora sugerida como rascunho editorial, não texto obrigatório.
- Priorização de páginas órfãs, conteúdos de apoio e hubs relevantes.
- Proteções contra excesso de links, auto-link, URLs não canônicas e destinos
  noindex/404.

Critérios de aceite:

- Cada link recomendado contém justificativa temática e URL de destino válida.
- O resultado é uma lista para edição humana; não modifica HTML ou WordPress.
- O relatório separa links de melhoria de links necessários para a pauta nova.

## Fase E5 — Workflow editorial e medição

**Objetivo:** acompanhar as decisões humanas e medir resultados sem atribuição
indevida.

Entregas:

- Estados: `proposed`, `approved`, `rejected`, `published`, `measured`.
- Registro da URL publicada e dos links efetivamente incluídos, inseridos por
  confirmação humana.
- Baseline de GSC antes da publicação e medição após janela mínima configurável.
- Motivos de rejeição para melhorar o ranking futuro das pautas.

Critérios de aceite:

- Não declarar ganho causal sem janela pós-publicação suficiente.
- Métricas distinguem nova URL, expansão de URL e interlinking.
- Ações rejeitadas não reaparecem automaticamente sem nova evidência material.

## Fase E6 — Fontes externas opcionais

**Objetivo:** ampliar descoberta além da visibilidade atual do domínio.

O Search Console só mostra consultas que já geraram impressão para o site. Para
identificar temas em que o domínio ainda não aparece, integrar apenas com
autorização explícita uma fonte como Keyword Planner, DataForSEO, Semrush ou
Ahrefs.

Critérios de aceite:

- Proveniência e data da fonte externa ficam registradas em cada pauta.
- Custo, quota e termos de uso são respeitados.
- A fonte externa amplia evidência; não substitui a validação contra o acervo
  próprio para evitar duplicação.

## Ordem recomendada

1. E0 — Fundação editorial
2. E1 — Base de demanda e intenção
3. E2 — Lacunas em conteúdo existente
4. E3 — Backlog de pautas novas
5. E4 — Planejador de interlinking
6. E5 — Workflow e medição
7. E6 — Fontes externas, quando houver necessidade e autorização

## Fora de escopo deliberadamente

- gerar ou publicar posts automaticamente;
- copiar ou reescrever conteúdo existente para montar uma pauta;
- criar redirects, canonicals ou noindex a partir de canibalização;
- alterar links internos automaticamente;
- afirmar demanda de mercado a partir de queries sem impressões no Search
  Console.
