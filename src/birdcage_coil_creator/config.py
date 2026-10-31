# Imports
import math
from typing import Literal
from pydantic import BaseModel, Field, computed_field, model_validator


class CoilGeometry(BaseModel):
    """
    Creates the basic coil model based on the default.toml file, later based on UI input.
    """
    n_legs: int = Field(16, ge=8)
    radius_mm: float = Field(145.0, gt=0)
    length_mm: float = Field(290.0, gt=0)        # incl. end rings
    ring_width_mm: float = Field(20.0, gt=0)     # axial
    leg_width_mm: float = Field(20.0, gt=0)      # arc length
    cap_gap_mm: float = Field(4.0, gt=0)         # along current direction
    feed_island_mm: float = Field(4.0, gt=0)     # conductor island between C1 and C2

    @computed_field
    @property
    def dphi_deg(self) -> float:
        return 360.0 / self.n_legs

    @computed_field
    @property
    def leg_gap_chord_mm(self) -> float:          # your B_BOX
        return 2 * self.radius_mm * math.sin(
            math.pi / self.n_legs - self.leg_width_mm / (2 * self.radius_mm))

    @computed_field
    @property
    def leg_length_mm(self) -> float:
        return self.length_mm - 2 * self.ring_width_mm

    @model_validator(mode="after")
    def _check(self):
        if self.n_legs % 2:
            raise ValueError("n_legs must be even")
        if self.leg_length_mm <= 0:
            raise ValueError("rings wider than coil length")
        if self.feed_island_mm + 2 * self.cap_gap_mm >= self.leg_gap_chord_mm:
            raise ValueError("feed region wider than the leg gap")
        return self


class Conductor(BaseModel):
    kind: Literal["pec", "finite", "layered"] = "pec"
    material: str = "copper"          # replaces conductivity_S_per_m
    thickness_um: float = 35.0        # only used for "layered"


class AirRegion(BaseModel):
    cylinder_margin_radial_mm: float = 50.0
    cylinder_margin_axial_mm: float = 100.0
    cylinder_segments: int = 24       # polygon instead of a true circle (coarser surface mesh)
    boundary: Literal["radiation", "pml"] = "radiation"
    boundary_distance_mm: float = 1200.0


class Capacitors(BaseModel):
    c_ring_pF: float = Field(105.0, gt=0)
    n: float = Field(1.0, gt=0)                   # matching ratio C2/C1

    @computed_field
    @property
    def c1_pF(self) -> float:
        return self.c_ring_pF * (1 + self.n) / self.n

    @computed_field
    @property
    def c2_pF(self) -> float:
        return self.c_ring_pF * (1 + self.n)


class Feeds(BaseModel):
    angles_deg: list[float] = [0.0, 90.0]
    ring: Literal["Bot", "Top"] = "Bot"
    impedance_ohm: float = 50.0

class ProbeSettings(BaseModel):
    radius_fraction: float = Field(0.4, gt=0, lt=1)   # probe cylinder radius / coil radius
    height_fraction: float = Field(0.4, gt=0, lt=1)   # probe cylinder height / coil length

class MeshSettings(BaseModel):
    gap_max_mm: float | None = None               # default: cap_gap / 2
    conductor_max_mm: float | None = None         # default: leg_width / 2
    air_cylinder_max_mm: float = 40.0


class Environment(BaseModel):
    aedt_version: str = "2023.2"
    project_name: str = "Birdcage_scripted"
    design_name: str = "HP_Birdcage"
    non_graphical: bool = False
    new_desktop: bool = False
    cores: int = 4


class CoilConfig(BaseModel):
    geometry: CoilGeometry = Field(default_factory=CoilGeometry)
    conductor: Conductor = Field(default_factory=Conductor)
    capacitors: Capacitors = Field(default_factory=Capacitors)
    feeds: Feeds = Field(default_factory=Feeds)
    air: AirRegion = Field(default_factory=AirRegion)
    mesh: MeshSettings = Field(default_factory=MeshSettings)
    probe: ProbeSettings = Field(default_factory=ProbeSettings)   # NEW
    env: Environment = Field(default_factory=Environment)

    @model_validator(mode="after")
    def _feeds_on_gaps(self):
        d = self.geometry.dphi_deg
        for a in self.feeds.angles_deg:
            if abs(a / d - round(a / d)) > 1e-9:
                raise ValueError(f"feed angle {a}° is not a multiple of {d}°")
        return self