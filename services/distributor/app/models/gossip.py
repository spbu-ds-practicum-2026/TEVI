from collections.abc import Collection
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


def _validate_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


_NonBlankString = Annotated[StrictStr, AfterValidator(_validate_non_blank)]


class NodeStatus(StrEnum):
    ALIVE = "alive"
    SUSPECT = "suspect"
    DEAD = "dead"


class NodeEntry(BaseModel):
    node_id: _NonBlankString
    addr: _NonBlankString
    status: NodeStatus
    incarnation: StrictInt = Field(ge=0)
    ready: StrictBool

    @field_validator("status", mode="before")
    @classmethod
    def validate_status_type(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("status must be a string")
        return value


class GossipRequest(BaseModel):
    sender: _NonBlankString
    table: list[NodeEntry] = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_table(self) -> Self:
        node_ids = {entry.node_id for entry in self.table}
        if len(node_ids) != len(self.table):
            raise ValueError("table must not contain duplicate node_id values")
        if self.sender not in node_ids:
            raise ValueError("table must contain an entry for sender")
        return self


class GossipResponse(BaseModel):
    table: list[NodeEntry] = Field(strict=True)
    is_in_active: StrictBool
    continuously_live: StrictBool


def validate_gossip_context(
    request: GossipRequest,
    expected_node_ids: Collection[str],
) -> None:
    actual = {entry.node_id for entry in request.table}
    expected = set(expected_node_ids)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"Gossip table from sender {request.sender!r} does not match cluster membership "
            f"(missing={missing}, unknown={unknown})"
        )
