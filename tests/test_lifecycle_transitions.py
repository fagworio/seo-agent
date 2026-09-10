"""Regressão P0: estados TERMINAIS do lifecycle não podem regredir/voltar à fila.

O guard anterior era inalcançável (o `if` externo excluía os terminais), então
`implemented → approved` e `rejected → approved` passavam — reenfileirando itens
já finalizados na Caixa e permitindo ação duplicada por campanha.
"""
from hermes_seo_agent.storage.db import Storage


def _status(s: Storage, wid: str) -> str:
    lc = s.get_work_item_lifecycle(wid)
    return lc["status"] if lc else ""


def test_implemented_does_not_regress_to_approved(tmp_path):
    with Storage(str(tmp_path / "l.db")) as s:
        s.set_work_item_lifecycle("checklist:1", "approved")
        s.set_work_item_lifecycle("checklist:1", "implemented")
        s.set_work_item_lifecycle("checklist:1", "approved")   # tentativa de retroceder
        assert _status(s, "checklist:1") == "implemented"
        s.set_work_item_lifecycle("checklist:1", "new")        # também bloqueado
        assert _status(s, "checklist:1") == "implemented"


def test_rejected_is_terminal(tmp_path):
    with Storage(str(tmp_path / "l.db")) as s:
        s.set_work_item_lifecycle("checklist:2", "rejected")
        s.set_work_item_lifecycle("checklist:2", "approved")
        assert _status(s, "checklist:2") == "rejected"


def test_measured_is_terminal(tmp_path):
    with Storage(str(tmp_path / "l.db")) as s:
        s.set_work_item_lifecycle("checklist:3", "measured")
        s.set_work_item_lifecycle("checklist:3", "approved")
        assert _status(s, "checklist:3") == "measured"


def test_implemented_can_advance_to_measured(tmp_path):
    with Storage(str(tmp_path / "l.db")) as s:
        s.set_work_item_lifecycle("checklist:4", "implemented")
        s.set_work_item_lifecycle("checklist:4", "measured")
        assert _status(s, "checklist:4") == "measured"


def test_non_terminal_regression_blocked(tmp_path):
    with Storage(str(tmp_path / "l.db")) as s:
        s.set_work_item_lifecycle("checklist:5", "executing")
        s.set_work_item_lifecycle("checklist:5", "approved")   # rank menor: bloqueado
        assert _status(s, "checklist:5") == "executing"


def test_forward_transitions_still_allowed(tmp_path):
    with Storage(str(tmp_path / "l.db")) as s:
        s.set_work_item_lifecycle("checklist:6", "new")
        s.set_work_item_lifecycle("checklist:6", "approved")
        s.set_work_item_lifecycle("checklist:6", "delegated")
        s.set_work_item_lifecycle("checklist:6", "executing")
        s.set_work_item_lifecycle("checklist:6", "implemented")
        assert _status(s, "checklist:6") == "implemented"
