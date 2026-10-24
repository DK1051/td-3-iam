"""When the engine disables a person it also ends their sessions and revokes offline tokens."""

from fake_keycloak import seeded_fake
from support import FIXTURES, LATER, ROLES_MAP, TODAY, about, load_v2, make_plan

from lifecycle import engine
from lifecycle.__main__ import main
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
    result = engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    assert {target for _, target, _ in result.failures} == {"E4001", "E4002", "E4003"}
    leaver = fake.get_user_by_username("e4001")
    assert leaver["enabled"] is False and "disabled_on" not in leaver["attributes"]
    retry = make_plan(fake, feed, accounts, ROLES)
    assert [a.kind for a in about(retry, "E4001")] == ["disable_user"]   # planned again
    fake.revoke_offline_tokens = original
    result = engine.apply(retry, fake)
    assert result.failures == []
    assert "disabled_on" in fake.get_user_by_username("e4001")["attributes"]
    assert about(make_plan(fake, feed, accounts, ROLES), "E4001") == []


def test_a_failed_create_does_not_stop_the_leavers_being_switched_off(tmp_path, capsys):
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.give_access("e4001")
    original = fake.create_user

    def broken(username, **kwargs):
        raise KeycloakError("POST /admin/realms/maple-harbour/users -> HTTP 500")

    fake.create_user = broken
    plan = make_plan(fake, feed, accounts, ROLES)
    assert [a.kind for a in plan[:3]] == ["disable_user"] * 3      # leavers come first
    result = engine.apply(plan, fake)
    leaver = fake.get_user_by_username("e4001")
    assert leaver["enabled"] is False and leaver["attributes"]["disabled_on"] == "2026-10-16"
    assert fake.sessions[leaver["id"]] == 0 and fake.consents[leaver["id"]] == []
    assert len(result.failures) == 6 and all(kind == "create_user" for kind, _, _ in result.failures)
    assert result["disable_user"] == 3 and result["move_user"] == 3   # the rest still ran
    fake.create_user = original

    # The command line reports the failure and exits non-zero, after doing everything else.
    fake.create_user = broken
    code = main(["apply", "--feed", str(FIXTURES / "feed-v2.csv"), "--service-accounts",
                 str(FIXTURES / "service-accounts-v2.csv"), "--realm", "maple-harbour",
                 "--today", TODAY.isoformat(), "--reports-dir", str(tmp_path)],
                kc_factory=lambda realm: fake)
    captured = capsys.readouterr()
    assert code == 4
    assert "FAILED create_user E2001: POST /admin/realms/maple-harbour/users -> HTTP 500" \
        in captured.err
    assert "6 action(s) failed" in captured.err


def test_leaver_ordering_puts_every_switch_off_before_anything_new():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.create_client("svc-orphan-export", enabled=True,
                       attributes={"owner": "E1002", "purpose": "x", "expires_on": "2027-02-28"})
    kinds = [a.kind for a in make_plan(fake, feed, accounts, ROLES)]
    last_switch_off = max(i for i, k in enumerate(kinds) if k == "disable_user"
                          or k == "update_client")
    first_new = min(i for i, k in enumerate(kinds) if k in ("move_user", "create_user"))
    assert kinds[:3] == ["disable_user"] * 3 and kinds[3] == "update_client"
    assert last_switch_off < first_new or kinds.index("update_client") < first_new


def test_a_disabled_joiner_account_has_its_sessions_ended_without_a_marker_and_stays_quiet():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.seed_user("e2004", [], enabled=False)          # disabled by a person, no marker
    fake.give_access("e2004")
    plan = make_plan(fake, feed, accounts, ROLES)
    ended = about(plan, "E2004")
    assert [a.kind for a in ended] == ["end_sessions"]
    assert "needs review (sessions ended)" in ended[0].summary
    engine.apply(plan, fake)
    user = fake.get_user_by_username("e2004")
    assert user["enabled"] is False and "pending_start" not in user["attributes"]
    assert "end_user_sessions" in calls_for(fake, "e2004")
    # Nothing left to end: the next plan only repeats the plain SKIPPED line.
    again = about(make_plan(fake, feed, accounts, ROLES), "E2004")
    assert [a.kind for a in again] == ["skipped"]
    assert engine.apply(again, fake).total() == 0


def test_a_failed_logout_on_a_disabled_joiner_is_retried_next_run():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.seed_user("e2004", [], enabled=False)
    fake.give_access("e2004")
    original = fake.end_user_sessions

    def broken(user_id):
        raise KeycloakError("POST /admin/realms/maple-harbour/users/{id}/logout -> HTTP 500")

    fake.end_user_sessions = broken
    result = engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    assert ("end_sessions", "E2004") in [failure[:2] for failure in result.failures]
    retry = about(make_plan(fake, feed, accounts, ROLES), "E2004")
    assert [a.kind for a in retry] == ["end_sessions"]
    fake.end_user_sessions = original
    engine.apply(retry, fake)
    assert [a.kind for a in about(make_plan(fake, feed, accounts, ROLES), "E2004")] == ["skipped"]


def test_a_leaver_whose_account_is_off_but_whose_token_survives_is_cleaned_up():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)       # leavers disabled, marker set
    assert about(make_plan(fake, feed, accounts, ROLES), "E4001") == []
    fake.give_access("e4001", sessions=0, offline_clients=("app",))   # an offline token appears
    again = about(make_plan(fake, feed, accounts, ROLES), "E4001")
    assert [a.kind for a in again] == ["disable_user"]
    engine.apply(again, fake)
    assert about(make_plan(fake, feed, accounts, ROLES), "E4001") == []
