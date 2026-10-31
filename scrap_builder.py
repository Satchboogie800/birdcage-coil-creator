import tomllib

from ansys.aedt.core import Hfss

from birdcage_coil_creator.aedt.geometry import build_coil
from birdcage_coil_creator.config import CoilConfig

with open("configs/coils/test_coil.toml", "rb") as f:
    cfg = CoilConfig.model_validate(tomllib.load(f))

SOLUTION = "eigenmode"           # "eigenmode" or "driven"

HFSS_SOLUTION = {"eigenmode": "Eigenmode", "driven": "Modal"}[SOLUTION]
suffix = "Eig" if SOLUTION == "eigenmode" else "Drv"

hfss = Hfss(
    project=cfg.env.project_name,
    design=f"{cfg.env.design_name}_{suffix}",
    solution_type=HFSS_SOLUTION,
    version=cfg.env.aedt_version,
    non_graphical=cfg.env.non_graphical,
    new_desktop=cfg.env.new_desktop,
)

try:
    objects = build_coil(hfss, cfg, SOLUTION)
    print(objects)
    hfss.save_project()
finally:
    hfss.release_desktop(close_projects=False, close_desktop=False)