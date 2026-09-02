/** Formatadores compartilhados (separados de páginas — não exportar helpers de page.tsx). */
export function fmt(n: number | null | undefined) { return n == null ? "—" : n.toLocaleString("pt-BR"); }
export function fmtNum(n: number | null | undefined) { return n == null ? "0" : n.toLocaleString("pt-BR"); }
export function pct(n: number | null | undefined) { return n == null ? "—" : `${(n * 100).toFixed(1).replace(".", ",")}%`; }
export function num(n: number | null | undefined) { return n == null ? "—" : n.toFixed(1).replace(".", ","); }
