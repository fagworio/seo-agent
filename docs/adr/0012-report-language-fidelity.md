# ADR-0012 — Contrato de idioma × fidelidade do relatório (prosa × evidência)

- **Status:** aceito
- **Data:** 2026-09-21
- **Contexto:** relatório do job `Hermes SEO Agent`

## Problema

Um relatório do job citou o campo `rank_math_title` **traduzido**:

```text
Valor no WordPress:  Sony: fábrica de discos do PlayStation vira microlentes
Valor no relatório:  Sony: 的 PlayStation 光盘工厂转型为微透镜
```

Nada foi escrito no WordPress (o conteúdo, o `rank_math_title` e os metadados SEO
seguiam íntegros), mas o relatório deixou de ser uma representação fiel do estado
real do sistema. Para um agente operacional isso é um problema de
**observabilidade/fidelidade**, não de estilo: o operador passaria a decidir com
dado falso.

Causa: o prompt misturava dois contratos distintos — *idioma da resposta* e
*fidelidade dos dados citados* — e a frase "se algum dado da ferramenta chegar em
outro idioma, traduza para pt-BR antes de escrever" autorizava exatamente reescrever
evidência. O bloco "NUNCA responda em chinês/japonês/coreano/inglês" criava o
problema oposto: proibia dado legítimo de origem (`God of War`, `PlayStation`,
`Apple TV+`, um `post_title` em inglês).

## Decisão

Separar os dois contratos e verificar o segundo deterministicamente.

```text
LINGUAGEM NARRATIVA  -> pt-BR obrigatório (prosa gerada pelo agente)
DADOS DE FERRAMENTA  -> literais, byte a byte (evidência do estado real)
TRADUÇÃO             -> só na etapa editorial explicitamente destinada a ela
```

1. **Prompt** (os dois jobs): prosa em pt-BR; lista explícita de campos que não
   podem ser traduzidos/resumidos/reformatados (`post_title`, `rank_math_title`,
   `rank_math_description`, slug, URL, nome de arquivo, query do GSC, mensagem de
   erro, ID, nome próprio/marca, before/after); valores literais em outra escrita
   são **exceção permitida** (são dado de origem, não prosa). A regra proibitiva
   de idiomas foi substituída por "não use outro idioma para a prosa gerada".
   A exceção editorial (traduzir CONTEÚDO) é explícita **apenas** no job
   editorial — e continua valendo que dados técnicos permanecem literais.

2. **Guard determinístico** (`hermes_seo_agent/report/language_guard.py`, exposto
   pela CLI como `report-guard`): valida um rascunho
   `{"narrative": ..., "evidence": {campo: valor}}` sem nenhuma chamada de modelo.

   | Checagem | Violação |
   | -------- | -------- |
   | prosa sem CJK/coreano (após remover os literais citados) | `prosa_com_cjk:...` |
   | campo esperado presente na evidência | `campo_ausente:<campo>` |
   | valor da evidência igual ao da ferramenta | `valor_alterado:<campo>` |
   | valor esperado citado na prosa, byte a byte | `valor_nao_citado:<campo>` |
   | valor solto (`--expect`) presente no payload | `valor_nao_literal:<valor>` |
   | prosa não vazia | `prosa_vazia` |

   O guard remove da prosa os literais que ela cita antes de checar CJK: um
   `post_title` legítimo em japonês/chinês continua permitido, enquanto um texto
   CJK que **não** é valor de ferramenta é acusado. O idioma é validado apenas
   sobre a prosa; valores de evidência são preservados, nunca normalizados.

3. **Ciclo de correção**: `ok=false` → reescrever SOMENTE a prosa
   (`retry_instruction`) e revalidar (máximo 2 tentativas); só enviar com
   `ok=true`. Se a violação persistir, enviar a prosa corrigida + evidência
   literal + a linha "GUARD: violação residual" — nunca enviar em silêncio um
   relatório que alterou um valor.

4. **Ordem de escalada**: modelo/configuração só depois de contrato + guard +
   regeneração + teste. Sem dado empírico de que o modelo continua falhando, trocar
   de modelo é chute.

## Testes

`tests/test_language_guard.py` fixa o incidente exatamente: prosa pt-BR **e**
`rank_math_title` citado byte a byte (`Sony: fábrica de discos do PlayStation vira
microlentes`), além de rejeitar a versão traduzida, resumida, com acento/caixa
alterados, campo ausente e prosa vazia — e aceitar CJK quando ele é o valor
legítimo da ferramenta.

## Consequências

- Um relatório que "melhora" evidência passa a falhar de forma determinística, sem
  depender do julgamento do modelo ou de revisão humana.
- Dado legítimo de origem deixa de ser proibido pelo contrato de idioma.
- O custo é um passo extra no fim do run (o guard é local, zero tokens).
- Limite conhecido: o guard valida a **mensagem**, não o conteúdo publicado; no job
  editorial a tradução do conteúdo é o trabalho e continua fora do escopo dele.
