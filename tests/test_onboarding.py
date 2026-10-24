from src.onboarding import checklist, next_step


def test_a_new_farm_starts_at_the_milk_price_and_each_step_ticks_off():
    items = checklist(price=None, cows=[], in_milk=None, feeds=[], logged=[])
    assert [i[0] for i in items] == ["price", "cows", "in_milk", "feeds", "first_log"]
    assert not any(i[4] for i in items) and next_step(items)[0] == "price"
    items = checklist(price=50, cows=[{"id": 1}], in_milk=None, feeds=[], logged=[])
    assert [i[0] for i in items if i[4]] == ["price", "cows"] and next_step(items)[0] == "in_milk"


def test_a_milk_price_of_zero_still_counts_as_set_and_a_finished_farm_has_no_next_step():
    assert checklist(0, [], None, [], [])[0][4]
    done = checklist(50, [1], 3, [1], [1])
    assert all(i[4] for i in done) and next_step(done) is None
