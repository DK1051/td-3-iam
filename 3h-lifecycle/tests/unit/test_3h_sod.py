"""Separation of duties (SOD-1/2/3), warnings about managers who left, and the `sod` command."""

import pytest
from fake_keycloak import seeded_fake
from support import (
    FIXTURES,
    ROLES_MAP,
    SOD_RULES,
    TODAY,
    about,
    edited_feed,
    load_v2,
    make_plan,
)

from lifecycle import engine, sod
from lifecycle.__main__ import main
from lifecycle.feed import load_feed, load_service_accounts

ROLES = engine.load_roles_map(ROLES_MAP)


def warning_for(plan, employee_id):
    return next(a for a in about(plan, employee_id) if a.kind == "warning")


def violations_for(feed, accounts, fake):
    state = engine.read_state(fake, feed, accounts)
    projected = engine.projected_groups(feed, ROLES, state)
    return sod.evaluate(sod.load_rules(SOD_RULES), feed, accounts, projected, state.users,
                        directory_overlap=engine.directory_overlap(feed, state),
                        unlisted_clients=state.other_clients)


# ---- the rules file ------------------------------------------------------------------------

def test_rules_file_has_exactly_sod_1_2_3_with_all_fields():
    rules = sod.load_rules(SOD_RULES)
    assert [r.id for r in rules] == ["SOD-1", "SOD-2", "SOD-3"]
    assert all(r.title and r.plain_english and r.check for r in rules)


def test_rules_file_with_a_missing_or_extra_rule_is_refused(tmp_path):
    text = SOD_RULES.read_text(encoding="utf-8")
    broken = tmp_path / "rules.yaml"
    broken.write_text(text.replace("SOD-3", "SOD-4"), encoding="utf-8")
    with pytest.raises(sod.SodError, match="exactly"):
        sod.load_rules(broken)
    broken.write_text(text.replace("requester-not-approver", "made-up"), encoding="utf-8")
    with pytest.raises(sod.SodError, match="unknown check"):
        sod.load_rules(broken)


# ---- one violation per rule; the clean feed has none ---------------------------------------

def test_extended_feed_reports_exactly_one_violation_per_rule():
    feed, accounts = load_v2()
    found = [(v.rule_id, v.subject) for v in violations_for(feed, accounts, seeded_fake(ROLES))]
    assert found == [("SOD-1", "E2010"), ("SOD-2", "E3004"), ("SOD-3", "svc-orphan-export")]


def test_clean_feed_has_no_violations():
    feed = load_feed(FIXTURES.parent.parent / "hr" / "fixtures" / "clean-feed.csv")
    accounts = load_service_accounts(
        FIXTURES.parent.parent / "hr" / "fixtures" / "clean-service-accounts.csv")
    assert violations_for(feed, accounts, seeded_fake(ROLES)) == []


def test_sod_command_exit_codes_and_output(capsys):
    fake = seeded_fake(ROLES)
    base = ["sod", "--realm", "maple-harbour", "--today", TODAY.isoformat()]
    code = main([*base, "--feed", str(FIXTURES / "feed-v2.csv"),
                 "--service-accounts", str(FIXTURES / "service-accounts-v2.csv")],
                kc_factory=lambda realm: fake)
    out = capsys.readouterr().out
    assert code == 1
    assert "SOD-1  E2010" in out and "SOD-2  E3004" in out and "SOD-3  svc-orphan-export" in out
    assert "3 violation(s)" in out
    code = main([*base, "--feed", str(FIXTURES / "feed-v1.csv"),
                 "--service-accounts", str(FIXTURES / "service-accounts-v1.csv")],
                kc_factory=lambda realm: fake)
    assert code == 0 and "no violations" in capsys.readouterr().out
    assert fake.writes == []                       # the check only reads


# ---- SOD-2 fails closed --------------------------------------------------------------------

def test_mover_who_would_hold_both_payment_groups_is_skipped_and_reported():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    plan = make_plan(fake, feed, accounts, ROLES)
    assert [(a.kind, "SOD-2" in a.summary) for a in about(plan, "E3004")] == [("skipped", True)]
    user_id = fake.get_user_by_username("e3004")["id"]
    engine.apply(plan, fake)
    # Never half-applied: no write of any kind touched this person.
    assert not [w for w in fake.writes if user_id in w]
    assert fake.group_names_of("e3004") == {"finance", "payments-initiate"}
    assert fake.get_user_by_username("e3004")["attributes"]["job_title"] == "Payments Officer"
    # And nobody in the directory ended up in both groups.
    for user in fake.users:
        names = {fake.groups[g] for g in fake.memberships[user]}
        assert not {"payments-initiate", "payments-approve"} <= names


def test_a_joiner_who_would_hold_both_payment_groups_is_not_created():
    feed, accounts = load_v2()
    roles = engine.load_roles_map(ROLES_MAP)
    roles.departments["finance"] = ["finance", "payments-initiate"]   # makes E2006 conflict
    fake = seeded_fake(roles)
    plan = make_plan(fake, feed, accounts, roles)
    assert about(plan, "E2006")[0].kind == "skipped" and "SOD-2" in about(plan, "E2006")[0].summary
    engine.apply(plan, fake)
    assert fake.get_user_by_username("e2006") is None


# ---- SOD-3: service accounts need an active owner ------------------------------------------

def test_service_account_without_an_owner_is_never_created():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    plan = make_plan(fake, feed, accounts, ROLES)
    orphan = about(plan, "svc-orphan-export")
    assert [(a.kind, "SOD-3" in a.summary) for a in orphan] == [("blocked", True)]
    engine.apply(plan, fake)
    assert fake.get_client_by_client_id("svc-orphan-export") is None
    assert fake.get_client_by_client_id("svc-payments-batch")["enabled"] is True


def test_existing_enabled_ownerless_account_is_disabled_with_a_marker_and_stays_off():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.create_client("svc-orphan-export", enabled=True,
                       attributes={"owner": "E1002", "purpose": "x", "expires_on": "2027-02-28"})
    fake.writes.clear()
    plan = make_plan(fake, feed, accounts, ROLES)
    assert [a.kind for a in about(plan, "svc-orphan-export")] == ["update_client"]
    engine.apply(plan, fake)
    client = fake.get_client_by_client_id("svc-orphan-export")
    assert client["enabled"] is False
    assert client["attributes"]["disabled_by_engine"] == "SOD-3 no active owner"
    again = about(make_plan(fake, feed, accounts, ROLES), "svc-orphan-export")
    assert [a.kind for a in again] == ["skipped"]            # only a report, no change
    assert engine.apply(again, fake).total() == 0


def test_account_whose_owner_has_left_is_disabled_and_not_re_enabled_later(tmp_path):
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    # The owner of svc-payments-batch is now a leaver from the feed (E4001).
    path = tmp_path / "sa.csv"
    path.write_text((FIXTURES / "service-accounts-v2.csv").read_text().replace(
        "svc-payments-batch,E1001", "svc-payments-batch,E4001"))
    moved = load_service_accounts(path)
    plan = about(make_plan(fake, feed, moved, ROLES), "svc-payments-batch")
    assert [a.kind for a in plan] == ["update_client"] and "has left" in plan[0].summary
    engine.apply(plan, fake)
    assert fake.get_client_by_client_id("svc-payments-batch")["enabled"] is False
    # A new, healthy owner is named: the account is NOT switched back on by the engine.
    healthy = about(make_plan(fake, feed, accounts, ROLES), "svc-payments-batch")
    assert [a.kind for a in healthy] == ["skipped"]
    engine.apply(healthy, fake)
    assert fake.get_client_by_client_id("svc-payments-batch")["enabled"] is False


def test_owner_who_is_not_in_the_directory_or_is_disabled_counts_as_no_owner(tmp_path):
    feed, _accounts = load_v2()
    fake = seeded_fake(ROLES)
    path = tmp_path / "sa.csv"
    path.write_text("client_id,owner,purpose,expires_on\n"
                    "svc-ghost,E9999,Nobody home,2027-01-01\n"
                    "svc-off,E1002,Owner switched off,2027-01-01\n")
    fake.users[fake.get_user_by_username("e1002")["id"]]["enabled"] = False
    plan = make_plan(fake, feed, load_service_accounts(path), ROLES)
    assert "is not in the directory" in about(plan, "svc-ghost")[0].summary
    assert "is disabled" in about(plan, "svc-off")[0].summary


# ---- managers who left ---------------------------------------------------------------------

def test_staff_whose_manager_has_left_get_a_reassign_warning(tmp_path):
    feed = edited_feed(tmp_path, "feed-v1.csv",
                       ("priya.nambiar@mapleharbour.example,finance,Payments Officer,E1001",
                        "priya.nambiar@mapleharbour.example,finance,Payments Officer,E4001"))
    accounts = load_service_accounts(FIXTURES / "service-accounts-v1.csv")
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    assert warning_for(plan, "E2001").summary == "WARNING manager has left - reassign E2001 (manager E4001)"


def test_manager_who_is_disabled_or_missing_also_warns(tmp_path):
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.users[fake.get_user_by_username("e1002")["id"]]["enabled"] = False
    plan = make_plan(fake, feed, accounts, ROLES)
    assert warning_for(plan, "E2003").summary.startswith(
        "WARNING manager has left - reassign E2003")
    del fake.users[fake.get_user_by_username("e1001")["id"]]
    plan = make_plan(fake, feed, accounts, ROLES)
    assert "manager not found - reassign E2001" in warning_for(plan, "E2001").summary


def test_no_warnings_when_every_manager_is_active():
    feed, accounts = load_v2()
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    assert [a for a in plan if a.kind == "warning"] == []


# ---- the directory itself, not only the feed ------------------------------------------------

def test_sod2_also_finds_people_already_in_both_payment_groups_who_are_not_in_the_feed(capsys):
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.seed_user("e9001", ["payments-initiate", "payments-approve"])     # not in the feed
    found = [(v.rule_id, v.subject) for v in violations_for(feed, accounts, fake)]
    assert ("SOD-2", "e9001") in found
    code = main(["sod", "--feed", str(FIXTURES / "feed-v2.csv"), "--service-accounts",
                 str(FIXTURES / "service-accounts-v2.csv"), "--realm", "maple-harbour"],
                kc_factory=lambda realm: fake)
    assert code == 1 and "SOD-2  e9001: is in both" in capsys.readouterr().out


def test_a_feed_person_in_both_groups_who_the_feed_fixes_is_not_reported_twice():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    # E3002 holds initiate and the feed moves her to approve only: no violation either way.
    fake.memberships[fake.get_user_by_username("e3002")["id"]].add(
        fake._group_id("payments-approve"))
    found = [v.subject for v in violations_for(feed, accounts, fake)]
    assert "E3002" not in found and "e3002" not in found


def test_sod3_also_reports_service_account_clients_that_are_not_in_the_csv():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    attrs = {"purpose": "x", "expires_on": "2027-01-01"}
    fake.create_client("svc-nobody", enabled=True, attributes=attrs)               # no owner
    fake.create_client("svc-gone", enabled=True, attributes={**attrs, "owner": "E4001"})
    fake.create_client("svc-fine", enabled=True, attributes={**attrs, "owner": "E1001"})
    fake.create_client("admin-cli", enabled=True, attributes={})                   # built in
    found = {(v.rule_id, v.subject) for v in violations_for(feed, accounts, fake)}
    assert ("SOD-3", "svc-nobody") in found and ("SOD-3", "svc-gone") in found
    assert ("SOD-3", "svc-fine") not in found and ("SOD-3", "admin-cli") not in found
    # Reported only: the engine does not manage these, so it does not disable them.
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    assert fake.get_client_by_client_id("svc-nobody")["enabled"] is True


# ---- the manager warning also covers a manager who has not started yet ----------------------

def test_a_manager_who_has_not_started_yet_gets_a_warning(tmp_path):
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)       # E2003 now exists, pending
    new_feed = edited_feed(tmp_path, "feed-v2.csv",
                           ("priya.nambiar@mapleharbour.example,finance,Payments Officer,E1001",
                            "priya.nambiar@mapleharbour.example,finance,Payments Officer,E2003"))
    plan = make_plan(fake, new_feed, accounts, ROLES)
    assert "manager has not started yet - reassign E2001" in warning_for(plan, "E2001").summary


# ---- roles-map note --------------------------------------------------------------------------

def test_loading_a_map_with_a_payments_conflicting_pair_warns_but_works(tmp_path):
    with pytest.warns(engine.RolesMapWarning, match="payments-ops.*Finance Manager"):
        roles = engine.load_roles_map(ROLES_MAP)
    assert ("payments-ops", "Finance Manager") in roles.conflicting_pairs()
    quiet = tmp_path / "roles-map.yaml"
    quiet.write_text("departments: {finance: [finance]}\njob_titles: {Teller: []}\n"
                     "managed_groups: [finance]\n")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        engine.load_roles_map(quiet)
