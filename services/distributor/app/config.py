import os
import re
from pathlib import Path
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

_http_url = TypeAdapter(AnyHttpUrl)


def validate_node_id(node_id: str) -> str:
    if not node_id.strip():
        raise ValueError("node ID must not be blank")
    return node_id


def validate_node_address(address: str) -> str:
    # Pydantic can normalize missing or extra slashes, so require an authority first.
    if not re.fullmatch(r"https?://[^/?#\\\s][^\\\s]*", address, re.IGNORECASE):
        raise ValueError("node address must be an absolute HTTP or HTTPS URL")
    _http_url.validate_python(address)
    return address


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)

    n0: int = Field(gt=0)
    nodes: dict[
        Annotated[str, AfterValidator(validate_node_id)],
        Annotated[str, AfterValidator(validate_node_address)],
    ] = Field(min_length=1)
    t_req: float = Field(gt=0, allow_inf_nan=False)
    r_max: int = Field(ge=0, alias="R_max")

    @model_validator(mode="after")
    def validate_node_count(self) -> Self:
        if self.n0 != len(self.nodes):
            raise ValueError("n0 must equal the number of entries in nodes")
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        path = Path(path)
        data = path.read_bytes()
        try:
            return cls.model_validate_json(data)
        except ValidationError as exc:
            raise ValueError(f"Invalid cluster configuration in {path}: {exc}") from None

    @classmethod
    def from_env(cls) -> Self:
        path = os.getenv("CONFIG_PATH")
        if not path or not path.strip():
            raise RuntimeError("Set CONFIG_PATH to the path of the cluster configuration file")
        return cls.from_file(path)
