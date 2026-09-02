"""Catálogo de apresentação das regras de SEO.

Fonte central de label amigável + camada de correção. NENHUM mapping desse tipo
deve vazar para componentes React. O rule_id permanece no DTO para rastreabilidade
(detalhe técnico/tooltip), mas nunca é o texto principal.

Camadas (correction_target.layer): wordpress | headless | both | external | manual_review
"""

from __future__ import annotations

from ..rules.registry import Rule, get_rule


class Layer:
    WORDPRESS = "wordpress"
    HEADLESS = "headless"
    BOTH = "both"
    EXTERNAL = "external"
    MANUAL_REVIEW = "manual_review"


# rule_id -> (label amigável, camada de correção, diagnóstico humano)
_PRESENTATION: dict[str, tuple[str, str, str]] = {
    "title_too_long": ("Título longo", Layer.WORDPRESS,
                       "O título ultrapassa o limite recomendado de caracteres e pode ser truncado nos resultados de busca."),
    "title_missing": ("Título ausente", Layer.WORDPRESS,
                      "A página não possui title, o que prejudica a relevância e o CTR no resultado de busca."),
    "title_duplicate": ("Título duplicado", Layer.WORDPRESS,
                        "Várias páginas compartilham o mesmo title, diluindo a sinalização de relevância."),
    "meta_too_long": ("Meta description longa", Layer.WORDPRESS,
                      "A meta description ultrapassa o limite e pode ser truncada nos resultados de busca."),
    "meta_missing": ("Meta description ausente", Layer.WORDPRESS,
                     "A página não possui meta description; o snippet é montado automaticamente pelo Google."),
    "canonical_conflict": ("Canonical divergente", Layer.WORDPRESS,
                           "O rel canonical não aponta para a URL canônica esperada."),
    "canonical_missing": ("Canonical ausente", Layer.WORDPRESS,
                          "A página não possui rel canonical definido."),
    "wp_static_mismatch": ("Conteúdo não sincronizado com o site publicado", Layer.HEADLESS,
                           "O post existe no WordPress, mas a URL correspondente não está no site headless publicado."),
    "broken_internal_link": ("Link interno quebrado", Layer.WORDPRESS,
                             "Há um link interno apontando para uma URL com erro (404/inacessível)."),
    "broken_external_link": ("Link externo quebrado", Layer.WORDPRESS,
                             "Há um link externo que retorna erro."),
    "redirect_chain": ("Cadeia de redirecionamentos", Layer.HEADLESS,
                       "A URL passa por mais de um redirecionamento antes do destino final."),
    "redirect_loop": ("Loop de redirecionamento", Layer.HEADLESS,
                      "A URL entra em loop de redirecionamento."),
    "noindex_inconsistency": ("Conflito de indexação", Layer.WORDPRESS,
                              "As diretivas de indexação conflitam entre si (meta robots / X-Robots-Tag / robots.txt)."),
    "sitemap_blocked": ("Página bloqueada no sitemap", Layer.HEADLESS,
                        "A URL está no sitemap, mas é bloqueada pelas regras de robots.txt."),
    "orphan_page": ("Página órfã", Layer.HEADLESS,
                    "A URL está no sitemap, mas não possui contraparte no WordPress."),
    "static_orphan": ("URL estática sem contraparte WordPress", Layer.BOTH,
                      "A URL estática publicada não possui origem no WordPress."),
    "structured_data_invalid": ("Dados estruturados inválidos", Layer.WORDPRESS,
                                "O JSON-LD da página apresenta erros de validação."),
    "image_no_alt": ("Imagem sem texto alternativo", Layer.WORDPRESS,
                     "Item de mídia ou <img> sem texto alternativo (alt)."),
    "image_no_dimensions": ("Imagem sem dimensões", Layer.WORDPRESS,
                            "<img> sem width/height declarados (risco de CLS)."),
    "cwv_lcp_poor": ("LCP abaixo do recomendado", Layer.EXTERNAL,
                     "LCP acima de 2,5s (laboratório ou campo)."),
    "cwv_cls_poor": ("CLS acima do recomendado", Layer.EXTERNAL,
                     "CLS acima de 0,1 (laboratório ou campo)."),
    "cwv_inp_poor": ("INP acima do recomendado", Layer.EXTERNAL,
                     "INP acima de 200ms (laboratório ou campo)."),
    "low_ctr_opportunity": ("Baixo CTR com alto volume de impressões", Layer.WORDPRESS,
                            "Alto volume de impressões com CTR abaixo do esperado — oportunidade de título."),
    "zero_click_impression": ("Impressões sem cliques", Layer.WORDPRESS,
                              "A página recebe impressões mas nenhum clique na janela."),
    "duplicate_content": ("Conteúdo duplicado", Layer.WORDPRESS,
                          "Título+H1 normalizados idênticos em páginas distintas."),
    "thin_content": ("Conteúdo fino", Layer.WORDPRESS,
                     "O conteúdo pode ser semanticamente raso."),
    "keyword_cannibalization": ("Canibalização de palavra-chave", Layer.WORDPRESS,
                                "Várias URLs disputam a mesma palavra-chave."),
}


def rule_presentation(rule_id: str) -> dict[str, str]:
    """Retorna label + camada + descrição amigáveis, com fallback seguro."""
    label, layer, diagnosis = _PRESENTATION.get(
        rule_id, (rule_id.replace("_", " ").capitalize(), Layer.WORDPRESS,
                  "Problema técnico identificado pela análise automática."))
    rule: Rule | None = get_rule(rule_id)
    return {
        "rule_id": rule_id,
        "label": label,
        "layer": layer,
        "diagnosis": diagnosis,
        "severity": rule.severity if rule else "medium",
        "level": rule.level if rule else "observe",
        "suggested_action": rule.suggested_action if rule else "",
    }
