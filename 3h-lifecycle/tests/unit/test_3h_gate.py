"""The proofing gate: no account without all three identity checks, and no request approved by
the person who made it. Leaver rows are never blocked."""

from fake_keycloak import seeded_fake
from support import FIXTURES, ROLES_MAP, TODAY, about, edited_feed, load_v2, make_plan

from lifecycle import engine
from lifecycle.__main__ import main
from lifecycle.reports import write_blocked_report

ROLES = engine.load_roles_map(ROLES_MAP)


def test_each_single_false_check_blocks_the_joiner():
    feed, accounts = load_v2()
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    expected = {
        "E2007": "BLOCKED joiner E2007: proofing incomplete - id_checked_live_video",
        "E2008": "BLOCKED joiner E2008: proofing incomplete - references_contacted",
        "E2009": "BLOCKED joiner E2009: proofing incomplete - education_verified",
    }
    for employee_id, text in expected.items():
        assert [(a.kind, a.summary) for a in about(plan, employee_id)] == [("blocked", text)]


def test_blocked_joiners_are_never_created():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    for username in ("e2007", "e2008", "e2009", "e2010"):
        assert fake.get_user_by_username(username) is None, username
    assert fake.get_user_by_username("e2001") is not None   # the all-true control joiner exists


def test_all_true_joiner_is_created():
    feed, accounts = load_v2()
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    assert [a.kind for a in about(plan, "E2001")] == ["create_user"]


def test_requester_equal_to_approver_blocks_a_joiner_and_a_mover(tmp_path):
    feed, accounts = load_v2()
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    assert about(plan, "E2010")[0].summary == "BLOCKED joiner E2010: requester equals approver"
    mover_feed = edited_feed(tmp_path, "feed-v2.csv",
                             ("2026-10-19,,E1001,E1002,,,\nE3002", "2026-10-19,,E1001,E1001,,,\nE3002"))
    fake = seeded_fake(ROLES)
    plan = make_plan(fake, mover_feed, accounts, ROLES)
    assert about(plan, "E3001")[0].summary == "BLOCKED mover E3001: requester equals approver"
    engine.apply(plan, fake)
    assert fake.group_names_of("e3001") == {"member-services"}   # nothing changed for her


def test_a_row_can_be_blocked_for_two_reasons(tmp_path):
    feed = edited_feed(tmp_path, "feed-v2.csv",
                       ("2026-11-23,,E1001,E1002,false,", "2026-11-23,,E1001,E1001,false,"))
    _, accounts = load_v2()
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    assert about(plan, "E2007")[0].summary == (
        "BLOCKED joiner E2007: proofing incomplete - id_checked_live_video; "
        "requester equals approver")


def test_leaver_rows_are_never_blocked(tmp_path):
    # Same requester and approver on a leaver row: the account must still be disabled.
    feed = edited_feed(tmp_path, "feed-v2.csv",
                       ("2026-10-16,E1001,E1002,,,", "2026-10-16,E1001,E1001,,,"))
    _, accounts = load_v2()
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    assert fake.get_user_by_username("e4001")["enabled"] is False


def test_an_existing_account_of_a_blocked_joiner_is_left_alone():
    feed, accounts = load_v2()
    fake = seeded_fake(ROLES)
    fake.seed_user("e2007", [], enabled=True)
    plan = make_plan(fake, feed, accounts, ROLES)
    assert [a.kind for a in about(plan, "E2007")] == ["blocked"]


def test_blocked_report_lists_the_blocked_joiners_with_missing_checks(tmp_path):
    feed, accounts = load_v2()
    plan = make_plan(seeded_fake(ROLES), feed, accounts, ROLES)
    path = write_blocked_report(plan, tmp_path / "reports")
    text = path.read_text(encoding="utf-8")
    assert path.name == "blocked-joiners.md"
    assert "| E2007 | Yusuf Karimi | finance | Payments Officer | " \
           "proofing incomplete - id_checked_live_video |" in text
    assert "references_contacted" in text and "education_verified" in text
    assert "| E2010 | Chloe Gagnon |" in text and "requester equals approver" in text
    assert "E2001" not in text                      # a passing joiner is not listed
    assert "Every mover row passed the gate" in text


def test_apply_writes_the_report_but_dry_run_does_not(tmp_path, capsys):
    reports = tmp_path / "reports"
    args = ["--feed", str(FIXTURES / "feed-v2.csv"), "--service-accounts",
            str(FIXTURES / "service-accounts-v2.csv"), "--realm", "maple-harbour",
            "--today", TODAY.isoformat()]
    fake = seeded_fake(ROLES)
    assert main(["apply", "--dry-run", *args, "--reports-dir", str(reports)],
                kc_factory=lambda realm: fake) == 0
    assert not reports.exists()
    assert main(["apply", *args, "--reports-dir", str(reports)],
                kc_factory=lambda realm: fake) == 0
    out = capsys.readouterr().out
    assert "BLOCKED joiner E2008: proofing incomplete - references_contacted" in out
    assert (reports / "blocked-joiners.md").exists()
