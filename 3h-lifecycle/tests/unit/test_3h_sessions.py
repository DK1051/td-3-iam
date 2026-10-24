"""When the engine disables a person it also ends their sessions and revokes offline tokens."""

import pytest
from fake_keycloak import seeded_fake
from support import LATER, ROLES_MAP, about, load_v2, make_plan

from lifecycle import engine
from lifecycle.kc import KeycloakError

ROLES = engine.load_roles_map(ROLES_MAP)


def calls_for(fake, username):
    user_id = fake.get_user_by_username(username)["id"]
    return [w[0] for w in fake.writes if user_id in w[1:]]


def test_disabling_a_leaver_ends_sessions_and_revokes_offline_tokens_in_order():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    # switch off -> log out everywhere -> revoke offline tokens -> write the date marker last
    assert calls_for(fake, "e4001") == ["update_user", "end_user_sessions",
                                        "revoke_offline_tokens", "update_user"]
    assert fake.get_user_by_username("e4001")["attributes"]["disabled_on"] == "2026-10-16"


def test_the_pre_start_disable_of_an_enabled_joiner_also_ends_sessions():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.seed_user("e2001", ["finance", "payments-initiate"])    # enabled before its start date
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    assert "end_user_sessions" in calls_for(fake, "e2001")
    assert "revoke_offline_tokens" in calls_for(fake, "e2001")


def test_enabling_or_moving_a_person_does_not_end_sessions():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    fake.writes.clear()
    engine.apply(make_plan(fake, feed, accounts, ROLES, today=LATER), fake)   # joiners start
    assert calls_for(fake, "e2001") == ["update_user"]
    assert not [w for w in fake.writes if w[0] in ("end_user_sessions", "revoke_offline_tokens")]


def test_a_failed_step_leaves_no_marker_so_the_next_run_finishes_the_job():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    original = fake.revoke_offline_tokens

    def broken(user_id):
        raise KeycloakError("GET /admin/realms/maple-harbour/users/{id}/consents -> HTTP 500")

    fake.revoke_offline_tokens = broken
    with pytest.raises(KeycloakError):
        engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    leaver = fake.get_user_by_username("e4001")
    assert leaver["enabled"] is False and "disabled_on" not in leaver["attributes"]
    retry = make_plan(fake, feed, accounts, ROLES)
    assert [a.kind for a in about(retry, "E4001")] == ["disable_user"]   # planned again
    fake.revoke_offline_tokens = original
    engine.apply(retry, fake)
    assert "disabled_on" in fake.get_user_by_username("e4001")["attributes"]
    assert about(make_plan(fake, feed, accounts, ROLES), "E4001") == []
