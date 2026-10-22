"""An in-memory stand-in for lifecycle.kc.KeycloakClient, so unit tests need no network.

It has the same method names and arguments as the real client (a test checks this), keeps
everything in dictionaries, and records every call that changes something in `writes`.
There is no delete-user method, exactly like the real client.
"""

import itertools


class FakeKeycloak:
    def __init__(self, group_names=()):
        self._ids = itertools.count(1)
        self.groups: dict[str, str] = {}          # group id -> group name
        self.users: dict[str, dict] = {}          # user id -> user record
        self.memberships: dict[str, set[str]] = {}  # user id -> set of group ids
        self.clients: dict[str, dict] = {}        # client uuid -> client record
        self.writes: list[tuple] = []
        for name in group_names:
            self.groups[f"g-{next(self._ids)}"] = name

    # ---- helpers for tests (not part of the real client's interface) ------------------------

    def seed_user(self, username, groups=(), enabled=True, attributes=None):
        user_id = f"u-{next(self._ids)}"
        self.users[user_id] = {
            "id": user_id, "username": username, "email": f"{username}@mapleharbour.example",
            "firstName": "Test", "lastName": "User", "enabled": enabled,
            "attributes": dict(attributes or {}),
        }
        self.memberships[user_id] = {self._group_id(name) for name in groups}
        return user_id

    def group_names_of(self, username) -> set[str]:
        user = self.get_user_by_username(username)
        return {self.groups[gid] for gid in self.memberships[user["id"]]}

    def _group_id(self, name):
        return next(gid for gid, group_name in self.groups.items() if group_name == name)

    # ---- the same calls as KeycloakClient ----------------------------------------------------

    def get_user_by_username(self, username):
        for user in self.users.values():
            if user["username"] == username.lower():
                return {**user, "attributes": dict(user["attributes"])}
        return None

    def create_user(self, username, *, email, first_name, last_name, enabled=True,
                    attributes=None):
        self.writes.append(("create_user", username))
        user_id = f"u-{next(self._ids)}"
        self.users[user_id] = {
            "id": user_id, "username": username, "email": email, "firstName": first_name,
            "lastName": last_name, "enabled": enabled, "attributes": dict(attributes or {}),
        }
        self.memberships[user_id] = set()
        return user_id

    def update_user(self, user_id, *, enabled=None, attributes=None, remove_attributes=None):
        self.writes.append(("update_user", user_id))
        if enabled is not None:
            self.users[user_id]["enabled"] = enabled
        self.users[user_id]["attributes"].update(attributes or {})
        for name in remove_attributes or []:
            self.users[user_id]["attributes"].pop(name, None)

    def list_groups(self):
        return [{"id": gid, "name": name} for gid, name in self.groups.items()]

    def user_groups(self, user_id):
        return [{"id": gid, "name": self.groups[gid]} for gid in self.memberships[user_id]]

    def add_user_to_group(self, user_id, group_id):
        self.writes.append(("add_user_to_group", user_id, group_id))
        self.memberships[user_id].add(group_id)

    def remove_user_from_group(self, user_id, group_id):
        self.writes.append(("remove_user_from_group", user_id, group_id))
        self.memberships[user_id].discard(group_id)

    def get_client_by_client_id(self, client_id):
        for client in self.clients.values():
            if client["clientId"] == client_id:
                return {**client, "attributes": dict(client["attributes"])}
        return None

    def create_client(self, client_id, *, enabled, attributes):
        self.writes.append(("create_client", client_id))
        uuid = f"c-{next(self._ids)}"
        self.clients[uuid] = {
            "id": uuid, "clientId": client_id, "enabled": enabled,
            "serviceAccountsEnabled": True, "publicClient": False, "standardFlowEnabled": False,
            "attributes": dict(attributes),
        }
        return uuid

    def update_client(self, client_uuid, *, enabled=None, attributes=None):
        self.writes.append(("update_client", client_uuid))
        if enabled is not None:
            self.clients[client_uuid]["enabled"] = enabled
        self.clients[client_uuid]["attributes"].update(attributes or {})
