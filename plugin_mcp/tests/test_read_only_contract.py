from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server.py"


def test_read_only_contract_is_explicit():
    source = SERVER.read_text(encoding="utf-8")
    assert "commit=False" in source
    assert '"committed": False' in source
    assert '"operationalMutation": False' in source


def test_no_write_tools_registered():
    source = SERVER.read_text(encoding="utf-8")
    forbidden_tool_names = [
        "finalize_po",
        "commit_receiving",
        "save_stock_opname",
        "commit_vendor_payable",
        "confirm_vendor_payment",
    ]
    for name in forbidden_tool_names:
        assert f"def {name}(" not in source


def test_receiving_token_is_not_exposed():
    source = SERVER.read_text(encoding="utf-8")
    assert 'result.pop("confirmationToken", None)' in source
