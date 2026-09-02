"use client";

import { useEffect, useState } from "react";
import { Button } from "@/design-system/button";

type Theme = "light" | "dark";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  useEffect(() => {
    const saved = window.localStorage.getItem("seo-agent-theme") as Theme | null;
    const next = saved ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
  }, []);
  function toggle() {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    window.localStorage.setItem("seo-agent-theme", next);
  }
  return <Button variant="ghost" size="sm" onClick={toggle} aria-label={`Ativar tema ${theme === "light" ? "escuro" : "claro"}`}>
    {theme === "light" ? "Escuro" : "Claro"}
  </Button>;
}
