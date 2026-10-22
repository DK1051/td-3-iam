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


def test_bad_boolean_names_the_row_and_column(tmp_path):
    bad = GOOD_JOINER.replace(",true,true,true", ",yes,true,true")
    with pytest.raises(FeedError) as error:
        load_feed(write_feed(tmp_path, bad))
    message = str(error.value)
    assert "row 2" in message and "id_checked_live_video" in message and "'yes'" in message


def test_capital_true_is_rejected(tmp_path):
    with pytest.raises(FeedError, match="education_verified"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.replace("true,true,true", "true,true,True")))


def test_joiner_with_blank_verification_column_is_rejected(tmp_path):
    with pytest.raises(FeedError, match="references_contacted"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.replace("true,true,true", "true,,true")))


def test_missing_column_is_named(tmp_path):
    header = HEADER.replace("education_verified", "something_else")
    with pytest.raises(FeedError, match="missing column.*education_verified"):
        load_feed(write_feed(tmp_path, header=header))


def test_bad_date_is_rejected(tmp_path):
    with pytest.raises(FeedError, match="start_date.*YYYY-MM-DD"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.replace("2026-11-02", "02/11/2026")))
    with pytest.raises(FeedError, match="not a real calendar date"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.replace("2026-11-02", "2026-02-30")))


def test_unknown_action_and_empty_field_and_duplicate_id(tmp_path):
    with pytest.raises(FeedError, match="action"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.replace(",joiner,", ",hired,")))
    with pytest.raises(FeedError, match="last_name.*must not be empty"):
        load_feed(write_feed(tmp_path, GOOD_JOINER.replace(",Person,", ",,")))
    with pytest.raises(FeedError, match="more than once"):
        load_feed(write_feed(tmp_path, GOOD_JOINER, GOOD_JOINER))


def test_leaver_needs_an_end_date(tmp_path):
    leaver = "E9002,leaver,Gone,Person,gone.person@mapleharbour.example,finance,Teller,E1001,,,,,,,\n"
    with pytest.raises(FeedError, match="row 2, column 'end_date'"):
        load_feed(write_feed(tmp_path, leaver))


def test_bad_service_account_date(tmp_path):
    path = tmp_path / "sa.csv"
    path.write_text("client_id,owner,purpose,expires_on\nsvc-x,E1001,Test,never\n")
    with pytest.raises(FeedError, match="row 2, column 'expires_on'"):
        load_service_accounts(path)


def test_unreadable_file_message_has_no_path_details(tmp_path):
    with pytest.raises(FeedError, match="cannot read nothing.csv: FileNotFoundError"):
        load_feed(tmp_path / "nothing.csv")
