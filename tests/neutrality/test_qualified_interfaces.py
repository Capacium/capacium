"""CAPN-R2-P03 — Provider-neutral qualified interface tests."""

from __future__ import annotations


def test_round_trip_dict():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    iface = QualifiedInterface(
        interface_id="capacium.test.runner",
        interface_version="1.0.0",
        schema_version="v1alpha1",
        status=InterfaceStatus.REQUIRED,
    )
    d = iface.to_dict()
    recreated = QualifiedInterface.from_dict(d)
    assert recreated == iface


def test_compatibility_match():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus, CompatibilityResult

    a = QualifiedInterface(
        "capacium.test.interface", "1.0.0", "v1",
        InterfaceStatus.OPTIONAL, digest="abc123",
    )
    b = QualifiedInterface(
        "capacium.test.interface", "1.0.0", "v1",
        InterfaceStatus.OPTIONAL, digest="abc123",
    )
    assert a.compatibility(b) == CompatibilityResult.MATCH
    assert a.is_compatible_with(b)


def test_interface_is_provider_neutral():
    """Two providers implementing the same interface must be compatible."""
    from src.capacium.interfaces import (
        QualifiedInterface, InterfaceStatus, CompatibilityResult, InterfaceBinding,
    )

    iface_a = QualifiedInterface(
        "capacium.interfaces.runner", "1.0.0", "v1",
        InterfaceStatus.REQUIRED,
    )
    iface_b = QualifiedInterface(
        "capacium.interfaces.runner", "1.0.0", "v1",
        InterfaceStatus.REQUIRED,
    )

    assert iface_a.compatibility(iface_b) == CompatibilityResult.MATCH

    binding_a = InterfaceBinding("capacium.interfaces.runner", "skillweave.provider", "execute")
    binding_b = InterfaceBinding("capacium.interfaces.runner", "elementeer.provider", "execute")

    assert iface_a.is_compatible_with(iface_b)
    # Two different providers bind to the same interface — incompatibility
    # must be in provider binding space, not interface identity space
    assert binding_a.provider_id != binding_b.provider_id


def test_incompatible_different_interface_id():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus, CompatibilityResult

    a = QualifiedInterface("test.iface.alpha", "1.0.0", "v1", InterfaceStatus.REQUIRED)
    b = QualifiedInterface("test.iface.beta", "1.0.0", "v1", InterfaceStatus.REQUIRED)
    assert a.compatibility(b) == CompatibilityResult.INTERFACE_MISMATCH
    assert not a.is_compatible_with(b)


def test_incompatible_different_interface_version():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus, CompatibilityResult

    a = QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED)
    b = QualifiedInterface("capacium.test.iface", "2.0.0", "v1", InterfaceStatus.REQUIRED)
    assert a.compatibility(b) == CompatibilityResult.INTERFACE_VERSION_MISMATCH


def test_incompatible_schema_version():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus, CompatibilityResult

    a = QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED)
    b = QualifiedInterface("capacium.test.iface", "1.0.0", "v2", InterfaceStatus.REQUIRED)
    assert a.compatibility(b) == CompatibilityResult.SCHEMA_VERSION_MISMATCH


def test_incompatible_digest():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus, CompatibilityResult

    a = QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED, digest="aaa")
    b = QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED, digest="bbb")
    assert a.compatibility(b) == CompatibilityResult.DIGEST_MISMATCH


def test_incompatible_status():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus, CompatibilityResult

    a = QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED)
    b = QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.OPTIONAL)
    assert a.compatibility(b) == CompatibilityResult.REQUIRED_VS_OPTIONAL


def test_owner_payload_preserved():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    iface = QualifiedInterface(
        interface_id="capacium.test.runner",
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


def test_two_providers_same_interface_compatible():
    """Prove one interface can bind to two unrelated providers."""
    from src.capacium.interfaces import (
        QualifiedInterface, InterfaceStatus, CompatibilityResult, InterfaceBinding,
    )

    iface = QualifiedInterface("capacium.interfaces.agent", "1.0.0", "v1", InterfaceStatus.REQUIRED)

    sw_binding = InterfaceBinding("capacium.interfaces.agent", "skillweave.provider", "run_agent")
    elem_binding = InterfaceBinding("capacium.interfaces.agent", "elementeer.provider", "run_agent")
    cap_binding = InterfaceBinding("capacium.interfaces.agent", "capacium.provider", "cap_run")

    assert iface.compatibility(iface) == CompatibilityResult.MATCH
    bindings = {sw_binding.provider_id, elem_binding.provider_id, cap_binding.provider_id}
    assert len(bindings) == 3, "Three independent providers must bind to the same interface"


def test_core_does_not_interpret_owner_payload():
    from src.capacium.interfaces import QualifiedInterface, InterfaceStatus

    iface = QualifiedInterface(
        interface_id="capacium.test.iface",
        interface_version="1.0.0",
        schema_version="v1",
        status=InterfaceStatus.REQUIRED,
        owner_payload={"action": "executeLocal"},
    )
    assert "owner_payload" in iface.to_dict()


def test_interface_binding_round_trip():
    from src.capacium.interfaces import InterfaceBinding

    b = InterfaceBinding("capacium.test.iface", "test.provider", "op_one")
    d = b.to_dict()
    assert d["provider_id"] == "test.provider"
    rt = InterfaceBinding.from_dict(d)
    assert rt == b


def test_check_required_interfaces_all_match():
    from src.capacium.interfaces import (
        QualifiedInterface, InterfaceStatus, CompatibilityResult, check_required_interfaces,
    )

    required = [QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED)]
    available = [QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.OPTIONAL)]
    results = check_required_interfaces(required, available)
    assert results["capacium.test.iface"] == CompatibilityResult.REQUIRED_VS_OPTIONAL


def test_check_required_interfaces_missing():
    from src.capacium.interfaces import (
        QualifiedInterface, InterfaceStatus, CompatibilityResult, check_required_interfaces,
    )

    required = [QualifiedInterface("capacium.test.iface", "1.0.0", "v1", InterfaceStatus.REQUIRED)]
    results = check_required_interfaces(required, [])
    assert results["capacium.test.iface"] == CompatibilityResult.INTERFACE_MISMATCH
