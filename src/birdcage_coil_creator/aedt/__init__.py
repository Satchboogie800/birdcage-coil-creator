from ansys.aedt.core import Hfss

with Hfss(version="2023.2", non_graphical=False, new_desktop=True) as hfss:
    print(hfss.design_name)