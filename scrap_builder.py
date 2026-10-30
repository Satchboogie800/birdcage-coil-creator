import tomllib

from ansys.aedt.core import Hfss

from birdcage_coil_creator.aedt.geometry import build_coil
from birdcage_coil_creator.config import CoilConfig

with open("configs/coils/bachelor_29x29.toml", "rb") as f:
    cfg = CoilConfig.model_validate(tomllib.load(f))

hfss = Hfss(
    project=cfg.env.project_name,
    design=cfg.env.design_name,
    solution_type="Modal",
    version=cfg.env.aedt_version,
    non_graphical=cfg.env.non_graphical,
    new_desktop=cfg.env.new_desktop,
)

objects = build_coil(hfss, cfg)
print(objects)

hfss.save_project()
hfss.release_desktop(close_projects=False, close_desktop=False)