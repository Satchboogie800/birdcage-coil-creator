"""Build the birdcage coil geometry in HFSS from a CoilConfig."""

import math
from dataclasses import dataclass, field

from ansys.aedt.core import Hfss

from birdcage_coil_creator.config import CoilConfig, SolutionKind


# ----------------------------------------------------------------------------
# Result: names of everything that was created
# ----------------------------------------------------------------------------
@dataclass
class CoilObjects:
    conductor: str = ""
    cap_sheets: list[str] = field(default_factory=list)
    port_sheets: list[str] = field(default_factory=list)
    port_names: list[str] = field(default_factory=list)
    port_lines: list[list[list[float]]] = field(default_factory=list)   # NEW
    air_cylinder: str = ""
    region: str = ""
    probe_region: str = ""                                             # NEW
    probe_center: str = ""

    @property
    def gap_sheets(self) -> list[str]:
        """All sheets in the ring gaps (capacitors + ports), for mesh refinement."""
        return self.cap_sheets + self.port_sheets


# ----------------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------------
class CoilBuilder:
    """Creates the coil step by step in an open HFSS design."""

    def __init__(self, hfss: Hfss, cfg: CoilConfig, solution:SolutionKind):
        self.hfss = hfss
        self.cfg = cfg
        self.solution = solution
        self.geo = cfg.geometry           # shortcut, used everywhere
        self.objects = CoilObjects()
        self._tools = []                  # objects that get cut out of the conductor
        self._cap_jobs = []               # (sheet, integration line, capacitor variable)

    # ---------------- main sequence ----------------
    def build(self) -> CoilObjects:
        self.hfss.modeler.model_units = "mm"
        self._set_design_variables()
        self._create_conductor()
        self._cut_legs()
        self._cut_ring_gaps()
        self.hfss.modeler.subtract(self.objects.conductor, self._tools, keep_originals=False)
        self._assign_conductor_boundary()
        self._assign_capacitors()
        self._create_air()
        self._create_probes()
        return self.objects

    # ---------------- design variables ----------------
    def _set_design_variables(self):
        caps = self.cfg.capacitors
        self.hfss["C_ring"] = f"{caps.c_ring_pF}pF"
        self.hfss["n"] = f"{caps.n}"
        self.hfss["C1"] = "C_ring*(1+n)/n"     # C1 and C2 in series = C_ring
        self.hfss["C2"] = "C1*n"
        self.hfss["coilHeight"] = f"{self.geo.length_mm}mm"
        self.hfss["coilRadius"] = f"{self.geo.radius_mm}mm"

    # ---------------- geometry helpers ----------------
    def _pt(self, theta_deg, y, z):
        """Point on the cylinder at frame angle theta, chord offset y, height z."""
        r = self.geo.radius_mm
        phi = math.radians(theta_deg) + math.asin(y / r)
        return [r * math.cos(phi), r * math.sin(phi), z]

    def _half_box(self, name, theta, y1, y2, z0, h):
        """Box that cuts the cylinder on one side only."""
        box = self.hfss.modeler.create_box(
            [0, y1, z0], [1.5 * self.geo.radius_mm, y2 - y1, h], name=name
        )
        self.hfss.modeler.rotate(box, "Z", theta)
        return box

    def _gap_sheet(self, name, theta, y1, y2, z0, h):
        """Curved sheet exactly filling a gap between offsets y1..y2."""
        pts = [self._pt(theta, y, z0) for y in (y1, 0.5 * (y1 + y2), y2)]
        arc = self.hfss.modeler.create_polyline(pts, segment_type="Arc", name=name)
        self.hfss.modeler.sweep_along_vector(arc, [0, 0, h])
        return arc

    def _int_line(self, theta, y1, y2, z):
        """Integration line across the gap, along the ring current."""
        return [self._pt(theta, y1, z), self._pt(theta, y2, z)]

    # ---------------- conductor ----------------
    def _create_conductor(self):
        circ = self.hfss.modeler.create_circle(
            "XY", [0, 0, 0], self.geo.radius_mm, is_covered=False, name="Coil"
        )
        self.hfss.modeler.sweep_along_vector(circ, [0, 0, self.geo.length_mm])
        self.objects.conductor = circ.name

    def _cut_legs(self):
        """N/2 boxes through the axis give N gaps between the legs."""
        g = self.geo
        for k in range(g.n_legs // 2):
            box = self.hfss.modeler.create_box(
                [-1.5 * g.radius_mm, -g.leg_gap_chord_mm / 2, g.ring_width_mm],
                [3 * g.radius_mm, g.leg_gap_chord_mm, g.leg_length_mm],
                name=f"LegCut{k}",
            )
            self.hfss.modeler.rotate(box, "Z", k * g.dphi_deg)
            self._tools.append(box)

    def _cut_ring_gaps(self):
        g = self.geo
        # leg index -> port name, e.g. {0: "Feed1", 4: "Feed2"}
        feed_ports = {
            round(a / g.dphi_deg) % g.n_legs: f"Feed{i + 1}"
            for i, a in enumerate(self.cfg.feeds.angles_deg)
        }
        rings = {"Bot": 0.0, "Top": g.length_mm - g.ring_width_mm}

        for ring, z0 in rings.items():
            for k in range(g.n_legs):
                if ring == self.cfg.feeds.ring and k in feed_ports:
                    self._add_feed(ring, k, z0, feed_ports[k])
                else:
                    self._add_cap_gap(ring, k, z0)

    def _add_cap_gap(self, ring, k, z0):
        """Normal ring gap with one capacitor C_ring."""
        g = self.geo
        th, w = k * g.dphi_deg, g.ring_width_mm
        y1, y2 = -g.cap_gap_mm / 2, g.cap_gap_mm / 2
        self._tools.append(self._half_box(f"Cut_{ring}{k}", th, y1, y2, z0 - 1, w + 2))
        s = self._gap_sheet(f"C_{ring}{k}", th, y1, y2, z0, w)
        self._cap_jobs.append((s, self._int_line(th, y1, y2, z0 + w / 2), "C_ring"))

    def _add_feed(self, ring, k, z0, port_name):
        """Feed gap: C1 gap, conductor island, C2 gap (C2 and port side by side)."""
        g = self.geo
        th, w = k * g.dphi_deg, g.ring_width_mm
        a1, a2 = -(g.feed_island_mm / 2 + g.cap_gap_mm), -g.feed_island_mm / 2   # C1 gap
        b1, b2 = g.feed_island_mm / 2, g.feed_island_mm / 2 + g.cap_gap_mm       # C2 gap

        self._tools.append(self._half_box(f"Cut_C1_{ring}{k}", th, a1, a2, z0 - 1, w + 2))
        self._tools.append(self._half_box(f"Cut_C2_{ring}{k}", th, b1, b2, z0 - 1, w + 2))

        s1 = self._gap_sheet(f"C1_{ring}{k}", th, a1, a2, z0, w)
        self._cap_jobs.append((s1, self._int_line(th, a1, a2, z0 + w / 2), "C1"))

        # port on the outer half of the ring (away from the legs), C2 on the inner half
        if ring == "Bot":
            port_z, c2_z = z0, z0 + w / 2
        else:
            port_z, c2_z = z0 + w / 2, z0

        sp = self._gap_sheet(f"{port_name}_sheet", th, b1, b2, port_z, w / 2)
        self.objects.port_sheets.append(sp.name)
        self.objects.port_names.append(port_name)
        self.objects.port_lines.append(self._int_line(th, b1, b2, port_z + w / 4))


        s2 = self._gap_sheet(f"C2_{ring}{k}", th, b1, b2, c2_z, w / 2)
        self._cap_jobs.append((s2, self._int_line(th, b1, b2, c2_z + w / 4), "C2"))

    # ---------------- boundaries and excitations ----------------
    def _assign_conductor_boundary(self):
        c = self.cfg.conductor
        name = self.objects.conductor
        if c.kind == "pec":
            self.hfss.assign_perfecte_to_sheets(name, name="PEC_Coil")
        elif c.kind == "finite":
            self.hfss.assign_finite_conductivity(name, material=c.material, name="Cond_Coil")
        else:  # "layered": finite conductivity with a physical thickness
            self.hfss.assign_finite_conductivity(
                name, material=c.material, use_thickness=True,
                thickness=f"{c.thickness_um}um", name="Cond_Coil",
            )

    def _assign_capacitors(self):
        c_start = self.cfg.capacitors.c_ring_pF * 1e-12
        for sheet, line, var in self._cap_jobs:
            bnd = self.hfss.assign_lumped_rlc_to_sheet(
                sheet.name, start_direction=line, rlc_type="Parallel",
                capacitance=c_start, name=f"RLC_{sheet.name}",
            )
            bnd.props["Capacitance"] = var      # link to the design variable
            bnd.update()
            self.objects.cap_sheets.append(sheet.name)

    def _create_probes(self):
        """Central probe region and centre point for mode classification (non-model)."""
        g, p = self.geo, self.cfg.probe
        r = p.radius_fraction * g.radius_mm
        h = p.height_fraction * g.length_mm
        z_mid = g.length_mm / 2

        region = self.hfss.modeler.create_cylinder(
            orientation="Z", origin=[0, 0, z_mid - h / 2],
            radius=r, height=h, num_sides=16, name="ProbeRegion",
        )
        region.model = False  # helper object: not part of the simulation
        self.objects.probe_region = region.name

        center = self.hfss.modeler.create_point([0, 0, z_mid], name="ProbeCenter")
        self.objects.probe_center = center.name

    # ---------------- air ----------------
    def _create_air(self):
        a, g = self.cfg.air, self.geo
        cyl = self.hfss.modeler.create_cylinder(
            orientation="Z",
            origin=[0, 0, -a.cylinder_margin_axial_mm],
            radius=g.radius_mm + a.cylinder_margin_radial_mm,
            height=g.length_mm + 2 * a.cylinder_margin_axial_mm,
            num_sides=a.cylinder_segments,
            name="AirCylinder",
            material="vacuum",
        )
        self.objects.air_cylinder = cyl.name


        if self.solution == "eigenmode":
            d = a.eigenmode_distance_mm
        else:
            d = a.driven_distance_mm
        region = self.hfss.modeler.create_air_region(
            x_pos=d, y_pos=d, z_pos=d, x_neg=d, y_neg=d, z_neg=d, is_percentage=False
        )
        self.objects.region = region.name
        if self.solution == "driven":
            if a.driven_boundary != "radiation":
                raise NotImplementedError(f"Boundary '{a.driven_boundary}' is not implemented yet")
            self.hfss.assign_radiation_boundary_to_objects(region.name, name="Rad")

# ----------------------------------------------------------------------------
# Convenience function
# ----------------------------------------------------------------------------
def build_coil(hfss: Hfss, cfg: CoilConfig, solution: SolutionKind) -> CoilObjects:
    """Build the complete coil for the given solution type and return the object names."""
    objects = CoilBuilder(hfss, cfg, solution).build()
    if solution == "driven":
        assign_ports(hfss, cfg, objects)
    return objects


def assign_ports(hfss: Hfss, cfg: CoilConfig, objects: CoilObjects) -> None:
    """Driven design: turn the port sheets into lumped ports."""
    for sheet, line, name in zip(objects.port_sheets, objects.port_lines, objects.port_names):
        hfss.lumped_port(
            assignment=sheet, create_port_sheet=False, integration_line=line,
            impedance=cfg.feeds.impedance_ohm, name=name, renormalize=True,
        )


def terminate_ports_with_resistors(hfss: Hfss, cfg: CoilConfig, objects: CoilObjects) -> None:
    """Eigenmode design (optional): load the port positions with 50 Ω instead of leaving them open."""
    for sheet, line, name in zip(objects.port_sheets, objects.port_lines, objects.port_names):
        hfss.assign_lumped_rlc_to_sheet(
            sheet, start_direction=line, rlc_type="Parallel",
            resistance=cfg.feeds.impedance_ohm, name=f"R_{name}",
        )