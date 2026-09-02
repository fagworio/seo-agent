import { redirect } from "next/navigation";

export default function Home() {
  // O control plane abre no Hoje; o middleware decide login vs sessão.
  redirect("/today");
}
