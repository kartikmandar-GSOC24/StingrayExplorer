def test_services_import_and_state_works(loaded_state):
    assert loaded_state.has_event_data("ev1")
    assert loaded_state.has_event_data("ev2")
    assert len(loaded_state.get_event_data("ev1").time) == 20000
