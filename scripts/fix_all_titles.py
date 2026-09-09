"""Corrige TODOS os títulos longos via SQL direto (pymysql, sem LLM).

Grupo A: rank_math_title existente >65  -> encurta o meta.
Grupo B: sem rank_math E post_title >65 -> cria rank_math_title encurtado.
Executa em batch (INSERT ... ON DUPLICATE KEY UPDATE) e confirma contagem.

Uso: .venv/bin/python scripts/fix_all_titles.py [--apply] [--limit N]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hermes_seo_agent.tools.title_opportunities import shorten_title  # noqa: E402

WP_PATH = "/www/wwwroot/prod.unicorniohater.com.br"
SOCKET = "/tmp/mysql.sock"
USER = "sql_prod_unicorniohater_com_br"
DB = "sql_prod_unicorniohater_com_br"
STATUSES = "('publish','pending','draft','future')"


def _password() -> str:
    out = subprocess.run(
        ["wp", f"--path={WP_PATH}", "--allow-root", "config", "get",
         "DB_PASSWORD"],
        capture_output=True, text=True)
    return out.stdout.strip()


def _conn(password: str) -> pymysql.Connection:
    return pymysql.connect(unix_socket=SOCKET, user=USER, password=password,
                           database=DB, charset="utf8mb4")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = _conn(_password())
    try:
        with conn.cursor() as cur:
            q = (
                "SELECT p.ID, p.post_title, pm.meta_value "
                "FROM wp_posts p LEFT JOIN wp_postmeta pm "
                "ON pm.post_id = p.ID AND pm.meta_key = 'rank_math_title' "
                f"WHERE p.post_type='post' AND p.post_status IN {STATUSES}"
            )
            if args.limit:
                q += f" LIMIT {args.limit}"
            cur.execute(q)
            rows = cur.fetchall()

        fix: list[tuple[int, str]] = []  # (post_id, novo rank_math_title)
        a = b = ok_short = 0
        for post_id, post_title, rm in rows:
            rm = (rm or "").strip()
            if rm and len(rm) > 65:
                novo = shorten_title(rm)
                if novo and novo != rm:
                    fix.append((post_id, novo))
                    a += 1
                    continue
            elif not rm and len(post_title or "") > 65:
                novo = shorten_title(post_title or "")
                if novo and novo != (post_title or ""):
                    fix.append((post_id, novo))
                    b += 1
                    continue
            ok_short += 1

        print(f"corrigir: A(rm>65)={a} | B(criar)={b} | ja ok={ok_short} "
              f"| total={len(rows)}")
        if not fix:
            print("NADA A FAZER")
            return 0

        # sanidade: nenhum novo >60 chars
        longos = [(pid, t) for pid, t in fix if len(t) > 60]
        if longos:
            print("ABORTANDO: novos titulos >60 chars:", len(longos))
            for pid, t in longos[:5]:
                print(" ", pid, len(t), t[:90])
            return 2

        if not args.apply:
            print(f"DRY-RUN: {len(fix)} prontos (A={a}, B={b}); rode --apply")
            return 0

        with conn.cursor() as cur:
            for i in range(0, len(fix), 500):
                chunk = fix[i:i + 500]
                cur.executemany(
                    "INSERT INTO wp_postmeta (post_id, meta_key, meta_value) "
                    "VALUES (%s, 'rank_math_title', %s) "
                    "ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value)",
                    chunk)
            conn.commit()
        print(f"APLICADO: {len(fix)}")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM wp_postmeta pm "
                "JOIN wp_posts p ON p.ID = pm.post_id "
                "WHERE pm.meta_key='rank_math_title' "
                "AND CHAR_LENGTH(pm.meta_value) > 65 "
                f"AND p.post_type='post' AND p.post_status IN {STATUSES}")
            rest = cur.fetchone()[0]
        print("restantes com rank_math >65:", rest)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
