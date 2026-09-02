import { Card } from "@/design-system/card";

export default function ExperimentsPage() {
  return (
    <div className="space-y-4">
      <Card title="Experimentos & medição">
        <p className="text-sm text-[var(--muted)]">
          A implementar nesta fase (F11). O objetivo é mostrar intervenções
          (aprovadas/implementadas), a linha de base, a janela de espera, as
          métricas atuais e o delta — distinguindo <strong>movimento observado</strong>{" "}
          de certeza causal.
        </p>
      </Card>
      <Card title="Mudança não termina em executado">
        <p className="text-sm text-[var(--muted)]">
          Baseado no modelo já existente de medição before/after (impact, snapshots
          e histórico de página).
        </p>
      </Card>
    </div>
  );
}
