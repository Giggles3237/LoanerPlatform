import json

from loaner_platform.settings import (BUNDLED_DEFAULTS, SettingsStore,
                                      ratebook_from_dict, ratebook_to_dict)


def test_bundled_defaults_round_trip():
    data = json.loads(BUNDLED_DEFAULTS.read_text())
    rb = ratebook_from_dict(data)
    assert len(rb.programs) > 0
    assert rb.discount_chart[0][0] == 0
    assert ratebook_to_dict(ratebook_from_dict(ratebook_to_dict(rb))) == ratebook_to_dict(rb)


def test_store_save_load(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    rb = store.load()  # falls back to bundled defaults
    rb.program_mileage_limit = 16000
    rb.programs.popitem()
    store.save(rb)
    rb2 = store.load()
    assert rb2.program_mileage_limit == 16000
    assert len(rb2.programs) == len(rb.programs)
