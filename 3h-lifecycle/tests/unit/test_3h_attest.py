"""Quarterly attestation files and service-account expiry flags (fixed "today", no clock)."""

from datetime import date

import pytest
from fake_keycloak import seeded_fake
from support import FIXTURES, ROLES_MAP, TODAY, edited_feed, load_v2, make_plan

from lifecycle import attest, engine, expiry
from lifecycle.__main__ import main
from lifecycle.feed import load_service_accounts

ROLES = engine.load_roles_map(ROLES_MAP)
BOXES = "[ ] keep  [ ] revoke"


def applied_directory(feed, accounts):
    fake = seeded_fake(ROLES)
    engine.apply(make_plan(fake, feed, accounts, ROLES), fake)
    return fake


def build(feed, accounts, fake, today=TODAY):
    state = engine.read_state(fake, feed, accounts)
    return attest.build_attestation(feed, accounts, state, "2026-Q4", today)


def table_rows(text):
    return [line for line in text.splitlines() if BOXES in line]


# ---- expiry -------------------------------------------------------------------------------

def test_expiry_flags_use_a_30_day_window_and_the_given_today():
    today = date(2026, 10, 22)
    assert expiry.expiry_flag(date(2026, 10, 21), today) == "EXPIRED"
    assert expiry.expiry_flag(date(2026, 10, 22), today) == "EXPIRES SOON"      # today
    assert expiry.expiry_flag(date(2026, 11, 21), today) == "EXPIRES SOON"      # 30th day
    assert expiry.expiry_flag(date(2026, 11, 22), today) is None                # 31st day


def test_one_soon_one_expired_two_healthy():
    accounts = load_service_accounts(FIXTURES / "service-accounts-v1.csv")
    flags = {a.client_id: expiry.expiry_flag(a.expires_on, TODAY) for a in accounts}
    assert flags == {"svc-payments-batch": None, "svc-member-portal-api": None,
                     "svc-report-export": "EXPIRES SOON", "svc-legacy-sync": "EXPIRED"}
    assert expiry.expiry_warnings(accounts, TODAY) == [
        "svc-report-export: EXPIRES SOON (expires_on 2026-11-15)",
        "svc-legacy-sync: EXPIRED (expires_on 2026-08-31)"]


def test_today_comes_from_the_option_then_the_environment_then_the_clock(monkeypatch):
    monkeypatch.setenv("LIFECYCLE_TODAY", "2026-12-25")
    assert expiry.resolve_today(date(2026, 1, 2)) == date(2026, 1, 2)
    assert expiry.resolve_today() == date(2026, 12, 25)
    monkeypatch.setenv("LIFECYCLE_TODAY", "yesterday")
    with pytest.raises(expiry.ExpiryError, match="YYYY-MM-DD"):
        expiry.resolve_today()
    monkeypatch.delenv("LIFECYCLE_TODAY")
    assert isinstance(expiry.resolve_today(), date)     # the real clock, only as a last resort


def test_plan_command_prints_the_expiry_warnings(capsys):
    fake = seeded_fake(ROLES)
    code = main(["plan", "--feed", str(FIXTURES / "feed-v1.csv"), "--service-accounts",
                 str(FIXTURES / "service-accounts-v1.csv"), "--realm", "maple-harbour", "--today", "2026-10-22"],
                kc_factory=lambda realm: fake)
    assert code == 0
    out = capsys.readouterr().out
    assert "Expiry warnings:" in out
    assert "svc-report-export: EXPIRES SOON" in out and "svc-legacy-sync: EXPIRED" in out


# ---- attestation files ---------------------------------------------------------------------

def test_one_file_per_manager_plus_unassigned():
    feed, accounts = load_v2()
    files = build(feed, accounts, applied_directory(feed, accounts))
    assert set(files) == {"E1001.md", "E1002.md", "unassigned.md"}


def test_every_report_and_owned_account_has_a_row_with_the_keep_and_revoke_boxes():
    feed, accounts = load_v2()
    files = build(feed, accounts, applied_directory(feed, accounts))
    for manager_id in ("E1001", "E1002"):
        reports = [p for p in [*feed.joiners, *feed.movers, *feed.leavers]
                   if p.manager_id == manager_id]
        owned = [a for a in accounts if a.owner == manager_id]
        assert len(table_rows(files[f"{manager_id}.md"])) == len(reports) + len(owned)
        assert all(line.count("[ ] keep") == 1 and line.count("[ ] revoke") == 1
                   for line in table_rows(files[f"{manager_id}.md"]))


def test_rows_show_job_title_groups_and_enabled_state_including_disabled_people():
    feed, accounts = load_v2()
    text = build(feed, accounts, applied_directory(feed, accounts))["E1001.md"]
    row = {line.split("|")[1].strip(): line for line in table_rows(text)}
    assert "| Payments Officer | finance, payments-initiate | no (starts 2026-11-02) |" in row["E2001"]
    assert "no (disabled 2026-10-16)" in row["E4001"]                  # leaver: shown as disabled
    assert "finance, payments-initiate" in row["E4001"]                # groups kept as evidence
    assert "| no account |" in row["E2007"]                            # blocked joiner
    assert "Elena Marchetti" in text.splitlines()[0] or "(E1001)" in text.splitlines()[0]
    assert "- Quarter: 2026-Q4" in text and "- Generated: 2026-10-22" in text


def test_expiry_flags_appear_in_the_owners_file_and_healthy_accounts_have_none():
    feed, accounts = load_v2()
    files = build(feed, accounts, applied_directory(feed, accounts))
    owner_e1001 = files["E1001.md"]
    row = {line.split("|")[1].strip(): line for line in table_rows(owner_e1001)}
    assert "EXPIRES SOON" in row["svc-report-export"]
    assert "svc-report-export: EXPIRES SOON (expires_on 2026-11-15)" in owner_e1001.split(
        "## Warnings")[1]
    assert "EXPIRES" not in row["svc-payments-batch"] and "EXPIRED" not in row["svc-payments-batch"]
    owner_e1002 = files["E1002.md"]
    assert "svc-legacy-sync: EXPIRED (expires_on 2026-08-31)" in owner_e1002.split("## Warnings")[1]
    assert "disabled, EXPIRED" in owner_e1002


def test_an_ownerless_service_account_is_in_no_managers_file_only_in_unassigned():
    feed, accounts = load_v2()
    files = build(feed, accounts, applied_directory(feed, accounts))
    assert "svc-orphan-export" not in files["E1001.md"] + files["E1002.md"]
    assert "svc-orphan-export" in files["unassigned.md"] and "SOD-3" in files["unassigned.md"]


def test_staff_of_a_manager_who_left_go_to_unassigned_with_a_reassign_line(tmp_path):
    feed = edited_feed(tmp_path, "feed-v2.csv",
                       ("priya.nambiar@mapleharbour.example,finance,Payments Officer,E1001",
                        "priya.nambiar@mapleharbour.example,finance,Payments Officer,E4001"))
    _, accounts = load_v2()
    files = build(feed, accounts, applied_directory(feed, accounts))
    assert "manager has left - reassign E2001" in files["unassigned.md"]
    assert "E4001.md" not in files                       # nobody attests through a leaver
    assert "E2001" not in files["E1001.md"]


def test_unassigned_file_is_written_even_when_nothing_is_unassigned():
    feed, _ = load_v2()
    accounts = load_service_accounts(FIXTURES / "service-accounts-v1.csv")
    files = build(feed, accounts, applied_directory(feed, accounts))
    assert files["unassigned.md"].count("None.") == 2


def test_attest_command_writes_files_and_removes_only_stale_attestation_files(tmp_path, capsys):
    out = tmp_path / "attestation"
    out.mkdir()
    (out / "E9999.md").write_text("# Access attestation - old (E9999)\n")
    (out / "notes.md").write_text("# My own notes\n")
    feed, accounts = load_v2()
    fake = applied_directory(feed, accounts)
    code = main(["attest", "--feed", str(FIXTURES / "feed-v2.csv"), "--service-accounts",
                 str(FIXTURES / "service-accounts-v2.csv"), "--realm", "maple-harbour",
                 "--today", "2026-10-22", "--quarter", "2026-Q4", "--out", str(out)],
                kc_factory=lambda realm: fake)
    assert code == 0
    assert sorted(p.name for p in out.glob("*.md")) == ["E1001.md", "E1002.md", "notes.md",
                                                        "unassigned.md"]
    printed = capsys.readouterr().out
    assert "Wrote 3 attestation file(s)" in printed and "Expiry warnings:" in printed


def test_a_malformed_quarter_is_refused(tmp_path, capsys):
    fake = seeded_fake(ROLES)
    code = main(["attest", "--feed", str(FIXTURES / "feed-v1.csv"), "--service-accounts",
                 str(FIXTURES / "service-accounts-v1.csv"), "--realm", "maple-harbour",
                 "--quarter", "Q4-2026", "--out", str(tmp_path)], kc_factory=lambda realm: fake)
    assert code == 2 and "2026-Q4" in capsys.readouterr().err
