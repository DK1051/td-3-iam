"""Unit tests for scripts/approve.py, using 3H's in-memory Keycloak fake (no network).

The rule these tests protect: when approve.py refuses (exit 2-5) the directory and the proposal
file are exactly as they were (exit 7 if the directory cannot be read at all); a Keycloak failure
part-way is visible as status "partial" (exit 6).
"""

import json
import uuid

import pytest
from fake_keycloak import seeded_fake
from passport_support import PASSPORT, audit_lines, jwks_of, load_approve, make_env, mint, new_key

import server
from lifecycle import engine, sod
from lifecycle.kc import KeycloakError

approve = load_approve()

ROLES_MAP = PASSPORT.parent / "3h-lifecycle" / "roles-map.yaml"
MANAGER_KEY = new_key()


@pytest.fixture
def env(tmp_path):
    return make_env(tmp_path)


@pytest.fixture
def fake():
    fake = seeded_fake(engine.load_roles_map(ROLES_MAP))
    fake.seed_user("e2005")                          # a joiner who exists but holds nothing yet
    fake.seed_user("e2001", enabled=False)           # exists but disabled
    return fake


def manager_token(env, *, username="manager.demo", roles=("manager",), **kwargs):
    extra = {"realm_access": {"roles": list(roles)}}
    if username is not None:
        extra["preferred_username"] = username
    return mint(env, key=MANAGER_KEY, aud="approve-cli", azp="approve-cli", sub="manager-sub-1",
                scope="openid profile", extra=extra, **kwargs)


def make_proposal(env, *, request_id="REQ-001", requester="e3001", groups=("payments-initiate",),
                  status="pending", **overrides):
    proposal_id = str(uuid.uuid4())
    proposal = {
        "id": proposal_id, "request_id": request_id, "requester": requester,
        "proposed_groups": list(groups), "justification": "Because.",
        "created_at": "2026-11-01T00:00:00Z", "created_by": "agent-access-assistant",
        "status": status, **overrides,
    }
    env.settings.proposals_dir.mkdir(parents=True, exist_ok=True)
    path = env.settings.proposals_dir / f"{proposal_id}.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")
    return proposal_id, path


def run(env, fake, proposal_id, token, *, allowed=None):
    verifier = server.make_verifier(
        env.settings, audience="approve-cli",
        jwks_source=lambda: jwks_of(("manager-key", MANAGER_KEY)))
    return approve.run(proposal_id, token=token, settings=env.settings, verifier=verifier,
                       kc=fake, allowed_groups=allowed or server.managed_groups())


def token_with_kid(env, **kwargs):
    return manager_token(env, kid="manager-key", **kwargs)


def assert_untouched(fake, path, before):
    assert fake.writes == []
    assert path.read_text("utf-8") == before


def refused(env, fake, expected_code, proposal_id, path, token):
    before = path.read_text("utf-8") if path.exists() else None
    memberships = {uid: set(groups) for uid, groups in fake.memberships.items()}
    assert run(env, fake, proposal_id, token) == expected_code
    assert fake.writes == []
    assert fake.memberships == memberships
    if before is not None:
        assert path.read_text("utf-8") == before
    lines = audit_lines(env)
    assert lines and lines[-1]["decision"] == "deny"
    return lines[-1]


def test_it_reuses_the_3h_sod_module_and_client():
    assert approve.sod is sod
    from lifecycle.kc import KeycloakClient
    assert approve.KeycloakClient is KeycloakClient


# ---- exit 2 / 3: the token -----------------------------------------------------------------

def test_missing_token_exits_2_and_changes_nothing(env, fake):
    proposal_id, path = make_proposal(env)
    for token in (None, ""):
        line = refused(env, fake, approve.EXIT_NO_TOKEN, proposal_id, path, token)
        assert line["tool"] == "approve.py" and "MANAGER_TOKEN" in line["reason"]


def test_invalid_token_exits_3(env, fake):
    proposal_id, path = make_proposal(env)
    roles = {"realm_access": {"roles": ["manager"]}, "preferred_username": "manager.demo"}
    bad_tokens = [
        # the assistant's audience is not enough: approve.py wants "approve-cli"
        mint(env, key=MANAGER_KEY, kid="manager-key", aud="agent-passport", extra=roles),
        manager_token(env, kid="manager-key", expires_in=-5),
        manager_token(env, kid="manager-key", typ="ID"),
        manager_token(env, kid="manager-key", alg="HS256"),
        manager_token(env, kid="signed-by-an-unknown-key"),
    ]
    for token in bad_tokens:
        refused(env, fake, approve.EXIT_DENIED, proposal_id, path, token)


def test_garbage_token_exits_3(env, fake):
    proposal_id, path = make_proposal(env)
    refused(env, fake, approve.EXIT_DENIED, proposal_id, path, "not.a.jwt")


def test_token_without_manager_role_exits_3(env, fake):
    proposal_id, path = make_proposal(env)
    for roles in ((), ("helpdesk",), ("managers",)):
        line = refused(env, fake, approve.EXIT_DENIED, proposal_id, path,
                       token_with_kid(env, roles=roles))
        assert line["reason"] == "token lacks the manager role"


def test_token_without_realm_access_claim_exits_3(env, fake):
    proposal_id, path = make_proposal(env)
    token = mint(env, key=MANAGER_KEY, kid="manager-key", aud="approve-cli",
                 extra={"preferred_username": "manager.demo"})
    refused(env, fake, approve.EXIT_DENIED, proposal_id, path, token)


# ---- exit 4: the proposal ------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "not-a-uuid", "{" + str(uuid.uuid4()) + "}",
                                    "urn:uuid:" + str(uuid.uuid4()), ""])
def test_proposal_id_must_be_a_plain_uuid(env, fake, bad_id):
    _, path = make_proposal(env)
    refused(env, fake, approve.EXIT_BAD_PROPOSAL, bad_id, path, token_with_kid(env))


def test_unknown_proposal_exits_4(env, fake):
    _, path = make_proposal(env)
    refused(env, fake, approve.EXIT_BAD_PROPOSAL, str(uuid.uuid4()), path, token_with_kid(env))


@pytest.mark.parametrize("status", ["approved", "partial", "rejected"])
def test_only_pending_proposals_can_be_approved(env, fake, status):
    proposal_id, path = make_proposal(env, status=status)
    refused(env, fake, approve.EXIT_BAD_PROPOSAL, proposal_id, path, token_with_kid(env))


@pytest.mark.parametrize("overrides", [
    {"requester": "e3003"},                                   # redirected to someone else
    {"groups": ("payments-initiate", "privileged")},          # more than the request asked for
    {"groups": ("privileged",)},
    {"request_id": "REQ-999"},                                # request not in pending.json
    {"groups": ()},
])
def test_proposal_must_match_pending_json(env, fake, overrides):
    kwargs = {"requester": "e3001", "groups": ("payments-initiate",), **overrides}
    proposal_id, path = make_proposal(env, **kwargs)
    refused(env, fake, approve.EXIT_BAD_PROPOSAL, proposal_id, path, token_with_kid(env))


def test_proposal_file_must_carry_its_own_id(env, fake):
    proposal_id, path = make_proposal(env, id=str(uuid.uuid4()))
    refused(env, fake, approve.EXIT_BAD_PROPOSAL, proposal_id, path, token_with_kid(env))


# ---- exit 5: separation of duties ----------------------------------------------------------

def test_sod2_payments_pair_is_refused(env, fake):
    # REQ-003: e3002 already holds payments-initiate and asks for payments-approve.
    proposal_id, path = make_proposal(env, request_id="REQ-003", requester="e3002",
                                      groups=("payments-approve",))
    line = refused(env, fake, approve.EXIT_SOD, proposal_id, path, token_with_kid(env))
    assert line["reason"].startswith("SOD-2")
    assert fake.group_names_of("e3002") == {"finance", "payments-initiate"}


def test_approver_equal_to_requester_is_refused(env, fake):
    proposal_id, path = make_proposal(env)               # requester e3001
    line = refused(env, fake, approve.EXIT_SOD, proposal_id, path,
                   token_with_kid(env, username="E3001"))   # case does not matter
    assert line["reason"].startswith("SOD-1")


def test_token_without_a_username_is_refused(env, fake):
    proposal_id, path = make_proposal(env)
    refused(env, fake, approve.EXIT_SOD, proposal_id, path, token_with_kid(env, username=None))


def test_missing_or_disabled_requester_is_refused(env, fake):
    for request_id, requester, groups in (("REQ-004", "e2001", ("finance",)),          # disabled
                                          ("REQ-005", "e2002", ("member-services",))):  # not in directory
        proposal_id, path = make_proposal(env, request_id=request_id, requester=requester,
                                          groups=groups)
        refused(env, fake, approve.EXIT_SOD, proposal_id, path, token_with_kid(env))


def test_group_outside_the_3h_managed_list_is_refused(env, fake):
    proposal_id, path = make_proposal(env)
    before = path.read_text("utf-8")
    allowed = server.managed_groups() - {"payments-initiate"}
    assert run(env, fake, proposal_id, token_with_kid(env), allowed=allowed) == approve.EXIT_SOD
    assert_untouched(fake, path, before)


def test_group_missing_from_the_directory_is_refused(env, fake):
    gid = next(g for g, name in fake.groups.items() if name == "payments-initiate")
    del fake.groups[gid]
    proposal_id, path = make_proposal(env)
    refused(env, fake, approve.EXIT_SOD, proposal_id, path, token_with_kid(env))


# ---- success, double approval, partial ----------------------------------------------------

def test_success_adds_the_groups_marks_approved_and_audits(env, fake):
    proposal_id, path = make_proposal(env)
    token = token_with_kid(env)
    assert run(env, fake, proposal_id, token) == approve.EXIT_OK
    assert fake.group_names_of("e3001") == {"member-services", "payments-initiate"}
    assert [w[0] for w in fake.writes] == ["add_user_to_group"]
    proposal = json.loads(path.read_text("utf-8"))
    assert proposal["status"] == "approved"
    assert proposal["approved_by"] == {"subject": "manager-sub-1", "username": "manager.demo"}
    assert proposal["approved_at"].endswith("Z") and proposal["applied_groups"] == ["payments-initiate"]
    lines = audit_lines(env)
    assert [(line["tool"], line["decision"], line["reason"]) for line in lines] == [
        ("approve.py", "allow", "added to group payments-initiate"),
        ("approve.py", "allow", "proposal approved")]
    assert lines[0]["caller"] == {"client_id": "approve-cli", "subject": "manager-sub-1"}
    assert token not in env.settings.audit_file.read_text("utf-8")


def test_double_approval_is_refused(env, fake):
    proposal_id, path = make_proposal(env)
    assert run(env, fake, proposal_id, token_with_kid(env)) == approve.EXIT_OK
    writes = list(fake.writes)
    assert run(env, fake, proposal_id, token_with_kid(env)) == approve.EXIT_BAD_PROPOSAL
    assert fake.writes == writes
    assert json.loads(path.read_text("utf-8"))["status"] == "approved"


def test_groups_the_requester_already_has_are_skipped(env, fake):
    fake.memberships[fake.get_user_by_username("e2005")["id"]].add(
        next(g for g, name in fake.groups.items() if name == "it"))
    proposal_id, _ = make_proposal(env, request_id="REQ-007", requester="e2005",
                                   groups=("it", "helpdesk"))
    assert run(env, fake, proposal_id, token_with_kid(env)) == approve.EXIT_OK
    assert [w[0] for w in fake.writes] == ["add_user_to_group"]     # only helpdesk was added
    assert fake.group_names_of("e2005") == {"it", "helpdesk"}


def test_keycloak_error_part_way_marks_the_proposal_partial(env, fake):
    proposal_id, path = make_proposal(env, request_id="REQ-007", requester="e2005",
                                      groups=("it", "helpdesk"))
    real_add, calls = fake.add_user_to_group, []

    def flaky(user_id, group_id):
        calls.append(group_id)
        if len(calls) == 2:
            raise KeycloakError("PUT /admin/realms/maple-harbour/users/{id}/groups/{id} -> HTTP 500")
        real_add(user_id, group_id)

    fake.add_user_to_group = flaky
    assert run(env, fake, proposal_id, token_with_kid(env)) == approve.EXIT_PARTIAL
    assert fake.group_names_of("e2005") == {"it"}                   # the first group stays added
    proposal = json.loads(path.read_text("utf-8"))
    assert proposal["status"] == "partial" and proposal["applied_groups"] == ["it"]
    assert [(line["decision"], line["reason"]) for line in audit_lines(env)] == [
        ("allow", "added to group it"), ("deny", "keycloak error while adding helpdesk")]


def test_directory_unreachable_before_any_change_exits_7_and_stays_pending(env, fake):
    proposal_id, path = make_proposal(env)
    before = path.read_text("utf-8")

    def broken(username):
        raise KeycloakError("GET /admin/realms/maple-harbour/users -> HTTP 503")

    fake.get_user_by_username = broken
    assert run(env, fake, proposal_id, token_with_kid(env)) == approve.EXIT_DIRECTORY == 7
    assert_untouched(fake, path, before)
    assert audit_lines(env)[-1]["reason"] == "directory unreachable"


def test_main_without_a_proposal_id_prints_usage(capsys):
    assert approve.main(["approve.py"]) == approve.EXIT_BAD_PROPOSAL
    assert "usage" in capsys.readouterr().err
