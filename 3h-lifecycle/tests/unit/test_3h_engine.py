"""Tests for lifecycle.engine and the command line, using an in-memory fake (no network)."""

import inspect
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from fake_keycloak import FakeKeycloak

from lifecycle import engine
from lifecycle.__main__ import main
from lifecycle.feed import load_feed, load_service_accounts
from lifecycle.kc import KeycloakClient

ROOT = Path(__file__).resolve().parents[2]
FEED = ROOT / "tests" / "fixtures" / "feed-v1.csv"
ACCOUNTS = ROOT / "tests" / "fixtures" / "service-accounts-v1.csv"
ROLES_MAP = ROOT / "roles-map.yaml"
TODAY = date(2026, 10, 22)      # before every joiner's start date
LATER = date(2026, 11, 20)      # after every joiner's start date


@pytest.fixture
def roles_map():
    return engine.load_roles_map(ROLES_MAP)


@pytest.fixture
def feed():
    return load_feed(FEED)


@pytest.fixture
def accounts():
    return load_service_accounts(ACCOUNTS)


def new_fake(roles_map, *, with_staff):
    """A fake realm with the groups from roles-map.yaml; optionally the 6 pre-existing staff."""
    fake = FakeKeycloak(group_names=sorted(roles_map.managed_groups))
    if with_staff:
        # The 3 movers in their OLD groups and the 3 leavers (still enabled).
        fake.seed_user("e3001", ["member-services"],
                       attributes={"department": "member-services", "job_title": "Teller"})
        fake.seed_user("e3002", ["finance", "payments-initiate"],
                       attributes={"department": "finance", "job_title": "Payments Officer"})
        fake.seed_user("e3003", ["it", "helpdesk"],
                       attributes={"department": "it", "job_title": "Helpdesk Analyst"})
        fake.seed_user("e4001", ["finance", "payments-initiate"])
        fake.seed_user("e4002", ["member-services"])
        fake.seed_user("e4003", ["it", "privileged"])
    return fake


def make_plan(fake, feed, accounts, roles_map, today=TODAY):
    state = engine.read_state(fake, feed, accounts)
    return engine.plan(feed, accounts, roles_map, state, today)


def people_only(actions):
    """Drop service-account actions (svc-report-export expires on 2026-11-15, before LATER)."""
    return [a for a in actions if not a.kind.endswith("_client")]


def kinds(actions):
    return Counter(action.kind for action in actions)


# ---- AC1: the two scenarios ----------------------------------------------------------------

def test_plan_against_seeded_directory(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    actions = make_plan(fake, feed, accounts, roles_map)
    assert kinds(actions) == {"create_user": 6, "move_user": 3, "disable_user": 3,
                              "create_client": 4}
    assert fake.writes == []  # planning changed nothing


def test_plan_against_empty_directory(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=False)
    actions = make_plan(fake, feed, accounts, roles_map)
    assert kinds(actions) == {"create_user": 6, "create_client": 4, "skipped": 6}
    skipped = sorted(a.summary for a in actions if a.kind == "skipped")
    assert skipped == [f"SKIPPED unknown user {e}" for e in
                       ["E3001", "E3002", "E3003", "E4001", "E4002", "E4003"]]
    assert fake.writes == []


def test_cli_plan_prints_counts_and_changes_nothing(capsys, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    code = main(["plan", "--feed", str(FEED), "--service-accounts", str(ACCOUNTS),
                 "--realm", "maple-harbour", "--today", "2026-10-22"],
                kc_factory=lambda realm: fake)
    output = capsys.readouterr().out
    assert code == 0
    assert "Plan: 6 create_user, 3 move_user, 3 disable_user, 4 create_client" in output
    assert fake.writes == []


def test_cli_apply_dry_run_behaves_like_plan(capsys, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    code = main(["apply", "--dry-run", "--feed", str(FEED), "--service-accounts", str(ACCOUNTS),
                 "--realm", "maple-harbour", "--today", "2026-10-22"],
                kc_factory=lambda realm: fake)
    output = capsys.readouterr().out
    assert code == 0 and "Applied" not in output and fake.writes == []


def test_cli_apply_twice_second_run_changes_nothing(capsys, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    args = ["apply", "--feed", str(FEED), "--service-accounts", str(ACCOUNTS),
            "--realm", "maple-harbour", "--today", "2026-10-22"]
    assert main(args, kc_factory=lambda realm: fake) == 0
    first = capsys.readouterr().out
    assert ("Applied: create_user=6, move_user=3, disable_user=3, create_client=4") in first
    assert main(args, kc_factory=lambda realm: fake) == 0
    second = capsys.readouterr().out
    assert "Applied 0 changes." in second


def test_cli_reports_errors_without_a_traceback(capsys, tmp_path, roles_map):
    bad = tmp_path / "feed.csv"
    bad.write_text("employee_id\nE1\n")
    code = main(["plan", "--feed", str(bad), "--service-accounts", str(ACCOUNTS),
                 "--realm", "x"], kc_factory=lambda realm: new_fake(roles_map, with_staff=False))
    assert code == 2
    assert "missing column" in capsys.readouterr().err


# ---- each action type ----------------------------------------------------------------------

def test_joiner_with_a_past_start_date_is_created_enabled_with_groups_and_attributes(
        feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map, today=LATER), fake)
    user = fake.get_user_by_username("e2003")  # Kwame Boateng, IT Administrator
    assert user["enabled"] is True
    assert user["email"] == "kwame.boateng@mapleharbour.example"
    assert user["attributes"] == {"employee_id": "E2003", "department": "it",
                                  "job_title": "IT Administrator", "manager_id": "E1002"}
    assert fake.group_names_of("e2003") == {"it", "privileged"}
    assert fake.group_names_of("e2006") == {"finance", "payments-approve"}


def test_joiner_before_the_start_date_is_created_disabled_with_a_marker(feed, accounts,
                                                                       roles_map):
    fake = new_fake(roles_map, with_staff=True)
    actions = make_plan(fake, feed, accounts, roles_map)  # today is before every start date
    creates = [a for a in actions if a.kind == "create_user"]
    assert all("create DISABLED until 2026-11-" in a.summary for a in creates)
    engine.apply(actions, fake)
    user = fake.get_user_by_username("e2001")
    assert user["enabled"] is False
    assert user["attributes"]["pending_start"] == "2026-11-02"
    assert fake.group_names_of("e2001") == {"finance", "payments-initiate"}  # groups already set
    # Running again before the start date changes nothing.
    assert make_plan(fake, feed, accounts, roles_map) == []


def test_joiners_are_enabled_once_their_start_date_has_come_and_then_left_alone(
        feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    on_the_day = make_plan(fake, feed, accounts, roles_map, today=date(2026, 11, 2))
    assert sorted(a.target for a in on_the_day) == ["E2001", "E2002"]  # the two starting 11-02
    assert all(a.kind == "enable_user" and "starts today" in a.summary for a in on_the_day)
    after = people_only(make_plan(fake, feed, accounts, roles_map, today=LATER))
    assert Counter(a.kind for a in after) == {"enable_user": 6}
    assert any("started 2026-11-16" in a.summary for a in after)
    engine.apply(after, fake)
    for username in ("e2001", "e2002", "e2003", "e2004", "e2005", "e2006"):
        user = fake.get_user_by_username(username)
        assert user["enabled"] is True
        assert "pending_start" not in user["attributes"]
    assert people_only(make_plan(fake, feed, accounts, roles_map, today=LATER)) == []
    assert engine.apply(people_only(make_plan(fake, feed, accounts, roles_map, today=LATER)),
                        fake) == Counter()


def test_a_joiner_an_administrator_disabled_is_never_switched_back_on(feed, accounts,
                                                                      roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map, today=LATER), fake)
    fake.users[fake.get_user_by_username("e2004")["id"]]["enabled"] = False  # no marker
    actions = people_only(make_plan(fake, feed, accounts, roles_map, today=LATER))
    assert [(a.kind, a.target) for a in actions] == [("skipped", "E2004")]


def test_mover_stale_group_is_removed_and_new_groups_added(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    assert fake.group_names_of("e3001") == {"finance", "payments-initiate"}  # member-services gone
    assert fake.group_names_of("e3002") == {"finance", "payments-approve"}   # initiate gone
    assert fake.group_names_of("e3003") == {"it", "privileged"}              # helpdesk gone
    assert fake.get_user_by_username("e3002")["attributes"]["job_title"] == "Finance Manager"


def test_groups_outside_the_map_are_left_alone(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    fake.groups["g-extra"] = "book-club"
    fake.memberships[fake.get_user_by_username("e3001")["id"]].add("g-extra")
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    assert "book-club" in fake.group_names_of("e3001")


def test_leaver_is_disabled_not_deleted_and_groups_kept(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    leaver = fake.get_user_by_username("e4003")
    assert leaver is not None                       # the record is still there
    assert leaver["enabled"] is False
    assert leaver["attributes"]["disabled_on"] == "2026-10-21"
    assert fake.group_names_of("e4003") == {"it", "privileged"}  # kept as evidence
    assert fake.get_user_by_username("e4001")["attributes"]["disabled_on"] == "2026-10-16"


def test_leaver_with_a_future_end_date_is_disabled_now_and_says_so(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    actions = make_plan(fake, feed, accounts, roles_map, today=date(2026, 10, 12))
    summary = {a.target: a.summary for a in actions if a.kind == "disable_user"}
    assert "leaves on 2026-10-16" in summary["E4001"]       # end date still ahead
    assert "leaves on 2026-10-21" in summary["E4003"]
    assert "left 2026-10-09" in summary["E4002"]            # end date already past
    engine.apply(actions, fake)
    assert fake.get_user_by_username("e4001")["enabled"] is False   # disabled immediately


def test_nothing_in_the_engine_can_delete_a_user():
    # AC4: neither the real client nor the fake has any call that deletes a user (or anything).
    for cls in (KeycloakClient, FakeKeycloak):
        names = [name for name, _ in inspect.getmembers(cls, inspect.isfunction)]
        assert [name for name in names if "delete" in name] == []


def test_fake_and_real_client_have_the_same_calls():
    real = {name: inspect.signature(fn) for name, fn in inspect.getmembers(
        KeycloakClient, inspect.isfunction) if not name.startswith("_")}
    fake = {name: inspect.signature(fn) for name, fn in inspect.getmembers(
        FakeKeycloak, inspect.isfunction) if not name.startswith("_")}
    for name, signature in real.items():
        assert name in fake, f"fake is missing {name}"
        assert list(fake[name].parameters) == list(signature.parameters), name
    extra = set(fake) - set(real)
    assert extra <= {"seed_user", "group_names_of"}


def test_plan_flags_anyone_who_gains_the_privileged_group(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    by_target = {a.target: a for a in make_plan(fake, feed, accounts, roles_map)}
    assert by_target["E2003"].summary.endswith("PRIVILEGED")   # joiner, IT Administrator
    assert by_target["E3003"].summary.endswith("PRIVILEGED")   # mover, gains privileged
    assert "PRIVILEGED" not in by_target["E2001"].summary
    assert "PRIVILEGED" not in by_target["E3002"].summary


def test_master_realm_is_refused(capsys, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    code = main(["apply", "--feed", str(FEED), "--service-accounts", str(ACCOUNTS),
                 "--realm", "master"], kc_factory=lambda realm: fake)
    assert code == 2
    assert "--realm master is not allowed" in capsys.readouterr().err
    assert fake.writes == []


def test_unexpected_errors_show_only_the_type(capsys):
    def broken(realm):
        raise RuntimeError("text that might contain an object id")

    code = main(["plan", "--feed", str(FEED), "--service-accounts", str(ACCOUNTS),
                 "--realm", "maple-harbour"], kc_factory=broken)
    error = capsys.readouterr().err
    assert code == 3 and "unexpected RuntimeError" in error and "object id" not in error


# ---- service accounts ----------------------------------------------------------------------

def test_service_account_attributes_round_trip_and_flags(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    client = fake.get_client_by_client_id("svc-payments-batch")
    assert client["attributes"] == {"owner": "E1001", "purpose": "Nightly payments batch file export",
                                    "expires_on": "2027-06-30"}
    assert client["serviceAccountsEnabled"] is True
    assert client["publicClient"] is False
    assert client["standardFlowEnabled"] is False


def test_expired_service_account_is_created_disabled_with_reason(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    actions = make_plan(fake, feed, accounts, roles_map)
    legacy = next(a for a in actions if a.target == "svc-legacy-sync")
    assert legacy.kind == "create_client"
    assert "expired on 2026-08-31" in legacy.summary
    assert legacy.details["enabled"] is False
    engine.apply(actions, fake)
    assert fake.get_client_by_client_id("svc-legacy-sync")["enabled"] is False
    # healthy and expiring-soon accounts are enabled
    for client_id in ("svc-payments-batch", "svc-member-portal-api", "svc-report-export"):
        assert fake.get_client_by_client_id(client_id)["enabled"] is True
    assert make_plan(fake, feed, accounts, roles_map) == []  # and re-running stays quiet


def test_account_expiring_today_is_still_enabled(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    actions = make_plan(fake, feed, accounts, roles_map, today=date(2026, 11, 15))
    report = next(a for a in actions if a.target == "svc-report-export")
    assert report.details["enabled"] is True


def test_account_that_expires_later_gets_disabled(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    december = date(2026, 12, 1)
    # (joiners start in November, so only look at the service-account actions here)
    later = [a for a in make_plan(fake, feed, accounts, roles_map, today=december)
             if a.kind.endswith("_client")]
    assert [(a.kind, a.target) for a in later] == [("update_client", "svc-report-export")]
    assert "expired on 2026-11-15" in later[0].summary
    engine.apply(later, fake)
    assert fake.get_client_by_client_id("svc-report-export")["enabled"] is False
    assert [a for a in make_plan(fake, feed, accounts, roles_map, today=december)
            if a.kind.endswith("_client")] == []


# ---- idempotency and safety ----------------------------------------------------------------

def test_plan_after_apply_is_empty_and_second_apply_does_nothing(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    first = engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    assert sum(first.values()) == 16
    assert make_plan(fake, feed, accounts, roles_map) == []
    writes_before = len(fake.writes)
    assert engine.apply(make_plan(fake, feed, accounts, roles_map), fake) == Counter()
    assert len(fake.writes) == writes_before


def test_half_finished_run_is_repaired_by_the_next_plan(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    # Pretend a crash left a joiner without one of their groups.
    user_id = fake.get_user_by_username("e2001")["id"]
    fake.memberships[user_id].discard(fake._group_id("payments-initiate"))
    repair = make_plan(fake, feed, accounts, roles_map)
    assert [(a.kind, a.target) for a in repair] == [("move_user", "E2001")]
    engine.apply(repair, fake)
    assert make_plan(fake, feed, accounts, roles_map) == []


def test_disabled_account_for_a_joiner_is_reported_not_re_enabled(feed, accounts, roles_map):
    fake = new_fake(roles_map, with_staff=True)
    fake.seed_user("e2002", [], enabled=False)
    actions = make_plan(fake, feed, accounts, roles_map)
    assert any(a.kind == "skipped" and a.target == "E2002" for a in actions)
    engine.apply(actions, fake)
    assert fake.get_user_by_username("e2002")["enabled"] is False


def test_leaver_who_is_already_disabled_without_a_date_still_gets_the_date(feed, accounts,
                                                                          roles_map):
    fake = new_fake(roles_map, with_staff=True)
    fake.users[fake.get_user_by_username("e4002")["id"]]["enabled"] = False
    actions = make_plan(fake, feed, accounts, roles_map)
    assert any(a.kind == "disable_user" and a.target == "E4002" for a in actions)


# ---- bad input -----------------------------------------------------------------------------

def test_missing_group_stops_the_plan_with_a_clear_message(feed, accounts, roles_map):
    fake = FakeKeycloak(group_names=["finance"])  # the dev script was not run
    with pytest.raises(engine.EngineError, match="group.*not found.*keycloak-dev.sh"):
        make_plan(fake, feed, accounts, roles_map)


def test_unknown_job_title_names_the_employee(feed, accounts, roles_map):
    del roles_map.job_titles["Teller"]
    fake = new_fake(roles_map, with_staff=True)
    with pytest.raises(engine.EngineError, match="E2002.*job title 'Teller'"):
        make_plan(fake, feed, accounts, roles_map)


def test_roles_map_file_without_sections_is_rejected(tmp_path):
    path = tmp_path / "roles-map.yaml"
    path.write_text("departments: {}\n")
    with pytest.raises(engine.EngineError, match="job_titles"):
        engine.load_roles_map(path)


# ---- managed groups ------------------------------------------------------------------------

def test_a_renamed_group_is_removed_from_members_and_the_new_one_added(feed, accounts,
                                                                       roles_map):
    roles_map.job_titles["IT Administrator"] = ["admins"]       # privileged -> admins
    roles_map.managed_groups |= {"admins"}                      # privileged stays managed
    fake = new_fake(roles_map, with_staff=True)
    fake.groups["g-privileged"] = "privileged"
    fake.memberships[fake.get_user_by_username("e3003")["id"]].add("g-privileged")
    engine.apply(make_plan(fake, feed, accounts, roles_map), fake)
    assert fake.group_names_of("e3003") == {"it", "admins"}   # privileged and helpdesk removed


def test_every_group_the_map_hands_out_must_be_listed_as_managed(tmp_path):
    path = tmp_path / "roles-map.yaml"
    path.write_text("departments: {it: [it, extra]}\njob_titles: {}\nmanaged_groups: [it]\n")
    with pytest.raises(engine.EngineError, match="missing from managed_groups: extra"):
        engine.load_roles_map(path)
    path.write_text("departments: {it: [it]}\njob_titles: {}\n")
    with pytest.raises(engine.EngineError, match="managed_groups"):
        engine.load_roles_map(path)
