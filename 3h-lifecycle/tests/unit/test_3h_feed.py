"""Tests for lifecycle.feed: the good sample files and every kind of bad row."""

from datetime import date
from pathlib import Path

import pytest

from lifecycle.feed import FeedError, load_feed, load_service_accounts

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
HEADER = ("employee_id,action,first_name,last_name,email,department,job_title,manager_id,"
          "start_date,end_date,requested_by,approved_by,id_checked_live_video,"
          "references_contacted,education_verified\n")
GOOD_JOINER = ("E9001,joiner,Test,Person,test.person@mapleharbour.example,finance,Payments Officer,"
               "E1001,2026-11-02,,E1001,E1002,true,true,true\n")


def write_feed(tmp_path, *rows, header=HEADER):
    path = tmp_path / "feed.csv"
    path.write_text(header + "".join(rows), encoding="utf-8")
    return path


def test_good_sample_feed_has_6_joiners_3_movers_3_leavers():
    feed = load_feed(FIXTURES / "feed-v1.csv")
    assert (len(feed.joiners), len(feed.movers), len(feed.leavers)) == (6, 3, 3)
    assert feed.joiners[0].start_date == date(2026, 11, 2)
    assert feed.joiners[0].id_checked_live_video is True
    assert feed.leavers[0].end_date == date(2026, 10, 16)


def test_all_sample_emails_are_fictional():
    # Joiners and movers carry an email; every one must be on the fictional domain.
    feed = load_feed(FIXTURES / "feed-v1.csv")
    for person in [*feed.joiners, *feed.movers]:
        assert person.email.endswith("@mapleharbour.example")


def test_good_sample_service_accounts():
    accounts = load_service_accounts(FIXTURES / "service-accounts-v1.csv")
    assert [a.client_id for a in accounts] == [
        "svc-payments-batch", "svc-member-portal-api", "svc-report-export", "svc-legacy-sync"]
    assert accounts[3].expires_on == date(2026, 8, 31)


def only_bad_row(feed):
    """The feed has exactly one malformed row, nothing else was read from it; return it."""
    assert len(feed.bad_rows) == 1
    return feed.bad_rows[0]


def test_bad_boolean_becomes_a_bad_row_naming_the_row_and_column(tmp_path):
    bad = GOOD_JOINER.replace(",true,true,true", ",yes,true,true")
    feed = load_feed(write_feed(tmp_path, bad))
    row = only_bad_row(feed)
    assert (row.line, row.who) == (2, "E9001")
    assert "id_checked_live_video" in row.reason and "'yes'" in row.reason
    assert feed.joiners == []                          # the malformed row was not used


def test_capital_true_is_rejected(tmp_path):
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace("true,true,true", "true,true,True")))
    assert "education_verified" in only_bad_row(feed).reason


def test_joiner_with_blank_verification_column_is_rejected(tmp_path):
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace("true,true,true", "true,,true")))
    assert "references_contacted" in only_bad_row(feed).reason


def test_a_bad_row_does_not_stop_the_good_rows(tmp_path):
    bad = GOOD_JOINER.replace("E9001", "E9002").replace(",true,true,true", ",True,true,true")
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER, bad))
    assert [j.employee_id for j in feed.joiners] == ["E9001"]
    assert [b.who for b in feed.bad_rows] == ["E9002"]


def test_missing_column_is_still_a_structural_error(tmp_path):
    header = HEADER.replace("education_verified", "something_else")
    with pytest.raises(FeedError, match="missing column.*education_verified"):
        load_feed(write_feed(tmp_path, header=header))


def test_row_with_the_wrong_number_of_columns_is_a_structural_error(tmp_path):
    with pytest.raises(FeedError, match="row 2: wrong number of columns"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.rstrip("\n") + ",extra\n"))


def test_bad_date_is_rejected(tmp_path):
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace("2026-11-02", "02/11/2026")))
    assert "start_date" in only_bad_row(feed).reason and "YYYY-MM-DD" in only_bad_row(feed).reason
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace("2026-11-02", "2026-02-30")))
    assert "not a real calendar date" in only_bad_row(feed).reason


def test_unknown_action_and_empty_field_are_bad_rows_but_duplicates_stop_the_run(tmp_path):
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace(",joiner,", ",hired,")))
    assert "action" in only_bad_row(feed).reason
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace(",Person,", ",,")))
    assert "last_name" in only_bad_row(feed).reason and "must not be empty" in only_bad_row(feed).reason
    with pytest.raises(FeedError, match="more than once"):
        load_feed(write_feed(tmp_path, GOOD_JOINER, GOOD_JOINER))


def test_leaver_needs_an_end_date(tmp_path):
    leaver = "E9002,leaver,Gone,Person,gone.person@mapleharbour.example,finance,Teller,E1001,,,,,,,\n"
    row = only_bad_row(load_feed(write_feed(tmp_path, leaver)))
    assert (row.line, row.who) == (2, "E9002") and "end_date" in row.reason


def test_bad_service_account_row_is_listed_and_the_good_ones_are_kept(tmp_path):
    path = tmp_path / "sa.csv"
    path.write_text("client_id,owner,purpose,expires_on\nsvc-x,E1001,Test,never\n"
                    "svc-y,E1001,Fine,2027-01-01\n")
    accounts = load_service_accounts(path)
    assert [a.client_id for a in accounts] == ["svc-y"]
    assert [(b.line, b.who, b.source) for b in accounts.bad_rows] == [
        (2, "svc-x", "service accounts")]
    assert "expires_on" in accounts.bad_rows[0].reason


def test_unreadable_file_message_has_no_path_details(tmp_path):
    with pytest.raises(FeedError, match="cannot read nothing.csv: FileNotFoundError"):
        load_feed(tmp_path / "nothing.csv")


def test_employee_ids_that_differ_only_in_case_are_duplicates(tmp_path):
    with pytest.raises(FeedError, match="more than once"):
        load_feed(write_feed(tmp_path, GOOD_JOINER, GOOD_JOINER.replace("E9001", "e9001")))


@pytest.mark.parametrize("bad_id", ["E 9001", "E9001;rm", "E9001/../x", "E9\u00e91", "E9001?a=b"])
def test_employee_id_with_odd_characters_is_a_bad_row_with_unknown_who(tmp_path, bad_id):
    row = only_bad_row(load_feed(write_feed(tmp_path, GOOD_JOINER.replace("E9001", bad_id))))
    assert row.who == "?" and "employee_id" in row.reason


def test_manager_id_and_service_account_ids_are_checked_too(tmp_path):
    row = only_bad_row(load_feed(write_feed(
        tmp_path, GOOD_JOINER.replace(",E1001,2026", ",E 1001,2026"))))
    assert "manager_id" in row.reason
    path = tmp_path / "sa.csv"
    path.write_text("client_id,owner,purpose,expires_on\nsvc x,E1001,Test,2027-01-01\n")
    assert "client_id" in load_service_accounts(path).bad_rows[0].reason


def test_tab_or_line_break_inside_a_field_is_a_bad_row(tmp_path):
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace(",Test,", ',"Te\tst",')))
    assert "first_name" in only_bad_row(feed).reason and "control or invisible" in feed.bad_rows[0].reason
    feed = load_feed(write_feed(tmp_path, GOOD_JOINER.replace("Payments Officer", '"Payments\nOfficer"')))
    assert "job_title" in only_bad_row(feed).reason


@pytest.mark.parametrize("control", ["\x00", "\x1b", "\x7f", "\u202e", "\u200b"])
def test_any_control_character_in_a_field_is_a_bad_row(tmp_path, control):
    bad = GOOD_JOINER.replace(",Test,", f",Te{control}st,")
    assert "control or invisible" in only_bad_row(load_feed(write_feed(tmp_path, bad))).reason


def test_a_value_with_a_control_character_is_never_printed_raw(tmp_path):
    bad = GOOD_JOINER.replace("true,true,true", "tr\x1b[31mue,true,true")
    reason = only_bad_row(load_feed(write_feed(tmp_path, bad))).reason
    assert "\x1b" not in reason and "\\x1b" in reason
