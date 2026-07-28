"""CAPN-P02 Lane C — Qualified interface tests."""

from __future__ import annotations


def test_round_trip_dict():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    iface = QualifiedInterface(
        interface_id="test.xyz/interfaces/runner/v1",
        provider_id="test.xyz",
        operation_id="run",
        interface_version="1.0.0",
        schema_version="v1alpha1",
        status=InterfaceStatus.REQUIRED,
    )
    d = iface.to_dict()
    recreated = QualifiedInterface.from_dict(d)
    assert recreated == iface


def test_compatibility_same_provider():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    a = QualifiedInterface(
        "test.xyz/interfaces/x/v1", "test.xyz", "op", "1.0.0", "v1",
        InterfaceStatus.REQUIRED,
    )
    b = QualifiedInterface(
        "test.xyz/interfaces/x/v1", "test.xyz", "op", "1.0.0", "v1",
        InterfaceStatus.OPTIONAL,
    )
    assert a.is_compatible_with(b)


def test_incompatible_different_provider():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    a = QualifiedInterface(
        "a.xyz/interfaces/x/v1", "a.xyz", "op", "1.0.0", "v1",
        InterfaceStatus.REQUIRED,
    )
    b = QualifiedInterface(
        "a.xyz/interfaces/x/v1", "b.xyz", "op", "1.0.0", "v1",
        InterfaceStatus.REQUIRED,
    )
    assert not a.is_compatible_with(b)


def test_owner_payload_preserved():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    iface = QualifiedInterface(
        interface_id="test.xyz/interfaces/runner/v1",
        provider_id="test.xyz",
        operation_id="run",
        interface_version="1.0.0",
        schema_version="v1alpha1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={"custom_key": "custom_value", "nested": {"deep": True}},
    )
    d = iface.to_dict()
    recreated = QualifiedInterface.from_dict(d)
    assert recreated.owner_payload == {
        "custom_key": "custom_value",
        "nested": {"deep": True},
    }


def test_core_does_not_interpret_owner_payload():
    """Capacium Core must not access owner_payload fields as structured data."""
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    iface = QualifiedInterface(
        interface_id="test.xyz/interfaces/x/v1",
        provider_id="test.xyz",
        operation_id="op",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={"action": "executeLocal"},
    )
    assert "owner_payload" in iface.to_dict()
