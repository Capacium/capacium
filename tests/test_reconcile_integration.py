from unittest.mock import patch
from capacium.commands.list_capabilities import list_capabilities
from capacium.commands.doctor import doctor

@patch("capacium.commands.reconcile.show_reconcile_summary")
def test_list_capabilities_calls_reconcile(mock_show):
    # Call list_capabilities without json_output
    list_capabilities(json_output=False)
    mock_show.assert_called_once()

@patch("capacium.commands.reconcile.show_reconcile_summary")
def test_list_capabilities_skips_reconcile_json(mock_show):
    # Call list_capabilities with json_output
    list_capabilities(json_output=True)
    mock_show.assert_not_called()

@patch("capacium.commands.reconcile.show_reconcile_summary")
def test_doctor_calls_reconcile(mock_show):
    # Call doctor with no caps, should still run basic logic and call summary
    doctor()
    mock_show.assert_called_once()

# For install, since it is triggered via cli.py, we can just test the function directly if it was injected there, but wait, it is in cli.py.
