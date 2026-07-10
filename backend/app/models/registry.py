"""Pydantic models for the cleaned cerevi-server registry (`metadata/specimens.json`).

The registry is composition-only: every field that can be expressed as standard
OME-Zarr v0.5 metadata lives in upstream `zarr.json` files, not here. What stays
here is identity, file lists, and per-mode routing tables that compose the
upstream multiscales into a single virtual pyramid per access mode.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

# Routing row: [file_idx, level_indices, channels_or_regions]
#   file_idx          — index into the variant's `files[]`.
#   level_indices     — list parallel to that file's internal multiscale levels;
#                        each entry is the *global* pyramid level it surfaces as,
#                        or -1 to skip.
#   channels_or_regions — channel indices (image/region_mask) or region names
#                          (mesh) covered by that file.
RoutingRow = tuple[int, list[int], list[int | str]]


class Modes(BaseModel):
    """Per-axis routing tables. xy/xz/yz may be empty (e.g. for meshes)."""

    model_config = ConfigDict(extra="forbid")

    three_d: list[RoutingRow] = Field(default_factory=list, alias="3d")
    xy: list[RoutingRow] = Field(default_factory=list)
    xz: list[RoutingRow] = Field(default_factory=list)
    yz: list[RoutingRow] = Field(default_factory=list)


class _VariantBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    RAS_coordinate: str = ""
    files: list[str]
    modes: Modes


class ChannelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wavelength: str
    marker: str


class ImageVariant(_VariantBase):
    pixel_format: str | None = None
    physical_size_um: tuple[float, float, float] | None = None
    origin_um: tuple[float, float, float] | None = None
    channels: list[ChannelMetadata] = Field(default_factory=list)
    resolutions_um_2d: list[tuple[float, float]] = Field(default_factory=list)
    axes_order: str | None = None
    tile_size_2d: tuple[int, int] | None = None
    tile_step_2d: float | None = None
    tile_thickness_2d: float | None = None
    tile_size_3d: tuple[int, int, int] | None = None


class RegionMaskVariant(_VariantBase):
    region_id_map: dict[str, str] = Field(default_factory=dict)


class MeshVariant(_VariantBase):
    downsample_factor: float = Field(gt=0)


class AtlasRegions(BaseModel):
    """Atlas region collection (one entry per published version)."""

    model_config = ConfigDict(extra="forbid")

    files: list[str]
    blobs: dict[str, list[tuple[int]]] = Field(default_factory=dict)


class SpecimenEntry(BaseModel):
    """A real specimen with imaging data."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["specimen"] = "specimen"
    id: str
    name: str
    species: str = ""
    description: str = ""
    atlas_reference: str | None = None
    image: dict[str, ImageVariant] = Field(default_factory=dict)
    region_mask: dict[str, RegionMaskVariant] = Field(default_factory=dict)
    mesh: dict[str, MeshVariant] = Field(default_factory=dict)


class AtlasEntry(BaseModel):
    """An atlas entry (no imaging data, but referenced by specimens)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["atlas"] = "atlas"
    id: str
    name: str
    species: str = ""
    description: str = ""
    regions: dict[str, AtlasRegions] = Field(default_factory=dict)


Entry = Annotated[SpecimenEntry | AtlasEntry, Field(discriminator="kind")]


def parse_entry(raw: dict[str, Any]) -> SpecimenEntry | AtlasEntry:
    """Discriminate by structure: presence of `regions` ⇒ atlas."""
    if "regions" in raw and "image" not in raw:
        return AtlasEntry.model_validate({**raw, "kind": "atlas"})
    return SpecimenEntry.model_validate({**raw, "kind": "specimen"})


class Registry(RootModel[dict[str, SpecimenEntry | AtlasEntry]]):
    """Top-level registry: id → entry."""

    @classmethod
    def parse(cls, raw: dict[str, dict[str, Any]]) -> "Registry":
        return cls(root={sid: parse_entry(entry) for sid, entry in raw.items()})

    def __getitem__(self, key: str) -> SpecimenEntry | AtlasEntry:
        return self.root[key]

    def __contains__(self, key: object) -> bool:
        return key in self.root

    def get(self, key: str) -> SpecimenEntry | AtlasEntry | None:
        return self.root.get(key)

    def items(self):
        return self.root.items()
