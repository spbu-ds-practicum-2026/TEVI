import json

import pytest
from pydantic import ValidationError

from app.models.gossip import (
    GossipRequest,
    GossipResponse,
    NodeEntry,
    NodeStatus,
    validate_gossip_context,
)


@pytest.fixture
def node_data():
    return {
        "node_id": "n1",
        "addr": "node1:8080",
        "status": "alive",
        "incarnation": 1712345678901,
        "ready": True,
    }


@pytest.mark.parametrize("status", list(NodeStatus))
def test_status_is_parsed_from_dict_and_json(node_data, status):
    node_data["status"] = status.value

    assert NodeEntry.model_validate(node_data).status is status
    assert NodeEntry.model_validate_json(json.dumps(node_data)).status is status


@pytest.mark.parametrize("status", ["unknown", "ALIVE", 1, True, b"alive"])
def test_invalid_status_is_rejected(node_data, status):
    with pytest.raises(ValidationError, match="status"):
        NodeEntry.model_validate({**node_data, "status": status})


@pytest.mark.parametrize("field", ["node_id", "addr", "status", "incarnation", "ready"])
@pytest.mark.parametrize("omit", [True, False], ids=["missing", "null"])
def test_gossip_request_requires_complete_node_entries(node_data, field, omit):
    if omit:
        del node_data[field]
    else:
        node_data[field] = None

    with pytest.raises(ValidationError) as error:
        GossipRequest.model_validate({"sender": "n1", "table": [node_data]})

    assert error.value.errors()[0]["loc"] == ("table", 0, field)


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (GossipRequest, "sender"),
        (GossipRequest, "table"),
        (GossipResponse, "table"),
        (GossipResponse, "is_in_active"),
        (GossipResponse, "continuously_live"),
    ],
)
@pytest.mark.parametrize("omit", [True, False], ids=["missing", "null"])
def test_message_fields_are_required(node_data, model, field, omit):
    if model is GossipRequest:
        data = {"sender": "n1", "table": [node_data]}
    else:
        data = {"table": [node_data], "is_in_active": False, "continuously_live": True}
    if omit:
        del data[field]
    else:
        data[field] = None

    with pytest.raises(ValidationError) as error:
        model.model_validate(data)

    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_id", 1),
        ("node_id", b"n1"),
        ("addr", 8080),
        ("addr", b"node1"),
        ("incarnation", "1"),
        ("incarnation", 1.0),
        ("incarnation", True),
        ("ready", 1),
        ("ready", "true"),
    ],
)
def test_node_entry_rejects_implicit_type_conversion(node_data, field, value):
    with pytest.raises(ValidationError, match=field):
        NodeEntry.model_validate({**node_data, field: value})


@pytest.mark.parametrize("sender", ["", " \t\n", 1, b"n1"])
def test_invalid_sender_is_rejected(node_data, sender):
    with pytest.raises(ValidationError) as error:
        GossipRequest.model_validate({"sender": sender, "table": [node_data]})

    assert error.value.errors()[0]["loc"] == ("sender",)


@pytest.mark.parametrize("field", ["node_id", "addr"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_blank_node_strings_are_rejected(node_data, field, value):
    with pytest.raises(ValidationError, match=field):
        NodeEntry.model_validate({**node_data, field: value})


@pytest.mark.parametrize("addr", ["node1:8080", "http://node1:8080", "https://node1:8080", " node1 "])
def test_addresses_are_informational_and_strings_are_preserved(node_data, addr):
    node_data.update(node_id=" n1 ", addr=addr)
    request = GossipRequest.model_validate({"sender": " n1 ", "table": [node_data]})

    assert request.sender == " n1 "
    assert request.table[0].node_id == " n1 "
    assert request.table[0].addr == addr


def test_zero_incarnation_is_valid(node_data):
    assert NodeEntry.model_validate({**node_data, "incarnation": 0}).incarnation == 0


def test_negative_incarnation_is_rejected(node_data):
    with pytest.raises(ValidationError, match="incarnation"):
        NodeEntry.model_validate({**node_data, "incarnation": -1})


@pytest.mark.parametrize("table", [{}, "[]", ()])
def test_message_tables_must_be_lists(table):
    with pytest.raises(ValidationError, match="valid list"):
        GossipRequest.model_validate({"sender": "n1", "table": table})
    with pytest.raises(ValidationError, match="valid list"):
        GossipResponse.model_validate(
            {"table": table, "is_in_active": True, "continuously_live": False}
        )


@pytest.mark.parametrize("field", ["is_in_active", "continuously_live"])
@pytest.mark.parametrize("value", [0, "false"])
def test_response_flags_require_boolean_values(field, value):
    data = {"table": [], "is_in_active": True, "continuously_live": False}
    data[field] = value
    with pytest.raises(ValidationError, match=field):
        GossipResponse.model_validate(data)


def test_empty_request_table_is_rejected():
    with pytest.raises(ValidationError, match="at least 1 item"):
        GossipRequest.model_validate({"sender": "n1", "table": []})


def test_duplicate_node_ids_are_rejected(node_data):
    duplicate = {**node_data, "status": "dead"}
    with pytest.raises(ValidationError, match="duplicate node_id"):
        GossipRequest.model_validate({"sender": "n1", "table": [node_data, duplicate]})


def test_request_requires_an_entry_for_sender(node_data):
    with pytest.raises(ValidationError, match="entry for sender"):
        GossipRequest.model_validate({"sender": "n2", "table": [node_data]})


def test_partial_table_is_accepted_and_extra_fields_are_ignored(node_data):
    table = [{**node_data, "unknown_entry_field": True}]
    request = GossipRequest.model_validate({"sender": "n1", "table": table, "extra": 1})
    response = GossipResponse.model_validate(
        {"table": table, "is_in_active": True, "continuously_live": True, "extra": 1}
    )

    assert request.model_dump(mode="json") == {"sender": "n1", "table": [node_data]}
    assert response.model_dump(mode="json") == {
        "table": [node_data],
        "is_in_active": True,
        "continuously_live": True,
    }


def test_gossip_request_json_round_trip(node_data):
    peer = {**node_data, "node_id": "n2", "status": "suspect", "ready": False}
    data = {"sender": "n1", "table": [peer, node_data]}
    request = GossipRequest.model_validate_json(json.dumps(data))

    assert request.table[0].status is NodeStatus.SUSPECT
    assert json.loads(request.model_dump_json()) == data


@pytest.mark.parametrize("empty", [False, True], ids=["with-table", "empty-table"])
def test_gossip_response_json_round_trip(node_data, empty):
    data = {
        "table": [] if empty else [node_data],
        "is_in_active": True,
        "continuously_live": False,
    }
    response = GossipResponse.model_validate_json(json.dumps(data))

    assert json.loads(response.model_dump_json()) == data


@pytest.mark.parametrize("node_ids", [("n1", "n2", "n3"), ("n3", "n1", "n2")])
def test_gossip_context_accepts_full_table_in_any_order(node_data, node_ids):
    request = GossipRequest(
        sender="n1", table=[NodeEntry(**{**node_data, "node_id": node_id}) for node_id in node_ids]
    )
    expected = ["n1", "n2", "n3"]
    original_request = request.model_dump()

    assert validate_gossip_context(request, expected) is None
    assert request.model_dump() == original_request
    assert expected == ["n1", "n2", "n3"]


@pytest.mark.parametrize(
    ("sender", "node_ids", "missing", "unknown"),
    [
        ("n1", ("n1", "n3"), ["n2"], []),
        ("n1", ("n1",), ["n2", "n3"], []),
        ("n1", ("n1", "n2", "n3", "n9"), [], ["n9"]),
        ("n1", ("n9", "n1", "n8", "n3", "n2"), [], ["n8", "n9"]),
        ("n1", ("n9", "n1", "n8"), ["n2", "n3"], ["n8", "n9"]),
        ("n9", ("n1", "n2", "n3", "n9"), [], ["n9"]),
    ],
    ids=[
        "one-missing",
        "multiple-missing",
        "one-unknown",
        "multiple-unknown",
        "same-count-different-members",
        "unknown-sender",
    ],
)
def test_gossip_context_reports_membership_mismatch(node_data, sender, node_ids, missing, unknown):
    request = GossipRequest(
        sender=sender, table=[NodeEntry(**{**node_data, "node_id": node_id}) for node_id in node_ids]
    )
    expected = ["n3", "n2", "n1"]
    original_request = request.model_dump()

    with pytest.raises(ValueError) as error:
        validate_gossip_context(request, expected)

    assert str(error.value) == (
        f"Gossip table from sender {sender!r} does not match cluster membership "
        f"(missing={missing}, unknown={unknown})"
    )
    assert request.model_dump() == original_request
    assert expected == ["n3", "n2", "n1"]
