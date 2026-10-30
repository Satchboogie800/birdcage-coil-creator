from nicegui import ui

ui.label("Birdcage Coil Creator")
ui.button("Test", on_click=lambda: ui.notify("works"))

ui.run(native=True, title="Birdcage Coil Creator", reload=False)